"""Contract v1.7.0 free-tier deployment: read-only mode, pool settings, clean shutdown."""

from __future__ import annotations

import pytest
from api_testlib import grid, validate_response
from fastapi.testclient import TestClient
from winterpath_routing import GraphUnavailableError, PostgisGraphProvider

from winterpath_api.db import create_db_engine, engine_options
from winterpath_api.main import create_app
from winterpath_api.settings import Settings
from winterpath_api.state import build_state

REPORT = {"category": "ice", "location": grid(1, 1), "location_consent": True}
PILOT = {
    "organization": "Test Org (fixture)",
    "contact_email": "test@example.org",
    "segment": "campus",
    "consent": True,
}


class NoWrites:
    """Repository stand-in: any write is a test failure."""

    def create(self, *a, **kw):  # pragma: no cover - must never be called
        raise AssertionError("write reached the store while API_PUBLIC_WRITES=false")


# ----------------------------------------------------------------------------- settings
def test_settings_defaults_and_env() -> None:
    d = Settings.from_env({})
    assert d.public_writes is True
    assert (d.db_pool_size, d.db_max_overflow, d.db_pool_recycle_s) == (3, 2, 300)
    s = Settings.from_env(
        {"API_PUBLIC_WRITES": "false", "DATABASE_POOL_SIZE": "2", "DATABASE_MAX_OVERFLOW": "0"}
    )
    assert (s.public_writes, s.db_pool_size, s.db_max_overflow) == (False, 2, 0)
    for v in ("0", "no", "OFF", " False "):
        assert Settings.from_env({"API_PUBLIC_WRITES": v}).public_writes is False
    for v in ("", "1", "true", "yes"):
        assert Settings.from_env({"API_PUBLIC_WRITES": v}).public_writes is True


@pytest.mark.parametrize(
    "env",
    [
        {"API_PUBLIC_WRITES": "maybe"},  # a typo must not silently open writes
        {"DATABASE_POOL_SIZE": "0"},
        {"DATABASE_MAX_OVERFLOW": "-1"},
        {"DATABASE_POOL_SIZE": "three"},
    ],
)
def test_settings_reject_invalid(env) -> None:
    with pytest.raises(ValueError):
        Settings.from_env(env)


def test_engine_options_for_session_pooler() -> None:
    s = Settings.from_env(
        {
            "DATABASE_URL": "postgresql+psycopg://u:p@pooler.invalid:5432/postgres?sslmode=require",
            "DATABASE_POOL_SIZE": "2",
            "DATABASE_MAX_OVERFLOW": "1",
        }
    )
    o = engine_options(s)
    assert o["pool_pre_ping"] is True and o["pool_recycle"] == 300
    assert (o["pool_size"], o["max_overflow"], o["pool_timeout"]) == (2, 1, 10)
    assert o["connect_args"]["connect_timeout"] == 10
    eng = create_db_engine(s)  # lazy: no connection is opened here
    try:
        assert (eng.pool.size(), eng.pool._max_overflow, eng.pool._recycle) == (2, 1, 300)
        assert eng.pool._pre_ping is True
        assert eng.pool.checkedout() == 0
    finally:
        eng.dispose()


def test_graph_load_uses_one_short_lived_connection(monkeypatch) -> None:
    import sqlalchemy
    from sqlalchemy.pool import NullPool

    seen = []
    real = sqlalchemy.create_engine

    def spy(url, **kw):
        eng = real(url, **kw)
        disposed = []
        orig = eng.dispose
        eng.dispose = lambda *a, **k: (disposed.append(True), orig(*a, **k))
        seen.append((kw, disposed))
        return eng

    monkeypatch.setattr(sqlalchemy, "create_engine", spy)
    p = PostgisGraphProvider(
        "postgresql+psycopg://u:p@127.0.0.1:1/none", (0, 0, 1, 1), connect_timeout_s=2
    )
    with pytest.raises(GraphUnavailableError):
        p.load()  # nothing listens on port 1
    [(kw, disposed)] = seen
    assert kw["poolclass"] is NullPool and kw["connect_args"]["connect_timeout"] == 2
    assert disposed == [True]  # released even when the load fails


# ----------------------------------------------------------------------------- read-only mode
@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/reports", REPORT),
        ("/reports", {"junk": True}),  # answered before validation
        ("/pilot-requests", PILOT),
        ("/pilot-requests", {}),
    ],
)
def test_writes_disabled_is_503(make_client, path, body) -> None:
    from winterpath_api.repositories.reports import InMemoryReportRepository

    class GuardedReports(InMemoryReportRepository):
        create = NoWrites.create

    c = make_client(public_writes=False, reports=GuardedReports(), pilot_requests=NoWrites())
    r = c.post(f"/api/v1{path}", json=body)
    assert r.status_code == 503, r.text
    validate_response(r, path, "post")
    assert r.json()["code"] == "WRITES_DISABLED"
    assert "test@example.org" not in r.text


def test_writes_disabled_leaves_reads_and_rate_limit_alone(make_client) -> None:
    c = make_client(public_writes=False, rate_limit_per_minute=1)
    for _ in range(3):  # gate answers before the limiter: never 429
        assert c.post("/api/v1/reports", json=REPORT).status_code == 503
    assert c.get("/api/v1/health").status_code == 200
    r = c.post("/api/v1/routes/compare", json={"origin": grid(0, 0), "destination": grid(1, 2)})
    assert r.status_code == 200
    assert (
        c.delete(
            "/api/v1/reports/00000000-0000-0000-0000-000000000000",
            headers={"X-Deletion-Token": "x"},
        ).status_code
        == 404
    )


def test_writes_enabled_by_default(client) -> None:
    assert client.post("/api/v1/reports", json=REPORT).status_code == 201
    assert client.post("/api/v1/pilot-requests", json=PILOT).status_code == 201


# ----------------------------------------------------------------------------- shutdown
def test_lifespan_shutdown_releases_resources(settings) -> None:
    class Engine:
        disposed = 0

        def dispose(self):
            Engine.disposed += 1

    state = build_state(settings)
    state.db_engine = Engine()
    with TestClient(create_app(settings, state)) as c:
        assert c.get("/api/v1/health").status_code == 200
    assert Engine.disposed == 1
    with pytest.raises(RuntimeError):  # worker pool no longer accepts work
        state.compute._ex.submit(lambda: None)
