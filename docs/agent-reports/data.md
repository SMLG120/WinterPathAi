# Agent report — data

- **Status:** READY FOR REVIEW (all 11 brief steps done; see open items and change requests)
- **Branch / SHA:** agent/data @ see `git log -1` (this report is committed in the final commit;
  code commits `bcf0c10` scaffold+graph+fixture, `10ca71b` pipelines+migrations+loader)
- **Date (UTC):** 2026-11-10

## Files changed
`git diff --stat $(git merge-base integration/winterpath HEAD) HEAD` (before this report commit):
```text
 data/fixtures/pilot_mini/{ATTRIBUTION.md,edges.geojson,manifest.json,metadata.json,nodes.geojson}
 data/qa/osm_pilot_gaps.json            | 2722 +
 data/qa/pipeline_stats.json            |  194 +
 db/alembic.ini, db/migrations/env.py, db/migrations/script.py.mako
 db/migrations/versions/0001_wp_schema_v1.py |  220 +
 services/ingestion/** (package winterpath_ingestion, tests, uv.lock)
 42 files changed, 7275 insertions(+)
```
`scripts/check-ownership.sh data` → `ownership OK for agent/data`.
No raw data committed (`data/raw/`, `data/processed/` are git-ignored). Largest tracked files:
`services/ingestion/uv.lock` 218 KB, `data/fixtures/pilot_mini/edges.geojson` 153 KB (all < 5 MB).

## Commands run and literal results
```text
$ uv run ruff check .
All checks passed!

$ uv run pytest -v --durations=3      (services/ingestion; PostGIS container up on :55432)
collected 39 items
tests/test_fixture_pilot_mini.py::test_metadata_and_attribution PASSED
tests/test_fixture_pilot_mini.py::test_edge_limits_and_ids PASSED
tests/test_graph.py::test_edge_ids_stable_across_two_builds PASSED
tests/test_graph.py::test_edge_ids_independent_of_element_order PASSED
tests/test_graph.py::test_no_prohibited_foot_access PASSED
tests/test_graph.py::test_extract_actually_contained_prohibited_ways PASSED
tests/test_graph.py::test_only_included_highway_types PASSED
tests/test_graph.py::test_lengths_positive_and_match_32188 PASSED
tests/test_graph.py::test_no_duplicate_ids PASSED
tests/test_graph.py::test_edge_id_format_and_endpoints PASSED
tests/test_graph.py::test_geometry_endpoints_match_nodes PASSED
tests/test_graph.py::test_every_edge_has_reverse_twin PASSED
tests/test_graph.py::test_crossing_nodes_carry_metadata PASSED
tests/test_graph.py::test_crossing_edges_have_crossing_info PASSED
tests/test_graph.py::test_steps_never_step_free PASSED
tests/test_graph.py::test_components_consistent PASSED
tests/test_graph.py::test_connectivity_from_osm_topology_only PASSED
tests/test_graph.py::test_gaps_reported_not_repaired PASSED
tests/test_postgis.py::test_migration_up_down_up PASSED
tests/test_postgis.py::test_constraints_reject_bad_rows PASSED
tests/test_postgis.py::test_loader_atomic_and_idempotent PASSED
tests/test_runs_http.py::test_noop_on_same_checksum PASSED
tests/test_runs_http.py::test_failed_run_keeps_previous_output PASSED
tests/test_runs_http.py::test_download_retries_three_times_then_raises PASSED
tests/test_sources.py::test_blocks_passage_only_when_barred PASSED
tests/test_sources.py::test_closures_outside_bbox_dropped PASSED
tests/test_sources.py::test_aggregate_rule PASSED
tests/test_sources.py::test_311_filters_and_aggregates PASSED
tests/test_sources.py::test_swob_sentinels_are_null_not_zero PASSED
tests/test_sources.py::test_climate_hourly_row PASSED
tests/test_sources.py::test_dedupe_prefers_climate_hourly PASSED
tests/test_sources.py::test_voirie_match_is_enrichment_by_overlap PASSED
tests/test_sources.py::test_voirie_refuses_missing_crs PASSED
tests/test_tags.py::test_exclusions PASSED
tests/test_tags.py::test_foot_access PASSED
tests/test_tags.py::test_edge_kind PASSED
tests/test_tags.py::test_crossing_type PASSED
tests/test_tags.py::test_kerb_and_step_free PASSED
tests/test_tags.py::test_incline PASSED
============================= slowest 3 durations ==============================
7.16s call     tests/test_postgis.py::test_migration_up_down_up
6.09s call     tests/test_postgis.py::test_loader_atomic_and_idempotent
1.63s call     tests/test_postgis.py::test_constraints_reject_bad_rows
============================= 39 passed in 19.19s ==============================

$ uv run alembic -c ../../db/alembic.ini upgrade head / current / downgrade base / upgrade head
  (against wp_data, which was empty before: only public PostGIS tables)
0001_wp_schema_v1 (head)
wp tables: ['closure', 'community_report', 'edge', 'edge_risk', 'ingest_run', 'node', 'pilot_request', 'report_311_cell', 'sidewalk_polygon', 'source', 'weather_obs']
gist: ['closure_geom_gix', 'community_report_geom_gix', 'edge_geom_gix', 'node_geom_gix', 'sidewalk_polygon_geom_gix']
$ alembic downgrade base
wp tables: []
gist: []
$ alembic upgrade head
$ alembic current
0001_wp_schema_v1 (head)

$ uv run wp-ingest osm
WARNING winterpath_ingestion.http download attempt 1/3 failed: HTTP 502 from https://overpass-api.de/api/interpreter
"osm_snapshot": "2026-11-10T20:43:04Z", "ways_downloaded": 6853, "ways_included": 4936,
"ways_excluded_by_reason": {"access=no": 19, "access=private": 92, "area=yes (polygon, not a linear walkway)": 22,
  "foot=no": 8, "foot=use_sidepath": 481, "highway=corridor": 147, "highway=cycleway": 150,
  "highway=secondary_link": 7, "highway=service": 983, "highway=unclassified": 8},
"segments": 8326, "zero_length_segments_dropped": 0, "nodes": 6987, "directed_edges": 16652,
"total_length_m_undirected": 172906.7, "components": 159, "largest_component_nodes": 6398,
"largest_component_node_share": 0.9157, "largest_component_length_share": 0.9711,
"crossing_nodes": 1467,
"edge_kind_counts": {"crossing": 5068, "footway": 3508, "other": 1382, "path": 232,
  "pedestrian_street": 188, "shared_street": 16, "sidewalk": 5194, "steps": 1064},
"foot_access_counts": {"designated": 84, "permissive": 36, "unknown": 16200, "yes": 332},
"step_free_counts": {"False": 1128, "None": 13976, "True": 1548}, "gap_count": 351
input_checksum (Overpass response sha256): a7ee9f8c1af78a1756c7500fdeac37ebc82b0afdd309dd18ac38a0e8e4f02e2a

$ (scratchpad script) two builds of the full real snapshot
build1 edges 16652 sha 2991ce37cc31bc98
build2 edges 16652 sha 2991ce37cc31bc98
identical: True
gap types: {'near_miss_dangling_endpoint': 193, 'disconnected_component': 158}
near-miss distance_m: min 0.1 max 1.99 cross-component 77
disconnected component sizes (top 10): [115, 37, 24, 15, 12, 11, 10, 10, 9, 7] singletons/pairs: 125

$ uv run wp-ingest fixture
"edge_count": 200, "node_count": 88, "bbox": [-73.578035, 45.503034, -73.573657, 45.505518]
50 of 200 fixture edges matched (Voirie)
edge kinds: footway 52, sidewalk 48, crossing 38, pedestrian_street 34, other 18, steps 10

$ uv run wp-ingest voirie
"polygons_in_bbox": {"trottoir": 1313, "ilot": 182}, "polygons_written": 1495
match_rates: sidewalk 4888/5194 (0.9411), crossing 1796/5068 (0.3544), footway 376/3508 (0.1072),
  steps 52/1064 (0.0489), path 10/232 (0.0431), other 8/1382 (0.0058),
  pedestrian_street 0/188, shared_street 0/16, all 7130/16652 (0.4282)

$ uv run wp-ingest entraves
"permits_total": 1974, "impact_rows_total": 2105, "closures_in_bbox": 167,
"blocks_passage_counts": {"False": 113, "True": 44, "None": 10}, "unmapped": {}
observed sidewalk_blockedtype: "Aucun impact / non applicable": 907, "Barré": 642,
  "Obstrué (un passage piéton de 1,5 m est conservé)": 556
observed backsidewalk_blockedtype: "Aucun impact / non applicable": 1578, "Obstrué": 277, "Barré": 250

$ uv run wp-ingest 311        (requetes311.csv, 850 013 464 bytes, sha256 8d19aa86…de8bb)
"rows_by_reason": {"located_at_borough_office": 2773, "no_location": 24962,
  "not_winter_category": 3163268, "ok": 80614},
"reports_aggregated_by_category": {"roadway_slippery": 9159, "sidewalk_slippery": 10391,
  "snow_clearing": 55441, "snow_dumping": 5623},
"cells_rows": 68214, "distinct_cells": 2678, "rows_with_n_lt_3": 65975,
"day_range": ["2022-01-01", "2026-11-07"]

$ uv run wp-ingest eccc
"rows": 84248, "rows_by_collection": {"climate-hourly": 84085, "swob-realtime": 163},
"null_counts": {"temperature_c": 1, "precip_mm": 42733, "snow_depth_cm": 84248, "wind_kmh": 33}

$ uv run wp-ingest load        (first run)
{"source_id": "osm", "noop": false, "counts": {"node": 6987, "edge": 16652}}
{"source_id": "mtl-voirie", "noop": false, "counts": {"sidewalk_polygon": 1495}}
{"source_id": "mtl-entraves", "noop": false, "counts": {"closure": 167}}
{"source_id": "mtl-311", "noop": false, "counts": {"report_311_cell": 68214}}
{"source_id": "eccc-geomet", "noop": false, "counts": {"weather_obs": 84248}}

In-DB checks (wp_data):
edges/nodes [(16652, 6987)]
edges length mismatch >1% vs PostGIS 32188: [(0,)]
foot no/private: [(0,)]
NaN stored: [(0,)]
edges with sidewalk polygons: [(7130,)]
invalid geoms: edges 0, sidewalk_polygon 0 (1 invalid after 7-dp rounding was repaired at load
  with ST_MakeValid; re-verified: "invalid polygons: (0,) total (1495,)")
closures by blocks_passage: [(False, 113), (True, 44), (None, 10)]

$ uv run wp-ingest all   (second run, unchanged inputs)
"pipeline": "osm" noop true · "voirie" noop true · "fixture" noop true · "entraves" noop true
"311" noop true · "eccc" noop false   ← expected: current year + swob-realtime are re-fetched
$ uv run wp-ingest load
osm/mtl-voirie/mtl-entraves/mtl-311 noop true; eccc-geomet noop false {"weather_obs": 84249}
```

## Acceptance criteria
| Criterion (docs/agents/data.md) | Met? | Evidence |
|---|---|---|
| Pilot graph from real OSM; node/edge counts, largest-component share, gap list recorded | Yes | 6 987 nodes, 16 652 directed edges; largest component 91.57 % of nodes / 97.11 % of length; `data/qa/osm_pilot_gaps.json` (193 near-misses ≤2 m, 158 small components) |
| Edge IDs stable across two builds of the same snapshot (test) | Yes | `test_edge_ids_stable_across_two_builds`, `test_edge_ids_independent_of_element_order`; full snapshot hash identical |
| No edge with `foot_access in (no, private)` | Yes | test + in-DB count 0 |
| All lengths > 0 and within 1 % of 32188 recomputation | Yes | test + PostGIS `ST_Length(ST_Transform(geom,32188))` check: 0 mismatches |
| No duplicate IDs | Yes | test; PK constraints in DB |
| Crossing nodes carry crossing metadata where tagged | Yes | `test_crossing_nodes_carry_metadata`, 1 467 crossing nodes |
| Migrations apply and roll back cleanly on PostGIS | Yes | `test_migration_up_down_up` (throwaway DB `wp_data_test`) + manual up/down/up on `wp_data` |
| Attribution for every ingested source | Yes | `wp.source` rows (registry.py), fixture `ATTRIBUTION.md` (OSM + Voirie) |
| Pipelines idempotent + atomic | Yes | no-op rerun above; `test_failed_run_keeps_previous_output`; `test_loader_atomic_and_idempotent` |

## Design notes / deviations (please review)
1. **Graph built from Overpass JSON with our own splitter, not OSMnx's builder.** OSMnx
   simplification merges segments across ways and keeps a tag subset; the contract's
   `edge_id` (`k` ordered by OSM way id) needs one way per edge. Rule: split each included way at
   nodes shared with another included way, way endpoints, and nodes tagged crossing/kerb/barrier.
   OSMnx stays a dependency but is not used in the build. Every edge is inserted in both
   directions (pedestrians are not bound by `oneway`).
2. **Highway types included strictly per brief:** footway (incl. sidewalk/crossing), path,
   pedestrian, steps, living_street, residential, tertiary, secondary, primary.
   **Excluded and counted:** service 983, cycleway 150, corridor 147 (indoor/RÉSO), unclassified
   8, secondary_link 7. These cause some of the 158 small components. Changing the include
   list is a policy decision for the coordinator.
3. **`foot_access`:** explicit `foot` wins, else `access`. Untagged is `unknown`, not `yes`,
   because we don't claim a legal status the data doesn't state. `foot=use_sidepath` maps to
   `no`, so those ways are excluded. 97 % of edges are `unknown`, and they stay routable.
4. **`step_free`:** `false` for steps, `wheelchair=no`, or any `kerb=raised` on the edge. `true`
   only for `wheelchair=yes` with no contradicting kerb. Otherwise `null`. Kerb tags alone never
   set `true`.
5. **Road edges** (`residential`…`primary`) get `edge_kind="other"`. We don't upgrade them to
   `sidewalk` from `sidewalk=*` tags. Many Montréal roads are `sidewalk=separate` and duplicate
   the mapped footways.
6. **Entraves geometry is the permit point.** Entraves publishes one point per permit. Affected
   street sections are named only (`streetid`, `fromname`, `toname`); they're kept in
   `attrs.impacts` in the processed file, but `wp.closure` has no attrs column. We do not
   geocode them. Routing should treat closure-to-edge matching as approximate.
7. **Voirie match rule:** an edge matches a polygon when ≥ 50 % of the edge length lies inside
   the polygon buffered by 1 m (EPSG:32188). Enrichment only. `polygon_id` is prefixed by layer
   (`trottoir:<ID_VOI_TROTTOIR>`, `ilot:<ID_VOI_ILOT>`) to avoid cross-layer collisions.
   `surveyed_at` is NULL because no survey date is published (`DATE_VERSION` is the dataset
   version).
8. **DB roles:** `wp_reader`, `wp_writer` and `wp_migrator` already existed cluster-wide. The
   migration creates them NOLOGIN only if absent, and downgrade revokes grants but never drops
   them. `wp_reader` has no SELECT on `pilot_request` or `community_report` (PII).
9. **PostGIS tests** create and drop a throwaway DB `wp_data_test` in the shared container, so
   `wp_data` is never touched. They skip (never fake) if the server is unreachable. Docker was
   reported paused in the brief, but it was up during this run with container `winterpath-db-1`
   (postgis/postgis:16-3.4, PostGIS 3.4.3).

## Source verification findings (brief step 2) — change request for `docs/data-sources-and-licenses.md`
Verified 2026-11-10. Policy pages were read by a fetch sub-agent; the short quotes are from that
report.
- **Overpass API (overpass-api.de)** — wiki.openstreetmap.org/wiki/Overpass_API and
  dev.overpass-api.de/overpass-doc/en/preface/commons.html: "less than 10,000 queries per day
  and download less than 1 GB data per day" (÷100 for regular use); requests must carry a
  `User-Agent` or `Referer` that identifies the app; "No parallel running of multiple scripts";
  after 429 "pause for 30 seconds"; default timeout 180 s, memory 512 MiB; **"Commercial use
  should use self-hosted or paid Overpass servers"**. The FOSSGIS terms page linked from the
  table was not fetched.
  → Our use is 1 cached query per snapshot, with a custom UA from `HTTP_USER_AGENT` and a 30 s
  backoff on 429. **Before a commercial launch, switch to a Geofabrik `quebec` extract or a
  self-hosted Overpass.** Proposed row update: Access = "Overpass public: ≤10k req/day, ≤1 GB/day,
  identifying UA, commercial → self-host; Geofabrik: no stated quotas".
- **Geofabrik** — download.geofabrik.de/technical.html and geofabrik.de/data/download.html: no
  rate limit, quota, UA or commercial restriction stated; "You may use the data for any purpose,
  but you have to acknowledge OpenStreetMap as the data source"; derived DBs keep ODbL. Diffs
  are kept 100 days.
- **311 methodology** (donnees.montreal.ca/dataset/requete-311, "Production des données") —
  locations of address/installation requests are "relocalisées au milieu du tronçon le plus près
  ayant une longueur de plus de 45 mètres". LOC_LAT/LONG/X/Y are "Position obfusquée". The
  location is the request site, not the requester. Information requests are not geolocated.
  `LOC_ERREUR_GDT`: 0 = located at the request site, 1 = located at the borough office (BAM).
  **No rounding in metres is published beyond that rule.** → Rows with `LOC_ERREUR_GDT=1`
  (2 773 winter rows) are excluded from aggregation. ACTI_NOM is only "Catégorie de la
  demande"; NATURE ∈ {Information, Commentaire, Requête, Plainte}. Licence: CKAN
  `license_id=cc-by` (API, verified). The page also lists overlapping archive files (2016–2018
  vs 2017–2018 and 2014–2016), so dedupe on `ID_UNIQUE` if archives are added.
- **311 winter categories** (from 996 distinct `ACTI_NOM` values in the 2022→2026-11-09 file):
  kept `Trottoir glissant` (12 984 rows) → `sidewalk_slippery`, `Chaussée glissante` (11 280) →
  `roadway_slippery`, `Opération déneigement` (76 702) and `Déneigement ruelle` (8) →
  `snow_clearing`, `Dépôt Illégal - Neige` (7 355) and `Dépôt neige-ruelle` (20) →
  `snow_dumping`. Deliberately excluded: Signalisation - Neige, Neige - Remorquage, Permis/Billet
  neige, Piste cyclable déneigement, Carte Info-Neige, and generic Trottoir ou bordure -
  Réparation. Counts include all NATURE values. The ML agent may want `sidewalk_slippery` alone
  as the label.
- **311 date basis:** `DDS_DATE_CREATION` has no timezone (`2023-07-10T20:15:39`), and the
  publisher doesn't state one. `day` is the published calendar date as-is. **Unverified whether
  this is local time or UTC.**
- **Voirie / Entraves licences:** CKAN `voirie-trottoir-ilot` and `info-travaux` both have
  `license_id=cc-by` (CC BY 4.0). The doc's ids `vmtl-voirie-trottoir-ilot` and
  `vmtl-info-travaux` return "Not Found" on donnees.montreal.ca CKAN, where the ids are
  `voirie-trottoir-ilot` and `info-travaux` (the `vmtl-` prefix is the Données Québec id).
- **ECCC stations:** `climate-stations` query, bbox −73.85,45.40,−73.45,45.60, `HAS_HOURLY_DATA=Y`:
  7025251 MONTREAL INTL A (hourly 2013-02-13 → present, ~13.6 km from McGill; **PRECIP_AMOUNT
  null for every hourly row**), 702S006 MONTREAL/PIERRE ELLIOTT TRUDEAU INTL (hourly precip
  present; hourly ends 2026-10-01 per metadata), 7025250 (ended 2013). No downtown hourly
  station was found. Both 7025251 and 702S006 are ingested as separate `station_id`s, with no
  merging. SWOB realtime: id 7025251 = manual CYUL obs (no precip/snow fields); 702S007 =
  automatic minutely; `snw_dpth=-1` is a sentinel and is stored as NULL.

## Change requests (contracts)
1. **`wp.edge`: add `crossing_type text`, `crossing_kerb text`** (CrossingInfo enums). The API's
   `SegmentFeature.crossing` needs per-edge crossing info, which the builder already computes
   (it's in `edges.geojson`) but has no column for. Additive → minor bump.
2. **`wp.closure`: add `attrs jsonb`** to keep the named affected street sections and permit id
   (see note 6), and `backsidewalk_blocks_passage boolean null` (opposite sidewalk, `Barré` →
   true, `Obstrué` → null). Additive.
3. **`wp.weather_obs.source_collection`: allow `climate-daily`**, or add a `weather_daily`
   table. 7025251's daily data has `SNOW_ON_GROUND` (31/31 days, Jan 2025) and
   `TOTAL_PRECIPITATION` (30/31), while its hourly precip is entirely null and no hourly
   snow-depth field exists. This matters for ML features. Additive.
4. **Docs:** fix the CKAN dataset ids (see above) and record the Overpass/Geofabrik/311 findings
   in the "Still to verify" section.
5. *(Optional)* `wp.edge.highway text` and `osm_snapshot` for traceability. Both are in the
   GeoJSON outputs now.

## Blockers
| Blocker | Impact | Next step / who |
|---|---|---|
| None blocking. Overpass public instance discourages commercial use | Production OSM refresh path | Coordinator: approve Geofabrik extract or self-hosted Overpass before launch |
| ECCC hourly precip/snow depth gaps (above) | ML weather features thinner | Coordinator: CR 3; ML agent: decide feature set |
| 311 archives (2014–2021) not ingested | Training window 2022-01-01 → 2026-11-07 only (5 winters) | Add to `r311.RESOURCES` if ML needs more; dedupe on `ID_UNIQUE` |

## Dependencies on other agents
- **Routing / Frontend:** `data/fixtures/pilot_mini/` has 200 real directed edges and 88 nodes
  near Roddick Gates. It's connected, `"simulated": false`, snapshot 2026-11-10T20:43:04Z.
  Properties follow the `wp.edge` columns plus `crossing` ({type, kerb} or null), `highway` and
  `osm_snapshot`. `risk` is **not** included; that's the API/ML layer's job (absent means
  `unknown`). Node ids `osm:n<id>`; edge ids `<from>><to>:<k>`.
- **ML:** `wp.report_311_cell` (68 214 rows, 2 678 cells) and `wp.weather_obs` (84 248 rows) are
  loaded in `wp_data`. 65 975 of the 68 214 cell-day rows have n<3 and must be suppressed in any
  public output.
- **Platform:** migrations run with `uv run alembic -c db/alembic.ini upgrade head` (from
  `services/ingestion`). The URL comes from `DATABASE_URL` or `-x url=...`.

## Licensing / data notes
- OSM extract (fixture, `data/qa/*`, test extract) is ODbL 1.0. The derived-DB share-alike
  obligation needs counsel review before commercial launch.
- Ville de Montréal (Voirie, Entraves, 311) is CC BY 4.0 with attribution "Contient des données
  de la Ville de Montréal, sous licence CC BY 4.0".
- ECCC: "Data Source: Environment and Climate Change Canada". No logos, no endorsement.
- 311 rows are **reports, not confirmed obstacles**. Only counts per H3 res-9 cell, day and
  category leave `data/raw/`.
- Nothing in any output states that a sidewalk is cleared, safe, ice-free or accessible.
  `step_free=null` means unknown.
- Planif-Neige: not touched (token required).

## Review readiness
Ready for coordinator review: ownership check passes, 39/39 tests pass with PostGIS live, and
no secrets or raw data are committed (the author email that `uv init` inserted into
pyproject.toml was removed before the first commit). Please decide CR 1–4 and the
Overpass→Geofabrik production path.

## Post-merge check — integration/winterpath (contract v1.1.0 + platform), 2026-11-10
`git merge --no-edit integration/winterpath` → merge commit `df39e73`, no conflicts.
v1.1.0 does not change `data-model.md` → no migration needed. The CI steps for this package,
run locally after the merge:
```text
$ uv run --with ruff ruff check .
All checks passed!
$ uv run --with ruff ruff format --check .
26 files already formatted
$ uv run pytest -q
.......................................                                  [100%]
39 passed in 20.97s
$ uv run --with pip-audit pip-audit --skip-editable --progress-spinner off
No known vulnerabilities found
```
Compatibility with `infra/db/init/20-winterpath.sh`: both create roles with `IF NOT EXISTS`.
Platform's default privileges for `wp_migrator` would grant `wp_reader` SELECT on every table.
Migration 0001 explicitly revokes `wp_reader` SELECT on `pilot_request` and `community_report`
after creating them, so the PII tables stay unreadable by `wp_reader`.
`scripts/check-ownership.sh data` → `ownership OK for agent/data`.
