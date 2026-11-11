# WinterPath AI — web (apps/web)

Vite + React 18 + TypeScript SPA. Talks to the API only through the client generated from
`docs/contracts/openapi.yaml`; there is no routing or risk logic in the browser.

```bash
npm install
npm run gen:api        # regenerate src/api/schema.d.ts from the contract
npm run dev:mock       # http://localhost:5174 with MSW mocks ("Demo data" badges, SIMULATED labels)
npm run dev            # real API: set VITE_API_BASE_URL (e.g. http://localhost:8104/api/v1)
npm run lint && npm test && npm run build && npm run size
npx playwright test    # builds the mock app into dist-mock/ and runs e2e + axe (desktop + 390 px)
```

Env (all public, `VITE_*`): `VITE_USE_MOCKS`, `VITE_API_BASE_URL`, `VITE_MAP_STYLE_URL`
(default OpenFreeMap positron). Switching mocks ↔ real API is env-only.

Routes: `/en|fr/` · `/plan` · `/winter` · `/reports` · `/how-it-works` · `/pilot` · `/admin` (unlinked, noindex).

## Real-API e2e
Runs the production (non-mock) build against a live API. From the repo root, start the API on the
frontend's assigned port (fixture graph = real `data/fixtures/pilot_mini`, in-memory stores):

```bash
API_CORS_ORIGINS=http://localhost:5174 \
API_ADMIN_TOKEN_HASH=$(printf '<local test token>' | shasum -a 256 | cut -d' ' -f1) \
ROUTING_GRAPH_SOURCE=fixture API_STORE_BACKEND=memory RISK_PROVIDER=none \
uv run --project services/api uvicorn winterpath_api.main:app --host 127.0.0.1 --port 8104
```

then `cd apps/web && E2E_ADMIN_TOKEN='<local test token>' npm run e2e:real`
(`E2E_API_BASE_URL` overrides the default `http://localhost:8104/api/v1`).

The compare tests read the `risk_layer` from the API response and assert the matching copy, so the
suite also runs with the ML layer: `RISK_PROVIDER=winterpath_ml.inference:load_provider` plus
`MODEL_ARTIFACT_DIR=<path to models/artifacts>` (artifacts are git-ignored). Without them the provider
falls back to `none` and logs `risk_artifacts_missing`; check `GET /models/status` (`risk_layer`).

## Free-tier deployment (contract v1.7) — Cloudflare Pages
Nothing here deploys anything; the coordinator does that with the user's approval.

- **Pages settings:** root directory `apps/web`, build command `npm ci && npm run build`, output `dist`.
  Node comes from `.node-version` (24). There is deliberately no `404.html`, so Pages serves the SPA
  fallback; the build fails if one appears, or if any sourcemap is emitted.
- **Build env (public, baked into the bundle):** `VITE_API_BASE_URL` (the Render API, e.g.
  `https://<service>.onrender.com/api/v1`), `VITE_PUBLIC_WRITES=false` (read-only demo: the report and
  pilot forms are replaced by a "not available in this public demo" notice), optional
  `VITE_API_TIMEOUT_MS` (default 15000), optional `VITE_MAP_STYLE_URL`.
- **Headers:** `public/_headers` is a template; `build/cloudflarePages.ts` fills the CSP with the API
  origin from `VITE_API_BASE_URL`, the map style origin, OpenFreeMap, and hashes of `index.html`'s inline
  script. Also nosniff, `frame-ancestors 'none'`, Referrer-Policy, Permissions-Policy
  (`geolocation=(self)`), and one-year immutable cache for `/assets/*`. `vite preview` serves the same
  headers, so every e2e run happens under the production CSP. Non-mock builds drop `mockServiceWorker.js`.
- **Cold start:** Render Free sleeps after ~15 min idle. Network errors, timeouts and proxy 502/503/504
  without a WinterPath error body are retried with backoff (1, 2, 4, 8, then every 10 s) for about 90 s while a
  "server is waking up" banner shows; then a clear error with a retry button. Writes that timed out are
  never resent automatically. API answers (`UPSTREAM_UNAVAILABLE`, `WRITES_DISABLED`, …) are never retried
  as a cold start. Nothing is rendered from a partial answer (`INCOMPLETE`).
- **Tests:** `npm run e2e` (includes cold start, upstream-down, incomplete-answer, `WRITES_DISABLED`
  and CSP-violation checks via mock-only switches in `src/mocks/handlers.ts`) and `npm run e2e:readonly`
  (a `VITE_PUBLIC_WRITES=false` build).
