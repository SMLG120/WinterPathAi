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

## Known limits
- No address search: no permitted geocoder is configured (public Nominatim is not allowed). Points are set on the map, by coordinates, or by "Use my location".
- A point more than 75 m from the walkable network is refused (`OFF_NETWORK`), which is more common in parks and large lots.
- The coverage outline joins islands closer than about 800 m into one polygon, because the API contract allows a single polygon. It is a service-area outline, not a land map.
- Map overlays (segments, hazards) load only when zoomed in (bbox area limit 0.0025 deg²).
