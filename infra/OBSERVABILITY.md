# Observability spec (v1)

Applies to `services/api` and ingestion jobs. Implemented by the stub in
`tests/integration/stub_server/` as a reference; enforced by `tests/integration/test_privacy.py`.

## 1. Structured logs
One JSON object per line on stdout. UTF-8. No multi-line stack traces in production
(exceptions are logged as `error.type` + `error.message`; full traces only at `debug` locally).

| Field | Type | Required | Notes |
|---|---|---|---|
| `ts` | string | yes | RFC 3339 UTC, ms precision |
| `level` | string | yes | `debug` `info` `warning` `error` |
| `event` | string | yes | snake_case, stable (`http_request`, `route_computed`, `ingest_run_finished`, …) |
| `service` | string | yes | `api`, `ingestion`, `ml` |
| `version` | string | yes | same as `/health.version` |
| `request_id` | string | for HTTP | echoed in `X-Request-ID` response header and in `Error.request_id` |
| `method`, `route`, `status`, `duration_ms` | | for `http_request` | `route` is the **template** (`/api/v1/reports/{reportId}`), never the raw path/query |
| `origin_3dp`, `destination_3dp` | `[lon, lat]` strings | optional | rounded to **3 decimals** (~100 m). Alternatively `origin_h3_r7`. |
| `ingest_run_id`, `source_id`, `record_count` | | for ingestion | |

### Never log
- Raw precise coordinates (> 3 decimal places), from any field, query string or body.
- Request bodies of `/reports` and `/pilot-requests` (description, e-mail, name).
- `Authorization`, `X-Deletion-Token`, deletion tokens, cookies, `DATABASE_URL`, API keys.
- Client IP addresses (rate limiting uses the salted, daily-rotated hash in memory only).

Uvicorn's access log is disabled in the API image (`--no-access-log`) because it prints raw
query strings; nginx in the web image runs with `access_log off` for the same reason.

### Test
`tests/integration/test_privacy.py` sends requests with 6-decimal coordinates and fails if any
log line contains a Montréal-range coordinate with ≥ 4 decimals or the literal values sent.
It needs the API's log output via `API_LOG_FILE` (set automatically for the stub).

## 2. `/health` expectations
Contract: `Health { status: ok|degraded|down, version, checks: {name: {status, detail}} }`.

| Check key | `ok` | `degraded` | `down` | `disabled` |
|---|---|---|---|---|
| `database` | `SELECT 1` < 500 ms | slow (> 500 ms) | unreachable | — |
| `graph` | pilot graph loaded, edge_count > 0 | loaded, largest_component_share < 0.9 | not loaded | — |
| `risk_layer` | model enabled and artifact checksum matches registry | heuristic only | artifact missing/corrupt | ML disabled by gate |
| `weather` | last ECCC success < 2 h | 2–24 h | > 24 h / never | — |
| `sources` | all `active` | any `stale` | — | — |

Overall `status` = worst of required checks (`database`, `graph`); optional checks can only
degrade. `/health` must respond < 1 s, must not call upstream providers synchronously, and
must return HTTP 200 for `ok` and `degraded` (load balancers use it). `detail` strings must
not contain hostnames, credentials or stack traces.

## 3. Metrics (later, no paid APM in v1)
Derive from logs: request count/latency per `route` (p50/p95), 4xx/5xx rate, route-compare
p95 (target < 2 s — measured, not claimed), ingest run success/failure per source.
