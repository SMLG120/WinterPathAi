# Environment variables

Names are defined in `.env.example` (names only; never commit values). Real values live in `.env.local` (local, git-ignored), the Render dashboard (API), GitHub Actions secrets (jobs) and the Cloudflare Pages build environment / direct-upload build (web).

**Every `VITE_*` variable is compiled into the public JavaScript bundle. Never put a secret, database URL or token in a `VITE_*` variable.**

## API (`services/api`, Render web service)

| Name | Local | Production (Render) | Secret |
|---|---|---|---|
| `PORT` | unset (uvicorn `--port`) | injected by Render (default 10000) | no |
| `DATABASE_URL` | local PostGIS | Supabase **session pooler** URL (IPv4), login role `wp_api`, `sslmode=require` | **yes** |
| `DATABASE_POOL_SIZE` / `DATABASE_MAX_OVERFLOW` | defaults | `3` / `2` | no |
| `ROUTING_GRAPH_SOURCE` | `fixture` | `postgis` | no |
| `ROUTING_FIXTURE_DIR` | optional | unset | no |
| `ROUTING_WORKERS` | `4` | `1` (0.1 CPU) | no |
| `ROUTING_STEPS_V2` | `false` | **`true`** since 2026-11-12 (merged, named steps; same Step shape; route geometry unchanged) | no |
| `ROUTING_COMPACT_GRAPH` | `false` | `false` (prototype) | no |
| `API_STORE_BACKEND` | `memory` | **`postgis`**: routing must read confirmed closures and 311 aggregates from `wp.closure` / `wp.report_311_cell`. With `memory`, production loads no hazards at all. This requires the API build in which writes-off keeps the community and pilot stores in memory, because `wp_reader` has no SELECT on `community_report` / `pilot_request` (PII). Before that build, `postgis` makes `/hazards` and `/routes/compare` return 503. Shipped in `8252f2e` (merged `129ffb7`); production runs `postgis` since 2026-11-11. | no |
| `API_PUBLIC_WRITES` | `true` | **`false`** (POST /reports, /pilot-requests → 503 `WRITES_DISABLED`) | no |
| `API_CORS_ORIGINS` | `http://localhost:5174` | exact production `https://<project>.pages.dev` (+ the specific preview alias if used); never `*` | no |
| `API_ADMIN_TOKEN_HASH` | test hash | SHA-256 of a token kept in a password manager | **yes** |
| `API_RATE_LIMIT_PER_MINUTE` | `60` | `60` | no |
| `API_LOG_LEVEL` | `INFO` | `info` | no |
| `RISK_PROVIDER` | `none` or `winterpath_ml.inference:load_provider` | `winterpath_ml.inference:load_provider` | no |
| `RISK_SCORE_SOURCE` | `file` | `postgis` (`wp.risk_cell_score`) | no |
| `MODEL_ARTIFACT_DIR` / `MODEL_REGISTRY_PATH` | local artifacts | image defaults (registry + committed coverage list only) | no |
| `WEATHER_SOURCE` | `none` | `postgis` | no |
| `WEATHER_MAX_AGE_MINUTES` | `180` | **`300`** since 2026-11-13: the 3-h cron plus ~1 h ECCC publication lag plus GitHub delays left observations 3–4 h old, so health flapped `degraded` at 180 | no |
| `WEATHER_STATION_IDS` | empty | `7025251,702S006` (priority order) | no |
| `WEATHER_LIVE_ENABLED` | `false` | `true` (v1.8: live ECCC forecast/alerts in API memory) | no |
| `WEATHER_LIVE_USER_AGENT` | `WinterPathAI-API/1.8` | default (generic, no personal contact) | no |
| `GEOCODER_PROVIDER` / `GEOCODER_API_KEY` | empty | empty (no geocoder in v1; map-pin selection) | key: yes |
| `HTTP_USER_AGENT` | `WinterPathAI/dev` | not needed by the API | no |

## Scheduled jobs (GitHub Actions secrets)

| Secret | Use |
|---|---|
| `WP_ETL_DATABASE_URL` | Supabase session pooler URL, login role `wp_etl` (member of `wp_writer`). Used by weather ingest and scoring. |
| `HTTP_USER_AGENT` (variable, not secret) | identifying User-Agent for ECCC / Ville de Montréal downloads |

## Scheduler (Cloudflare Worker `winterpath-scheduler`, `infra/cron-worker/`)

| Name | Value | Secret |
|---|---|---|
| `GITHUB_REPO` / `GITHUB_WORKFLOW` / `GITHUB_REF` | `SMLG120/WinterPathAi` / `scheduled.yml` / `main` (`wrangler.toml` vars) | no |
| `GITHUB_DISPATCH_TOKEN` | fine-grained PAT: this repository only, **Actions: Read and write**, nothing else; set with `wrangler secret put` | **yes** |

Migrations are run manually by the coordinator with the `wp_migrate` role (never from the API or scheduled jobs).

## Web (`apps/web`, Cloudflare Pages)

| Name | Local | Production | Notes |
|---|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:8104/api/v1` | `https://<service>.onrender.com/api/v1` | public |
| `VITE_MAP_STYLE_URL` | OpenFreeMap style URL | OpenFreeMap style URL (replaceable) | public |
| `VITE_PUBLIC_WRITES` | `true` | **`false`** | public; hides report/pilot forms |
| `VITE_API_TIMEOUT_MS` | `15000` | `15000` | public |
| `VITE_USE_MOCKS` | `true` for `dev:mock` | **must be unset/false** | public |

## Environments

| Environment | Web | API | DB |
|---|---|---|---|
| Local | Vite dev / preview on 5173–5175 | uvicorn on 8100–8105 | Docker PostGIS `winterpath-db-1` |
| Preview | Cloudflare Pages preview deployment (branch alias) | same Render service (no second free service) | same Supabase project |
| Production | Cloudflare Pages `https://winterpath.pages.dev` | Render `winterpath-api` (`https://winterpath-api.onrender.com`) | Supabase project `WinterPathAI` (us-east-1) |

Preview deployments talk to the production API only if their exact origin is added to `API_CORS_ORIGINS`; by default only the production origin is allowed.

## Deployment credentials (operator machine only)
`.env.deploy` (git-ignored by `.env.*`, mode 600): `SUPABASE_ACCESS_TOKEN`, `RENDER_API_KEY`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`. Never printed, never committed, never copied into CI.
