# Island of Montréal coverage (v2) — status and measurements

**Status (2026-11-13): implemented and tested locally. NOT deployed.** Production still serves the downtown pilot. Everything below marked "local" was measured on the development Mac, not on Render.

## Why the app was downtown-only
- Production holds only the pilot graph (6,807 nodes, 16,296 directed edges) for the bbox `-73.588,45.496,-73.562,45.513`.
- That bbox was hard-coded in the API (`PILOT_BBOX`: route, map and report validation), in the 311 and closures loads, and in the web map (initial view, mask, point hints).
- The island graph could not simply be loaded: reading 650,920 edges from PostGIS at boot needs more than 1 GiB (Render Free has 512 MB), and every request asked the risk layer about every edge.

## What the island graph is
Built by the data pipeline (`wp-ingest`, `osm/island.py`) from the Geofabrik Québec extract of 2026-11-08 (OpenStreetMap, ODbL), clipped to the agglomeration's land. No connectivity is invented.

| Measure | Value |
|---|---|
| Nodes / directed edges | 257,542 / 650,920 |
| Network length (undirected) | 10,207.7 km |
| Largest connected component | 98.15 % of foot-legal edges; 97.07 % of nodes |
| Other components | 1,777 small sub-networks, not used for routing (`/coverage` lists the 200 largest) |
| Node extent | `-73.970,45.401,-73.477,45.707` |
| Other islands | Included only where a mapped pedestrian link connects them to the main island (87 isolated networks dropped) |

## How it is served
- **Prebuilt graph file.** `python -m winterpath_api.graph_artifact` writes one `.npz` (NumPy arrays only, loaded with `allow_pickle=False`, SHA-256 pinned by `ROUTING_GRAPH_ARTIFACT_SHA256`). Island: 180 MB; loads in under 0.1 s locally. The file also carries the coverage name, bbox and outline, and the edge → H3 risk-cell index. The API then needs no graph tables in the database.
- **Compiled search** (`ROUTING_FAST_SEARCH=true`): SciPy Dijkstra over the same arcs and weights, with an exact growing radius. Same optimal cost as the Python search; equal-cost ties may resolve differently.
- **Array risk lookup.** One `cell_risk` call per H3 cell every 5 minutes instead of one call per edge per request. An edge with any unknown cell is unknown.
- **Hazards.** `HAZARD_CACHE_SECONDS` reuses the closure / 311 list and the matched edges between requests.
- **Web.** The map takes its area from `GET /coverage`.

## Measurements (local, full API, real production risk scores read-only)
| Trip length (straight line) | n | Routed | p50 | p95 |
|---|---|---|---|---|
| 0.3–1.5 km | 40 | 39 | 32 ms | 42 ms |
| 2–5 km | 40 | 38 | 75 ms | 156 ms |
| 8–15 km | 40 | 39 | 164 ms | 239 ms |
| 20–40 km | 40 | 40 | 245 ms | 324 ms |

- The 4 failures were `OFF_NETWORK`: a random node outside the main component.
- All 21 pairs between Downtown, NDG, Saint-Laurent, Pointe-Claire, Lachine, Anjou and Pointe-aux-Trembles routed (5.6 km to 39.2 km).
- Same optimum as the reference search on 126 island pairs and on the golden test cases.
- API memory on macOS: about 400 MiB resident after load tests.

### Docker, Render-Free-sized (`--cpus=0.1 --memory=512m`, 2026-11-13)
Image built from `infra/docker/api.Dockerfile` with the release asset; production scores read-only; 160 paced random trips (40 per class), one worker.

| | arrays copied into RAM | `ROUTING_GRAPH_ARTIFACT_MMAP=true` |
|---|---|---|
| Graph loaded after container start | 31 s | 25 s (first `200` from `/health` at 47 s) |
| Non-reclaimable memory, idle → after load test | 345 → 409 MiB | 178 → 239 MiB |
| Peak container memory | 512 MiB (at the limit) | 374 MiB |
| OOM kills | 0 | 0 |
| Short 0.3–1.5 km, p50 / p95 / max | 0.65 / 2.6 / 7.4 s | 0.64 / 1.6 / 12.8 s |
| Medium 2–5 km | 1.3 / 2.1 / 3.8 s | 1.3 / 3.2 / 4.1 s |
| Long 8–15 km | 3.6 / 6.5 / 8.1 s | 3.1 / 5.4 / 6.3 s |
| Cross-island 20–40 km | 4.6 / 8.3 / 12.0 s | 5.1 / 7.2 / 8.1 s |

- 156 of 160 trips routed in both runs; the other 4 were `OFF_NETWORK` (random point more than 75 m from the network).
- Without the memory map the container reached its limit, so the island is only viable on 512 MB with `ROUTING_GRAPH_ARTIFACT_MMAP=true`.
- The 12.8 s maximum was the first request after boot. The web client times out at 15 s.
- This is a local container, not Render: disk speed, CPU throttling and concurrent users there are **not measured**.

## Winter-risk coverage
- Risk scores exist for 2,930 H3 cells; the island network touches 4,268. Edges outside scored cells are reported as unknown, never as low risk.
- Example (2026-11-13 scores): Downtown → Anjou 0 % unknown; Downtown → Pointe-Claire 42–43 % unknown; a Pointe-Claire map view is 100 % unknown.
- Closures and 311 aggregates in production are still loaded for the pilot bbox only. The island sets exist locally (`--region island`: 1,970 closures, 576 blocking).

## Live since 2026-11-13
- API (Render, commit `fa4fdbe`) serves the island graph from the `graph-island-v1` release file, memory-mapped. Web (Cloudflare Pages, commit `60d5660`) built with `VITE_COVERAGE_BBOX=-73.97,45.401,-73.477,45.707`.
- Live checks at 16:30 UTC: ten district routes (Downtown, NDG, Saint-Laurent, Pointe-Claire, Lachine, Anjou, Pointe-aux-Trembles) all `200`, 5.6–39.2 km, 1.3–4.4 s warm; two requests after idle took 11–13 s. Render reported 257 MiB memory after these checks and no restart.
- Closures job now loads the island set (`--region island`): 1,729 closures on the first run. Entraves is a Ville de Montréal dataset; linked cities such as Pointe-Claire publish nothing there. 311 aggregates were already agglomeration-wide.
- Share of each route without winter-condition data in these checks: 0 % (Downtown → Anjou) to 70 % (Pointe-Claire → Lachine). The cards state the percentage.
- Not measured: behaviour with several simultaneous users on Render.

## Instability found after go-live (2026-11-13, 16:40–16:55 UTC)
Render restarted the instance three times after `/health` timed out. Route-only tests had not shown it; a browser also loads overlays, and the island closures (1,729) had just been loaded. Causes and fixes:

- **Closures re-matched every minute.** The hazard list was cached per clock minute and matches were remembered per object, so each new minute redid all spatial matching (35–65 s at 0.1 CPU). Now: one list per `HAZARD_CACHE_SECONDS` period, and matches are remembered by geometry.
- **Unaligned memory-mapped arrays.** `np.savez` does not align members; NumPy copied the whole grid index on every lookup (659 µs instead of 2 µs). Now arrays up to 16 MiB that are unaligned are read into memory; the large coordinate blocks stay mapped.
- **Segments overlay built an `Edge` for every street in view** to test walkability (about 45,000 for a downtown view) before returning 500. Now filtered on the graph's array.
- **First request after a restart** paid for the initial matching. `ROUTING_WARMUP=true` does it before the server accepts traffic.

Docker at 0.1 CPU / 512 MB, before → after (warm-up not included in this run): `/map/segments` 19–32 s → 1.3–2.5 s; first route after boot 46–67 s → 15.6 s; repeat route 2 s → 1.4 s; non-reclaimable memory after these requests 319 MiB. A mixed browser-like load test of the final build was **not completed** (Docker Desktop was paused).

Fix deployed 2026-11-13 18:33 UTC (commit `62fd988`, `HAZARD_CACHE_SECONDS=300`, `ROUTING_WARMUP=true`). Live mixed load right after (14 rounds of route + segments + hazards in parallel, `/health` every 5 s): all `200`; route p50 4.4 s / max 7.0 s, segments 1.7 / 2.6 s, hazards 2.1 / 3.0 s, health 1.1 / 2.4 s (Render's limit is 5 s). No restart in the three minutes observed; memory 344 MiB and still rising at the end of the run. Longer-term stability is **not yet observed**.

## Aligned graph file (v2, built 2026-11-13, in production since 2026-11-14 01:14 UTC)
`compact_io.save` now writes every array on a 64-byte file offset (still an ordinary `.npz`, byte-for-byte reproducible). The v1 island graph re-saved this way: 188,557,261 bytes, SHA-256 `2f40b5e4b540d162a95e11d5c878373e7e1b25fe8cf17592a8baad0e22c06bb9`, all 49 members identical to v1.

- Memory: with v1 the memory-mapped load copies 61 MiB of unaligned arrays into RAM; with v2 it copies none.
- Start-up: the graph load itself goes from about 27 ms to 12 ms on the development Mac. **It does not shorten cold starts in any way a visitor would notice.** The 43 s cold start measured on Render at 19:35 UTC was: about 23 s before the graph was loaded (Render waking the instance, Python imports), 8 s to open the server, 4.6 s warm-up, 6.6 s before the first answer.

Published as GitHub Release `graph-island-v2` (downloaded copy matches the SHA-256). Render deploy `dep-dbrrarmk1f9s73ff2lfg` of `cdd9514`: `graph_loaded` with 257,542 nodes / 650,920 edges, `mmap: true`; warm-up 3.8 s (823 hazards).

- Live mixed load right after the deploy (14 requests of each kind, all 200): route p50 3.5 s / max 4.9 s, segments 1.3 / 2.6 s, hazards 1.2 / 2.4 s, health 0.7 / 1.6 s.
- Memory on Render after that load: peak 382 MiB, then 337 MiB. The same load on v1 settled at 345–347 MiB, so the saving seen in production so far is about 10 MiB, not the 61 MiB measured locally (memory-mapped pages that have been read still count towards the container).
- **Memory growth seen on v1:** the instance that had run since 18:33 UTC was at 446 MiB of 512 between 00:35 and 01:09 UTC (360 MiB at 00:30). Cause (found 2026-11-14): not a leak and not slow growth. That instance had cold-started at 00:26 UTC; one browser session then panned the map for 8 minutes (about 190 `/map/segments` and 190 `/hazards` requests, up to 35 of each per minute) and memory rose from 296 to 446 MiB, then stayed flat once the panning stopped. Reproduced locally (macOS, production settings and database, 100 segment requests): `/hazards` alone adds nothing; `/map/segments` adds about 95 MiB. Python objects still alive afterwards: a few MiB (the bounded edge cache). The rest is (a) about 40 MiB of graph file pages read for the first time (memory-mapped, the OS can drop them) and (b) heap freed by finished requests but not returned to the OS, which grows with the number of segment requests running at once: 10 MiB at start, 20 MiB with one at a time, 62 MiB with six at a time. Not yet measured on Linux (Docker Desktop paused), where the allocator differs. Not fixed: more simultaneous map users could push the instance past 512 MiB.
- Rollback to v1: set `ROUTING_GRAPH_ARTIFACT_URL` / `ROUTING_GRAPH_ARTIFACT_SHA256` back to the `graph-island-v1` values and redeploy.

## Known limits
- No address search: no permitted geocoder is configured (public Nominatim is not allowed). Points are set on the map, by coordinates, or by "Use my location".
- A point more than 75 m from the walkable network is refused (`OFF_NETWORK`), which is more common in parks and large lots.
- The coverage outline joins islands closer than about 800 m into one polygon, because the API contract allows a single polygon. It is a service-area outline, not a land map.
- Map overlays (segments, hazards) load only when zoomed in (bbox area limit 0.0025 deg²).
