"""Alembic env: plain SQL migrations (no ORM metadata). DATABASE_URL from env / .env.local."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env.local", override=False)
except ImportError:  # pragma: no cover
    pass


def _url() -> str:
    url = context.get_x_argument(as_dictionary=True).get("url") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, version_table_schema="public")
    with context.begin_transaction():
        context.run_migrations()


# ETL advisory locks (infra/ETL-LOCKS.md): migrations hold the schema gate (WPET, 0) EXCLUSIVELY
# for the whole run. Migrations commit one transaction per migration, so a transaction-scoped lock
# would be released between them; the gate is therefore a SESSION lock on a dedicated connection
# (the scheme's documented exception), blocking under lock_timeout, released in `finally` (and by
# the server if the connection drops). A timeout fails the migration: never migrate under a load.
WPET = 1464878420
SCHEMA_GATE = 0


@contextmanager
def _schema_gate(url: str):
    import psycopg

    timeout = os.environ.get("WP_MIGRATION_LOCK_TIMEOUT", "5min")
    dsn = url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True, application_name="alembic-schema-gate") as gate:
        gate.execute("SELECT set_config('lock_timeout', %s, false)", (timeout,))
        gate.execute("SELECT pg_advisory_lock(%s, %s)", (WPET, SCHEMA_GATE))
        try:
            yield
        finally:
            gate.execute("SELECT pg_advisory_unlock(%s, %s)", (WPET, SCHEMA_GATE))


def run_migrations_online() -> None:
    url = _url()
    engine = create_engine(url, poolclass=pool.NullPool)
    with _schema_gate(url), engine.connect() as conn:
        context.configure(connection=conn, version_table_schema="public",
                          transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
