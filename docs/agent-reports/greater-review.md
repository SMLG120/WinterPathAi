# PR #2 code review — fixes (lead, 2026-11-17)

`/code-review` on PR #2 reported 9 findings. The lead checked each against the code and fixed 1–4.

| # | Finding | Fix | Test |
|---|---|---|---|
| 1 | `region.py`, `island.py` and the coverage doc claimed the island graph is unchanged / byte-identical, but the seasonal rule changes it (7 ways + 391 reachable only through them) | claims scoped to policy `v1.6.0`; the seasonal change and the need to rebuild and revalidate are stated | docs only |
| 2 | `links.py` docstring and coverage doc said the graph does not evaluate `seasonal` | now say `seasonal=*` without winter is excluded; `*:conditional` still verbatim only | docs only |
| 3 | `wp-ingest fixed-links` ignored `--refresh` / `--force` | passed to `sda.run` and `geofabrik.fetch` | `test_fixed_links_passes_refresh_and_force` (2 cases) |
| 4 | `graph_from_processed` crashed on a non-ISO `osm_snapshot` / `finished_at` | same `_looks_like_dt` guard as the fixture provider: unknown freshness, snapshot kept as text | `test_unparseable_snapshot_is_unknown_freshness_not_a_crash` |

Not changed: SDA GPKG re-hashed on every run (speed), duplicated parsing in `graph_from_processed`
(memory for Stage 2), 0.03° neighbour pre-filter in degrees, seed-only neighbour check in
`links.structures`. Contract edits were the coordinator's, user-approved ("do (a), update the contract").

## Results (local, 2026-11-17)
- `services/ingestion`: `ruff check` → All checks passed!; `ruff format --check` → 37 files already formatted; `pytest -q` → 92 passed, 10 skipped, 2 warnings
- `services/api`: `ruff check` → All checks passed!; `ruff format` → 41 files left unchanged; `pytest -q` → 133 passed, 15 skipped, 1 warning
