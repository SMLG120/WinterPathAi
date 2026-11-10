# Agent report — routing

- **Status:** READY FOR REVIEW
- **Branch / SHA:** `agent/routing` @ `3460fa1` (code; includes the merges of `integration/winterpath` at contract v1.1.0 → `aff27a6` and data-model v1.2.0 + pilot_mini → `9fb5fa5`). This report is committed on top.
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
  tests/  test_api_{contract,adapters,pilot_mini,postgis}.py, api_testlib.py
docs/agent-reports/routing.md
```

## Commands run and literal results
Environment: Apple M4 (10 cores, 16 GB), macOS (Darwin 25.6.0), Python 3.12.13, uv 0.10.7. FastAPI 0.162.4, Starlette 1.10.0, Pydantic 2.14.3. PostGIS in the shared Docker container (:55432), DB `wp_routing`. **Shared machine: `uptime` load averages 32.41 / 37.81 / 39.25 during the final runs** (other agent sessions), so latency figures are noisy upper bounds.

### 1. Full routing + API suites, PostGIS enabled (`DATABASE_URL` → `wp_routing`)
`wp_routing` schema created by applying the Data agent's migration to my own DB (`alembic -c db/alembic.ini upgrade head` → `0001_wp_schema_v1 (head)`). The PostGIS tests load the real pilot_mini into `wp.node`/`wp.edge`, exercise every DB-backed path, and delete exactly the rows they created.
```text
$ uv run --project services/api pytest services/routing services/api -rs -p no:cacheprovider   # DATABASE_URL=…/wp_routing
============================= test session starts ==============================
platform darwin -- Python 3.12.13, pytest-9.2.0, pluggy-1.7.0
rootdir: /Users/smlgmac/Projects/Geography/winterpath-routing/services/routing
configfile: pyproject.toml
plugins: anyio-4.16.0
collected 257 items
services/routing/tests/test_routing_engine.py .......................... [ 10%]
......                                                                   [ 12%]
services/routing/tests/test_routing_latency.py 
[latency] SYNTHETIC grid 25x25 over PILOT_BBOX: nodes=625 directed_edges=2400 n=100 compare() p50=9.1 ms p95=45.2 ms max=251.2 ms
.
[latency] SYNTHETIC grid 60x60 over PILOT_BBOX: nodes=3600 directed_edges=14160 n=100 compare() p50=72.2 ms p95=294.5 ms max=467.6 ms
.                        [ 13%]
services/routing/tests/test_routing_pilot_mini.py .....
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=1.5 ms p95=3.8 ms max=6.1 ms (rejected >75 m from network: 48)
.                 [ 15%]
services/routing/tests/test_routing_providers.py ....................... [ 24%]
........................................................................ [ 52%]
................................................                         [ 71%]
services/routing/tests/test_routing_search.py ......................     [ 79%]
services/routing/tests/test_api_adapters.py ......
[latency] API POST /routes/compare SYNTHETIC toy grid (38 edges), n=100: p50=7.9 ms p95=35.1 ms max=71.7 ms
.                      [ 82%]
services/routing/tests/test_api_contract.py ............................ [ 93%]
.....                                                                    [ 95%]
services/routing/tests/test_api_pilot_mini.py ........
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=7.5 ms p95=20.4 ms max=65.3 ms
.                  [ 98%]
services/routing/tests/test_api_postgis.py ...                           [100%]
=============================== warnings summary ===============================
services/api/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
======================= 257 passed, 1 warning in 28.62s ========================
$ row counts in wp_routing after run
{'edge': 0, 'node': 0, 'community_report': 0, 'pilot_request': 0}
```
Notes:
- 0 skipped.
- The API test files print as `services/routing/tests/…` because pytest chooses `services/routing` as rootdir when given both directories; they live in `services/api/tests/`.
- The one warning is Starlette's deprecation of `httpx` in TestClient.

### 2. Lint and ownership gate
```text
$ (cd services/routing && uv run ruff check . && uv run ruff format --check .)
All checks passed!
20 files already formatted
$ (cd services/api && uv run ruff check . && uv run ruff format --check .)
All checks passed!
27 files already formatted
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
| engine `compare()` (both variants), random points in fixture bbox | 100 routed (48 more rejected as > 75 m from network) | 1.5 ms | 3.8 ms | 6.1 ms |
| same, earlier run under heavier load | 100 | 4.2 ms | 139.1 ms | 649.7 ms |
| API via TestClient, random node-pair ODs | 100 | 7.5 ms | 20.4 ms | 65.3 ms |
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
| `/routes/compare` schema-valid vs openapi.yaml; 422 outside coverage; 400/422 on bad input | Yes | `test_api_contract.py`, `test_api_pilot_mini.py` (3 profiles × 2 locales on real graph); Platform harness 54 passed |
| No fabricated weather/risk; unknown flows through | Yes | weather → 503; `unknown_share == 1.0`, `RISK_LAYER_UNAVAILABLE`; segments risk `unknown`; malformed or failing provider → unknown |
| `PostgisGraphProvider` against data-model | Yes | `test_postgis_graph_provider_integration`: real pilot_mini loaded into `wp_routing`, read back identical to `FixtureGraphProvider` (ids, lengths, kinds, access, step_free) |
| `/reports` + moderation + deletion, in-memory + PostGIS | Yes | in-memory lifecycle/expiry/purge tests; `test_api_postgis.py` runs the full lifecycle, hazards, sources and pilot requests on PostGIS |
| Latency p50/p95, 100 pilot OD pairs | Yes (pilot_mini) | table above; full pilot graph pending |
| `pytest services/routing services/api` green; ruff clean | Yes | 257 passed, 0 skipped; ruff output above |

## Fixes made after integration (this cycle)
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
| Migration `0001` lacks v1.2 columns (`wp.edge.crossing_type/crossing_kerb/highway/osm_snapshot`, `wp.closure.attrs/backsidewalk_blocks_passage`, `wp.weather_daily`) | From PostGIS, crossing type/kerb come only from node tags until the v1.2 migration lands (handled; selected automatically once present) | Data agent: migration 0002 |
| ML `RiskProvider` not landed | Only the `none` layer is exercised end-to-end | ML; then set `RISK_PROVIDER=winterpath_ml.inference:<factory>` |
| No concrete ECCC weather adapter | `/weather/*` → 503 (correct, no invented values). `wp.weather_obs`/`weather_daily` exist in `wp_data` | Follow-up (routing): adapter reading `wp.weather_obs`/`weather_daily` |
| Report `purge()` not scheduled | Expiry is enforced on read; 30-day hard delete only when `purge()` is called | Platform/coordinator (scheduled jobs need approval) |

## Dependencies on other agents
- **Data:** fixture layout as delivered (`edges/nodes.geojson`, `metadata.json` with explicit `simulated`, `manifest.json`). `wp.source` ids are canonical.
- **ML:** `edge_risk(edge_ids, at)`, plus optional `risk_layer` attribute and `model_status()` dict.
- **Platform:** harness passes against this API.
- **Frontend:** both routes are always returned; `explanation[].evidence_state` drives badges; `warnings` are localized.

## Licensing / data notes
- No external data was downloaded or committed by this agent.
- Real data used: the Data agent's `data/fixtures/pilot_mini` (OSM, ODbL; see its `ATTRIBUTION.md`).
- Synthetic data: `services/routing/tests/fixtures/synthetic/toy_grid` (`simulated: true`), used only in tests.
- `/data-sources` licence and attribution text is transcribed from `docs/data-sources-and-licenses.md`. Licence URLs for CC BY 4.0, ODbL 1.0 and the ECCC licence page come from my own knowledge, not re-fetched — please verify.
- Integration tests write to `wp_routing` (my own DB) only and clean up after themselves.

## Change requests (contracts) — still open
1. `.env.example`: add `ROUTING_GRAPH_SOURCE`, `ROUTING_FIXTURE_DIR`, `API_STORE_BACKEND`, `RISK_PROVIDER`, `ROUTING_WORKERS`. `API_ADMIN_TOKEN_HASH` = SHA-256 hex of the token (optional `sha256:` prefix).
2. openapi.yaml (additive): declare `503 Unavailable` on `/routes/compare`, `/map/segments`, `/hazards`, `/data-sources`. These return `503 UPSTREAM_UNAVAILABLE` when the graph or a store is down.
3. openapi.yaml (clarify): a point > 75 m from the routable network returns `422 OUTSIDE_COVERAGE` with `details.which`/`max_snap_distance_m`. Consider a distinct code (e.g. `OFF_NETWORK`).
4. data-model (additive): `wp.edge.name text null`. pilot_mini also has no `name`, so `steps[].street_name` is always null on real data and instructions carry no street names.
5. data-model (additive): `wp.community_report.terminal_at timestamptz`. Hard delete currently approximates with `COALESCE(moderated_at, expires_at)`.
6. data-model (clarify): `wp.closure.status` vocabulary (closures are currently filtered by validity window only).
7. Confirm the evidence states chosen for explanation codes, and that both routes are returned when they are identical.
8. **Platform (FYI, not a contract change):** `tests/integration/log_scan.py` flags fractional seconds of microsecond ISO timestamps (e.g. `…:40.010135Z`) as latitudes. I avoided this by logging milliseconds, but other services may trip it.

(Withdrawn: the source-id CR is resolved by the Data agent's canonical ids. The `DELETE /reports` 404/422 question is resolved by v1.1.0.)

## Review readiness
READY FOR REVIEW. The worktree is clean after this commit. Coordinator re-run:
```bash
cd ../winterpath-routing
set -a; source .env.local; set +a          # DATABASE_URL → wp_routing (schema: alembic -c db/alembic.ini upgrade head)
uv run --project services/api pytest services/routing services/api -rs
(cd services/routing && uv run ruff check . && uv run ruff format --check .)
(cd services/api && uv run ruff check . && uv run ruff format --check .)
scripts/check-ownership.sh routing
```
