"""ML risk wiring (``RISK_PROVIDER=winterpath_ml.inference:load_provider``).

Two kinds of tests:

* Adapter tests with a FAKE coordinate-keyed provider (TEST FIXTURE values, never shown as real).
* End-to-end tests with the REAL ML package and its versioned artifacts listed in
  ``models/registry.json``. Artifacts are git-ignored, so these skip (with reason) when they are
  not present in this checkout.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from api_testlib import PILOT_MINI, validate_response
from winterpath_routing import (
    FixtureGraphProvider,
    NullRiskProvider,
    PedestrianGraph,
    RouteRequest,
    RoutingEngine,
)

from winterpath_api.adapters import (
    CoordinateRiskAdapter,
    default_model_status,
    load_risk_provider,
)

AT_NOV = datetime(2026, 11, 10, 15, 0, tzinfo=UTC)


# ----------------------------------------------------------------------------- fake provider
class FakeCoordProvider:
    """Coordinate-keyed provider shaped like ``winterpath_ml.inference.RiskProvider``."""

    def __init__(self, level="moderate", layer="heuristic", fail=False) -> None:
        self.level, self.layer, self.fail, self.calls = level, layer, fail, 0

    def cell_risk(self, h3_cell, valid_from):  # pragma: no cover - protocol shape only
        raise NotImplementedError

    def edge_risk(self, coords, valid_from):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        assert len(coords) >= 2 and all(len(c) == 2 for c in coords)
        if self.level == "unknown":
            return {"level": "unknown", "probability": None, "evidence": {"state": "unknown"}}
        return {
            "level": self.level,
            "probability": None,
            "evidence": {
                "state": "model_estimate",
                "source_ids": ["mtl-311", "eccc-geomet"],
                "observed_at": None,
                "note": "TEST FIXTURE",
            },
        }

    def status(self):
        return {
            "risk_layer": self.layer,
            "enabled": True,
            "model_id": "test-fixture",
            "target": "TEST",
            "trained_at": None,
            "training_window": None,
            "evaluation": None,
            "limitations": ["TEST FIXTURE"],
        }


@pytest.fixture(scope="module")
def graph() -> PedestrianGraph:
    return PedestrianGraph(FixtureGraphProvider(PILOT_MINI).load())


def _coords(graph):
    return lambda eid: graph.edges[eid].coords if eid in graph.edges else None


def test_adapter_normalises_and_caches_per_local_day(graph) -> None:
    fake = FakeCoordProvider()
    a = CoordinateRiskAdapter(fake, _coords(graph))
    assert a.risk_layer == "heuristic"
    ids = list(graph.edges)[:5]
    out = a.edge_risk([*ids, "missing-edge"], AT_NOV)
    assert {out[i].level.value for i in ids} == {"moderate"}
    assert all(out[i].probability is None for i in ids)
    assert all(out[i].evidence.state.value == "model_estimate" for i in ids)
    assert out["missing-edge"].is_unknown  # no geometry → unknown, never low
    calls = fake.calls
    a.edge_risk(ids, AT_NOV.replace(hour=20))  # same Montréal day → cached
    assert fake.calls == calls
    a.edge_risk(ids, datetime(2026, 11, 11, 15, tzinfo=UTC))  # next day → recomputed
    assert fake.calls == calls + len(ids)


def test_adapter_failure_and_unknown_stay_unknown(graph) -> None:
    ids = list(graph.edges)[:3]
    for fake in (FakeCoordProvider(fail=True), FakeCoordProvider(level="unknown")):
        out = CoordinateRiskAdapter(fake, _coords(graph)).edge_risk(ids, AT_NOV)
        assert all(out[i].is_unknown and out[i].probability is None for i in ids)


def test_unknown_keeps_unknown_penalty_in_routing(graph) -> None:
    eng = RoutingEngine(graph)
    nodes = sorted(graph.nodes)
    o, d = graph.nodes[nodes[0]], graph.nodes[nodes[-1]]
    req = RouteRequest((o.lon, o.lat), (d.lon, d.lat), AT_NOV)
    unknown = CoordinateRiskAdapter(FakeCoordProvider(level="unknown"), _coords(graph))
    low = CoordinateRiskAdapter(FakeCoordProvider(level="low"), _coords(graph))
    ru, rl = eng.compare(req, unknown).routes[0], eng.compare(req, low).routes[0]
    assert ru.unknown_share == 1.0 and rl.unknown_share == 0.0
    assert ru.generalized_cost_s > rl.generalized_cost_s  # unknown is never treated as low


def test_coordinate_provider_without_graph_is_null(monkeypatch) -> None:
    import types

    mod = types.ModuleType("wp_fake_ml")
    mod.load_provider = FakeCoordProvider
    monkeypatch.setitem(__import__("sys").modules, "wp_fake_ml", mod)
    assert isinstance(load_risk_provider("wp_fake_ml:load_provider"), NullRiskProvider)
    p = load_risk_provider("wp_fake_ml:load_provider", lambda eid: None)
    assert isinstance(p, CoordinateRiskAdapter)
    assert default_model_status(p)["model_id"] == "test-fixture"


# ----------------------------------------------------------------------------- real ML package
IN_SEASON_DAY = "2026-01-14"  # the in-season day the real-layer tests route on


def _artifacts_reason() -> str | None:
    """Registry + coverage, resolved exactly as ML resolves them (honours MODEL_ARTIFACT_DIR)."""
    try:
        from winterpath_ml.inference import artifact_path, load_registry

        reg = load_registry()
    except FileNotFoundError:
        return "models/registry.json absent"
    cov = artifact_path(reg, reg["coverage"])
    if not cov.exists():
        return f"ML coverage artifact absent ({cov})"
    return None


def _scores_reason(day: str) -> str | None:
    """The per-day score tables are git-ignored (only coverage + the heuristic joblib are
    committed in v1.7), so CI and fresh checkouts have none. Without rows for ``day`` every
    edge is unknown and the in-season assertions cannot hold: skip, saying why."""
    base = _artifacts_reason()
    if base:
        return base
    import pandas as pd
    from winterpath_ml.inference import load_registry, scores_dir

    reg = load_registry()
    d = scores_dir(reg, reg["active_layer"])
    files = sorted(d.glob("*.parquet")) if d.is_dir() else []
    if not files:
        return (
            f"ML per-day score tables absent ({d}/*.parquet is git-ignored; copy "
            f"models/artifacts/{reg['run_id']}/scores/ from agent/ml or run the ML score job)"
        )
    days = set()
    for f in files:
        t = pd.read_parquet(f, columns=["day", "p"])
        days |= set(pd.to_datetime(t.loc[t["p"].notna(), "day"]).dt.strftime("%Y-%m-%d"))
    if day not in days:
        return f"ML score tables in {d} have no scored rows for {day}"
    return None


REASON = _artifacts_reason()
SCORES_REASON = _scores_reason(IN_SEASON_DAY)
needs_artifacts = pytest.mark.skipif(REASON is not None, reason=REASON or "")
needs_scores = pytest.mark.skipif(SCORES_REASON is not None, reason=SCORES_REASON or "")
SPEC = "winterpath_ml.inference:load_provider"


@pytest.fixture
def ml(make_client):
    return make_client(fixture_dir=PILOT_MINI, risk_provider=SPEC)


def _compare(client, graph, when: str):
    nodes = sorted(graph.nodes)
    o, d = graph.nodes[nodes[0]], graph.nodes[nodes[-1]]
    return client.post(
        "/api/v1/routes/compare",
        json={
            "origin": {"lon": o.lon, "lat": o.lat},
            "destination": {"lon": d.lon, "lat": d.lat},
            "departure_time": when,
        },
    )


@needs_scores
def test_real_heuristic_layer_in_season(ml, graph) -> None:
    r = _compare(ml, graph, f"{IN_SEASON_DAY}T15:00:00Z")
    assert r.status_code == 200, r.text
    validate_response(r, "/routes/compare", "post")
    body = r.json()
    assert body["risk_layer"] == "heuristic"
    assert any("heuristic" in w and "not sidewalk conditions" in w for w in body["warnings"])
    for route in body["routes"]:
        assert route["unknown_share"] < 1.0
    st = ml.get("/api/v1/models/status")
    validate_response(st, "/models/status", "get")
    s = st.json()
    assert s["risk_layer"] == "heuristic" and s["enabled"] is False  # model failed its gate
    assert any("heuristic" in x for x in s["limitations"])


@needs_scores
def test_real_heuristic_estimates_have_no_probability(graph) -> None:
    # score_source pinned to "file": an ambient RISK_SCORE_SOURCE=postgis must not change it.
    p = load_risk_provider(SPEC, lambda eid: graph.edges[eid].coords, score_source="file")
    out = p.edge_risk(list(graph.edges), datetime(2026, 1, 14, 15, tzinfo=UTC))
    known = [e for e in out.values() if not e.is_unknown]
    assert known, f"expected scored cells on {IN_SEASON_DAY}"
    assert all(e.probability is None for e in out.values())
    assert {e.evidence.state.value for e in known} == {"model_estimate"}
    assert all("mtl-311" in e.evidence.source_ids for e in known)


@needs_artifacts
def test_real_layer_out_of_season_is_unknown(ml, graph) -> None:
    r = _compare(ml, graph, "2026-07-01T15:00:00Z")
    assert r.status_code == 200, r.text
    validate_response(r, "/routes/compare", "post")
    assert all(x["unknown_share"] == 1.0 for x in r.json()["routes"])
