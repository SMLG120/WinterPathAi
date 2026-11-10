/**
 * DEMO FIXTURES — not real observations.
 *
 * Every payload here validates against docs/contracts/openapi.yaml (see fixtures.test.ts),
 * and every condition/risk datum carries evidence.state = "simulated" (or "unknown").
 * Source metadata mirrors the verified inventory in docs/data-sources-and-licenses.md,
 * but with status "disabled" because no ingest runs in mock mode.
 * No ECCC alerts are fabricated: the mock alert list is always empty.
 */
import type {
  Coverage,
  DataSource,
  Evidence,
  HazardFeature,
  Health,
  ModelStatus,
  SegmentFeature,
  WeatherCurrent,
  WeatherForecast,
} from '@/api/types';
import { PILOT_BBOX } from '@/lib/env';
import { haversineM } from './geo-mock';

export const DEMO_SOURCE_ID = 'demo-fixture';

const iso = (d: Date) => d.toISOString();
const hoursFrom = (base: Date, h: number) => new Date(base.getTime() + h * 3_600_000);

export function simulatedEvidence(now: Date, note = 'Demo fixture — simulated, not an observation.'): Evidence {
  return {
    state: 'simulated',
    source_ids: [DEMO_SOURCE_ID],
    observed_at: iso(hoursFrom(now, -0.5)),
    retrieved_at: iso(now),
    confidence: null,
    note,
  };
}

export function unknownEvidence(): Evidence {
  return { state: 'unknown', source_ids: [], observed_at: null, retrieved_at: null, confidence: null, note: null };
}

export const health = (): Health => ({
  status: 'degraded',
  version: 'mock-1.0.0',
  checks: {
    api: { status: 'ok', detail: 'MSW mock (demo data)' },
    database: { status: 'disabled', detail: 'Not connected in mock mode' },
    risk_model: { status: 'disabled', detail: 'No validated model' },
  },
});

const { west: W, south: S, east: E, north: N } = PILOT_BBOX;

export const coverage = (): Coverage => ({
  pilot_name: 'McGill / Downtown pilot',
  bbox: [W, S, E, N],
  area: {
    type: 'Polygon',
    coordinates: [
      [
        [W, S],
        [E, S],
        [E, N],
        [W, N],
        [W, S],
      ],
    ],
  },
  graph: { node_count: 0, edge_count: 0, built_at: null, osm_snapshot: null },
  known_gaps: [
    { description: 'Demo mode: no pedestrian graph has been built in this environment.', geometry: null },
  ],
});

const CC_BY = 'https://creativecommons.org/licenses/by/4.0/';
const demoNote = 'Demo mode: no ingest has run in this environment.';
const vdm = (id: string, slug: string, name: string): DataSource => ({
  id,
  name,
  publisher: 'Ville de Montréal',
  license: 'CC BY 4.0',
  license_url: CC_BY,
  commercial_use: 'allowed_with_conditions',
  attribution: 'Contient des données de la Ville de Montréal, sous licence CC BY 4.0',
  url: `https://www.donneesquebec.ca/recherche/dataset/${slug}`,
  status: 'disabled',
  last_success_at: null,
  record_count: null,
  notes: demoNote,
});

export const dataSources = (): DataSource[] => [
  {
    id: 'osm',
    name: 'OpenStreetMap',
    publisher: 'OpenStreetMap contributors',
    license: 'ODbL 1.0',
    license_url: 'https://opendatacommons.org/licenses/odbl/1-0/',
    commercial_use: 'allowed_with_conditions',
    attribution: '© OpenStreetMap contributors',
    url: 'https://www.openstreetmap.org/copyright',
    status: 'disabled',
    last_success_at: null,
    record_count: null,
    notes: demoNote,
  },
  vdm('mtl-voirie', 'vmtl-voirie-trottoir-ilot', 'Trottoir et îlot (Voirie)'),
  vdm('mtl-311', 'vmtl-requete-311', 'Requêtes 311'),
  vdm('mtl-entraves', 'vmtl-info-travaux', 'Entraves et travaux en cours'),
  {
    ...vdm('mtl-planif-neige', 'vmtl-deneigement', 'Déneigement / Planif-Neige'),
    status: 'requires_credentials',
    notes: 'Token required from the publisher. Snow-loading plans do not certify sidewalk clearance.',
  },
  {
    id: 'eccc-geomet',
    name: 'MSC GeoMet OGC API',
    publisher: 'Environment and Climate Change Canada',
    license: 'ECCC Data Servers End-use Licence',
    license_url: 'https://eccc-msc.github.io/open-data/licence/readme_en/',
    commercial_use: 'allowed_with_conditions',
    attribution: 'Data Source: Environment and Climate Change Canada',
    url: 'https://api.weather.gc.ca/',
    status: 'disabled',
    last_success_at: null,
    record_count: null,
    notes: demoNote,
  },
];

export const weatherCurrent = (now: Date): WeatherCurrent => ({
  station_id: 'DEMO',
  station_name: 'Demo station (simulated)',
  observed_at: iso(hoursFrom(now, -0.5)),
  temperature_c: -6,
  precipitation_mm_1h: 0.4,
  snow_depth_cm: 12,
  wind_speed_kmh: 18,
  freeze_thaw_24h: true,
  evidence: simulatedEvidence(now),
});

const PERIODS: Array<[string, string, number, number]> = [
  ['Simulated: light snow', 'Simulé : faible neige', -5, 60],
  ['Simulated: cloudy', 'Simulé : nuageux', -3, 20],
  ['Simulated: freezing drizzle', 'Simulé : bruine verglaçante', 0, 40],
  ['Simulated: clearing, colder', 'Simulé : dégagement, plus froid', -9, 10],
];

export const weatherForecast = (now: Date, hours = 24): WeatherForecast => {
  const n = Math.max(1, Math.min(PERIODS.length, Math.ceil(hours / 6)));
  return {
    issued_at: iso(hoursFrom(now, -1)),
    periods: PERIODS.slice(0, n).map(([en, fr, t, pop], i) => ({
      start: iso(hoursFrom(now, i * 6)),
      end: iso(hoursFrom(now, (i + 1) * 6)),
      summary_en: en,
      summary_fr: fr,
      temperature_c: t,
      pop_percent: pop,
    })),
    alerts: [],
    evidence: simulatedEvidence(now),
  };
};

export const modelStatus = (): ModelStatus => ({
  risk_layer: 'none',
  enabled: false,
  model_id: null,
  target: 'P(>=1 winter-related 311 report in H3 res-9 cell within next 24h)',
  trained_at: null,
  training_window: null,
  evaluation: null,
  limitations: [
    'No model has passed the evaluation gate; the risk layer is disabled.',
    'The target is a reporting proxy, not physical ice probability.',
  ],
});

/** Hazard placements are fractions of the pilot bbox, so they're obviously synthetic. */
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const at = (fx: number, fy: number): [number, number] => [
  Number(lerp(W, E, fx).toFixed(6)),
  Number(lerp(S, N, fy).toFixed(6)),
];

export const hazards = (now: Date): HazardFeature[] => [
  {
    type: 'Feature',
    id: 'demo-hz-1',
    geometry: { type: 'LineString', coordinates: [at(0.42, 0.55), at(0.5, 0.55)] },
    properties: {
      kind: 'sidewalk_closure',
      evidence: simulatedEvidence(now),
      blocks_passage: true,
      title_en: 'Simulated sidewalk closure (demo)',
      title_fr: 'Fermeture de trottoir simulée (démo)',
      valid_from: iso(hoursFrom(now, -24)),
      valid_to: iso(hoursFrom(now, 72)),
      report_count: null,
    },
  },
  {
    type: 'Feature',
    id: 'demo-hz-2',
    geometry: { type: 'Point', coordinates: at(0.62, 0.4) },
    properties: {
      kind: 'construction_impact',
      evidence: simulatedEvidence(now),
      blocks_passage: null,
      title_en: 'Simulated construction impact — passage not stated (demo)',
      title_fr: 'Impact de chantier simulé — passage non précisé (démo)',
      valid_from: iso(hoursFrom(now, -48)),
      valid_to: null,
      report_count: null,
    },
  },
  {
    type: 'Feature',
    id: 'demo-hz-3',
    geometry: { type: 'Point', coordinates: at(0.35, 0.3) },
    properties: {
      kind: 'report_311_aggregate',
      evidence: simulatedEvidence(now),
      blocks_passage: null,
      title_en: 'Simulated 311 winter-report cluster (demo)',
      title_fr: 'Regroupement simulé de requêtes 311 hivernales (démo)',
      valid_from: null,
      valid_to: null,
      report_count: 4,
    },
  },
  {
    type: 'Feature',
    id: 'demo-hz-4',
    geometry: { type: 'Point', coordinates: at(0.7, 0.7) },
    properties: {
      kind: 'community_report',
      evidence: simulatedEvidence(now),
      blocks_passage: null,
      title_en: 'Simulated approved community report: ice (demo)',
      title_fr: 'Signalement citoyen approuvé simulé : glace (démo)',
      valid_from: iso(hoursFrom(now, -3)),
      valid_to: iso(hoursFrom(now, 69)),
      report_count: null,
    },
  },
];

const LEVELS = ['low', 'moderate', 'elevated', 'high', 'unknown', 'unknown'] as const;

/** A coarse synthetic grid over the pilot bbox — clearly not real sidewalks. */
export const segments = (now: Date): SegmentFeature[] => {
  const out: SegmentFeature[] = [];
  const steps = 8;
  let i = 0;
  for (let r = 1; r < steps; r++) {
    for (let c = 0; c < steps; c++) {
      for (const horizontal of [true, false]) {
        const a = horizontal ? at(c / steps, r / steps) : at(r / steps, c / steps);
        const b = horizontal ? at((c + 1) / steps, r / steps) : at(r / steps, (c + 1) / steps);
        const level = LEVELS[(r * 7 + c * 3 + (horizontal ? 1 : 0)) % LEVELS.length]!;
        out.push({
          type: 'Feature',
          id: `demo-seg-${i++}`,
          geometry: { type: 'LineString', coordinates: [a, b] },
          properties: {
            length_m: Math.round(haversineM(a, b) * 10) / 10,
            edge_kind: 'sidewalk',
            crossing: null,
            connectivity_confidence: 'low',
            accessibility: { step_free: null, incline_percent: null, width_m: null, surface: null },
            risk: {
              level,
              probability: null,
              evidence: level === 'unknown' ? unknownEvidence() : simulatedEvidence(now),
            },
            sources: [DEMO_SOURCE_ID],
            updated_at: null,
          },
        });
      }
    }
  }
  return out;
};
