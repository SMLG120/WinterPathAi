# Agent 1 — Geospatial Data Engineer

Branch `agent/data` · worktree `../winterpath-data` · ports/DB: see integration-rules §4 (`wp_data`, API 8101).
**Owns:** `data/`, `db/`, `services/ingestion/`, `docs/agent-reports/data.md`. Owns all Alembic migrations.
**Read first:** `CLAUDE.md`, `docs/architecture.md`, `docs/contracts/*`, `docs/data-sources-and-licenses.md`.

## Dependencies & mocks
- PostGIS via Docker. **Docker Desktop is currently paused** — if `docker info` fails, build the pipeline + tests against GeoPackage/in-memory GeoPandas and mark DB steps BLOCKED in your report. Do not fake migration success.
- Nobody depends on you for code imports; Routing and Frontend depend on your **fixture** `data/fixtures/pilot_mini/` — produce it first.

## Steps
1. Scaffold `services/ingestion` (uv, Python 3.12, package `winterpath_ingestion`, ruff, pytest).
2. Resolve "Still to verify" items in the data-sources doc (Overpass/Geofabrik policy, 311 methodology incl. location precision and winter `ACTI_NOM` categories). Record findings in your report as a change request — do not edit the doc.
3. OSM pedestrian graph for `PILOT_BBOX` with OSMnx (custom filter: footway, sidewalk, path, pedestrian, crossing, steps, living_street, residential/tertiary/secondary/primary **only where walking is legal** — exclude `foot=no`, `access=private|no`, motorways/trunk). Custom User-Agent from `HTTP_USER_AGENT`; cache raw responses in `data/raw/` (git-ignored); record snapshot timestamp + checksum.
4. Build stable `node_id`/`edge_id` per data-model; project to EPSG:32188 for `length_m`; repair geometries; compute components; record gaps.
5. Voirie sidewalk polygons: download GeoJSON ZIP, checksum, normalise CRS, spatial-join to edges (enrichment only, never connectivity). Report match rates.
6. Entraves: ingest closures + impacts; build `sidewalk_blockedtype → blocks_passage` mapping table from the actual distinct values (document every value; unknown values → `null`).
7. 311: stream CSVs, filter winter-relevant categories (documented list), aggregate to H3 res-9 × day × category. Never persist raw rows outside `data/raw/`.
8. ECCC: ingest `climate-hourly` for the nearest Montréal station(s) for the training window + `swob-realtime` adapter. Record station ids.
9. Alembic migrations for all `wp.*` tables + GiST indexes + roles. Migration up/down tests.
10. Export `data/fixtures/pilot_mini/` (≤200 real edges near McGill, `edges.geojson`, `nodes.geojson`, `ATTRIBUTION.md`, `metadata.json` with snapshot, bbox, `"simulated": false`).
11. Make every pipeline idempotent (same input checksum ⇒ no-op) and atomic (staging + swap).

## Acceptance criteria
- Pilot graph built from real OSM; node/edge counts, largest-component share, and gap list recorded.
- Edge IDs stable across two builds of the same snapshot (test).
- Topology tests: no edge with `foot_access in (no, private)`; all lengths > 0 and within 1% of 32188 recomputation; no duplicate IDs; crossing nodes carry crossing metadata where tagged.
- Migrations apply and roll back cleanly on PostGIS (or BLOCKED with reason).
- Attribution present for every ingested source.

## Tests
`pytest services/ingestion` — fixtures under `services/ingestion/tests/fixtures/` (small, real extracts or plainly labelled synthetic).

## Stop conditions
Licence ambiguity on a source → do not ingest it; report. Upstream download failure → retry with backoff ≤3, then report; never substitute synthetic data silently.

## Completion report — `docs/agent-reports/data.md`
Status · branch + SHA · files changed · commands run with literal output (tests, counts) · graph statistics · source verification findings / change requests · blockers (impact, next step) · licence notes · review readiness.
