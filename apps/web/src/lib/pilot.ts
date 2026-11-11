/** Pilot bbox from docs/architecture.md §3 — used only for client-side UX hints; the API is authoritative.
 *  Kept free of `import.meta.env` so Node-side test tooling (Playwright) can import it. */
export const PILOT_BBOX = { west: -73.588, south: 45.496, east: -73.562, north: 45.513 } as const;
