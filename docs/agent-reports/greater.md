# Agent B (greater): Stage 1 report

Scope: island + Laval + Longueuil, local only. Results and tables: `docs/GREATER_MONTREAL_COVERAGE.md`.

* Island regression: processed GeoJSON identical to Wave 1 after blanking `ingest_run_id`; artifact
  not byte-identical to published v2 (PostGIS-sourced `updated_at`/ordering); all graph content
  equal (id-ordered comparison, 0 differences except `updated_at`).
* Stage 1 artifact 250,021,231 bytes (1.33x island); post-test RSS 382 vs 294 MiB (1.30x) on a Mac.
  Projection above 400 MiB: not proposed for shipping; partitioning recommendation in the coverage doc.
* Longueuil's only foot link is OSM way 852435426 tagged `seasonal=spring;summer;fall` (graph does
  not evaluate it).

## Change request (for the coordinator)

A coverage made of several areas (island + municipalities, or per-region partitions) needs
`/coverage` to return a MultiPolygon (docs/contracts/openapi.yaml). Not edited here.

## Test output

services/ingestion: ruff check "All checks passed!"; ruff format --check "37 files already formatted"; pytest "79 passed, 10 skipped, 2 warnings in 1.90s".
services/api: ruff check "All checks passed!"; ruff format --check "41 files already formatted"; pytest "132 passed, 15 skipped, 1 warning in 7.83s".
