# Agent 2 — Routing & Backend Engineer

Branch `agent/routing` · worktree `../winterpath-routing` · API port 8102, DB `wp_routing`.
**Owns:** `services/api/`, `services/routing/`, `docs/agent-reports/routing.md`.
**Read first:** `CLAUDE.md`, `docs/architecture.md` §5–6, `docs/contracts/*`.

## Dependencies & mocks
- Graph: until `data/fixtures/pilot_mini/` exists on `integration/winterpath`, write your own minimal fixture in `services/routing/tests/fixtures/` marked synthetic (`"simulated": true`) — topology toy graphs are fine for algorithm tests.
- Risk: `NullRiskProvider` (all `unknown`) until ML's `RiskProvider` interface lands. Define the protocol locally exactly as in integration-rules §2 (`winterpath_ml.inference.RiskProvider`: `edge_risk(edge_ids, at) -> dict[edge_id, RiskEstimate]`) via a thin adapter.
- DB: `PostgisGraphProvider` coded against data-model.md; integration test skipped (with reason) if DB unavailable.

## Steps
1. `services/routing` package `winterpath_routing` (pure Python, NetworkX): graph loading, edge filtering (hard exclusions), cost functions (seconds, ≥0), Dijkstra shortest-distance & shortest-time, A* (haversine/walk-speed admissible heuristic) for winter-aware, snapping origin/destination to nearest routable edge (reject if >75 m from network), step-list generation, explanation codes.
2. Unknown risk → documented `unknown_penalty_s` (configurable, default small positive), counted in `unknown_share`; never treated as low risk.
3. `step_free` profile: exclude edges with `step_free is not True`. If no route → 404 `NO_ROUTE` with explanation, not a fallback that violates the constraint.
4. `services/api` package `winterpath_api` (FastAPI): every v1 endpoint in openapi.yaml with Pydantic models matching the schema (generate with `datamodel-code-generator` or hand-write + contract test), error envelope, bbox validation and size limit, pagination cursors, CORS from env, rate limiting, admin bearer auth (hash compare), structlog JSON logs with coordinates rounded to 3 dp.
5. Weather endpoints call an ECCC adapter interface; when no adapter/data → 503 `UPSTREAM_UNAVAILABLE`, never invented values.
6. `/reports` + moderation + deletion with in-memory repository behind an interface, plus a PostGIS repository.
7. Latency test: p50/p95 for 100 random pilot OD pairs on the fixture/real graph — report measured numbers.

## Acceptance criteria
- Shortest-path correctness on hand-checked toy graphs (Dijkstra = A* cost; prohibited edges never used; closures excluded; step-free hard).
- `/routes/compare` returns schema-valid responses (validated against openapi.yaml in tests); 422 outside coverage; 400/422 on bad input.
- No endpoint returns fabricated weather/risk; unknown flows through as `unknown`.
- `pytest services/routing services/api` green; ruff clean.

## Stop conditions
Contract ambiguity → change request in your report, continue elsewhere. Do not edit `docs/contracts/`.

## Completion report — `docs/agent-reports/routing.md`
Status · SHA · files · literal test output · latency measurements (environment described) · contract deviations/change requests · blockers · review readiness.
