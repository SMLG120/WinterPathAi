/** Runtime configuration. Switching between mocks and the real API is env-only. */
export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true';

export const API_BASE_URL = (USE_MOCKS ? '/api/v1' : import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '');

/** OpenFreeMap (ADR-3). Never tile.openstreetmap.org. */
export const MAP_STYLE_URL = import.meta.env.VITE_MAP_STYLE_URL || 'https://tiles.openfreemap.org/styles/positron';

/** Pilot bbox from docs/architecture.md §3 — used only for client-side UX hints; the API is authoritative. */
export const PILOT_BBOX = { west: -73.588, south: 45.496, east: -73.562, north: 45.513 } as const;

/** Max bbox area accepted by /hazards and /map/segments (openapi Bbox parameter). */
export const MAX_BBOX_AREA_DEG2 = 0.0025;

/** Freshness threshold after which a datum is shown as stale. */
export const STALE_AFTER_MS = 6 * 60 * 60 * 1000;
