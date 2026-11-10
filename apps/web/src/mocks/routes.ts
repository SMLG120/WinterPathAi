/**
 * Mock /routes/compare. Produces two obviously synthetic L-shaped paths; all
 * explanations are evidence_state "simulated". NOT a routing algorithm — the
 * real API (services/api) is the only place routes are computed.
 */
import type { ApiError, Route, RouteCompareRequest, RouteCompareResponse } from '@/api/types';
import { isInPilot } from '@/lib/geo';
import { DEMO_SOURCE_ID } from './fixtures';
import { lineLength, type Pos } from './geo-mock';

export type MockResult = { status: 200; body: RouteCompareResponse } | { status: 404 | 422; body: ApiError };

const T = {
  en: {
    sim: 'Simulated demo explanation — no real conditions were evaluated.',
    unknown: 'Part of this route has no condition data (unknown, not zero risk).',
    closure: 'Avoids a simulated sidewalk closure shown on the demo map.',
    shortest: 'Shortest-distance baseline.',
    step: (s: string) => `Walk along ${s}`,
    arrive: 'Arrive at destination',
    turn: 'Turn at the corner',
    noRoute: 'No step-free path: the demo fixture has no edge with verified step-free status.',
    outside: 'Origin or destination is outside the pilot coverage area.',
  },
  fr: {
    sim: 'Explication de démonstration simulée — aucune condition réelle évaluée.',
    unknown: 'Une partie de ce trajet n’a aucune donnée d’état (inconnu, pas « sans risque »).',
    closure: 'Évite une fermeture de trottoir simulée affichée sur la carte de démo.',
    shortest: 'Référence : distance la plus courte.',
    step: (s: string) => `Marchez le long de ${s}`,
    arrive: 'Arrivée à destination',
    turn: 'Tournez au coin',
    noRoute: 'Aucun trajet sans marche : la démo ne contient aucun tronçon dont l’absence de marche est vérifiée.',
    outside: 'Le départ ou l’arrivée est hors de la zone pilote.',
  },
};

function buildRoute(
  variant: Route['variant'],
  coords: Pos[],
  speed: number,
  locale: 'en' | 'fr',
  unknownShare: number,
  now: Date,
): Route {
  const t = T[locale];
  const distance = lineLength(coords);
  const legs = coords.slice(1).map((c, i) => lineLengthPair(coords[i]!, c));
  return {
    variant,
    geometry: { type: 'LineString', coordinates: coords },
    distance_m: Math.round(distance),
    duration_s: Math.round(distance / speed),
    generalized_cost_s: Math.round(distance / speed),
    edge_ids: coords.slice(1).map((_, i) => `demo-route-${variant}-${i}`),
    unknown_share: unknownShare,
    hazards_avoided: variant === 'winter_aware' ? ['demo-hz-1'] : [],
    hazards_on_route: [],
    explanation: [
      { code: 'SIMULATED_DEMO', text: t.sim, evidence_state: 'simulated' },
      variant === 'winter_aware'
        ? { code: 'AVOIDS_SIMULATED_CLOSURE', text: t.closure, evidence_state: 'simulated' }
        : { code: 'SHORTEST_BASELINE', text: t.shortest, evidence_state: 'simulated' },
      { code: 'UNKNOWN_CONDITIONS', text: t.unknown, evidence_state: 'unknown' },
    ],
    steps: [
      ...legs.map((d, i) => ({
        instruction: i === 0 ? t.step(locale === 'fr' ? 'la rue de démo A' : 'Demo Street A') : t.turn,
        distance_m: Math.round(d),
        street_name: i === 0 ? (locale === 'fr' ? 'Rue de démo A' : 'Demo Street A') : null,
      })),
      { instruction: t.arrive, distance_m: 0, street_name: null },
    ],
    data_freshness: { [DEMO_SOURCE_ID]: now.toISOString() },
  };
}

const lineLengthPair = (a: Pos, b: Pos) => lineLength([a, b]);

export function mockCompare(req: RouteCompareRequest, now = new Date()): MockResult {
  const locale = req.locale ?? 'en';
  const t = T[locale];
  if (!isInPilot(req.origin) || !isInPilot(req.destination)) {
    return { status: 422, body: { code: 'OUTSIDE_COVERAGE', message: t.outside, request_id: 'mock' } };
  }
  if (req.profile === 'step_free') {
    return { status: 404, body: { code: 'NO_ROUTE', message: t.noRoute, request_id: 'mock' } };
  }
  const o: Pos = [req.origin.lon, req.origin.lat];
  const d: Pos = [req.destination.lon, req.destination.lat];
  const speed = req.profile === 'reduced_mobility' ? 0.9 : 1.3;
  const shortest = buildRoute('shortest', [o, [d[0], o[1]], d], speed, locale, 0.4, now);
  const winter = buildRoute('winter_aware', [o, [o[0], d[1]], d], speed, locale, 0.25, now);
  return {
    status: 200,
    body: {
      request_id: `mock-${now.getTime()}`,
      routes: [shortest, winter],
      identical: false,
      risk_layer: 'none',
      computed_at: now.toISOString(),
      warnings: [locale === 'fr' ? 'Données de démonstration simulées.' : 'Simulated demo data.'],
    },
  };
}
