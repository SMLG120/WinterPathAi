"""v2 island wiring: prebuilt graph artifact, coverage from the artifact, array-backed risk.

The graph is the REAL pilot_mini OSM fixture. Risk scores are TEST FIXTURE values fed to the real
``winterpath_ml`` heuristic layer (never shown as real); the reference for every comparison is
the existing per-edge path (``inner.edge_risk`` / the id-keyed adapter).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd
import pytest
from api_testlib import PILOT_MINI, pilot_route_points, validate_response
from winterpath_routing import FixtureGraphProvider, RouteRequest, compact_io
from winterpath_routing.compact import CompactGraph
from winterpath_routing.compact_engine import CompactRoutingEngine

from winterpath_api import graph_artifact
from winterpath_api.adapters import CoordinateRiskAdapter, normalise_estimate
from winterpath_api.risk_cells import LEVELS, RiskCellIndex

AT = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)
DAY = "2026-11-10"


@pytest.fixture(scope="module")
def artifact(tmp_path_factory):
    out = tmp_path_factory.mktemp("artifact") / "pilot_mini.npz"
    area = out.with_suffix(".geojson")
    meta = json.loads((PILOT_MINI / "metadata.json").read_text())
    w, s, e, n = meta["bbox"]
    # two polygons → exercises the single-Polygon rule of the contract's Coverage.area
    half = (w + e) / 2
    area.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {},
                        "geometry": {"type": "Polygon", "coordinates": [ring]},
                    }
                    for ring in (
                        [[w, s], [half - 1e-4, s], [half - 1e-4, n], [w, n], [w, s]],
                        [[half + 1e-4, s], [e, s], [e, n], [half + 1e-4, n], [half + 1e-4, s]],
                    )
                ],
            }
        )
    )
    rc = graph_artifact.main(
        [
            "--out", str(out), "--from-fixture", str(PILOT_MINI),
            "--coverage-name", "TEST coverage", "--coverage-area", str(area),
        ]
    )  # fmt: skip
    assert rc == 0
    return out


@pytest.fixture(scope="module")
def graph() -> CompactGraph:
    return CompactGraph.from_graph_data(FixtureGraphProvider(PILOT_MINI).load())


@pytest.fixture(autouse=True)
def fine_cells(monkeypatch):
    """pilot_mini fits in ONE res-9 cell, so sample at res 11 here: the ML layer's own edge rule
    then sees several cells per route (its module-level ``cells_along`` is what both the layer
    and the index use)."""
    import winterpath_ml.inference as inf

    orig = inf.cells_along

    def cells_along(coords, res=11, step_m=5.0):
        return orig(coords, res, step_m)

    monkeypatch.setattr(inf, "cells_along", cells_along)


def _ml_provider(graph: CompactGraph):
    """Real ML heuristic layer over TEST scores: most cells scored, a few left out (unknown)."""
    import winterpath_ml.inference as inf
    from winterpath_ml.inference import HeuristicRiskProvider, load_registry

    cells = RiskCellIndex.build(graph, inf.cells_along).cells
    assert len(cells) >= 3, "pilot_mini must span several cells for this test"
    scored = [c for k, c in enumerate(cells) if k % 7 != 3]  # the rest: outside coverage
    reg = load_registry()
    scores = pd.DataFrame(
        {
            "h3": scored,
            "day": DAY,
            "p": [(0.03, 0.06, 0.2, 0.0)[k % 4] for k in range(len(scored))],  # TEST values
            "scored_at": "2026-11-10T12:00:00+00:00",
            "data_through": "2026-11-10T05:00:00+00:00",
        }
    )
    return HeuristicRiskProvider(reg, "heuristic", scores, frozenset(scored))


# ----------------------------------------------------------------------------- artifact + coverage
def test_artifact_source_serves_routes_and_declared_coverage(make_client, artifact) -> None:
    sha = compact_io.sha256_file(artifact)
    c = make_client(
        graph_source="artifact",
        graph_artifact=artifact,
        graph_artifact_sha256=sha,
        routing_fast_search=True,
    )
    cov = c.get("/api/v1/coverage")
    validate_response(cov, "/coverage", "get")
    body = cov.json()
    assert body["pilot_name"] == "TEST coverage"
    assert body["area"]["type"] == "Polygon"
    assert body["graph"]["edge_count"] > 0
    w, s, e, n = body["bbox"]
    o, d = pilot_route_points()
    assert w <= o["lon"] <= e and s <= o["lat"] <= n

    r = c.post("/api/v1/routes/compare", json={"origin": o, "destination": d})
    validate_response(r, "/routes/compare", "post")
    assert r.status_code == 200 and len(r.json()["routes"]) == 2

    out = c.post(
        "/api/v1/routes/compare",
        json={"origin": o, "destination": {"lon": e + 0.01, "lat": d["lat"]}},
    )
    assert out.status_code == 422
    assert out.json()["code"] == "OUTSIDE_COVERAGE"
    assert out.json()["details"]["coverage_bbox"] == body["bbox"]
    seg = c.get("/api/v1/map/segments", params={"bbox": f"{e + 1},{s},{e + 1.01},{n}"})
    assert seg.status_code == 422 and seg.json()["code"] == "OUTSIDE_COVERAGE"


def test_artifact_with_wrong_sha_is_not_loaded(make_client, artifact) -> None:
    c = make_client(
        graph_source="artifact", graph_artifact=artifact, graph_artifact_sha256="0" * 64
    )
    h = c.get("/api/v1/health").json()
    assert h["checks"]["graph"]["status"] != "ok"
    o, d = pilot_route_points()
    assert c.post("/api/v1/routes/compare", json={"origin": o, "destination": d}).status_code == 503


def test_missing_artifact_degrades(make_client, tmp_path) -> None:
    c = make_client(graph_source="artifact", graph_artifact=tmp_path / "nope.npz")
    assert c.get("/api/v1/health").json()["checks"]["graph"]["status"] != "ok"


def test_default_coverage_is_still_the_pilot(client) -> None:
    body = client.get("/api/v1/coverage").json()
    assert body["pilot_name"] == "McGill / Downtown pilot"
    assert body["bbox"] == [-73.588, 45.496, -73.562, 45.513]


# ----------------------------------------------------------------------------- snapshot risk
def test_snapshot_equals_per_edge_ml_answers(graph) -> None:
    inner = _ml_provider(graph)
    adapter = CoordinateRiskAdapter(inner, lambda eid: graph.edges[eid].coords, graph=graph)
    snap = adapter.edge_risk_snapshot(AT)
    assert snap is not None and len(snap.levels) == len(graph.edges)
    known = unknown = 0
    for i in range(len(graph.edges)):
        ref = normalise_estimate(inner.edge_risk(graph.edge_at(i).coords, AT))
        got = snap.estimate(i)
        assert got.is_unknown == ref.is_unknown, i
        assert LEVELS[int(snap.levels[i])] == (ref.level if not ref.is_unknown else "unknown"), i
        if ref.is_unknown:
            unknown += 1
        else:
            assert got == ref, i
            known += 1
    assert known > 20 and unknown > 0  # the TEST scores exercise both outcomes


def test_routing_with_snapshot_equals_per_edge_adapter(graph) -> None:
    inner = _ml_provider(graph)
    coords = lambda eid: graph.edges[eid].coords  # noqa: E731
    per_edge = CoordinateRiskAdapter(inner, coords)
    arrays = CoordinateRiskAdapter(inner, coords, graph=graph)
    assert per_edge.edge_risk_snapshot(AT) is None
    o, d = pilot_route_points()
    req = RouteRequest((o["lon"], o["lat"]), (d["lon"], d["lat"]), AT)
    ref = CompactRoutingEngine(graph).compare(req, per_edge, ())
    for fast in (False, True):
        got = CompactRoutingEngine(graph, fast_search=fast).compare(req, arrays, ())
        for a, b in zip(ref.routes, got.routes, strict=True):
            assert b.unknown_share == pytest.approx(a.unknown_share, abs=1e-12)
            assert b.generalized_cost_s == pytest.approx(a.generalized_cost_s, rel=1e-12)
            assert b.risk_cost_s == pytest.approx(a.risk_cost_s, rel=1e-12)
        assert got.risk_layer == ref.risk_layer == "heuristic"
    assert any(r.risk_cost_s > 0 for r in ref.routes)
    # the map endpoint path (id-keyed call) answers from the same snapshot
    ids = list(graph.edges)[:40]
    assert arrays.edge_risk(ids, AT) == {
        eid: arrays.edge_risk_snapshot(AT).estimate(graph.edge_index(eid)) for eid in ids
    }


def test_snapshot_refreshes_when_scores_land(graph) -> None:
    inner = _ml_provider(graph)
    table = inner._by_day.pop(pd.Timestamp(DAY))  # the day is not scored yet
    now = [0.0]
    adapter = CoordinateRiskAdapter(
        inner, lambda eid: graph.edges[eid].coords, graph=graph, clock=lambda: now[0]
    )
    first = adapter.edge_risk_snapshot(AT)
    assert all(LEVELS[int(c)] == "unknown" for c in first.levels)
    inner._by_day[pd.Timestamp(DAY)] = table  # the scoring job ran
    now[0] = 299.0
    assert adapter.edge_risk_snapshot(AT) is first  # still inside the TTL
    now[0] = 301.0
    later = adapter.edge_risk_snapshot(AT)
    assert later.token != first.token
    assert any(LEVELS[int(c)] != "unknown" for c in later.levels)
    now[0] = 700.0
    assert adapter.edge_risk_snapshot(AT).token == later.token  # unchanged levels keep the token


def test_shipped_index_with_other_sampler_params_is_rebuilt(graph) -> None:
    import winterpath_ml.inference as inf

    inner = _ml_provider(graph)
    good = RiskCellIndex.build(graph, inf.cells_along)
    stale = (good.to_extras(), {"params": {"res": 8, "step_m": 999.0}})
    adapter = CoordinateRiskAdapter(
        inner, lambda eid: graph.edges[eid].coords, graph=graph, risk_cells=stale
    )
    snap = adapter.edge_risk_snapshot(AT)  # small graph: rebuilt at start-up, not trusted
    ref = normalise_estimate(inner.edge_risk(graph.edge_at(0).coords, AT))
    assert snap.estimate(0).is_unknown == ref.is_unknown


def test_warmup_runs_one_route_at_startup_and_never_fails(make_client, monkeypatch) -> None:
    c = make_client(routing_warmup=True)
    engine = c.app.state.wp.engine
    calls = []
    real = engine.compare

    def spy(*a, **kw):
        calls.append(1)
        return real(*a, **kw)

    monkeypatch.setattr(engine, "compare", spy)
    with c:
        assert calls == [1]
        assert c.get("/api/v1/health").status_code == 200
    # a broken hazard store must not stop the server from starting
    c2 = make_client(routing_warmup=True)

    def boom(at):
        raise RuntimeError("down")

    monkeypatch.setattr(c2.app.state.wp.hazards, "list", boom)
    with c2:
        assert c2.get("/api/v1/coverage").status_code == 200
    # off by default
    c3 = make_client()
    monkeypatch.setattr(c3.app.state.wp.engine, "compare", spy)
    with c3:
        assert calls == [1]
