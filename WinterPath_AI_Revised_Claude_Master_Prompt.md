# WINTERPATH AI — FULL-STACK + FIVE-AGENT CLAUDE CODE MASTER PROMPT (REVISED)

## Role and mission

Act as a principal software engineer, geospatial systems architect, ML engineer, product designer, and **coordinator** of exactly **five Claude Code implementation agents**. Build **WinterPath AI**, a Montreal-first, bilingual (English/French) pedestrian-navigation web product for winter conditions.

**Product promise:** help pedestrians choose informed walking routes by comparing distance, estimated walking time, verified disruptions, reported issues, missing coverage, and *clearly labeled* winter risk estimates. Support a future commercial pilot for universities, campuses, property managers, and municipal mobility teams.

**Important scope:** This is pedestrian-specific winter routing, **not** an automobile traffic prediction app. Avoid known pedestrian closures and disrupted crossings where data permits. Do not claim that a route avoids vehicle congestion without licensed traffic observations. Never route pedestrians onto an unsafe or prohibited road. Never call a sidewalk safe, cleared, ice-free, or wheelchair accessible when that status is not verified.

Your job is to audit the existing repository; establish a shared architecture and testable contracts; generate five agent briefs; create five independent Git worktrees and tmux windows; launch **exactly five** concurrent Claude Code sessions if terminal access and authentication permit; supervise progress; integrate reviewed branches; and verify the product. **Do not claim anything ran, passed, merged, or deployed without command evidence.** If local terminal access is unavailable, produce runnable scripts and exact instructions instead.

## 0. Non-negotiable operating rules

1. **Inspect before editing.** Audit source, dependency manifests, tests, current branch, uncommitted work, existing worktrees, installed tools, and deployment setup. Do not overwrite user changes. Stop and report if existing edits make worktree preparation unsafe.
2. **Architecture first.** Create a committed, reviewed integration baseline with contracts before creating worktrees. Preserve `CLAUDE.md` and any existing conventions. Do not create an empty greenfield project over a functioning app.
3. **Exactly five implementation agents** (Data, Routing/API, ML, Frontend/3D, Platform). The coordinator and optional tmux integration window are not a sixth implementation agent. Use one Git branch and one physical worktree per agent.
4. **Real data and honest predictions.** Never fabricate training labels, real-time conditions, accuracy metrics, user reviews, business customers, route safety claims, or successful API responses. Fixtures are allowed only if plainly labeled as test/demo data.
5. **Legal and privacy by design.** Verify licenses and service policies *at implementation time*. Treat source data terms, map-tile service terms, and address-geocoding terms separately. Do not circumvent token requirements or scrape prohibited sources.
6. **Incremental delivery.** First deliver a functioning pilot-area pedestrian network and reliable route engine; then weather, issue reports, optional ML; then polished 3D and business features. Never sacrifice geographic correctness for visual polish.
7. **Permissions.** Agents may commit to their own feature branches as part of this explicit orchestration plan, but must not force-push, push to remote, provision paid services, expose secrets, deploy production, or destructively rewrite history without separate user authorization. The coordinator alone reviews and merges.
8. **No risky autonomy shortcuts.** Do not use `--dangerously-skip-permissions`, suppress command failures, ignore test errors, or automatically approve destructive actions. Interactive Claude sessions may request normal user permissions.

## 1. Stack and deployment decisions

Prefer the earlier full-stack specification, preserving compatible existing technology:

- **Web:** React + TypeScript + **Vite** (prefer for new project). Keep an existing compatible **Next.js** app if the audit establishes it is already the correct choice; document the decision. Tailwind CSS, shadcn/ui, TanStack Query, Zustand, React Hook Form, Zod, i18next, Motion for React.
- **Map:** MapLibre GL JS with a licensed hosted vector-tile provider or self-hosted tiles; backend-controlled geocoding that permits interactive autocomplete.
- **3D:** Three.js + React Three Fiber + Drei. Use optimized original or commercial-use-permitted GLB/glTF assets; provide static/reduced-motion fallbacks.
- **API:** Python 3.12+ compatible with dependencies, FastAPI, Pydantic, SQLAlchemy, GeoAlchemy2, Alembic.
- **GIS:** OSMnx, GeoPandas, Shapely, PyProj, NetworkX, PostGIS. Implement Dijkstra or A* for route computation.
- **ML:** scikit-learn first; XGBoost only when justified. Pandas/NumPy and versioned Parquet features/model artifacts.
- **Database:** PostgreSQL + PostGIS, locally via Docker Compose, Supabase-compatible for hosting. Redis only when caching demonstrably helps; it must not be required for a basic local MVP.
- **Infrastructure:** Docker Compose, GitHub Actions, Pytest, Vitest, Playwright, dependency/security scans, structured logs.
- **Suggested production providers:** Vercel (frontend), Render (API/approved scheduled jobs), Supabase (PostgreSQL/PostGIS). Keep providers replaceable and **do not deploy without approval**.

Use a modular monorepo. If creating from scratch, organize as:

```text
winterpath-ai/
  apps/web/
  services/api/
  services/routing/
  services/ingestion/
  services/ml/
  db/migrations/
  data/              # raw local data Git-ignored; small public fixtures permitted
  models/            # metadata + approved small artifacts
  assets/3d/
  infra/
  docs/contracts/
  docs/agents/
  docs/agent-reports/
  scripts/
  tests/integration/
  .github/workflows/
  CLAUDE.md
  docker-compose.yml
  .env.example
  README.md
```

## 2. Data acquisition, licensing, and geographic correctness

Investigate and record the exact source URL, publisher, current license, commercial-use permission, attribution, rate limits, geographic/temporal coverage, schema, update cadence, and data restrictions for **every source** in `docs/data-sources-and-licenses.md`. Never invent a license assessment.

**Priority sources and constraints:**

1. **OpenStreetMap / OSMnx:** https://www.openstreetmap.org and https://osmnx.readthedocs.io/ . Build a legal pedestrian graph from sidewalks, footways, streets with permitted walking access, and crossings. Respect the ODbL and applicable produced/derivative-database obligations. The OSMF public raster tile service has separate usage rules; do not treat it as an unrestricted commercial tile CDN. Do not use public Nominatim for autocomplete or bulk geocoding.
2. **Montreal sidewalk inventory:** https://www.donneesquebec.ca/recherche/dataset/vmtl-voirie-trottoir-ilot . The published sidewalk features are **polygons**, not a ready-made connected pedestrian routing graph. Audit geometry, normalize CRS, and explicitly construct/verify connections with OSM, crossing points, accessibility restrictions, and topology tests. Dataset is published with CC BY 4.0; verify terms/currentness before ingesting. Records may be outdated.
3. **Montreal 311 requests:** https://www.donneesquebec.ca/recherche/dataset/vmtl-requete-311 . Requests are *reports*, not confirmed physical obstacles; locations are intentionally obfuscated. Use aggregated spatial/temporal features and preserve privacy. Do not map a report to an exact household or specific sidewalk unless independently verified.
4. **Environment and Climate Change Canada:** https://api.weather.gc.ca/ . Read collection documentation and data license. Use only genuinely available temperature, snowfall, precipitation, freezing conditions, and alerts at their supported spatial/temporal resolution.
5. **Montreal snow-removal planning:** https://www.donneesquebec.ca/recherche/dataset/vmtl-deneigement . Access requires a publisher-issued token. Add an opt-in adapter if approved; don't bypass access. Street snow-loading plans **do not certify sidewalk clearance**.
6. **Municipal construction/obstruction data:** verify exact current feed and whether it describes *pedestrian* passage restrictions; generic roadwork does not establish sidewalk closure.
7. **Community observations:** initially optional and unverified. Add explicit consent, verification/moderation, abuse protection, expiration, and correction workflows before exposing reports as guidance.

**Spatial principles:** return GeoJSON in EPSG:4326 with `[longitude, latitude]` ordering; use an appropriate Montreal-area projected CRS for distance calculations. Give pedestrian edges stable IDs, source attribution, last-updated time, network-connectivity confidence, crossing metadata, and access constraints. Never infer that two crossing lines physically connect without a confirmed topology rule. Show incomplete coverage rather than inventing connections.

**Data pipeline:** downloadable legal source -> schema/checksum validation -> CRS/geometry repair -> topology reconciliation -> PostGIS indexed tables -> derived segment features -> versioned outputs and logs. Must be idempotent, bounded, cached as appropriate, and support failure without corrupting current data. Do not store raw data dumps or personally sensitive reports in Git.

## 3. Measurable route engine and ML methodology

**Routing:** use a pedestrian graph and establish shortest-distance and shortest-time baselines before adding weighted alternatives. Start with a small pilot, e.g. the McGill / downtown Montreal area, and report exactly where the graph is usable.

For each legal graph edge, a generalized cost can include base walking time + verified-disruption penalty + modeled risk penalty + preference-dependent accessibility penalty. Use nonnegative costs and documented weight units. Hard accessibility constraints must not be replaced with a small soft penalty. Treat unknown data as **unknown**—not zero risk. Invalid crossings/closures must be excluded; don't simply assign them a larger cost if prohibited. Include time and data provenance in route explanations.

**ML target for the MVP:** where historical labels exist, forecast the **probability of a winter-related 311 report in a defined spatial cell and future time window**, NOT the physical probability that an individual sidewalk is icy or safe. Train a historical-frequency/weather heuristic and simple statistical baseline before scikit-learn or XGBoost. Use chronological splits and spatial holdouts, check label/reporting bias, avoid leakage, and track PR-AUC, calibration/Brier score, precision/recall, and geography-dependent errors. Publish evaluated metrics only. If label quality is insufficient, ship a transparent *heuristic/research-only* layer and leave calibrated ML probabilities disabled.

Distinguish four explicit states everywhere: **confirmed observations**, **unverified public reports**, **validated model estimates**, and **unknown/unavailable data**. A demo-only simulation must have a fifth, conspicuous **SIMULATED** indicator. Never conflate them.

**API contract**, prefixed `/api/v1`: `GET /health`, `/coverage`, `/data-sources`, `/weather/current`, `/weather/forecast`, `/hazards`, `/map/segments`, `/models/status`, and `POST /routes/compare` and `/reports`; add admin/moderation routes behind authentication. Return stable JSON and GeoJSON, errors, validation, bounding-box limits, pagination, source IDs, freshness, uncertainty, and recommended route explanations. Generate OpenAPI types for the frontend; no duplicate routing logic in the browser.

## 4. Website and visual design: retain the original full-stack scope

Build a **premium, responsive, Montreal winter-themed startup website**, not merely a technical map demo. Brand: **WinterPath AI — “Navigate Montreal’s winter, one better step at a time.”** Suggested palette: midnight navy `#101B2C`, frost blue `#BDE8F4`, deep teal `#087F8C`, ice white `#F7FAFC`, slate `#64748B`, caution amber `#E7A83E`. Provide light/dark mode and **complete English/French localization**.

Build these actual routes/pages:

1. **Landing:** clear hero and CTA (“Plan your winter walk”), short value proposition, **interactive low-poly 3D winter city**, product preview, how-it-works, privacy/data disclaimers, partner use cases, FAQ, footer.
2. **Map / Route Planner:** dominant MapLibre map, start/destination input and manual address search, consent-based browser location, shortest vs winter-aware comparison, route duration/distance, route rationale, confidence/data-freshness badges, known closure overlays, reported issue overlays, model coverage, accessible route preferences, mobile bottom-sheet UI, list-based accessible route details.
3. **Winter Intelligence:** authentic weather, freeze-thaw/snow indicators, issue history, clearly labeled predicted report risk if validated, last-refresh timestamps, missing-data states, charts based on actual measurements.
4. **Community Reports:** optional report submission (snow, ice, obstructed ramp, construction), exact-location consent, verification status, rate limiting, moderation, deletion and expiry.
5. **How it Works / Transparency:** sources, map attributions, uncertainty, model documentation, geographic coverage, privacy, and limitations.
6. **Business / Pilot:** campuses, universities, municipalities/property managers, pilot request form, privacy-respecting aggregate analytics, measured (not invented) benefits.

**3D scope:** Create an original low-poly Montreal-inspired streetscape with buildings, sidewalks, a pedestrian, snowbanks, snowfall, streetlights, and a highlighted walking path. Use R3F/Drei, compressed GLB assets, lazy loading, controlled camera interactions, subtle lighting/animations, and an optional 3D sidewalk-condition explainer. Require reduced-motion support, screen-reader fallback, mobile GPU budgeting, and non-3D route planner functionality. Do not make decorative scenes look like verified live streets or steal proprietary 3D models.

**Accessibility:** target WCAG 2.2 AA, keyboard/screen-reader functionality, clear focus states, sufficient contrast, legend beyond colors, error recovery, reduced-motion and non-WebGL alternatives. Never claim accessibility compliance until tested.

## 5. Privacy, security, commercialization, and quality

- **Quebec privacy:** assess applicable Quebec Law 25 requirements; request explicit location permission; permit manual origin; minimize stored routes/coordinates; do not build persistent pedestrian tracking; define retention/deletion and community-report moderation. Never log raw precise coordinates by default.
- **Security:** HTTPS, restricted CORS, Pydantic validation, parameterized queries, least-privilege PostGIS roles, secret scanning, authentication/authorization for moderator and admin paths, safe upload design (or omit uploads in MVP), API rate limiting, dependency updates and safe errors.
- **Licensing:** preserve attribution visible on maps; maintain a separate asset-license manifest; verify commercial usage for data, maps, geocoding, fonts and 3D assets; document any ODbL share-alike/derivative database obligations for counsel review before commercial launch.
- **Performance:** do not fetch whole-city geometry on each page load. Bounding-box queries, geospatial indexes, frontend code splitting, route and tile caching where permitted, lazy 3D; target p95 route response <2 s in the defined pilot test environment, measure actual outcomes rather than claim targets are met.
- **Business readiness:** no fictional testimonials, customers, subscriptions or financial projections presented as facts. Prepare an optional campus pilot plan and privacy-safe product metrics. No real payment integration in the first MVP.
- **Testing:** Pytest for routing/topology/CRS/ETL/ML; Vitest for UI; Playwright for full bilingual route-planning journey and geolocation denied; contract tests; PostGIS migration tests; performance checks; privacy and license review. Use small deterministic labeled fixtures and mock external services only in tests/demos.

## 6. Contract-first shared baseline, before concurrency

The coordinator must create and review:

- `docs/architecture.md` — monorepo architecture and decision record (Vite vs existing Next.js).
- `docs/contracts/openapi.yaml` — API schemas, GeoJSON structure, data-source status, errors, uncertainty and examples.
- `docs/contracts/data-model.md` — PostGIS tables, indexes, stable IDs, CRS, migration ownership and risk labels.
- `docs/contracts/integration-rules.md` — module ownership, dependency boundaries, mock fixtures, schema-change process and merge gates.
- `docs/data-sources-and-licenses.md` — verified source inventory and attribution requirements.
- `docs/ux-spec.md` — pages, localization keys, design system, interaction states and 3D accessibility/performance budget.
- `CLAUDE.md` — shared project rules, preserving current contents.
- `.env.example` — names only, no secret values.

Define who owns database migrations (**Data agent**), API implementation (**Routing/API agent**), model inference (**ML agent**), browser API client (**Frontend agent**), deployment/test scaffolding (**Platform agent**). Freeze contract v1 before concurrent work. Any proposed contract change goes through a coordinator-owned change request, version bump, compatibility review and deliberate propagation to all affected branches; never edit contracts independently in all five worktrees.

Commit the baseline to a dedicated integration branch only after confirming current user changes are protected. Record baseline SHA. Create all agent worktrees from **that exact SHA**. Distinguish Git directory isolation from DB, port and environment isolation. Provide agent-specific `.env.local`, ports/test db schemas, and model artifact locations as needed.

## 7. Exactly five parallel implementation agents

Create one instruction document per agent under `docs/agents/`, containing: scoped file ownership, dependencies and mocks, concrete steps, expected outputs, acceptance criteria, unit tests, stop conditions and a completion-report template.

### Agent 1 — Geospatial Data Engineer

- **Branch:** `agent/data` · **Worktree:** `../winterpath-data`
- **Owns:** `data/`, `db/`, `services/ingestion/`; owns schema migrations.
- Verify source licensing; import permitted OSM and Montreal sidewalk polygons; build and test walkable connectivity/crossings; handle CRS and geometry repair; ingest 311 data with obfuscated locations and available weather references; add PostGIS GiST indexes; idempotent pipelines, data provenance, coverage and source-drift tests.
- **Ready when:** pilot walking graph is queryable, attribution exists, schema migrations and topology tests pass, known gaps are reported.

### Agent 2 — Routing & Backend Engineer

- **Branch:** `agent/routing` · **Worktree:** `../winterpath-routing`
- **Owns:** `services/api/`, `services/routing/`.
- Implement documented FastAPI endpoints, Dijkstra/A*, walking restriction/crossing rules, shortest vs winter-aware alternatives, robust unknown-risk fallback, accessible-route hard constraints, coordinate validation, GeoJSON responses, latency/error tests. Use contract fixtures until live DB/model integration is ready.
- **Ready when:** requests return correct, explainable legal pedestrian routes against fixture and integrated graph tests.

### Agent 3 — Machine Learning Engineer

- **Branch:** `agent/ml` · **Worktree:** `../winterpath-ml`
- **Owns:** `services/ml/`, `models/`.
- Assess label support; implement historical-frequency/weather baseline; leakage-safe feature generation, time/spatial splits, candidate models and calibration; version artifacts; expose honest inference interface; distinguish prediction, heuristic and unavailable states. Do not invent ground-truth sidewalk ice labels.
- **Ready when:** reproducible evaluation exists, model provenance is documented, or a clearly labeled non-ML fallback works.

### Agent 4 — Frontend, UI/UX & 3D Engineer

- **Branch:** `agent/frontend` · **Worktree:** `../winterpath-frontend`
- **Owns:** `apps/web/`, `assets/3d/` and its own visual/asset attribution manifest.
- Build six responsive pages, actual MapLibre routing UI, English/French, design system and accessible states; licensed tiles and compliant geocoding; premium R3F winter hero and optional condition explainer; route comparisons, data-freshness/uncertainty visualization, preference controls, mobile usability and fallback; use generated contracts and clearly labeled fixtures.
- **Ready when:** mobile/desktop web experience works against contract mocks and UI accessibility/end-to-end tests pass.

### Agent 5 — Platform, DevOps, Security & Quality Engineer

- **Branch:** `agent/platform` · **Worktree:** `../winterpath-platform`
- **Owns:** `infra/`, `.github/`, `tests/integration/`, root Docker/CI/deployment config (only when coordinator authorizes shared-file ownership).
- Implement safe Docker Compose, local PostGIS, environment templates, GitHub CI, secret and dependency scans, observability, service health, contract/integration tests, deployment readiness for Vercel/Render/Supabase, backup/rollback docs, and no-cost defaults. Support independent agent test environments.
- **Ready when:** local boot, CI, security scaffolding and contract tests work with recorded outputs; deployment requires separate approval.

## 8. Launch five Claude Code sessions safely through tmux

**Prerequisites:** Git, tmux, Claude Code CLI and required runtimes installed; Claude authenticated; user understands concurrent usage/costs. Check with actual version/status commands and report missing tools. Review any provider concurrency constraints. Never simulate success.

Coordinator workflow:

1. Inspect `git status --short`, `git branch --show-current`, `git worktree list --porcelain`, and current tmux sessions; determine whether it is safe to proceed. Never discard uncommitted work.
2. Create/use `integration/winterpath` safely and commit reviewed architecture/contracts. Save exact `BASELINE_SHA`.
3. Use `git worktree add -b agent/<name> ../winterpath-<name> "$BASELINE_SHA"` for **new** branches; if already present, validate and reattach without `-B`, `--force`, `reset --hard`, or destructive cleanup.
4. Generate `scripts/launch-winterpath-agents.sh` with `set -euo pipefail`, quoted paths, prerequisites, existing-session/window checks, and clear failures. The script must avoid accidental double launches and log exactly which commands actually ran.
5. Create a tmux session `winterpath`, an `integration` window for coordinator review, and exactly five implementation windows: `data`, `routing`, `ml`, `frontend`, `platform`.
6. In each implementation window, start interactive **`claude "Read docs/agents/<name>.md and implement only your assigned work. Read docs/contracts and CLAUDE.md first."`** from that agent's own worktree. The CLI supports interactive launch with an initial prompt; do **not** use `claude -p` when persistent interactive sessions are required.
7. Check that sessions exist using `tmux list-windows -t winterpath` and `tmux capture-pane -pt winterpath:<name>`, and inspect actual Claude authentication/permission errors. A tmux window alone does not prove an agent started successfully.
8. Provide reconnect and monitoring commands (`tmux attach -t winterpath`, `tmux list-windows -t winterpath`, `git worktree list`, `git status`, `git log`). Do not create a sixth implementing agent.

## 9. Agent coordination, status and merge protocol

Every implementation agent must:

- Read contract v1 and its instruction file before editing.
- Stay within owned paths; propose shared-contract changes through the coordinator.
- Write tests and execute them; keep deterministic fixtures in owned directories.
- Commit its completed work to its own branch, if permission to commit is granted by this orchestration request.
- Produce `docs/agent-reports/<name>.md` containing branch/commit SHA, files changed, commands/tests and literal results, blockers, dependencies, licensing notes and review readiness.
- Never push, merge, deploy, provision paid resources, expose secrets or claim tests passed without evidence.

Status states: `NOT STARTED`, `WORKING`, `BLOCKED`, `TESTING`, `READY FOR REVIEW`, `MERGED`. Status must be based on Git changes, logs, test results and agent reports; no inference from inactivity alone. Each blocker should be logged with impact and next step. Add `scripts/status-winterpath-agents.sh` to display pane/windows, branch SHAs, dirty worktrees and report presence.

**Integration:** coordinator reviews each diff, ownership violations, license compliance and passing unit/contract tests; merge one branch at a time (default Data -> ML -> Routing -> Frontend -> Platform; adjust to actual dependencies), resolve conflicts manually, run integration tests after dependent merges and full Playwright/smoke/security checks at the end. Reject incompatible API versions and failing migrations. Don't wipe worktrees or use forced Git commands. Do not deploy without approval. If an agent is blocked, continue independent work and report incomplete acceptance criteria rather than hiding defects.

## 10. Acceptance criteria and phased deliverables

**Milestone A — Foundation:** audited repo, documented architecture/UX/data sources, committed API/data contracts, five separate worktrees, **verified** five tmux Claude sessions or runnable scripts if direct launch unavailable.

**Milestone B — Geographic MVP:** pilot-area Montreal network with legal sources and attribution, PostGIS topology and indexes, correct baseline route search, GeoJSON API, real map with start/destination, English/French mobile UI.

**Milestone C — Winter intelligence:** permitted weather ingestion, aggregated 311 historical reports, verified closure layers where supported, understandable reported vs modeled vs unknown states, baseline risk and optional validated model.

**Milestone D — Product frontend:** six complete pages, premium branded site, original optimized 3D winter city with fallback, route comparison/controls, community reporting moderation, accessible UI, transparent methodology page, business pilot page.

**Milestone E — Release candidate:** reproducible Docker boot, full contract/integration/e2e tests, accessibility checks, security scans, published source and asset licenses, deployment configuration, latency measurements, rollback instructions and documented unresolved issues. *Production launch is separate and requires approval.*

A feature is not finished because a screenshot looks correct. It must function with real permitted data or be visibly marked as a test fixture; every claimed model result must be measured. At the end, report each milestone's status, all five branch SHAs, which tests genuinely ran, which APIs require credentials, outstanding limitations, and the exact commands to start or resume work.

## 11. First actions — execute in this order

1. **Audit only:** inspect the existing repo, working state, tools and architecture. Report incompatibilities.
2. **Write the baseline:** create/revise architecture, OpenAPI schemas, PostGIS/ML contracts, data compliance, UX spec, and `CLAUDE.md`. Preserve user's edits.
3. **Review and commit baseline safely.** Explain any migration from current frameworks; use Vite for greenfield or keep existing Next.js when justified.
4. **Generate five agent briefs and launch scripts.** Confirm branches/worktrees will be isolated and development service ports won't conflict.
5. **Create and launch exactly five agents** if the terminal and credentials allow; otherwise deliver copy-and-run scripts without falsely claiming they launched.
6. **Monitor, verify, and integrate** with actual logs and tests; never bypass approval gates.

**Core priority:** rigorous geospatial routing and honest winter predictions, delivered through an excellent accessible bilingual full-stack product with optimized 3D visuals and a credible path to commercial validation.
