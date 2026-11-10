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
