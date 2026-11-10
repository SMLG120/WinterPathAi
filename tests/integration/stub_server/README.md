# ⚠️ SCHEMA-ONLY STUB — not the WinterPath API

Owned by the Platform agent. Exists only so `tests/integration/` can run before
`services/api` is merged.

- Validates every request against `docs/contracts/openapi.yaml` (params, headers, JSON body)
  and answers 400 (malformed) / 422 (contract violation, `BBOX_TOO_LARGE`, `OUTSIDE_COVERAGE`).
- Returns canned payloads from `fixtures.py`. Every `evidence.state` is **`simulated`** and
  every human-readable string says STUB/SIMULATED. The "route" is a straight line between the
  endpoints — **not a walkable path**. Weather endpoints always return 503.
- Stores nothing. `/reports` returns a receipt but persists nothing; deletes/moderation → 404.
- Admin routes accept `Authorization: Bearer $STUB_ADMIN_TOKEN` (default
  `stub-admin-token-not-a-secret`, a test-only value).
- Logs one JSON line per request (format: `infra/OBSERVABILITY.md`), coordinates rounded to 3 dp.

Run: `cd tests/integration && uv run python -m stub_server` → http://127.0.0.1:8105/api/v1

After integration, run the same tests against the real API:
`API_BASE_URL=http://127.0.0.1:8100/api/v1 API_LOG_FILE=<api log> make test`
