# Agent report — data

- **Status:** READY FOR REVIEW. v1 MERGED (bc6d6c5); v1.2.0, v1.3.0 and CR-ROUTING-7 (migration 0004) follow-ups below
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
> **Accepted as contract v1.2.0 (36b961b), implemented in migration 0002; see the last section.**

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

## Contract v1.2.0 follow-up — 2026-11-10
`git merge --no-edit integration/winterpath` fast-forwarded to `36b961b` (contract v1.2.0). No
conflicts; nothing in `docs/contracts/` or platform-owned paths was edited.

**Implemented**
- `db/migrations/versions/0002_contract_v1_2_0.py`, purely additive:
  - `wp.edge` gains `crossing_type` and `crossing_kerb` (CHECK on the CrossingInfo enums),
    `highway`, and `osm_snapshot timestamptz`.
  - `wp.closure` gains `backsidewalk_blocks_passage boolean` and
    `attrs jsonb NOT NULL DEFAULT '{}'`.
  - New table `wp.weather_daily`: PK(station_id, day), non-negative CHECKs on precip, snow and
    snow on ground, and `source_collection` limited to `climate-daily`. Grants: reader SELECT,
    writer DML, migrator ALL.
  - Downgrade drops exactly these objects.
- Loader:
  - Edges load the new columns. Crossing type and kerb come from the builder's `crossing`
    object, and non-crossing edges get NULL.
  - Closures load `attrs` (permit id, reason, named impacts) and
    `backsidewalk_blocks_passage`.
  - `weather_daily` is upserted with no pruning, so history is kept.
- ECCC pipeline: `climate-daily` is fetched for 7025251 and 702S006 (2022 onward) into
  `weather_daily.csv`, in the same run as hourly. Missing values stay NULL;
  `SNOW_ON_GROUND` is NULL outside winter upstream and is not filled with 0.
- **Unchanged, as instructed:** the Overpass source and the highway include-list
  (service/cycleway/corridor still excluded) are both pending a user decision.

**Literal results**
```text
$ alembic upgrade head            (wp_data)
$ alembic current
0002_contract_v1_2_0 (head)
$ alembic downgrade -1
$ alembic current
0001_wp_schema_v1
$ alembic upgrade head
$ alembic current
0002_contract_v1_2_0 (head)

$ uv run wp-ingest eccc   (daily section of stats)
"daily": {"rows": 3550, "non_null": {"total_precip_mm": 3472, "total_snow_cm": 1766,
  "snow_on_ground_cm": 1075, "min_temp_c": 3451, "max_temp_c": 3451},
  "day_range": ["2022-01-01", "2026-11-10"]}

$ load(["osm","entraves","eccc"], force=True)   → wp_data
{'source_id': 'osm', 'noop': False, 'counts': {'node': 6987, 'edge': 16652}}
{'source_id': 'mtl-entraves', 'noop': False, 'counts': {'closure': 167}}
{'source_id': 'eccc-geomet', 'noop': False, 'counts': {'weather_obs': 84249, 'weather_daily': 3550}}
crossing edges with crossing_type: [(5068, 5068)]
non-crossing edges with crossing_type: [(0,)]
crossing_type dist: [('unmarked', 'unknown', 2264), ('traffic_signals', 'unknown', 1440), ('traffic_signals', 'lowered', 438), ('marked', 'unknown', 408), ('unmarked', 'lowered', 224), ('marked', 'lowered', 98)]
highway null / osm_snapshot distinct: [(0, [datetime.datetime(2026, 11, 10, 20, 43, 4, tzinfo=zoneinfo.ZoneInfo(key='Etc/UTC'))])]
closure back/attrs: [(False, 134, 134), (True, 13, 13), (None, 20, 20)]
weather_daily: [('7025251', 1775, datetime.date(2022, 1, 1), datetime.date(2026, 11, 10), 578, 1766), ('702S006', 1775, datetime.date(2022, 1, 1), datetime.date(2026, 11, 10), 497, 1706)]
  (columns: station, rows, first day, last day, snow_on_ground non-null, total_precip non-null)

$ uv run --with ruff ruff check .
All checks passed!
$ uv run --with ruff ruff format --check .
26 files already formatted
$ uv run pytest -v
... (all 40 listed PASSED, including new/extended:)
tests/test_postgis.py::test_migration_up_down_up PASSED        # head → 0001 → head → base → head; v1.2 columns/table present/absent
tests/test_postgis.py::test_constraints_reject_bad_rows PASSED # + weather_daily negative snow rejected
tests/test_postgis.py::test_loader_atomic_and_idempotent PASSED # + crossing_type on every crossing edge, none elsewhere, highway/osm_snapshot set
tests/test_sources.py::test_climate_daily_row_keeps_nulls PASSED
============================= 40 passed in 23.74s ==============================
$ uv run --with pip-audit pip-audit --skip-editable --progress-spinner off
No known vulnerabilities found
```
One test fix during this work: `test_constraints_reject_bad_rows` first failed with
`InFailedSqlTransaction`, because the second violating INSERT ran in the transaction the first
had aborted. The test now uses an autocommit connection; the schema was not the cause.

**Notes for consumers**
- **ML:** use `wp.weather_daily` for precip and snow. 7025251 has `snow_on_ground_cm` on 578
  days (winter only), and 702S006 never reports `total_snow_cm`. `day` is the station-local
  calendar day from `LOCAL_DATE`.
- **Routing/API:** `wp.edge.crossing_type`/`crossing_kerb` map directly to
  `SegmentFeature.crossing`. Kerb is `unknown` on 4 112 of 5 068 crossing edges, which is not
  the same as step-free. `pilot_mini` already carried the same values in its `crossing`
  property; its IDs are unchanged.
- **Closures:** `backsidewalk_blocks_passage`: 13 true, 134 false, 20 null in the pilot bbox.
  This counts differently from my earlier "None 10" figure for `blocks_passage`, because it
  applies the back-sidewalk mapping (`Obstrué` → null).

## Contract v1.3.0 follow-up — 2026-11-10
Merged `integration/winterpath` (51f808c + ML/routing merges) → `7246a24`, no conflicts.
Migration **0003** was added instead of folding into 0002, because 0002 was already applied to
`wp_data`.
- `0003_contract_v1_3_0`: adds `wp.edge.name text` and `wp.community_report.terminal_at
  timestamptz`, plus a partial index on `terminal_at` for the 30-day hard-delete job.
  Backfill uses only existing timestamps (`moderated_at`, or `expires_at` for expired rows),
  never invented ones. There is no CHECK tying `terminal_at` to status, because the API owns
  that write path.
- The graph builder emits `name` (OSM `name` tag), and the loader writes it. The rebuilt
  `pilot_mini` has identical edge and node ids; only `name` and `ingest_run_id` changed. 20 of
  200 fixture edges are named.
- `wp.source` gains `mtl-planif-neige` with status `requires_credentials`. It is **not
  ingested**: no token, and CKAN id `deneigement` was verified as cc-by. Canonical ids are
  unchanged.
- Closures: `attrs.currentstatus` (raw) and `attrs.weekly_schedule` were added (see the
  proposal below).

```text
$ alembic upgrade head → 0003_contract_v1_3_0 (head)
$ alembic downgrade -1 → 0002_contract_v1_2_0
$ alembic upgrade head → 0003_contract_v1_3_0 (head)
load osm/entraves (force): {'node': 6987, 'edge': 16652}, {'closure': 167}
edges with name: [(7444, 16652)]   (all 1382 road edges named)
sources: eccc-geomet active, mtl-311 active, mtl-entraves active,
         mtl-planif-neige requires_credentials, mtl-voirie active, osm active
$ ruff check . → All checks passed!   $ ruff format --check . → 26 files already formatted
$ uv run pytest -q → 40 passed in 15.56s
```
**Migration test:** `test_migration_up_down_up` now runs head → 0002 → head → 0001 → head →
base → head. It asserts that `wp.edge.name` and `wp.community_report.terminal_at` exist at head,
disappear at 0002 (with the v1.2 columns and tables still intact), and come back on re-upgrade:
```text
$ uv run pytest -q
........................................                                 [100%]
40 passed in 50.70s
```

## Proposal — CR-ROUTING-7: `wp.closure.status` vocabulary
Evidence from the 2026-11-10 Entraves file (1 974 permits): `currentstatus` has a single value,
`Permis émis` (1 974), and `permitcategory` is always `Travaux`. Against
2026-11-10T21:00Z, 1 547 permits are inside their date window, **347 have already ended** and 80
haven't started, even though the file is titled "en cours". Also, **942 permits are active only
part of the day** on some weekday, and 1 101 are inactive on at least one weekday.
1. `status` = **publisher lifecycle only**, normalised: `permit_issued` (from `Permis émis`) ·
   `cancelled` · `completed` · `unknown`. Any unmapped value becomes `unknown`, with the raw value
   kept in `attrs.currentstatus` and added to the mapping table once observed. Only
   `Permis émis` has been observed; `cancelled` and `completed` are reserved and nothing maps
   to them yet.
2. **Do not store time-derived states** (active, scheduled, ended) in `status`; they go stale
   between ingests. Instead, the consumer computes `active_at(t)` =
   `status='permit_issued' AND valid_from <= t AND (valid_to IS NULL OR t < valid_to) AND
   attrs.weekly_schedule[weekday(t local America/Montreal)]` permits `t`. Here `active` must be
   `true`; if `all_day` is false, `t` must fall between `start` and `end`; a `null` flag means
   unknown and is never treated as active-safe.
3. Routing applies closures only when `active_at(now)` is true **and** `blocks_passage` is true.
   For unknown activity it should take the conservative branch already defined for unknowns
   (penalise or flag, never treat as clear).
4. If accepted, the Data agent will add migration 0004:
   `CHECK (status IN ('permit_issued','cancelled','completed','unknown'))`, mapping at ingest,
   and optionally a SQL function `wp.closure_active_at(timestamptz)`.

## CR-ROUTING-7 accepted — migration 0004 (2026-11-10)
- **`db/migrations/versions/0004_closure_status.py`** (revises 0003):
  - Maps existing rows (`Permis émis`→`permit_issued`, anything else→`unknown`) and adds
    `closure_status_check CHECK (status IN ('permit_issued','cancelled','completed','unknown'))`.
    NULL is still allowed by the CHECK, but ingest always writes a value.
  - `wp.closure_active_at(c wp.closure, t timestamptz) → boolean` (STABLE). It is three-valued:
    `true` means active at t. `false` means explicitly inactive: outside valid_from..valid_to, an
    inactive weekday, outside the window, or cancelled/completed. `NULL` means unknown: unknown
    status, no valid_from, a missing or non-boolean flag, an unparseable time, or an overnight
    window. Weekday and window use America/Montreal local time. Usage:
    `SELECT … FROM wp.closure c WHERE c.blocks_passage AND wp.closure_active_at(c, now()) IS NOT FALSE`
    (consumers decide the conservative branch for NULL; NULL is never clear).
  - EXECUTE is granted to wp_reader, wp_writer and wp_migrator, and revoked from PUBLIC.
  - Downgrade drops the function and the CHECK, then restores raw values from `attrs.currentstatus`.
- **Deviations from the proposal text (please review):**
  1. `valid_to` is treated as **inclusive** (`t <= valid_to`), not `t < valid_to`, because the
     publisher writes `23:59:59` local as the end. An end time of `23:59` is treated as end of day.
  2. **Overnight windows** (end ≤ start) return `NULL`. Whether `19:00–06:00` on Monday means
     "Mon 19:00 → Tue 06:00" or "both ends on Monday" isn't documented. There are 170 such
     day-windows in the citywide file and none in the pilot bbox.
- **Ingest:** `entraves.CLOSURE_STATUS = {"Permis émis": "permit_issued"}`. Unmapped values
  become `unknown` and are counted in `manifest.stats.unmapped` as `currentstatus=…`. The raw value
  stays in `attrs.currentstatus`.
- **Contract text:** `docs/contracts/data-model.md` on integration/winterpath still describes
  `status` without a vocabulary. **CR-DATA-6 (for the coordinator):** add the enum and
  `wp.closure_active_at` semantics above to the `wp.closure` section. I did not edit
  `docs/contracts/*`.

Literal results (Entraves file of 2026-11-10; `now()` ≈ 2026-11-10 evening UTC):
```text
$ uv run pytest -q            (services/ingestion)
..........................................                               [100%]
42 passed in 116.05s (0:01:56)
$ ruff check .  → All checks passed!
$ alembic upgrade head        (wp_data)  → version_num 0004_closure_status
$ wp-ingest entraves --force  → "noop": false, "closures_in_bbox": 167, "unmapped": {}
$ wp-ingest load --force
{"source_id": "osm", "noop": false, "counts": {"node": 6987, "edge": 16652}}
{"source_id": "mtl-voirie", "noop": false, "counts": {"sidewalk_polygon": 1495}}
{"source_id": "mtl-entraves", "noop": false, "counts": {"closure": 167}}
{"source_id": "mtl-311", "noop": false, "counts": {"report_311_cell": 68214}}
{"source_id": "eccc-geomet", "noop": false, "counts": {"weather_obs": 84249, "weather_daily": 3550}}
-- status:                         permit_issued|167
-- closure_active_at(c, now()) | blocks_passage | count
f|f|45   f|t|19   f||1   t|f|68   t|t|25   t||9
```
At that moment, 25 pilot closures were active **and** blocked passage; 9 were active with an
unknown blocking status. New tests:
- `test_closure_status_and_active_at` runs 12 synthetic cases: the date window, the weekday
  window, a UTC→local weekday shift, a null flag, an overnight window, the 23:59 end, unknown and
  cancelled statuses, and a CHECK rejection.
- `test_status_is_publisher_lifecycle_only` covers the ingest mapping.
- The migration test now also steps head→0003→head.

Note: `ruff format --check db` flags `db/migrations/env.py`. That formatting predates this change,
and I left it untouched.

## Merge integration/winterpath + re-run (2026-11-10)
`git merge --no-edit integration/winterpath` → `Already up to date.` (integration is at `fa8b4ea`,
which is already an ancestor of agent/data).
The first re-run went `4 failed, 38 passed`, with `FATAL: database "wp_data_test" does not exist`.
`test_postgis.py` also exists in four other worktrees through merges, and they all used the fixed
name `wp_data_test`, so a run in one worktree dropped another's database. Fix: the test database is
now `wp_data_test_<pid>`.
```text
$ ruff check . → All checks passed!   $ ruff format --check . → 26 files already formatted
$ uv run pytest -q
..........................................                               [100%]
42 passed in 46.87s
```

## Merge integration/winterpath (contract v1.4.0) + re-run (2026-11-10)
`git merge --no-edit integration/winterpath` fast-forwarded `21ec5c6..dc1ed12`
(`docs/contracts/data-model.md`, `integration-rules.md`: contract v1.4.0, CR-ROUTING-7).
```text
$ uv run pytest -q   (straight after the merge)
42 passed in 53.58s
```
**Conformance fix — migration 0005.** v1.4.0 specifies `t < valid_to` (exclusive), but 0004
shipped `t <= valid_to`, the inclusive deviation proposed above. Because 0004 is already merged
and applied, I left it unchanged. `0005_closure_active_exclusive_end.py` does
`CREATE OR REPLACE` with that one comparison changed. It loads 0004's function text and asserts
that the replaced fragment occurs exactly once. Downgrade restores the 0004 body. The overnight
window → NULL rule from 0004 still stands. It is consistent with "null = unknown" in v1.4.0.
New test cases are `at_end` (t = valid_to → false) and `pre_end` (t = valid_to − 1 min → true).
The migration test now also steps head→0004→head and checks which function body is installed.
```text
$ ruff check . 0005…py → All checks passed!   $ ruff format --check → 27 files already formatted
$ uv run pytest -q
..........................................                               [100%]
42 passed in 50.05s
$ alembic upgrade head (wp_data) → version_num 0005_closure_active_excl_end
-- closure_active_at(c, now()) | blocks_passage | count (unchanged vs 0004 at this time)
f|f|45   f|t|19   f||1   t|f|68   t|t|25   t||9
```
Note: `ruff format` on `db/migrations/versions/` would reflow 0001's `EDGE_KIND` constant, and
`ruff check` flags E501 inside 0001's SQL. Both predate this change. I reverted the reflow so that
0001 stays byte-identical.

## Contract v1.5.0 follow-up — Geofabrik, path policy, CR-ML-1 (2026-11-10)
`git merge --no-edit integration/winterpath` merged `bbae7d3` (contract v1.5.0) as `d69c717`. No
conflicts.

### (1) OSM source: Geofabrik, with no public Overpass in the pipeline
- **New `osm/geofabrik.py`; `osm/overpass.py` deleted.**
  - `quebec-latest.osm.pbf` is resolved to its dated redirect target and cached under that name.
    The redirect target is
    `https://download.geofabrik.de/north-america/canada/quebec-261108.osm.pbf`.
  - The file is checked against Geofabrik's `.md5`, and a mismatch is fatal (tested).
  - The file is clipped with **pyosmium 4.3.2** in two streaming passes. Pass 1 indexes node
    locations in C++ and only highway ways reach Python. Pass 2 runs an IdFilter over the needed
    nodes.
  - Clip semantics replicate the old Overpass query: a way is kept if any segment intersects the
    bbox, and the whole way is kept. A way that crosses the bbox with no node inside it is kept
    (tested).
  - The output keeps the Overpass JSON shape, so `build_graph` is unchanged.
- **Provenance.** The URL, Last-Modified, PBF header `osmosis_replication_timestamp`, MD5, SHA-256
  and fetched_at go into the manifest and **`wp.ingest_run.log.provenance`**. For that,
  `db_load._run_log` now copies `manifest.provenance` into the log.
  ```text
  url  https://download.geofabrik.de/north-america/canada/quebec-261108.osm.pbf
  Last-Modified  Mon, 09 Nov 2026 00:37:54 GMT   osm_replication_timestamp  2026-11-08T21:21:00Z
  md5  4aa2c6163b2c7121113238feec9e1328   size 1 166 570 375 B
  sha256  76f100e41397bbc3428ed357b2c1f91d3f8d3f2663b335c34dfb3321e9614768
  clip: 6 853 ways, 21 273 nodes, 0 missing nodes   (wp-ingest osm --force: 1:52.77 wall)
  ```
- **Comparison with the Overpass snapshot** (`data/qa/osm_source_comparison.json`, built with
  both policies so source and policy effects stay separate):
  - **Source effect: none.** Overpass (2026-11-10T20:43:04Z) and the Geofabrik clip
    (2026-11-08T21:21:00Z) contain the same 6 853 ways. Way tags and node lists are identical, and
    so are all 21 273 nodes. Under the old policy both builds give **identical** results: 16 652
    edges and 6 987 nodes, with 0 IDs differing.
  - **Policy effect** (Geofabrik, old→new policy): 16 642 edge IDs are kept, 10 disappear and 204
    appear. Node IDs: 6 987 kept, 55 added.
    - The 10 removed IDs are segments of existing ways that are now split at nodes shared with a
      newly included service or cycleway way. This follows the documented split rule; it is not a
      change in the ID scheme.
    - Kept edges have unchanged geometry.
  - The edge-ID stability tests (two builds; shuffled element order) are kept. They are joined by
    `test_clip_reproduces_graph_and_edge_ids`. That test writes a PBF from the committed real
    extract, clips it, and checks that the edge and node ID lists match exactly.

### (2) Path policy
`graph.CONDITIONAL_HIGHWAYS = {service, cycleway}` are included only when `foot ∈ {yes, designated,
permissive}`. `corridor` stays excluded. A cycleway with foot permission has `edge_kind = path`
(shared-use path); a service road has `other`.

| | Overpass / old policy | **Geofabrik / v1.5.0** |
|---|---|---|
| ways included | 4 936 | **4 975** (+39: 38 service, 1 cycleway) |
| nodes | 6 987 | **7 042** |
| directed edges | 16 652 | **16 846** (+service/yes 110, service/permissive 66, cycleway/designated 8; +10 from re-splits) |
| components | 159 | **145** |
| largest component (nodes / length) | 91.57 % / 97.11 % | **93.24 % / 97.86 %** |
| gaps | 351 (193 near-miss + 158 component) | **336 (192 + 144)** |
| excluded: service / cycleway without foot permission | 983 / 150 | **946 / 148** |

**Needs a ruling (CR-DATA-7):** 6 of the added ways carry `access=private|no` *and* an explicit
`foot=yes|permissive`: 112854780, 503388659 (Rue Kimberley), 1296208357, 1379125200,
1460735759 and 1460735762. They are mostly driveways. The v1.4 rule, in OSM semantics and covered
by an existing test, is that an explicit foot tag overrides `access`, so these are **included**.
v1.5.0 also says "`access=private|no` everywhere" is excluded. If that means "even with foot=yes",
it is a one-line change, and I'll make it on request.

### (3) CR-ML-1: `wp.report_311_cell.nature`
- **Migration `0006_report_311_nature`** (revises 0005):
  - Adds `nature NOT NULL CHECK IN (requete, plainte, information, commentaire)` and
    `CHECK category IN (sidewalk_slippery, roadway_slippery, snow_clearing, snow_dumping)`.
  - The PK becomes `(h3, day, category, nature)`.
  - Upgrade **deletes** existing aggregates. They mix natures and can't be split; inventing a
    nature isn't an option. The table is derived data and is rebuilt by `wp-ingest 311 && load`.
  - Downgrade is exact: it sums n over natures back into the old PK (tested with synthetic rows:
    2 + 1 + 5 → 8).
- **Ingest:** `r311.normalize_nature` matches case- and accent-insensitively ("Requête" →
  `requete`). Any other value is skipped and counted as `unknown_nature`, never guessed. The
  pipeline checksum includes the nature map.
- Observed natures in the whole file: Requete 1 725 024, Information 1 487 690, Commentaire
  29 967, Plainte 28 936.
- **Rebuilt (pilot-independent, citywide):**
  - 80 614 winter reports → 70 427 rows (h3×day×category×nature) in 2 678 cells, 2022-01-01 to
    2026-11-07.
  - By nature in DB: requete 61 067 rows / 70 574 reports, plainte 2 631 / 2 714, commentaire
    6 729 / 7 326, **information 0**. Winter information requests carry no location, consistent
    with the publisher note.
  - Label view (requete + plainte summed, k-anon checked **after** summing): 63 112 cell-days, of
    which 61 347 have n<3.

### pilot_mini regenerated from the Geofabrik build
200 edges / **92 nodes** (was 88), `simulated:false`, `osm_snapshot` 2026-11-08T21:21:00Z.
`metadata.json` now has `osm_raw_sha256` (the PBF sha256), `osm_pipeline_checksum` and
`osm_source` (provider, URL, Last-Modified, replication timestamp, MD5). ATTRIBUTION now names
Geofabrik.

**Heads-up for routing/api/frontend:** only **40 of 200** fixture edge IDs are unchanged, even
though 99.9 % of full-graph IDs are stable. The fixture is the first 200 edges by network distance
from the anchor, and the newly included service paths (several `foot=permissive` around McGill)
change which edges are nearest. Tests that hard-code fixture edge IDs need updating.

### Commands (literal)
```text
$ wp-ingest osm --force       → noop false; nodes 7042, directed_edges 16846, components 145, gap_count 336
$ wp-ingest voirie --force    → sidewalk match 0.9411 (4890/5196); all 0.424 (7142/16846)
$ wp-ingest fixture --force   → {'edge_count': 200, 'node_count': 92}
$ wp-ingest 311 --force       → cells_rows 70427, distinct_cells 2678, label_cell_days 63112
$ alembic upgrade head (wp_data) → 0006_report_311_nature
$ wp-ingest load
{"source_id": "osm", "noop": false, "counts": {"node": 7042, "edge": 16846}}
{"source_id": "mtl-voirie", "noop": false, "counts": {"sidewalk_polygon": 1495}}
{"source_id": "mtl-entraves", "noop": true}
{"source_id": "mtl-311", "noop": false, "counts": {"report_311_cell": 70427}}
{"source_id": "eccc-geomet", "noop": true}
$ ruff check . → All checks passed!     $ ruff format --check . → 27 files already formatted
$ uv run pytest -q
................................................                         [100%]
48 passed in 48.08s
$ pip-audit (uv export) → No known vulnerabilities found   (new dep: osmium 4.3.2)
```
QA: `data/qa/osm_pilot_gaps.json` (336), `data/qa/pipeline_stats.json` (refreshed with
`osm_source` and `graph_policy`), and `data/qa/osm_source_comparison.json` (new).

### Merge integration/winterpath (d04da54 + 2d37f32), post-checkpoint
`git merge --no-edit integration/winterpath` → `bea2d96`. This includes `d04da54` (data@abcea83,
routing@32e69f6, platform@89477f5) and `2d37f32` (`.env.example` weather names). No conflicts. The
merge touched no file under `data/`, `db/`, `services/ingestion/` or `docs/contracts/`.
```text
$ ruff check . → All checks passed!
$ uv run pytest -q
................................................                         [100%]
48 passed in 51.46s
```

## Contract v1.6.0 — CR-ML-2 + CR-DATA-7 (2026-11-11)
`git merge --no-edit integration/winterpath` → `69bd9e6` (integration `a292b63`, tag
`contract-v1.6.0`). No conflicts. **pilot_mini was not regenerated:** `data/fixtures/` is
byte-identical to `ee5f1fc`, as the coordinator asked.

### CR-ML-2: alley categories (folded into 0006)
- `0006_report_311_nature` category CHECK now has six values. The two new ones are
  `snow_clearing_alley` ← Déneigement ruelle and `snow_dumping_alley` ← Dépôt neige-ruelle.
  `r311.WINTER_CATEGORIES` and `CATEGORY_VALUES` are updated to match.
- `wp_data`:
  - `alembic downgrade 0005_closure_active_excl_end` collapsed to **68 214 rows / 80 614
    reports**. That is exactly the pre-0006 (v1.4) aggregate, which confirms the downgrade sum.
  - `alembic upgrade head` → 0006 with the six-value CHECK, then `wp-ingest 311 --force` and
    `load`.
- **Per-category counts** (citywide, 2022-01-01 → 2026-11-07; 80 614 geolocated winter reports →
  70 428 rows in 2 678 cells):

| category | reports (all natures) | requete | plainte | commentaire | DB rows |
|---|---|---|---|---|---|
| sidewalk_slippery | 10 391 | 10 136 | 93 | 162 | 9 328 |
| roadway_slippery | 9 159 | 9 064 | 41 | 54 | 8 299 |
| snow_clearing | 55 434 | 45 889 | 2 517 | 7 028 | 47 446 |
| snow_dumping | 5 603 | 5 464 | 60 | 79 | 5 328 |
| **snow_clearing_alley** | **7** | 1 | 3 | 3 | 7 |
| **snow_dumping_alley** | **20** | 20 | 0 | 0 | 20 |

  No `information` rows exist in any category; they have no location. Label cell-days
  (requete + plainte, summed before the k-anon check): 63 115, of which 61 352 have n<3.
  **Note for ML:** each alley category is too small to train on alone (8 and 20 label reports in
  ~5 years). Summing them into the parent category restores the v1.5 meaning, per the contract.

### CR-DATA-7: foot permission overrides access
- `graph.exclusion_reason`: `access=private|no` excludes **unless**
  `foot ∈ {yes, designated, permissive}`. `foot=no|use_sidepath` (and `private`) still always
  exclude.
- **Rule tightened:** the v1.5 code let *any* `foot` tag (for example `foot=customers`) override
  access. Now only the three explicit permissions do.
- A new stat `ways_admitted_by_foot_over_access` is reported. Tests cover every combination,
  including non-permission foot values.
- **Ways admitted by the rule: 12** (6 `footway` with `access=no, foot=yes`; 6 `service` as listed
  under CR-DATA-7 above). In this clip no way has `access=private|no` with any foot value other
  than yes / permissive / no / use_sidepath, so tightening the rule changes no output.
- `GRAPH_POLICY` (part of the OSM run checksum) is bumped to `v1.6.0` and includes the override
  set. The rebuild is therefore recorded as a new run: input checksum `1a606553…`, with
  `wp.ingest_run.log.provenance` unchanged (`quebec-261108.osm.pbf`).

### Edge-ID stability (full graph, v1.5 build → v1.6 build)
```text
edges v1.5 16846  v1.6 16846  common 16846  removed 0  added 0
nodes v1.5 7042   v1.6 7042   common 7042
attribute/geometry diffs on common edges (excluding ingest_run_id): 0
ways_included 4975, components 145, gap_count 336 (unchanged)
```

### Commands (literal)
```text
$ alembic downgrade 0005_closure_active_excl_end  → wp.report_311_cell: 68214 rows, sum(n) 80614
$ alembic upgrade head                            → 0006_report_311_nature; 0 rows
$ wp-ingest osm --force     → noop false, checksum 1a606553fa4def64…, directed_edges 16846
$ wp-ingest voirie --force  → all edges 7142/16846 matched (0.424)
$ wp-ingest 311 --force     → cells_rows 70428, distinct_cells 2678
$ wp-ingest load
{"source_id": "osm", "noop": false, "counts": {"node": 7042, "edge": 16846}}
{"source_id": "mtl-voirie", "noop": false, "counts": {"sidewalk_polygon": 1495}}
{"source_id": "mtl-entraves", "noop": true}
{"source_id": "mtl-311", "noop": true}        ← already loaded (70428 rows) by the previous load
{"source_id": "eccc-geomet", "noop": true}
$ ruff check . → All checks passed!   $ ruff format --check . → 27 files already formatted
$ uv run pytest -q
..................................................                       [100%]
50 passed in 41.51s
$ git status --short data/fixtures   → (empty)
```

## Merge integration/winterpath + re-run (2026-11-11)

`integration/winterpath` is still at `a292b63` (contract v1.6.0), which is already merged as `69bd9e6`.
There was nothing new to merge, and HEAD stays at `f6eb3b2`. `pilot_mini` is untouched: `data/fixtures/`
is identical to `ee5f1fc`.

```
$ git merge --no-edit integration/winterpath
Already up to date.
$ cd services/ingestion && uv run pytest -q
..................................................                       [100%]
50 passed in 25.34s
$ uv run ruff check .                  → All checks passed!
$ uv run ruff format --check src tests → 26 files already formatted
$ git diff --stat ee5f1fc HEAD -- data/fixtures/   → (empty)
```

## Merge integration/winterpath @ 6a712e9 (all five agents merged) + re-run (2026-11-11)

The merge was clean: merge commit `044f747`, with no conflicts. Integration includes data `f6eb3b2` via `3625bd7`.
The merge changed nothing under `data/`, `db/`, `services/ingestion/` or `docs/contracts/`.

```
$ git merge --no-edit integration/winterpath   → 044f747 Merge branch 'integration/winterpath' into agent/data
$ cd services/ingestion && uv run pytest -q
..................................................                       [100%]
50 passed in 54.60s
$ uv run ruff check .                  → All checks passed!
$ uv run ruff format --check src tests → 26 files already formatted
$ uvx pip-audit -r <uv export --frozen> → No known vulnerabilities found
$ alembic current (wp_data)            → 0006_report_311_nature (head)
$ git diff --stat ee5f1fc HEAD -- data/fixtures/   → (empty; pilot_mini unchanged)
$ scripts/check-ownership.sh data      → ownership OK for agent/data
```

## Hosted DB: `load --weather-since` + Supabase initial-load runbook (2026-11-11)

- **`wp-ingest load --weather-since YYYY-MM-DD`** (`db_load._weather`, `cli.py`):
  - Bounds `wp.weather_obs` to `observed_at >= date 00:00 America/Montreal`. Older CSV rows are
    skipped, and older table rows are pruned in the same transaction.
  - `weather_daily` is not bounded.
  - The cutoff is part of the load checksum (`<checksum>|weather_since=<date>`), so bounded and
    full loads never no-op each other.
  - The diagnostic counts `_weather_obs_skipped_before_since` and `_weather_obs_pruned_before_since`
    go into `ingest_run.log`. `record_count` excludes `_`-prefixed keys.
  - The new test `test_weather_since_bounds_and_prunes` covers the local-midnight boundary, both
    sides, pruning, `record_count`, the bounded no-op and the full reload restoring all rows.
- **Size**, measured on fresh scratch DBs, each migrated to 0006 and loaded from the current
  `data/processed`, followed by `VACUUM ANALYZE`. The scratch DBs were dropped afterwards and
  `wp_data` was not touched.

  | `--weather-since` | weather_obs rows | weather_obs | all `wp.*` | whole DB |
  |---|---|---|---|---|
  | none (2022-01-01 →) | 84,249 | 10 MB | 35 MB | 51 MB |
  | 2025-11-01 | 17,160 | 2.2 MB | 27 MB | 43 MB |
  | 2026-08-01 | 4,061 | 0.6 MB | 26 MB | 41 MB |

  - An empty PostGIS DB is about 16 MB, of which `spatial_ref_sys` is 7 MB. Supabase's own
    overhead was not measured.
  - Local `wp_data` (79 MB) is inflated by dead tuples from repeated rebuilds. A fresh full load
    is 51 MB.
  - Pruning an existing DB does not shrink it without `VACUUM FULL`, so the hosted DB should be
    loaded bounded from the start.
  - Weather is only 10 MB of the 35 MB in `wp.*`; the rest is mostly `report_311_cell` and `edge`.
- **Runbook** in `services/ingestion/README.md`:
  - Bootstrap as the Supabase admin: group roles, `wp_migrate`/`wp_loader` login users, CREATE on
    the database and `public`, PostGIS, and a search_path note if PostGIS lives in `extensions`.
  - Migrate with `options=-c role=wp_migrator` over the direct connection.
  - Load as `wp_writer` from `data/processed` with no network calls.
  - Rehearsed on a local scratch DB without superuser rights: head reached, `wp_migrator` owns all
    objects, 5/5 sources succeeded.
  - **Not run against Supabase.** Login users and passwords are Platform's to create.

```
$ uv run pytest -q
...................................................                      [100%]
51 passed in 32.71s
$ uv run ruff check . → All checks passed!
# rehearsal (scratch DB wp_data_rolecheck, dropped afterwards)
$ alembic -x url="…?options=-c%20role%3Dwp_migrator" current → 0006_report_311_nature (head)
  owners: tables wp_migrator|12, schema wp_migrator, closure_active_at wp_migrator, alembic_version wp_migrator
$ DATABASE_URL="…?options=-c%20role%3Dwp_writer" wp-ingest load --weather-since 2025-11-01
{"source_id": "eccc-geomet", "noop": false, "counts": {"weather_obs": 17160, "_weather_obs_skipped_before_since": 67089, "_weather_obs_pruned_before_since": 0, "weather_daily": 3550}}
  ingest_run: osm 23888, mtl-voirie 1495, mtl-entraves 167, mtl-311 70428, eccc-geomet 20710 — all succeeded
```

## Contract v1.7.0 — migration 0007 `wp.risk_cell_score` + `wp-ingest load --source` (2026-11-11)

I merged integration `5238c45` as `b3abe51`, with no conflicts. Contract v1.7 adds
`wp.risk_cell_score` and the Supabase deployment notes.

**Migration `0007_risk_cell_score`** (down_revision 0006). It has a single head, and `wp_data` is
now at 0007.

The table has exactly the contract's columns:

| Column | Type | Null |
|---|---|---|
| `h3` | text | NOT NULL |
| `day` | date | NOT NULL |
| `model_id` | text | NOT NULL |
| `layer` | text | NOT NULL |
| `p` | double precision | NOT NULL |
| `scored_at` | timestamptz | NOT NULL, default now() |
| `data_through` | timestamptz | nullable |
| `ingest_run_id` | uuid | nullable FK → `wp.ingest_run` |

- **Keys and index:** PK(h3, day, model_id) and index `risk_cell_score_day_model_idx (day, model_id)`.
- **CHECKs:** `layer IN ('heuristic','model')` and `p BETWEEN 0 AND 1`. NaN is rejected.
- **Grants:** `wp_reader` SELECT only; `wp_writer` SELECT/INSERT/UPDATE/DELETE (DELETE … WHERE
  needs SELECT, an upsert needs UPDATE); `wp_migrator` ALL.
- **Downgrade:** `DROP TABLE`. The rows are derived and can be regenerated by the scoring job.
- **Choices beyond the contract text:**
  - `p` is NOT NULL because "no score" is expressed as no row, which means `unknown`, never NULL.
  - `data_through` and `ingest_run_id` are nullable. The FK follows every other derived table. If
    ML sets `ingest_run_id`, it must first insert a `wp.ingest_run` row whose `source_id` exists
    in `wp.source`.
- **Test** `test_risk_cell_score_schema_constraints_grants_roundtrip` covers:
  - exact columns and nullability, the PK, the index, and grants
  - layer, p > 1, p < 0, NaN and NULL rejected; the bounds 0 and 1 accepted
  - duplicate key and FK violations
  - a failed partition replace keeps the old day
  - insert and delete as `SET ROLE wp_writer`; delete denied for `wp_reader`
  - 0007 → 0006 → head
- The migration ladder test now also steps head → 0006 → head.

**`wp-ingest load --source <source_id>`**:
- The flag is repeatable. The choices are the canonical ids `osm`, `mtl-voirie`, `mtl-entraves`,
  `mtl-311` and `eccc-geomet`; a pipeline name such as `eccc` is rejected.
- It uses the same `_load` path as a full load: one transaction per source with staging → upsert
  → prune, a failed ingest_run on error, and a no-op on an already-succeeded checksum. It combines
  with `--force` and `--weather-since`.
- `wp-ingest load --help` lists every id in the usage line as one unbreakable token. Tests check
  this at COLUMNS 40, 80 and 200, so `scheduled.yml`'s `grep -- eccc-geomet` holds.
- Tests:
  - `test_cli.py` checks id ↔ loader ↔ registry consistency, selection, dedup and rejects.
  - `test_load_source_cli_loads_only_that_source` checks that only eccc-geomet loads while
    osm_pilot output is present, and that a rerun is a no-op.

**For Platform:** `wp-ingest eccc --refresh` fetches hourly data from 2022 onward. Without
`--weather-since`, the scheduled `load --source eccc-geomet` grows the hosted `wp.weather_obs` to
the full history (about 10 MB). Suggested change:
`wp-ingest load --source eccc-geomet --weather-since "$(date -u -d '365 days ago' +%F)"`.

**Runbook:** the README now follows the v1.7 deployment notes: PostGIS `WITH SCHEMA extensions`
and `search_path = public, extensions` on the login roles. I re-rehearsed it locally on a scratch
DB, which has since been dropped. Not run against Supabase.

```
$ git merge --no-edit integration/winterpath   → b3abe51
$ uv run pytest -q
.............................................................            [100%]
61 passed in 27.35s
$ uv run ruff check . ../../db/migrations/versions/0007_risk_cell_score.py → All checks passed!
$ alembic heads → 0007_risk_cell_score (head)
$ alembic upgrade head (wp_data); alembic current → 0007_risk_cell_score (head)
$ wp-ingest load --source eccc-geomet (wp_data) → {"source_id": "eccc-geomet", "noop": true}
# rehearsal, scratch DB, PostGIS in `extensions`, roles via options:
  postgis schema → extensions; current → 0007_risk_cell_score (head); tables wp_migrator|13
  wp.edge.geom → extensions.geometry(LineString,4326)
  load --source osm --source eccc-geomet --weather-since 2025-11-01 as wp_writer
    → osm 23888 succeeded, eccc-geomet 20710 succeeded (only those two runs)
  SET ROLE wp_writer; INSERT/DELETE wp.risk_cell_score → INSERT 0 1 / DELETE 1
```

## Island feasibility (WinterPath 2.0, Wave 1, 2026-11-12) — local only

I merged integration `eaac440`. It was a fast-forward, because integration already contained
`360fdd4`. Everything below is **local**: no Supabase writes, no contract edits, no deploys.
The full machine-readable summary is in `data/qa/island_feasibility.json`.

### → Routing: `wp_island` is loaded
- **Database:** `wp_island`, on the shared container (port 55432). It is migrated to
  `0007_risk_cell_score (head)`, the same schema as `wp_data`.
  - Use the same credentials as `wp_data`, i.e. `DATABASE_URL` from `.env.local` with the database
    name `wp_island`.
- **Contents:**
  - `wp.node`: 257,542 rows.
  - `wp.edge`: 650,920 directed rows, 10,207.7 km undirected.
  - One `wp.ingest_run`: `osm`, succeeded, checksum `c5c9e2b3…`.
  - Every other table is empty. There are no closures, sidewalk polygons or risk scores yet.
- **Snapshot:** the same as the pilot (`quebec-261108.osm.pbf`, 2026-11-08T21:21:00Z), built with
  the same rules (`GRAPH_POLICY` v1.6.0).
  - **16,748 of the pilot's 16,846 edge IDs (99.42%)** exist in `wp_island` with identical
    geometry.
  - The other 98 lie on the pilot bbox border. There, the island build splits ways at junctions
    with roads outside the pilot bbox, as the stable-ID rule says it should.
- **Columns:** `component_id` is island-wide (0 = largest). `sidewalk_polygon_ids` is empty: voirie
  matching is not run for the island.
- **Reload:** `DATABASE_URL=…/wp_island uv run wp-ingest load --source osm --osm-graph island`
  (from `services/ingestion`).

### 1. Boundaries
- **`limites-administratives-agglomeration`** (WGS 84 GeoJSON, CC BY 4.0, CKAN modified 2026-11-01)
  - sha256 `c2357160a8dce9039283cae02408cf48f02c20fd183fb75b93f80234555f70ef`
  - 34 units: 19 arrondissements and 15 villes liées.
- **`archipel-agglomeration`** (GPKG, EPSG:2950, photogrammetry 2020, CC BY 4.0)
  - sha256 `687843fa0a55e555d8c94fc154c17d803feb36524ce603f58ac4b3ec70cd856d`
  - One MultiPolygon, which explodes into **187 islands**.
- Both are cached under `data/raw/boundaries/` (git-ignored).
- `wp-ingest boundaries` writes `data/processed/boundaries/`: `main_island`, `islands` (id, area,
  centroid, admin units, `is_main_island`), `units_on_land` (each unit clipped to the main island
  and to other islands, flagged separately) and `admin_limits`.
- **Main island:** 470.55 km². The other 186 islands total 30.68 km².
  - Islands of 0.1 km² or more, identified by geometry and admin unit only (no names invented):

    | Island | Area | Admin unit | Comment |
    |---|---|---|---|
    | isl-0001 | 22.76 km² | L'Île-Bizard-Sainte-Geneviève | |
    | isl-0002 | 3.80 km² | Verdun | |
    | isl-0003 | 1.31 km² | Ville-Marie | |
    | isl-0004 | 1.23 km² | Ville-Marie | |
    | isl-0005 | 0.48 km² | LaSalle | |
    | isl-0006 | 0.18 km² | Dorval / L'Île-Dorval | |
    | isl-0007, isl-0008 | 0.14 and 0.13 km² | Rivière-des-Prairies-Pointe-aux-Trembles | |
    | isl-0009 | 0.12 km² | LaSalle | |
    | isl-0010 | 0.11 km² | Ahuntsic-Cartierville | |

  - Every unit has main-island land except **L'Île-Dorval**.
  - Laval and Longueuil appear in neither dataset, so they are never labelled island.

### 2. Island graph (`wp-ingest osm-island`)
- **Area rule** (documented in `osm/island.py`):
  - Clip to all agglomeration land, keeping complete ways.
  - Apply the existing inclusion policy unchanged.
  - Keep a connected network only if it has at least one node on the **main** island. Other
    islands are therefore included only where mapped ways connect them; isolated networks are
    dropped and counted.
  - Label every node `main_island`, `other_island` or `outside_agglomeration_land`.
  - No edges were invented, and prohibited ways are excluded, not penalised.
- **Clip:** 268,011 highway ways and 952,235 nodes. No missing nodes or locations.
- **Component rule:**
  - 184,464 candidate ways; 184,192 kept.
  - 272 ways in **87 networks** not connected to the main island were dropped.
  - After the build, 0 components lack a main-island node.
- **Result:**
  - **257,542 nodes**, **650,920 directed edges** (325,460 segments).
  - **10,207.7 km** of network (undirected), 62,044 crossing nodes.
- **Nodes by land:**
  - Main island: 252,103.
  - Other islands: 5,372, mostly isl-0002 (3,309), isl-0001 (1,127), isl-0003 (573) and isl-0004 (292).
  - Outside agglomeration land: 67.
- **Policy effects:**
  - The foot-over-access rule admitted 240 ways: service 145, path 53, footway 38, residential 2, steps 2.
  - The largest exclusions are `service` without explicit foot permission (47,689 ways) and
    `foot=use_sidepath` (18,128); the full breakdown is in the QA JSON.
- **Connected components: 1,778.**
  - The largest has **250,008 nodes (97.07%)** and **10,088.6 km (98.83% of length)**.
  - By size in directed edges: 1–2 edges: 857; 3–10: 723; 11–50: 177; over 50 (excluding the
    largest): **20**.
  - Gaps reported, never repaired: 3,977, of which 2,200 are near-miss dangling endpoints and 1,777
    are disconnected components. The list is in `data/processed/osm_island/gaps.json`.

  Components of more than 50 edges, other than the largest:

  | id | directed edges | km | unit | centroid |
  |---|---|---|---|---|
  | 1 | 664 | 8.20 | Côte-des-Neiges-NDG | -73.65388, 45.50196 |
  | 2 | 252 | 0.75 | Ville-Marie | -73.58151, 45.51016 |
  | 3 | 240 | 1.93 | Sainte-Anne-de-Bellevue | -73.93637, 45.42659 |
  | 4 | 172 | 1.68 | Sainte-Anne-de-Bellevue | -73.93866, 45.40677 |
  | 5 | 166 | 1.10 | Mercier-Hochelaga-Maisonneuve | -73.54317, 45.58770 |
  | 6 | 138 | 1.19 | Pointe-Claire | -73.79693, 45.48089 |
  | 8 | 124 | 0.84 | Sainte-Anne-de-Bellevue | -73.94960, 45.41228 |
  | 7 | 122 | 2.36 | Rosemont-La Petite-Patrie | -73.56722, 45.56155 |
  | 9 | 92 | 0.68 | Dorval | -73.74090, 45.45410 |
  | 14 | 90 | 0.88 | Saint-Laurent | -73.67299, 45.51589 |
  | 10 | 86 | 0.61 | Pointe-Claire | -73.80835, 45.43429 |
  | 12 | 72 | 0.50 | Sainte-Anne-de-Bellevue | -73.93905, 45.40843 |
  | 11 | 70 | 0.38 | Pierrefonds-Roxboro | -73.85599, 45.48563 |
  | 13 | 66 | 0.24 | Dorval | -73.74059, 45.45277 |
  | 18 | 62 | 2.02 | Sainte-Anne-de-Bellevue | -73.93892, 45.42997 |
  | 24 | 58 | 1.14 | Ville-Marie | -73.54351, 45.50539 |
  | 15 | 56 | 0.28 | Senneville (main 8 / other island 16 / off-land 5 nodes) | -73.96907, 45.41845 |
  | 17 | 56 | 0.27 | Côte-des-Neiges-NDG | -73.62877, 45.45690 |
  | 16 | 54 | 0.27 | Pierrefonds-Roxboro | -73.91949, 45.46041 |
  | 20 | 52 | 0.40 | Ahuntsic-Cartierville | -73.67355, 45.53590 |

  These are mapped networks with no mapped pedestrian link to the main network, for example
  campuses, parks, or areas reached only by excluded service roads. They are reported, not
  repaired.

- **Per unit.** Nodes are assigned by location; edges and km by edge midpoint against the
  unclipped admin limits. "Trottoir" is the number of voirie trottoir polygons in the unit.

  | Unit | Type | Nodes | Directed edges | km | Trottoir | Trottoir / km |
  |---|---|---|---|---|---|---|
  | Ahuntsic-Cartierville | Arr. | 22,643 | 56,516 | 745.1 | 5,548 | 7.45 |
  | Anjou | Arr. | 4,076 | 10,352 | 202.1 | 2,272 | 11.24 |
  | Côte-des-Neiges-NDG | Arr. | 18,079 | 45,624 | 638.4 | 4,467 | 7.00 |
  | L'Île-Bizard-Sainte-Geneviève | Arr. | 1,944 | 4,826 | 156.0 | 1,220 | 7.82 |
  | LaSalle | Arr. | 10,357 | 25,798 | 420.5 | 3,016 | 7.17 |
  | Lachine | Arr. | 5,954 | 14,750 | 240.6 | 2,719 | 11.30 |
  | Le Plateau-Mont-Royal | Arr. | 11,335 | 31,152 | 415.6 | 3,611 | 8.69 |
  | Le Sud-Ouest | Arr. | 17,729 | 43,776 | 468.0 | 4,487 | 9.59 |
  | Mercier-Hochelaga-Maisonneuve | Arr. | 16,554 | 44,642 | 716.7 | 6,185 | 8.63 |
  | Montréal-Nord | Arr. | 4,050 | 11,076 | 241.2 | 3,122 | 12.94 |
  | Outremont | Arr. | 3,394 | 9,582 | 148.8 | 1,091 | 7.33 |
  | Pierrefonds-Roxboro | Arr. | 7,256 | 17,238 | 375.0 | 3,956 | 10.55 |
  | Rivière-des-Prairies-Pointe-aux-Trembles | Arr. | 7,947 | 22,032 | 616.4 | 6,136 | 9.95 |
  | Rosemont-La Petite-Patrie | Arr. | 18,709 | 50,384 | 707.6 | 4,197 | 5.93 |
  | Saint-Laurent | Arr. | 16,939 | 39,304 | 561.3 | 5,788 | 10.31 |
  | Saint-Léonard | Arr. | 6,356 | 16,630 | 320.1 | 3,021 | 9.44 |
  | Verdun | Arr. | 9,331 | 21,930 | 267.4 | 2,316 | 8.66 |
  | Ville-Marie | Arr. | 20,586 | 52,080 | 621.4 | 4,970 | 8.00 |
  | Villeray-Saint-Michel-Parc-Extension | Arr. | 15,567 | 39,080 | 507.7 | 4,423 | 8.71 |
  | Baie-D'Urfé | V.l. | 1,461 | 3,084 | 60.7 | 172 | 2.83 |
  | Beaconsfield | V.l. | 2,482 | 5,830 | 154.5 | 704 | 4.56 |
  | Côte-Saint-Luc | V.l. | 2,256 | 5,868 | 106.8 | 1,191 | 11.15 |
  | Dollard-des-Ormeaux | V.l. | 4,121 | 10,080 | 254.8 | 2,684 | 10.53 |
  | Dorval | V.l. | 4,623 | 10,276 | 175.9 | 2,186 | 12.43 |
  | Hampstead | V.l. | 1,282 | 3,974 | 69.9 | 402 | 5.75 |
  | Kirkland | V.l. | 3,060 | 7,174 | 151.1 | 1,915 | 12.67 |
  | L'Île-Dorval | V.l. | 0 | 0 | 0.0 | **0** | — |
  | Mont-Royal | V.l. | 3,600 | 9,098 | 159.5 | 1,673 | 10.49 |
  | Montréal-Est | V.l. | 811 | 2,028 | 57.4 | 708 | 12.33 |
  | Montréal-Ouest | V.l. | 980 | 2,592 | 42.3 | 378 | 8.94 |
  | Pointe-Claire | V.l. | 7,226 | 17,210 | 314.8 | 2,880 | 9.15 |
  | Sainte-Anne-de-Bellevue | V.l. | 2,811 | 6,268 | 95.5 | 632 | 6.62 |
  | Senneville | V.l. | 416 | 890 | 31.6 | 73 | 2.31 |
  | Westmount | V.l. | 3,544 | 9,642 | 155.5 | 1,094 | 7.04 |
  | outside the agglomeration limits (bridge ends) | — | 63 | 134 | 7.6 | — | — |

- **Build time and memory** (`/usr/bin/time -l`, Apple M4, 10 cores, 16 GB):
  - `wp-ingest osm-island`: **295 s wall time, 2.58 GB peak RSS**. Stages: clip 106 s (two
    passes over the 1.17 GB PBF), component filter 3 s, `build_graph` 95 s, write GeoJSON 79 s.
  - Load into `wp_island`: **379 s wall time, 1.91 GB peak RSS**.
  - Outputs (git-ignored): `edges.geojson` 523 MB, `nodes.geojson` 101 MB, clip cache 136 MB.
- **Correction during the run.** The first build resolved Geofabrik's "latest" redirect, which now
  points to `quebec-261110.osm.pbf`. It downloaded that 1.17 GB file (cached, git-ignored, MD5
  verified) and built from it.
  - I then **pinned** the island build to the pilot's PBF URL from the `osm_pilot` manifest and
    rebuilt from `quebec-261108`, as the brief requires. All figures above come from 261108.
  - The 261110 file is still in `data/raw/osm/geofabrik/`. It can be deleted, or kept for the
    next pilot refresh: plain `wp-ingest osm` would now resolve to 261110, but it has not been run.

### 3. Database size (local `wp_island`, after `VACUUM ANALYZE`, `pg_total_relation_size` including indexes)

| Table | Rows | Heap | Indexes | Total |
|---|---|---|---|---|
| `wp.edge` | 650,920 | 199.0 MB | 102.4 MB | **301.5 MB** (486 B/edge) |
| `wp.node` | 257,542 | 29.5 MB | 26.3 MB | **55.8 MB** |
| other `wp.*` (empty) | — | — | — | 0.4 MB |
| **whole DB** | | | | **374 MB** (391,655,907 B) |

- Edge indexes: `edge_pkey` 37 MB, `edge_geom_gix` 27 MB, `edge_to_idx` 21 MB, `edge_from_idx`
  14 MB, `edge_component_idx` 4 MB.
- Node indexes: `node_pkey` 16 MB, `node_geom_gix` 10 MB.

**Projected Supabase total.** The base is the live hosted size of **49 MB** from the coordinator's
audit. From it I subtract the pilot graph, measured on a fresh local load: `edge` 8.1 MB plus
`node` 1.6 MB, 9.7 MB in all. Measured components are marked; extrapolations are marked
*projected*.

| Scenario | Size |
|---|---|
| Hosted today | 49 MB |
| + island graph, replacing the pilot graph (measured) | **≈ 397 MB** |
| + island `risk_cell_score`: 4,365 H3 r9 cells × 30 days × 1 model = 130,950 rows (measured with placeholder rows in a scratch DB, then dropped) | +25 MB per model → **≈ 422 MB** |
| + island-wide voirie sidewalk polygons: 89,249 trottoir + 11,187 îlot × 1.36 kB/row, the pilot's measured rate (*projected*) | +≈131 MB → **≈ 553 MB, over the 500 MB Free limit** |
| + address search (section 4) | +66 MB (Montréal dataset) or +166 MB (RQA) |

- **Verdict:** the island graph alone fits in Supabase Free, with about 80–100 MB of headroom
  after one model's scores. Adding island-wide sidewalk polygons, address search or a second model
  takes it over or to the limit. Supabase's own schemas are included in the 49 MB base, since the
  coordinator measured it live.
- **Measured option A:** store each segment once instead of in both directions. That is 325,460
  rows and **152 MB** including the same indexes, against 302 MB, saving **about 150 MB**.
  - This is a **contract change**: `wp.edge` would become undirected, and readers expand it to
    directed edges. It is the coordinator's and owner's decision; I have not done it.
- **Option B, unmeasured:** keep the routing graph out of Postgres. The API would load a compact
  artifact, which is routing's CSR prototype, and the DB would keep only what the API queries.
- **Option C:** a paid tier. This is the owner's decision.

### 4. Sidewalk dataset reach (voirie trottoir)
- The plan assumed voirie trottoir is City of Montréal only. **It is not.**
  - The cached citywide file (89,249 trottoir polygons) has polygons in all 19 boroughs and in
    **14 of the 15 linked municipalities**.
  - **The only linked municipality with no sidewalk polygons is L'Île-Dorval**, which also has no
    pedestrian network connected to the main island.
  - Polygons were assigned to units by representative point; 12 fall outside the limits.
- Coverage density varies: from 2.3 to 4.6 trottoir polygons per network km in Senneville,
  Baie-D'Urfé and Beaconsfield, against 7 to 13 elsewhere.
  - This may reflect real sidewalk scarcity or incomplete mapping. The publisher warns the polygons
    are "not necessarily up to date across the whole territory".
  - It must not be read as sidewalk presence or absence on any given street.
- Polygons stay enrichment only and never create connectivity. They were **not matched** to island
  edges in this wave.

### 5. Place-search assessment (not built)

| | Ville de Montréal "Adresse ponctuelle" | Référentiel québécois des adresses (RQA), MRNF |
|---|---|---|
| Licence | CC BY 4.0 (CKAN `adresses-ponctuelles`) | CC BY 4.0 (Données Québec `referentiel-quebecois-des-adresses`). "Code postal" is noted as an official mark of Canada Post |
| Coverage | All 34 units: 345,969 points, 0 outside the limits, every unit including L'Île-Dorval (61) has points | All of Québec: 5,356,156 rows. Region 06 (the agglomeration): 1,258,169 active rows, all "Certifiée", covering Montréal (19 arrondissements) and all 15 linked municipalities |
| Rows for search | 345,969 (civic **ranges** such as "6215-23", one point per building) | **636,161** distinct civic addresses (number + suffix + street + municipality, ignoring apartment units) |
| Update | "irregular"; last 2026-11-09 | monthly; version 2026-11-01. It replaces Adresses Québec, which is being phased out by the end of 2026 |
| Position quality | not stated per row | per row: Géocodée 374,192; Bâtiment 315,608; **Incertaine 567,733 (45%)**; Centre lot 633 |
| Raw size | CSV 36 MB, sha256 `64cd31f0d01f9e2ade29a0a2fbb7fe618175f41626a32e5795954fcea32cc560` | zip 818 MB (3.16 GB CSV), sha256 `f1e0725894bcfed5690a708c218af80e1a9564be0ce5263efc23ddd1d51450ea` |
| **Measured DB size** (label + point, PK, GIN `gin_trgm_ops` on `lower(label)`, GiST) | **66 MB**: heap 29, trigram 16, GiST 14, PK 7.6 | **166 MB**: heap 74, trigram 53, GiST 25, PK 14 |

- The sizes were measured in a scratch database that has since been dropped. Nothing is in `wp_*`.
- **Query design matters.** A naive `label % '5664 1re avenue'` over the RQA table took **9.2 s**
  locally, because the GIN index returned 214k candidates for a short, common-token query.
  - Production search needs a tokenised or prefix strategy, for example number plus street-name
    prefix plus municipality, or a dedicated search column. That belongs to Wave 2 or 3.
- **Recommendation:**
  - Use RQA, for its monthly updates, per-row position quality, municipality and arrondissement
    columns and clean civic numbers. Display its positioning quality, and never present an
    "Incertaine" point as an exact entrance.
  - The Montréal dataset is smaller (66 MB) but uses ranges and has no quality flag.
  - Neither fits next to the island graph in Supabase Free without option A, B or C.
  - **Not verified:** the RQA user guide PDF is downloaded but could not be text-extracted here,
    because there is no PDF tool. Any terms it adds beyond the CC BY 4.0 dataset licence have not
    been read.
- Attribution, if used: "Ministère des Ressources naturelles et des Forêts — Référentiel québécois
  des adresses (CC BY 4.0)" or "Ville de Montréal — Adresse ponctuelle (CC BY 4.0)".

### Code (agent/data)
- `sources/boundaries.py` (`wp-ingest boundaries`) and `osm/island.py` (`wp-ingest osm-island`,
  pinned to the pilot's PBF).
- `geofabrik.clip_area` and `area_predicate`. The pilot bbox clip is unchanged and its tests pass.
- `load --osm-graph {pilot,island}`, default `pilot`.
- `tests/test_island.py` covers: largest part = main island, units clipped to land, segment
  semantics for the area predicate, the component rule (bridged island kept, isolated island
  dropped, excluded ways still counted), and off-land nodes never labelled island.
- `test_cli` covers the `--osm-graph` wiring.
- `data/fixtures/` is unchanged.

```
$ git merge --no-edit integration/winterpath → fast-forward to eaac440
$ uv run wp-ingest boundaries → 34 units, 187 islands, main island 470.55 km²
$ /usr/bin/time -l uv run wp-ingest osm-island → 295.11 real, 2579300352 maximum resident set size
$ psql …/postgres -c "CREATE DATABASE wp_island"; alembic -x url=…/wp_island upgrade head → 0007_risk_cell_score (head)
$ /usr/bin/time -l env DATABASE_URL=…/wp_island uv run wp-ingest load --source osm --osm-graph island
{"source_id": "osm", "noop": false, "counts": {"node": 257542, "edge": 650920}}
      378.60 real   1909538816  maximum resident set size
$ psql …/wp_island: edge 316145664 B total (idx 107388928), node 58515456 B (idx 27574272), database 391655907 B; invalid geoms 0
$ pilot overlap: 16846 pilot edges, 16748 in island (99.42%), 16748 same geometry
$ uv run pytest -q
.....................................................................    [100%]
69 passed in 157.18s (0:02:37)
$ uv run ruff check . → All checks passed!   $ ruff format --check → 31 files already formatted
```
