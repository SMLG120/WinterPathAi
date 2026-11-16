# Agent report — cache (Agent C)

Status: **READY FOR REVIEW** · branch `agent/cache` · base `e581535`
Commits: `da8a2dc` (API response caches), `7a650c8` (web keys, abort, freshness). Agent C stopped at a
usage limit before reporting; the lead verified and wrote this report on 2026-11-16. Not pushed, merged or deployed.

## What changed
**API (`services/api`)**
- `cache.py`: thread-safe LRU+TTL response caches bounded by entries and bytes; single flight for identical
  concurrent misses; salted key digests in logs (no raw coordinates); `API_RESPONSE_CACHE=false` kill switch.
- `/map/segments`: key = graph version + risk snapshot version + normalised bbox + page; the two-build cap stays;
  a request whose client disconnected while queued is not built.
- `/hazards`: key = hazard-list version; STR-tree bbox selection per list version.
- `/routes/compare`: key = exact points + every preference + now-vs-explicit departure + graph, risk,
  hazard-list and source-freshness versions. A leave-now answer lives ≤ 60 s and never past the next hazard
  validity change; `request_id` and `weather_context` are per request. Evidence states pass through unchanged.

**Web (`apps/web/src/api`)**
- `spatialKey.ts`: viewport widened outward to a power-of-two grid (≈ 1/8 of the view) so small pans share a key.
- `queries.ts`: AbortSignal on every query; overlays staleTime 2 min, gcTime 5 min, ≤ 12 unobserved areas per
  overlay; identical in-flight compares share one request; hooks expose a lazy freshness getter.
- `freshness.ts`: `freshnessOf`/`withFreshness` → `idle|loading|fresh|cached|stale|previous-area|unavailable`,
  `fetchedAt`, `ageMs`, `fromCache`, `isRefreshing`, `error`.
- `resilientFetch.ts`: a cancelled request stops retrying immediately; cold-start backoff otherwise unchanged.

## Tests (literal, 2026-11-16)
```
services/api$ uv run ruff check .          → All checks passed!
services/api$ uv run ruff format --check . → 42 files already formatted
services/api$ uv run pytest -q             → 152 passed, 15 skipped, 1 warning in 12.75s
apps/web$ npm run typecheck                → exit 0
apps/web$ npm run lint                     → exit 0
apps/web$ npx vitest run
 Test Files  22 passed (22)
      Tests  178 passed (178)
```
Skips are environmental: 13 × `DATABASE_URL not set` (PostGIS; Docker Desktop was paused), 2 × ML per-day
score tables absent (git-ignored parquet) — none caused by this branch.

## Benchmark (local Mac, NOT Render)
Island graph v2 release asset (sha256 `2f40b5e4…6bb9`), memory-mapped, fast search, warm-up on, one uvicorn worker,
`MALLOC_ARENA_MAX=2`, in-memory stores (**no risk layer, no DB hazards** → hazards are near-empty lists).
Load: 3 concurrent panning clients × 40 viewports (zoom ≈ 16, pans 5–20 % of the view) on `/map/segments` and
`/hazards`, plus 15 route compares (3 downtown pairs × 5). Script: lead's scratchpad `bench_cache.py`.

Raw viewports (what the old client sent):
```
cache_off segments n=120 p50=   79.3 ms p95=  133.6 ms max=  169.9 ms
cache_off hazards  n=120 p50=   17.6 ms p95=   54.7 ms max=   87.5 ms
cache_off compare  n= 15 p50=  174.8 ms p95=  234.3 ms max=  267.1 ms
cache_off wall=4.0s rss_idle=189 MiB rss_peak=247 MiB rss_end=219 MiB   cpu_time=0:05.50
cache_on  segments n=120 p50=   79.8 ms p95=  155.7 ms max=  204.1 ms
cache_on  hazards  n=120 p50=    9.7 ms p95=   54.4 ms max=  109.6 ms
cache_on  compare  n= 15 p50=   30.3 ms p95=  219.3 ms max=  395.8 ms
cache_on  wall=4.2s rss_idle=194 MiB rss_peak=247 MiB rss_end=222 MiB   cpu_time=0:05.16
```
Viewports snapped like `spatialKey.ts` (what the new client sends):
```
snap_cache_off segments n=120 p50=   79.2 ms p95=  160.9 ms max=  243.8 ms
snap_cache_off hazards  n=120 p50=   14.7 ms p95=   66.1 ms max=  214.2 ms
snap_cache_off compare  n= 15 p50=  171.5 ms p95=  283.1 ms max=  449.2 ms
snap_cache_off wall=4.5s rss_idle=184 MiB rss_peak=234 MiB rss_end=223 MiB   cpu_time=0:05.59
snap_cache_on  segments n=120 p50=   67.3 ms p95=  121.1 ms max=  196.1 ms
snap_cache_on  hazards  n=120 p50=    3.6 ms p95=   29.5 ms max=   61.6 ms
snap_cache_on  compare  n= 15 p50=   23.0 ms p95=  210.4 ms max=  314.9 ms
snap_cache_on  wall=3.3s rss_idle=154 MiB rss_peak=243 MiB rss_end=225 MiB   cpu_time=0:04.49
```
Reading:
- Repeated route compares: p50 ≈ 172 → 23–30 ms (12 of 15 are cache hits). p95 is the first, uncached call of a pair.
- Segments: server cache alone does not help random pans (keys rarely repeat); with client snapping p50 79 → 67 ms
  and p95 161 → 121 ms. The bigger win is in the browser (TanStack reuses the snapped key without any request), not measured here.
- Peak RSS unchanged (234–247 MiB); the caches' byte bounds hold. CPU time −20 % with snapping + cache.
- **Not measured:** Render (0.1 CPU, 512 MB) or the Docker equivalent (Docker Desktop paused); PostGIS hazards/risk;
  browser-side request counts.

## For integration
- D's `useOverlayQueryStatus` adapter (`agent/mapux`, `src/features/map/dataStatus.ts`) reads TanStack fields;
  map C's `freshnessOf` states onto it at integration (fresh/cached/stale/unavailable already align).
- No contract change: no new response headers or fields.
