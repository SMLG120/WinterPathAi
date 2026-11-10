# Agent report — routing

- **Status:** READY FOR REVIEW (with blockers below: no real pilot graph yet, PostGIS schema not migrated, ML provider not landed)
- **Branch / SHA:** `agent/routing` @ `dbef3dc` (code). This report is committed on top of it.
- **Date (UTC):** 2026-11-10

## Files changed
`git diff --stat $(git merge-base integration/winterpath HEAD) HEAD` → `51 files changed, 8632 insertions(+)` (code commit; ~3.1k of those lines are the two `uv.lock` files and the generated synthetic fixture GeoJSON).

```
services/routing/                         winterpath_routing (pure Python; no FastAPI imports)
  src/winterpath_routing/models.py        value types mirroring contract (Evidence, RiskEstimate, Edge, Hazard…)
  src/winterpath_routing/geo.py           EPSG:4326 ⇄ EPSG:32188, haversine, bearings, per-thread warm-up
  src/winterpath_routing/providers.py     GraphProvider protocol, FixtureGraphProvider, PostgisGraphProvider
  src/winterpath_routing/graph.py         NetworkX MultiDiGraph + STRtree, components, gap reporting
  src/winterpath_routing/filters.py       hard exclusions
  src/winterpath_routing/costs.py         cost model (seconds, ≥ 0), CostConfig
  src/winterpath_routing/search.py        Dijkstra / A* (label-setting, rejects negative weights)
  src/winterpath_routing/engine.py        snapping, context, compare(), route assembly, explanations
  src/winterpath_routing/steps.py         EN/FR list directions
  src/winterpath_routing/explain.py       explanation-code catalog (EN/FR, evidence state per code)
  src/winterpath_routing/risk.py          RiskProvider protocol + NullRiskProvider
  tests/…                                 search, engine, providers/costs, latency
  tests/fixtures/synthetic/toy_grid/      SYNTHETIC fixture, metadata "simulated": true (+ generator script)
services/api/                             winterpath_api (FastAPI)
  src/winterpath_api/main.py              app factory, request-id + access-log middleware, CORS
  src/winterpath_api/schemas.py           Pydantic v2 models hand-written from openapi.yaml
  src/winterpath_api/routers/*.py         system, map, routing, reports/admin
  src/winterpath_api/repositories/*.py    reports, hazards, sources, pilot requests (memory + PostGIS)
  src/winterpath_api/adapters.py          risk adapter (normalising), WeatherAdapter protocol
  src/winterpath_api/compute.py           pre-warmed route-compute thread pool
  src/winterpath_api/{errors,logs,params,security,settings,state,deps}.py
  tests/…                                 contract validation against docs/contracts/openapi.yaml, adapters
```

## Commands run and literal results
Environment: Apple M4 (10 cores, 16 GB), macOS (Darwin 25.6.0), Python 3.12.13, uv 0.10.7. FastAPI 0.162.4, Starlette 1.10.0, Pydantic 2.14.3. **The machine was shared with other agent sessions; `uptime` load averages were 31.83 / 49.18 / 40.49**, so latency numbers are noisy upper bounds.

```text
$ uv run --project services/api pytest services/routing services/api -rs -p no:cacheprovider
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.2.0, pluggy-1.7.0
rootdir: /Users/smlgmac/Projects/Geography/winterpath-routing/services/routing
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 238 items
services/routing/tests/test_routing_engine.py .......................... [ 10%]
......                                                                   [ 13%]
services/routing/tests/test_routing_latency.py 
[latency] SYNTHETIC grid 25x25 over PILOT_BBOX: nodes=625 directed_edges=2400 n=100 compare() p50=16.9 ms p95=77.8 ms max=245.0 ms
.
[latency] SYNTHETIC grid 60x60 over PILOT_BBOX: nodes=3600 directed_edges=14160 n=100 compare() p50=70.5 ms p95=265.2 ms max=1000.0 ms
.                        [ 14%]
services/routing/tests/test_routing_providers.py ....................... [ 23%]
........................................................................ [ 54%]
...............................................s                         [ 74%]
services/routing/tests/test_routing_search.py ......................     [ 83%]
services/routing/tests/test_api_adapters.py .....s
[latency] API POST /routes/compare SYNTHETIC toy grid (38 edges), n=100: p50=7.6 ms p95=21.7 ms max=42.1 ms
.                      [ 86%]
services/routing/tests/test_api_contract.py ............................ [ 98%]
....                                                                     [100%]
=============================== warnings summary ===============================
services/api/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
=========================== short test summary info ============================
SKIPPED [1] services/routing/tests/test_routing_providers.py:142: DATABASE_URL not set
SKIPPED [1] services/api/tests/test_api_adapters.py:105: DATABASE_URL not set
================== 236 passed, 2 skipped, 1 warning in 23.71s ==================
```
(The API test files print as `services/routing/tests/test_api_*.py` because pytest picks `services/routing` as rootdir when both directories are passed. They live in `services/api/tests/`. The single warning is Starlette's deprecation of `httpx` in its TestClient.)

DB integration tests with this worktree's `.env.local` loaded (`DATABASE_URL` → `wp_routing` on :55432; Docker was up by then):
```text
SKIPPED [1] services/routing/tests/test_routing_providers.py:142: wp.edge table absent (Data agent migrations not applied)
SKIPPED [1] services/api/tests/test_api_adapters.py:105: wp.community_report absent (Data agent migrations not applied)
```

Lint and ownership gate:
```text
$ (cd services/routing && uv run ruff check . && uv run ruff format --check .)
All checks passed!
19 files already formatted
$ (cd services/api && uv run ruff check . && uv run ruff format --check .)
All checks passed!
25 files already formatted
$ scripts/check-ownership.sh routing
ownership OK for agent/routing
```

Live smoke test (`ROUTING_FIXTURE_DIR=../routing/tests/fixtures/synthetic/toy_grid uv run uvicorn winterpath_api.main:app --port 8102`):
```text
GET /api/v1/health → {"status":"degraded",…,"graph":{"status":"degraded","detail":"SIMULATED fixture graph loaded."},"database":{"status":"disabled",…},"risk":{"status":"disabled",…},"weather":{"status":"disabled",…}}
POST /routes/compare (locale fr) → risk_layer none, identical True, warnings ['SIMULÉ : données de démonstration synthétiques.', 'Aucune couche de risque : risque inconnu sur tout le trajet.']
  winter_aware 390.0 m 300.0 s unknown_share 1.0; codes ['SIMULATED_DATA','WINTER_AWARE_COST','IDENTICAL_TO_SHORTEST','RISK_LAYER_UNAVAILABLE']
  steps ['Partez en direction du nord sur Synthetic Lane 0', 'Tournez à droite sur Synthetic Street C', 'Vous êtes à destination']
GET /weather/current → {"code":"UPSTREAM_UNAVAILABLE","message":"ECCC current observation (no adapter configured) is unavailable; no weather values are returned.",…}
20 sequential POST /routes/compare, curl time_total (s), sorted:
0.003035 0.003050 0.003143 0.003292 0.003420 0.003533 0.003536 0.003587 0.003667 0.003804 0.004293 0.005362 0.005663 0.006200 0.007791 0.008321 0.008937 0.010974 0.011762 0.018164
```

### Latency measurements (all on SYNTHETIC graphs — no real pilot graph exists yet)
| Run | Graph | n | p50 | p95 | max |
|---|---|---|---|---|---|
| engine `compare()` (run A) | 25×25 grid over PILOT_BBOX, 2 400 directed edges | 100 random OD | 8.8 ms | 18.2 ms | 34.0 ms |
| engine `compare()` (run B, final) | same | 100 | 16.9 ms | 77.8 ms | 245.0 ms |
| engine `compare()` (run A) | 60×60 grid, 14 160 directed edges | 100 | 53.7 ms | 189.3 ms | 305.6 ms |
| engine `compare()` (run B, final) | same | 100 | 70.5 ms | 265.2 ms | 1000.0 ms |
| API via TestClient (run A) | toy grid, 38 edges | 100 | 6.3 ms | 22.3 ms | 59.2 ms |
| API via TestClient (run B, final) | same | 100 | 7.6 ms | 21.7 ms | 42.1 ms |
| live uvicorn :8102, curl | toy grid | 20 sequential | ≈4.0 ms (median of 20) | — | 18.2 ms |

"compare()" computes both variants (Dijkstra shortest-distance + A* winter-aware), including snapping, exclusions, risk lookup and step generation. The 60×60 grid is a size proxy for the ~2 km × 1.9 km pilot, not its topology. **p95 < 2 s was met on synthetic graphs only; it has not been measured on the real pilot graph.**

Performance fix found during measurement: before `compute.py`, live requests took 0.10–0.35 s on the 38-edge graph. Cause (measured): pyproj builds its transformer per thread on first use, costing 17–94 ms per transformer, so requests landing on fresh FastAPI threadpool threads paid that cost. Route computation now runs on a dedicated pool whose workers warm their transformers at startup (`ROUTING_WORKERS`, default 4).

## Acceptance criteria
| Criterion (docs/agents/routing.md) | Met? | Evidence |
|---|---|---|
| Shortest path correct on hand-checked toy graphs | Yes | `test_shortest_hand_checked_and_never_uses_prohibited_shortcut`, `test_step_free_is_hard_constraint` (perimeter length checked), `test_snap_within_limit_and_partial_edges`, `test_same_edge_forward_and_reverse`; search checked against `networkx.dijkstra_path_length` on 20 random graphs |
| Dijkstra = A* cost | Yes | `test_dijkstra_equals_astar_generalized_cost` (5 seeds × 15 OD pairs, generalized and time weights, random risk + hazards) |
| Prohibited edges never used | Yes | `test_prohibited_edges_never_used_random_pairs` (100 random pairs); `foot_access=no` diagonal shortcut never chosen |
| Closures excluded (not penalised) | Yes | `test_confirmed_blocking_closure_is_excluded_not_penalised`, `test_confirmed_closure_excluded_end_to_end`; unconfirmed "blocking" reports are not hard-excluded (`test_unconfirmed_blocking_report_is_not_a_hard_exclusion`) |
| Step-free hard; no route → 404 `NO_ROUTE`, no fallback | Yes | `test_step_free_no_route_is_404_not_fallback`, `test_step_free_no_route_returns_404` |
| `/routes/compare` responses validate against openapi.yaml | Yes | `test_compare_routes_schema_valid` (3 profiles × 2 locales), validated with jsonschema Draft 2020-12 + FormatChecker against the contract file itself |
| 422 outside coverage; 400/422 on bad input | Yes | `test_compare_routes_error_cases` (outside bbox, >75 m from network, malformed JSON → 400, missing/extra field, lat 91, bad profile, same point) |
| No fabricated weather/risk; unknown flows through as `unknown` | Yes | weather → 503 (`test_weather_unavailable_is_503_not_invented`); `unknown_share == 1.0` + `RISK_LAYER_UNAVAILABLE`; segments `risk.level/evidence.state == unknown`; malformed/failing provider output → unknown (`test_api_adapters.py`) |
| `pytest services/routing services/api` green | Yes | 236 passed, 2 skipped (DB tests, reasons above) |
| ruff clean | Yes | output above |
| Every v1 endpoint implemented | Yes | `test_all_contract_operations_are_implemented` compares contract paths with the app's generated OpenAPI |
| Error envelope, bbox limit, pagination, CORS, rate limiting, admin hash auth, logs rounded to 3 dp | Yes | `test_hazards_bbox_validation`, `test_segments_pagination_and_unknown_risk`, `test_admin_pagination`, `test_cors_allow_list`, `test_rate_limit`, `test_admin_auth`, `test_logs_round_coordinates` (asserts 4-dp coordinates and report descriptions never appear in logs) |
| `/reports` + moderation + deletion, in-memory + PostGIS repos | Partly | In-memory fully tested (`test_report_lifecycle_and_moderation`, expiry/purge). PostGIS repositories are written but **untested**: the `wp` schema is absent |
| `PostgisGraphProvider` coded against data-model.md | Partly | Written; integration test skipped (schema absent) |
| Latency p50/p95 for 100 pilot OD pairs | Partly | Measured on synthetic graphs only (table above); real pilot graph unavailable |

## Design notes (for review)
- **Cost model** (`costs.py`, all seconds): `base = length_m / speed` (1.3 m/s; 0.9 m/s for `reduced_mobility`). `+45 s` per edge with a confirmed, passable disruption. `+20 s` per edge with unverified reports, only when `avoid_unverified_reports`. Risk penalty = base × {low 0, moderate 0.15, elevated 0.40, high 1.0}, applied only for `model_estimate`/`simulated` evidence. **`unknown_penalty_s_per_100m = 3.0`** (≈ +3.9 % at 1.3 m/s, must be > 0, counted in `unknown_share`). Risk with any other evidence state is treated as unknown. Unlit edges +5 %. `reduced_mobility`: +300 s on steps / `step_free=false`, +10 % when step_free is unknown (soft; only `step_free` is hard).
- **Hard exclusions:** `foot_access ∈ {no, private}`; confirmed hazards with `blocks_passage = true` that are active at `departure_time` (matched to edges within 5 m in EPSG:32188); `step_free is not True` under the `step_free` profile; edges outside the largest connected component (other components are listed as `/coverage` gaps, never bridged).
- **Snapping:** nearest allowed edge ≤ 75 m (EPSG:32188), with partial-edge virtual start and end nodes, so the shared graph is never mutated. The A* heuristic uses distance to the *snapped* point × 0.999 / speed. An earlier version measured to the raw click point and was inadmissible; the Dijkstra = A* test caught it.
- **Routes:** always returns both `shortest` (Dijkstra on distance) and `winter_aware` (A* on generalized cost), with `identical` set when they match.
- **Explanation evidence states:** `SHORTEST_DISTANCE`/`WINTER_AWARE_COST` → `unknown` (they state conditions are not verified). `STEP_FREE_TAGGED_ONLY`/`INCLUDES_STEPS` → `unverified_report` (community-mapped OSM tags). Closures/disruptions → `confirmed`. Reports → `unverified_report`. `LOWER_MODELED_RISK` → `model_estimate`. Synthetic graph → `SIMULATED_DATA` (`simulated`) plus a warning. A test checks the catalog never says safe / cleared / ice-free / wheelchair accessible (EN/FR).
- **Privacy:** access logs record path, status and duration only (no query string, body or IP). A structlog processor rounds coordinate-like fields to 3 dp and redacts email/description/token fields. Rate-limit keys are an HMAC of the client IP with a per-process secret, rotated daily. Validation errors never echo input values. The deletion token is shown once; only its SHA-256 is stored; wrong or missing tokens get 404.
- **`/data-sources`** without a DB lists the 6 API data sources from `docs/data-sources-and-licenses.md` with `status: disabled` (`requires_credentials` for Planif-Neige), `last_success_at`/`record_count: null` and a note "Not ingested by this API instance". With PostGIS, `wp.source` is authoritative. Basemap rows (OpenFreeMap, Protomaps) are omitted as frontend concerns.

## Blockers
| Blocker | Impact | Next step / who |
|---|---|---|
| `data/fixtures/pilot_mini/` not on `integration/winterpath` | All tests and latency figures use synthetic graphs; real-graph correctness and latency are unmeasured | Data agent publishes the fixture; then run `ROUTING_FIXTURE_DIR=… pytest` + latency on it (routing) |
| `wp.*` schema not migrated in `wp_routing` | `PostgisGraphProvider` and PostGIS report/hazard/source/pilot repos untested (2 tests skipped) | Data agent migrations; apply to `wp_routing`; rerun with `.env.local` loaded |
| ML `RiskProvider` not landed | Only `none` risk layer exercised end-to-end (plus test doubles) | ML agent; set `RISK_PROVIDER=winterpath_ml.inference:<factory>` |
| No concrete ECCC weather adapter | `/weather/*` always 503 (correct per brief, but no live weather) | Follow-up: implement `WeatherAdapter` over GeoMet `swob-realtime` / `citypageweather` or read `wp.weather_obs` |
| Report purge not scheduled | `purge()` exists (expiry, 30-day hard delete) but nothing calls it periodically | Platform / coordinator decide on cron (architecture §10 requires approval) |

## Dependencies on other agents
- **Data:** fixture layout assumed = `edges.geojson` (feature `id` = `edge_id`; properties per `wp.edge` columns), `nodes.geojson`, `metadata.json` with **explicit** `"simulated"` (the loader refuses a fixture without it), optional `osm_snapshot`, `built_at`, `source_freshness`.
- **ML:** provider must expose `edge_risk(edge_ids, at)`. The adapter also reads an optional `risk_layer` attribute (`model|heuristic|none`) and an optional `model_status()` dict for `/models/status`.
- **Frontend:** both routes are always returned; `explanation[].evidence_state` drives badges; `warnings` are localized strings.

## Licensing / data notes
No external data was downloaded or committed. The only graph committed is the synthetic toy grid (40 KB, metadata `"simulated": true`, `source_ids: ["synthetic"]`). `/data-sources` licence and attribution strings are transcribed from `docs/data-sources-and-licenses.md`. Licence URLs not given there (CC BY 4.0, ODbL 1.0, ECCC licence page) were filled from my knowledge, not re-fetched — please verify.

## Change requests (contracts)
1. **`.env.example` (coordinator):** add `ROUTING_GRAPH_SOURCE` (`fixture|postgis|none`), `ROUTING_FIXTURE_DIR`, `API_STORE_BACKEND` (`memory|postgis`), `RISK_PROVIDER` (`none` | `module:factory`), `ROUTING_WORKERS`. `API_ADMIN_TOKEN_HASH` = SHA-256 hex of the token (optional `sha256:` prefix).
2. **openapi.yaml (additive):** declare `503 Unavailable` on `/routes/compare`, `/map/segments`, `/hazards`, `/data-sources`. The implementation returns `503 UPSTREAM_UNAVAILABLE` when the graph or a store is unavailable rather than inventing data; the contract currently lists 503 only for weather.
3. **openapi.yaml (clarify):** a point inside the pilot bbox but > 75 m from the routable network currently returns `422 OUTSIDE_COVERAGE` with `details.which` and `details.max_snap_distance_m`. Consider a dedicated code (e.g. `OFF_NETWORK`).
4. **openapi.yaml (clarify):** `DELETE /reports/{id}` with a missing, short or invalid `X-Deletion-Token` (or non-UUID id) returns 404 to avoid revealing whether a report exists. The contract marks the header required and declares no 422; please confirm.
5. **data-model.md (additive):** `wp.edge.name text null`. Without it, PostGIS-backed `steps[].street_name` is always null.
6. **data-model.md (additive):** `wp.community_report.terminal_at timestamptz`. The 30-day hard delete currently approximates with `COALESCE(moderated_at, expires_at)`; a reporter's deletion time is not recorded.
7. **data-model.md (clarify):** `wp.closure.status` vocabulary. Closures are filtered by validity window only; cancelled or finished statuses may need excluding.
8. **Source ids:** I used `osm`, `mtl-voirie-trottoir`, `mtl-311`, `mtl-entraves`, `mtl-planif-neige`, `eccc-geomet`. Only `mtl-311` appears in the contract; the Data agent's `wp.source` ids should be canonical.
9. **Semantics to confirm:** the evidence states chosen for explanation codes (see Design notes), and always returning two routes when they are identical.

## Review readiness
Ready for code review of `services/routing` and `services/api`. It is **not** ready to claim real-graph correctness or latency, or to claim the PostGIS paths work, until the blockers above clear. Suggested coordinator re-run:
```bash
cd ../winterpath-routing
uv run --project services/api pytest services/routing services/api -rs
(cd services/routing && uv run ruff check . && uv run ruff format --check .)
(cd services/api && uv run ruff check . && uv run ruff format --check .)
```
