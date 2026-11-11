# WinterPath AI — Architecture & Decision Record (contract v1)

Status: **baseline v1**, 2026-11-10. Owner: coordinator.

## 1. Audit findings that shaped this baseline

| Finding | Consequence |
|---|---|
| `~/Projects/Geography/WinterPathAi` contained only the spec. No code, manifests, tests, CLAUDE.md or deploy config. | Greenfield. No existing code to preserve; no Next.js app → **Vite** chosen (ADR-1). |
| `~/Projects` is itself a Git repo with **no commits**, every project untracked, no remote. | WinterPath gets its **own** repo at `~/Projects/Geography/WinterPathAi`. The parent repo was not modified. Worktrees live beside it: `~/Projects/Geography/winterpath-<name>`. |
| Tools: git 2.52, tmux 3.8, Claude Code 2.1.322 (logged in, claude.ai), Python 3.12.13 + 3.14.3, uv 0.10.7, Node 24.13 / npm 11.6, Docker 29.5.3, psql 18.3, gh 2.93. Missing: pnpm, GDAL `ogr2ogr`. | Python 3.12 via uv; npm (no pnpm); GDAL used through Python wheels (pyogrio), not CLI. |
| Docker Desktop is **paused**. | PostGIS cannot run until the user unpauses Docker. Agents use fixtures and in-memory graphs until then. |
| Existing tmux sessions `13`, `14`, `siuuu` (attached). | The `winterpath` session name is free; launch script refuses to touch other sessions. |

## 2. System overview

```
Browser (apps/web, Vite+React+TS)
  ├─ MapLibre GL ── vector tiles: OpenFreeMap (no key, commercial OK, attribution required)
  ├─ R3F/Drei 3D hero (lazy, reduced-motion & no-WebGL fallback)
  └─ typed client generated from docs/contracts/openapi.yaml  ──HTTPS──┐
                                                                       ▼
services/api (FastAPI, /api/v1) ── routing core (services/routing, NetworkX A*/Dijkstra over pilot graph)
     │                          └─ ml inference interface (services/ml, read-only artifacts)
     ▼
PostGIS (db/migrations, Alembic)  ◄── services/ingestion (idempotent ETL: OSM, Voirie, 311, Entraves, ECCC)
```

- **No routing logic in the browser.** The browser renders what the API returns.
- **Geocoding** goes through a backend endpoint only (future; v1 uses manual map pick + a provider adapter interface with no default provider). Public Nominatim is **forbidden** for autocomplete (verified policy, see data-sources doc).
- Redis is **not** part of v1.

## 3. Pilot area

`PILOT_BBOX` (McGill / downtown Montréal), EPSG:4326: **west −73.5880, south 45.4960, east −73.5620, north 45.5130** (~2.0 km × 1.9 km). Routes with either endpoint outside the bbox return `422 OUTSIDE_COVERAGE`. Coverage may be expanded only by a contract change.

## 4. Coordinate systems
- Wire format: EPSG:4326, `[lon, lat]`.
- Metric work: **EPSG:32188** (NAD83 / MTM zone 8 — Montréal's municipal projection).
- Storage: geometries stored in 4326 with GiST indexes; metric columns (`length_m`) precomputed in 32188.

## 5. Routing model
Graph: directed multigraph of pedestrian edges (see data-model). Cost per edge for profile *p*:

```
cost_s = base_walk_s                      (length_m / walk_speed_mps; default 1.3 m/s, 0.9 m/s for "reduced_mobility")
       + disruption_penalty_s             (only from evidence_state = confirmed disruptions that do not prohibit passage)
       + risk_penalty_s                   (only from model_estimate or heuristic layer; unknown → documented unknown_penalty, never 0-risk)
       + preference_penalty_s             (soft preferences, e.g. avoid unlit)
```
Hard exclusions (edge removed, never penalised): `foot=no`, access private/no, confirmed sidewalk closure with no passage, crossings flagged prohibited, and for `step_free` profile any edge with steps or unverified kerb (`accessibility.step_free != true`).
Algorithms: Dijkstra baseline (shortest distance, shortest time), A* with haversine heuristic for winter-aware. All weights ≥ 0, unit = seconds.

## 6. Evidence states (used everywhere)
`confirmed` · `unverified_report` · `model_estimate` · `unknown` · `simulated`. Defined in OpenAPI `EvidenceState`. UI must render each with a distinct icon + text label (not colour only). Route explanation codes map to states as documented in OpenAPI `Route.explanation` (v1.5). OSM accessibility tags are community-mapped and count as `unverified_report`, never `confirmed`.

## 7. ADRs
- **ADR-1 Vite over Next.js** — greenfield, SPA + separate FastAPI; no SSR requirement; spec preference. 
- **ADR-2 Own repo** — avoids entangling the uncommitted `~/Projects` mega-repo; worktrees isolated.
- **ADR-3 Basemap = OpenFreeMap** for dev/pilot (verified: free, commercial use allowed, attribution required, no SLA). Production fallback: self-hosted Protomaps PMTiles (ODbL produced work). Never `tile.openstreetmap.org` as a CDN.
- **ADR-4 Graph source of truth = OSM** from the **Geofabrik Québec extract** (user decision 2026-11-10; public Overpass not used in the pipeline) — ways with legal foot access + crossings; `service`/`cycleway` only with explicit foot permission; indoor RÉSO corridors excluded until access/hours are verified. Montréal Voirie sidewalk **polygons** enrich edges (sidewalk presence/width/material) by spatial join; they never create connectivity on their own.
- **ADR-5 ML target** = P(≥1 winter-related 311 report in H3 res-9 cell, next 24 h). Not physical ice probability. Disabled in UI unless evaluation passes the gate in `docs/agents/ml.md`.
- **ADR-6 Weather** = ECCC GeoMet OGC API (`climate-hourly`, `swob-realtime`, `citypageweather-realtime`, `weather-alerts`). Alerts reproduced without alteration (licence clause).
- **ADR-7 No auth provider in v1**: moderator/admin routes use a single bearer token whose hash is in env; replaceable later.

## 8. Technology stack (v1)
| Layer | Choice |
|---|---|
| Web | React 18 + TypeScript + Vite, Tailwind, shadcn/ui, TanStack Query, Zustand, React Hook Form + Zod, i18next (EN/FR), Motion for React, react-router |
| Map | MapLibre GL JS, OpenFreeMap style (dev/pilot) — replaceable via `VITE_MAP_STYLE_URL` |
| 3D | three, @react-three/fiber, @react-three/drei; GLB compressed with gltf-transform |
| API | FastAPI, Pydantic v2, SQLAlchemy 2 + GeoAlchemy2, Alembic, structlog |
| GIS/ETL | OSMnx, GeoPandas, Shapely 2, PyProj, pyogrio, h3, NetworkX |
| ML | pandas, NumPy, scikit-learn (XGBoost only if justified by eval), Parquet artifacts |
| DB | PostgreSQL 16 + PostGIS 3.4 (Docker `postgis/postgis`), Supabase-compatible SQL (no custom C extensions beyond PostGIS/h3-pg optional) |
| Test | Pytest, Vitest + Testing Library, Playwright + axe, Schemathesis (contract) |
| CI | GitHub Actions: lint, type-check, unit, contract, gitleaks, pip-audit, npm audit |

## 9. Privacy & security (Quebec Law 25 oriented — needs counsel review)
- Geolocation only after explicit browser prompt triggered by user action; manual origin always available.
- Route requests: coordinates processed in memory; logs store only rounded (3 dp ≈ 100 m) or H3 res-7 cells, never raw precise coordinates. No user accounts, no route history in v1.
- Community reports: exact location only with explicit consent, default expiry 72 h, deletion token, moderation before display, salted daily-rotated client hash for rate limiting; hard delete 30 days after terminal status.
- Pilot form: minimal fields, 12-month retention.
- Security: HTTPS only in deploy, CORS allow-list from env, Pydantic validation with `extra=forbid`, parameterised SQL (SQLAlchemy), least-privilege DB roles (`wp_reader`, `wp_writer`, `wp_migrator`), admin bearer token hashed in env, per-IP rate limiting (in-process token bucket in v1), safe error envelopes (no stack traces), no file uploads in v1, secret scanning in CI.

## 10. Deployment compatibility (no deployment without approval)
- **Vercel**: `apps/web` static build (`vite build`), SPA rewrites; only `VITE_*` public env.
- **Render**: `services/api` Docker web service; ingestion as Render cron jobs (approval required before any scheduled job is created).
- **Supabase**: Postgres + PostGIS; Alembic migrations run from CI/manual with `wp_migrator` role. Avoid features Supabase lacks.
- Local: `docker compose up` (Platform agent) with PostGIS, API, web. All providers replaceable via env.

## 11. Milestone gates
A Foundation → B Geographic MVP → C Winter intelligence → D Product frontend → E Release candidate (spec §10). Deployment is a separate, user-approved step.
