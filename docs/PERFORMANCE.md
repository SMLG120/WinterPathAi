# Performance

All numbers below were measured; none are estimates. Load-test method: sequential `POST /routes/compare` with random origin and destination points inside the pilot bbox (seed 7), a random profile, and EN/FR.

## /routes/compare latency

| Environment | Build | n | Status codes | p50 | p95 | max |
|---|---|---|---|---|---|---|
| Local Mac, full graph | pre-`7bcb7b8` | 100 | — | 57 ms | 199 ms | — |
| Docker `--cpus=0.1 --memory=512m` (Render Free emulation) | `0e9adef` | 100 | 85×200, 14×422, 1×404 | 913 ms | 5,806 ms | 7,508 ms |
| Routing agent, 0.1 CPU harness | `7bcb7b8` | — | — | — | 602 ms (was 4,692) | — |
| **Live Render Free (Virginia)**, client in Montréal, includes network | `b81b5b9` | 60 | 50×200, 9×422, 1×404 | **366 ms** | **806 ms** | 8,663 ms (single outlier) |

- 422 = a point could not be snapped to the pedestrian graph. 404 = no route under the profile's hard constraints. Both are expected for random points.
- The routing speed-up in `7bcb7b8` changed the data structures (precomputed adjacency and per-profile static costs) but not the search order or arithmetic. A golden test checks that outputs are **byte-identical**.
- Target: warm p95 < 2 s on 0.1 CPU. **Met** on the live service.

## Cold start (Render Free sleeps after 15 min idle)
- Docker emulation: about 47 s from container start until healthy (graph load from PostGIS plus risk scores).
- Live: the graph loaded about 36 s after Render began deploying the new image (`graph_loaded` log 19:23:21; deploy began 19:22:45). Wake-from-sleep latency for a first visitor was **not yet measured**. Render documents "about a minute".
- The web app uses a 15 s API timeout (`VITE_API_TIMEOUT_MS`) and shows a "waking up" state. A user's first request after idle may time out once and need a retry.

## Memory
- Docker emulation: 180–220 MB RSS of the 512 MB limit.

## Web bundle (`npm run build:pages`, `b81b5b9`)
- 52 files, no source maps. The largest chunk is `PlannerMap` (MapLibre): 1,085 kB, 298 kB gzip. It is lazy-loaded on the planner route only.
- LCP measured earlier at about 3 s (local Lighthouse). Pre-rendering the landing page is pending an owner decision.
- Not yet measured on the live Pages deployment (blocked: Cloudflare token).

## Database
- 49 MB of the Supabase Free limit of 500 MB.
- API pool: 3 connections plus 2 overflow, session pooler.
