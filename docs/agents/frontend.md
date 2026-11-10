# Agent 4 — Frontend, UI/UX & 3D Engineer

Branch `agent/frontend` · worktree `../winterpath-frontend` · web port 5174, mock API 8104.
**Owns:** `apps/web/`, `assets/3d/`, `apps/web/ASSET_LICENSES.md`, `docs/agent-reports/frontend.md`.
**Read first:** `CLAUDE.md`, `docs/ux-spec.md`, `docs/contracts/openapi.yaml`, `docs/architecture.md` §8–9.

## Dependencies & mocks
- API types: generate with `openapi-typescript ../../docs/contracts/openapi.yaml -o src/api/schema.d.ts`; thin typed fetch client. No routing/risk logic in the browser.
- Mock mode (`VITE_USE_MOCKS=true`): MSW handlers returning schema-valid payloads. Every mock-backed view shows a visible **"Demo data"** badge; anything simulating conditions shows **SIMULATED**.
- Map style: OpenFreeMap (`https://tiles.openfreemap.org/styles/positron` / `liberty`) — keep attribution control visible. No tile.openstreetmap.org, no public Nominatim.

## Steps
1. Scaffold Vite + React + TS in `apps/web` (npm). Tailwind, shadcn/ui, TanStack Query, Zustand, RHF + Zod, i18next, Motion, react-router with `/en` `/fr` prefixes.
2. Design tokens + light/dark from ux-spec; evidence-badge component; layout, nav, footer with attributions.
3. Pages per ux-spec table: Landing, Plan, Winter, Reports, How it works, Pilot (+ hidden Admin moderation).
4. `/plan`: MapLibre map, map-click origin/destination, consent-gated geolocation, manual coordinate entry, profile select, compare card, overlays (`/hazards`, `/map/segments` by viewport bbox, debounced), legend, step list, mobile bottom sheet. Handle 404 NO_ROUTE / 422 OUTSIDE_COVERAGE with helpful copy.
5. 3D hero: original low-poly scene built from primitives/merged geometry or self-authored GLB (gltf-transform compressed) under `assets/3d/`; lazy + Suspense, poster fallback, reduced-motion and no-WebGL fallback; budgets from ux-spec.
6. Full EN/FR copy (no machine-translation placeholders left as English); key-parity test.
7. Tests: Vitest for components/stores/i18n parity; Playwright: bilingual planning journey against mocks, geolocation-denied journey, axe scan per page.

## Acceptance criteria
- All six pages render in EN and FR, desktop + 390 px mobile, light + dark.
- Planner works end-to-end against mocks; switching to real API is env-only.
- Evidence states displayed with icon + text everywhere; no unlabelled demo data.
- `npm run build`, `npm run lint`, `npm test`, `npx playwright test` pass (literal output in report); bundle sizes reported.
- Asset/font licence manifest complete.

## Stop conditions
Need a contract change → change request; do not edit `docs/contracts/`. No proprietary 3D models, no stock assets without verified commercial licence.

## Completion report — `docs/agent-reports/frontend.md`
Status · SHA · screenshots paths (optional) · literal test/build output · bundle sizes · licence manifest summary · blockers · review readiness.
