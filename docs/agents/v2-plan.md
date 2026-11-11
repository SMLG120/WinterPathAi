# WinterPath AI 2.0: island expansion plan (coordinator)

Source request: owner prompt "WinterPath AI 2.0 — Montreal Island Expansion…" (2026-11-11).

Rules that still apply: CLAUDE.md, `docs/contracts/integration-rules.md`, the honesty rules, and no push, deploy or paid service without the owner's approval.

## Phase 1 audit (2026-11-11 23:45 UTC)

### Implemented and live
| Component | State |
|---|---|
| Web | `https://winterpath.pages.dev` (Cloudflare Pages). EN/FR, mobile layout, MapLibre with OpenFreeMap, procedural 3D hero, read-only mode |
| API | `https://winterpath-api.onrender.com` (Render Free, 0.1 CPU / 512 MB). Endpoints: health, coverage, data-sources, weather/current, weather/forecast, hazards, map/segments, models/status, routes/compare (shortest + winter_aware; profiles standard / reduced_mobility / step_free) |
| DB | Supabase Free, us-east-1, **49 MB** (`wp` schema 31 MB) |
| Jobs | GitHub Actions `scheduled.yml`: weather every 3 h, scoring 12:00/18:00 UTC |
| CI | Green on `main` (4af5262) |

### Measured problems
1. **Coverage is a 2.6 × 1.9 km downtown bbox** (`-73.588,45.496,-73.562,45.513`): 6,807 nodes, 16,296 edges, largest component 95.8 %.
2. **The GitHub cron has never fired.** Since the workflow was registered (19:10 UTC), every run was a manual `workflow_dispatch`; the 21:17 UTC weather run never happened. As a result, weather freshness depends on manual runs.
3. **Weather is observations only** (ECCC SWOB, 2 stations). `GET /weather/forecast` is in the contract but returns 503 (`ECCC forecast is unavailable`): not implemented. No hourly forecast, alerts, wind chill or precipitation probability reach the user. `departure_time` exists in the contract, but forecasts are not used for it.
4. **311 aggregates end on 2026-11-07.** There is no scheduled 311 ingest, so the 311 hazard layer is empty right now.
5. **Address search is disabled** (no permitted geocoder). Users must pick points on the map or type coordinates. This is the largest usability gap.
6. **Steps exist but are unusable for navigation.** The live API returned 46 steps for a 1.1 km walk; some legs are under 2 m, `street_name` is always null, and the UI has no live navigation (no position tracking, progress or reroute).
7. **Risk layer is a labelled heuristic** (historical winter 311 frequency × observed weather). No validated supervised model.
8. **Frontend detail:** after "Compare routes" the map zoomed out to the whole region instead of fitting the route (seen in a live browser test 2026-11-11).
9. **Free-tier limits:**
   - Render sleeps after 15 min (about 1 min to wake) and has 0.1 CPU.
   - Supabase has 500 MB, no backups, and pauses after 1 week idle.
10. **Monitoring:** none.

### API responsiveness (live, 60 requests)
- compare p50 366 ms, p95 806 ms.
- health about 0.3 s when warm.

### Data freshness at audit time
| Data | Latest |
|---|---|
| Weather observations | 22:00 UTC (manual run) |
| Scores | 19:22 UTC |
| Closures | ingested 19:01 UTC |
| 311 | 2026-11-07 |

## Key feasibility question (decides the architecture)
The island is roughly 500 km² against the pilot's about 5 km². The pedestrian graph is likely 50–100× larger: a few hundred thousand nodes and about a million edges.

Two unknowns must be **measured, not assumed**:
- **API memory.** The current Python object graph would likely exceed Render Free's 512 MB. A compact array representation (CSR) may fit.
- **Database size.** Edges with geometry plus indexes may approach or exceed Supabase Free's 500 MB.

Wave 1 measures both. If either does not fit, the owner gets the exact numbers and the lowest-cost option before anything is provisioned.

## Weather freshness design (coordinator decision)
- GitHub cron is unreliable (problem 2), and the API's database role is read-only by design. So **the API itself keeps forecasts and alerts fresh in memory**:
  - per-product TTL cache with single-flight refresh (one fetch per product per process, never one per request);
  - TTLs aligned with ECCC's `lastUpdated` cadence.
- On failure, it keeps serving the last validated payload, marked `delayed` or `stale`.
- The scheduled jobs keep writing snapshots and observations to PostGIS for history and ML. They are best effort, not the freshness mechanism.
- Render Free sleeps, so nothing refreshes while it is asleep. The first request after waking triggers a bounded refresh. **This will be documented, not hidden.**
- Products:
  - `citypageweather-realtime` item `qc-147` (Montréal): current conditions, wind chill, 24 h hourly forecast with probability of precipitation, 7-day forecast, warnings. It is labelled **experimental** by ECCC, so there must be a fallback;
  - `weather-alerts` collection, filtered to the island;
  - `swob-realtime` observations (existing).

## Phased sequence
| Wave | Goal | Contract | Deploy |
|---|---|---|---|
| **1 (now)** | Measure the island graph (DB size, RAM, latency); weather forecast/alerts library; UX fixes needing no contract change; scheduler reliability | none | none |
| 2 | Contract v1.8.0 (additive): coverage areas, `/weather/alerts`, freshness block on weather, `/data-status`, route `steps`, forecast-aware `departure_time`, place search | coordinator | — |
| 3 | Island graph in a staging DB; compact routing graph; forecast-aware routing; navigation UI; place search | v1.8 | owner approval |
| 4 | ML comparison (frequency baseline, weather rules, logistic/count regression, RF, XGBoost) with temporal and geographic holdouts; publish only if validated | — | owner approval |
| 5 | 3D polish, performance, accessibility and production verification; docs listed in the request | — | owner approval |

## Wave 1 briefs (local only: no Supabase writes, no deploys, no contract edits)

### data (Agent 1: geographic data)
1. **Boundaries.** Download both datasets: CC BY 4.0, cache under `data/raw`, record checksums.
   - `limites-administratives-agglomeration` (WGS84 GeoJSON): 19 boroughs plus 15 linked municipalities.
   - `archipel-agglomeration` (GPKG): land polygons.
   - Derive:
     - the **main-island polygon**;
     - per-municipality and per-borough polygons clipped to it;
     - separately flagged other islands (Île-Bizard, Île-des-Sœurs, Île Sainte-Hélène / Notre-Dame, etc.).
   - Never label Laval or Longueuil as island.
2. **Island graph.** Build it from the cached `quebec-261108.osm.pbf`, clipped to the island polygon (main island; other islands included only where connected by mapped pedestrian links). Use the existing rules: no invented connectivity, prohibited edges excluded.
   - Load it into a **new local DB `wp_island`** (shared container). Do not touch `wp_data` or Supabase.
3. **Report to `docs/agent-reports/data.md` → "Island feasibility":**
   - nodes, edges, network km;
   - connected components (count, largest share, list of components larger than 50 edges that are not in the largest);
   - per-municipality nodes, edges and km;
   - `pg_total_relation_size` per table **including indexes**, plus a projected Supabase total;
   - build time;
   - how far the sidewalk datasets reach: voirie trottoir is City of Montréal only, so state which linked municipalities have **no** sidewalk polygons.
4. **Place search assessment.** Is there an open, legally reusable address-point dataset for the whole island (e.g. Ville de Montréal address points, or Adresses Québec)? Report licence, row count, and projected DB size for a trigram search index. Do not build it yet.

### routing (Agent 2: backend and routing)
1. Measure the RSS of the **current** graph loader on `wp_island` once data reports it is loaded. Until then, measure bytes per edge on the pilot graph and project.
2. Prototype a **compact graph** (e.g. numpy CSR arrays, a KD-tree for nearest node, A* with an admissible time heuristic). Requirements:
   - **byte-identical** results on the existing golden test;
   - same cost function;
   - no contract change.
3. Benchmark in Docker `--cpus=0.1 --memory=512m` with these route classes:
   - short (< 1 km);
   - medium (2–5 km);
   - cross-island (15–40 km, e.g. Pointe-Claire → Montréal-Nord, Sainte-Anne-de-Bellevue → Pointe-aux-Trembles).
   - Report p50/p95, boot time, peak RSS.
4. Write the results to `docs/agent-reports/routing.md` → "Island feasibility". Commit the prototype behind a flag. Production behaviour must not change.
5. **Steps (no contract change):**
   - merge consecutive steps along the same way, street name or footway class;
   - fill `street_name` from OSM `name` (or `footway=crossing` / `sidewalk` descriptors, EN/FR) where present;
   - drop sub-5 m legs into the neighbouring step.
   Put a before/after count for the golden routes in the report.

### ml (Agent 3: weather and ML)
1. **Library `winterpath_ml.weather`:** fetch → validate → normalize for ECCC `citypageweather-realtime/qc-147` and `weather-alerts` (island bbox or polygon). Requirements:
   - pure functions plus a provider with a TTL single-flight cache;
   - UTC storage, America/Toronto semantics, correct across DST;
   - missing variables stay missing; never fill them in;
   - each payload carries provider, issued time, validity interval, fetched time, validated time and freshness state (`current` / `delayed` / `stale` / `unavailable`).
2. Record real responses as **labelled recorded fixtures** (with retrieval timestamp) for tests.
3. Test cases: outage, malformed payload, expired forecast, DST transition (2026-11-01 and 2027-03-14), the experimental product disappearing (fallback to observations only).
4. Read and summarise the ECCC Data Servers End-use Licence and any GeoMet usage policy for these products (cadence, attribution). Do not treat a failed fetch as confirmation.
5. Do not start new model training yet. Write a short plan for the Phase 5 comparison, stating which labels exist and how many.

### frontend (Agent 4: UI/UX and 3D)
`bb76eb2` is pending merge. Then, without contract changes:
1. **Fix:** after compare, fit the map to the selected route (it currently zooms out to the region).
2. **Mobile-first planner:**
   - full-screen map with a bottom sheet (peek / half / full);
   - compact route cards (time, distance, risk category with text and icon, freshness);
   - selecting a card highlights its path;
   - large touch targets; one-hand reachable.
3. **Desktop:** collapsible left panel.
4. **Landing page:**
   - the obvious primary action ("Plan a walk") and current Montréal weather from the existing `/weather/current`;
   - headline "Walk smarter through Montreal's winter." with an FR equivalent;
   - the 3D hero must never block entry.
5. **Small controls:** swap, clear, recenter, reset layers, skeletons, friendly errors, cold-start "waking up" state.
6. **Recent destinations:** local only, opt-in, clearable.
7. Measure LCP and route-planner interactivity at a 390 px viewport with 4× CPU slowdown, before and after.

Design tokens: midnight navy, ice blue, frost white, teal, slate, amber for caution. Never use colour alone.

### platform (Agent 5: DevOps, security and quality)
1. **Cron:** find out why the scheduled cron never fires (workflow registration, default branch, any GitHub notices). Do not add artificial pings. Then:
   - add `concurrency:` groups so runs never overlap;
   - add an ETL advisory lock, coordinated with data, who owns ingestion code. Propose the lock key scheme in your report.
2. **Daily data-integrity job (proposal):** row counts, freshness thresholds, orphan checks. It reports a failure via the job status and does **not** ping the API more than once per run.
3. **Staleness monitoring proposal** that respects Render's sleep policy (no keep-alive).
4. A Docker benchmark harness that routing can reuse for island measurements.

## Owner decisions that will be needed (not yet asked)
- Hosting upgrade, **only if** the measurements show the free tiers cannot hold the island graph.
- Place-search source (open address data in our DB, or a third-party geocoder with verified terms).

## Wave 2a: implement contract v1.8.0 (2e3d4b2)
Start after your Wave 1 item is committed. Merge `integration/winterpath` first; it contains ml `df50641` (`winterpath_ml.weather_live`).

### routing (API)
1. Wire `LiveWeatherProvider` into the API (one provider per process, injectable for tests) and use it to serve:
   - `/weather/forecast`: `periods` = hourly, plus `text_periods`, `freshness`, `provenance`;
   - `/weather/alerts`;
   - the `/weather/current` additions: `wind_chill_c`, `condition`, `freshness` and `provenance`. Keep SWOB observations from PostGIS as the primary observation, and say which source each field came from.
2. Errors:
   - 503 only when no validated payload exists or the last one has expired;
   - otherwise serve the cached payload with its degraded freshness;
   - a request must never trigger more than the single-flight refresh.
3. `/data-status`: compute freshness for every listed product. Use `api_on_demand` for forecast and alerts, `scheduled_job` for observations and scores, `manual` for closures, 311 and graph.
4. `routes/compare` `weather_context`: the hourly forecast covering `departure_time`; null when outside the forecast range. The risk score is unchanged (`used_for: display_only`).
5. Env vars (names only, defaults safe): `WEATHER_LIVE_ENABLED` (default false in tests, true in deploy docs), `WEATHER_LIVE_USER_AGENT`. Tell me the final names; `.env.example` is coordinator-owned.
6. Tests with ML's recorded fixtures, including the outage and stale paths. Do not call real ECCC from CI.

### frontend
Run `npm run gen:api` against v1.8, then build:
- **Compact weather bar** (temperature, condition, next-hours precipitation, valid time, "updated N min ago" from `provenance.fetched_at`) with a stale/delayed label. It must never show stale data as current.
- **Expandable panel:** hourly list, `text_periods`, alerts with verbatim text in the user's language, wind chill.
- **Departure time choice:** Leave now / In 1 h / Later today / Pick a time within the forecast range. Show the route's `weather_context` and state that the forecast is shown for information only.
- **Data status page or section** from `/data-status`.
- MSW fixtures must validate against the schema and be labelled as fixtures.

### platform
- Contract tests for the v1.8 endpoints.
- Freshness checks in the integrity-job proposal using `/data-status`: one request per run, no keep-alive.
