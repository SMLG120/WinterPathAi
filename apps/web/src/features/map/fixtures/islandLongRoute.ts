/**
 * TEST FIXTURE — not real data, not a real outline, not a computed route.
 *
 * Used by the mock build (MSW, fixtures/handlers.ts) when localStorage `wp-mock-fixture` = `island-long`, to exercise
 * the map with (a) a multi-part coverage area (MultiPolygon, a future contract shape) and (b) a long
 * cross-region route (~25 km, Downtown → Pointe-Claire area). Shapes are hand-drawn approximations;
 * every explanation is evidence_state "simulated" so the UI labels the result SIMULATED.
 */
import type { Coverage, Route, RouteCompareResponse } from '@/api/types';
import { LONG_A, LONG_B } from './islandPoints';

export { LONG_A, LONG_B };

export const FIXTURE_FLAG = 'wp-mock-fixture';
export const ISLAND_LONG = 'island-long';

/** Same bbox the island build uses (docs/ISLAND_COVERAGE.md: VITE_COVERAGE_BBOX). */
export const ISLAND_BBOX = [-73.97, 45.401, -73.477, 45.707] as const;

/** Hand-drawn, coarse: a main "island" polygon with one hole, plus a separate small polygon. */
export const ISLAND_AREA = {
  type: 'MultiPolygon' as const,
  coordinates: [
    [
      [
        [-73.95, 45.44],
        [-73.83, 45.41],
        [-73.66, 45.41],
        [-73.53, 45.5],
        [-73.48, 45.63],
        [-73.5, 45.7],
        [-73.6, 45.66],
        [-73.75, 45.53],
        [-73.88, 45.5],
        [-73.95, 45.48],
        [-73.95, 45.44],
      ],
      [
        [-73.64, 45.47],
        [-73.62, 45.47],
        [-73.62, 45.48],
        [-73.64, 45.48],
        [-73.64, 45.47],
      ],
    ],
    [
      [
        [-73.92, 45.49],
        [-73.88, 45.49],
        [-73.88, 45.52],
        [-73.92, 45.52],
        [-73.92, 45.49],
      ],
    ],
  ],
};


export function islandCoverage(): Coverage {
  return {
    pilot_name: 'TEST FIXTURE: island-wide coverage (hand-drawn shape, not the real outline)',
    bbox: [...ISLAND_BBOX],
    // MultiPolygon is not in contract v1.8 (Polygon only); this fixture exercises the future shape.
    area: ISLAND_AREA as unknown as Coverage['area'],
    graph: { node_count: 0, edge_count: 0, built_at: null, osm_snapshot: null },
    known_gaps: [{ description: 'TEST FIXTURE: no network data; routes are synthetic lines.', geometry: null }],
  };
}

type Pos = [number, number];

/** A zig-zag line through the given waypoints, densified so it looks like a street route. */
function densify(points: Pos[], steps = 12): Pos[] {
  const out: Pos[] = [];
  for (let i = 1; i < points.length; i++) {
    const [a, b] = [points[i - 1]!, points[i]!];
    for (let k = 0; k < steps; k++) {
      const f = k / steps;
      const x = a[0] + (b[0] - a[0]) * f;
      const y = a[1] + (b[1] - a[1]) * f;
      out.push(k % 2 ? [x, y + 0.0004] : [x, y]);
    }
  }
  out.push(points[points.length - 1]!);
  return out;
}

function lengthM(c: Pos[]): number {
  let m = 0;
  for (let i = 1; i < c.length; i++) {
    const [a, b] = [c[i - 1]!, c[i]!];
    const lat = (((a[1] + b[1]) / 2) * Math.PI) / 180;
    m += Math.hypot(((b[0] - a[0]) * Math.PI * 6_371_000 * Math.cos(lat)) / 180, ((b[1] - a[1]) * Math.PI * 6_371_000) / 180);
  }
  return m;
}

function route(variant: Route['variant'], via: Pos[], unknown: number, locale: 'en' | 'fr', now: Date): Route {
  const o: Pos = [LONG_A.lon, LONG_A.lat];
  const d: Pos = [LONG_B.lon, LONG_B.lat];
  const coords = densify([o, ...via, d]);
  const dist = Math.round(lengthM(coords));
  const text =
    locale === 'fr'
      ? 'Trajet synthétique de test (fixture) — aucune condition réelle évaluée.'
      : 'Synthetic test route (fixture) — no real conditions were evaluated.';
  return {
    variant,
    geometry: { type: 'LineString', coordinates: coords },
    distance_m: dist,
    duration_s: Math.round(dist / 1.3),
    edge_ids: [],
    unknown_share: unknown,
    hazards_avoided: [],
    hazards_on_route: [],
    explanation: [{ code: 'SIMULATED_DATA', text, evidence_state: 'simulated' }],
    steps: [{ instruction: text, distance_m: dist, street_name: null }],
    data_freshness: { 'demo-fixture': now.toISOString() },
  };
}

export function islandLongCompare(locale: 'en' | 'fr' = 'en', now = new Date()): RouteCompareResponse {
  return {
    request_id: 'fixture-island-long',
    routes: [
      route('shortest', [[-73.62, 45.483], [-73.7, 45.46], [-73.76, 45.452]], 0.7, locale, now),
      route('winter_aware', [[-73.6, 45.49], [-73.68, 45.475], [-73.75, 45.46]], 0.43, locale, now),
    ],
    identical: false,
    risk_layer: 'heuristic',
    computed_at: now.toISOString(),
    warnings: [locale === 'fr' ? 'Fixture de test : trajets synthétiques.' : 'Test fixture: synthetic routes.'],
  };
}
