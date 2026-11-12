import type { Route } from '@/api/types';

/**
 * Oldest refresh among the route's sources; null when any source has never refreshed (unknown
 * freshness must not be hidden behind a newer one).
 */
export function oldestFreshness(r: Route): string | null {
  const v = Object.values(r.data_freshness);
  if (v.length === 0 || v.some((x) => !x)) return null;
  return (v as string[]).reduce((a, b) => (Date.parse(a) <= Date.parse(b) ? a : b));
}
