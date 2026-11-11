# Agent report — platform

- **Status:** READY FOR REVIEW (harness verified against the stub **and the live merged real API**; CI never run on GitHub — no remote, nothing pushed)
- **Branch / SHA:** agent/platform — fast-forwarded to `integration/winterpath` 2d37f32 (d04da54 + one `.env.example` commit); this checkpoint's harness changes and report are in the commit after it. Earlier: 5ce5c9f (v1.1.0 adoption), b6daddf (original).
- **Contract:** v1.5.0 (merged; `docs/contracts/` not edited on this branch)
- **Date (UTC):** 2026-11-11

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
| API-NULL-1 (null accepted for non-nullable optional fields) | Routing fixes `schemas.py`; Platform then removes both API-NULL-1 markers |
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
