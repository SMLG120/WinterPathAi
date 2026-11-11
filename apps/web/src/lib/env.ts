/** Runtime configuration. Switching between mocks and the real API is env-only. */
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true';

export const API_BASE_URL = (USE_MOCKS ? '/api/v1' : import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '');

/** v1.7: `false` = read-only public demo — report and pilot forms are replaced by a notice. */
export const PUBLIC_WRITES = import.meta.env.VITE_PUBLIC_WRITES !== 'false';

const timeout = Number(import.meta.env.VITE_API_TIMEOUT_MS);
/** Per-request timeout (v1.7, default 15 s). */
export const API_TIMEOUT_MS = Number.isFinite(timeout) && timeout > 0 ? timeout : 15_000;

/**
 * Total time spent retrying while a sleeping free-tier backend wakes (~1 min) before giving up.
 * Mock builds only: e2e may shorten it via localStorage `wp-mock-wake-budget-ms` (compiled out of real builds).
 */
export const WAKE_BUDGET_MS = (() => {
  if (USE_MOCKS) {
    try {
      const v = Number(localStorage.getItem('wp-mock-wake-budget-ms'));
      if (Number.isFinite(v) && v > 0) return v;
    } catch {
      /* storage blocked */
    }
  }
  return 90_000;
})();

/** OpenFreeMap (ADR-3). Never tile.openstreetmap.org. */
export const MAP_STYLE_URL = import.meta.env.VITE_MAP_STYLE_URL || 'https://tiles.openfreemap.org/styles/positron';

export { PILOT_BBOX } from './pilot';

/** Max bbox area accepted by /hazards and /map/segments (openapi Bbox parameter). */
export const MAX_BBOX_AREA_DEG2 = 0.0025;

/** Freshness threshold after which a datum is shown as stale. */
export const STALE_AFTER_MS = 6 * 60 * 60 * 1000;
