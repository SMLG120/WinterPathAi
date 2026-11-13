import { afterEach, describe, expect, it, vi } from 'vitest';
import { fitTarget } from '@/features/plan/mapFit';
import { getCoverage, outsideMask, resetCoverage, setCoverage, subscribeCoverage } from './coverage';
import { clipToPilot, isInPilot } from './geo';
import { PILOT_BBOX } from './pilot';

const ISLAND = [-73.97, 45.401, -73.477, 45.707];
const POINTE_CLAIRE = { lon: -73.8208, lat: 45.4303 };

describe('coverage', () => {
  afterEach(() => resetCoverage());

  it('defaults to the v1 pilot bbox until the API answers', () => {
    expect(getCoverage()).toEqual({ box: PILOT_BBOX, ring: null, fromApi: false });
    expect(isInPilot(POINTE_CLAIRE)).toBe(false);
    expect(fitTarget([], 'winter_aware')).toEqual([
      [PILOT_BBOX.west, PILOT_BBOX.south],
      [PILOT_BBOX.east, PILOT_BBOX.north],
    ]);
  });

  it('adopts the bbox and polygon from GET /coverage and notifies subscribers', () => {
    const seen = vi.fn();
    const off = subscribeCoverage(seen);
    const ring = [
      [-73.9, 45.42],
      [-73.5, 45.42],
      [-73.5, 45.7],
      [-73.9, 45.7],
      [-73.9, 45.42],
    ];
    setCoverage(ISLAND, { type: 'Polygon', coordinates: [ring] });
    expect(seen).toHaveBeenCalledTimes(1);
    expect(getCoverage().fromApi).toBe(true);
    expect(isInPilot(POINTE_CLAIRE)).toBe(true);
    expect(clipToPilot([-74.5, 45.0, -73.0, 46.0])).toEqual(ISLAND);
    expect(fitTarget([], 'winter_aware')).toEqual([
      [ISLAND[0], ISLAND[1]],
      [ISLAND[2], ISLAND[3]],
    ]);
    expect(outsideMask().geometry.coordinates[1]).toEqual(ring); // the hole is the real outline
    setCoverage(ISLAND, { type: 'Polygon', coordinates: [ring] });
    expect(seen).toHaveBeenCalledTimes(1); // unchanged → no re-render / re-fit
    off();
  });

  it('ignores malformed coverage and falls back to a rectangle without a polygon', () => {
    setCoverage([1, 2, 3]);
    setCoverage([-73.5, 45.4, -73.9, 45.7]); // west > east
    expect(getCoverage().fromApi).toBe(false);
    setCoverage(ISLAND, null);
    expect(outsideMask().geometry.coordinates[1]).toHaveLength(5);
  });
});
