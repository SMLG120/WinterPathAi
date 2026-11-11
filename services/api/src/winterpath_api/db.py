"""SQLAlchemy engine construction (v1.7: Supabase session-pooler friendly).

Supabase's session pooler (Supavisor, port 5432 on the pooler host, IPv4) gives each client
connection a dedicated server connection for the life of the session, so psycopg's prepared
statements work unchanged. What matters on a free tier is the *number* of client connections
and not holding dead ones:

* a small pool (``DATABASE_POOL_SIZE`` + ``DATABASE_MAX_OVERFLOW``), one engine per process;
* ``pool_pre_ping`` so a connection the pooler or a NAT dropped is replaced, not handed out;
* ``pool_recycle`` (300 s) so idle connections are renewed before they go stale;
* a bounded ``pool_timeout`` so an exhausted pool fails fast (the endpoints map it to 503).

The URL itself (host, ``sslmode=require``) comes from ``DATABASE_URL`` and is never logged.
"""

from __future__ import annotations

from typing import Any

from .settings import Settings


def engine_options(settings: Settings) -> dict[str, Any]:
    return {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_pre_ping": True,
        "pool_recycle": settings.db_pool_recycle_s,
        "pool_timeout": settings.db_pool_timeout_s,
        "connect_args": {
            "connect_timeout": settings.db_connect_timeout_s,
            # Visible in pg_stat_activity / the pooler dashboard; contains no user data.
            "application_name": "winterpath-api",
        },
    }


def needs_db(settings: Settings) -> bool:
    """Any PostGIS-backed component → one shared engine (stores, weather, risk scores)."""
    return bool(settings.database_url) and (
        settings.store_backend == "postgis"
        or settings.weather_source == "postgis"
        or (settings.risk_provider != "none" and settings.risk_score_source == "postgis")
    )


def ping(engine) -> bool:
    from sqlalchemy import text

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def create_db_engine(settings: Settings):
    from sqlalchemy import create_engine

    if not settings.database_url:
        raise ValueError("DATABASE_URL is not set")
    return create_engine(settings.database_url, **engine_options(settings))
