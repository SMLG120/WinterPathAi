"""contract v1.2.0 (CR-DATA-1/2/3/5): edge crossing/highway/snapshot columns, closure attrs +
backsidewalk_blocks_passage, new wp.weather_daily.

Revision ID: 0002_contract_v1_2_0
Revises: 0001_wp_schema_v1
Create Date: 2026-11-10

Purely additive; downgrade drops exactly what upgrade adds.
"""

from alembic import op

revision = "0002_contract_v1_2_0"
down_revision = "0001_wp_schema_v1"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE wp.edge
  ADD COLUMN crossing_type text
    CHECK (crossing_type IN ('marked','traffic_signals','unmarked','uncontrolled','unknown')),
  ADD COLUMN crossing_kerb text
    CHECK (crossing_kerb IN ('lowered','flush','raised','unknown')),
  ADD COLUMN highway text,
  ADD COLUMN osm_snapshot timestamptz;

ALTER TABLE wp.closure
  ADD COLUMN backsidewalk_blocks_passage boolean,
  ADD COLUMN attrs jsonb NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE wp.weather_daily (
  station_id         text NOT NULL,
  day                date NOT NULL,
  total_precip_mm    double precision CHECK (total_precip_mm IS NULL OR total_precip_mm >= 0),
  total_snow_cm      double precision CHECK (total_snow_cm IS NULL OR total_snow_cm >= 0),
  snow_on_ground_cm  double precision CHECK (snow_on_ground_cm IS NULL OR snow_on_ground_cm >= 0),
  min_temp_c         double precision,
  max_temp_c         double precision,
  source_collection  text NOT NULL DEFAULT 'climate-daily'
                     CHECK (source_collection IN ('climate-daily')),
  ingest_run_id      uuid REFERENCES wp.ingest_run(ingest_run_id),
  PRIMARY KEY (station_id, day)
);

GRANT SELECT ON wp.weather_daily TO wp_reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON wp.weather_daily TO wp_writer;
GRANT ALL ON wp.weather_daily TO wp_migrator;
"""

DOWNGRADE = """
REVOKE ALL ON wp.weather_daily FROM wp_reader, wp_writer, wp_migrator;
DROP TABLE wp.weather_daily;
ALTER TABLE wp.closure DROP COLUMN attrs, DROP COLUMN backsidewalk_blocks_passage;
ALTER TABLE wp.edge
  DROP COLUMN osm_snapshot, DROP COLUMN highway, DROP COLUMN crossing_kerb,
  DROP COLUMN crossing_type;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
