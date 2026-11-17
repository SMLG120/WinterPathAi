# Greater Montréal coverage: Stage 1 (Island + Laval + Longueuil)

Local measurements only (macOS, 2026-11-16). Nothing here is deployed. Mac numbers are not Render
numbers (Render: 512 MB, 0.1 CPU). OSM snapshot: Geofabrik `quebec-261110.osm.pbf`. Municipal
limits: Québec SDA (CC BY 4.0), see `osm/region.py` for the area rule.

## Island regression

`wp-ingest osm-region --graph-region island --force` rebuilt the island through the region path.

* Processed GeoJSON equals the Wave 1 build (`data/processed/osm_island`) after blanking the per-run
  `ingest_run_id` (a fresh UUID each run, so raw file hashes can never match): edges
  `530778519c6c...c76d6` (650,920 edges), nodes `29a860c54462...410c0` (257,542 nodes), both builds.
* The artifact built with `--from-processed` is **not** byte-identical to the published
  `graph-island-v2` (`2f40b5e4...06bb9`); ours is `e2a842b9...d7a58`. Reason: v2 was packed from
  PostGIS (`updated_at`/`built_at`/snapshot metadata and row order), ours from the GeoJSON. An
  id-ordered comparison of the two (every edge id, node id, coordinate, geometry, length, from/to,
  main-component mask and every attribute) shows 0 differences except `updated_at`
  (650,920 edges: set in v2, empty in ours). Same nodes, edges, geometry and attributes.

## Fixed links (read-only report, `wp-ingest fixed-links`, 75 structures)

Foot-legal links into Laval and Longueuil (all are in graph component 0, the largest):

| Neighbour | Structure | OSM way ids | Tags of note |
|---|---|---|---|
| Laval | Pie-IX bridge | 289089432 (cycleway, foot=designated), 289089434 (footway) | none conditional |
| Laval | Boulevard des Laurentides | 964053201, 964309234 (footway, foot=designated) | none |
| Laval | Pont Lachapelle | 1049434614 (footway), 1049434624 (cycleway) | none; other Lachapelle ways excluded `foot=use_sidepath` |
| Laval | Pont Olivier-Charbonneau | 360051750 (cycleway, foot=designated) | none |
| Laval | Pont de l'Île-Perry | 264386396 (cycleway, foot=designated) | none |
| Longueuil | Pont Jacques-Cartier | 426366140, 852435426, 852435428, 928301945, 1331433208 | **852435426: `seasonal=spring;summer;fall`**; a structure member carries `opening_date=2027-01-01` (excluded member) |

Excluded, with reason: Laval motorways (A-25, A-13 Chomedey, A-19 Papineau, A-15 Laurentides),
Pie-IX trunk ways, Laurentides ways (`foot=use_sidepath`, service/cycleway without explicit foot),
Pont Lachapelle `foot=use_sidepath` ways, rail/REM/metro (not a road), Longueuil
Pont-Tunnel Louis-H.-La Fontaine (`highway=construction`), Autoroute Transcanadienne (motorway).
Other neighbours (not Stage 1): Pont Victoria `foot=no`, Honoré-Mercier trunk, Champlain estacade
cycleway 408747052 (`access:conditional=no @ 6:00-22:00`, `winter_service=no`) and its service
road (`access:conditional=no @ (Nov 15-Apr 15 00:00-24:00; ...)`). The graph does **not** evaluate
`seasonal`/`*:conditional` tags; they are reported verbatim only.

Longueuil's connection to the island depends on one seasonal-tagged way: in the earlier link-removal
test, removing 852435426 dropped the share of Longueuil nodes connected to the main island from
0.9167 to 0.0. Removing all 42 seasonal/conditional ways left Laval unchanged (0.9289). So Laval is
linked by year-round-tagged bridges; Longueuil only by Jacques-Cartier ways whose winter
availability is unverified. Stage 1 therefore must not present Longueuil walking routes in winter
as confirmed (evidence state `unknown`). Variant `stage1-laval` (island + Laval) exists for this.

## Stage 1 graph

| | Island (region path) | Island + Laval | Stage 1 (+ Longueuil) |
|---|---|---|---|
| Nodes | 257,542 | 312,396 | 342,687 |
| Directed edges | 650,920 | 780,710 | 856,436 |
| Network km (undirected) | see island stats | | 14,311.2 |
| Largest component, nodes | 98.15% | 97.61% | 95.92% (328,690) |
| Artifact bytes | 188,568,037 | 228,112,687 (1.21x) | 250,021,231 (1.33x) |
| Artifact build, API venv | 30.8 s | 39.7 s | 42.4 s |
| Graph build (`osm-region`) | 196.7 s (cached clip) | | 196.7 s (cached clip) |

Stage 1: 3,326 components, 6,271 reported gaps (never repaired). Laval: 54,835 nodes, 2,464.3 km,
92.89% of nodes in the largest component (the one containing the island). Longueuil: 30,065 nodes,
1,627.2 km, 91.67% in it. Sub-components are other disconnected OSM fragments (not joined).
`--coverage-name` for the artifact needs a MultiPolygon area; see change request in
`docs/agent-reports/greater.md`.

## API measurements (Mac, port 8109, mmap, fast search, warm-up, memory store, no risk provider)

80 pairs from random main-component nodes (20 per group). Latency = `/routes/compare` HTTP, 200s only.
RSS = `ps rss` (includes clean memory-mapped graph pages).

| Artifact | Idle RSS | Post-test RSS | island-local p50/p95 | Laval-local | Longueuil-local | cross-river |
|---|---|---|---|---|---|---|
| Island v2 | 183 MiB | 294 MiB | 74 / 262 ms | 20/20 OFF_NETWORK | 15 OUTSIDE_COVERAGE, 5 OFF_NETWORK | 10 OFF_NETWORK, 10 OUTSIDE_COVERAGE |
| Island + Laval | 221 | 352 | 66 / 248 | 34 / 134 | 20/20 not served | 7 ok (159/191), 13 not served |
| Stage 1 | 222 | 382 | 67 / 267 | 36 / 147 | 28 / 45 | 178 / 247 (20/20 ok) |

Load time (health ready): 2.1 s for island and Stage 1. Latencies were measured at full CPU.

## Decision

Rule: do not propose shipping if artifact > 1.6x island or the island-equivalent peak RSS
projection exceeds about 400 MiB.

* Size: 1.33x passes.
* Memory: Render island peak after route load was 382 MiB (docs/ISLAND_COVERAGE.md). On the same
  Mac load, Stage 1 post-test RSS is 1.30x island (382 vs 294 MiB), +88 MiB. Projection:
  382 x 1.30 = about 497 MiB, or 382 + 88 = about 470 MiB. Both exceed 400 MiB and the 512 MiB
  limit leaves no headroom. **Not proposed for shipping on the current instance.**
* Island + Laval is 1.20x post-test RSS (352 vs 294): projection about 458 MiB, also over.

Partitioning recommendation (not implemented): one artifact per region (island 188.6 MB, Laval
about +40 MB of graph, Longueuil about +22 MB), loaded by the region of the request's origin and
destination, with cross-region routes served only where a verified foot link exists (Laval: yes;
Longueuil: Jacques-Cartier, seasonal). That keeps one region resident per process at about island
memory; an instance with more than 512 MB is the alternative. Either needs an architecture and
`/coverage` change (MultiPolygon, multiple areas) that is outside this agent's paths.


## Seasonal-access rule (user decision 2026-11-16, conservative seasonal exclusion)

Build-time, deterministic, in the shared inclusion policy (`osm/graph.py: seasonal_exclusion`, used
by `exclusion_reason` for island, region and links builds; `GRAPH_POLICY` is now `v1.6.0+seasonal-v1`,
so every region rebuilds). A way with `seasonal=*` is excluded unless the value, split on `;` and
trimmed (case-insensitive), includes `winter`. `seasonal=yes` and unparseable values are excluded
(open period unknown is never open). `seasonal=no` or absent: unchanged. Excluded like other
prohibited edges (removed, not penalised); no edge is added or repaired. Other exclusion reasons
take precedence. Slash-separated values such as `spring/summer/autumn` are unparseable and excluded.

Effects (same OSM snapshot, rebuilt locally):

* Island: 7 seasonal ways newly excluded: 87389005, 108705328, 108705333 (steps, `summer`),
  136728395 (path, `yes`), 852435426 (Pont Jacques-Cartier footway, `spring;summer;fall`),
  1253645848, 1253645849 (footways, `summer`); way with `seasonal=winter` kept. Nodes 257,542 to
  256,993 (-549), directed edges 650,920 to 649,506 (-1,414; 1,420 edge ids removed, 6 added where
  splits changed). The component filter then drops 391 further ways that were connected to the main
  island only through the excluded ways (land unit isl-0003: 573 to 35 nodes). Island ways dropped by
  the filter: 272 to 663. Largest component, artifact: 98.15% to 98.14% of nodes; build stat 0.9707
  unchanged. Island artifact now `675efa44...34e11` (188,125,526 bytes); it no longer matches v2
  (`2f40b5e4...`), as expected.
* Stage 1: 40 seasonal ways newly excluded (7 above plus Longueuil cycleways such as Chemin de la
  Rive / Rue Pierre-Dupuy / La Riveraine `spring;summer;autumn`, and `spring/summer/autumn` paths).
  Nodes 342,687 to 342,640; directed edges 856,436 to 856,238. **Longueuil: 0 of 30,035 nodes are in
  the island component (was 91.67%)**: confirmed, no foot link remains. Laval: 50,938 to 50,936 of
  54,835 nodes (92.89% unchanged to 4 digits). Largest component: 97.41% to 88.84% of nodes
  (artifact) because Longueuil is now a separate, reported component. Stage-1 artifact
  `6b9c1d50...c7a17` (249,926,985 bytes). Decision above (not shipping Stage 1) is unaffected;
  `stage1-laval` is the only candidate and Longueuil is no longer reachable on foot from the island.
* The latency and memory tables above predate this rule and were not re-run.

Change request: `docs/contracts/data-model.md` inclusion policy needs the line "ways with
`seasonal=*` are excluded unless the value lists `winter`; `seasonal=yes` or unparseable values are
excluded". Not edited here (frozen contract).
