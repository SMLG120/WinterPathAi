/**
 * Cache / freshness metadata for query results, so the UI can say "cached", "stale" or
 * "unavailable" instead of silently showing old data. Pure: derived from TanStack Query's own
 * state, never invented. An error is never hidden: when older data is still shown after a failed
 * refresh, the state is `stale` and `error` is set.
 */
import type { UseQueryResult } from '@tanstack/react-query';
import type { ApiRequestError } from './client';

export type FreshnessState =
  /** query disabled (no bbox, overlay hidden) and nothing to show */
  | 'idle'
  /** first fetch in progress, nothing to show yet */
  | 'loading'
  /** data fetched from the API since this view mounted, within its stale time */
  | 'fresh'
  /** data served from the in-memory cache (fetched before this view mounted), within its stale time */
  | 'cached'
  /** data older than its stale time, or a refresh failed and older data is still shown */
  | 'stale'
  /** data for the previous map area, kept on screen while the new area loads */
  | 'previous-area'
  /** no data and the last request failed */
  | 'unavailable';

export type CacheFreshness = {
  state: FreshnessState;
  /** when the shown data arrived from the API (ms since epoch); null when there is none */
  fetchedAt: number | null;
  /** `now - fetchedAt` at the time of the call; null when there is no data */
  ageMs: number | null;
  /** past the query's stale time (TanStack `isStale`) or older data shown after an error */
  isStale: boolean;
  /** shown data did not come from a request made by this view (cache or previous area) */
  fromCache: boolean;
  /** a request is in flight while data is shown */
  isRefreshing: boolean;
  /** the last error, typed when it came from the API client; null when the last request succeeded */
  error: ApiRequestError | Error | null;
};

type QueryLike = Pick<
  UseQueryResult<unknown, Error>,
  'data' | 'dataUpdatedAt' | 'error' | 'isFetching' | 'isStale' | 'isPlaceholderData' | 'isFetchedAfterMount'
>;

export function freshnessOf(q: QueryLike, now: number = Date.now()): CacheFreshness {
  const hasData = q.data !== undefined;
  const error = q.error ?? null;
  const fetchedAt = hasData && q.dataUpdatedAt > 0 ? q.dataUpdatedAt : null;
  const base = {
    fetchedAt,
    ageMs: fetchedAt === null ? null : Math.max(0, now - fetchedAt),
    isRefreshing: hasData && q.isFetching,
    error,
  };
  if (!hasData) {
    if (error) return { ...base, state: 'unavailable', isStale: false, fromCache: false };
    return { ...base, state: q.isFetching ? 'loading' : 'idle', isStale: false, fromCache: false };
  }
  if (q.isPlaceholderData) return { ...base, state: 'previous-area', isStale: true, fromCache: true };
  const fromCache = !q.isFetchedAfterMount;
  if (error || q.isStale) return { ...base, state: 'stale', isStale: true, fromCache };
  return { ...base, state: fromCache ? 'cached' : 'fresh', isStale: false, fromCache };
}

/**
 * Adds a lazy `freshness` getter to a query result (the result object itself is unchanged, so
 * TanStack's render tracking still only follows the properties a component reads).
 */
export function withFreshness<T extends QueryLike>(q: T): T & { readonly freshness: CacheFreshness } {
  if (!Object.prototype.hasOwnProperty.call(q, 'freshness')) {
    Object.defineProperty(q, 'freshness', { get: () => freshnessOf(q), enumerable: false, configurable: true });
  }
  return q as T & { readonly freshness: CacheFreshness };
}

/** Age of a route comparison: the API may answer a repeated request from its short-lived cache,
 *  and `computed_at` is always when the routes were actually computed. */
export function computedAgeMs(computedAt: string | undefined | null, now: number = Date.now()): number | null {
  if (!computedAt) return null;
  const t = Date.parse(computedAt);
  return Number.isFinite(t) ? Math.max(0, now - t) : null;
}
