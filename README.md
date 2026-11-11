# WinterPath AI

Montréal-first, bilingual (EN/FR) pedestrian winter-navigation web product. *Navigate Montreal's winter, one better step at a time.*

WinterPath compares a shortest walking route with a winter-aware route through a pilot area of downtown Montréal, using open data: OpenStreetMap, Ville de Montréal sidewalks, closures and 311 requests, and Environment and Climate Change Canada weather. Every piece of route information carries an evidence label, so the app never presents a guess as a fact.

> **Status: pilot / pre-release (contract v1.6.0, 2026-11-11).** Runs locally. **Not deployed.** CI runs on GitHub Actions. The routes are decision support, not safety guarantees.

## What works today

| Area | State |
|---|---|
| Pedestrian graph | Real OSM data (Geofabrik `quebec-latest.osm.pbf`, clipped to the pilot bbox): **7 042 nodes / 16 846 directed edges**, enriched by Voirie sidewalk polygons. Stable edge IDs. |
| Routing API | FastAPI `/api/v1`: shortest vs winter-aware compare, `step_free` and `reduced_mobility` profiles, hard exclusion of edges blocked by active closures, `OFF_NETWORK` / `OUTSIDE_COVERAGE` errors, map layers, hazards, data sources, coverage. |
| Closures | Entraves permits with a three-valued "active at time t" rule (true / false / **unknown**). Unknown activity is flagged, never treated as clear. |
| 311 signal | Aggregated to H3 res-9 cells per day; cells with fewer than 3 reports are hidden in public output; no raw points stored or shown. |
| Risk layer | **Labelled heuristic only.** The ML model (HGB) **failed its evaluation gate** and is disabled. A logistic-regression candidate is pre-registered for an evaluation on winter 2026–27, not before 2027-05-08. See `models/gate.md` and `models/gate-logreg-2026.md`. |
| Weather | ECCC GeoMet adapter reading PostGIS. `/weather/current` returns **503** when the latest observation is older than 3 h. No scheduled ingestion yet, so expect 503 unless you ingest manually. |
| Community reports | Submit, moderate and delete (deletion token, 72 h expiry, admin bearer token). |
| Web app | Vite + React + TypeScript, EN/FR, MapLibre map (OpenFreeMap), lazy 3D hero with reduced-motion and no-WebGL fallbacks, demo mode with clearly badged mock data. Initial JS 143.9 KB gz. |

### Evidence states
`confirmed` · `unverified_report` · `model_estimate` · `unknown` · `simulated`. Each is shown with an icon and a text label. OSM accessibility tags count as `unverified_report`; demo data is always `simulated`.

### Pilot area
Downtown/McGill, EPSG:4326 bbox **−73.5880, 45.4960, −73.5620, 45.5130** (about 2 km × 1.9 km). Requests outside it return `422 OUTSIDE_COVERAGE`.

## Repository layout

```
apps/web/            React SPA (Frontend agent)
services/api/        FastAPI app (Routing agent)
services/routing/    routing core: graph, costs, Dijkstra/A* (Routing agent)
services/ingestion/  ETL: OSM, Voirie, 311, Entraves, ECCC → PostGIS (Data agent)
services/ml/         risk heuristic, model evaluation, gates (ML agent)
db/migrations/       Alembic migrations, schema `wp` (Data agent)
data/fixtures/       pilot_mini: 200 real OSM edges near McGill (ODbL)
models/              registry, model card, evaluations, gates (artifacts are git-ignored)
tests/integration/   smoke, privacy, CORS and Schemathesis contract tests (Platform agent)
infra/, docker-compose.yml, Makefile, .github/workflows/ci.yml   (Platform agent)
docs/                architecture, contracts (OpenAPI + data model), sources & licences, UX spec, agent briefs/reports
```

## Quick start (local)

Prerequisites: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 24 with npm, Docker.

```bash
cp .env.example .env.local          # fill in POSTGRES_PASSWORD etc.; never commit .env.local

# 1. Frontend only, with mock data (no backend needed)
cd apps/web && npm ci && npm run dev:mock      # http://localhost:5174, "Demo data" badges

# 2. API on the bundled 200-edge fixture (no database needed)
ROUTING_GRAPH_SOURCE=fixture API_STORE_BACKEND=memory RISK_PROVIDER=none \
  uv run --project services/api uvicorn winterpath_api.main:app --port 8104
cd apps/web && VITE_API_BASE_URL=http://localhost:8104/api/v1 npm run dev

# 3. Full pipeline with PostGIS
make up-db                                     # postgis/postgis:16-3.4
cd services/ingestion
uv run alembic -c ../../db/alembic.ini upgrade head
uv run wp-ingest osm && uv run wp-ingest voirie && uv run wp-ingest entraves \
  && uv run wp-ingest 311 && uv run wp-ingest eccc && uv run wp-ingest load
```

Raw downloads go to the git-ignored `data/raw/`. To enable the risk heuristic, set `RISK_PROVIDER=winterpath_ml.inference:load_provider` and `MODEL_ARTIFACT_DIR`, after generating artifacts with `uv run python -m winterpath_ml.evaluate` in `services/ml`. Without artifacts the API reports `risk_layer: none` and logs a warning. All environment variable names are listed in `.env.example`.

## Tests

```bash
make test        # integration harness (stub API) + every Python package + web unit tests
make lint        # ruff, eslint/tsc, actionlint, compose config
make secrets     # gitleaks over full history
make audit       # pip-audit + npm audit
cd apps/web && npx playwright test                                   # mock e2e (desktop + mobile, EN/FR, axe)
cd apps/web && npx playwright test -c playwright.real.config.ts      # e2e against a running API
```

Last full coordinator run (2026-11-11, all five agents merged): ingestion 50, routing 210 (1 skipped), ml 43 (1 skipped), API 92, web unit 107 tests passed; integration harness against the stub 59 passed (5 skipped); real-API e2e 16/16 with the heuristic risk layer on; 0 precise coordinates in API logs; gitleaks clean; `npm audit` 0 vulnerabilities.

## Not done yet / known limitations

- **Not deployed.** Vercel (web), Render (API) and Supabase (Postgres) compatibility is designed in; deployment needs explicit approval.
- **No scheduled jobs** for weather/closure/311 ingestion, daily scoring or report purging, so data goes stale until refreshed manually.
- **No geocoding:** origins and destinations are picked on the map.
- **Performance:** latency measured only on the 200-edge fixture (p95 about 8 ms) and on synthetic grids, not the full pilot graph. Page-load LCP is about 3 s against a 2.5 s target.
- **Accessibility:** automated axe checks pass; no manual screen-reader QA yet. That is not a WCAG compliance claim.
- **Data caveats:** 311 timestamps have no published timezone; 311 locations are obfuscated by the city; Voirie coverage is incomplete per its publisher; Entraves gives a permit point, not the exact blocked segment.
- **Legal:** ODbL share-alike obligations, ECCC/Canada.ca and OpenFreeMap terms, and font/3D-asset licences need review before any commercial launch. Not legal advice. Privacy design follows Québec Law 25 principles but has not had counsel review.
- Planif-Neige integration is opt-in and needs a city-issued token.

## How this repo is developed

Five Claude Code agents (Data, Routing, ML, Frontend, Platform) each work in their own git worktree on `agent/<name>`. A coordinator reviews, tests the combined result and merges into `integration/winterpath`, which is pushed as `main`. Contracts are versioned (`contract-v*` tags; changelog in `docs/contracts/integration-rules.md` §7).

```bash
scripts/create-worktrees.sh            # branches agent/<name> + ../winterpath-<name>
scripts/launch-winterpath-agents.sh    # tmux panes for the five agents
scripts/status-winterpath-agents.sh    # SHAs, dirty state, reports
scripts/check-ownership.sh <agent>     # merge gate: agent touched only its owned paths
scripts/merge-agent.sh <agent>         # coordinator: gated --no-ff merge
```

Nothing is pushed or deployed by these scripts.

## Documentation

- Spec: `WinterPath_AI_Revised_Claude_Master_Prompt.md`
- Architecture & ADRs: `docs/architecture.md`
- Contracts: `docs/contracts/openapi.yaml`, `docs/contracts/data-model.md`, `docs/contracts/integration-rules.md`
- Data sources & licences: `docs/data-sources-and-licenses.md`
- UX: `docs/ux-spec.md` · Agent briefs: `docs/agents/` · Agent reports: `docs/agent-reports/`

## Attribution

Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), available under the ODbL; OSM extract via Geofabrik. Basemap: OpenFreeMap © OpenMapTiles, data from OpenStreetMap. Contient des données de la Ville de Montréal, sous licence CC BY 4.0. Data Source: Environment and Climate Change Canada.

## License

No licence has been chosen for the code yet, so all rights are reserved. Third-party data keeps its own licence (see above and `docs/data-sources-and-licenses.md`).
