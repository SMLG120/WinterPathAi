"""ETL advisory locks for ML writers (infra/ETL-LOCKS.md, integration 11ad5a2).

Constants are COPIED from Data's `winterpath_ingestion.locks` (not imported: services/ml must not
depend on services/ingestion). `tests/test_locks.py` checks they still match when that file is
present in the checkout. Never change them here alone.

Two-key Postgres advisory locks `(WPET, objid)`, TRANSACTION-scoped (released by COMMIT,
ROLLBACK or a lost connection; safe on Supabase poolers). Order: the schema gate (objid 0)
SHARED first, then one resource lock EXCLUSIVE. Try-lock only: on contention `Locked` is raised
inside the transaction and the caller skips cleanly (scheduled runs exit 0 with a notice).
"""

from __future__ import annotations

WPET = 1464878420  # 0x57504554 "WPET" — never change
SCHEMA_GATE = 0
RISK_CELL_SCORE = 100  # wp.risk_cell_score — winterpath_ml.score --write-db


class Locked(Exception):
    """Another run (or a migration, for objid 0) holds (WPET, objid)."""

    def __init__(self, objid: int):
        super().__init__(f"lock ({WPET},{objid}) held by another run")
        self.objid = objid

    @property
    def notice(self) -> str:
        return f"lock ({WPET},{self.objid}) held by another run — skipping"


def acquire(cur, objid: int | None) -> None:
    """Inside an open transaction: try the shared schema gate, then the exclusive resource lock.

    objid None → schema gate only. Raises `Locked` if either is held elsewhere."""
    cur.execute("SELECT pg_try_advisory_xact_lock_shared(%s, %s)", (WPET, SCHEMA_GATE))
    if not cur.fetchone()[0]:
        raise Locked(SCHEMA_GATE)
    if objid is not None:
        cur.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", (WPET, objid))
        if not cur.fetchone()[0]:
            raise Locked(objid)
