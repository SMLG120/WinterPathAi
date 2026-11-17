# Agent D (mapux): report

Branch `agent/mapux` (from `integration/winterpath` @ `e581535`). Code commit: `ee7e518`.
Status: **READY FOR REVIEW**. Nothing pushed, merged or deployed.

## What changed (Plan page map)
| Area | Change |
|---|---|
| Markers | Start = teal **circle "A"**, destination = navy **square "B"** (shape, letter and text differ, not just colour). A **searched place** is a hollow, dashed **pin** with the place name, anchored at its tip, with the accessible name "…searched place "X". Approximate: the route starts from the nearest walkable path, if one is within 75 m." Markers are `role=img`, have no tab stop and `pointer-events:none`, so clicks pass through to the map. |
| Endpoint metadata | `features/map/endpoints.ts` reads **optional** store fields (`originMeta`/`destinationMeta` `{label, source}` or `originLabel`/`originSource` and the same for destination), or an optional `endpoints` prop. With neither, behaviour is unchanged. |
| Route alternatives | One `routes` source, `promoteId: variant`. Selection and hover are feature state, so there is no `setData` on select or hover. The selected route is thicker, opaque and on top. An invisible 18 px (touch: 32 px) hit layer makes the lines easy to point at. **Clicking a route line selects it and no longer moves the destination.** While picking a point, clicks still pick. |
| Sync | `features/map/routeHighlight.ts` (zustand): pointing at or focusing a compact card or a details card highlights its line; pointing at a line highlights both cards (`data-hovered`). Selection still goes through the planner store (`setSelected`). |
| Coverage boundary | Outside area is dimmed and hatched, and the boundary has a cased navy outline, taken from `GET /coverage.area`. `coverageArea.ts` accepts **Polygon and MultiPolygon** (each outer ring is cut out of the mask, holes are filled back in) and falls back to the bbox, never to "everything served". |
| Fit | Fits the selected route plus both markers. Padding per side is the larger of the caller's (sheet) padding and the room the controls need, plus the measured height of the top-left stack (attribution + chip) on mobile, then clamped. Routes over 10 km fly for 900 ms; reduced motion → 0. |
| Status chip | A MapLibre control in the attribution corner (mobile top-left, desktop bottom-left) shows: computing routes · zoom in · outside area · loading · updating · fresh (time) · cached (time) · stale (time, amber) · unavailable / error (red border, "showing the last view that loaded" when old data remains, 44 px **Retry**). Mobile hides only "fresh". Derived from the TanStack Query cache by `useOverlayQueryStatus()` → pure `overlayStatus()`, which can be swapped for C's freshness metadata. |
| Cards / details | New winter-condition **data-coverage bar** (known / hatched unknown, text and `aria-label`). It names the source (model / heuristic estimate). "Mostly unknown" appears at ≥ 50 %. With `risk_layer: none` the bar shows the **whole route as unknown** and says "No risk layer active: conditions are not assessed". No safety wording. The details "Show on map" button is 44 px on mobile. |
| Legend | Start/destination/searched-place shapes, selected vs alternative line, "unknown is not low risk", boundary + hatched outside area, coverage name, network build date, OSM snapshot, known gaps (from `/coverage`, with loading and error text). |
| Mobile | Zoom buttons are 44 × 44 on coarse pointers and moved below the page's recenter button, with no overlap (asserted). The fitted route stays above the half sheet (asserted). |
| Performance | `PlannerMap` is `memo` with by-value comparison of `fitPadding` and `endpoints`. The map is created once (`data-map-inits`, asserted = 1 after compare, select, hover, pan and layer toggles). Hover is applied through a store subscription with no React render. The chip re-renders only when its status string changes. |
| i18n | New `map` namespace (en/fr) registered in `src/i18n/index.ts`; parity tests cover it. |

## Test fixtures (labelled)
`src/features/map/fixtures/` are **TEST FIXTURES**: hand-drawn shapes and a synthetic route, every explanation `simulated`. They are switched on per test by localStorage `wp-mock-fixture`:
- `island-long`: MultiPolygon coverage (2 parts, 1 hole) and a ~20 km Downtown → Pointe-Claire-area synthetic route (unknown share 43 % / 70 %, `risk_layer: heuristic`).
- `overlays-down`: `/map/segments` and `/hazards` → 503 `UPSTREAM_UNAVAILABLE`.

They are registered with one line in `src/mocks/browser.ts`; without the flag the handlers fall through.

## Files touched outside the core list (small, flagged)
- `src/mocks/browser.ts`: prepends the inert fixture handlers.
- `src/i18n/index.ts`: registers the `map` namespace (as briefed).
- `playwright.config.ts`: `E2E_PORT` env (default 5174) so worktrees can run e2e side by side. This run used 5178.
- `e2e/pages.spec.ts`: three hard-coded `http://localhost:5174` URLs now follow `E2E_PORT`. With E2E_PORT=5178 they failed with `ERR_CONNECTION_REFUSED`; behaviour is unchanged at the default port.
- A test-only hook `window.__wpPlannerMap` is set **only when `USE_MOCKS`** (compiled out of real builds), so e2e can project lon/lat to pixels.

## Literal results (apps/web, 2026-11-16)
```
> @winterpath/web@0.1.0 typecheck
> tsc -b --noEmit
> @winterpath/web@0.1.0 lint
> eslint . --max-warnings 0
 RUN  v4.1.12 /Users/smlgmac/Projects/Geography/winterpath-mapux/apps/web
 Test Files  21 passed (21)
      Tests  186 passed (186)
```
Baseline before changes: 20 files / 161 tests passed.

Full Playwright suite, `E2E_PORT=5178 npx playwright test` (projects `desktop` and `mobile-390`, MSW mock build):
```
[throttled desktop] panel heading 4724 ms, map ready 6046 ms
  ✓   12 [desktop] › e2e/mapux.spec.ts:197:1 › throttled network (slow 3G-like): planner usable before the map, then map, route and status arrive (16.6s)
[throttled mobile] panel heading 4758 ms, map ready 6627 ms
  ✓   88 [mobile-390] › e2e/mapux.spec.ts:197:1 › throttled network (slow 3G-like): planner usable before the map, then map, route and status arrive (18.1s)
  5 skipped
  147 passed (7.7m)
```
The 5 skips are viewport-specific tests (desktop-only or mobile-only). The throttle is CDP `Network.emulateNetworkConditions`: 400 ms latency, 94 000 B/s down, 32 000 B/s up. Responses served by the MSW service worker are not throttled; only network assets (JS chunks) are.

Screenshots (`apps/web/test-results/mapux/`; the directory is gitignored and is overwritten by each run): `long-route-{desktop,mobile}.png`, `route-selected-from-map-{desktop,mobile}.png`, `mobile-fit-mobile.png`, `overlay-unavailable-{desktop,mobile}.png`, `throttled-{desktop,mobile}.png`.

## Requests
**Agent A (Plan.tsx / stores/planner.ts / search)**
1. Expose endpoint metadata in the store, e.g. `originMeta` / `destinationMeta: { label: string | null; source: 'map' | 'coordinates' | 'geolocation' | 'recent' | 'search' } | null`. Reset it when the point is set by any other means. Or pass `endpoints={{ origin: …, destination: … }}` to `<PlannerMap>`. The map then shows searched places as dashed pins automatically.
2. When a route is chosen while the sheet is `full`, drop to `half` so the re-fitted route is visible:
   ```tsx
   // Plan.tsx, CompareCard onSelect
   onSelect={(v) => { s.setSelected(v); if (!desktop && snap === 'full') setSnap('half'); }}
   ```
3. Optional: `overlayMsg` in the panel partly duplicates the map chip. `useOverlayQueryStatus()` from `@/features/map/dataStatus` can drive both. If the recenter button moves from `top-[86px]`, update `features/map/map.css` (touch zoom buttons sit at margin-top 140 px).

**Agent C (api/**)**
1. Freshness metadata: anything shaped like `QueryLike` (`status`, `fetchStatus`, `dataUpdatedAt`, `hasData`, `isPlaceholderData`, `error`), plus optional server-side freshness, can replace the cache adapter in `dataStatus.ts` (`useOverlayQueryStatus`) without UI changes.
2. Coordinator / contract: `Coverage.area` as `oneOf: [Polygon, MultiPolygon]` would let the island outline stop merging nearby islands. The map already supports it. `lib/coverage.ts setCoverage` still only takes a Polygon ring; the map no longer depends on that ring.

**Mock owner / coordinator**
- `mocks/routes.ts` returns `risk_layer: 'none'` with `unknown_share` 0.25 / 0.4, which is inconsistent. The UI now shows the bar fully unknown in that case, while the card text still quotes the API share.

## Open issues
- Not tested against the real API (port 8108) or the island graph; long routes use the synthetic fixture only.
- Hover sync on touch devices is focus/tap-based. There is no long-press preview.
- Known-gap geometries from `/coverage` are listed in the legend, not drawn. In mock mode the gap covers almost the whole pilot area, and drawing it would hide the boundary.
- No axe run was added specifically for the new chip and legend. The existing `pages.spec.ts` axe checks pass.
