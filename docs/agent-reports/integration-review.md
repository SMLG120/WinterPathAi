# PR #1 code review — fixes (lead, 2026-11-17)

`/code-review` on PR #1 reported 10 findings. The lead verified the five correctness findings against
the code (the parser one by running it) and fixed them; the five cleanups are not in this change.

| # | Finding | Fix | Test |
|---|---|---|---|
| 1 | `coords.ts`: French ordinal `3e` read as "3° East" (`"200 3e"` → out_of_range; `"45 3e"` → lat 45, lon 3) | an integer written straight against `e` is an ordinal → address query; `3 E`, `3°E` still parse | `coords.test.ts` (10 cases) |
| 2 | `staticProvider.ts`: manifest kept for the tab's life; after an index redeploy the old `v/<build>/` is deleted, search stays unavailable | manifest fetched with `cache: 'no-cache'`; a `missing` shard under an already-loaded manifest drops manifest + shard cache and retries once | `staticProvider.test.ts` (2) |
| 3 | `useSegments`: only the first page (500) of `/map/segments` was used; grid-snapped boxes (≤1.56× area) made truncation likelier | `fetchAllSegments`: limit 1000, follows `next_cursor` up to 5 pages; `next_cursor` stays set if capped | `segmentsPaging.test.ts` (2) |
| 4 | `hazards.py`: serial read after the DB read, so concurrent misses could share a version for different lists | bucket miss + read under a lock; serial taken before the read (one DB read per expired bucket) | `test_db_hazard_list_concurrent_misses_read_once_and_share_one_version` |
| 5 | `map.py` process-wide STR-tree cache keyed by per-repository versions | versions include a process-unique repository id | `test_hazard_list_versions_are_unique_per_repository` |

Not changed: hazard overlay paging (`/hazards`) still reads one page; cleanups (status-chip freshness
duplication, dead `endpoints.ts` fields, duplicated serializers, coverage outline re-parse, re-search
after choosing a result).

## Results (local, 2026-11-17)
- `apps/web`: `vitest run` → Test Files 30 passed (30), Tests 287 passed (287); `npm run lint` exit 0; `npm run typecheck` exit 0
- `apps/web`: `playwright test -c playwright.search.config.ts` → 20 passed (55.0s); `playwright test` → 147 passed (5.6m)
- `services/api`: `ruff check` → All checks passed!; `ruff format --check` → 43 files already formatted; `pytest -q` → 157 passed, 15 skipped, 1 warning
