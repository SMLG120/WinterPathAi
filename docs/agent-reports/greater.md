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


## Addendum: seasonal-access rule (user decision 2026-11-16, conservative seasonal exclusion)

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

### Unresolved foot/access :conditional ways, not applied (user decision 2026-11-16)

Foot-legal ways in the graph with a conditional tag; the graph does not evaluate them. Island: 34 ways, Stage 1: 42 ways (island ways marked I). Tags verbatim.

| way | in | highway | name | conditional tags |
|---|---|---|---|---|
| 34582158 | S1 | path |  | access:conditional=yes @ winter |
| 229485293 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2023 May 20-2023 Sep 5) |
| 337509255 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Oct 14) |
| 393787289 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Aug 26) |
| 393873277 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Aug 26) |
| 408747052 | I | cycleway | Piste cyclable de l'Estacade du Pont-Champlain | access:conditional=no @ 6:00-22:00 |
| 436272524 | I | path | ski lièvre | foot:conditional=no @ winter |
| 446260496 | S1 | path |  | access:conditional=yes @ winter |
| 446260497 | S1 | path |  | access:conditional=yes @ winter |
| 446260499 | S1 | path |  | access:conditional=yes @ winter |
| 452060452 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Aug 26) |
| 452060453 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Aug 26) |
| 452096883 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Oct 14) |
| 452101823 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Aug 26) |
| 461162995 | I | secondary | Rue Ontario Est | foot:conditional=yes @ (2025 Jun 16-2025 Sep 12); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2025 Jun 16-2025 Sep 12) |
| 461163000 | I | secondary | Rue Ontario Est | foot:conditional=yes @ (2025 Jun 16-2025 Sep 12); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2025 Jun 16-2025 Sep 12) |
| 461163002 | I | secondary | Rue Ontario Est | foot:conditional=yes @ (2025 Jun 16-2025 Sep 12); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2025 Jun 16-2025 Sep 12) |
| 461163008 | I | secondary | Rue Ontario Est | foot:conditional=yes @ (2025 Jun 16-2025 Sep 12); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2025 Jun 16-2025 Sep 12) |
| 461163009 | I | living_street | Rue Ontario Est | foot:conditional=yes @ (2025 Jun 16-2025 Sep 12); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2025 Jun 16-2025 Sep 12) |
| 463886932 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Aug 26) |
| 463886933 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Aug 26) |
| 463886941 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Aug 26) |
| 463886942 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Aug 26) |
| 463886948 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Oct 14) |
| 464057453 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Aug 26) |
| 464080257 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Aug 26) |
| 464106928 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Aug 26) |
| 465183712 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Oct 14) |
| 470242938 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2023 May 20-2023 Sep 5) |
| 471004956 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2023 May 20-2023 Sep 5) |
| 634019334 | S1 | path |  | access:conditional=yes @ winter |
| 725190286 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Oct 14) |
| 906950648 | S1 | path |  | access:conditional=yes @ winter |
| 971673239 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2024 Jun 5-2024 Oct 14) |
| 998260230 | I | footway |  | access:conditional=private @ school_hours |
| 1162831540 | I | living_street | Rue Ontario Est | foot:conditional=yes @ (2025 Jun 16-2025 Sep 12); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2025 Jun 16-2025 Sep 12) |
| 1162831541 | I | secondary | Rue Ontario Est | foot:conditional=yes @ (2025 Jun 16-2025 Sep 12); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2025 Jun 16-2025 Sep 12) |
| 1181868296 | S1 | path |  | access:conditional=yes @ winter |
| 1181868297 | S1 | path |  | access:conditional=yes @ winter |
| 1182315432 | I | secondary | Avenue du Mont-Royal Est | bicycle:conditional=designated @ (2023 May 20-2023 Sep 5); foot:conditional=designated @ (2023 May 20-2023 Sep 5); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2023 May 20-2023 Sep 5) |
| 1411366472 | I | secondary | Rue Ontario Est | foot:conditional=yes @ (2025 Jun 16-2025 Sep 12); hgv:conditional=delivery @ (19:00-07:00); motor_vehicle:conditional=no @ (2025 Jun 16-2025 Sep 12) |
| 1429424601 | I | steps |  | access:conditional=private @ school_hours |

After the seasonal rule: services/ingestion ruff check "All checks passed!", format "37 files already formatted", pytest "90 passed, 10 skipped, 2 warnings in 2.12s"; services/api ruff "All checks passed!", format "41 files already formatted", pytest "132 passed, 15 skipped, 1 warning in 9.26s".
