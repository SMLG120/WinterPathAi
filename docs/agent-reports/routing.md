# Agent report — routing

- **Status:** READY FOR REVIEW. Cycle 6 adopts contract **v1.5.0**: 311 natures, CR-ROUTING-4 and CR-ROUTING-9 accepted. Cycle 5 added v1.4.0 closure activity and `terminal_at`; cycle 4 added v1.3.0 and the ML risk layer; earlier cycles were merged at `517a493` (1–2) and `d179845` (3).
- **Branch / SHA:** `agent/routing` @ `864aa80` (code). `integration/winterpath` (`bbae7d3`, v1.5.0) was merged in first as `71afb2b`. Cycle 5 code is `b6b62c4`, on merge `c6d603f`. This report is committed on top.
- **Date (UTC):** 2026-11-10

## Files changed
`git diff --stat $(git merge-base integration/winterpath HEAD) HEAD -- services docs/agent-reports/routing.md`. Only owned paths are touched; `scripts/check-ownership.sh routing` → `ownership OK for agent/routing`.

```
services/routing/   winterpath_routing — pure Python (NetworkX, Shapely, pyproj); no web framework
  src/…/models.py, geo.py, providers.py (Fixture + PostGIS GraphProvider), graph.py, filters.py,
  costs.py, search.py (Dijkstra/A*), engine.py, steps.py, explain.py, risk.py
  tests/  test_routing_{search,engine,providers,latency,pilot_mini}.py, routing_testlib.py,
          fixtures/synthetic/toy_grid/ (SYNTHETIC, metadata "simulated": true, + generator)
services/api/       winterpath_api — FastAPI
  src/…/main.py, schemas.py, routers/{system,map,routing,reports}.py,
  repositories/{reports,hazards,sources}.py (in-memory + PostGIS), adapters.py (risk/weather),
  compute.py (pre-warmed route pool), errors.py, logs.py, params.py, security.py, settings.py, state.py
  weather.py (ECCC observations, cycle 3)
  tests/  test_api_{contract,adapters,pilot_mini,postgis,weather,ml_risk}.py, api_testlib.py
  pyproject.toml / uv.lock: path dependency on ../ml (winterpath-ml), cycle 4
docs/agent-reports/routing.md
```

## Commands run and literal results
### 0b. Cycle 6 run (contract v1.5.0) — current
`uptime` at start: `load averages: 11.79 23.10 29.56`. `wp_routing` at `0004_closure_status (head)`; no migration for `report_311_cell.nature` exists yet.
```text
$ set -a; source .env.local; set +a; uv run --project services/api pytest services/routing services/api -rs -p no:cacheprovider -s   # filtered to latency + summary
[latency] SYNTHETIC grid 25x25 over PILOT_BBOX: nodes=625 directed_edges=2400 n=100 compare() p50=7.6 ms p95=17.5 ms max=69.3 ms
[latency] SYNTHETIC grid 60x60 over PILOT_BBOX: nodes=3600 directed_edges=14160 n=100 compare() p50=43.5 ms p95=118.5 ms max=226.1 ms
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=1.3 ms p95=2.0 ms max=2.5 ms (rejected >75 m from network: 48)
[latency] API POST /routes/compare SYNTHETIC toy grid (38 edges), n=100: p50=3.9 ms p95=7.0 ms max=13.7 ms
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=5.8 ms p95=8.0 ms max=14.3 ms
======================= 291 passed, 1 warning in 19.59s ========================
$ (cd services/routing && uv run ruff check . && uv run ruff format --check .)
All checks passed!
20 files already formatted
$ (cd services/api && uv run ruff check . && uv run ruff format --check .)
All checks passed!
30 files already formatted
$ scripts/check-ownership.sh routing
ownership OK for agent/routing
$ row counts in wp_routing after run
{'edge': 0, 'node': 0, 'closure': 0, 'community_report': 0, 'pilot_request': 0, 'weather_obs': 0, 'weather_daily': 0, 'report_311_cell': 0}
```
Before this, on the unchanged cycle-5 branch (`integration/winterpath` was still `dc1ed12`, so `git merge` printed `Already up to date.`), the rerun gave `290 passed, 1 warning in 28.65s` with the same lint and ownership output.

### 0a. Cycle 5 run (contract v1.4.0 closure activity)
`wp_routing` migrated to head with the Data agent's alembic (my own DB only):
```text
$ uv run --project services/ingestion --with alembic alembic -c db/alembic.ini current   # before
0001_wp_schema_v1
$ … alembic -c db/alembic.ini upgrade head; … current
0004_closure_status (head)
$ schema check on wp_routing
('wp_routing', '0004_closure_status')
(True, True)        # wp.closure_active_at(wp.closure, timestamptz) exists, wp.weather_daily exists
['attrs', 'backsidewalk_blocks_passage', 'crossing_kerb', 'crossing_type', 'name', 'terminal_at']
```
`uptime` at start: `load averages: 28.18 31.32 33.66` (heavily shared machine).
```text
$ set -a; source .env.local; set +a; uv run --project services/api pytest services/routing services/api -rs -p no:cacheprovider -s   # filtered to latency + summary
[latency] SYNTHETIC grid 25x25 over PILOT_BBOX: nodes=625 directed_edges=2400 n=100 compare() p50=6.2 ms p95=14.2 ms max=16.2 ms
[latency] SYNTHETIC grid 60x60 over PILOT_BBOX: nodes=3600 directed_edges=14160 n=100 compare() p50=46.9 ms p95=134.9 ms max=255.0 ms
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=1.1 ms p95=1.8 ms max=2.2 ms (rejected >75 m from network: 48)
[latency] API POST /routes/compare SYNTHETIC toy grid (38 edges), n=100: p50=6.3 ms p95=17.1 ms max=32.0 ms
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=23.2 ms p95=96.6 ms max=238.4 ms
======================= 290 passed, 1 warning in 45.21s ========================
$ # wp_routing must be at alembic head (0004_closure_status) for the closure-activity PostGIS tests
(cd services/routing && uv run ruff check . && uv run ruff format --check .)
All checks passed!
20 files already formatted
$ (cd services/api && uv run ruff check . && uv run ruff format --check .)
All checks passed!
30 files already formatted
$ scripts/check-ownership.sh routing
ownership OK for agent/routing
$ row counts in wp_routing after run
{'edge': 0, 'node': 0, 'closure': 0, 'community_report': 0, 'pilot_request': 0, 'weather_obs': 0, 'weather_daily': 0}
```
The API latency figure is load noise. That test uses in-memory hazards, so it doesn't touch the closure code. Two immediate reruns at load ≈ 31 gave `p50=17.0 ms p95=101.5 ms` and `p50=7.3 ms p95=39.4 ms`. Engine `compare()` on the same graph is unchanged (p50 1.1 ms).

### 0. Cycle 4 run (contract v1.3.0 + ML risk)
`uptime` at start: `load averages: 27.01 18.65 11.32`. The ML artifacts (`models/artifacts/v2-8d19aa86/`, git-ignored) were copied from the ML worktree so the real-provider tests run; without them those 3 tests skip with a reason.
```text
$ set -a; source .env.local; set +a; uv run --project services/api pytest services/routing services/api -rs -p no:cacheprovider -s   # filtered to latency + summary
[latency] SYNTHETIC grid 25x25 over PILOT_BBOX: nodes=625 directed_edges=2400 n=100 compare() p50=3.1 ms p95=7.2 ms max=26.2 ms
[latency] SYNTHETIC grid 60x60 over PILOT_BBOX: nodes=3600 directed_edges=14160 n=100 compare() p50=22.0 ms p95=63.1 ms max=130.8 ms
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=0.7 ms p95=1.3 ms max=1.7 ms (rejected >75 m from network: 48)
[latency] API POST /routes/compare SYNTHETIC toy grid (38 edges), n=100: p50=2.6 ms p95=5.9 ms max=9.7 ms
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=3.1 ms p95=7.0 ms max=10.5 ms
======================= 281 passed, 1 warning in 13.03s ========================
$ # wp_routing must be at alembic head (0004_closure_status) for the closure-activity PostGIS tests
(cd services/routing && uv run ruff check . && uv run ruff format --check .)
All checks passed!
20 files already formatted
$ (cd services/api && uv run ruff check . && uv run ruff format --check .)
All checks passed!
30 files already formatted
$ scripts/check-ownership.sh routing
ownership OK for agent/routing
$ row counts in wp_routing after run
{'edge': 0, 'node': 0, 'community_report': 0, 'pilot_request': 0, 'weather_obs': 0}
```
(The `risk_provider_failed` warnings in the unfiltered output come from tests that deliberately use a failing provider.)

Live uvicorn :8102 with `RISK_PROVIDER=winterpath_ml.inference:load_provider` (fixture graph = real pilot_mini), then stopped:
```text
GET /models/status → {'risk_layer': 'heuristic', 'enabled': False, 'model_id': 'winter311-hgb-v1'}
  limitations[0]: "The ML model did not pass its pre-registered evaluation gate; the map shows a labelled heuristic and no probab…"
POST /routes/compare (2026-01-14T15:00Z) → risk_layer heuristic, unknown_share [0.0, 0.0]
  warnings: ['Risk levels are a heuristic (historical winter 311 report frequency × observed weather): not probabilities and not sidewalk conditions.']
POST /routes/compare, destination >75 m off network → OFF_NETWORK {'which': 'destination', 'max_snap_distance_m': 75.0, 'nearest_network_m': None}
GET /map/segments (pilot_mini bbox, today) → Counter({('low', None, 'model_estimate'): 188, ('moderate', None, 'model_estimate'): 12})
```

Environment: Apple M4 (10 cores, 16 GB), macOS (Darwin 25.6.0), Python 3.12.13, uv 0.10.7. FastAPI 0.162.4, Starlette 1.10.0, Pydantic 2.14.3. PostGIS in the shared Docker container (:55432), DB `wp_routing`. **Shared machine: `uptime` load averages 32.41 / 37.81 / 39.25 during the final runs** (other agent sessions), so latency figures are noisy upper bounds.

### 1. Full routing + API suites, PostGIS enabled (`DATABASE_URL` → `wp_routing`) — cycle 3 run
`wp_routing` schema was created by applying the Data agent's migration to my own DB (`alembic -c db/alembic.ini upgrade head` → `0001_wp_schema_v1 (head)`). The PostGIS tests load real pilot_mini / TEST- weather rows, exercise every DB-backed path, and delete exactly the rows they created.
```text
$ uv run --project services/api pytest services/routing services/api -rs -p no:cacheprovider   # DATABASE_URL=…/wp_routing
services/routing/tests/test_routing_latency.py 
[latency] SYNTHETIC grid 25x25 over PILOT_BBOX: nodes=625 directed_edges=2400 n=100 compare() p50=3.8 ms p95=9.3 ms max=59.2 ms
[latency] SYNTHETIC grid 60x60 over PILOT_BBOX: nodes=3600 directed_edges=14160 n=100 compare() p50=26.0 ms p95=56.9 ms max=111.4 ms
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=1.1 ms p95=2.0 ms max=2.5 ms (rejected >75 m from network: 48)
[latency] API POST /routes/compare SYNTHETIC toy grid (38 edges), n=100: p50=4.6 ms p95=19.6 ms max=128.2 ms
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=5.7 ms p95=11.3 ms max=49.1 ms
======================= 274 passed, 1 warning in 23.37s ========================
$ row counts in wp_routing after run
{'edge': 0, 'node': 0, 'community_report': 0, 'pilot_request': 0, 'weather_obs': 0}
```
(The output above is filtered to latency lines and the summary. The cycle-2 run, unfiltered: `257 passed, 1 warning in 28.62s`, 0 skipped; the 17 new weather tests account for the difference. The single warning is Starlette's `httpx` TestClient deprecation.)

### 2. Lint and ownership gate
```text
$ # wp_routing must be at alembic head (0004_closure_status) for the closure-activity PostGIS tests
(cd services/routing && uv run ruff check . && uv run ruff format --check .)
All checks passed!
20 files already formatted
$ (cd services/api && uv run ruff check . && uv run ruff format --check .)
All checks passed!
29 files already formatted
$ scripts/check-ownership.sh routing
ownership OK for agent/routing
```

### 3. Platform's integration harness against the real API (live uvicorn :8102, default fixture dir = real pilot_mini)
```text
$ curl /coverage (default fixture dir)
{'node_count': 88, 'edge_count': 200, 'largest_component_share': 1.0, 'built_at': '2026-11-10T21:01:47Z', 'osm_snapshot': '2026-11-10T20:43:04Z'} []
$ (cd tests/integration && API_BASE_URL=http://127.0.0.1:8102/api/v1 API_LOG_FILE=<api log> API_ADMIN_TOKEN=<test token> CORS_ALLOWED_ORIGIN=http://localhost:5173 uv run pytest -q -rfs)
SKIPPED [5] .venv/lib/python3.12/site-packages/pluggy/_manager.py:183: Impossible to generate negative test cases
54 passed, 5 skipped in 14.32s
```
History: the first run of this harness against my API (after the v1.1.0 merge) gave **3 failed / 51 passed**, and those failures led to the fixes below. The run above is after the fixes.

### 4. Latency on the REAL pilot_mini fixture (OSM, 200 directed edges, 88 nodes, ~340 m × 280 m)
| Measurement | n | p50 | p95 | max |
|---|---|---|---|---|
| engine `compare()` (both variants), random points in fixture bbox — cycle 3 | 100 routed (48 more rejected as > 75 m from network) | 1.1 ms | 2.0 ms | 2.5 ms |
| same — cycle 2 | 100 | 1.5 ms | 3.8 ms | 6.1 ms |
| same, earlier run under heavier load | 100 | 4.2 ms | 139.1 ms | 649.7 ms |
| API via TestClient, random node-pair ODs — cycle 3 | 100 | 5.7 ms | 11.3 ms | 49.1 ms |
| same — cycle 2 | 100 | 7.5 ms | 20.4 ms | 65.3 ms |
| same, earlier run | 100 | 8.4 ms | 56.1 ms | 109.8 ms |
| live uvicorn :8102, curl `time_total`, sequential node-pair ODs | 30 | ≈4.8 ms | — | 19.2 ms |

Live raw samples (s, sorted): `0.002906 0.003306 0.003402 0.003497 0.003518 0.003586 0.003710 0.003833 0.004220 0.004253 0.004360 0.004376 0.004482 0.004651 0.004703 0.004915 0.004984 0.005216 0.005281 0.005362 0.006905 0.007028 0.007944 0.008397 0.008534 0.009681 0.009937 0.011749 0.012517 0.019160`

Size proxies (SYNTHETIC grids over PILOT_BBOX, final run): 2 400 edges p50 9.1 / p95 45.2 ms; 14 160 edges p50 72.2 / p95 294.5 ms. Earlier runs under heavier load measured up to p95 771 ms and max 2.16 s on the 14 160-edge grid, so p95 < 2 s holds there but max did not always. **The full ~2 km × 1.9 km pilot graph has not been built yet; its latency is unmeasured.**

## Acceptance criteria
| Criterion (docs/agents/routing.md) | Met? | Evidence |
|---|---|---|
| Shortest path correct on hand-checked toy graphs | Yes | `test_routing_engine.py` (hand-computed lengths, partial edges, same-edge forward/reverse); search vs `networkx.dijkstra_path_length` on 20 random graphs |
| …and on real data | Yes | `test_shortest_matches_networkx_oracle_on_node_pairs`: engine distance = NetworkX oracle (±0.05 m) on ≥ 50 real pilot_mini node pairs |
| Dijkstra = A* cost | Yes | synthetic (5 seeds × 15 pairs, random risk + hazards) and real pilot_mini (≥ 100 random pairs) |
| Prohibited edges never used; closures excluded, not penalised | Yes | `test_prohibited_edges_never_used_random_pairs`, `test_confirmed_blocking_closure_is_excluded_not_penalised`, `test_confirmed_closure_excluded_end_to_end` |
| Step-free hard; no route → 404 `NO_ROUTE`, no fallback | Yes | synthetic tests + `test_step_free_on_real_data_never_relaxed` (only 2 directed edges in pilot_mini are tagged step-free; requests fail or use only those) |
| `/routes/compare` schema-valid vs openapi.yaml; 422 `OUTSIDE_COVERAGE` / `OFF_NETWORK`; 400/422 on bad input | Yes | `test_api_contract.py`, `test_api_pilot_mini.py` (3 profiles × 2 locales on real graph); Platform harness 54 passed |
| No fabricated weather/risk; unknown flows through | Yes | weather: observations served unaltered, 503 when stale/absent, forecast always 503 (`test_api_weather.py`); risk: `unknown_share == 1.0`, `RISK_LAYER_UNAVAILABLE`, segments `unknown`, malformed or failing provider → unknown |
| Weather endpoints call an ECCC adapter interface | Yes | `ObservationWeatherAdapter` over `WeatherStore` (fake + PostGIS); PostGIS end-to-end test passes |
| `PostgisGraphProvider` against data-model | Yes | `test_postgis_graph_provider_integration`: real pilot_mini loaded into `wp_routing`, read back identical to `FixtureGraphProvider` (ids, lengths, kinds, access, step_free) |
| `/reports` + moderation + deletion, in-memory + PostGIS | Yes | in-memory lifecycle/expiry/purge tests; `test_api_postgis.py` runs the full lifecycle, hazards, sources and pilot requests on PostGIS |
| Latency p50/p95, 100 pilot OD pairs | Yes (pilot_mini) | table above; full pilot graph pending |
| `pytest services/routing services/api` green; ruff clean | Yes | 281 passed, 0 skipped (cycle 4); ruff output above |

## Cycle 6 — contract v1.5.0
| Item | Change | Evidence |
|---|---|---|
| `wp.report_311_cell.nature` (CR-ML-1) | `/hazards` and route hazards now sum `n` over `nature IN ('requete','plainte')` per (cell, day, category) and apply the k-anonymity floor **after** summing (sums < 3 suppressed), then sum across the 3-day window. Before this, the floor was applied to each stored row before summing. A table without `nature` (pre-v1.5) is summed as-is. Canonical categories get EN/FR titles. | `test_311_sums_natures_then_applies_floor` (real Postgres, session TEMP table with the v1.5 shape, because no migration adds `nature` yet): 1 requete + 2 plainte → shown with `report_count` 3; 2 requete + 5 information → suppressed; 2 + 2 on different days → suppressed (floor per day) |
| CR-ROUTING-4 (accepted, v1.5 wording) | `DELETE /reports/{id}`: a wrong, **missing or malformed** token, or an unknown or **non-UUID** id, now returns **404 `NOT_FOUND`** with an identical body. Before this, malformed input returned 422. Admin endpoints keep 422 for a malformed id. | `test_api_contract.py`: 5 bad-deletion variants, all 404 and schema-valid |
| CR-ROUTING-9 (accepted) | No change needed: the catalog already matches the documented mapping | — |
| `CONTRACT_VERSION` | `1.5.0` (`openapi.yaml` `info.version` is now 1.5.0) | — |

**Points for the coordinator:**
- **The v1.5 evidence mapping says "closures → confirmed".** My cycle-5 codes `PASSES_POSSIBLE_CLOSURE` / `AVOIDS_POSSIBLE_CLOSURE` use **`unknown`**, because the statement they make ("may be in effect") rests on unknown activity, even though the permit itself is confirmed. I kept `unknown`. Please confirm, or tell me to use `confirmed`.
- **The mapping doesn't list two codes:** `REDUCED_MOBILITY_SPEED` (currently `model_estimate`, an assumed speed) and `RISK_UNKNOWN_SHARE` (`unknown`).
- **For Platform:** any harness case that expected 422 for a malformed deletion token or id must now expect 404.
- **Not acted on:** the v1.5 path-type policy (Geofabrik, `service`/`cycleway` only with explicit foot permission, corridors excluded) is enforced at graph build (Data). Routing still excludes edges whose `foot_access` is `no` or `private`, regardless of source.

## Cycle 5 — closure activity (contract v1.4.0, CR-ROUTING-7) and `terminal_at`
Rule (data-model v1.4): `wp.closure_active_at(c, t)` is three-valued. An edge is excluded only when the closure is active at `t` **and** `blocks_passage` is true. `NULL` (unknown activity) must be flagged or penalised, never treated as clear.

| Closure at departure time | `blocks_passage` | Routing | Response |
|---|---|---|---|
| `active = true` | `true` (confirmed) | **Excluded** (both directions, ≤ 5 m) | `EXCLUDES_CONFIRMED_CLOSURE`; `NO_ROUTE` if that disconnects the pair (never relaxed) |
| `active = null` | `true` (confirmed) | **Not excluded; +120 s per edge** (`possible_closure_penalty_s`, larger than the 45 s passable disruption) | `PASSES_POSSIBLE_CLOSURE` / `AVOIDS_POSSIBLE_CLOSURE` (evidence `unknown`), id in `hazards_on_route` / `hazards_avoided`, EN/FR warning "…its schedule at this time is unknown: it may be in effect." |
| `active = true` or `null` | `false`/`null` | Passable disruption, +45 s | `PASSES/AVOIDS_CONFIRMED_DISRUPTION` |
| `active = false` | any | Ignored (row not returned) | — |

- **Repository:** `PostgisHazardRepository` selects `wp.closure_active_at(c, :at) AS active … WHERE wp.closure_active_at(c, :at) IS DISTINCT FROM false`. On a database without the function (before migration 0004) it keeps the old validity-window filter.
- **Labelling:** an unknown-activity hazard keeps evidence `confirmed`, because the permit itself is confirmed official data. Its title gains "— schedule at this time unknown" / "— horaire à ce moment inconnu", and its evidence note says activity is unknown.
- **API reach:** `/routes/compare` evaluates closures at `departure_time`. `/hazards` and `/map` evaluate them at the current time, because they have no `at` parameter.

Tests:
- Engine on the toy grid (6):
  - unknown activity is penalised and not excluded, with a cost above the no-hazard cost, a flag and a warning;
  - the penalty takes part in the winter-aware choice;
  - unknown activity on a non-blocking permit is a disruption;
  - an active blocking closure is still excluded;
  - the penalty ordering holds;
  - the new texts make no safety claim.
- PostGIS on `wp_routing` with the **real `wp.closure_active_at` from migration 0004** (2):
  - 8 TEST-RT closures are classified as expected: all-day active and inside a 09:00–17:00 window → true; no schedule and status `unknown` → null; wrong weekday, ended, cancelled, and outside an evening window → dropped;
  - through the API, an unknown-schedule closure on the shortest route is flagged and penalised but still routed, and the same point with an active closure is excluded.

On this toy grid a 3-edge detour costs more than 120 s, so the winter-aware route keeps the edge but flags it. The 120 s value is a reviewable design choice, set in `CostConfig.possible_closure_penalty_s`.

**`terminal_at` (v1.3, migration 0003 now applied):**
- `PostgisReportRepository` writes it on reject (`now`), reporter delete (`now`) and expiry (`expires_at`, the moment it expired, matching the migration backfill).
- The 30-day hard delete uses `COALESCE(terminal_at, moderated_at, expires_at)`, and the column is detected so pre-0003 databases keep the old rule.
- PostGIS test: all three timestamps are written, and the purge deletes at +30 days, not +29.
- `purge()` is still not scheduled.

**`wp.edge.name`** now exists in `wp_routing`. The provider selects it, and pilot_mini rows carry none, so street names are still null on real data.

**`CONTRACT_VERSION` stays `1.3.0`:** v1.4.0 changed only the data model, and `openapi.yaml` `info.version` is still 1.3.0.

Observation for Data (not a request): `closure_active_at` returns `NULL` for `status = 'unknown'` **before** checking dates. A permit with an unmapped status whose `valid_to` is long past is therefore "unknown" rather than "false". Routing treats it as a possible closure (penalised and flagged). If the intent is that dates alone can establish `false`, the date check could move above the status check.

## Cycle 4 — contract v1.3.0 and ML risk layer
| Item | Done | Where / evidence |
|---|---|---|
| 422 `OFF_NETWORK` when a point is inside the bbox but > 75 m from the network (`details.which`, `max_snap_distance_m`, plus `nearest_network_m`) | Yes | `routers/routing.py`; `test_api_contract.py`, `test_api_pilot_mini.py`. Outside the bbox is still `OUTSIDE_COVERAGE`. |
| 503 `UPSTREAM_UNAVAILABLE` on `/routes/compare`, `/map/segments`, `/hazards`, `/data-sources` | Already implemented; now validated against the v1.3 declarations | `test_api_contract.py` (graph/store down) |
| `CONTRACT_VERSION` | `1.3.0` | `winterpath_api/__init__.py` |
| `wp.edge.name` | Read when the column exists (same presence check as the v1.2 columns) | `providers.py` `OPTIONAL_EDGE_COLS`; present in `wp_routing` since cycle 5 |
| `wp.community_report.terminal_at` | Adopted in cycle 5 | see Cycle 5 |
| Canonical source ids | Already in use | `/data-sources` registry |
| ML risk: `RISK_PROVIDER=winterpath_ml.inference:load_provider` | Yes | see below |

**ML wiring.** `winterpath_ml.inference.RiskProvider.edge_risk` takes edge **coordinates** (`[lon, lat]` polyline) and a time, not edge ids. `adapters.CoordinateRiskAdapter` therefore:
- looks each edge's geometry up in the loaded routing graph (`build_state` passes the lookup);
- takes `risk_layer` from `status()["risk_layer"]`. The registry's active layer is `heuristic`, and `/models/status` is the ML package's `model_status()`, validated against the contract;
- normalises each estimate. A provider exception, missing geometry or a malformed value becomes `unknown`, and unknown keeps the +3 s/100 m penalty (`test_unknown_keeps_unknown_penalty_in_routing`);
- caches per (edge id, Montréal local day), because the ML layers are daily score tables;
- without a graph returns `NullRiskProvider`, since there is no geometry to look up.

The heuristic layer gives `probability: null` and evidence `model_estimate` with `source_ids ["mtl-311", "eccc-geomet"]`. Out of season (May–Oct) or outside coverage everything is `unknown`. Real pilot_mini, 200 edges:

| Day | Result (level × count) |
|---|---|
| 2026-11-10 | low 188, moderate 12 |
| 2026-01-14 | moderate 140, elevated 48, high 12 |
| 2026-07-01 | unknown 200 |

Every estimate had probability None.

**Honesty addition:** when `risk_layer == "heuristic"` the route response carries a localized warning (EN/FR) saying the levels are a heuristic of 311 reporting × observed weather, not probabilities and not sidewalk conditions. CR-9's explanation evidence states and CR-4's 404 on a wrong deletion token are **unchanged**, pending the decision.

Tests (`services/api/tests/test_api_ml_risk.py`, 7):
- 4 use a fake coordinate provider labelled TEST FIXTURE: normalisation and caching; failure → unknown; unknown keeps the penalty; loader without a graph → Null.
- 3 use the real ML package and registry artifacts: in season through the API with schema validation and `/models/status`; probability null with `model_estimate`; out of season → `unknown_share` 1.0. They **skip with a reason when the git-ignored artifacts are absent**, so a fresh checkout shows 3 skips until `models/artifacts/v2-8d19aa86/` is present.

FYI for ML: `model_status()` reports `model_id: "winter311-hgb-v1"` (the gated-off model) while the active layer is the heuristic `winter311-heuristic-v1`. The API passes it through unchanged. Consider reporting the active layer's id, or say which you intend.

## Cycle 3 — ECCC WeatherAdapter (`services/api/src/winterpath_api/weather.py`)
Reads `wp.weather_obs` (migration 0001) and, when the table exists, `wp.weather_daily` (data-model v1.2; **no migration creates it yet**, so it is detected with `to_regclass` and treated as absent).

| Endpoint / field | Behaviour |
|---|---|
| `/weather/current` | Latest observation for `WEATHER_STATION_IDS` (priority order; default = most recent across stations). Values are passed through **unaltered**. Evidence: `confirmed`, `source_ids: ["eccc-geomet"]`, `observed_at`, `retrieved_at` = the ingest run's `finished_at`. |
| stale / absent | **503 `UPSTREAM_UNAVAILABLE`** when there is no row, the store errors, or the latest observation is older than `WEATHER_MAX_AGE_MINUTES` (default 180). Historical training-window rows are therefore never presented as current. |
| `freeze_thaw_24h` | From hourly temperatures in the 24 h before the observation: `true` if min < 0 °C < max; `false` only with ≥ 18 distinct hours of temperature and no crossing; otherwise `null` (noted in evidence). Touching exactly 0 °C is not a crossing. |
| `snow_depth_cm` | Hourly value. Only if that is null, falls back to `weather_daily.snow_on_ground_cm` for the observation's climate day (LST = UTC−5), and the evidence note says so. |
| `precipitation_mm_1h` | `weather_obs.precip_mm` only. Daily totals are never presented as 1-hour precipitation. |
| `/weather/forecast` | Always **503**: no forecast product is ingested, and observations are not a forecast. |
| `/health` `checks.weather` | `disabled` (no adapter) / `ok` (fresh observation) / `degraded` (stale, absent or store error, with reason). |

Enabled with `WEATHER_SOURCE=postgis` plus `DATABASE_URL`. Tests (`services/api/tests/test_api_weather.py`, 17):
- fake-store unit tests: pass-through, staleness, store failure, 6 freeze-thaw cases, daily fallback and its labelling, hourly-wins, station priority, forecast;
- API responses validated against openapi.yaml (fresh → 200; stale → 503 + health degraded);
- a PostGIS end-to-end test on `wp_routing`: inserts 25 hourly rows for station `TEST-IT-ROUTING` and deletes them afterwards.

Not done or not verifiable here:
- `wp.weather_daily` is not exercised against PostGIS (the table doesn't exist in any migration).
- I did not query the Data agent's `wp_data` (not my DB). If it holds only historical `climate-hourly` rows, `/weather/current` will correctly answer 503 (stale) in integration until a near-real-time `swob-realtime` ingest runs.

## Fixes made after integration (cycle 2)
1. **Privacy (found by Platform harness):** uvicorn's own access log wrote full query strings (precise bbox coordinates) and client IPs. It is now disabled from inside the app (`logs.py`), so this holds however uvicorn is launched; our middleware logs path/status/duration only. Log timestamps are now at millisecond precision.
2. **Contract v1.1.0:** a malformed report id or deletion token now returns 422 on DELETE and moderation (declared in v1.1.0). A well-formed but wrong token still returns 404, so report existence is never revealed. `CONTRACT_VERSION` is 1.1.0.
3. **PostGIS bug (found by the new DB tests):** the admin listing used `(:status IS NULL OR status = :status)`, which Postgres rejects as an untyped parameter. The filter is now built explicitly.
4. **pilot_mini / data-model v1.2:**
   - Crossing metadata is read from nested `crossing: {type, kerb}` (fixture) or flat `crossing_type`/`crossing_kerb` (v1.2 columns).
   - v1.2 edge columns are selected only when the applied migration has them: migration `0001` does not yet create `crossing_type`/`crossing_kerb`.
   - `built_at` falls back to `manifest.json` `finished_at`.
   - Source id `mtl-voirie-trottoir` → `mtl-voirie`, the Data agent's canonical id.
5. **Earlier (cycle 1):** inadmissible A* heuristic (measured to the raw click instead of the snapped point; caught by the Dijkstra = A* test). Per-thread pyproj initialisation of 17–94 ms is now absorbed by a pre-warmed compute pool.

## Design notes (unchanged from cycle 1)
- **Cost (s, ≥ 0):** `length_m / speed` (1.3 m/s; 0.9 m/s for `reduced_mobility`) plus:
  - confirmed passable disruption +45 s per edge;
  - unverified reports +20 s per edge, only when `avoid_unverified_reports`;
  - risk penalty × {0, 0.15, 0.40, 1.0}, only for `model_estimate`/`simulated` evidence;
  - **unknown risk +3.0 s per 100 m** (must be > 0; counted in `unknown_share`);
  - unlit +5 %;
  - `reduced_mobility` soft penalties for steps (+300 s) and unknown step_free (+10 %).
- **Hard exclusions:** foot_access no/private; confirmed `blocks_passage = true` hazards active at departure time (≤ 5 m in EPSG:32188); `step_free is not True` under the `step_free` profile; edges outside the largest component (other components are reported as gaps, never bridged).
- **Snapping:** ≤ 75 m via virtual partial-edge nodes, so the shared graph is never mutated.
- **Responses:** both variants are always returned, with `identical`.
- **Wording:** a test guarantees the explanation catalog never says safe / cleared / ice-free / wheelchair accessible.

## Blockers
| Blocker | Impact | Next step / who |
|---|---|---|
| Full pilot graph (whole PILOT_BBOX) not built | Real-data latency known only for 200 edges; synthetic 14k-edge proxy given | Data agent; rerun `test_routing_latency` pattern on it (routing) |
| ML artifacts are git-ignored | Real-ML tests skip in a checkout without `models/artifacts/<run_id>/`; the API falls back to `NullRiskProvider` (all unknown) | Coordinator: decide how artifacts reach the integration worktree |
| No forecast source ingested | `/weather/forecast` is always 503 (by design) | Decision (coordinator/user): ingest ECCC `citypageweather-realtime` into a table, or approve a live adapter |
| No near-real-time weather ingest confirmed | `/weather/current` answers 503 (stale) unless `weather_obs` has a row newer than 180 min | Data agent: schedule a `swob-realtime` ingest (scheduled jobs need approval) |
| Report `purge()` not scheduled | Expiry is enforced on read; 30-day hard delete only when `purge()` is called | Platform/coordinator (scheduled jobs need approval) |

## Dependencies on other agents
- **Data:** fixture layout as delivered (`edges/nodes.geojson`, `metadata.json` with explicit `simulated`, `manifest.json`). `wp.source` ids are canonical. Migrations 0001–0004; `wp.closure_active_at(c, t)` semantics as in migration 0004.
- **ML:** `winterpath_ml.inference.load_provider()` → `edge_risk(coords, valid_from)`, `cell_risk`, `status()` (coordinate-keyed; adapted). Id-keyed providers (`edge_risk(edge_ids, at)`) are still accepted.
- **Platform:** harness passes against this API.
- **Frontend:** both routes are always returned; `explanation[].evidence_state` drives badges; `warnings` are localized.

## Licensing / data notes
- No external data was downloaded or committed by this agent.
- Real data used: the Data agent's `data/fixtures/pilot_mini` (OSM, ODbL; see its `ATTRIBUTION.md`).
- Synthetic data: `services/routing/tests/fixtures/synthetic/toy_grid` (`simulated: true`), used only in tests.
- `/data-sources` licence and attribution text is transcribed from `docs/data-sources-and-licenses.md`. Licence URLs for CC BY 4.0, ODbL 1.0 and the ECCC licence page come from my own knowledge, not re-fetched — please verify.
- Integration tests write to `wp_routing` (my own DB) only and clean up after themselves.

## Change requests (contracts)
Resolved by v1.3.0 and adopted in cycle 4: 503 declarations (old #2), `OFF_NETWORK` (old #3), `wp.edge.name` (old #4; read when migrated), `wp.community_report.terminal_at` (old #5; awaiting migration), and `.env.example` routing names (old #1, partly).

Resolved by v1.4.0 and adopted in cycle 5: closure status vocabulary and activity (old #6, CR-ROUTING-7). Migrations 0002–0004 are applied to `wp_routing`.
Resolved by v1.5.0 and adopted in cycle 6: CR-ROUTING-4 (404 for any bad deletion attempt) and CR-ROUTING-9 (explanation evidence mapping, old #7).

Still open (pending coordinator/user decision; not implemented):
1. `.env.example`: still missing `WEATHER_SOURCE`, `WEATHER_MAX_AGE_MINUTES`, `WEATHER_STATION_IDS`. Also: `RISK_PROVIDER=winterpath_ml.inference:load_provider` enables the ML layer, and `API_ADMIN_TOKEN_HASH` = SHA-256 hex of the token (optional `sha256:` prefix).
6. openapi (additive, new in cycle 5): `HazardFeature.properties.active: boolean | null` (closure activity at the evaluated time). Today "schedule unknown" reaches the map only through `title_en/fr` and `evidence.note`, so the frontend cannot badge it reliably.
7. Confirm that both routes are returned when they are identical (the evidence-state part was resolved by v1.5).
8. **Platform (FYI, not a contract change):** `tests/integration/log_scan.py` flags fractional seconds of microsecond ISO timestamps (e.g. `…:40.010135Z`) as latitudes. I avoided this by logging milliseconds, but other services may trip it.
9. data-model (clarify, cycle 3): the interval of `wp.weather_obs.precip_mm`. I serve it as `precipitation_mm_1h`, which is correct for `climate-hourly` and for SWOB's 1-hour amount. Please confirm the ingest stores the 1-hour value for `swob-realtime`. Also: `wp.weather_daily` needs a migration.

(Withdrawn: the source-id CR is resolved by the Data agent's canonical ids. The `DELETE /reports` 404/422 question is resolved by v1.1.0.)

## Review readiness
READY FOR REVIEW. The worktree is clean after this commit. Coordinator re-run (copy `models/artifacts/v2-8d19aa86/` from the ML worktree first, or expect 3 reasoned skips):
```bash
cd ../winterpath-routing
set -a; source .env.local; set +a          # DATABASE_URL → wp_routing (schema: alembic -c db/alembic.ini upgrade head)
uv run --project services/api pytest services/routing services/api -rs
# wp_routing must be at alembic head (0004_closure_status) for the closure-activity PostGIS tests
(cd services/routing && uv run ruff check . && uv run ruff format --check .)
(cd services/api && uv run ruff check . && uv run ruff format --check .)
scripts/check-ownership.sh routing
```
