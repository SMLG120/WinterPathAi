import { delay, http, HttpResponse } from 'msw';
import type { ModerationStatus, ReportAdminView, ReportCreate, PilotRequest, RouteCompareRequest } from '@/api/types';
import { isInPilot } from '@/lib/geo';
import * as fx from './fixtures';
import { geomIntersectsBbox, type Pos } from './geo-mock';
import { mockCompare } from './routes';
import { pilotMiniSegments } from './pilotMini';

const BASE = '*/api/v1';
const LATENCY = 250;

const err = (status: number, code: string, message: string, headers?: Record<string, string>) =>
  HttpResponse.json({ code, message, request_id: 'mock' }, { status, headers });

function parseBbox(raw: string | null): [number, number, number, number] | 'bad' | 'large' {
  if (!raw || !/^-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?$/.test(raw)) return 'bad';
  const b = raw.split(',').map(Number) as [number, number, number, number];
  if ((b[2] - b[0]) * (b[3] - b[1]) > 0.0025) return 'large';
  return b;
}

function flatCoords(g: { type: string; coordinates: unknown }): Pos[] {
  if (g.type === 'Point') return [g.coordinates as Pos];
  if (g.type === 'LineString') return g.coordinates as Pos[];
  return (g.coordinates as Pos[][]).flat();
}

/** In-memory store for the demo session only. */
type Stored = ReportAdminView & { token: string };
const reports = new Map<string, Stored>();
let reportCount = 0;
const REPORT_RATE_LIMIT = 5;

function randomToken(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export function resetMockState() {
  reports.clear();
  reportCount = 0;
  firstCallAt = null;
}

const requireAdmin = (req: Request) => {
  const h = req.headers.get('Authorization') ?? '';
  return /^Bearer .{8,}$/.test(h);
};

/**
 * E2E-only failure switches (mock builds only; read from localStorage in the page).
 *  wp-mock-asleep-ms   — act like a sleeping free-tier host for N ms after the first API call:
 *                        HTML 503 from the "proxy", no WinterPath error body.
 *  wp-mock-writes=off  — POST /reports and /pilot-requests → 503 WRITES_DISABLED (v1.7).
 *  wp-mock-upstream    — comma list of `weather`, `compare` → 503 UPSTREAM_UNAVAILABLE.
 *  wp-mock-incomplete=compare — 200 with a truncated JSON body.
 */
const flag = (k: string): string | null => {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage.getItem(k);
  } catch {
    return null;
  }
};
let firstCallAt: number | null = null;
const upstream = (what: string) => (flag('wp-mock-upstream') ?? '').split(',').includes(what);
const upstreamDown = () => err(503, 'UPSTREAM_UNAVAILABLE', 'Upstream data source unavailable');

export const handlers = [
  http.all(`${BASE}/*`, () => {
    const asleepMs = Number(flag('wp-mock-asleep-ms'));
    if (!(asleepMs > 0)) return undefined;
    firstCallAt ??= Date.now();
    if (Date.now() - firstCallAt < asleepMs) {
      return new HttpResponse('<html><body>Service is waking up</body></html>', { status: 503, headers: { 'Content-Type': 'text/html' } });
    }
    return undefined; // awake: fall through to the real mock handlers
  }),
  http.get(`${BASE}/health`, () => HttpResponse.json(fx.health())),
  http.get(`${BASE}/coverage`, async () => {
    await delay(LATENCY);
    return HttpResponse.json(fx.coverage());
  }),
  http.get(`${BASE}/data-sources`, async () => {
    await delay(LATENCY);
    return HttpResponse.json(fx.dataSources());
  }),
  http.get(`${BASE}/weather/current`, async () => {
    if (upstream('weather')) return upstreamDown();
    await delay(LATENCY);
    return HttpResponse.json(fx.weatherCurrent(new Date()));
  }),
  http.get(`${BASE}/weather/forecast`, async ({ request }) => {
    if (upstream('weather')) return upstreamDown();
    await delay(LATENCY);
    const h = Number(new URL(request.url).searchParams.get('hours') ?? 24);
    if (!Number.isInteger(h) || h < 1 || h > 48) return err(400, 'VALIDATION_ERROR', 'hours must be 1..48');
    return HttpResponse.json(fx.weatherForecast(new Date(), h));
  }),
  http.get(`${BASE}/models/status`, async () => {
    await delay(LATENCY);
    return HttpResponse.json(fx.modelStatus());
  }),
  http.get(`${BASE}/hazards`, async ({ request }) => {
    await delay(LATENCY);
    const b = parseBbox(new URL(request.url).searchParams.get('bbox'));
    if (b === 'bad') return err(400, 'VALIDATION_ERROR', 'Invalid bbox');
    if (b === 'large') return err(422, 'BBOX_TOO_LARGE', 'Bbox exceeds 0.0025 deg²');
    const features = fx.hazards(new Date()).filter((f) => geomIntersectsBbox(flatCoords(f.geometry), b));
    return HttpResponse.json({ type: 'FeatureCollection', features, next_cursor: null });
  }),
  http.get(`${BASE}/map/segments`, async ({ request }) => {
    await delay(LATENCY);
    const b = parseBbox(new URL(request.url).searchParams.get('bbox'));
    if (b === 'bad') return err(400, 'VALIDATION_ERROR', 'Invalid bbox');
    if (b === 'large') return err(422, 'BBOX_TOO_LARGE', 'Bbox exceeds 0.0025 deg²');
    const features = pilotMiniSegments().filter((f) => geomIntersectsBbox(f.geometry.coordinates as Pos[], b));
    return HttpResponse.json({ type: 'FeatureCollection', features, next_cursor: null });
  }),
  http.post(`${BASE}/routes/compare`, async ({ request }) => {
    await delay(LATENCY * 2);
    if (upstream('compare')) return upstreamDown();
    if (flag('wp-mock-incomplete') === 'compare') {
      return new HttpResponse('{"request_id":"mock","routes":[{"variant":"shortest","geometry":', { status: 200, headers: { 'Content-Type': 'application/json' } });
    }
    const body = (await request.json()) as RouteCompareRequest;
    if (!body?.origin || !body?.destination) return err(400, 'VALIDATION_ERROR', 'origin and destination required');
    const r = mockCompare(body);
    return HttpResponse.json(r.body, { status: r.status });
  }),
  http.post(`${BASE}/reports`, async ({ request }) => {
    await delay(LATENCY);
    if (flag('wp-mock-writes') === 'off') return err(503, 'WRITES_DISABLED', 'Public writes are disabled in this deployment');
    const body = (await request.json()) as ReportCreate;
    if (reportCount >= REPORT_RATE_LIMIT) {
      return err(429, 'RATE_LIMITED', 'Too many reports from this client', { 'Retry-After': '600' });
    }
    if (body.location_consent !== true) return err(422, 'VALIDATION_ERROR', 'location_consent must be true');
    if (body.description && body.description.length > 280) return err(422, 'VALIDATION_ERROR', 'description too long');
    if (!isInPilot(body.location)) return err(422, 'OUTSIDE_COVERAGE', 'Location outside pilot area');
    reportCount++;
    const now = new Date();
    const id = crypto.randomUUID();
    const token = randomToken();
    const expires = new Date(now.getTime() + 72 * 3_600_000).toISOString();
    reports.set(id, {
      id,
      category: body.category,
      location: body.location,
      description: body.description ?? null,
      status: 'pending',
      created_at: now.toISOString(),
      expires_at: expires,
      moderated_at: null,
      moderation_note: null,
      token,
    });
    return HttpResponse.json({ id, status: 'pending', expires_at: expires, deletion_token: token }, { status: 201 });
  }),
  http.delete(`${BASE}/reports/:reportId`, async ({ params, request }) => {
    await delay(LATENCY);
    const r = reports.get(String(params.reportId));
    if (!r || r.token !== request.headers.get('X-Deletion-Token')) return err(404, 'NOT_FOUND', 'Report not found');
    reports.delete(r.id);
    return new HttpResponse(null, { status: 204 });
  }),
  http.get(`${BASE}/admin/reports`, async ({ request }) => {
    await delay(LATENCY);
    if (!requireAdmin(request)) return err(401, 'UNAUTHORIZED', 'Missing or invalid admin token');
    const status = new URL(request.url).searchParams.get('status') as ModerationStatus | null;
    const items = [...reports.values()]
      .filter((r) => !status || r.status === status)
      .map(({ token: _t, ...rest }) => rest);
    return HttpResponse.json({ items, next_cursor: null });
  }),
  http.post(`${BASE}/admin/reports/:reportId/moderation`, async ({ params, request }) => {
    await delay(LATENCY);
    if (!requireAdmin(request)) return err(401, 'UNAUTHORIZED', 'Missing or invalid admin token');
    const r = reports.get(String(params.reportId));
    if (!r) return err(404, 'NOT_FOUND', 'Report not found');
    const { decision, note } = (await request.json()) as { decision: 'approve' | 'reject' | 'expire'; note?: string };
    r.status = decision === 'approve' ? 'approved' : decision === 'reject' ? 'rejected' : 'expired';
    r.moderated_at = new Date().toISOString();
    r.moderation_note = note ?? null;
    const { token: _t, ...view } = r;
    return HttpResponse.json(view);
  }),
  http.post(`${BASE}/pilot-requests`, async ({ request }) => {
    await delay(LATENCY);
    if (flag('wp-mock-writes') === 'off') return err(503, 'WRITES_DISABLED', 'Public writes are disabled in this deployment');
    const body = (await request.json()) as PilotRequest;
    if (body.consent !== true || !body.organization || !body.contact_email) {
      return err(422, 'VALIDATION_ERROR', 'Missing required fields');
    }
    return new HttpResponse(null, { status: 201 });
  }),
];
