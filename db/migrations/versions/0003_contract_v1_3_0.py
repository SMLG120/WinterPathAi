"""contract v1.3.0 (CR-ROUTING-5/6): wp.edge.name, wp.community_report.terminal_at.

Revision ID: 0003_contract_v1_3_0
Revises: 0002_contract_v1_2_0
Create Date: 2026-11-10

Additive. terminal_at is backfilled only from timestamps that already exist (moderated_at for
rejected/deleted, expires_at for expired); otherwise it stays NULL — no invented times.
No CHECK tying terminal_at to status: the API agent owns the write path and the contract
declares the column nullable. A partial index supports the 30-day hard-delete job.
"""

from alembic import op

revision = "0003_contract_v1_3_0"
down_revision = "0002_contract_v1_2_0"
branch_labels = None
depends_on = None

UPGRADE = """
ALTER TABLE wp.edge ADD COLUMN name text;

ALTER TABLE wp.community_report ADD COLUMN terminal_at timestamptz;
UPDATE wp.community_report
   SET terminal_at = CASE WHEN status = 'expired' THEN expires_at ELSE moderated_at END
 WHERE status IN ('rejected','expired','deleted') AND terminal_at IS NULL;
CREATE INDEX community_report_terminal_idx ON wp.community_report (terminal_at)
 WHERE terminal_at IS NOT NULL;
"""

DOWNGRADE = """
DROP INDEX IF EXISTS wp.community_report_terminal_idx;
ALTER TABLE wp.community_report DROP COLUMN terminal_at;
ALTER TABLE wp.edge DROP COLUMN name;
"""


def upgrade() -> None:
    op.execute(UPGRADE)


def downgrade() -> None:
    op.execute(DOWNGRADE)
