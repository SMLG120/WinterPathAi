# Data model — PostGIS contract v1

**Migration owner: Data agent** (`db/migrations/`, Alembic). Other agents read these tables; they never create migrations. Schema changes → change request (integration-rules §3).

Conventions: schema `wp`; geometry SRID **4326** with GiST index; metric values computed in **EPSG:32188**; all timestamps `timestamptz` UTC; every derived row has `source_id` and `ingest_run_id`.

## Stable IDs
- `node_id` = `osm:n<osm_node_id>` for OSM nodes; `syn:<sha1(lon6,lat6)[:16]>` for nodes created by a documented topology rule.
- `edge_id` = `<from_node_id>><to_node_id>:<k>` where `k` disambiguates parallel edges (0-based, ordered by OSM way id). Same OSM snapshot + same build ⇒ same IDs (tested).
- H3 cells: resolution **9** (`h3` string) for 311 aggregation and ML.

## Tables

### `wp.source` — registry (mirrors `/data-sources`)
`source_id text PK`, `name`, `publisher`, `license`, `license_url`, `commercial_use` (enum as OpenAPI), `attribution`, `url`, `status`, `last_success_at`, `notes`.

### `wp.ingest_run`
`ingest_run_id uuid PK`, `source_id FK`, `started_at`, `finished_at`, `status (running|succeeded|failed)`, `input_checksum text`, `record_count int`, `log jsonb`. Failed runs never replace current data (load into staging, swap in a transaction).

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
| sidewalk_polygon_ids | text[] | Voirie polygons matched by spatial join (enrichment only) |
| connectivity_confidence | text | `high` (OSM topology), `medium` (documented snap rule ≤ 2 m), `low` |
| component_id | int | connected component; routing uses largest + reports others as gaps |
| source_id, ingest_run_id, updated_at | | |

Indexes: GiST(geom), btree(from_node_id), btree(to_node_id), btree(component_id).

### `wp.sidewalk_polygon` — Voirie trottoir/îlot
`polygon_id text PK` (publisher id), `geom geometry(MultiPolygon,4326)`, `category`, `type`, `material`, `surveyed_at date null`, `attrs jsonb`, `source_id`, `ingest_run_id`. GiST.

### `wp.closure` — Entraves
`closure_id text PK` (`entrave:<id>`), `geom geometry(Geometry,4326)`, `sidewalk_blockedtype text`, `blocks_passage boolean null` (true **only** if `sidewalk_blockedtype` explicitly indicates blocked pedestrian passage; mapping table documented by Data agent), `valid_from`, `valid_to`, `status`, `source_id`, `ingest_run_id`. GiST. Evidence state: `confirmed` (official permit data).

### `wp.report_311_cell` — aggregated, privacy-preserving
`h3 text`, `day date`, `category text` (normalised winter category), `n int`, PK(h3, day, category). **No raw rows stored in the DB**; raw CSV stays in git-ignored `data/raw/`. Cells with n<3 per day are kept for training but suppressed in public API output (k-anonymity floor; ML agent may use them).

### `wp.weather_obs`
`station_id`, `observed_at`, `temperature_c`, `precip_mm`, `snow_depth_cm`, `wind_kmh`, `source_collection` (`climate-hourly|swob-realtime`), `ingest_run_id`. PK(station_id, observed_at).

### `wp.community_report`
`report_id uuid PK`, `category`, `geom Point 4326` (stored only with consent), `description`, `status (pending|approved|rejected|expired|deleted)`, `created_at`, `expires_at` (default +72 h), `deletion_token_hash`, `moderated_at`, `moderation_note`, `client_hash` (salted, rotated daily, for rate-limit only). Hard-deleted 30 days after terminal status.

### `wp.edge_risk` — ML/heuristic output (written by ML pipeline via Data-owned migration)
`edge_id FK`, `valid_from`, `valid_to`, `level (low|moderate|elevated|high|unknown)`, `probability double null`, `evidence_state`, `model_id`, PK(edge_id, valid_from).

### `wp.pilot_request`
`id uuid`, `organization`, `contact_name`, `contact_email`, `segment`, `message`, `locale`, `created_at`; deleted after 12 months.

## Risk labels
`level` thresholds are defined by the ML agent in `models/registry.json` and surfaced via `/models/status`. Absent rows ⇒ `unknown` (never `low`).

## Fixtures
`data/fixtures/pilot_mini/` (Data agent): ≤ 200 edges GeoJSON from a real OSM extract of a few blocks around McGill, with attribution file; usable by Routing and Frontend without a DB. Any synthetic fixture lives under `fixtures/synthetic/` and has `"simulated": true` in its metadata.
