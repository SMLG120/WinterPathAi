# Per-region routing graphs — plan (not implemented)

Status: **plan, 2026-11-16.** Nothing here is built. Owner of the decision: the user. Coordinator: lead.

## Why
Stage 1 (island + Laval + Longueuil) was not shipped: Mac RSS after a load test was 382 MiB vs 294 MiB
for the island (×1.30), projected to ~470–497 MiB on Render Free (512 MB). See `GREATER_MONTREAL_COVERAGE.md`.

**Caveat on that projection.** It scaled Mac `ps` RSS, which counts clean memory-mapped graph pages. The
island budget in `ISLAND_COVERAGE.md` was measured differently: the container's **anonymous (non-reclaimable)**
memory under cgroup limits (178 → 239 MiB with `ROUTING_GRAPH_ARTIFACT_MMAP=true`). Mapped file pages are
reclaimable and do not cause OOM kills. The Stage-1 projection is therefore likely pessimistic. Step 0 settles it.

## Step 0 — measure before building anything (gate)
Docker, `--cpus=0.1 --memory=512m`, same method and trip classes as `ISLAND_COVERAGE.md`, three artifacts built
with graph policy `v1.6.0+seasonal-v1`:

| Artifact | Contents | Size |
|---|---|---|
| I | island | 188.1 MB (`675efa44…`) |
| IL | island + Laval | ~228 MB (to build) |
| S1 | island + Laval + Longueuil | 249.9 MB (`6b9c1d50…`) |

Record per artifact: start-to-healthy time, anonymous memory idle → after routes → after 3-client panning, peak
container memory, OOM kills, route p50/p95/max per class incl. cross-river (island ↔ Laval).

**Decision rule**
- Anonymous memory peak ≤ 400 MiB, no OOM, cross-region p95 < 15 s (web timeout) → **ship one artifact (IL),
  no partitioning.** Longueuil can ride along (S1) only if it also passes; in winter it is a separate component
  (seasonal rule), so its routes stay inside Longueuil.
- Otherwise → steps 1–4.

## Steps 1–4 — partitioned graphs (only if step 0 fails)
Key fact: with the seasonal rule, **Longueuil has no winter walking link to the island** (0 of 30,035 nodes in
the island component). The South Shore is therefore a natively separate graph: partitioning there needs **no
stitching** and invents no connection.

1. **Partition unit = a winter-connected service area, never an arbitrary tile.**
   - `north`: island + Laval (+ later Terrebonne, Repentigny) — one artifact, because trips cross the bridges.
   - `south`: Longueuil (+ later Brossard, Saint-Lambert, Boucherville) — separate artifact.
   - No cross-artifact edges. A trip whose ends are in different areas gets an honest refusal
     (`NO_ROUTE`, details `reason: "no_winter_walking_link"`, the areas named) — never a stitched route.
2. **Loader (API, `state.py` / `graph_artifact.py`).** `ROUTING_GRAPH_ARTIFACTS` = list of
   `{area, url, sha256}`; each SHA-pinned like today. All memory-mapped; the per-artifact in-RAM part (small
   unaligned arrays, coordinate copies, SciPy CSR built at search time) is what costs anonymous memory.
   Load `north` at boot; load `south` lazily on first use and keep at most N areas resident (LRU, N from
   measurement). Warm-up per area optional (`ROUTING_WARMUP`).
3. **Area lookup.** Point → area by the areas' outlines (same `outside_area` test as the OUTSIDE_COVERAGE fix,
   applied after a snap failure). Response caches already key on graph version: extend to `(area, sha256)`.
   Risk-cell index and hazard matching are per artifact (each artifact already carries its edge → H3 index).
4. **Coverage and web.** `/coverage` returns a `MultiPolygon` + per-area names → **contract change**
   (pending CR from agent/mapux and agent/greater). The map already draws MultiPolygon and hatches outside.

## Contract / config changes (coordinator)
- `Coverage.area`: `Polygon | MultiPolygon`; optional `areas: [{name, bbox, area}]` (additive).
- `NO_ROUTE` details: optional `reason`, `areas` (additive).
- Env: `ROUTING_GRAPH_ARTIFACTS` (JSON list); `ROUTING_GRAPH_ARTIFACT{,_SHA256}` kept as the single-area form.
- Release assets: one per area, published only after step-0-style measurement of the final set.

## Order of work (one agent at a time)
| # | Work | Owner | Gate |
|---|---|---|---|
| 0 | Docker measurement of I / IL / S1 | lead (no agent) | Docker running |
| 1 | If gate passes: publish IL as `graph-greater-v1` (user approval), `/coverage` outline update | B + lead | user approval |
| 2 | Else: loader for multiple artifacts + area lookup + cache keys + tests | B (Sonnet) | CR approved |
| 3 | Contract v1.10 (`MultiPolygon`, `areas`, `NO_ROUTE.reason`) | lead | user OK |
| 4 | Web: area names in refusal copy; per-area freshness | D's files, small | after 3 |
| 5 | Docker re-measure the partitioned build; then PR, preview, user-approved deploy | lead | numbers |

## Not decided / open
- Seasonal rule makes Parc Jean-Drapeau (land unit `isl-0003`, 573 → 35 nodes) mostly unreachable; check
  whether the Concorde bridge / metro-only access is mapped correctly before release.
- 34 (island) / 42 (Stage 1) `*:conditional` ways are reported, not applied.
- Winter-risk scores exist only for island H3 cells; Laval/Longueuil routes will be ~100 % `unknown` until the
  ML scoring covers them. Ville de Montréal closures and 311 do not cover other cities.

## Step 0 results — Mac fallback (2026-11-16; Docker Desktop was paused, so NOT Render/Docker numbers)
API code: `integration/search-cache-map` @ `bdb1823` (PR #1: response caches + OUTSIDE_COVERAGE fix), one uvicorn
worker, mmap, fast search, warm-up, no risk layer, in-memory stores, full Mac CPU, no memory limit.
Memory = macOS `footprint` (dirty + compressed; excludes clean mapped graph pages). Trips = agent B's 80 pairs
(`island-local`, `Laval-local`, `Longueuil-local`, `cross-river` 7 island–Laval / 7 island–Longueuil / 6 Laval–Longueuil),
then 3 concurrent panning clients × 40 snapped downtown viewports.

| Artifact | Size | Island p50/p95 | Laval p50/p95 | Longueuil | Cross-river ok | Footprint idle → routes → panning |
|---|---|---|---|---|---|---|
| v2 (production) | 188.6 MB | 65 / 239 ms | OUTSIDE_COVERAGE ×20 | OUTSIDE_COVERAGE ×20 | 0/20 | 166 → 184 → 197 MiB |
| I (seasonal) `675efa44…` | 188.1 MB | 67 / 248 ms | OUTSIDE_COVERAGE ×20 | OUTSIDE_COVERAGE ×20 | 0/20 | 162 → 179 → 194 MiB |
| IL (seasonal) `bddc1b56…` | 227.7 MB | 69 / 269 ms | 36 / 65 ms (20/20) | OUTSIDE_COVERAGE ×20 | 7/20 (all 7 island–Laval) | 177 → 201 → 218 MiB |
| S1 (seasonal) `6b9c1d50…` | 249.9 MB | 70 / 271 ms | 39 / 63 ms (20/20) | **OFF_NETWORK ×20** | 7/20 | 187 → 209 → 230 MiB |

Panning: all 120 `/map/segments` and 120 `/hazards` answered 200 in every run (segments p50 51–58 ms, p95 99–115 ms).

Reading:
- Dirty memory grows ×1.11 for IL and ×1.17 for S1 over v2, far less than the ×1.30 RSS used in the earlier
  projection. Scaling the Docker anonymous-memory figures from ISLAND_COVERAGE.md (239 MiB after a load test;
  319 MiB after the segments test) by ×1.11 gives ~265–354 MiB for IL: **under the 400 MiB gate, but projected,
  not measured in a 512 MB / 0.1 CPU container.** Latency at 0.1 CPU is not measured.
- **S1 must not ship.** Longueuil is inside S1's outline but, after the seasonal rule, outside the routed main
  component, so every Longueuil trip is refused with OFF_NETWORK ("inside the coverage area but more than 75 m
  from a walkway") — false. Longueuil needs its own artifact (south area) or must stay out of the outline.
- **IL is the candidate:** Laval-local and island–Laval trips route; Longueuil is honestly OUTSIDE_COVERAGE.

Next gate before publishing IL: one Docker run of IL at `--cpus=0.1 --memory=512m` (anonymous memory, OOM,
cross-river p95 < 15 s), then user approval to publish `graph-greater-v1`.
