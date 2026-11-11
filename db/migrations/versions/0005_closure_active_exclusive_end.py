"""contract v1.4.0 conformance: wp.closure_active_at uses an exclusive valid_to (t < valid_to).

Revision ID: 0005_closure_active_excl_end
Revises: 0004_closure_status
Create Date: 2026-11-10

0004 treated valid_to as inclusive (t <= valid_to). data-model.md v1.4.0 specifies
`t < valid_to`. This replaces the function body with that single change. The signature,
grants and comment are unchanged. Downgrade restores the 0004 body.
"""

import importlib.util
from pathlib import Path

from alembic import op

revision = "0005_closure_active_excl_end"
down_revision = "0004_closure_status"
branch_labels = None
depends_on = None

_INCLUSIVE = "(c.valid_to IS NOT NULL AND t > c.valid_to)"
_EXCLUSIVE = "(c.valid_to IS NOT NULL AND t >= c.valid_to)"


def _function_sql_0004() -> str:
    """The CREATE FUNCTION statement exactly as 0004 shipped it."""
    p = Path(__file__).with_name("0004_closure_status.py")
    spec = importlib.util.spec_from_file_location("_m0004", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    start = m.UPGRADE.index("CREATE FUNCTION")
    end = m.UPGRADE.index("$fn$;", start) + len("$fn$;")
    sql = m.UPGRADE[start:end]
    assert sql.count(_INCLUSIVE) == 1
    return sql.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def upgrade() -> None:
    op.execute(_function_sql_0004().replace(_INCLUSIVE, _EXCLUSIVE))


def downgrade() -> None:
    op.execute(_function_sql_0004())
