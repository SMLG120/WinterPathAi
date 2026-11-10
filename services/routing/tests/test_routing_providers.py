"""Graph providers + cost model invariants."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from routing_testlib import TOY_DIR

from winterpath_routing import (
    CostConfig,
    Edge,
    FixtureGraphProvider,
    GraphUnavailableError,
    PedestrianGraph,
    PostgisGraphProvider,
    Profile,
    RiskEstimate,
    RiskLevel,
    edge_cost,
)
from winterpath_routing.geo import haversine_m
from winterpath_routing.graph import GraphIntegrityError
from winterpath_routing.models import Evidence, EvidenceState, GraphData, GraphMetadata, Node


def test_fixture_provider_loads_synthetic_and_flags_it() -> None:
    data = FixtureGraphProvider(TOY_DIR).load()
    assert data.metadata.simulated is True
    assert len(data.edges) == 38 and len(data.nodes) == 14
    ids = [e.edge_id for e in data.edges]
    assert len(ids) == len(set(ids))
    crossing = [e for e in data.edges if e.edge_kind == "crossing"]
    assert crossing and all(e.crossing_type == "marked" for e in crossing)


def test_lengths_epsg32188_within_1pct_of_geodesic() -> None:
    for e in FixtureGraphProvider(TOY_DIR).load().edges:
        geo = sum(haversine_m(a, b) for a, b in zip(e.coords, e.coords[1:], strict=False))
        assert e.length_m == pytest.approx(geo, rel=0.01)


def test_fixture_missing_files_raise(tmp_path: Path) -> None:
    with pytest.raises(GraphUnavailableError):
        FixtureGraphProvider(tmp_path).load()


def test_fixture_requires_explicit_simulated_flag(tmp_path: Path) -> None:
    for f in TOY_DIR.iterdir():
        shutil.copy(f, tmp_path / f.name)
    meta = json.loads((tmp_path / "metadata.json").read_text())
    del meta["simulated"]
    (tmp_path / "metadata.json").write_text(json.dumps(meta))
    with pytest.raises(GraphUnavailableError, match="simulated"):
        FixtureGraphProvider(tmp_path).load()


def test_graph_rejects_dangling_edges_and_duplicates() -> None:
    n = {"a": Node("a", -73.57, 45.50)}
    e = Edge("a>b:0", "a", "b", ((-73.57, 45.50), (-73.569, 45.50)), 78.0, "footway")
    with pytest.raises(GraphIntegrityError):
        PedestrianGraph(GraphData(n, [e], GraphMetadata(simulated=True)))
    n["b"] = Node("b", -73.569, 45.50)
    with pytest.raises(GraphIntegrityError):
        PedestrianGraph(GraphData(n, [e, e], GraphMetadata(simulated=True)))


def _edge(**kw) -> Edge:
    base = dict(
        edge_id="x",
        from_node_id="a",
        to_node_id="b",
        coords=((0.0, 0.0), (0.001, 0.0)),
        length_m=100.0,
        edge_kind="footway",
    )
    base.update(kw)
    return Edge(**base)


@pytest.mark.parametrize("profile", list(Profile))
@pytest.mark.parametrize("level", list(RiskLevel))
@pytest.mark.parametrize("lit", [True, False, None])
@pytest.mark.parametrize("step_free", [True, False, None])
def test_costs_are_non_negative_and_at_least_base(profile, level, lit, step_free) -> None:
    risk = RiskEstimate(level, Evidence(EvidenceState.MODEL_ESTIMATE))
    c = edge_cost(
        _edge(lit=lit, step_free=step_free),
        profile,
        risk,
        n_confirmed_disruptions=1,
        n_unverified_reports=1,
        avoid_unverified_reports=True,
        config=CostConfig(),
    )
    for v in (c.base_s, c.disruption_s, c.risk_s, c.unknown_s, c.preference_s):
        assert v >= 0
    assert c.total_s >= c.base_s > 0
    if level is RiskLevel.UNKNOWN:
        assert c.unknown_s > 0 and c.risk_s == 0


def test_cost_config_rejects_negative_or_zero_unknown_penalty() -> None:
    with pytest.raises(ValueError):
        CostConfig(unknown_penalty_s_per_100m=0.0)
    with pytest.raises(ValueError):
        CostConfig(confirmed_disruption_penalty_s=-1)


def test_unknown_risk_estimate_helper() -> None:
    assert RiskEstimate.unknown().is_unknown
    assert RiskEstimate(RiskLevel.LOW, Evidence(EvidenceState.CONFIRMED)).is_unknown


def _db_url() -> str | None:
    return os.environ.get("ROUTING_TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


def _db_ready(url: str | None) -> str | None:
    """Return a skip reason, or None if the wp schema is reachable."""
    if not url:
        return "DATABASE_URL not set"
    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        return "postgis extra not installed (sqlalchemy/psycopg)"
    try:
        eng = create_engine(url, connect_args={"connect_timeout": 2})
        with eng.connect() as c:
            ok = c.execute(text("SELECT to_regclass('wp.edge') IS NOT NULL")).scalar()
        return None if ok else "wp.edge table absent (Data agent migrations not applied)"
    except Exception as exc:
        return f"PostGIS unreachable ({type(exc).__name__}); Docker Desktop paused?"


def test_postgis_graph_provider_integration() -> None:
    reason = _db_ready(_db_url())
    if reason:
        pytest.skip(reason)
    data = PostgisGraphProvider(_db_url(), (-73.588, 45.496, -73.562, 45.513)).load()
    assert data.metadata.simulated is False
    PedestrianGraph(data)
