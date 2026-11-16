/**
 * Loading / cached / stale / unavailable / error state of the map overlays (sidewalk segments and
 * hazards), derived from TanStack Query state only.
 *
 * `overlayStatus()` is pure and takes a minimal query-like object, so once the query hooks expose
 * their own freshness metadata it can be fed from that instead (swap `useOverlayQueryStatus`).
 */
import { useEffect, useState, useSyncExternalStore } from 'react';
import { useQueryClient, type Query } from '@tanstack/react-query';

export type DataStatus =
  /** Layer off, zoomed out, or outside coverage: nothing requested. */
  | 'off'
  /** First request for this view in flight, nothing to show yet. */
  | 'loading'
  /** Showing the previous view's (or an older) answer while the new one loads. */
  | 'updating'
  /** Answer received within the query's freshness window. */
  | 'fresh'
  /** Answer reused from this browser's cache (older than the freshness window, not re-requested). */
  | 'cached'
  /** Cached answer older than STALE_OVERLAY_MS. */
  | 'stale'
  /** The API said the service is unavailable (503) or the network/timeout failed. */
  | 'unavailable'
  /** Any other failure. */
  | 'error';

export type QueryLike = {
  status: 'pending' | 'error' | 'success';
  fetchStatus: 'fetching' | 'paused' | 'idle';
  dataUpdatedAt: number;
  hasData: boolean;
  isPlaceholderData?: boolean;
  error?: unknown;
};

export type OverlayStatus = { status: DataStatus; updatedAt: number | null; hasData: boolean };

/** Same as the query hooks' staleTime (api/queries.ts: 60 s). */
export const FRESH_OVERLAY_MS = 60_000;
/** Beyond this a cached overlay is called stale (closures/311 change within the day). */
export const STALE_OVERLAY_MS = 15 * 60_000;

const UNAVAILABLE = new Set(['UPSTREAM_UNAVAILABLE', 'SERVICE_UNAVAILABLE', 'NETWORK', 'TIMEOUT', 'WAKE_TIMEOUT', 'WRITES_DISABLED']);

function isUnavailable(e: unknown): boolean {
  if (!e || typeof e !== 'object') return false;
  const x = e as { status?: unknown; code?: unknown };
  return x.status === 503 || x.status === 0 || (typeof x.code === 'string' && UNAVAILABLE.has(x.code));
}

export function overlayStatus(q: QueryLike | undefined, now = Date.now()): OverlayStatus {
  if (!q) return { status: 'off', updatedAt: null, hasData: false };
  const updatedAt = q.dataUpdatedAt > 0 ? q.dataUpdatedAt : null;
  const base = { updatedAt, hasData: q.hasData };
  if (q.fetchStatus === 'fetching') return { ...base, status: q.hasData ? 'updating' : 'loading' };
  if (q.status === 'error') return { ...base, status: isUnavailable(q.error) ? 'unavailable' : 'error' };
  if (q.isPlaceholderData) return { ...base, status: 'updating' };
  if (q.status === 'pending') return { ...base, status: q.fetchStatus === 'paused' ? 'unavailable' : 'loading' };
  const age = updatedAt === null ? Infinity : now - updatedAt;
  return { ...base, status: age > STALE_OVERLAY_MS ? 'stale' : age > FRESH_OVERLAY_MS ? 'cached' : 'fresh' };
}

/** Worst of several layer states (what one map chip should say). */
const RANK: DataStatus[] = ['off', 'fresh', 'cached', 'updating', 'loading', 'stale', 'unavailable', 'error'];
export function combineStatus(list: OverlayStatus[]): OverlayStatus {
  const on = list.filter((s) => s.status !== 'off');
  if (!on.length) return { status: 'off', updatedAt: null, hasData: false };
  const worst = on.reduce((a, b) => (RANK.indexOf(b.status) > RANK.indexOf(a.status) ? b : a));
  const times = on.map((s) => s.updatedAt).filter((x): x is number => x !== null);
  // Oldest data shown decides the timestamp.
  return { status: worst.status, hasData: on.some((s) => s.hasData), updatedAt: times.length ? Math.min(...times) : null };
}

/** The enabled ("active") query of a key prefix, i.e. the one for the current viewport. */
function activeQueryLike(queries: Query[]): QueryLike | undefined {
  const q = queries.find((x) => x.isActive());
  if (!q) return undefined;
  const st = q.state;
  // keepPreviousData: the observer shows another key's data while this one has none yet.
  const placeholder = st.data === undefined && queries.some((x) => x !== q && x.state.data !== undefined);
  return {
    status: st.status,
    fetchStatus: st.fetchStatus,
    dataUpdatedAt: st.dataUpdatedAt,
    hasData: st.data !== undefined || placeholder,
    isPlaceholderData: placeholder,
    error: st.error,
  };
}

/**
 * Adapter: current overlay status read from the shared query cache for the given key prefixes
 * (default: the `segments` and `hazards` viewport queries). Re-renders only when the derived
 * status string changes, plus once a minute so "fresh" can age into "cached"/"stale".
 */
export function useOverlayQueryStatus(prefixes: readonly string[] = ['segments', 'hazards']): OverlayStatus & { retry: () => void } {
  const qc = useQueryClient();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(id);
  }, []);
  const snapshot = () => {
    const parts = prefixes.map((p) => overlayStatus(activeQueryLike(qc.getQueryCache().findAll({ queryKey: [p] })), now));
    const s = combineStatus(parts);
    return `${s.status}|${s.updatedAt ?? ''}|${s.hasData ? 1 : 0}`;
  };
  const key = useSyncExternalStore((cb) => qc.getQueryCache().subscribe(cb), snapshot, snapshot);
  const [status, updatedAt, hasData] = key.split('|');
  return {
    status: status as DataStatus,
    updatedAt: updatedAt ? Number(updatedAt) : null,
    hasData: hasData === '1',
    retry: () => void qc.refetchQueries({ predicate: (q) => prefixes.includes(String(q.queryKey[0])), type: 'active' }),
  };
}
