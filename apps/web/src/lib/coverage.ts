import { PILOT_BBOX } from './pilot';

/** Served coverage area. Client-side UX hint only: the API is authoritative (422 OUTSIDE_COVERAGE). */
export type CoverageBox = { west: number; south: number; east: number; north: number };
export type Ring = [number, number][];
export type Coverage = {
  box: CoverageBox;
  /** Outer ring of the coverage polygon from GET /coverage, or null → the bbox rectangle. */
  ring: Ring | null;
  /** True once GET /coverage answered; until then `box` is the build-time default. */
  fromApi: boolean;
};

function parseBox(raw: string | undefined): CoverageBox | null {
  const v = (raw ?? '').split(',').map(Number);
  if (v.length !== 4 || v.some((x) => !Number.isFinite(x))) return null;
  const [west, south, east, north] = v as [number, number, number, number];
  return west < east && south < north ? { west, south, east, north } : null;
}

/** Build-time default (`VITE_COVERAGE_BBOX=west,south,east,north`), else the v1 pilot bbox. */
const DEFAULT_BOX: CoverageBox = parseBox(import.meta.env?.VITE_COVERAGE_BBOX) ?? PILOT_BBOX;

let current: Coverage = { box: DEFAULT_BOX, ring: null, fromApi: false };
const listeners = new Set<() => void>();

export const getCoverage = (): Coverage => current;

export function subscribeCoverage(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** Adopt the API's coverage (bbox + optional Polygon). Invalid input is ignored. */
export function setCoverage(bbox: readonly number[] | undefined, area?: { type?: string; coordinates?: unknown } | null): void {
  const box = parseBox(bbox?.join(','));
  if (!box) return;
  const outer = area?.type === 'Polygon' && Array.isArray(area.coordinates) ? (area.coordinates[0] as Ring | undefined) : undefined;
  const ring = outer && outer.length >= 4 ? outer : null;
  const same =
    current.fromApi &&
    current.box.west === box.west &&
    current.box.south === box.south &&
    current.box.east === box.east &&
    current.box.north === box.north &&
    (current.ring?.length ?? 0) === (ring?.length ?? 0);
  if (same) return;
  current = { box, ring, fromApi: true };
  listeners.forEach((cb) => cb());
}

/** Test helper: back to the build-time default. */
export function resetCoverage(): void {
  current = { box: DEFAULT_BOX, ring: null, fromApi: false };
  listeners.forEach((cb) => cb());
}

/** World polygon with the coverage punched out → the hatched "outside coverage" mask. */
export function outsideMask(c: Coverage = current) {
  const { west: W, south: S, east: E, north: N } = c.box;
  const hole: Ring = c.ring ?? [
    [W, S],
    [W, N],
    [E, N],
    [E, S],
    [W, S],
  ];
  return {
    type: 'Feature' as const,
    properties: {},
    geometry: {
      type: 'Polygon' as const,
      coordinates: [
        [
          [-180, -85],
          [180, -85],
          [180, 85],
          [-180, 85],
          [-180, -85],
        ],
        hole,
      ],
    },
  };
}
