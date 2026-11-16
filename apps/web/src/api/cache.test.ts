// @vitest-environment node
import { describe, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { gridStep, normaliseOverlayBbox, snapOutward } from './spatialKey';
import { computedAgeMs, freshnessOf, withFreshness } from './freshness';
import { createResilientFetch } from './resilientFetch';
import { api, ApiRequestError, isAbortError, unwrap } from './client';
import { compareRoutesOnce, trimOverlayCache } from './queries';
import type { Bbox } from '@/lib/geo';

const MAX_AREA = 0.0025;
const area = (b: Bbox) => (b[2] - b[0]) * (b[3] - b[1]);
const COVER: Bbox = [-73.97, 45.401, -73.477, 45.707];
const clip = ([w, s, e, n]: Bbox): Bbox | null => {
  const c: Bbox = [Math.max(w, COVER[0]), Math.max(s, COVER[1]), Math.min(e, COVER[2]), Math.min(n, COVER[3])];
  return c[0] < c[2] && c[1] < c[3] ? c : null;
};
const ok = (b: Bbox) => area(b) > 0 && area(b) <= MAX_AREA;
const fmt = (b: Bbox) => b.map((v) => v.toFixed(5)).join(',');

describe('spatially normalised overlay bbox', () => {
  const view: Bbox = [-73.5751, 45.5011, -73.5592, 45.5094]; // ~1.2 km × 0.9 km downtown

  it('uses a power-of-two grid about an eighth of the viewport', () => {
    const step = gridStep(view);
    expect(Number.isInteger(Math.log2(step))).toBe(true);
    expect(step).toBeLessThanOrEqual((view[2] - view[0]) / 8);
    expect(step).toBeGreaterThan((view[2] - view[0]) / 16);
  });

  it('only widens: the viewport is always inside the requested box', () => {
    const b = normaliseOverlayBbox(view, clip, ok);
    expect(b[0]).toBeLessThanOrEqual(view[0]);
    expect(b[1]).toBeLessThanOrEqual(view[1]);
    expect(b[2]).toBeGreaterThanOrEqual(view[2]);
    expect(b[3]).toBeGreaterThanOrEqual(view[3]);
    expect(area(b) / area(view)).toBeLessThan(1.8);
  });

  it('small pans give the same key; a pan of a grid cell or more gives another', () => {
    const step = gridStep(view);
    const base = fmt(normaliseOverlayBbox(view, clip, ok));
    let same = 0;
    const n = 200;
    for (let i = 0; i < n; i++) {
      const d = ((i % 20) - 10) * (step / 100); // pans up to a tenth of a cell
      const pan: Bbox = [view[0] + d, view[1] + d / 2, view[2] + d, view[3] + d / 2];
      if (fmt(normaliseOverlayBbox(pan, clip, ok)) === base) same++;
    }
    expect(same / n).toBeGreaterThan(0.6);
    const far: Bbox = [view[0] + 2 * step, view[1], view[2] + 2 * step, view[3]];
    expect(fmt(normaliseOverlayBbox(far, clip, ok))).not.toBe(base);
  });

  it('never exceeds the area limit: falls back to a finer grid, then to the viewport', () => {
    const big: Bbox = [-73.6, 45.5, -73.55, 45.549]; // 0.00245 deg², just under the limit
    const b = normaliseOverlayBbox(big, clip, ok);
    expect(area(b)).toBeLessThanOrEqual(MAX_AREA);
    expect(b[0]).toBeLessThanOrEqual(big[0]);
    expect(b[3]).toBeGreaterThanOrEqual(big[3]);
    const exact: Bbox = [-73.6, 45.5, -73.55, 45.55]; // exactly the limit: no room to widen
    expect(normaliseOverlayBbox(exact, clip, ok)).toEqual(exact);
  });

  it('stays inside coverage', () => {
    const edge: Bbox = [-73.98, 45.40, -73.965, 45.41];
    const c = clip(edge)!;
    const b = normaliseOverlayBbox(c, clip, ok);
    expect(b[0]).toBeGreaterThanOrEqual(COVER[0]);
    expect(b[1]).toBeGreaterThanOrEqual(COVER[1]);
  });

  it('snapOutward is deterministic on the grid', () => {
    expect(snapOutward([0.3, 0.3, 0.7, 0.7], 0.25)).toEqual([0.25, 0.25, 0.75, 0.75]);
    expect(snapOutward([0.3, 0.3, 0.7, 0.7], 0)).toEqual([0.3, 0.3, 0.7, 0.7]);
  });
});

describe('freshness metadata', () => {
  const q = (o: Partial<Parameters<typeof freshnessOf>[0]>) => ({
    data: undefined,
    dataUpdatedAt: 0,
    error: null,
    isFetching: false,
    isStale: false,
    isPlaceholderData: false,
    isFetchedAfterMount: false,
    ...o,
  });

  it('idle, loading, unavailable', () => {
    expect(freshnessOf(q({})).state).toBe('idle');
    expect(freshnessOf(q({ isFetching: true })).state).toBe('loading');
    const err = new ApiRequestError(0, undefined, null, 'TIMEOUT');
    const f = freshnessOf(q({ error: err }));
    expect(f.state).toBe('unavailable');
    expect(f.error).toBe(err);
  });

  it('fresh vs cached vs stale, with age', () => {
    const fresh = freshnessOf(q({ data: {}, dataUpdatedAt: 1000, isFetchedAfterMount: true }), 4000);
    expect(fresh).toMatchObject({ state: 'fresh', fromCache: false, fetchedAt: 1000, ageMs: 3000, isStale: false });
    expect(freshnessOf(q({ data: {}, dataUpdatedAt: 1000 }), 2000).state).toBe('cached');
    const stale = freshnessOf(q({ data: {}, dataUpdatedAt: 1000, isStale: true, isFetching: true }), 2000);
    expect(stale).toMatchObject({ state: 'stale', isStale: true, isRefreshing: true });
  });

  it('a failed refresh with older data is stale and keeps the error', () => {
    const err = new ApiRequestError(503, { code: 'UPSTREAM_UNAVAILABLE', message: 'x' } as never, null);
    const f = freshnessOf(q({ data: {}, dataUpdatedAt: 1, error: err, isFetchedAfterMount: true }));
    expect(f.state).toBe('stale');
    expect(f.error).toBe(err);
  });

  it('previous map area while the new one loads', () => {
    expect(freshnessOf(q({ data: {}, isPlaceholderData: true, isFetching: true })).state).toBe('previous-area');
  });

  it('withFreshness adds a lazy getter without copying the result', () => {
    const r = q({ data: {}, dataUpdatedAt: Date.now(), isFetchedAfterMount: true });
    const w = withFreshness(r);
    expect(w).toBe(r);
    expect(w.freshness.state).toBe('fresh');
    expect(Object.keys(w)).not.toContain('freshness');
  });

  it('computedAgeMs reads the API computed_at', () => {
    expect(computedAgeMs('2026-11-16T12:00:00Z', Date.parse('2026-11-16T12:00:40Z'))).toBe(40_000);
    expect(computedAgeMs(undefined)).toBeNull();
  });
});

describe('aborting obsolete requests', () => {
  it('a cancelled request stops waiting for a sleeping backend', async () => {
    const ctrl = new AbortController();
    let attempts = 0;
    const f = createResilientFetch({
      timeoutMs: 15_000,
      budgetMs: 90_000,
      baseFetch: (async () => {
        attempts++;
        return new Response('<html>waking</html>', { status: 503 });
      }) as unknown as typeof fetch,
      sleep: () => new Promise<void>((r) => setTimeout(r, 5_000)),
    });
    const p = f('http://api.test/api/v1/map/segments?bbox=1,2,3,4', { signal: ctrl.signal });
    await new Promise((r) => setTimeout(r, 10));
    ctrl.abort();
    await expect(p).rejects.toSatisfy(isAbortError);
    expect(attempts).toBe(1);
  });

  it('unwrap rethrows an abort as is (never reported as a network error)', async () => {
    const abort = new DOMException('aborted', 'AbortError');
    await expect(unwrap(Promise.reject(abort))).rejects.toBe(abort);
  });
});

describe('overlay cache bound', () => {
  it('keeps only the most recent unobserved areas', () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    const qc = new QueryClient();
    for (let i = 0; i < 20; i++) {
      qc.setQueryData(['segments', `b${i}`], { i });
      // dataUpdatedAt increases with i
      vi.setSystemTime(Date.now() + 1000);
    }
    qc.setQueryData(['hazards', 'x'], {});
    expect(trimOverlayCache(qc, 'segments', 12)).toBe(8);
    const left = qc.getQueryCache().findAll({ queryKey: ['segments'] }).map((q) => q.queryKey[1]);
    expect(left).toHaveLength(12);
    expect(left).toContain('b19');
    expect(left).not.toContain('b0');
    expect(qc.getQueryData(['hazards', 'x'])).toEqual({});
    vi.useRealTimers();
  });
});

describe('route comparison dedupe', () => {
  it('identical comparisons in flight share one request; a different one does not', async () => {
    let resolve!: (v: unknown) => void;
    const answer = { routes: [{ geometry: { coordinates: [[0, 0], [1, 1]] }, explanation: [] }] };
    const spy = vi.spyOn(api, 'POST').mockImplementation(
      () => new Promise((r) => (resolve = () => r({ data: answer, response: new Response(null, { status: 200 }) }))) as never,
    );
    const body = { origin: { lon: -73.57, lat: 45.5 }, destination: { lon: -73.56, lat: 45.51 } };
    const a = compareRoutesOnce(body);
    const b = compareRoutesOnce({ ...body });
    expect(spy).toHaveBeenCalledTimes(1);
    resolve(undefined);
    expect(await a).toBe(await b);
    void compareRoutesOnce({ ...body, locale: 'fr' });
    expect(spy).toHaveBeenCalledTimes(2);
    resolve(undefined);
    compareRoutesOnce(body); // settled requests are not reused: a new click asks again
    expect(spy).toHaveBeenCalledTimes(3);
    resolve(undefined);
    spy.mockRestore();
  });
});
