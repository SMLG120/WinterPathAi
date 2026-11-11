"""v1.7: ML risk scores read from ``wp.risk_cell_score`` through the API's shared engine.

``RISK_SCORE_SOURCE=postgis`` + ``RISK_PROVIDER=winterpath_ml.inference:load_provider``. The
rows inserted here are TEST FIXTURES (p = 0.5 for every scored cell, for today's local day) in
the routing agent's own DB; they are deleted afterwards and never presented as real scores.
"""

from __future__ import annotations

import inspect
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from api_testlib import PILOT_MINI, REPO, pilot_bbox_param, validate_response
from winterpath_routing import FixtureGraphProvider, NullRiskProvider, PedestrianGraph

from winterpath_api.adapters import CoordinateRiskAdapter, load_risk_provider
from winterpath_api.settings import Settings

SPEC = "winterpath_ml.inference:load_provider"
MTL = ZoneInfo("America/Montreal")
TEST_P = 0.5  # fixture value; maps to a non-unknown level under any registry thresholds


# ----------------------------------------------------------------------------- factory wiring
def test_factory_receives_engine_and_score_source_when_accepted(monkeypatch) -> None:
    import sys
    import types

    seen: dict[str, dict] = {}

    class Inner:  # minimal coordinate-keyed provider
        def __init__(self, name, **kw):
            seen[name] = kw

        def edge_risk(self, coords, valid_from):
            return {"level": "unknown", "probability": None, "evidence": {"state": "unknown"}}

        def cell_risk(self, h3, valid_from):  # pragma: no cover - protocol shape only
            raise NotImplementedError

        def status(self):
            return {"risk_layer": "heuristic", "enabled": True, "model_id": "test-fixture"}

    def v17(registry_path=None, *, engine=None, score_source=None):
        return Inner("v17", engine=engine, score_source=score_source)

    def legacy():  # pre-v1.7 factory: must still be called with no arguments
        return Inner("legacy")

    def varkw(**kw):
        return Inner("varkw", **kw)

    def engine_only(*, engine=None):
        return Inner("engine_only", engine=engine)

    mod = types.ModuleType("wp_fake_v17")
    mod.v17, mod.legacy, mod.varkw, mod.engine_only = v17, legacy, varkw, engine_only
    monkeypatch.setitem(sys.modules, "wp_fake_v17", mod)
    eng = object()
    for name in ("v17", "legacy", "varkw", "engine_only"):
        p = load_risk_provider(
            f"wp_fake_v17:{name}", lambda eid: None, engine=eng, score_source="postgis"
        )
        assert isinstance(p, CoordinateRiskAdapter)
    assert seen["v17"] == {"engine": eng, "score_source": "postgis"}
    assert seen["legacy"] == {}
    assert seen["varkw"] == {"engine": eng, "score_source": "postgis"}
    assert seen["engine_only"] == {"engine": eng}


def test_real_ml_factory_accepts_engine() -> None:
    from winterpath_ml.inference import load_provider

    params = inspect.signature(load_provider).parameters
    assert {"engine", "score_source"} <= set(params)


def test_postgis_score_source_without_db_is_all_unknown(make_client) -> None:
    # No DATABASE_URL → no engine → ML's documented fallback (NullRiskProvider), never "low".
    c = make_client(
        fixture_dir=PILOT_MINI, risk_provider=SPEC, risk_score_source="postgis", database_url=None
    )
    assert c.get("/api/v1/health").json()["checks"]["risk"]["status"] == "disabled"


def test_risk_score_source_setting() -> None:
    assert Settings.from_env({}).risk_score_source == "file"
    assert Settings.from_env({"RISK_SCORE_SOURCE": "PostGIS"}).risk_score_source == "postgis"
    with pytest.raises(ValueError):
        Settings.from_env({"RISK_SCORE_SOURCE": "s3"})


# ----------------------------------------------------------------------------- real DB at 0007
def _reason() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "DATABASE_URL not set"
    try:
        from sqlalchemy import create_engine, text

        with create_engine(url, connect_args={"connect_timeout": 10}).connect() as c:
            if not c.execute(text("SELECT to_regclass('wp.risk_cell_score') IS NOT NULL")).scalar():
                return "wp.risk_cell_score absent (migration 0007 not applied)"
    except Exception as exc:
        return f"PostGIS unreachable ({type(exc).__name__})"
    reg = json.loads((REPO / "models" / "registry.json").read_text())
    if not (REPO / reg["coverage"]["path"]).exists():
        return f"coverage artifact absent ({reg['coverage']['path']})"
    return None


REASON = _reason()


def _segment_risks(client) -> dict[str, dict]:
    out, cursor = {}, None
    while True:
        q = f"/api/v1/map/segments?bbox={pilot_bbox_param()}&limit=1000"
        r = client.get(q + (f"&cursor={cursor}" if cursor else ""))
        assert r.status_code == 200, r.text
        validate_response(r, "/map/segments", "get")
        out |= {f["id"]: f["properties"]["risk"] for f in r.json()["features"]}
        cursor = r.json()["next_cursor"]
        if not cursor:
            return out


def _compare(client, graph, departure: str) -> list[dict]:
    """compare over a spread of node pairs; returns the 200 responses (contract-validated)."""
    nodes = sorted(graph.nodes)
    bodies = []
    for i in range(0, len(nodes) // 2, max(1, len(nodes) // 16)):
        o, d = graph.nodes[nodes[i]], graph.nodes[nodes[-1 - i]]
        r = client.post(
            "/api/v1/routes/compare",
            json={
                "origin": {"lon": o.lon, "lat": o.lat},
                "destination": {"lon": d.lon, "lat": d.lat},
                "departure_time": departure,
            },
        )
        if r.status_code == 200:
            validate_response(r, "/routes/compare", "post")
            bodies.append(r.json())
    assert bodies
    return bodies


@pytest.mark.skipif(REASON is not None, reason=REASON or "")
def test_compare_reads_risk_cell_score_rows(make_client) -> None:
    """Rows for today's local day → heuristic levels; no row → unknown (never low).

    All 200 pilot_mini edges fall in ONE H3 r9 cell, so "row" vs "no row" cannot be mixed
    inside one route on this fixture; both cases are exercised on the same edges instead:
    (a) today with a row, (b) the next day (no rows) through the same client, and (c) today
    again after the row is deleted, through a fresh client.
    """
    from sqlalchemy import create_engine, text
    from winterpath_ml.inference import _coverage, cells_along, load_registry

    reg = load_registry()
    layer = reg["active_layer"]
    model_id = reg["layers"][layer]["id"]
    now_local = datetime.now(MTL)
    if now_local.month not in reg["season_months"]:
        pytest.skip(f"today ({now_local.date()}) is outside the layer's season months")
    day = now_local.date()
    noon = now_local.replace(hour=12, minute=0, second=0, microsecond=0)
    tomorrow = noon + timedelta(days=1)

    graph = PedestrianGraph(FixtureGraphProvider(PILOT_MINI).load())
    cells = {c for e in graph.edges.values() for c in cells_along(e.coords)}
    assert cells <= _coverage(reg), "pilot_mini cells must be in the coverage list"

    eng = create_engine(os.environ["DATABASE_URL"])
    count_sql = text(
        "SELECT count(*) FROM wp.risk_cell_score WHERE day = ANY(:ds) AND model_id = :m"
    )
    with eng.begin() as c:
        pre = c.execute(count_sql, {"ds": [day, tomorrow.date()], "m": model_id}).scalar()
        if pre:  # never clobber rows this test did not write
            pytest.skip(f"wp.risk_cell_score already has rows for {day}/{model_id}")
        c.execute(
            text(
                "INSERT INTO wp.risk_cell_score (h3, day, model_id, layer, p, data_through)"
                " VALUES (:h3, :day, :m, :layer, :p, now())"
            ),
            [
                {"h3": h, "day": day, "m": model_id, "layer": layer, "p": TEST_P}
                for h in sorted(cells)
            ],
        )

    def client():
        return make_client(
            fixture_dir=PILOT_MINI,
            risk_provider=SPEC,
            risk_score_source="postgis",
            database_url=os.environ["DATABASE_URL"],
            store_backend="memory",  # as deployed: the engine serves risk scores only
        )

    try:
        c1 = client()
        h = c1.get("/api/v1/health")
        validate_response(h, "/health", "get")
        checks = h.json()["checks"]
        assert checks["database"]["status"] == "ok"
        assert checks["risk"] == {
            "status": "ok",
            "detail": f"risk_layer={layer}; score_source=postgis",
        }

        # (a) today, row present: every edge scored, every route fully known.
        risks = _segment_risks(c1)  # evaluated "now" = today's local day
        assert set(risks) == set(graph.edges)
        assert all(r["level"] != "unknown" for r in risks.values())
        assert all(r["probability"] is None for r in risks.values())  # heuristic: no p shown
        assert {r["evidence"]["state"] for r in risks.values()} == {"model_estimate"}
        for body in _compare(c1, graph, noon.isoformat()):
            assert body["risk_layer"] == layer
            assert all(rt["unknown_share"] == 0.0 for rt in body["routes"])

        # (b) next local day, no rows: unknown everywhere, same client and engine.
        for body in _compare(c1, graph, tomorrow.isoformat()):
            assert body["risk_layer"] == layer
            assert all(rt["unknown_share"] == 1.0 for rt in body["routes"])
    finally:
        with eng.begin() as c:
            c.execute(
                text(
                    "DELETE FROM wp.risk_cell_score"
                    " WHERE day = :d AND model_id = :m AND h3 = ANY(:hs)"
                ),
                {"d": day, "m": model_id, "hs": sorted(cells)},
            )

    # (c) today again, row deleted, fresh client (no cached day): unknown, never low.
    c2 = client()
    assert all(r["level"] == "unknown" for r in _segment_risks(c2).values())
    for body in _compare(c2, graph, noon.isoformat()):
        assert all(rt["unknown_share"] == 1.0 for rt in body["routes"])
    with eng.connect() as c:
        assert c.execute(count_sql, {"ds": [day, tomorrow.date()], "m": model_id}).scalar() == 0
    eng.dispose()


def test_null_provider_type_is_ml_null_when_no_engine() -> None:
    # The direct factory call (no engine) is what the API did before this fix.
    from winterpath_ml.inference import load_provider

    inner = load_provider(score_source="postgis")
    assert type(inner).__name__ == NullRiskProvider.__name__
