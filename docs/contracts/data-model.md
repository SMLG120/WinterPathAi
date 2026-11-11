# Data model — PostGIS contract v1.7.0

> v1.7.0 (2026-11-11, free-tier deployment): new `wp.risk_cell_score` so deployed APIs read daily risk scores from PostGIS instead of local files; Supabase deployment notes.

> v1.6.0 (2026-11-11, user decisions on CR-ML-2 + CR-DATA-7): alley activities get their own 311 categories (`snow_clearing_alley`, `snow_dumping_alley`); an explicit `foot=yes|designated|permissive` overrides `access=private|no`.

> v1.5.0 (2026-11-10, CR-ML-1 + user decisions): `wp.report_311_cell` gains `nature` in the PK; canonical 311 category names; OSM source = Geofabrik; path-type inclusion policy.
> v1.4.0 (2026-11-10, CR-ROUTING-7): `wp.closure.status` vocabulary + `wp.closure_active_at(c wp.closure, t timestamptz)` (three-valued: true/false/null = unknown) (migration 0004).
> v1.3.0 (2026-11-10, CR-ROUTING-5/6/8): `wp.edge.name`; `wp.community_report.terminal_at`; canonical source ids.
> v1.2.0 (2026-11-10, CR-DATA-1/2/3/5): additive columns on `wp.edge` and `wp.closure`; new `wp.weather_daily`.

**Migration owner: Data agent** (`db/migrations/`, Alembic). Other agents read these tables; they never create migrations. Schema changes → change request (integration-rules §3).

Conventions: schema `wp`; geometry SRID **4326** with GiST index; metric values computed in **EPSG:32188**; all timestamps `timestamptz` UTC; every derived row has `source_id` and `ingest_run_id`.

## Stable IDs
- `node_id` = `osm:n<osm_node_id>` for OSM nodes; `syn:<sha1(lon6,lat6)[:16]>` for nodes created by a documented topology rule.
- `edge_id` = `<from_node_id>><to_node_id>:<k>` where `k` disambiguates parallel edges (0-based, ordered by OSM way id). Same OSM snapshot + same build ⇒ same IDs (tested).
- H3 cells: resolution **9** (`h3` string) for 311 aggregation and ML.

## Tables

### `wp.source` — registry (mirrors `/data-sources`)
Canonical `source_id`s (v1.3): `osm`, `mtl-voirie`, `mtl-311`, `mtl-entraves`, `mtl-planif-neige`, `eccc-geomet`. All agents use exactly these.
`source_id text PK`, `name`, `publisher`, `license`, `license_url`, `commercial_use` (enum as OpenAPI), `attribution`, `url`, `status`, `last_success_at`, `notes`.

### `wp.ingest_run`
`ingest_run_id uuid PK`, `source_id FK`, `started_at`, `finished_at`, `status (running|succeeded|failed)`, `input_checksum text`, `record_count int`, `log jsonb`. Failed runs never replace current data (load into staging, swap in a transaction).

### OSM source & path-type policy (v1.5, user decision 2026-11-10)
- **Source:** Geofabrik `quebec-latest.osm.pbf` (download.geofabrik.de), clipped to the pilot bbox; record file date, MD5/SHA and download URL in `wp.ingest_run`. The public Overpass instance is **no longer used by the pipeline** (its policy directs commercial use to self-hosted/paid servers). Overpass may be used only for ad-hoc developer checks.
- **Included highway types:** unchanged (footway incl. sidewalk/crossing, path, pedestrian, steps, living_street, residential, tertiary, secondary, primary) **plus** `service` and `cycleway` **only when** `foot ∈ {yes, designated, permissive}` is explicitly tagged.
- **Excluded:** `corridor` / indoor (RÉSO) until opening hours and public access are verified from a cited source; `service`/`cycleway` without explicit foot permission; `foot=no|use_sidepath` everywhere; `access=private|no` **unless** `foot ∈ {yes, designated, permissive}` is explicitly tagged on the same way (v1.6, CR-DATA-7: OSM's mode-specific tag overrides the general `access` tag). Data reports how many ways this rule admits.

### `wp.node`
`node_id text PK`, `geom geometry(Point,4326)`, `osm_id bigint null`, `kind (street_node|crossing|entrance|synthetic)`, `crossing_type`, `kerb`, `source_id`, `ingest_run_id`. GiST(`geom`).

### `wp.edge`
| column | type | notes |
|---|---|---|
| edge_id | text PK | stable |
| from_node_id / to_node_id | text FK → node | directed; footways are inserted in both directions |
| geom | geometry(LineString,4326) | GiST |
| length_m | double precision | computed in 32188 |
| edge_kind | text | enum from OpenAPI `SegmentFeature.edge_kind` |
| osm_way_id | bigint null | |
| foot_access | text | `yes|designated|permissive|no|private|unknown` — `no`/`private` rows are **not routable** |
| step_free | boolean null | null = unknown |
| incline_percent, width_m | double null | |
| surface | text null | |
| lit | boolean null | |
| name | text null | v1.3: OSM `name` (street name for step directions) |
| crossing_type | text null | v1.2: `CrossingInfo.type` enum; null when edge is not a crossing |
| crossing_kerb | text null | v1.2: `CrossingInfo.kerb` enum |
| highway | text null | v1.2: OSM `highway` value (traceability) |
| osm_snapshot | timestamptz null | v1.2: OSM snapshot timestamp the edge was built from |
| sidewalk_polygon_ids | text[] | Voirie polygons matched by spatial join (enrichment only) |
| connectivity_confidence | text | `high` (OSM topology), `medium` (documented snap rule ≤ 2 m), `low` |
| component_id | int | connected component; routing uses largest + reports others as gaps |
| source_id, ingest_run_id, updated_at | | |

Indexes: GiST(geom), btree(from_node_id), btree(to_node_id), btree(component_id).

### `wp.sidewalk_polygon` — Voirie trottoir/îlot
`polygon_id text PK` (publisher id), `geom geometry(MultiPolygon,4326)`, `category`, `type`, `material`, `surveyed_at date null`, `attrs jsonb`, `source_id`, `ingest_run_id`. GiST.

### `wp.closure` — Entraves
`closure_id text PK` (`entrave:<id>`), `geom geometry(Geometry,4326)` (Entraves publishes the **permit point**; edge matching is approximate), `sidewalk_blockedtype text`, `blocks_passage boolean null`, `backsidewalk_blocks_passage boolean null` (v1.2; same rule applied to `backsidewalk_blockedtype`), `attrs jsonb` (v1.2; permit id and named affected street sections — never geocoded into certainty) (true **only** if `sidewalk_blockedtype` explicitly indicates blocked pedestrian passage; mapping table documented by Data agent), `valid_from`, `valid_to`, `status`, `source_id`, `ingest_run_id`. GiST. Evidence state: `confirmed` (official permit data).

**Closure status (v1.4):** `status` is the publisher lifecycle only — `permit_issued` (from `Permis émis`) · `cancelled` · `completed` · `unknown` (CHECK constraint; unmapped raw values → `unknown`, raw kept in `attrs.currentstatus`). Time-derived states are **never stored**. Consumers call `wp.closure_active_at(c wp.closure, t timestamptz)` (three-valued: true/false/null = unknown): `status='permit_issued'` AND `valid_from <= t` AND (`valid_to` IS NULL OR `t < valid_to`) AND the weekly schedule in `attrs.weekly_schedule` (America/Montreal local weekday; partial-day windows respected) permits `t`. A `null` schedule flag means **unknown activity** — routing must flag or penalise it, never treat it as clear. Routing excludes an edge only when the closure is active at `t` **and** `blocks_passage` is true. Evidence (2026-11-10 file): 1 974 permits all `Permis émis`; 347 already ended and 80 not started despite the feed title; 942 partial-day.

### `wp.report_311_cell` — aggregated, privacy-preserving
`h3 text`, `day date`, `category text` (canonical: `sidewalk_slippery` ← Trottoir glissant, `roadway_slippery` ← Chaussée glissante, `snow_clearing` ← Opération déneigement, `snow_dumping` ← Dépôt Illégal - Neige, and since v1.6 (CR-ML-2) `snow_clearing_alley` ← Déneigement ruelle, `snow_dumping_alley` ← Dépôt neige-ruelle; consumers that want the v1.5 meaning SUM the alley category into its parent), `nature text` (v1.5: `requete`, `plainte`, `information`, `commentaire` from 311 `NATURE`), `n int`, PK(h3, day, category, nature). **Consumers must `SUM(n)` over the natures they need**: ML labels use `nature IN ('requete','plainte')`; public counts and hazard aggregates use the same two natures unless stated. The k-anonymity floor (n<3 suppressed) applies **after** summing. **No raw rows stored in the DB**; raw CSV stays in git-ignored `data/raw/`. Cells with n<3 per day are kept for training but suppressed in public API output (k-anonymity floor; ML agent may use them).

### `wp.weather_obs`
`station_id`, `observed_at`, `temperature_c`, `precip_mm`, `snow_depth_cm`, `wind_kmh`, `source_collection` (`climate-hourly|swob-realtime`), `ingest_run_id`. PK(station_id, observed_at).

### `wp.weather_daily` (v1.2)
`station_id`, `day date`, `total_precip_mm`, `total_snow_cm`, `snow_on_ground_cm`, `min_temp_c`, `max_temp_c`, `source_collection` (`climate-daily`), `ingest_run_id`. PK(station_id, day). Added because station 7025251's hourly precipitation is null throughout, while daily `SNOW_ON_GROUND`/`TOTAL_PRECIPITATION` are populated.

### `wp.community_report`
`report_id uuid PK`, `category`, `geom Point 4326` (stored only with consent), `description`, `status (pending|approved|rejected|expired|deleted)`, `created_at`, `expires_at` (default +72 h), `deletion_token_hash`, `moderated_at`, `moderation_note`, `terminal_at timestamptz null` (v1.3: time the report reached rejected/expired/deleted — drives the 30-day hard delete), `client_hash` (salted, rotated daily, for rate-limit only). Hard-deleted 30 days after terminal status.

### `wp.edge_risk` — ML/heuristic output (written by ML pipeline via Data-owned migration)
`edge_id FK`, `valid_from`, `valid_to`, `level (low|moderate|elevated|high|unknown)`, `probability double null`, `evidence_state`, `model_id`, PK(edge_id, valid_from).

### `wp.risk_cell_score` (v1.7) — daily per-cell risk scores (written by the ML scoring job)
`h3 text` (res 9), `day date` (America/Montreal local day the score is valid for), `model_id text` (registry id, e.g. `winter311-heuristic-v1`), `layer text` (`heuristic|model`), `p double precision` (calibrated score as defined by the registry; not a sidewalk-condition probability), `scored_at timestamptz`, `data_through timestamptz` (latest input data used), `ingest_run_id uuid`. PK(`h3`, `day`, `model_id`). Index on (`day`, `model_id`).
- One row per covered cell per day; cells outside the registry's coverage list have **no row** (⇒ `unknown`, never `low`).
- Writers replace a whole (`day`, `model_id`) partition in one transaction; failed runs never leave a partial day.
- Retention: keep 30 days; older rows are deleted by the scoring job.
- Readers (API risk provider): use the row for the requested local day; no row ⇒ `unknown`. Level thresholds stay in `models/registry.json`.

### Deployment notes (Supabase, v1.7)
- Enable PostGIS **before** the first migration in schema `extensions` (Supabase guidance: never `public`); migration 0001's `CREATE EXTENSION IF NOT EXISTS postgis` is then a no-op. Login roles used by Alembic, the API and jobs must have `extensions` on their `search_path`.
- Schema `wp` is not exposed through the Supabase Data API.

### `wp.pilot_request`
`id uuid`, `organization`, `contact_name`, `contact_email`, `segment`, `message`, `locale`, `created_at`; deleted after 12 months.

## Risk labels
`level` thresholds are defined by the ML agent in `models/registry.json` and surfaced via `/models/status`. Absent rows ⇒ `unknown` (never `low`).

## Fixtures
`data/fixtures/pilot_mini/` (Data agent): ≤ 200 edges GeoJSON from a real OSM extract of a few blocks around McGill, with attribution file; usable by Routing and Frontend without a DB. Any synthetic fixture lives under `fixtures/synthetic/` and has `"simulated": true` in its metadata.
