/**
 * Real OSM pedestrian edges from the Data agent's fixture (data/fixtures/pilot_mini,
 * ODbL 1.0 — see its ATTRIBUTION.md). Imported read-only; mock mode only.
 *
 * Geometry, edge kind, crossing and accessibility come straight from the fixture.
 * There is no risk layer in demo mode, so every segment's risk is `unknown`
 * (never `low`) — and no condition is invented.
 */
import edgesRaw from '../../../../data/fixtures/pilot_mini/edges.geojson?raw';
import metadata from '../../../../data/fixtures/pilot_mini/metadata.json';
import manifest from '../../../../data/fixtures/pilot_mini/manifest.json';
import type { SegmentFeature } from '@/api/types';
import { unknownEvidence } from './fixtures';

type RawEdge = {
  id: string;
  geometry: { type: 'LineString'; coordinates: [number, number][] };
  properties: {
    edge_kind: SegmentFeature['properties']['edge_kind'];
    length_m: number;
    connectivity_confidence: SegmentFeature['properties']['connectivity_confidence'];
    crossing: SegmentFeature['properties']['crossing'] | null;
    step_free: boolean | null;
    incline_percent: number | null;
    width_m: number | null;
    surface: string | null;
    source_id: string;
    sidewalk_polygon_ids?: string[];
    osm_snapshot: string | null;
  };
};

export const PILOT_MINI = {
  nodeCount: metadata.node_count,
  edgeCount: metadata.edge_count,
  osmSnapshot: metadata.osm_snapshot,
  builtAt: manifest.finished_at,
  bbox: metadata.bbox as [number, number, number, number],
  sourceIds: metadata.source_ids,
  simulated: metadata.simulated,
};

let cache: SegmentFeature[] | null = null;

export function pilotMiniSegments(): SegmentFeature[] {
  if (cache) return cache;
  const fc = JSON.parse(edgesRaw) as { features: RawEdge[] };
  cache = fc.features.map((f) => {
    const p = f.properties;
    const sources = [p.source_id];
    if (p.sidewalk_polygon_ids && p.sidewalk_polygon_ids.length > 0) sources.push('mtl-voirie');
    return {
      type: 'Feature',
      id: f.id,
      geometry: { type: 'LineString', coordinates: f.geometry.coordinates },
      properties: {
        length_m: p.length_m,
        edge_kind: p.edge_kind,
        crossing: p.crossing ?? null,
        connectivity_confidence: p.connectivity_confidence,
        accessibility: {
          step_free: p.step_free,
          incline_percent: p.incline_percent,
          width_m: p.width_m,
          surface: p.surface,
        },
        risk: { level: 'unknown', probability: null, evidence: unknownEvidence() },
        sources,
        updated_at: p.osm_snapshot,
      },
    } satisfies SegmentFeature;
  });
  return cache;
}

/** Edges whose OSM tags verify step-free access (step_free === true), counted from the fixture. */
export function pilotMiniStepFreeCount(): number {
  return pilotMiniSegments().filter((f) => f.properties.accessibility.step_free === true).length;
}
