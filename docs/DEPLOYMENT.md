# Deployment (free-tier public demo)

Status as of 2026-11-11. Limits and their sources: `docs/FREE_TIER_LIMITS.md`. Variables: `docs/ENVIRONMENT_VARIABLES.md`. Recovery: `docs/RECOVERY.md`.

```
 Browser ──HTTPS──► Cloudflare Pages (static SPA, _headers CSP)          [BLOCKED: token has no account access]
    │
    ├──HTTPS──► tiles.openfreemap.org (basemap style + tiles)
    │
    └──HTTPS──► Render free web service  winterpath-api  (Virginia, Docker, 0.1 CPU / 512 MB)
                   │  https://winterpath-api.onrender.com/api/v1
                   └──TLS, session pooler :5432, role wp_api (read-only)──►
                        Supabase Free  WinterPathAI  (us-east-1, Postgres 17, PostGIS 3.3.7 in `extensions`)
                             ▲
 GitHub Actions (scheduled.yml) ──TLS, role wp_etl──┘   weather ingest (ECCC) + daily risk scoring
```

| Component | State | Identifier |
|---|---|---|
| Database | **Deployed**: migrated to `0007_risk_cell_score`, data loaded | Supabase project `WinterPathAI`, us-east-1 |
| API | **Deployed and live** | Render `srv-dbqbv3ui0phs73c82qng`, `https://winterpath-api.onrender.com` |
| Web | **Built and checked locally; not deployed**. The Cloudflare API token verifies as active but can see 0 accounts. | Pages project `winterpath` (to be created) |
| Scheduled jobs | **Configured**. Weather job verified (run 43084925719); scoring fixed in `cb5226a`, re-run 43086426247 | `.github/workflows/scheduled.yml`, secret `WP_ETL_DATABASE_URL` |

## 1. Database (Supabase Free)
1. Create the project and enable PostGIS **in schema `extensions`**.
2. Create roles following `infra/SUPABASE.md`:
   - group roles `wp_reader`, `wp_writer`, `wp_migrator`;
   - login roles `wp_api` (`default_transaction_read_only=on`), `wp_etl`, `wp_migrate`;
   - each login role gets `search_path = public, extensions`.
3. Connect only through the **session pooler** (`aws-1-<region>.pooler.supabase.com:5432`, user `<role>.<project-ref>`, `sslmode=require`). The direct host is IPv6-only.
4. Migrate as `wp_migrate`: `DATABASE_URL=<wp_migrate pooler URL> uv run alembic upgrade head` (in `services/data`).
5. Load the data as `wp_etl`, using the operator's processed data:
   `DATA_DIR=… DATABASE_URL=<wp_etl URL> uv run wp-ingest load --weather-since <one year ago>`
   The 2026-11-11 load gave 7,042 nodes, 16,846 edges, 1,495 sidewalk polygons, 167 closures, 70,428 311 cell-days, 16,678 weather observations and 3,550 daily weather rows, plus 2,930 heuristic risk scores. The database is 49 MB of the 500 MB limit.

## 2. API (Render Free)
- Create the service through the API or dashboard:
  - type `web_service`, runtime `docker`, plan `free`, region `virginia`;
  - repo `SMLG120/WinterPathAi`, branch `main`, **autoDeploy off**;
  - Dockerfile `./infra/docker/api.Dockerfile`, context `.`, health check `/api/v1/health`.
  - `infra/render.yaml` describes the same service as a blueprint.
- Environment: see `docs/ENVIRONMENT_VARIABLES.md`. Production uses:
  - `API_STORE_BACKEND=postgis` so closures and 311 hazards are read;
  - `API_PUBLIC_WRITES=false`;
  - `RISK_SCORE_SOURCE=postgis` and `WEATHER_SOURCE=postgis`;
  - `ROUTING_WORKERS=1`;
  - `DATABASE_POOL_SIZE=3` and `DATABASE_MAX_OVERFLOW=2`.
- `API_CORS_ORIGINS` must be the exact Pages origin once the web app exists.
- Deploy: `POST /v1/services/<id>/deploys {"commitId": "<full 40-char SHA>"}`. Short SHAs are rejected.
- Verify with `GET /api/v1/health`: every check should be `ok`. Then run one `/routes/compare` and check that `POST /reports` returns 503 `WRITES_DISABLED`.

## 3. Web (Cloudflare Pages, direct upload)
```bash
cd apps/web && npm ci
VITE_API_BASE_URL=https://winterpath-api.onrender.com/api/v1 VITE_PUBLIC_WRITES=false \
VITE_MAP_STYLE_URL=https://tiles.openfreemap.org/styles/positron VITE_API_TIMEOUT_MS=15000 \
npm run build:pages          # refuses unsafe env; checks dist/ for maps, mocks, secrets, headers
npx wrangler pages project create winterpath --production-branch main   # once
npx wrangler pages deploy dist --project-name winterpath --branch main
```
- `wrangler` needs `CLOUDFLARE_API_TOKEN` (permission **Account → Cloudflare Pages → Edit**, scoped to the account) and `CLOUDFLARE_ACCOUNT_ID`.
- Then set Render `API_CORS_ORIGINS=https://winterpath.pages.dev` (the exact origin wrangler prints) and redeploy the API.

## 4. Scheduled jobs (GitHub Actions)
- Secret `WP_ETL_DATABASE_URL`: the wp_etl pooler URL.
- `scheduled.yml` runs weather ingest and daily scoring; scoring uses `--fetch-311 --write-db`. To run it manually: `gh workflow run scheduled.yml -f job=both`.
- These are real data jobs, not keep-alive pings. They also keep the Supabase project active.

## What must never happen
- No `VITE_*` secrets; no `*` CORS.
- No paid plan and no payment method added for overage.
- No public Nominatim; no deserialising untrusted model files in the API.
- Never use the Supabase `postgres` credentials in the API or CI.
