// @vitest-environment node
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { setupServer } from 'msw/node';
import { contractValidator } from '@/test/openapi';
import { handlers, resetMockState } from './handlers';
import * as fx from './fixtures';
import { mockCompare } from './routes';

const v = contractValidator();
const server = setupServer(...handlers);
const BASE = 'http://localhost/api/v1';
const IN_A = { lon: -73.5772, lat: 45.5048 };
const IN_B = { lon: -73.5698, lat: 45.5017 };

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterAll(() => server.close());
beforeEach(() => resetMockState());

const parse = async (r: Response) => {
  const text = await r.text();
  return text ? JSON.parse(text) : null;
};
const get = async (p: string) => {
  const r = await fetch(`${BASE}${p}`);
  return { status: r.status, body: await parse(r) };
};
const post = async (p: string, body: unknown, headers: Record<string, string> = {}) => {
  const r = await fetch(`${BASE}${p}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });
  return { status: r.status, headers: r.headers, body: await parse(r) };
};

describe('mock payloads validate against docs/contracts/openapi.yaml', () => {
  it.each([
    ['/health', 'Health'],
    ['/coverage', 'Coverage'],
    ['/weather/current', 'WeatherCurrent'],
    ['/weather/forecast?hours=24', 'WeatherForecast'],
    ['/models/status', 'ModelStatus'],
    ['/hazards?bbox=-73.588,45.496,-73.562,45.513', 'HazardCollection'],
    ['/map/segments?bbox=-73.588,45.496,-73.562,45.513', 'SegmentCollection'],
  ])('GET %s → %s', async (path, schema) => {
    const { status, body } = await get(path);
    expect(status).toBe(200);
    expect(v(schema, body)).toEqual([]);
  });

  it('GET /data-sources → DataSource[]', async () => {
    const { body } = await get('/data-sources');
    expect(Array.isArray(body)).toBe(true);
    for (const s of body as unknown[]) expect(v('DataSource', s)).toEqual([]);
  });

  it('POST /routes/compare (200) → RouteCompareResponse, both locales', async () => {
    for (const locale of ['en', 'fr'] as const) {
      const { status, body } = await post('/routes/compare', { origin: IN_A, destination: IN_B, profile: 'standard', locale });
      expect(status).toBe(200);
      expect(v('RouteCompareResponse', body)).toEqual([]);
    }
  });

  it('POST /routes/compare outside pilot → 422 OUTSIDE_COVERAGE Error', async () => {
    const { status, body } = await post('/routes/compare', { origin: { lon: -73.62, lat: 45.52 }, destination: IN_B });
    expect(status).toBe(422);
    expect(body.code).toBe('OUTSIDE_COVERAGE');
    expect(v('Error', body)).toEqual([]);
  });

  it('POST /routes/compare step_free → 404 NO_ROUTE (no edge verified step-free in demo)', async () => {
    const { status, body } = await post('/routes/compare', { origin: IN_A, destination: IN_B, profile: 'step_free' });
    expect(status).toBe(404);
    expect(body.code).toBe('NO_ROUTE');
  });

  it('bbox too large → 422 BBOX_TOO_LARGE', async () => {
    const { status, body } = await get('/hazards?bbox=-73.7,45.4,-73.5,45.6');
    expect(status).toBe(422);
    expect(body.code).toBe('BBOX_TOO_LARGE');
  });

  it('report lifecycle: create → receipt schema → admin list → moderate → delete; rate limit 429', async () => {
    const created = await post('/reports', { category: 'ice', location: IN_A, location_consent: true, description: 'test', locale: 'en' });
    expect(created.status).toBe(201);
    expect(v('ReportReceipt', created.body)).toEqual([]);
    expect(created.body.deletion_token.length).toBeGreaterThanOrEqual(32);

    expect((await get('/admin/reports')).status).toBe(401);
    const auth = { Authorization: 'Bearer demo-admin-token' };
    const list = await fetch(`${BASE}/admin/reports?status=pending`, { headers: auth }).then((r) => r.json());
    expect(list.items).toHaveLength(1);
    for (const it of list.items) expect(v('ReportAdminView', it)).toEqual([]);
    const mod = await post(`/admin/reports/${created.body.id}/moderation`, { decision: 'approve' }, auth);
    expect(v('ReportAdminView', mod.body)).toEqual([]);
    expect(mod.body.status).toBe('approved');

    const badDel = await fetch(`${BASE}/reports/${created.body.id}`, { method: 'DELETE', headers: { 'X-Deletion-Token': 'x'.repeat(32) } });
    expect(badDel.status).toBe(404);
    const del = await fetch(`${BASE}/reports/${created.body.id}`, { method: 'DELETE', headers: { 'X-Deletion-Token': created.body.deletion_token } });
    expect(del.status).toBe(204);

    for (let i = 0; i < 4; i++) await post('/reports', { category: 'snow', location: IN_A, location_consent: true });
    const limited = await post('/reports', { category: 'snow', location: IN_A, location_consent: true });
    expect(limited.status).toBe(429);
    expect(limited.headers.get('Retry-After')).toBe('600');
  }, 30_000);

  it('pilot request: 201 with consent, 422 without', async () => {
    const ok = await fetch(`${BASE}/pilot-requests`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ organization: 'Org', contact_email: 'a@example.org', segment: 'university', consent: true }),
    });
    expect(ok.status).toBe(201);
    const bad = await post('/pilot-requests', { organization: 'Org', contact_email: 'a@example.org', segment: 'university', consent: false });
    expect(bad.status).toBe(422);
  });
});

describe('mock honesty invariants', () => {
  const now = new Date();
  it('every hazard and risk datum is simulated or unknown — never confirmed', () => {
    for (const h of fx.hazards(now)) expect(h.properties.evidence.state).toBe('simulated');
    for (const s of fx.segments(now)) expect(['simulated', 'unknown']).toContain(s.properties.risk.evidence.state);
  });
  it('unknown risk level always carries unknown evidence (never low)', () => {
    for (const s of fx.segments(now)) {
      if (s.properties.risk.level === 'unknown') expect(s.properties.risk.evidence.state).toBe('unknown');
      expect(s.properties.accessibility.step_free).toBeNull();
    }
  });
  it('no ECCC alert is fabricated', () => {
    expect(fx.weatherForecast(now).alerts).toEqual([]);
  });
  it('model is disabled with no invented evaluation metrics', () => {
    const m = fx.modelStatus();
    expect(m.enabled).toBe(false);
    expect(m.evaluation).toBeNull();
  });
  it('coverage claims no graph in demo mode', () => {
    const c = fx.coverage();
    expect(c.graph.node_count).toBe(0);
    expect(c.graph.built_at).toBeNull();
    expect(c.known_gaps.length).toBeGreaterThan(0);
  });
  it('route explanations are labelled simulated/unknown', () => {
    const r = mockCompare({ origin: IN_A, destination: IN_B });
    if (r.status !== 200) throw new Error('expected 200');
    for (const route of r.body.routes) for (const e of route.explanation) expect(['simulated', 'unknown']).toContain(e.evidence_state);
  });
  it('sources are not reported as active in demo', () => {
    for (const s of fx.dataSources()) {
      expect(s.status).not.toBe('active');
      expect(s.last_success_at).toBeNull();
    }
  });
});
