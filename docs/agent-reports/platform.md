# Agent report — platform

- **Status:** READY FOR REVIEW (harness verified against the stub **and the live merged real API**; CI never run on GitHub — no remote, nothing pushed)
- **Branch / SHA:** agent/platform — fast-forwarded to `integration/winterpath` 2d37f32 (d04da54 + one `.env.example` commit); this checkpoint's harness changes and report are in the commit after it. Earlier: 5ce5c9f (v1.1.0 adoption), b6daddf (original).
- **Contract:** v1.5.0 (merged; `docs/contracts/` not edited on this branch)
- **Date (UTC):** 2026-11-11

## Update 2026-11-11 (k) — scoring job: `--fetch-311 --write-db`
The coordinator set the `WP_ETL_DATABASE_URL` secret and dispatched `scheduled.yml` on main 0e9adef (run 43084925719). The weather job succeeded end to end (Supabase's latest observation: 19:00 UTC). Scoring failed with `311 aggregates missing … (use --fetch-311)`, exit 2. The step now runs:
`uv run --locked python -m "$SCORING_MODULE" --start "$day" --fetch-311 --write-db`
Both flags are `add_argument` options in `services/ml/src/winterpath_ml/score.py` on integration 0e9adef: `--fetch-311` downloads and aggregates 311 into `<WP_ML_CACHE_DIR>/score/`, and `--write-db` writes `wp.risk_cell_score` and reads `DATABASE_URL`, which the step provides from the secret.

**311 download cache: not added (deliberate).**
1. `fetch_311()` always streams the CSV, unconditionally. Without `--fetch-311`, the scorer reads `config.INTERIM_DIR`, not the `score/` directory. A restored cache would therefore never be used without an ML code change.
2. The 18:00 UTC run exists to pick up 311 rows that are missing at 12:00. Reusing the 12:00 download would score the same file twice.
If ML later adds a conditional fetch (ETag / If-Modified-Since), a cache keyed on the response validator would be the right design.
```text
$ actionlint   -> [actionlint exit 0]
$ grep -n -E "SCORING_MODULE|fetch-311" .github/workflows/scheduled.yml
154:          uv run --locked python -m "$SCORING_MODULE" --start "$day" --fetch-311 --write-db
```
Not verified by me: the scoring step has not been re-run. The coordinator will merge, push and re-dispatch.

## Update 2026-11-11 (j) — CI: production build + safety scan (`build:pages`) on every web change
Merged frontend's exact commit 4ed7c81 as merge commit 3d2685b; it changed no platform-owned paths. In `ci.yml`'s `web` job, after `npm run build`, a new step runs `npm run build:pages` with placeholder production values: `VITE_API_BASE_URL=https://example.invalid/api/v1` (a reserved TLD that never resolves) and `VITE_PUBLIC_WRITES=false`. `build:pages` = `pagesCheck.ts env` (refuses an unsafe env) → `npm run build` → `pagesCheck.ts dist` (scans for mock code, sourcemaps, secrets, headers). If the script is absent on a branch, the step emits a `::notice` SKIP. It builds only; nothing is published.
```text
$ actionlint   -> [actionlint exit 0]
$ (apps/web, Node v24.13.0, after npm ci: "added 554 packages in 27s")
$ VITE_API_BASE_URL=https://example.invalid/api/v1 VITE_PUBLIC_WRITES=false npm run build:pages   (VITE_USE_MOCKS unset)
> @winterpath/web@0.1.0 build:pages
> node build/pagesCheck.ts env && npm run build && node build/pagesCheck.ts dist
pages-check env: OK
pages-check dist: OK
[build:pages exit 0]
$ (negative control) VITE_PUBLIC_WRITES unset -> node build/pagesCheck.ts env
pages-check env: FAILED
  - VITE_PUBLIC_WRITES must be "false" (user decision: read-only public demo)
[env-check exit 1]
```
The build also printed Rollup "annotation that Rollup cannot interpret" warnings from `node_modules/zod`. These are informational and belong to the frontend. `apps/web/dist` is git-ignored. Not verified: the step has not run on GitHub.

## Update 2026-11-11 (i) — deploy blocker: model registry in the API image
The coordinator's trial image (`--memory=512m --cpus=0.1`, real DB at 0007 with today's scores) reported `risk: disabled` because the image had no `models/registry.json`. That was a known open item: I flagged it in update (f) but had not fixed it. Changes:
- `infra/docker/api.Dockerfile`: `COPY --chown=root:root --chmod=0444` of `models/registry.json` → `/app/models/registry.json`, and of `models/artifacts/v2-8d19aa86/coverage_cells.parquet` → `/app/models/artifacts/v2-8d19aa86/`. Sets `ENV MODEL_REGISTRY_PATH=/app/models/registry.json MODEL_ARTIFACT_DIR=/app/models/artifacts`. `/app` is no longer chowned to the app user, so the app user cannot write there. CMD default port is now `${PORT:-10000}` (Render's default), with `EXPOSE 10000`.
- `infra/docker/api.Dockerfile.dockerignore`: allows exactly those two files.
- `docker-compose.yml` (`api` profile): container port and healthcheck now use 10000; the host port is still `${API_PORT:-8105}`.
- CI `deploy-readiness`: new step running `inference.load_registry()` **with no arguments** in the container. It asserts that the registry's coverage artifact resolves to an existing file. The smoke run no longer passes `PORT`, so it exercises the 10000 default.

**Merge-order dependencies (deploy-readiness stays red until both land on integration):**
1. `models/artifacts/v2-8d19aa86/coverage_cells.parquet` is committed on `agent/ml` (8771d77) but not on integration (5238c45), so the `COPY` fails the build without it.
2. ML's config does not honour `MODEL_REGISTRY_PATH` yet, on either branch. The no-argument `load_registry()` resolves relative to the installed package (`/opt/venv/models/registry.json`), so the new step fails. That is the blocker the coordinator found, now caught in CI.

Local verification used a scratch build context: the working-tree versions of tracked files plus the parquet taken from `agent/ml`, with sha256 equal to the registry's. Nothing was added to the worktree, and the scratch context and image were removed afterwards.
```text
$ shasum -a 256 coverage_cells.parquet (from agent/ml)
f7519df54d64d5d8734add8b4c3aa0631093007ffdd29de62432b729f8dc12cd
(registry: f7519df54d64d5d8734add8b4c3aa0631093007ffdd29de62432b729f8dc12cd)
$ docker build ... -> [build exit 0]
10001
-r--r--r-- 1 root root  4335 ... /app/models/registry.json
-r--r--r-- 1 root root 19883 ... coverage_cells.parquet
touch: cannot touch '/app/models/x': Permission denied
MODEL_REGISTRY_PATH=/app/models/registry.json MODEL_ARTIFACT_DIR=/app/models/artifacts

=== CI step: risk provider finds the model registry
FileNotFoundError: [Errno 2] No such file or directory: '/opt/venv/models/registry.json'
[registry step exit 1]                       <- expected until ML honours MODEL_REGISTRY_PATH
=== same, explicit path
explicit path OK; coverage resolves to /app/models/artifacts/v2-8d19aa86/coverage_cells.parquet exists= True

$ docker run --memory=512m --cpus=0.1 (no PORT; fixture graph, memory store, no DB)
ready: http://127.0.0.1:18115/api/v1/health
boot to healthy: 21.7 s (fixture graph, 0.1 CPU, 512m)
{"status":"ok","version":"0.1.0 (contract 1.6.0)","checks":{"graph":{"status":"ok"},"database":{"status":"disa…
coverage 200
mem 69.7MiB / 512MiB
$ actionlint -> [actionlint exit 0];  make config -> compose config OK
```
For the record (coordinator's measurement, real DB): boot to healthy 47 s at 0.1 CPU, 191 MiB RSS, DB ok. My fixture-graph number above is not comparable (no DB, no PostGIS graph). Local note: port 18080 was already in use on this machine by another container, which I did not touch; my run used 18115. CI is unaffected (fresh runner).

## Update 2026-11-11 (h) — weather job uses Data's per-source load (360fdd4)
Merged data's exact commit 360fdd4 as merge commit 87c3841; it changed no platform-owned paths. The weather step is now:
`uv run --locked wp-ingest load --source eccc-geomet --weather-since "$(date -u -d '365 days ago' +%F)"`
`--weather-since` keeps hosted `wp.weather_obs` bounded (Data's estimate: ~41–51 MB total). The `--help`-based fallback and `WEATHER_LOAD_SOURCE` are removed.
```text
$ (services/ingestion) uv run --locked wp-ingest load --help
usage: wp-ingest [-h] [--refresh] [--force] [--weather-since YYYY-MM-DD]
                 [--source {osm,mtl-voirie,mtl-entraves,mtl-311,eccc-geomet}]
                 {osm,fixture,voirie,entraves,311,eccc,all,load}
$ actionlint   -> [actionlint exit 0]
$ grep -n "wp-ingest load" .github/workflows/scheduled.yml
85:        run: uv run --locked wp-ingest load --source eccc-geomet --weather-since "$(date -u -d '365 days ago' +%F)"
```
`date -d` is GNU syntax, which matches the ubuntu-latest runner. Not verified: the job has not run on GitHub or against a database (no secret exists).

## Update 2026-11-11 (g) — coordinator review of 33537fe: scheduled.yml changes
Merged `integration/winterpath` 5238c45 first, as merge commit 89a0bf4. It changed no platform-owned paths and brought in `.gitignore` rules for the two scoring artifacts plus the deployment docs.

1. **Scoring schedule:** the 10:40 run is replaced by two runs, `0 12 * * *` and `0 18 * * *` UTC (07:00/13:00 EST, 08:00/14:00 EDT). The job `if:` matches either schedule. This relies on ML making its scorer idempotent (exit 0 if the day is already scored or inputs are incomplete).
2. **Artifacts:** the scoring job sets `MODEL_ARTIFACT_DIR: ${{ github.workspace }}/models/artifacts`, which ML's `config.py` honours (`ARTIFACT_DIR = Path(os.environ.get("MODEL_ARTIFACT_DIR", …))`). There is no download step. As of 5238c45 the artifacts are allowed by `.gitignore` but **not yet committed** (`git ls-files models/artifacts` → only `.gitkeep`). ML's sha256 check against `models/registry.json` will fail loudly until they are.
3. **Weather load:** the job uses `wp-ingest load --source "$WEATHER_LOAD_SOURCE"` (`eccc-geomet`, a placeholder for Data to confirm) once `wp-ingest load --help` advertises `--source`. If `--source` exists but does not list that name, the step fails with `::error` rather than loading the wrong thing. Until then it falls back to the full `wp-ingest load` with a `::notice` (non-weather sources skip with "no processed output"). Today the fallback is taken, because the CLI is unchanged and the weather loader key is still `eccc`.
4. **Container test under Render-Free limits: BLOCKED.** Routing's v1.7 commit is not on integration: `services/api` still has `CONTRACT_VERSION = "1.6.0"` and `settings.py` has no `API_PUBLIC_WRITES`, `RISK_SCORE_SOURCE` or `DATABASE_POOL_SIZE`. When it lands I will merge integration and run the image with `--memory=512m --cpus=0.1` against `wp_data`, `ROUTING_GRAPH_SOURCE=postgis` and `API_PUBLIC_WRITES=false`. I will report boot time, RSS, and p50/p95 for 100 `POST /routes/compare` requests with `{lon,lat}` points across the pilot bbox.

```text
$ actionlint            -> [actionlint exit 0]
$ grep -n -E "cron:|event.schedule" .github/workflows/scheduled.yml
16:    - cron: "17 */3 * * *"   # weather ingest every 3 h (minute 17 avoids top-of-hour congestion)
20:    - cron: "0 12 * * *"
21:    - cron: "0 18 * * *"
40:      (github.event_name == 'schedule' && github.event.schedule == '17 */3 * * *') ||
103:      (github.event_name == 'schedule' && (github.event.schedule == '0 12 * * *' || github.event.schedule == '0 18 * * *')) ||
$ (services/ingestion, branch-selection dry run, --help only, no DB)
fallback branch: no --source in 'wp-ingest load --help'
usage: wp-ingest [-h] [--refresh] [--force]
                 {osm,fixture,voirie,entraves,311,eccc,all,load}
```
Not verified: neither job has run on GitHub, and neither has touched a database, because no secret exists.

## Update 2026-11-11 (f) — v1.7 free-tier deployment drafts (nothing applied)
Context: merged `integration/winterpath` 07a1f29 (contract **v1.7.0**) once, after integration moved past 3aa6438; it touched no platform-owned paths. The user's request arrived truncated: it began mid-item at "free, runtime docker, …". Items (2)–(5) are done below; **item (1) was not received and is not done.**

**(2) `infra/render.yaml` (draft, not applied).** `runtime: docker`, `plan: free`, `region: virginia` (v1.7 decision), `autoDeploy: false`, `healthCheckPath: /api/v1/health`. 19 env vars, no duplicates. `sync: false` is used for every secret (`DATABASE_URL`, `API_ADMIN_TOKEN_HASH`, `GEOCODER_API_KEY`) and for not-yet-known deployment values (`API_CORS_ORIGINS`, `WEATHER_STATION_IDS`, `GEOCODER_PROVIDER`, `HTTP_USER_AGENT`). The v1.7 names are set: `API_PUBLIC_WRITES=false` (read-only demo), `RISK_SCORE_SOURCE=postgis`, `DATABASE_POOL_SIZE=2`, `DATABASE_MAX_OVERFLOW=0`. Graph, store and weather are all from PostGIS. `PORT` is deliberately not declared, because Render injects it. Sizing values are drafts marked "verify". The `VITE_*` names are documented as Vercel settings. Render cron was removed in favour of GitHub Actions (v1.7 decision).

**(3) `.github/workflows/scheduled.yml` (new, inert until the secret exists).**
- `weather-ingest`: every 3 h (`17 */3 * * *`), running `wp-ingest eccc --refresh` then `wp-ingest load` (the other sources skip with "no processed output").
- `daily-scoring`: `40 10 * * *` UTC = 05:40 EST / 06:40 EDT.
- Both have `workflow_dispatch` (input `job: weather|scoring|both`), per-job `concurrency` (no cancel mid-load), `timeout-minutes` (15 / 30), top-level `permissions: {}` and job-level `contents: read`, and `persist-credentials: false`.
- The secret `WP_ETL_DATABASE_URL` is checked first. If it is missing, the job emits `::notice … nothing ran` and succeeds. When present, it is passed as `DATABASE_URL` only to the step that connects, never to third-party actions.
- Installs use `uv sync --locked`; `uv lock --check` is clean for `services/ingestion` and `services/ml`.
- **Open dependency (ML):** no ML code writes `wp.risk_cell_score` yet. `winterpath_ml.score` writes Parquet files and needs local artifacts. The scoring job therefore has a second gate: it no-ops with a notice until `services/ml/src` references `wp.risk_cell_score`. `SCORING_MODULE` is a placeholder for ML to confirm before the secret is added.

**(4) CI `deploy-readiness` job (in `ci.yml`, new `deploy` path filter).** It runs `docker build -f infra/docker/api.Dockerfile`, asserts a non-root uid, and boots the container like Render (`PORT=10000`, fixture graph, memory store). It then asserts `/api/v1/health` status ok|degraded with `checks.graph.status == ok`, and `/coverage` 200. It always prints logs and cleans up. It pushes no image and deploys nothing.

**API image fixes found by that smoke test (`infra/docker/api.Dockerfile`, owned):**
1. The old build installed `./services/api`, whose `[tool.uv.sources]` mark routing/ml as **editable**. They were linked to `/src`, which is absent in the runtime stage, so the real image failed at import with `ModuleNotFoundError: No module named 'winterpath_routing'`. My original v1.0 probe build used a throwaway stand-in app, so it never caught this. The build now runs `uv sync --frozen --no-dev --no-editable` from `services/api/uv.lock`: pinned, hash-checked, with real copies in the venv.
2. The image binds `0.0.0.0:${PORT:-8000}` (v1.7). Compose and local runs still use 8000.
3. The image ships `data/fixtures/pilot_mini` (with `ATTRIBUTION.md`) and sets `ROUTING_FIXTURE_DIR`, because the API's default fixture path is relative to the source tree.
4. New `infra/docker/api.Dockerfile.dockerignore` (allow-list): only `services/` and the fixture go into the build context. Before this, `.env.local`, `.git`, venvs and `node_modules` were sent to the Docker daemon, although never copied into the image.

**(5)** Drafts only. Nothing was pushed, deployed or provisioned; no Render, Supabase or registry resources were created, and no secret was set.

Literal outputs:
```text
$ docker build -f infra/docker/api.Dockerfile -t wp-api:deploycheck .     (before the fix)
$ docker run ... python -c "import winterpath_api.main as m; m.app"
ModuleNotFoundError: No module named 'winterpath_routing'

$ (after the fix) docker build ...  -> [build exit 0]
uid=10001(app) gid=10001(app) groups=10001(app)
winterpath_api / winterpath_ml / winterpath_routing (+ dist-info), no _editable_impl_* ; no /src
$ docker run -d -p 127.0.0.1:18110:10000 -e PORT=10000 -e ROUTING_GRAPH_SOURCE=fixture -e API_STORE_BACKEND=memory -e WEATHER_SOURCE=none -e RISK_PROVIDER=none wp-api:deploycheck
ready: http://127.0.0.1:18110/api/v1/health
{"status":"ok","version":"0.1.0 (contract 1.6.0)","checks":{"graph":{"status":"ok"},"database":{"status":"disabled","detail":"In-memory stores (no DATABASE)."},"risk":{"status":"disabled","detail":"No risk layer; risk reported as unknown."},"weather":{"status":"disabled","detail":"No ECCC adapter configured."}}}
coverage 200
{"nodes": 92, "edges": 200, "simulated": false, "event": "graph_loaded", ...}
container removed; local image removed

$ actionlint                     -> [actionlint exit 0]   (ci.yml incl. deploy-readiness, scheduled.yml)
$ (PyYAML) render.yaml / scheduled.yml / ci.yml -> YAML OK
render: docker free virginia /api/v1/health autoDeploy= False
env keys: 19 dupes: 0
$ (gate dry run, secret empty)
::notice title=SKIP weather ingest::repository secret WP_ETL_DATABASE_URL is not set — nothing ran
gate output: configured=false
$ grep -rqs risk_cell_score services/ml/src  -> absent -> daily-scoring would SKIP with notice
$ make lint-infra -> compose config OK [exit 0];  make config -> compose config OK
$ scripts/check-ownership.sh platform -> ownership OK for agent/platform
```
Not verified: neither workflow change has run on GitHub. The scheduled jobs have not run against a database; that is by design, since no secret exists. The API on this tree still reports contract 1.6.0, so `API_PUBLIC_WRITES`, `RISK_SCORE_SOURCE` and `DATABASE_POOL_SIZE`/`DATABASE_MAX_OVERFLOW` have no effect until Routing's v1.7 work lands. The deployed risk layer may also need `models/registry.json`, which the image does not ship; ML/Routing to confirm.

## Update 2026-11-11 (e) — CI: Playwright job runs in the official image (no apt)
The coordinator reported that CI run 43053137078 on main 6a712e9 passed 11/12 jobs; the contract job is green, which confirms the CORS fix from update (b). The `playwright` job failed twice in `npx playwright install --with-deps chromium`, with apt exit 100. Literal lines from `gh run view 43053137078 --log-failed`:
```text
Temporary failure resolving 'azure.archive.ubuntu.com'
Temporary failure resolving 'archive.ubuntu.com'
Temporary failure resolving 'security.ubuntu.com'
```
Fix (`.github/workflows/ci.yml`, job `e2e`, the coordinator's preferred option):
- `container: mcr.microsoft.com/playwright:v1.65.0-noble@sha256:6e3fb709361521eb27161606e6da6d2674e5e89fa16516cb37d6fdd91372273d`, `options: --ipc=host`. The tag equals apps/web's exact `"@playwright/test": "1.65.0"`; the lockfile resolves `@playwright/test` and `playwright` to 1.65.0. Pinned by digest, like the actions. MCR: tags `v1.65.0-noble` and `v1.65.0` both return HTTP 200 with this digest.
- The `npx playwright install --with-deps chromium` step is removed. In its place, a step checks that `playwright-core`'s `chromium.executablePath()` exists in the image and fails with an `::error` naming the required version otherwise. A future `@playwright/test` bump without a tag/digest bump therefore fails loudly instead of downloading. There are no apt calls and no browser download.
- `setup-node` stays, so the job keeps the project's Node 24 (the image ships Node v26.13.0).

```text
$ actionlint                          -> [actionlint exit 0]   (1.7.12)
$ grep -n -- "--with-deps" .github/workflows/ci.yml   -> exit 1 (no matches)

$ (local dry run of the job steps in the same image digest, `git archive HEAD` copy, CI=true, --ipc=host)
v26.13.0
aarch64
chromium OK: /ms-playwright/chromium-1254/chrome-linux-arm64/chrome
  102 passed (4.7m)
[docker exit 0]
```
Differences between the dry run and CI: it ran on arm64 (CI is amd64; same multi-arch digest), used the image's Node 26 (CI uses Node 24 via setup-node), and ran as root (as GitHub's container jobs do by default). Not verified: the workflow change has not run on GitHub; that needs the coordinator's push. Nothing was pushed.

## Update 2026-11-11 (d) — merged integration/winterpath 6a712e9 (all five agents); checks re-run
1. `git merge --no-edit integration/winterpath` → **fast-forward** to 6a712e9 (contains platform b2ed23a). Platform-owned paths are unchanged by it. Contract `version: 1.6.0`. `apps/web` now exists, so `make test` and `make lint` also cover the frontend.
2. **Makefile fix (owned).** On first run, `make test` exited 2 at the web step because this worktree had never installed web dependencies. Literal output:
   ```text
   > @winterpath/web@0.1.0 test
   > vitest run --run
   sh: vitest: command not found
   make: *** [test] Error 127
   ```
   The web steps in `test` and `lint-web` now run `npm ci --no-audit --no-fund` when `apps/web/node_modules` is missing (it is git-ignored, `.gitignore:32`). This matches how the Python targets `uv sync` first.
3. **Finding for Routing/ML — not fixed here (routing-owned file):** `services/api/uv.lock` is stale on integration. ML's `services/ml/pyproject.toml` added a `db` extra (`psycopg[binary]>=3.2`), but the API lock was not regenerated. Plain `uv run` in `services/api` silently re-locks it (+2 lines: the psycopg requirement and `provides-extras = ["db"]`). I restored the file with `git checkout -- services/api/uv.lock` and did not commit it.
   ```text
   $ (per package) uv lock --check
   services/ingestion   Resolved 34 packages in 40ms
   services/routing     Resolved 18 packages in 4ms
   services/ml          Resolved 22 packages in 3ms
   services/api         The lockfile at `uv.lock` needs to be updated, but `--check` was provided. To update the lockfile, run `uv lock`.
   tests/integration    Resolved 62 packages in 9ms
   ```
   CI did not catch it because the Python matrix job runs `uv sync --all-extras --dev` (`ci.yml:112`) without `--locked`. Proposal, not applied (it would turn main red until Routing runs `uv lock` in `services/api`): switch that step to `uv sync --locked --all-extras --dev`, and use `uv run --locked` in the Makefile package loops, so a stale lock fails loudly instead of being rewritten in any agent's worktree.

Literal outputs (merged tree 6a712e9 + Makefile fix):
```text
$ make test        (stub; API_BASE_URL unset)
59 passed, 5 skipped in 11.30s
== services/ingestion
50 passed in 22.68s
== services/routing
210 passed, 1 skipped in 8.21s
== services/ml
43 passed, 1 skipped in 2.69s
== services/api
79 passed, 13 skipped, 1 warning in 5.11s
added 554 packages in 12s
 Test Files  11 passed (11)
      Tests  107 passed (107)
[make test exit 0]

$ make lint
All checks passed! / 13 files already formatted        (tests/integration)
All checks passed! / 27 files already formatted        (services/ingestion)
All checks passed! / 20 files already formatted        (services/routing)
All checks passed! / 28 files already formatted        (services/ml)
All checks passed! / 30 files already formatted        (services/api)
> eslint . --max-warnings 0                             (apps/web; no findings printed)
compose config OK
[make lint exit 0]

$ actionlint                -> [actionlint exit 0]
$ make config               -> compose config OK [make config exit 0]
$ scripts/check-ownership.sh platform
ownership OK for agent/platform

$ (real API from this tree, port 8105, same launch env as update (c), `uv run --frozen` so the lockfile is not rewritten)
{"status":"ok","version":"0.1.0 (contract 1.6.0)","checks":{"graph":{"status":"ok"},"database":{"status":"disabled",...},"risk":{"status":"disabled",...},"weather":{"status":"disabled",...}}}
=== real API, CONTRACT_MAX_EXAMPLES=40
59 passed, 5 skipped in 20.96s
[exit 0]
=== real API, CONTRACT_MAX_EXAMPLES=150
59 passed, 5 skipped in 53.51s
[exit 0]
log lines: 4530 | precise coordinate hits: 0
API stopped; 8105 free
```
`npm ci` also printed two deprecation warnings (`whatwg-encoding@3.1.1`, `eslint@9.39.5`), which belong to the frontend. The ML risk layer is still disabled locally because `models/artifacts/` is empty in this worktree.

## Update 2026-11-11 (c) — API-NULL-1 fixed upstream; all 7 markers removed
Coordinator instruction: merge routing's exact commit b036aab, remove all 7 API-NULL-1 markers in one commit, and run the harness against the stub and against a real API started from this tree.

1. `git merge --no-edit b036aab` → merge commit 74bc91e, no conflicts, no rebase or force. Platform-owned paths are untouched by the merge (`git diff --stat e0d1dc6 HEAD -- infra .github tests/integration docker-compose.yml Makefile docs/agent-reports/platform.md` → empty). The merge also brings in contract **v1.6.0**. The fix is visible in `services/api/src/winterpath_api/schemas.py`, e.g. `locale: Annotated[Locale | None, NotNull] = None`.
2. Removed: the 5 strict xfails (`test_smoke.py::test_explicit_null_rejected_for_non_nullable_optional`; the test itself stays as a regression check) and the 2 non-strict xfails (`test_contract.py::test_negative` for `POST /pilot-requests` and `POST /reports`), including `API_NULL_1_OPS`, `API_NULL_1` and `NULLABLE_GAP`.
3. The `/health` contract-version mismatch noted earlier is resolved: the API now reports `contract 1.6.0`.

Literal outputs:
```text
$ grep -rn -E "xfail|API.NULL|NULLABLE_GAP|applymarker" tests/integration/*.py
test_contract.py:7:  expected failures (API-NULL-1 fixed in routing b036aab; markers removed).
(docstring changelog line only — no markers)

$ cd tests/integration && uv run ruff check . && uv run ruff format --check .
All checks passed!
13 files already formatted

$ (stub) uv run pytest -q -rxX
59 passed, 5 skipped in 17.85s
[stub exit 0]

$ (real API from this tree, port 8105; same launch env as the 2026-11-11 run above)
$ curl -sS http://127.0.0.1:8105/api/v1/health
{"status":"ok","version":"0.1.0 (contract 1.6.0)","checks":{"graph":{"status":"ok"},"database":{"status":"disabled","detail":"In-memory stores (no DATABASE)."},"risk":{"status":"disabled","detail":"No risk layer; risk reported as unknown."},"weather":{"status":"disabled","detail":"No ECCC adapter configured."}}}
=== real API, CONTRACT_MAX_EXAMPLES=40
59 passed, 5 skipped in 14.50s
[exit 0]
=== real API, CONTRACT_MAX_EXAMPLES=150
59 passed, 5 skipped in 30.48s
[exit 0]
log lines: 4528 | precise coordinate hits: 0
API stopped; 8105 free
```
No XFAIL or XPASS in either real-API run (`-rfExX` printed none). The ML risk layer is still disabled locally because `models/artifacts/` has no artifacts in this worktree; the coordinator's trial merge covered that configuration. The CI admin-token idea is deferred, as the coordinator asked.

## Update 2026-11-11 (b) — CI fix: CORS origin for the real-API contract step
The coordinator reported the first GitHub run (private repo, run 43031068137, main = a292b63): 11/12 jobs passed. `contract + integration (schemathesis)` failed only in the step `tests against real API`. Literal lines from `gh run view 43031068137 --log-failed`:
```text
FAILED test_cors.py::test_preflight_allowed_origin - assert 405 in (200, 204)
FAILED test_cors.py::test_simple_request_headers - AssertionError: assert None == 'http://localhost:5175'
2 failed, 46 passed, 9 skipped, 5 xfailed, 2 xpassed in 7.34s
```
Cause: that step started uvicorn without `API_CORS_ORIGINS`. The API then installs no CORS middleware, so the preflight gets 405 and plain requests carry no ACAO header. The harness expects `http://localhost:5175`.

Fix (`.github/workflows/ci.yml`, step env only): `API_CORS_ORIGINS: http://localhost:5175` and `CORS_ALLOWED_ORIGIN: http://localhost:5175`, so the server allow-list and the harness expectation are the same explicit origin (no wildcard). Nothing was pushed; the coordinator merges and pushes.
```text
$ actionlint --version && actionlint
1.7.12
[actionlint exit 0]

$ (local reproduction of the CI step on port 8105; API started with only API_CORS_ORIGINS=http://localhost:5175)
$ API_BASE_URL=http://127.0.0.1:8105/api/v1 API_LOG_FILE=<scratch>/api.log CORS_ALLOWED_ORIGIN=http://localhost:5175 uv run pytest -q test_cors.py
3 passed in 0.06s
[exit 0]
```
Not verified: the fix has not run on GitHub yet. That needs the coordinator's next push.

Follow-up, not changed: the CI real-API step sets no `API_ADMIN_TOKEN` / `API_ADMIN_TOKEN_HASH`, so `test_admin_invalid_input_rejected_when_authorized` (4 cases) skips there. That accounts for 9 skipped = 5 + 4 in the log above. Positive admin contract cases only see 401. Covering authorized admin paths in CI would need a per-run throwaway token generated in the step (hash to the API, plaintext to pytest, masked with `::add-mask::`). I can add this if the coordinator wants it.

## Update 2026-11-11 — merged integration/winterpath; harness run against the real API
Coordinator instruction: merge `integration/winterpath` (d04da54) at the next checkpoint, no rebase/force, and continue.

1. `git merge --no-edit integration/winterpath` → **fast-forward** to 2d37f32 (`.env.example: weather adapter names (routing CR)`, one commit past d04da54; it only adds 4 lines to `.env.example`). 146 files changed upstream; **none under platform-owned paths** (`git diff --stat 89477f5 HEAD -- infra .github tests/integration docker-compose.yml Makefile` → empty). Contract now `version: 1.5.0`; `services/{ingestion,routing,ml,api}` now exist, so `make test`/`make lint` exercise them instead of printing SKIP.
2. **Real API run (closes the "not run against the real API" blocker).** Entry point `winterpath_api.main:app` is confirmed (`services/api/src/winterpath_api/main.py`). Launched locally on my assigned port 8105, then stopped:
   `API_CORS_ORIGINS=http://localhost:5175 API_ADMIN_TOKEN_HASH=<sha256 of a throwaway token in the session scratchpad> RISK_PROVIDER=winterpath_ml.inference:load_provider ROUTING_GRAPH_SOURCE=fixture API_STORE_BACKEND=memory WEATHER_SOURCE=none uv run uvicorn winterpath_api.main:app --host 127.0.0.1 --port 8105 --no-access-log`
   ```text
   $ curl -sS http://127.0.0.1:8105/api/v1/health
   {"status":"ok","version":"0.1.0 (contract 1.3.0)","checks":{"graph":{"status":"ok"},"database":{"status":"disabled","detail":"In-memory stores (no DATABASE)."},"risk":{"status":"disabled","detail":"No risk layer; risk reported as unknown."},"weather":{"status":"disabled","detail":"No ECCC adapter configured."}}}
   $ curl -sS http://127.0.0.1:8105/api/v1/models/status
   {"risk_layer":"none","enabled":false,"model_id":null,...}
   weather/current 503
   ```
   **Not reproduced here:** the coordinator's "heuristic risk on" configuration. `models/artifacts/` in this worktree holds only `.gitkeep` (artifacts are not in Git), so the risk layer came up disabled and every segment's risk is `unknown`. My run covers the contract surface, not the ML layer.
3. **Defect found in the real API — API-NULL-1 (routing-owned, not fixed here).** At `CONTRACT_MAX_EXAMPLES=150`, Schemathesis failed `test_negative[POST /pilot-requests]`:
   ```text
   - ST201 Schema-violating request accepted
       Invalid data should have been rejected
       Expected: 400, 401, 403, 404, 405, 406, 409, 415, 422, 428, 429, 5xx
       Invalid component: in body - locale: Incorrect type
   [201] Created:
       <EMPTY>
   1 failed, 22 passed, 5 skipped, 31 deselected in 28.06s
   ```
   Manual reproduction (in-memory store only):
   ```text
   POST /pilot-requests  locale: null  -> 201      (contract: string enum [en, fr], not nullable)
   POST /pilot-requests  no locale     -> 201
   POST /pilot-requests  locale: "de"  -> 422      (control)
   POST /reports  baseline             -> 201
   POST /reports  locale: null         -> 201      (contract: string enum, not nullable)
   POST /reports  description: null    -> 201      (contract: string, maxLength 280, not nullable)
   ```
   Cause: `services/api/src/winterpath_api/schemas.py` declares optional fields as `X | None = None` (e.g. lines 132, 134, 337, 338), so pydantic accepts an explicit `null`. Suggested fix for Routing: make them non-nullable when present (e.g. a validator that rejects explicit `None`, or `Field(default=None)` without `| None` in the type plus `exclude_unset`). The default 40-example run also hit it once, so contract runs against the real API were **flaky** until it is contained.
4. **Harness changes (owned paths only):**
   - `test_smoke.py::test_explicit_null_rejected_for_non_nullable_optional`: a deterministic check over 5 fields (`/pilot-requests` contact_name/message/locale, `/reports` description/locale). It must give 400/422 `VALIDATION_ERROR`. Passes against the stub. Against the real API it is a **strict** xfail (`API-NULL-1`), so it turns red as soon as the API is fixed, which forces the marker's removal.
   - `test_contract.py::test_negative`: a **non-strict** xfail for `POST /pilot-requests` and `POST /reports` only, and only against the real API. Whether Schemathesis generates a `null` body depends on the data, so a strict marker would flap. Remove it together with the strict one.
5. Note for Routing: `/health` reports `contract 1.3.0` (`CONTRACT_VERSION` in `services/api/src/winterpath_api/__init__.py`) while the merged contract is 1.5.0. This is an observation only; I don't know whether v1.4/v1.5 changed anything the API must implement.

Literal outputs:
```text
$ (real API) API_BASE_URL=http://127.0.0.1:8105/api/v1 API_LOG_FILE=<scratch>/api.log API_ADMIN_TOKEN=<scratch token> CORS_ALLOWED_ORIGIN=http://localhost:5175 uv run pytest -q -rxX
XFAIL test_contract.py::test_negative[POST /pilot-requests]
XFAIL test_smoke.py::test_explicit_null_rejected_for_non_nullable_optional[/pilot-requests-base0-contact_name]
XFAIL test_smoke.py::test_explicit_null_rejected_for_non_nullable_optional[/pilot-requests-base1-message]
XFAIL test_smoke.py::test_explicit_null_rejected_for_non_nullable_optional[/pilot-requests-base2-locale]
XFAIL test_smoke.py::test_explicit_null_rejected_for_non_nullable_optional[/reports-base3-description]
XFAIL test_smoke.py::test_explicit_null_rejected_for_non_nullable_optional[/reports-base4-locale]
XPASS test_contract.py::test_negative[POST /reports]
52 passed, 5 skipped, 6 xfailed, 1 xpassed in 48.21s
[exit 0]

$ (real API, CONTRACT_MAX_EXAMPLES=150, same env)
52 passed, 5 skipped, 6 xfailed, 1 xpassed in 97.23s (0:01:37)
[exit 0]

$ (privacy) log_scan.precise_coordinates over the real API's captured log
log lines: 11115 | precise coordinate hits: 0

$ make test        (stub; API_BASE_URL unset)
59 passed, 5 skipped in 10.26s
== services/ingestion
42 passed in 25.34s
== services/routing
210 passed, 1 skipped in 7.20s
== services/ml
28 passed in 2.42s
== services/api
68 passed, 11 skipped, 1 warning in 8.25s
SKIP apps/web: no package.json on this branch
[make test exit 0]

$ make lint
All checks passed! / 13 files already formatted        (tests/integration)
All checks passed! / 26 files already formatted        (services/ingestion)
All checks passed! / 20 files already formatted        (services/routing)
All checks passed! / 22 files already formatted        (services/ml)
All checks passed! / 30 files already formatted        (services/api)
SKIP apps/web: no package.json on this branch
compose config OK
[make lint exit 0]

$ actionlint        -> [exit 0]  (1.7.12)
$ make config       -> compose config OK [exit 0]
$ scripts/check-ownership.sh platform
ownership OK for agent/platform
$ docker ps --filter name=winterpath-db-1
winterpath-db-1 Up 10 hours (healthy)
```
(`make lint` lines are shown as summary pairs; the per-package ruff output was the two lines shown for each.) The `services/api` warning is a Starlette `httpx` deprecation inside the API's test client, owned by Routing.

Remaining blockers after this checkpoint:
| Blocker | Next step / who |
|---|---|
| CI has never executed on GitHub | Coordinator/user, when a remote exists |
| ~~API-NULL-1~~ | **Resolved**: fixed in routing b036aab; all 7 markers removed (update (c)) |
| ML risk layer not exercised by the platform harness locally (no artifacts in this worktree) | Coordinator's run covered it; Platform can re-run with artifacts if provided |

## Update 2026-11-10 — contract v1.1.0 adopted (superseded by the 2026-11-11 update where they differ)
The coordinator's instruction was: merge `integration/winterpath` (f191fce), remove the CR-PLAT-1 xfails, and re-verify.

1. `git merge --no-edit integration/winterpath`: merge made by `ort`, merge commit 11e525f, no conflicts, no rebase or force. The merge brought in `docs/contracts/openapi.yaml` 1.1.0, `integration-rules.md` §7 changelog, `.env.example` test-harness names and `scripts/` changes. I reviewed the contract diff and it matches CR-PLAT-1 exactly. **`docs/contracts/` was not edited on this branch.**
2. I removed the 4 strict xfail markers and the `KNOWN_NEGATIVE_GAPS` list from `tests/integration/test_contract.py`.
3. **A defect surfaced and was fixed (test harness, not stub or contract).** With the xfail removed, `test_negative[GET /admin/reports]` failed with Schemathesis `ST201 Schema-violating request accepted`. The generated case had removed the `Authorization` header (`header: violates required (was Authorization)`), but `_call()` re-injected the admin bearer token, which undid the mutation. The stub then correctly answered 200. Literal excerpt from the failing run:
   ```text
   - ST201 Schema-violating request accepted
       Invalid data should have been rejected
       Invalid component:
         - query: violates `additionalProperties`
         - header: violates `required` (was Authorization)
   [200] OK:
       `{"items":[],"next_cursor":null}`
   1 failed, 49 passed, 5 skipped in 25.31s
   ```
   Fix: the token is now injected only for positive cases (`inject_auth=True`). To keep validation behind auth covered, I added `test_smoke.py::test_admin_invalid_input_rejected_when_authorized`, with 4 cases: bad `status`, `limit=0`, bad `decision`, non-uuid id. Each expects 400/422 `VALIDATION_ERROR`.
4. The stub needed no code change. It already returns 400 for malformed bodies wherever the operation declares 400, and `/pilot-requests` now declares it.

Post-merge literal outputs:
```text
$ make test
cd tests/integration && uv sync --locked --quiet && uv run pytest -q
..............ssss...s.....................................              [100%]
=========================== short test summary info ============================
SKIPPED [5] .venv/lib/python3.12/site-packages/pluggy/_manager.py:183: Impossible to generate negative test cases
54 passed, 5 skipped in 11.56s
SKIP services/ingestion: no pyproject.toml on this branch
SKIP services/routing: no pyproject.toml on this branch
SKIP services/ml: no pyproject.toml on this branch
SKIP services/api: no pyproject.toml on this branch
SKIP apps/web: no package.json on this branch
[exit 0]

$ (contract only, larger budget) CONTRACT_MAX_EXAMPLES=150 uv run pytest -q -m contract
SKIPPED [5] .venv/lib/python3.12/site-packages/pluggy/_manager.py:183: Impossible to generate negative test cases
23 passed, 5 skipped, 31 deselected in 34.12s

$ make lint
cd tests/integration && uv sync --locked --quiet && uv run ruff check . && uv run ruff format --check .
All checks passed!
13 files already formatted
SKIP services/ingestion: no pyproject.toml on this branch
SKIP services/routing: no pyproject.toml on this branch
SKIP services/ml: no pyproject.toml on this branch
SKIP services/api: no pyproject.toml on this branch
SKIP apps/web: no package.json on this branch
actionlint
shellcheck -x -S warning infra/scripts/*.sh infra/db/init/*.sh
POSTGRES_USER=lint POSTGRES_PASSWORD=lint-placeholder docker compose config --quiet && echo "compose config OK"
compose config OK
[exit 0]

$ actionlint --version && actionlint
1.7.12
[exit 0]

$ make config
docker compose --env-file .env.local config --quiet && echo "compose config OK"
compose config OK
[exit 0]

$ grep -n "^  version" docs/contracts/openapi.yaml
4:  version: 1.1.0
$ grep -rn -E "xfail|KNOWN_NEGATIVE_GAPS" tests/integration/*.py
[exit 1 — 1 = no matches]
$ git diff --stat HEAD -- docs/contracts
[no output = contracts untouched]

$ scripts/check-ownership.sh platform
ownership OK for agent/platform

$ docker compose --env-file .env.local ps db
NAME              IMAGE                    COMMAND                  SERVICE   CREATED          STATUS                    PORTS
winterpath-db-1   postgis/postgis:16-3.4   "docker-entrypoint.s…"   db        18 minutes ago   Up 18 minutes (healthy)   127.0.0.1:55432->5432/tcp
```
The negative contract tests that were xfail before now pass, as shown in a `-rA` run before the harness fix: `PASSED test_negative[GET /weather/forecast]`, `[DELETE /reports/{reportId}]`, `[POST /admin/reports/{reportId}/moderation]`, `[POST /pilot-requests]`. `[GET /admin/reports]` also passes after the fix.

**The sections below are the original v1.0.0 report (commit b6daddf), kept for history.** Where they conflict with this update, this update wins.

## Files changed
```text
 .github/workflows/ci.yml                  | 307 ++++++++++
 Makefile                                  |  81 +++
 docker-compose.yml                        |  79 +++
 infra/OBSERVABILITY.md                    |  54 ++
 infra/README.md                           |  26 +
 infra/RUNBOOK.md                          |  75 +++
 infra/SUPABASE.md                         |  38 ++
 infra/db/init/20-winterpath.sh            |  49 ++
 infra/docker/api.Dockerfile               |  42 ++
 infra/docker/nginx-spa.conf               |  28 +
 infra/docker/web.Dockerfile               |  21 +
 infra/render.yaml                         |  46 ++
 infra/scripts/_common.sh                  |  11 +
 infra/scripts/db-backup.sh                |  13 +
 infra/scripts/db-bootstrap.sh             |   6 +
 infra/scripts/db-restore.sh               |  16 +
 infra/scripts/detect-services.sh          |  10 +
 infra/scripts/wait-for-http.sh            |   9 +
 infra/vercel/vercel.json                  |  23 +
 tests/integration/conftest.py             |  82 +++
 tests/integration/log_scan.py             |  24 +
 tests/integration/pyproject.toml          |  39 ++
 tests/integration/stub_server/README.md   |  19 +
 tests/integration/stub_server/__init__.py |   1 +
 tests/integration/stub_server/__main__.py |  17 +
 tests/integration/stub_server/app.py      | 211 +++++++
 tests/integration/stub_server/contract.py | 189 +++++++
 tests/integration/stub_server/fixtures.py | 184 ++++++
 tests/integration/test_contract.py        |  83 +++
 tests/integration/test_cors.py            |  45 ++
 tests/integration/test_openapi_valid.py   |  64 +++
 tests/integration/test_privacy.py         |  57 ++
 tests/integration/test_smoke.py           |  61 ++
 tests/integration/uv.lock                 | 912 ++++++++++++++++++++++++++++++
 34 files changed, 2922 insertions(+)
```

## What was built
- **`docker-compose.yml`**: the project name is pinned to `winterpath`, so every worktree targets the same container. `db` = `postgis/postgis:16-3.4` on `127.0.0.1:55432`, with a named volume `winterpath_pgdata`, a healthcheck (pg_isready plus a check that the init script finished), and an init script. The init script creates `wp_data wp_routing wp_ml wp_platform wp_integration` with `postgis`. It also creates the NOLOGIN group roles `wp_reader`, `wp_writer` (which includes `wp_reader`) and `wp_migrator`, with default privileges. `api` and `web` sit behind profiles. Credentials come only from env (`--env-file .env.local`); compose fails fast if they are missing.
- **`infra/`**: two Dockerfiles. The API image is python:3.12-slim running as uid 10001, with uvicorn's access log off because it prints raw query strings. The web image is a Vite build served by nginx-unprivileged, with SPA fallback and security headers. Drafts: Render blueprint (not applied, `autoDeploy: false`, no cron jobs), Vercel config, Supabase notes. Docs: runbook (backup, restore into a new DB, rollback table, incident checklist) and the observability spec (JSON log fields, never-log list, `/health` check semantics). Helper scripts live in `infra/scripts/`.
- **`.github/workflows/ci.yml`**: jobs are gated by path filters. They cover Python packages (ruff, pytest, pip-audit, with a PostGIS service container), web (lint, typecheck, test, build, `npm audit --audit-level=high`), Playwright, OpenAPI validation, contract tests (against the stub, plus the real API when `services/api` exists), compose (config, boot db, verify DBs/roles, shellcheck), gitleaks (checksum-verified binary, full history) and actionlint. A job whose package is missing on the branch prints a `::notice` SKIP and passes. Actions are pinned to commit SHAs. There are no deploy jobs.
- **`tests/integration/`**: Schemathesis contract tests in two modes: positive (valid input) and negative (invalid input must get a declared 4xx). Also smoke tests (`/health`, `/coverage`, OUTSIDE_COVERAGE, BBOX_TOO_LARGE, admin 401), a privacy test (logs must not contain Montréal-range coordinates with ≥ 4 decimals, the literal values sent, or report descriptions) and CORS tests (allow-list only, no `*`, no credentials).
- **Schema-only stub** (`tests/integration/stub_server/`, labelled in its README, docstrings and every payload): it validates requests against `openapi.yaml` and returns canned payloads with `evidence.state = simulated`. It stores nothing. Weather endpoints always return 503. The "route" it returns is a straight line explicitly marked as not walkable. Its logs follow the observability spec, with coordinates rounded to 3 dp.

## Commands run and literal results
```text
$ make config
docker compose --env-file .env.local config --quiet && echo "compose config OK"
compose config OK
[exit 0]
$ POSTGRES_USER=lint POSTGRES_PASSWORD=lint-placeholder docker compose config --services
db
[exit 0]
$ POSTGRES_USER=lint POSTGRES_PASSWORD=lint-placeholder docker compose --profile api --profile web config --services
db
api
web
[exit 0]
$ actionlint --version && actionlint
1.7.12
[exit 0]
$ make lint
cd tests/integration && uv sync --locked --quiet && uv run ruff check . && uv run ruff format --check .
All checks passed!
13 files already formatted
SKIP services/ingestion: no pyproject.toml on this branch
SKIP services/routing: no pyproject.toml on this branch
SKIP services/ml: no pyproject.toml on this branch
SKIP services/api: no pyproject.toml on this branch
SKIP apps/web: no package.json on this branch
actionlint
shellcheck -x -S warning infra/scripts/*.sh infra/db/init/*.sh
POSTGRES_USER=lint POSTGRES_PASSWORD=lint-placeholder docker compose config --quiet && echo "compose config OK"
compose config OK
[exit 0]
```

DB boot. Docker was reachable during this session, although the brief said it was paused:
```text
$ make up-db
docker compose --env-file .env.local up -d --wait --wait-timeout 180 db
 Image postgis/postgis:16-3.4 Pulled
 Network winterpath_default Created
 Volume winterpath_pgdata Created
 db The requested image's platform (linux/amd64) does not match the detected host platform (linux/arm64/v8) and no specific platform was requested
 Container winterpath-db-1 Created
 Container winterpath-db-1 Started
 Container winterpath-db-1 Healthy
exit=0
(pull-progress lines omitted; `platform: linux/amd64` was then added to compose to make the emulation explicit)

$ docker compose --env-file .env.local logs db | grep winterpath-init
db-1  | winterpath-init: database wp_data ready (postgis + role grants)
db-1  | winterpath-init: database wp_routing ready (postgis + role grants)
db-1  | winterpath-init: database wp_ml ready (postgis + role grants)
db-1  | winterpath-init: database wp_platform ready (postgis + role grants)
db-1  | winterpath-init: database wp_integration ready (postgis + role grants)

$ (per DB) select current_database(), postgis_lib_version()
wp_data|3.4.3
wp_routing|3.4.3
wp_ml|3.4.3
wp_platform|3.4.3
wp_integration|3.4.3
$ select rolname, rolcanlogin from pg_roles where rolname in (...)
wp_migrator|f
wp_reader|f
wp_writer|f

--- privilege test in wp_platform (temporary login roles, dropped afterwards) ---
 reader select: 1
expect permission denied for reader insert:
ERROR:  permission denied for table t
expect permission denied for writer DDL:
ERROR:  permission denied for schema wp_privtest

$ docker compose --env-file .env.local ps db
NAME              IMAGE                    COMMAND                  SERVICE   CREATED         STATUS                   PORTS
winterpath-db-1   postgis/postgis:16-3.4   "docker-entrypoint.s…"   db        2 minutes ago   Up 2 minutes (healthy)   127.0.0.1:55432->5432/tcp

$ make up
SKIP api: services/api/pyproject.toml not present on this branch
SKIP web: apps/web/package.json not present on this branch
+ docker compose --env-file .env.local  up -d --build --wait
 Container winterpath-db-1 Running
 Container winterpath-db-1 Healthy
exit=0
```

Bootstrap idempotency, backup and restore. Restore was tested into a scratch DB, which was then dropped. The backup went to the session scratchpad, outside the repo:
```text
$ infra/scripts/db-bootstrap.sh       -> re-ran cleanly for all 5 DBs, exit=0
$ infra/scripts/db-backup.sh wp_platform <scratch>/backups
4e69e3dae25fd5f97bfaabb283dea15f6d61a02bda11bf84556e90e8ff28af77  <scratch>/backups/wp_platform_20261110T205545Z.dump
backup written: <scratch>/backups/wp_platform_20261110T205545Z.dump
$ infra/scripts/db-restore.sh <dump> wp_restore_check
<scratch>/backups/wp_platform_20261110T205545Z.dump: OK
CREATE EXTENSION
restored <scratch>/backups/wp_platform_20261110T205545Z.dump into wp_restore_check
$ infra/scripts/db-restore.sh <dump> wp_restore_check     (second run must refuse)
<scratch>/backups/wp_platform_20261110T205545Z.dump: OK
ERROR: database wp_restore_check already exists — choose a new name (no in-place overwrite)
```

Dockerfile probe. The images were built from a throwaway scratch context with a minimal `winterpath_api` app and a stub `package.json`; neither is committed. Both images were removed afterwards:
```text
$ curl http://127.0.0.1:18105/api/v1/health
{"status":"ok","version":"probe","checks":{"uid":{"status":"ok","detail":"10001"}}}
$ docker exec wp-api-probe id
uid=10001(app) gid=10001(app) groups=10001(app)
$ curl -D - http://127.0.0.1:18175/some/spa/route
HTTP/1.1 200 OK
Cache-Control: no-cache
X-Frame-Options: DENY
<!doctype html><title>probe</title>
$ docker exec wp-web-probe id
uid=101(nginx) gid=101(nginx) groups=101(nginx)
```

Tests, run against the SCHEMA-ONLY STUB (`API_BASE_URL` unset):
```text
$ make test
cd tests/integration && uv sync --locked --quiet && uv run pytest -q
..............ssssx..s..xxx............................                  [100%]
=========================== short test summary info ============================
SKIPPED [5] .venv/lib/python3.12/site-packages/pluggy/_manager.py:183: Impossible to generate negative test cases
XFAIL test_contract.py::test_negative[GET /weather/forecast] - contract declares no 4xx (CR-PLAT-1)
XFAIL test_contract.py::test_negative[DELETE /reports/{reportId}] - contract declares no 4xx (CR-PLAT-1)
XFAIL test_contract.py::test_negative[GET /admin/reports] - contract declares no 4xx (CR-PLAT-1)
XFAIL test_contract.py::test_negative[POST /admin/reports/{reportId}/moderation] - contract declares no 4xx (CR-PLAT-1)
46 passed, 5 skipped, 4 xfailed in 6.64s
SKIP services/ingestion: no pyproject.toml on this branch
SKIP services/routing: no pyproject.toml on this branch
SKIP services/ml: no pyproject.toml on this branch
SKIP services/api: no pyproject.toml on this branch
SKIP apps/web: no package.json on this branch
[exit 0]
```
- The 5 skips are operations with no parameters or body (`/health`, `/coverage`, `/data-sources`, `/weather/current`, `/models/status`), where no invalid input can be generated.
- The 4 xfails are `strict=True`. They mark real contract gaps (CR-PLAT-1 below), and they will turn into failures once the contract is fixed, which forces removal of the markers.

Secrets and dependencies:
```text
$ gitleaks version && gitleaks git --redact --no-banner --exit-code 1 .     (after commit b6daddf)
8.30.1
3:57PM INF 6 commits scanned.
3:57PM INF scanned ~913741 bytes (913.74 KB) in 393ms
3:57PM INF no leaks found
[exit 0]

$ gitleaks dir --redact (working tree)
Finding:     POSTGRES_PASSWORD=REDACTED   RuleID: generic-api-key   File: .env.local   Line: 8
$ git check-ignore -v .env.local
.gitignore:48:.env.local	.env.local
$ git ls-files .env.local | wc -l
       0
```
The only working-tree finding is the untracked, git-ignored local dev password file. Nothing was committed.
```text
$ cd tests/integration && uv run --with pip-audit pip-audit --progress-spinner off
No known vulnerabilities found

$ scripts/check-ownership.sh platform
ownership OK for agent/platform
```

## Acceptance criteria
| Criterion (from docs/agents/platform.md) | Met? | Evidence |
|---|---|---|
| `docker compose config` valid | Yes | `make config` and `lint-infra` above; all 3 services resolve with profiles |
| `docker compose up db` healthy (or BLOCKED) | Yes | `Container winterpath-db-1 Healthy`; 5 DBs with PostGIS 3.4.3; roles and privileges verified |
| CI YAML passes `actionlint` locally | Yes | actionlint 1.7.12, exit 0, with shellcheck integration active |
| Contract tests green against stub, ready for real API | Yes (stub) | v1.1.0: 54 passed / 5 skipped / 0 xfail (was 46 / 4 xfail / 5 under v1.0.0). Real API: `API_BASE_URL=… API_LOG_FILE=… make test`; CI job already wired |
| gitleaks run on repo with literal output | Yes | History: no leaks (6 commits). Working tree: only the ignored `.env.local` |
| No secrets committed; `.env.example` names only | Yes | gitleaks; `.env.example` not edited on this branch (coordinator-owned); the CR-PLAT-2 test-harness names arrived via the v1.1.0 merge (f191fce) |
| api/web services behind profiles, skipped with explicit message | Yes | `make up` prints SKIP lines; CI prints `::notice` SKIP |
| Dockerfiles non-root; Render/Vercel/Supabase drafts; RUNBOOK | Yes | Probe build: uid 10001 / uid 101; files under `infra/` |
| Observability spec + `/health` expectations | Yes | `infra/OBSERVABILITY.md`; implemented by the stub and enforced by `test_privacy.py` |

## Blockers
| Blocker | Impact | Next step / who |
|---|---|---|
| CI has never executed on GitHub (no remote; pushing is prohibited) | Workflow has only been checked statically (actionlint); runtime behaviour of the jobs is unverified | Coordinator/user decides when a remote exists |
| Contract tests not yet run against the real API | Gap between stub and real behaviour unknown | After the Routing merge: `API_BASE_URL=http://127.0.0.1:8100/api/v1 API_LOG_FILE=<log> make test` |

## Dependencies on other agents
- **Routing/API**:
  - The ASGI entry point is assumed to be `winterpath_api.main:app`. It can be overridden with `API_APP` in the Dockerfile and the CI step. Please confirm.
  - The API must log per `infra/OBSERVABILITY.md`: JSON lines, coordinates rounded to 3 dp, no request bodies for `/reports` or `/pilot-requests`.
  - Read CORS origins from `API_CORS_ORIGINS`; never use a wildcard.
  - For the privacy test, the API's stdout must be capturable into a file (`API_LOG_FILE`).
  - Admin-route contract tests take a plaintext `API_ADMIN_TOKEN` and send it as a bearer token.
- **Frontend**:
  - Copy `infra/vercel/vercel.json` to `apps/web/vercel.json` at integration.
  - CI expects the npm scripts `lint`, `test` (Vitest, accepts `--run`), `build`, optionally `typecheck`, and a `playwright.config.*` for e2e.
  - `package-lock.json` is required (`npm ci`).
- **Data**:
  - Alembic should `SET ROLE wp_migrator` so the default privileges apply.
  - The CI python job provides a PostGIS service and `DATABASE_URL`.
  - A future ingestion Dockerfile for Render cron is not written; it needs approval first.
- **ML**: the API image installs `services/ml` if present. Artifacts are mounted read-only at `/app/models/artifacts`.

## Licensing / data notes
- No data was ingested and no external data was fetched.
- Stub payloads contain no real observations: every value is `simulated`, except the pilot bbox, which is a contract constant from architecture §3.
- Images used: `postgis/postgis:16-3.4`, `python:3.12-slim`, `node:24-slim`, `nginxinc/nginx-unprivileged:1.27-alpine`, `ghcr.io/astral-sh/uv:0.10.7`. Note that `postgis/postgis:16-3.4` is amd64-only and runs emulated on Apple Silicon.
- Render plan/region and Supabase features (`h3` availability, backup retention) are marked **unverified** in the drafts.

## Change requests (contracts)
### CR-PLAT-1 — declare error responses for invalid input (additive, minor bump) — **RESOLVED in v1.1.0 (f191fce)**
Schemathesis negative testing shows that these operations declare no status for schema-invalid requests. Any conforming implementation, including FastAPI's default 422, therefore produces an undocumented status:

| Operation | Invalid input example | Declared today | Proposed addition |
|---|---|---|---|
| `GET /weather/forecast` | `?hours=0` | 200, 503 | `400`, `422` |
| `DELETE /reports/{reportId}` | non-uuid id, missing `X-Deletion-Token` | 204, 404 | `400`, `422`, `429` |
| `GET /admin/reports` | `?status=bogus`, `?limit=0` | 200, 401 | `400`, `422` |
| `POST /admin/reports/{reportId}/moderation` | bad body / non-uuid id | 200, 401, 404 | `400`, `422` |
| `POST /pilot-requests` | malformed JSON / missing body | 201, 422, 429 | `400` (under v1.0.0 the stub used 422 here; since v1.1.0 it returns 400 for malformed bodies) |

### CR-PLAT-2 — `.env.example` names (coordinator-owned) — **RESOLVED in v1.1.0 (f191fce)**
Add names only, for the test harness: `API_BASE_URL`, `API_LOG_FILE`, `API_ADMIN_TOKEN` (plaintext, tests/local only), `API_APP`, `STUB_PORT`, `STUB_ADMIN_TOKEN`, `CORS_ALLOWED_ORIGIN`.

## Review readiness
Ready for review. Notes for the coordinator:
- `make down` (from any worktree) stops the **shared** DB container for all agents. `down -v` deletes the shared volume; the runbook says to announce it first.
- The db container `winterpath-db-1` is currently **running and healthy** on 127.0.0.1:55432, so other agents can use it now.
- Nothing was pushed, deployed, or provisioned. No cloud resources were created.
