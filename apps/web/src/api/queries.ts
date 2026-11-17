import { useEffect } from 'react';
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';
import { api, unwrap } from './client';
import { withFreshness } from './freshness';
import type {
  HazardCollection,
  ModerationStatus,
  PilotRequest,
  ReportCreate,
  RouteCompareRequest,
  RouteCompareResponse,
  SegmentCollection,
} from './types';

export const qk = {
  health: ['health'] as const,
  coverage: ['coverage'] as const,
  dataSources: ['data-sources'] as const,
  weatherCurrent: ['weather', 'current'] as const,
  weatherForecast: (h: number) => ['weather', 'forecast', h] as const,
  hazards: (bbox: string) => ['hazards', bbox] as const,
  segments: (bbox: string) => ['segments', bbox] as const,
  modelStatus: ['models', 'status'] as const,
  adminReports: (status: ModerationStatus | 'all') => ['admin', 'reports', status] as const,
};

// Every query passes TanStack's AbortSignal to the client: a query nobody observes any more
// (e.g. the map moved on) cancels its request instead of finishing it in the background.
// Each hook's result also carries a lazy `freshness` (api/freshness.ts) for cached/stale/unavailable UI.

export const useCoverage = () =>
  withFreshness(
    useQuery({
      queryKey: qk.coverage,
      queryFn: ({ signal }) => unwrap(api.GET('/coverage', { signal })),
      staleTime: 60 * 60_000,
    }),
  );

export const useDataSources = () =>
  withFreshness(
    useQuery({
      queryKey: qk.dataSources,
      queryFn: ({ signal }) => unwrap(api.GET('/data-sources', { signal })),
      staleTime: 10 * 60_000,
    }),
  );

export const useWeatherCurrent = () =>
  withFreshness(
    useQuery({
      queryKey: qk.weatherCurrent,
      queryFn: ({ signal }) => unwrap(api.GET('/weather/current', { signal })),
      staleTime: 5 * 60_000,
    }),
  );

export const useWeatherForecast = (hours = 24) =>
  withFreshness(
    useQuery({
      queryKey: qk.weatherForecast(hours),
      queryFn: ({ signal }) => unwrap(api.GET('/weather/forecast', { params: { query: { hours } }, signal })),
      staleTime: 10 * 60_000,
    }),
  );

export const useModelStatus = () =>
  withFreshness(
    useQuery({
      queryKey: qk.modelStatus,
      queryFn: ({ signal }) => unwrap(api.GET('/models/status', { signal })),
      staleTime: 30 * 60_000,
    }),
  );

/**
 * Viewport overlays. Keys are the grid-normalised bbox string (features/plan/useOverlayBbox.ts),
 * so small pans hit the cache. The API answers from caches of a few minutes, so a refetch
 * within OVERLAY_STALE_MS would usually get the same bytes back.
 */
export const OVERLAY_STALE_MS = 2 * 60_000;
/** Unobserved overlay areas are dropped after this long… */
export const OVERLAY_GC_MS = 5 * 60_000;
/** …and never more than this many per overlay are kept (a segments page is ~0.3 MB of JSON). */
export const OVERLAY_MAX_CACHED_AREAS = 12;

/** Remove the least recently fetched unobserved queries under `prefix` beyond `max`. */
export function trimOverlayCache(qc: QueryClient, prefix: string, max = OVERLAY_MAX_CACHED_AREAS): number {
  const idle = qc
    .getQueryCache()
    .findAll({ queryKey: [prefix] })
    .filter((q) => q.getObserversCount() === 0 && q.state.fetchStatus === 'idle')
    .sort((a, b) => b.state.dataUpdatedAt - a.state.dataUpdatedAt);
  const drop = idle.slice(max);
  for (const q of drop) qc.getQueryCache().remove(q);
  return drop.length;
}

function useOverlayTrim(prefix: string, bbox: string | null) {
  const qc = useQueryClient();
  useEffect(() => {
    trimOverlayCache(qc, prefix);
  }, [qc, prefix, bbox]);
}

/** Viewport-bbox overlays. `bbox` is null when the viewport is too large or outside the pilot. */
export const useHazards = (bbox: string | null) => {
  useOverlayTrim('hazards', bbox);
  return withFreshness(
    useQuery<HazardCollection>({
      queryKey: qk.hazards(bbox ?? ''),
      queryFn: ({ signal }) =>
        unwrap(api.GET('/hazards', { params: { query: { bbox: bbox! } }, signal })) as Promise<HazardCollection>,
      enabled: bbox !== null,
      placeholderData: keepPreviousData,
      staleTime: OVERLAY_STALE_MS,
      gcTime: OVERLAY_GC_MS,
    }),
  );
};

/** /map/segments pages followed per overlay box (API max limit 1000). Beyond that, `next_cursor`
 * stays set on the merged collection so the overlay is known to be truncated. */
export const SEGMENT_PAGE_LIMIT = 1000;
export const SEGMENT_MAX_PAGES = 5;

export async function fetchAllSegments(get: (cursor?: string) => Promise<SegmentCollection>): Promise<SegmentCollection> {
  const first = await get();
  const features = [...first.features];
  let page = first;
  for (let i = 1; i < SEGMENT_MAX_PAGES && page.next_cursor; i++) {
    page = await get(page.next_cursor);
    features.push(...page.features);
  }
  return { ...first, features, next_cursor: page.next_cursor };
}

export const useSegments = (bbox: string | null) => {
  useOverlayTrim('segments', bbox);
  return withFreshness(
    useQuery<SegmentCollection>({
      queryKey: qk.segments(bbox ?? ''),
      queryFn: ({ signal }) =>
        fetchAllSegments(
          (cursor) =>
            unwrap(
              api.GET('/map/segments', {
                params: { query: { bbox: bbox!, limit: SEGMENT_PAGE_LIMIT, ...(cursor ? { cursor } : {}) } },
                signal,
              }),
            ) as Promise<SegmentCollection>,
        ),
      enabled: bbox !== null,
      placeholderData: keepPreviousData,
      staleTime: OVERLAY_STALE_MS,
      gcTime: OVERLAY_GC_MS,
    }),
  );
};

/**
 * Identical comparisons already in flight share one request (double clicks, a language toggle
 * back and forth while the first answer is pending): the API is 0.1 CPU.
 */
const comparesInFlight = new Map<string, Promise<RouteCompareResponse>>();

export function compareRoutesOnce(body: RouteCompareRequest): Promise<RouteCompareResponse> {
  const key = JSON.stringify(body);
  const pending = comparesInFlight.get(key);
  if (pending) return pending;
  const p = unwrap(api.POST('/routes/compare', { body }), (d) =>
    // Both variants with drawable geometry, or it is an incomplete answer (never render half a comparison).
    Array.isArray(d?.routes) &&
    d.routes.length >= 1 &&
    d.routes.every((r) => Array.isArray(r?.geometry?.coordinates) && r.geometry.coordinates.length >= 2 && Array.isArray(r.explanation)),
  ).finally(() => comparesInFlight.delete(key));
  comparesInFlight.set(key, p);
  return p;
}

export const useCompareRoutes = () => useMutation({ mutationFn: compareRoutesOnce });

export const useCreateReport = () =>
  useMutation({ mutationFn: (body: ReportCreate) => unwrap(api.POST('/reports', { body })) });

export const useDeleteReport = () =>
  useMutation({
    mutationFn: ({ id, token }: { id: string; token: string }) =>
      unwrap(
        api.DELETE('/reports/{reportId}', {
          params: { path: { reportId: id }, header: { 'X-Deletion-Token': token } },
        }),
      ),
  });

export const useCreatePilotRequest = () =>
  // Contract declares 201 with no body: don't try to parse JSON.
  useMutation({ mutationFn: (body: PilotRequest) => unwrap(api.POST('/pilot-requests', { body, parseAs: 'text' })) });

/** Admin token is held in memory only (never persisted). */
export const useAdminReports = (token: string | null, status: ModerationStatus | 'all') =>
  useQuery({
    queryKey: [...qk.adminReports(status), token ? 'auth' : 'anon'],
    queryFn: () =>
      unwrap(
        api.GET('/admin/reports', {
          params: { query: status === 'all' ? {} : { status } },
          headers: { Authorization: `Bearer ${token}` },
        }),
      ),
    enabled: !!token,
    retry: false,
  });

export const useModerateReport = (token: string | null) =>
  useMutation({
    mutationFn: ({ id, decision, note }: { id: string; decision: 'approve' | 'reject' | 'expire'; note?: string }) =>
      unwrap(
        api.POST('/admin/reports/{reportId}/moderation', {
          params: { path: { reportId: id } },
          body: note ? { decision, note } : { decision },
          headers: { Authorization: `Bearer ${token}` },
        }),
      ),
  });
