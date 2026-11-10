import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query';
import { api, unwrap } from './client';
import type {
  HazardCollection,
  ModerationStatus,
  PilotRequest,
  ReportCreate,
  RouteCompareRequest,
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

export const useCoverage = () =>
  useQuery({ queryKey: qk.coverage, queryFn: () => unwrap(api.GET('/coverage')), staleTime: 60 * 60_000 });

export const useDataSources = () =>
  useQuery({ queryKey: qk.dataSources, queryFn: () => unwrap(api.GET('/data-sources')), staleTime: 10 * 60_000 });

export const useWeatherCurrent = () =>
  useQuery({ queryKey: qk.weatherCurrent, queryFn: () => unwrap(api.GET('/weather/current')), staleTime: 5 * 60_000 });

export const useWeatherForecast = (hours = 24) =>
  useQuery({
    queryKey: qk.weatherForecast(hours),
    queryFn: () => unwrap(api.GET('/weather/forecast', { params: { query: { hours } } })),
    staleTime: 10 * 60_000,
  });

export const useModelStatus = () =>
  useQuery({ queryKey: qk.modelStatus, queryFn: () => unwrap(api.GET('/models/status')), staleTime: 30 * 60_000 });

/** Viewport-bbox overlays. `bbox` is null when the viewport is too large or outside the pilot. */
export const useHazards = (bbox: string | null) =>
  useQuery<HazardCollection>({
    queryKey: qk.hazards(bbox ?? ''),
    queryFn: () => unwrap(api.GET('/hazards', { params: { query: { bbox: bbox! } } })) as Promise<HazardCollection>,
    enabled: bbox !== null,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

export const useSegments = (bbox: string | null) =>
  useQuery<SegmentCollection>({
    queryKey: qk.segments(bbox ?? ''),
    queryFn: () =>
      unwrap(api.GET('/map/segments', { params: { query: { bbox: bbox! } } })) as Promise<SegmentCollection>,
    enabled: bbox !== null,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

export const useCompareRoutes = () =>
  useMutation({
    mutationFn: (body: RouteCompareRequest) => unwrap(api.POST('/routes/compare', { body })),
  });

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
  useMutation({ mutationFn: (body: PilotRequest) => unwrap(api.POST('/pilot-requests', { body })) });

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
