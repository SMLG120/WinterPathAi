/**
 * Routable-area geometry for the map: the hatched "outside" mask and the boundary outline.
 *
 * GET /coverage `area` is a Polygon in contract v1.8. The island outline already merges nearby
 * islands into one polygon because the contract allows only one (docs/ISLAND_COVERAGE.md), so a
 * future MultiPolygon (several served areas) is accepted here too: every polygon's outer ring is
 * cut out of the mask and every polygon's holes stay masked. Anything else falls back to the bbox.
 */
import type { Feature, FeatureCollection, MultiLineString, Polygon } from 'geojson';
import type { CoverageBox } from '@/lib/coverage';

export type Ring = [number, number][];
/** One served polygon: outer ring + holes (lakes, excluded zones). */
export type AreaPolygon = { outer: Ring; holes: Ring[] };

const WORLD: Ring = [
  [-180, -85],
  [180, -85],
  [180, 85],
  [-180, 85],
  [-180, -85],
];

function isPos(p: unknown): p is [number, number] {
  return Array.isArray(p) && p.length >= 2 && Number.isFinite(p[0]) && Number.isFinite(p[1]);
}

/** A closed ring with at least 4 positions, or null. Extra dimensions (z) are dropped. */
function toRing(r: unknown): Ring | null {
  if (!Array.isArray(r) || r.length < 4 || !r.every(isPos)) return null;
  const ring = r.map((p) => [p[0], p[1]] as [number, number]);
  const [a, z] = [ring[0]!, ring[ring.length - 1]!];
  if (a[0] !== z[0] || a[1] !== z[1]) ring.push([a[0], a[1]]);
  return ring;
}

function toPolygon(coords: unknown): AreaPolygon | null {
  if (!Array.isArray(coords) || coords.length === 0) return null;
  const outer = toRing(coords[0]);
  if (!outer) return null;
  const holes = coords.slice(1).map(toRing).filter((x): x is Ring => x !== null);
  return { outer, holes };
}

/** Polygon | MultiPolygon → served polygons. Unknown or broken input → []. */
export function parseArea(area: { type?: string; coordinates?: unknown } | null | undefined): AreaPolygon[] {
  if (!area || !Array.isArray(area.coordinates)) return [];
  if (area.type === 'Polygon') {
    const p = toPolygon(area.coordinates);
    return p ? [p] : [];
  }
  if (area.type === 'MultiPolygon') {
    return (area.coordinates as unknown[]).map(toPolygon).filter((x): x is AreaPolygon => x !== null);
  }
  return [];
}

export function boxPolygon(b: CoverageBox): AreaPolygon {
  return {
    outer: [
      [b.west, b.south],
      [b.east, b.south],
      [b.east, b.north],
      [b.west, b.north],
      [b.west, b.south],
    ],
    holes: [],
  };
}

/** Served polygons, or the bbox rectangle when the API gave no usable area. */
export function servedPolygons(area: Parameters<typeof parseArea>[0], box: CoverageBox): AreaPolygon[] {
  const p = parseArea(area);
  return p.length ? p : [boxPolygon(box)];
}

/**
 * Mask = the world with each served outer ring punched out, plus each served hole filled back in.
 * The world polygon's own holes must not overlap; served polygons of a valid MultiPolygon don't.
 */
export function maskCollection(polys: AreaPolygon[]): FeatureCollection<Polygon> {
  const features: Feature<Polygon>[] = [
    { type: 'Feature', properties: { part: 'outside' }, geometry: { type: 'Polygon', coordinates: [WORLD, ...polys.map((p) => p.outer)] } },
  ];
  for (const p of polys) for (const h of p.holes) features.push({ type: 'Feature', properties: { part: 'hole' }, geometry: { type: 'Polygon', coordinates: [h] } });
  return { type: 'FeatureCollection', features };
}

/** Every boundary ring (outer and holes) as one MultiLineString, for the outline layer. */
export function outlineCollection(polys: AreaPolygon[]): FeatureCollection<MultiLineString> {
  return {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        properties: {},
        geometry: { type: 'MultiLineString', coordinates: polys.flatMap((p) => [p.outer, ...p.holes]) },
      },
    ],
  };
}

/** Point-in-served-area (even-odd, holes excluded). UX hint only: the API decides (422 OUTSIDE_COVERAGE). */
export function inServedArea(lon: number, lat: number, polys: AreaPolygon[]): boolean {
  const inRing = (r: Ring) => {
    let inside = false;
    for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
      const [xi, yi] = r[i]!;
      const [xj, yj] = r[j]!;
      if (yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  };
  return polys.some((p) => inRing(p.outer) && !p.holes.some(inRing));
}
