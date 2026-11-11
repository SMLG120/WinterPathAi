"""contract v1.5.0 (CR-ML-1) + v1.6.0 (CR-ML-2): wp.report_311_cell.nature in the PK;
canonical categories including the alley categories.

Revision ID: 0006_report_311_nature
Revises: 0005_closure_active_excl_end
Create Date: 2026-11-10

nature ∈ requete | plainte | information | commentaire (311 `NATURE`). category ∈
sidewalk_slippery | roadway_slippery | snow_clearing | snow_dumping | snow_clearing_alley |
snow_dumping_alley (the two alley categories are folded in here per contract v1.6.0, because
0006 had not reached integration; databases already at 0006 must downgrade to 0005 first).
PK becomes (h3, day, category, nature). Consumers SUM(n) over the natures they need; the
k-anonymity floor (n<3) applies after summing.

Upgrade: rows aggregated before this migration mix all natures and CANNOT be split, so they are
deleted rather than labelled with a guessed nature. This table holds only derived aggregates; it
is rebuilt from the raw file by `wp-ingest 311 && wp-ingest load`. The mtl-311 succeeded runs are
left in wp.ingest_run as history (the new pipeline checksum differs, so the reload is not a noop).

Downgrade: exact. The old per-(h3, day, category) count is the sum over natures.
"""

from alembic import op

revision = "0006_report_311_nature"
down_revision = "0005_closure_active_excl_end"
branch_labels = None
depends_on = None

CATEGORIES = (
    "('sidewalk_slippery','roadway_slippery','snow_clearing','snow_dumping',"
    "'snow_clearing_alley','snow_dumping_alley')"
)
NATURES = "('requete','plainte','information','commentaire')"

UPGRADE = f"""
DELETE FROM wp.report_311_cell;
ALTER TABLE wp.report_311_cell DROP CONSTRAINT report_311_cell_pkey;
ALTER TABLE wp.report_311_cell
  ADD COLUMN nature text NOT NULL
    CONSTRAINT report_311_cell_nature_check CHECK (nature IN {NATURES}),
  ADD CONSTRAINT report_311_cell_category_check CHECK (category IN {CATEGORIES}),
  ADD CONSTRAINT report_311_cell_pkey PRIMARY KEY (h3, day, category, nature);
"""

DOWNGRADE = """
CREATE TEMP TABLE report_311_collapse ON COMMIT DROP AS
  SELECT h3, day, category, sum(n)::integer AS n, min(source_id) AS source_id,
         (array_agg(ingest_run_id ORDER BY ingest_run_id))[1] AS ingest_run_id
    FROM wp.report_311_cell GROUP BY h3, day, category;
DELETE FROM wp.report_311_cell;
ALTER TABLE wp.report_311_cell
  DROP CONSTRAINT report_311_cell_pkey,
  DROP CONSTRAINT report_311_cell_category_check,
  DROP COLUMN nature;
INSERT INTO wp.report_311_cell (h3, day, category, n, source_id, ingest_run_id)
  SELECT h3, day, category, n, source_id, ingest_run_id FROM report_311_collapse;
ALTER TABLE wp.report_311_cell ADD CONSTRAINT report_311_cell_pkey PRIMARY KEY (h3, day, category);
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
