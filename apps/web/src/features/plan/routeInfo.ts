import type { Route } from '@/api/types';

const HOUR = 3_600_000;
/** Map data rebuilt by hand (street network, sidewalk polygons): not a "condition" that goes stale by the hour. */
const STATIC_SOURCES = new Set(['osm', 'mtl-voirie']);
/** Same limits as the API's /data-status: weather 6 h; closures and 311 reports 7 days. Unlisted sources: 6 h. */
const STALE_AFTER: Record<string, number> = { 'eccc-geomet': 6 * HOUR, 'mtl-entraves': 168 * HOUR, 'mtl-311': 168 * HOUR };

function conditionSources(r: Route): [string, string | null | undefined][] {
  return Object.entries(r.data_freshness).filter(([k]) => !STATIC_SOURCES.has(k));
}

/**
 * Oldest refresh among the route's condition sources (weather, closures, 311; not the static map
 * data); null when any of them has never refreshed (unknown freshness must not be hidden behind a
 * newer one).
 */
export function oldestFreshness(r: Route): string | null {
  const v = conditionSources(r).map(([, x]) => x);
  if (v.length === 0 || v.some((x) => !x)) return null;
  return (v as string[]).reduce((a, b) => (Date.parse(a) <= Date.parse(b) ? a : b));
}

/** True when any condition source is older than its own refresh limit. */
export function anyConditionStale(r: Route, now = Date.now()): boolean {
  return conditionSources(r).some(([k, x]) => {
    const t = x ? Date.parse(x) : NaN;
    return Number.isFinite(t) && now - t > (STALE_AFTER[k] ?? 6 * HOUR);
  });
}
