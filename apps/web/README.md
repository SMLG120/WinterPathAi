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
suite also runs with the ML layer: `RISK_PROVIDER=winterpath_ml.inference:load_provider`. That
provider needs the git-ignored artifacts under `models/artifacts/<run_id>/`; without them it falls
back to `none` without logging anything (check `GET /models/status`).
