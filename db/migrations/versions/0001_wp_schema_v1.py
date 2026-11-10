"""wp schema v1 (docs/contracts/data-model.md): tables, GiST/btree indexes, role grants.

Revision ID: 0001_wp_schema_v1
Revises:
Create Date: 2026-11-10

Enums are TEXT + CHECK constraints (Supabase-friendly, cheap to evolve via a new migration).
Roles wp_reader / wp_writer / wp_migrator are cluster-wide: created NOLOGIN if absent, but never
dropped on downgrade (other databases in the shared container may use them); downgrade only
revokes what upgrade granted and drops the wp schema objects.
"""

from alembic import op

revision = "0001_wp_schema_v1"
down_revision = None
branch_labels = None
depends_on = None

COMMERCIAL = "('allowed','allowed_with_conditions','not_allowed','unverified')"
SRC_STATUS = "('active','stale','disabled','requires_credentials','error')"
EDGE_KIND = "('sidewalk','footway','path','pedestrian_street','crossing','shared_street','steps','other')"
FOOT = "('yes','designated','permissive','no','private','unknown')"
RISK = "('low','moderate','elevated','high','unknown')"
EVIDENCE = "('confirmed','unverified_report','model_estimate','unknown','simulated')"

UPGRADE = f"""
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS wp;

CREATE TABLE wp.source (
  source_id        text PRIMARY KEY,
  name             text NOT NULL,
  publisher        text NOT NULL,
  license          text NOT NULL,
  license_url      text NOT NULL,
  commercial_use   text NOT NULL CHECK (commercial_use IN {COMMERCIAL}),
  attribution      text NOT NULL,
  url              text NOT NULL,
  status           text NOT NULL CHECK (status IN {SRC_STATUS}),
  last_success_at  timestamptz,
  notes            text
);

CREATE TABLE wp.ingest_run (
  ingest_run_id   uuid PRIMARY KEY,
  source_id       text NOT NULL REFERENCES wp.source(source_id),
  started_at      timestamptz NOT NULL DEFAULT now(),
  finished_at     timestamptz,
  status          text NOT NULL CHECK (status IN ('running','succeeded','failed')),
  input_checksum  text,
  record_count    integer,
  log             jsonb NOT NULL DEFAULT '{{}}'::jsonb
);
CREATE INDEX ingest_run_source_idx ON wp.ingest_run (source_id, started_at DESC);

CREATE TABLE wp.node (
  node_id        text PRIMARY KEY,
  geom           geometry(Point,4326) NOT NULL,
  osm_id         bigint,
  kind           text NOT NULL CHECK (kind IN ('street_node','crossing','entrance','synthetic')),
  crossing_type  text CHECK (crossing_type IN ('marked','traffic_signals','unmarked','uncontrolled','unknown')),
  kerb           text CHECK (kerb IN ('lowered','flush','raised','unknown')),
  source_id      text NOT NULL REFERENCES wp.source(source_id),
  ingest_run_id  uuid REFERENCES wp.ingest_run(ingest_run_id)
);
CREATE INDEX node_geom_gix ON wp.node USING gist (geom);

CREATE TABLE wp.edge (
  edge_id                  text PRIMARY KEY,
  from_node_id             text NOT NULL REFERENCES wp.node(node_id),
  to_node_id               text NOT NULL REFERENCES wp.node(node_id),
  geom                     geometry(LineString,4326) NOT NULL,
  length_m                 double precision NOT NULL CHECK (length_m > 0),
  edge_kind                text NOT NULL CHECK (edge_kind IN {EDGE_KIND}),
  osm_way_id               bigint,
  foot_access              text NOT NULL CHECK (foot_access IN {FOOT}),
  step_free                boolean,
  incline_percent          double precision,
  width_m                  double precision,
  surface                  text,
  lit                      boolean,
  sidewalk_polygon_ids     text[] NOT NULL DEFAULT '{{}}',
  connectivity_confidence  text NOT NULL CHECK (connectivity_confidence IN ('high','medium','low')),
  component_id             integer,
  source_id                text NOT NULL REFERENCES wp.source(source_id),
  ingest_run_id            uuid REFERENCES wp.ingest_run(ingest_run_id),
  updated_at               timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX edge_geom_gix ON wp.edge USING gist (geom);
CREATE INDEX edge_from_idx ON wp.edge (from_node_id);
CREATE INDEX edge_to_idx ON wp.edge (to_node_id);
CREATE INDEX edge_component_idx ON wp.edge (component_id);

CREATE TABLE wp.sidewalk_polygon (
  polygon_id     text PRIMARY KEY,
  geom           geometry(MultiPolygon,4326) NOT NULL,
  category       text,
  type           text,
  material       text,
  surveyed_at    date,
  attrs          jsonb NOT NULL DEFAULT '{{}}'::jsonb,
  source_id      text NOT NULL REFERENCES wp.source(source_id),
  ingest_run_id  uuid REFERENCES wp.ingest_run(ingest_run_id)
);
CREATE INDEX sidewalk_polygon_geom_gix ON wp.sidewalk_polygon USING gist (geom);

CREATE TABLE wp.closure (
  closure_id            text PRIMARY KEY,
  geom                  geometry(Geometry,4326) NOT NULL,
  sidewalk_blockedtype  text,
  blocks_passage        boolean,
  valid_from            timestamptz,
  valid_to              timestamptz,
  status                text,
  source_id             text NOT NULL REFERENCES wp.source(source_id),
  ingest_run_id         uuid REFERENCES wp.ingest_run(ingest_run_id)
);
CREATE INDEX closure_geom_gix ON wp.closure USING gist (geom);
CREATE INDEX closure_valid_idx ON wp.closure (valid_from, valid_to);

CREATE TABLE wp.report_311_cell (
  h3        text NOT NULL,
  day       date NOT NULL,
  category  text NOT NULL,
  n         integer NOT NULL CHECK (n > 0),
  source_id text NOT NULL DEFAULT 'mtl-311' REFERENCES wp.source(source_id),
  ingest_run_id uuid REFERENCES wp.ingest_run(ingest_run_id),
  PRIMARY KEY (h3, day, category)
);
CREATE INDEX report_311_cell_day_idx ON wp.report_311_cell (day);

CREATE TABLE wp.weather_obs (
  station_id         text NOT NULL,
  observed_at        timestamptz NOT NULL,
  temperature_c      double precision,
  precip_mm          double precision,
  snow_depth_cm      double precision,
  wind_kmh           double precision,
  source_collection  text NOT NULL CHECK (source_collection IN ('climate-hourly','swob-realtime')),
  ingest_run_id      uuid REFERENCES wp.ingest_run(ingest_run_id),
  PRIMARY KEY (station_id, observed_at)
);

CREATE TABLE wp.community_report (
  report_id            uuid PRIMARY KEY,
  category             text NOT NULL,
  geom                 geometry(Point,4326),
  description          text,
  status               text NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending','approved','rejected','expired','deleted')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  expires_at           timestamptz NOT NULL DEFAULT (now() + interval '72 hours'),
  deletion_token_hash  text,
  moderated_at         timestamptz,
  moderation_note      text,
  client_hash          text
);
CREATE INDEX community_report_geom_gix ON wp.community_report USING gist (geom);
CREATE INDEX community_report_status_idx ON wp.community_report (status, expires_at);

CREATE TABLE wp.edge_risk (
  edge_id         text NOT NULL REFERENCES wp.edge(edge_id) ON DELETE CASCADE,
  valid_from      timestamptz NOT NULL,
  valid_to        timestamptz,
  level           text NOT NULL CHECK (level IN {RISK}),
  probability     double precision CHECK (probability IS NULL OR probability BETWEEN 0 AND 1),
  evidence_state  text NOT NULL CHECK (evidence_state IN {EVIDENCE}),
  model_id        text,
  PRIMARY KEY (edge_id, valid_from)
);

CREATE TABLE wp.pilot_request (
  id             uuid PRIMARY KEY,
  organization   text,
  contact_name   text,
  contact_email  text,
  segment        text,
  message        text,
  locale         text,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX pilot_request_created_idx ON wp.pilot_request (created_at);

-- roles (cluster-wide; NOLOGIN group roles; login users are granted membership by Platform)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wp_reader') THEN
    CREATE ROLE wp_reader NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wp_writer') THEN
    CREATE ROLE wp_writer NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'wp_migrator') THEN
    CREATE ROLE wp_migrator NOLOGIN; END IF;
END $$;

GRANT USAGE ON SCHEMA wp TO wp_reader, wp_writer;
GRANT ALL ON SCHEMA wp TO wp_migrator;
GRANT SELECT ON ALL TABLES IN SCHEMA wp TO wp_reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA wp TO wp_writer;
GRANT ALL ON ALL TABLES IN SCHEMA wp TO wp_migrator;
-- PII tables are not readable by the generic reader role
REVOKE SELECT ON wp.pilot_request, wp.community_report FROM wp_reader;
"""

DOWNGRADE = """
REVOKE ALL ON ALL TABLES IN SCHEMA wp FROM wp_reader, wp_writer, wp_migrator;
REVOKE ALL ON SCHEMA wp FROM wp_reader, wp_writer, wp_migrator;
DROP TABLE IF EXISTS wp.pilot_request, wp.edge_risk, wp.community_report, wp.weather_obs,
  wp.report_311_cell, wp.closure, wp.sidewalk_polygon, wp.edge, wp.node, wp.ingest_run,
  wp.source;
DROP SCHEMA IF EXISTS wp;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
