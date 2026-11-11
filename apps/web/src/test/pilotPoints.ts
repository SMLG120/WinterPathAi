/**
 * Test points derived from whatever data/fixtures/pilot_mini build is checked out, so tests do
 * not break when the Data agent regenerates the fixture (edge ids and coverage change).
 *
 * - A, B: the two endpoints of the longest non-steps edge — on the network (0 m snap) and
 *   connected by that edge, so a real router can always route A→B.
 * - OFF_NET: the point of a 0.0005° grid over the pilot bbox (inset 0.001°) farthest from
 *   every edge; tests assert it is > 75 m (the snap limit) away.
 * Pure Node (fs) — usable from Vitest and Playwright.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pointSegmentM, type Pos } from '../mocks/geo-mock';
import { PILOT_BBOX } from '../lib/pilot';

type Edge = { geometry: { coordinates: Pos[] }; properties: { edge_kind: string; length_m: number } };

// Resolved from the cwd (apps/web for Vitest and Playwright): import.meta.url is not a file: URL under jsdom.
const edgesPath = resolve(process.cwd(), '../../data/fixtures/pilot_mini/edges.geojson');
const edges = (JSON.parse(readFileSync(edgesPath, 'utf8')) as { features: Edge[] }).features;

export function distanceToNetworkM(p: Pos): number {
  let best = Infinity;
  for (const e of edges) {
    const c = e.geometry.coordinates;
    for (let i = 1; i < c.length; i++) best = Math.min(best, pointSegmentM(p, c[i - 1]!, c[i]!));
  }
  return best;
}

const longest = edges
  .filter((e) => e.properties.edge_kind !== 'steps')
  .reduce((a, b) => (b.properties.length_m > a.properties.length_m ? b : a));
const coords = longest.geometry.coordinates;
const a = coords[0]!;
const b = coords[coords.length - 1]!;

let off: Pos = [PILOT_BBOX.west, PILOT_BBOX.south];
let offD = -1;
for (let lon = PILOT_BBOX.west + 0.001; lon <= PILOT_BBOX.east - 0.001; lon += 0.0005) {
  for (let lat = PILOT_BBOX.south + 0.001; lat <= PILOT_BBOX.north - 0.001; lat += 0.0005) {
    const d = distanceToNetworkM([lon, lat]);
    if (d > offD) [off, offD] = [[lon, lat], d];
  }
}

const ll = ([lon, lat]: Pos) => ({ lon: Number(lon.toFixed(6)), lat: Number(lat.toFixed(6)) });
const str = (p: { lon: number; lat: number }) => ({ lat: p.lat.toFixed(6), lon: p.lon.toFixed(6) });

/** Numeric { lon, lat } for API/mocks. */
export const PTS = { A: ll(a), B: ll(b), OFF_NET: ll(off) };
/** String { lat, lon } for form inputs. */
export const PTS_INPUT = { A: str(PTS.A), B: str(PTS.B), OFF_NET: str(PTS.OFF_NET) };
export const OFF_NET_DISTANCE_M = offD;
