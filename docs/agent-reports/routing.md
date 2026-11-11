# Agent report — routing

- **Status:** READY FOR REVIEW. Cycle 14: `/routes/compare` under 0.1 CPU p95 4692→602 ms (memory store), byte-identical results, golden regression test; 324 passed. Cycle 13: v1.7 risk wiring (shared engine + `RISK_SCORE_SOURCE` passed to ML's provider; data `360fdd4` + ml `79a0ee6` merged; `wp_routing` at 0007), 323 passed. Cycle 12: contract v1.7.0 (read-only `API_PUBLIC_WRITES`, Supabase session-pooler engine, clean SIGTERM), 317 passed. Cycle 9: **`agent/data` `f6eb3b2` merged by coordinator instruction** (v1.6 migration 0006 with alley categories, CR-DATA-7, Geofabrik pilot_mini); `wp_routing` was downgraded to 0005 and re-upgraded to head; **303 passed, 0 skipped**; re-merge of `integration/winterpath` (`a292b63`, no change) re-run: 303 passed. Earlier: cycle 8 contract v1.6.0, cycle 7 API-NULL-1, cycle 6 v1.5.0, cycle 5 v1.4.0 closure activity, cycle 4 v1.3.0 + ML risk.
- **Branch / SHA:** `agent/routing` @ `f776a3a` = merge of `agent/data` `f6eb3b2` (by coordinator instruction) onto `b62a2e8`. Code is unchanged since `31651e5` (contract v1.6.0). This report is committed on top.
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
### 0o. Cycle 14 — `/routes/compare` performance under a 0.1 CPU cap, identical results — current
**Method:**
- **Image:** Platform's `infra/docker/api.Dockerfile` from `8623a30` (the trial's), built from `git archive HEAD` for *before* and from the working tree for *after*.
- **Container:** `docker run --cpus=0.1 --memory=512m`, `ROUTING_GRAPH_SOURCE=postgis` on `wp_data` read only (`default_transaction_read_only=on`; graph 6,807 nodes / 16,296 edges inside the pilot bbox), `RISK_PROVIDER=none`, `ROUTING_WORKERS=1`, `API_PUBLIC_WRITES=false`.
- **Load:** sequential `POST /routes/compare` with seeded random `{lon,lat}` pairs across the pilot bbox and mixed profiles; 10 warm-up requests not counted, then n=100 (same seed before/after). RSS from `docker stats`.
- The host was shared with other agents (load average 8–15), so the *before* numbers vary between runs; both runs are shown.

| Config | | p50 | p95 | max | statuses | RSS after boot / after load |
|---|---|---|---|---|---|---|
| `API_STORE_BACKEND=memory` (deployment config) | before | 804 ms | 4692 ms | 11891 ms | 200×67, 404×2, 422×31 | 134.9 / 138.8 MiB |
| | **after** | **198 ms** | **602 ms** | 2302 ms | identical | 141.2 / 144.3 MiB |
| `API_STORE_BACKEND=postgis` (hazards from DB per request) | before | 796 ms | 2590 ms | 6399 ms | 200×67, 404×2, 422×31 | 176.9 / 184.6 MiB |
| | **after** | **292 ms** | **704 ms** | 2803 ms | identical | 141.8 / 149.2 MiB |

Warm p95 is under the 2 s target in both configurations. Boot under the cap was 42–76 s before and 51 s after (noisy; graph load + precompute).

**Profile** (cProfile, in-process, 100 ODs on the `wp_data` snapshot):
- **Before:** 67 % of time in the two searches. Of that, 4.3 s was the neighbour generator: a NetworkX `out_edges` view per settled node plus a `_weight` → `_cost` call per arc. A further 25 % was `_context`, which ran the exclusion filter over all 16k edges and built a 16k-entry risk dict per request. Pydantic and response building were minor.

**Changes** (`engine.py`, `graph.py`; same algorithms, same results):
1. **Precomputed per engine:**
   - adjacency, built from `g.out_edges(n, keys=True)` itself, so arc order and tie-breaking are unchanged;
   - edge lengths;
   - per profile, the statically allowed edge set (foot access, step-free rule, main component) and every edge's default `EdgeCost` (risk unknown, no hazard) with its `total_s`.
2. **Per request, only the dynamic part:** active closures are subtracted from the static set. Edges with a hazard or a *known* risk estimate get `edge_cost(...)` on a copy of the static weights (lazily if there are more than 2048). Unknown and missing estimates cost and report identically, so only known ones are kept. `NullRiskProvider` is not called: its answer is "unknown" for every edge.
3. **Specialised search loop `_run`:** it mirrors `search.astar` exactly: same relaxation order (start arcs; per node, out-arcs then end arcs), same `(priority, counter)` heap keys, same float expressions (`nd + h(v)`, heuristic `hypot(...) * per_m`). Dijkstra stays Dijkstra for the shortest route. A* with the existing admissible heuristic stays for winter-aware. **No bidirectional search or A* on the shortest route:** that could pick a different path among equal-cost ones, which would break "identical results". `search.astar`/`dijkstra` remain for tests.
4. **Snapping:** `nearest_edges` no longer copies the 16k-edge allowed set per call.

Engine-only on the `wp_data` snapshot, uncapped: before p50 42.5 ms / p95 128 ms; after p50 14.4–16.7 ms / p95 47–55 ms.

**Results are identical:**
- `wp_data`, 100 seeded ODs (66 routed, 34 errors), full engine output (`to_dict()`: geometry, steps, explanations, warnings, errors with details): `cmp golden_before.json golden_after.json` → **byte-identical**.
- Golden-test cases (96), full `to_dict()` output: **byte-identical**.
- HTTP bodies from the two images (status + body minus `request_id`/`computed_at`): **100/100 identical** for both store configs.
- **New regression test `tests/test_routing_golden.py`**:
  - Golden `fixtures/golden/compare_golden.json` generated from the **unmodified** engine before any change: 96 cases on real `pilot_mini` + a synthetic grid with mixed attributes, plus hard closure, possible closure, disruption and report hazards; no risk / static TEST risk; 3 profiles; EN/FR; 72 routed, 24 errors.
  - Compared exactly: error codes, both routes' edge sequences, `identical`, warnings, explanation codes, hazards on/avoided, step count. Distances and costs within 0.05.
  - Mutation checks: ignoring closures → fails (`synthetic/0/standard/none`, `edge_ids`); not applying hazard/risk costs → fails (`pilot_mini/15/standard/static`).
  - Honest limit: reversing arc order did **not** change any golden case, so these OD sets contain no exact cost ties. Identical tie-breaking comes from building the adjacency from NetworkX's own iteration order, not from this test.

```text
$ uv run --project services/api pytest services/routing services/api -rs
[latency] SYNTHETIC grid 60x60 over PILOT_BBOX: nodes=3600 directed_edges=14160 n=100 compare() p50=11.8 ms p95=32.1 ms max=304.7 ms   (was p50≈45 ms p95≈113 ms)
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=1.0 ms p95=1.8 ms max=2.2 ms (rejected >75 m from network: 4)
======================= 324 passed, 1 warning in 16.78s ========================
$ ruff (routing / api): All checks passed! 21 / 33 files already formatted
```

**Found while measuring (for the coordinator, not changed here):** with the deployment setting `API_STORE_BACKEND=memory` (`docs/ENVIRONMENT_VARIABLES.md`), `build_state` uses `InMemoryHazardRepository`. Closures (`wp.closure`) and 311 aggregates (`wp.report_311_cell`) are therefore **not** loaded in production, even though the DB has them. Routes would neither exclude active confirmed closures nor show 311 reports. Proposal: read hazards from PostGIS whenever a DB engine exists, and keep only *storing* community reports in memory. That is a behaviour change, so I'm awaiting your decision.

### 0n. Cycle 13b — combined-trial blocker: real-layer ML tests gated on per-day score tables
**Cause (coordinator's combined trial):** `test_real_heuristic_layer_in_season` and `test_real_heuristic_estimates_have_no_probability` failed with "expected scored cells on 2026-01-14". Their skip checked only `reg['coverage']['path']`. ML commits `coverage_cells.parquet` in v1.7, but the per-day score tables (`models/artifacts/v2-8d19aa86/scores/…`) are still git-ignored. CI and fresh checkouts therefore ran these tests with no scores, so every edge was `unknown`.

**Fix (`tests/test_api_ml_risk.py`):**
- New `needs_scores` marker. It resolves the directory with ML's own `scores_dir(reg, active_layer)` (which honours `MODEL_ARTIFACT_DIR`), reads the `*.parquet` tables there, and skips unless they contain non-null `p` rows for `IN_SEASON_DAY = "2026-01-14"`, the day both tests route on.
- The reason text names the missing path, says it is git-ignored, and says how to obtain it (copy `models/artifacts/v2-8d19aa86/scores/` from agent/ml or run the score job).
- The coverage check now also uses ML's `artifact_path` rather than a repo-relative path.
- `test_real_layer_out_of_season_is_unknown` (2026-07-01) needs no scores, so it keeps the coverage-only marker.
- `test_real_heuristic_estimates_have_no_probability` now pins `score_source="file"`, so an ambient `RISK_SCORE_SOURCE=postgis` cannot change what it tests.

**Verified both ways:**
```text
=== WITH scores dir
test_real_heuristic_layer_in_season PASSED / test_real_heuristic_estimates_have_no_probability PASSED / test_real_layer_out_of_season_is_unknown PASSED
========================= 7 passed, 1 warning in 1.89s =========================
=== WITHOUT scores dir (moved to scratchpad)
SKIPPED [1] services/api/tests/test_api_ml_risk.py:202: ML per-day score tables absent (…/models/artifacts/v2-8d19aa86/scores/winter311-heuristic-v1/*.parquet is git-ignored; copy models/artifacts/v2-8d19aa86/scores/ from agent/ml or run the ML score job)
SKIPPED [1] services/api/tests/test_api_ml_risk.py:219: (same reason)
=================== 5 passed, 2 skipped, 1 warning in 1.52s ====================
=== fresh-checkout equivalent: ONLY git-tracked artifacts present (features.parquet, metrics.json, winter311-hgb-v1.joblib, scores/ moved aside), full suite
================== 321 passed, 2 skipped, 1 warning in 24.32s ==================
=== all local artifacts restored, full suite
======================= 323 passed, 1 warning in 28.47s ========================
$ ruff (routing / api): All checks passed! 20 / 33 files already formatted
$ (cd services/api && uv lock --check)  → exit=0
$ scripts/check-ownership.sh routing    → 19 flagged files, 19/19 byte-identical to 79a0ee6 (unchanged from 0m)
```

### 0m. Cycle 13 — v1.7 risk wiring: merge data `360fdd4` + ml `79a0ee6`; shared engine → ML provider
**Merges (exact commits, as instructed):**
- `git merge --no-edit 360fdd4` → `40a61a4`.
- `git merge --no-edit 79a0ee6` → `737d3e5`. This merge first refused because two untracked files would be overwritten: `models/artifacts/v2-8d19aa86/{coverage_cells.parquet,winter311-heuristic-v1.joblib}`, my local copies of ML's artifacts, which ML now commits. Their `git hash-object` matched `79a0ee6`'s blobs (`cae69c1…`, `360242b…`), so I moved them to the scratchpad and the merge then succeeded.
- Afterwards `db/`, `services/ml`, `services/ingestion` and `models/` are identical to the named commits.
- `wp_routing`: `alembic upgrade head` → `0007_risk_cell_score (head)`.
- `services/api/uv.lock`: ML's `79a0ee6` added `sqlalchemy>=2.0` to `services/ml`'s `db` extra. The API lock now records it (metadata only, one line, no resolved version change), and `uv lock --check` exits 0.

**Fix (`state.py` / `adapters.py`):**
- `load_risk_provider(spec, edge_coords, *, engine=None, score_source=None)` inspects the factory's signature. It passes `engine=` and `score_source=` only if they are accepted (keyword or `**kwargs`). Older factories that take no arguments are still called with none.
- `build_state` passes the shared pooled engine and `settings.risk_score_source`. That setting comes from `RISK_SCORE_SOURCE` (`file` | `postgis`; default `file`; any other value fails at startup).
- The shared engine is created whenever **any** component needs PostGIS: stores, weather, or ML scores from postgis. The production combination is in-memory stores + weather + risk from postgis, so the engine can no longer be missing there. The stores use PostGIS only when `API_STORE_BACKEND=postgis`.
- `/health`: the `database` check now pings the engine itself. Before, with in-memory stores it called the in-memory repository's `ping()` and always said `ok`. The `risk` detail now names the score source.

**Tests (`tests/test_api_risk_postgis.py`, 6):**
- Factory wiring for v1.7, legacy, `**kwargs` and engine-only signatures.
- The real `load_provider` signature.
- `postgis` without a DB stays all-unknown (`disabled`).
- Setting parsing.
- A **real-DB test at 0007**. All 200 `pilot_mini` edges lie in **one** H3 r9 cell (`892baa441b3ffff`), so row and no-row can't be mixed inside one route on this fixture. The test exercises both on the same edges instead:
  - (a) A fixture row (p=0.5) for today's America/Montreal day. `/map/segments`: every edge has a non-unknown level, `probability` null and evidence `model_estimate`. `compare`: `risk_layer=heuristic`, `unknown_share=0.0`.
  - (b) The next local day, which has no rows, through the same client: `unknown_share=1.0`.
  - (c) After deleting the row, a fresh client for today: every segment is `unknown` and `unknown_share=1.0`.
  - The test skips rather than overwrite pre-existing rows, and checks that 0 rows remain afterwards.
- **Mutation check:** with `engine=None` put back in `build_state`, the DB test fails (`{'status': 'disabled'} != {'status': 'ok'}`), i.e. it reproduces the reported gap.

**(4) `/health` with `RISK_SCORE_SOURCE=postgis`** (uvicorn, `wp_routing` at 0007, in-memory stores, `pilot_mini` graph, writes disabled):
```text
{"status": "ok", "version": "0.1.0 (contract 1.7.0)",
 "checks": {"graph": {"status": "ok"}, "database": {"status": "ok"},
            "risk": {"status": "ok", "detail": "risk_layer=heuristic; score_source=postgis"},
            "weather": {"status": "disabled", "detail": "No ECCC adapter configured."}}}
/models/status: heuristic False winter311-hgb-v1
wp.risk_cell_score rows in wp_routing: 0
compare: risk_layer heuristic unknown_share [1.0, 1.0]
SIGTERM exit=143
```
**Operational gap:** `/health` says risk `ok` even when `wp.risk_cell_score` has **no rows for today** (scoring job not run or failed); every route is then 100 % unknown. That is honest per edge, but invisible in `/health`. Proposal (needs coordinator/ML agreement, since health semantics are contract-adjacent): report `risk: degraded` when the active layer's `model_id` has no rows for today's local day. That needs ML's `status()` to expose the *active* layer's id; it currently reports `winter311-hgb-v1`, the gated-off model, while the heuristic is active (FYI already sent).

```text
$ uv run --project services/api pytest services/routing services/api -rs
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=1.3 ms p95=2.3 ms max=2.7 ms (rejected >75 m from network: 4)
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=4.1 ms p95=5.4 ms max=10.0 ms
======================= 323 passed, 1 warning in 18.03s ========================
$ ruff (routing / api): All checks passed! 20 / 33 files already formatted
$ (cd services/api && uv lock --check)  → exit=0
$ scripts/check-ownership.sh routing    → exit=1: 19 files, all from the two named commits
```
The ownership check fails as expected. It compares against integration, which doesn't yet contain `360fdd4`/`79a0ee6`. All 19 flagged files (`db/…/0007_risk_cell_score.py`, `services/ml/*`, `services/ingestion/*`, `models/artifacts/v2-8d19aa86/{coverage_cells.parquet,winter311-heuristic-v1.joblib}`, `docs/agent-reports/{data,ml}.md`) are byte-identical to `79a0ee6` (`git diff --quiet 79a0ee6 HEAD -- <file>` for each: 19/19 same). No routing commit touches them.

### 0l. Cycle 12b — merge of `integration/winterpath` `137e623` (deployment docs)
The merge commit is `1027e50`: docs only (`docs/{DATA_COMPLIANCE,ENVIRONMENT_VARIABLES,FREE_TIER_LIMITS,RECOVERY,SECURITY}.md`), no code or migrations. The API matches `docs/ENVIRONMENT_VARIABLES.md`:
- `DATABASE_POOL_SIZE`/`DATABASE_MAX_OVERFLOW` default to 3 / 2.
- `API_PUBLIC_WRITES=false` → 503 `WRITES_DISABLED`.
- `API_LOG_LEVEL=info` is accepted case-insensitively (root level `INFO`).
- The production combination `API_STORE_BACKEND=memory` + `WEATHER_SOURCE=postgis` uses the single shared pooled engine.
```text
$ uv run --project services/api pytest services/routing services/api -rs
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=1.8 ms p95=5.8 ms max=9.2 ms (rejected >75 m from network: 4)
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=6.7 ms p95=19.4 ms max=86.8 ms
======================= 317 passed, 1 warning in 25.11s ========================
$ ruff (routing / api): All checks passed! 20 / 32 files already formatted
$ (cd services/api && uv lock --check)  → exit=0
$ scripts/check-ownership.sh routing    → ownership OK for agent/routing
```

### 0k. Cycle 12 — contract v1.7.0 (free-tier deployment): merge `07a1f29`, read-only mode, pooler settings, boot/SIGTERM
The coordinator's message reached me truncated: it starts mid-sentence at "…X_OVERFLOW (default 2)", so items (1)–(2) were missing. I implemented the API's share of contract v1.7.0 as written in `07a1f29` (`API_PUBLIC_WRITES`, pooler-friendly engine), plus items (3)–(5). **If (1)–(2) asked for anything else, please resend them.**

**Merge:** `integration/winterpath` `07a1f29` → `ef665fc`, no conflicts (contracts and `.env.example` only).

**Changes:**
- `CONTRACT_VERSION = "1.7.0"`; error code `WRITES_DISABLED` added.
- **`API_PUBLIC_WRITES`** (default true; accepts `1/true/yes/on` and `0/false/no/off`; any other value fails at startup, so a typo can't silently open writes). When false, `POST /reports` and `POST /pilot-requests` return **503 `WRITES_DISABLED`**. The check is a route dependency, so it answers before body validation, rate limiting or any store access, and nothing about the request is stored. Reads, routing and `DELETE /reports/{id}` are unchanged.
- **Pool (`winterpath_api/db.py`):**
  - Settings:
    - `DATABASE_POOL_SIZE`: default 3 (my choice, since the message didn't give one).
    - `DATABASE_MAX_OVERFLOW`: default 2.
    - `pool_pre_ping=True` and `pool_recycle=300`.
    - `pool_timeout=10` s, so an exhausted pool fails fast and the endpoint returns 503.
    - `connect_timeout=10` s and `application_name=winterpath-api`.
  - One engine per process, shared by every repository and the weather store. Previously, weather got a second engine when the stores were in memory.
  - Session pooler (port 5432) keeps psycopg's prepared statements working, so no `prepare_threshold` change. `sslmode=require` belongs in `DATABASE_URL`, which is never logged.
- **Graph load (`PostgisGraphProvider`):** one connection via `NullPool`, `connect_timeout`, and `engine.dispose()` in `finally` (also on failure). The startup load therefore never holds a pooler slot.
- **Shutdown:** a FastAPI lifespan hook runs after uvicorn drains requests on SIGTERM/SIGINT. It shuts the route worker pool and disposes the DB engine, then logs `shutdown_complete`.
- **Tests:** `tests/test_api_deploy_v17.py` has 14 tests covering settings parsing and invalid values, engine/pool options, graph load (`NullPool` + dispose on failure), 503 on both write endpoints validated against the contract (valid and invalid bodies, repository spies prove no write), the gate answering before the limiter, reads unaffected, writes on by default, and lifespan shutdown releasing the pool and engine.

**(4) Startup, measured against `wp_data`.** Settings: `ROUTING_GRAPH_SOURCE=postgis`, `API_STORE_BACKEND=postgis`, `API_PUBLIC_WRITES=false`, pool 3+2. The URL carries `options=-c default_transaction_read_only=on`, so the session could not write to Data's DB (`show default_transaction_read_only` → `on`). uvicorn started exactly as the image's CMD (`--no-access-log`), on loopback port 8102. A scratch `sitecustomize` recorded every non-loopback socket connect.
```text
wp_data: alembic 0006_report_311_nature; wp.node 7042, wp.edge 16846 (16694 in pilot bbox); wp.risk_cell_score absent (0007 not applied)
label=none risk=none boot_to_health_200_s=4.8 rss_after_boot_mb=125
health: ok {'graph': 'ok', 'database': 'ok', 'risk': 'disabled', 'weather': 'disabled'}
graph: 6807 nodes 16296 edges
compare 200 0.262568s / 0.066025s / 0.063107s / 0.064201s / 0.076824s
rss_after_5_routes_mb=147
POST /reports with writes disabled: 503
SIGTERM -> exit=143 in 0.17s
graph_loaded log lines: 1
probe: no non-loopback connections

label=ml risk=winterpath_ml.inference:load_provider boot_to_health_200_s=9.37 rss_after_boot_mb=162
health: ok {'graph': 'ok', 'database': 'ok', 'risk': 'ok', 'weather': 'disabled'}
compare 200 1.090192s / 0.106014s / 0.103326s / 0.097676s / 0.099556s
rss_after_5_routes_mb=149
SIGTERM -> exit=143 in 0.25s
graph_loaded log lines: 1
probe: no non-loopback connections

in-process (sys.setprofile over create_app, ML provider):
PostgisGraphProvider.load calls during startup: 1
fit/train/calibrate/download calls during startup: none
```
- These figures sit within the coordinator's ~12 s / 125–215 MB. Boot is 4.8 s without a risk layer and 9.4 s with the file-based ML provider; RSS is 125–162 MB. The host load average was ~11–15 throughout.
- With the ML layer, the first route of each Montréal local day pays about 1 s, because the adapter scores the day's edges and caches them per (edge, local day).
- **(5) SIGTERM:** the uvicorn log shows `Shutting down` → `Waiting for application shutdown.` → `shutdown_complete` → `Application shutdown complete.` → `Finished server process`, in 0.17–0.25 s. Exit status 143 (128+15) is expected: uvicorn 0.54 re-raises the captured signal after a graceful shutdown (`server.py`: `signal.raise_signal(captured_signal)`).

```text
$ uv run --project services/api pytest services/routing services/api -rs
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=1.7 ms p95=2.9 ms max=4.6 ms (rejected >75 m from network: 4)
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=5.6 ms p95=8.3 ms max=65.1 ms
======================= 317 passed, 1 warning in 24.13s ========================
$ ruff (routing / api): All checks passed! 20 / 32 files already formatted (after `ruff format` of the new test file)
$ (cd services/api && uv lock --check); echo exit=$?    → exit=0
$ scripts/check-ownership.sh routing                    → ownership OK for agent/routing
```

**For other agents:**
- **Platform:**
  - `infra/docker/api.Dockerfile` hard-codes `--port 8000`. v1.7 says the image binds `0.0.0.0:$PORT`, so it should be `--port "${PORT:-8000}"`.
  - With `uvicorn --workers N`, each worker loads the graph and holds its own pool. Keep the default single worker on Render Free, or size the pool as N×(pool+overflow) against the pooler limit.
- **ML:** `RISK_SCORE_SOURCE=postgis` / the DB-backed provider isn't on integration yet; the API loads whatever `RISK_PROVIDER` names. If that provider opens its own engine, please keep it to a tiny pool (or accept an engine from the API) so the total stays inside the session-pooler budget.

### 0j. Cycle 11 — merge of `integration/winterpath` `3aa6438`
This was a fast-forward from `0823006`, because integration already contained it. It changes nothing under `db/` or `services/`; the incoming changes are the frontend explainer, Platform's CI changes and other agents' reports. `wp_routing` stays at `0006_report_311_nature (head)`.
```text
$ git merge --no-edit integration/winterpath      # HEAD → 3aa6438
$ (cd services/api && uv lock --check); echo exit=$?
exit=0
$ uv run --project services/api pytest services/routing services/api -rs     # load average ≈15
[latency] SYNTHETIC grid 25x25 over PILOT_BBOX: nodes=625 directed_edges=2400 n=100 compare() p50=7.9 ms p95=20.6 ms max=87.9 ms
[latency] SYNTHETIC grid 60x60 over PILOT_BBOX: nodes=3600 directed_edges=14160 n=100 compare() p50=47.4 ms p95=110.7 ms max=171.4 ms
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=1.5 ms p95=2.8 ms max=3.8 ms (rejected >75 m from network: 4)
[latency] API POST /routes/compare SYNTHETIC toy grid (38 edges), n=100: p50=4.9 ms p95=6.3 ms max=10.9 ms
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=6.1 ms p95=12.0 ms max=55.2 ms
======================= 303 passed, 1 warning in 22.55s ========================
$ ruff (routing / api): All checks passed! 20 / 30 files already formatted
$ scripts/check-ownership.sh routing; echo exit=$?
ownership OK for agent/routing
exit=0
```

### 0i. Cycle 10 — merge of `integration/winterpath` `6a712e9` (all five agents) + `services/api/uv.lock` refresh
The merge commit is `83ee512` (no conflicts; 25 incoming commits). It changes nothing under `services/routing`, `services/api` or `db/`, and `db/` is identical to `f6eb3b2`, so `wp_routing` stays at `0006_report_311_nature (head)` with no re-migration. ML added a `db` extra to `services/ml`, which made `services/api/uv.lock` stale. `uv lock` adds only that metadata (`psycopg[binary]>=3.2` under `extra == 'db'`, `provides-extras = ["db"]`); no resolved package versions change.
```text
$ git merge --no-edit integration/winterpath      # 6a712e9
$ (cd services/api && uv lock --check)            # before
The lockfile at `uv.lock` needs to be updated, but `--check` was provided. To update the lockfile, run `uv lock`.
$ (cd services/api && uv lock)
Resolved 61 packages in 69ms
$ (cd services/api && uv lock --check); echo exit=$?
exit=0
$ uv run --project services/api pytest services/routing services/api -rs     # load average ≈18
[latency] SYNTHETIC grid 25x25 over PILOT_BBOX: nodes=625 directed_edges=2400 n=100 compare() p50=9.2 ms p95=32.9 ms max=179.6 ms
[latency] SYNTHETIC grid 60x60 over PILOT_BBOX: nodes=3600 directed_edges=14160 n=100 compare() p50=99.4 ms p95=407.9 ms max=573.5 ms
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=2.0 ms p95=5.5 ms max=13.0 ms (rejected >75 m from network: 4)
[latency] API POST /routes/compare SYNTHETIC toy grid (38 edges), n=100: p50=11.7 ms p95=61.2 ms max=101.1 ms
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=13.6 ms p95=62.3 ms max=101.6 ms
======================= 303 passed, 1 warning in 51.62s ========================
$ ruff (routing / api): All checks passed! 20 / 30 files already formatted
$ scripts/check-ownership.sh routing; echo exit=$?
ownership OK for agent/routing
exit=0
```
The ownership gate passes again now that integration contains `f6eb3b2`. The latency figures were measured with the host under load and are not a code regression.

### 0h. Cycle 9b — re-merge of `integration/winterpath` (no change) + full rerun
`integration/winterpath` is still `a292b63` (already merged at `5af6145`), so the merge was a no-op. `wp_routing` unchanged at head.
```text
$ git merge --no-edit integration/winterpath
Already up to date.
$ alembic -c db/alembic.ini current
0006_report_311_nature (head)
$ uv run --project services/api pytest services/routing services/api -rs
[latency] SYNTHETIC grid 25x25 over PILOT_BBOX: nodes=625 directed_edges=2400 n=100 compare() p50=6.0 ms p95=12.4 ms max=61.8 ms
[latency] SYNTHETIC grid 60x60 over PILOT_BBOX: nodes=3600 directed_edges=14160 n=100 compare() p50=30.1 ms p95=75.5 ms max=135.8 ms
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=1.0 ms p95=1.8 ms max=2.9 ms (rejected >75 m from network: 4)
[latency] API POST /routes/compare SYNTHETIC toy grid (38 edges), n=100: p50=5.5 ms p95=20.2 ms max=38.3 ms
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=5.1 ms p95=7.1 ms max=10.8 ms
======================= 303 passed, 1 warning in 19.16s ========================
$ (cd services/routing && uv run ruff check . && uv run ruff format --check .)
All checks passed!
20 files already formatted
$ (cd services/api && uv run ruff check . && uv run ruff format --check .)
All checks passed!
30 files already formatted
```

Second re-merge request, same day: `integration/winterpath` still `a292b63`.
```text
$ git merge --no-edit integration/winterpath
Already up to date.
$ alembic -c db/alembic.ini current
0006_report_311_nature (head)
$ uv run --project services/api pytest services/routing services/api -rs
[latency] SYNTHETIC grid 25x25 over PILOT_BBOX: nodes=625 directed_edges=2400 n=100 compare() p50=11.0 ms p95=26.3 ms max=86.3 ms
[latency] SYNTHETIC grid 60x60 over PILOT_BBOX: nodes=3600 directed_edges=14160 n=100 compare() p50=76.0 ms p95=248.0 ms max=363.0 ms
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=2.3 ms p95=4.5 ms max=8.7 ms (rejected >75 m from network: 4)
[latency] API POST /routes/compare SYNTHETIC toy grid (38 edges), n=100: p50=6.1 ms p95=9.5 ms max=17.3 ms
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=34.7 ms p95=198.6 ms max=2313.1 ms
======================= 303 passed, 1 warning in 48.89s ========================
$ ruff (routing / api): All checks passed! 20 / 30 files already formatted
```
Latencies are 2–7× the previous run with no code change; the host was shared with other agents' jobs at the time, so this reads as machine load, not a regression (API p95 assertion < 2 s still held; one 2.3 s outlier).

Third re-merge request, same day: `integration/winterpath` still `a292b63` (`Already up to date.`); `wp_routing` at `0006_report_311_nature (head)`; load average ≈13.
```text
[latency] SYNTHETIC grid 25x25 over PILOT_BBOX: nodes=625 directed_edges=2400 n=100 compare() p50=10.7 ms p95=54.8 ms max=78.7 ms
[latency] SYNTHETIC grid 60x60 over PILOT_BBOX: nodes=3600 directed_edges=14160 n=100 compare() p50=56.7 ms p95=152.0 ms max=244.3 ms
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=1.7 ms p95=3.3 ms max=5.9 ms (rejected >75 m from network: 4)
[latency] API POST /routes/compare SYNTHETIC toy grid (38 edges), n=100: p50=7.2 ms p95=36.2 ms max=144.5 ms
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=5.9 ms p95=10.5 ms max=42.6 ms
======================= 303 passed, 1 warning in 32.60s ========================
$ ruff (routing / api): All checks passed! 20 / 30 files already formatted
```

Fourth re-merge request, same day: `integration/winterpath` still `a292b63` (`Already up to date.`); `wp_routing` at `0006_report_311_nature (head)`; load average ≈11.
```text
[latency] SYNTHETIC grid 25x25 over PILOT_BBOX: nodes=625 directed_edges=2400 n=100 compare() p50=6.5 ms p95=19.2 ms max=86.6 ms
[latency] SYNTHETIC grid 60x60 over PILOT_BBOX: nodes=3600 directed_edges=14160 n=100 compare() p50=40.2 ms p95=97.3 ms max=217.2 ms
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=2.0 ms p95=6.9 ms max=12.0 ms (rejected >75 m from network: 4)
[latency] API POST /routes/compare SYNTHETIC toy grid (38 edges), n=100: p50=3.7 ms p95=5.3 ms max=32.6 ms
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=8.0 ms p95=235.9 ms max=1197.2 ms
======================= 303 passed, 1 warning in 29.64s ========================
$ ruff (routing / api): All checks passed! 20 / 30 files already formatted
```

### 0g. Cycle 9 — merge of `agent/data` `f6eb3b2`, DB re-migrated, full rerun
**Order** (0006 was edited in place, so the applied version had to be undone with its own downgrade):
1. **Downgrade with the applied 0006.** My scratchpad export of `agent/data`'s `db/` (identical to `4254dd7`'s 0006: `diff` empty) against **my own** DB:
   ```text
   target db: /wp_routing port 55432
   $ alembic -c <scratch>/data-db/db/alembic.ini current    → 0006_report_311_nature (head)
   $ … downgrade 0005_closure_active_excl_end; … current     → 0005_closure_active_excl_end
   ```
2. **Merge the exact commit:** `git merge --no-edit f6eb3b2` → `f776a3a` (26 files, no conflicts). The worktree's 0006 equals `f6eb3b2`'s (`diff` empty).
3. **Upgrade with the merged files:**
   ```text
   $ uv run --project services/ingestion --with alembic alembic -c db/alembic.ini upgrade head; … current
   0006_report_311_nature (head)
   report_311_cell_category_check: CHECK ((category = ANY (ARRAY['sidewalk_slippery', 'roadway_slippery', 'snow_clearing', 'snow_dumping', 'snow_clearing_alley', 'snow_dumping_alley'])))
   report_311_cell_pkey:           PRIMARY KEY (h3, day, category, nature)
   ```

**Fixture now in tree:** pilot_mini has 92 nodes, 200 edges and bbox `[-73.578801, 45.503026, -73.576318, 45.505218]`, the same as `ee5f1fc`/`4254dd7`. The fixture-derived tests from cycle 7 handle it.

```text
$ uptime → load averages: 9.24 6.98 7.56
$ uv run --project services/api pytest services/routing services/api -rs -p no:cacheprovider -s   # filtered
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=0.9 ms p95=1.5 ms max=1.7 ms (rejected >75 m from network: 4)
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=3.9 ms p95=6.5 ms max=11.3 ms
======================= 303 passed, 1 warning in 15.04s ========================
$ (cd services/routing && uv run ruff check . && uv run ruff format --check .)
All checks passed!
20 files already formatted
$ (cd services/api && uv run ruff check . && uv run ruff format --check .)
All checks passed!
30 files already formatted
$ row counts in wp_routing after run
{'edge': 0, 'node': 0, 'closure': 0, 'community_report': 0, 'pilot_request': 0, 'weather_obs': 0, 'weather_daily': 0, 'report_311_cell': 0}
```
**Ownership gate: `exit=1`, expected.** `scripts/check-ownership.sh routing` compares this branch with `integration/winterpath` (`a292b63`) and lists the 26 Data-owned files the `f6eb3b2` merge brought in: `data/fixtures/pilot_mini/*`, `data/qa/*`, `db/migrations/versions/0006_report_311_nature.py`, `docs/agent-reports/data.md` and `services/ingestion/*`. I verified that:
- every non-owned file changed since the merge base (26) appears in `git diff --name-only a292b63 f6eb3b2`;
- `git diff f6eb3b2 HEAD -- <those 26 files>` is **empty** (byte-identical to Data's commit);
- the only commits touching them are Data's (`f6eb3b2`, `ee5f1fc`, `4254dd7`).

No routing commit edits a non-owned path. The gate will pass again once integration contains `f6eb3b2`.

Not run: `services/ingestion` tests (Data-owned; their PostGIS tests target Data's DB setup, not `wp_routing`).

### 0f. Cycle 8 — contract v1.6.0 (a292b63)
- **Merge:** `git merge --no-edit integration/winterpath` → `5af6145`, no conflicts; docs only. Just before it, a merge attempt returned `Already up to date.` (integration was still `eb92007`).
- **CR-ML-2:** `CATEGORY_311_TITLES` gains `snow_clearing_alley` ("311 reports: snow clearing (alley)" / "Requêtes 311 : déneigement (ruelle)") and `snow_dumping_alley` ("311 reports: snow dumping (alley)" / "Requêtes 311 : dépôt de neige (ruelle)"). A new test checks that all six canonical categories have titles.
- **`CONTRACT_VERSION` = `1.6.0`.**
- **CR-DATA-7 (foot overrides access): no routing change.** Routing excludes on the Data-resolved `edge.foot_access ∈ {no, private}` only. A way with `access=private` + `foot=yes` arrives as `foot_access=yes` and is routable.
- **Fixture:** `pilot_mini` is byte-identical at `4254dd7`, `ee5f1fc` and the current `agent/data` head `69bd9e6` (`git diff --stat` is empty). The cycle-7 preview (302 passed on the merged data fixture) therefore already covers `ee5f1fc`'s fixture, and the tests read counts and coordinates from the fixture.
- **Flaky skip:** one rerun before this cycle showed `301 passed, 1 skipped`. I couldn't reproduce it (3 more runs: 302 passed, 0 skipped), and that run's skip reason wasn't captured, so the cause is unconfirmed. The likely cause is a PostGIS probe timing out under load: probe failures skip rather than fail, and only the weather module's probe would skip exactly one test. Probe `connect_timeout` was raised from 2 s to 10 s in all four test modules.
```text
$ uptime → load averages: 14.79 10.34 10.22
$ alembic … current → 0006_report_311_nature (head)
$ uv run --project services/api pytest services/routing services/api -rs -p no:cacheprovider   # run twice
======================= 303 passed, 1 warning in 22.96s ========================
======================= 303 passed, 1 warning in 35.86s ========================
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
Pending: when Data's commit with the alley categories folded into 0006 lands, I'll re-migrate `wp_routing` (0006 changes in place, so `downgrade 0005` then `upgrade head` with the new files) and rerun.

### 0e. Cycle 7 — DB at migration 0006, API-NULL-1, data+routing preview
**Merge:** `git merge --no-edit integration/winterpath` **fast-forwarded** to `eb92007`, because integration already contained routing `f63027a`.
- `eb92007` completes the explanation evidence mapping. It now lists `PASSES/AVOIDS_POSSIBLE_CLOSURE` → `unknown`, `REDUCED_MOBILITY_SPEED` → `model_estimate` and `RISK_UNKNOWN_SHARE` → `unknown`, which is exactly the catalog, so no code change was needed and my cycle-6 questions are resolved.
- ML's new `EdgeIdRiskProvider` / `api_provider` is an alternative entry point. The API's `CoordinateRiskAdapter` over `load_provider` keeps working (tests pass with the artifacts).

**DB at 0006:** migration 0006 is only on `agent/data` (`4254dd7`), not in integration, and I did not merge `agent/data` into this branch. I exported its `db/` with `git archive agent/data db` into the scratchpad (its 0005 is identical to integration's) and ran its alembic against **my own** `wp_routing` only:
```text
target db: /wp_routing port 55432
$ alembic -c <scratch>/data-db/db/alembic.ini current   → 0005_closure_active_excl_end
$ … upgrade head; … current                             → 0006_report_311_nature (head)
```
With `nature` now present on the real table, `PostgisHazardRepository` takes the v1.5 path (`test_311_nature_detection_matches_real_table`, which follows the actual column, so it skips nothing).

**API-NULL-1 (Platform finding):** every optional request field in the contract is non-nullable. An explicit `null` is now 422 `VALIDATION_ERROR` (`schemas.NotNull`, a before-validator), and omitting the field still uses the default. Fields:
- `/reports` `description`, `locale`;
- `/pilot-requests` `contact_name`, `message`, `locale`;
- `/routes/compare` `departure_time`;
- moderation `note`.

`profile`, `locale` and `avoid_unverified_reports` on `/routes/compare` already rejected null through their non-null defaults; the tests cover them too. **Platform can remove both API-NULL-1 markers** once this is merged: the strict xfail will start failing as XPASS, as designed. 10 new tests.

**Data + routing preview** (because the coordinator will merge both): a throwaway detached worktree in the scratchpad, `agent/routing` @ `92150c1` + `git merge agent/data` (clean, `0efc09d`), same 0006 DB, ML artifacts copied in.
- First run: **`4 failed, 298 passed`**. The regenerated pilot_mini has 92 nodes (was 88) and a bbox of about 190 m (was about 340 m). My tests hard-coded the old count and route endpoints: the destination −73.5745 is now `OFF_NETWORK` (`nearest_network_m: 156.9`). Code was fine; the tests were brittle.
- Fix `517186d`: the tests read `metadata.json` and `nodes.geojson` (count, bbox, centre, farthest node pair).
- The worktree was removed afterwards.
```text
$ uptime → load averages: 6.30 12.31 13.37
== agent/routing @ 517186d (current pilot_mini, 88 nodes)
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=1.1 ms p95=1.7 ms max=2.4 ms (rejected >75 m from network: 48)
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=4.6 ms p95=6.2 ms max=9.9 ms
======================= 302 passed, 1 warning in 18.98s ========================
== preview: agent/routing + agent/data 4254dd7 (Geofabrik pilot_mini, 92 nodes)
[latency] REAL pilot_mini (OSM, 200 edges) n=100 compare() p50=1.3 ms p95=2.2 ms max=3.6 ms (rejected >75 m from network: 4)
[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair ODs: p50=4.6 ms p95=7.2 ms max=13.1 ms
======================= 302 passed, 1 warning in 19.15s ========================
$ (cd services/routing && uv run ruff check . && uv run ruff format --check .)
All checks passed!
20 files already formatted
$ (cd services/api && uv run ruff check . && uv run ruff format --check .)
All checks passed!
30 files already formatted
$ scripts/check-ownership.sh routing
ownership OK for agent/routing
$ row counts in wp_routing after both runs
{'edge': 0, 'node': 0, 'closure': 0, 'community_report': 0, 'pilot_request': 0, 'weather_obs': 0, 'weather_daily': 0, 'report_311_cell': 0}
```
(The "rejected" count is random points in the fixture bbox more than 75 m from the network. The new, tighter bbox gives 4 instead of 48. These are expected `OFF_NETWORK` rejections, not failures.)

### 0d. Merge of `integration/winterpath` `2d37f32` (`.env.example` weather names) — current
`git merge --no-edit integration/winterpath` → `e98e9de` (`.env.example | 4 ++++`), no conflicts. `wp_routing` is at `0005_closure_active_excl_end (head)`. `uptime`: `load averages: 17.56 19.65 24.68`.
```text
$ uv run --project services/api pytest services/routing services/api -rs -p no:cacheprovider
======================= 291 passed, 1 warning in 34.28s ========================
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

### 0c. Merge of `integration/winterpath` `d04da54` (Data migration 0005)
- `git merge --no-edit integration/winterpath` → `ac80a71`, with no conflicts. It brought migration `0005_closure_active_exclusive_end` and the Data and Platform report updates.
- `wp_routing` was upgraded: `alembic … current` → `0005_closure_active_excl_end (head)`.
- I added the boundary case `TEST-RT-ends-at-t` (`valid_to` exactly at `t` → inactive → dropped) to the PostGIS closure-activity test. It passes against the 0005 function.
- `/health` keeps `checks.weather.status = degraded` when the latest observation is stale or absent (`test_api_weather_stale_is_503_and_health_degraded`).

`uptime`: `load averages: 15.59 20.59 25.86`.
```text
$ uv run --project services/api pytest services/routing services/api -rs -p no:cacheprovider
======================= 291 passed, 1 warning in 23.92s ========================
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
Integration note: the coordinator's `d04da54` includes routing up to `32e69f6` only. Cycle 6 (`864aa80`: v1.5.0 311 natures, 404 for every bad deletion attempt, `CONTRACT_VERSION` 1.5.0) and this commit are not yet in integration. After they are merged, the Platform harness must expect 404, not 422, for a malformed deletion token or id.

### 0b. Cycle 6 run (contract v1.5.0)
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
1. **CR-ROUTING-10 — RESOLVED** in `2d37f32` (merged as `e98e9de`): `.env.example` now lists the three weather names. They match `settings.py` (empty values fall back to `none` / `180` / no stations). For reference:
   - `WEATHER_SOURCE`: `none` (default, weather endpoints 503) or `postgis` (read `wp.weather_obs` / `wp.weather_daily` via `DATABASE_URL`);
   - `WEATHER_MAX_AGE_MINUTES`: default `180`; an older latest observation is stale → `/weather/current` 503 and `/health` `checks.weather.status = degraded`;
   - `WEATHER_STATION_IDS`: comma-separated ECCC station ids in priority order; empty = most recent across stations.

   Usage notes for existing names: `RISK_PROVIDER=winterpath_ml.inference:load_provider` enables the ML layer, and `API_ADMIN_TOKEN_HASH` = SHA-256 hex of the token (optional `sha256:` prefix).
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
