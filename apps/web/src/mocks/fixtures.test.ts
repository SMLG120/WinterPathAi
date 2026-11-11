// @vitest-environment node
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { setupServer } from 'msw/node';
import { contractValidator } from '@/test/openapi';
import { PTS } from '@/test/pilotPoints';
import { handlers, resetMockState } from './handlers';
import * as fx from './fixtures';
import { mockCompare } from './routes';
import { haversineM, nearestLineM, pointSegmentM } from './geo-mock';
import { isInPilot } from '@/lib/geo';
import { pilotMiniSegments, PILOT_MINI } from './pilotMini';
import edgesRaw from '../../../../data/fixtures/pilot_mini/edges.geojson?raw';

const v = contractValidator();
const server = setupServer(...handlers);
const BASE = 'http://localhost/api/v1';
// Derived from the checked-out pilot_mini fixture (inside pilot bbox; OFF_NET outside the network).
const { A: IN_A, B: IN_B, OFF_NET } = PTS;

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

  it('POST /routes/compare far from the real network → 422 OFF_NETWORK with snap details (v1.3)', async () => {
    const { status, body } = await post('/routes/compare', { origin: IN_A, destination: OFF_NET, locale: 'fr' });
    expect(status).toBe(422);
    expect(v('Error', body)).toEqual([]);
    expect(body.code).toBe('OFF_NETWORK');
    expect(body.details).toMatchObject({ which: 'destination', max_snap_distance_m: 75 });
    expect(body.details.nearest_network_m).toBeGreaterThan(75);
  });

  it('test points actually snap to the real pilot_mini network (≤ 75 m)', () => {
    const lines = pilotMiniSegments().map((f) => f.geometry.coordinates as [number, number][]);
    for (const p of [IN_A, IN_B]) expect(nearestLineM([p.lon, p.lat], lines)).toBeLessThanOrEqual(75);
  });

  it('derived OFF_NET point is inside the pilot bbox and well beyond the 75 m snap limit; A ≠ B', () => {
    const lines = pilotMiniSegments().map((f) => f.geometry.coordinates as [number, number][]);
    expect(nearestLineM([OFF_NET.lon, OFF_NET.lat], lines)).toBeGreaterThan(100);
    expect(isInPilot(OFF_NET)).toBe(true);
    expect(haversineM([IN_A.lon, IN_A.lat], [IN_B.lon, IN_B.lat])).toBeGreaterThan(30);
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

describe('mock geometry helper', () => {
  it('point-to-segment distance ≈ haversine scale (100 m north of a segment)', () => {
    const d = pointSegmentM([-73.575, 45.505 + 100 / 110_540], [-73.576, 45.505], [-73.574, 45.505]);
    expect(d).toBeCloseTo(100, 0);
  });
});

describe('mock honesty invariants', () => {
  const now = new Date();
  it('every hazard is simulated — never confirmed', () => {
    for (const h of fx.hazards(now)) expect(h.properties.evidence.state).toBe('simulated');
  });
  it('segments are the real pilot_mini OSM fixture (simulated=false), all 200 edges, valid per contract', () => {
    const segs = pilotMiniSegments();
    expect(PILOT_MINI.simulated).toBe(false);
    expect(segs).toHaveLength(PILOT_MINI.edgeCount);
    for (const s of segs) expect(v('SegmentFeature', s)).toEqual([]);
  });
  it('without a risk layer every segment risk is unknown (never low) and carries unknown evidence', () => {
    for (const s of pilotMiniSegments()) {
      expect(s.properties.risk.level).toBe('unknown');
      expect(s.properties.risk.evidence.state).toBe('unknown');
      expect(s.properties.risk.probability).toBeNull();
    }
  });
  it('step_free passes through from OSM unchanged — unknown stays null, never upgraded to true', () => {
    // Compared edge-by-edge with the raw fixture, so it holds whenever pilot_mini is regenerated.
    const raw = new Map(
      (JSON.parse(edgesRaw) as { features: { id: string; properties: { step_free: boolean | null } }[] }).features.map((f) => [f.id, f.properties.step_free]),
    );
    const segs = pilotMiniSegments();
    expect(segs).toHaveLength(raw.size);
    for (const s of segs) expect(s.properties.accessibility.step_free).toBe(raw.get(String(s.id)) ?? null);
  });
  it('steps edges are never marked step-free', () => {
    for (const s of pilotMiniSegments()) if (s.properties.edge_kind === 'steps') expect(s.properties.accessibility.step_free).not.toBe(true);
  });
  it('no ECCC alert is fabricated', () => {
    expect(fx.weatherForecast(now).alerts).toEqual([]);
  });
  it('model is disabled with no invented evaluation metrics', () => {
    const m = fx.modelStatus();
    expect(m.enabled).toBe(false);
    expect(m.evaluation).toBeNull();
  });
  it('coverage reports the fixture graph and declares the rest of the pilot a gap', () => {
    const c = fx.coverage();
    expect(c.graph).toMatchObject({ node_count: PILOT_MINI.nodeCount, edge_count: PILOT_MINI.edgeCount, osm_snapshot: PILOT_MINI.osmSnapshot });
    expect(PILOT_MINI.edgeCount).toBe(pilotMiniSegments().length); // metadata agrees with the edges file
    expect(c.known_gaps[0]!.description).toMatch(/only the pilot_mini fixture/);
  });
  it('route explanations are labelled simulated/unknown', () => {
    const r = mockCompare({ origin: IN_A, destination: IN_B });
    if (r.status !== 200) throw new Error('expected 200');
    for (const route of r.body.routes) for (const e of route.explanation) expect(['simulated', 'unknown']).toContain(e.evidence_state);
  });
  it('route explanation codes follow the openapi v1.5 code → evidence mapping', () => {
    // Subset of the contract's mapping (ExplanationItem description) that the demo uses.
    const mapping: Record<string, string> = {
      SIMULATED_DATA: 'simulated',
      SHORTEST_DISTANCE: 'unknown',
      RISK_LAYER_UNAVAILABLE: 'unknown',
    };
    const r = mockCompare({ origin: IN_A, destination: IN_B });
    if (r.status !== 200) throw new Error('expected 200');
    for (const route of r.body.routes) {
      for (const e of route.explanation) expect(e.evidence_state).toBe(mapping[e.code]);
    }
  });
  it('sources are not reported as active in demo', () => {
    for (const s of fx.dataSources()) {
      expect(s.status).not.toBe('active');
      expect(s.last_success_at).toBeNull();
    }
  });
});
