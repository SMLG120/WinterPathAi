"""Routing on the REAL OSM pilot_mini fixture (Data agent; simulated=false, 200 edges near McGill).

Independent oracle: networkx.dijkstra_path_length over length_m between node pairs.
"""

from __future__ import annotations

import random
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import networkx as nx
import pytest

from winterpath_routing import (
    EvidenceState,
    FixtureGraphProvider,
    NoRouteError,
    NullRiskProvider,
    PedestrianGraph,
    Profile,
    RouteRequest,
    RoutingEngine,
    SnapError,
)
from winterpath_routing.geo import haversine_m

PILOT_MINI = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "pilot_mini"
PILOT_BBOX = (-73.5880, 45.4960, -73.5620, 45.5130)
AT = datetime(2026, 12, 15, 8, 0, tzinfo=UTC)
NULL = NullRiskProvider()

pytestmark = pytest.mark.skipif(
    not (PILOT_MINI / "edges.geojson").exists(), reason="data/fixtures/pilot_mini not present"
)


@pytest.fixture(scope="module")
def graph() -> PedestrianGraph:
    return PedestrianGraph(FixtureGraphProvider(PILOT_MINI).load())


@pytest.fixture(scope="module")
def engine(graph) -> RoutingEngine:
    return RoutingEngine(graph)


def _fixture_bbox(graph):
    lons = [n.lon for n in graph.nodes.values()]
    lats = [n.lat for n in graph.nodes.values()]
    return min(lons), min(lats), max(lons), max(lats)


def test_real_fixture_metadata_and_integrity(graph) -> None:
    m = graph.metadata
    assert m.simulated is False
    assert m.osm_snapshot and m.source_freshness.get("osm") is not None
    meta = __import__("json").loads((PILOT_MINI / "metadata.json").read_text())
    assert (len(graph.edges), len(graph.nodes)) == (meta["edge_count"], meta["node_count"])
    assert all(e.foot_legal for e in graph.edges.values())
    assert graph.largest_component_share == 1.0 and graph.gaps() == []
    for e in graph.edges.values():
        geo = sum(haversine_m(a, b) for a, b in zip(e.coords, e.coords[1:], strict=False))
        assert e.length_m == pytest.approx(geo, rel=0.01)
        if e.edge_kind == "crossing":
            assert e.crossing_type in {"marked", "traffic_signals", "unmarked", "uncontrolled"}


def test_shortest_matches_networkx_oracle_on_node_pairs(graph, engine) -> None:
    oracle = nx.DiGraph()
    for e in graph.edges.values():
        w = e.length_m
        if (
            not oracle.has_edge(e.from_node_id, e.to_node_id)
            or oracle[e.from_node_id][e.to_node_id]["w"] > w
        ):
            oracle.add_edge(e.from_node_id, e.to_node_id, w=w)
    rnd = random.Random(1)
    ids = sorted(graph.nodes)
    checked = 0
    for _ in range(60):
        a, b = rnd.sample(ids, 2)
        na, nb = graph.nodes[a], graph.nodes[b]
        if haversine_m((na.lon, na.lat), (nb.lon, nb.lat)) < 5:
            continue
        expected = nx.dijkstra_path_length(oracle, a, b, weight="w")
        res = engine.compare(RouteRequest((na.lon, na.lat), (nb.lon, nb.lat), AT), NULL)
        assert res.routes[0].distance_m == pytest.approx(expected, abs=0.05), (a, b)
        checked += 1
    assert checked >= 50


def test_random_pairs_dijkstra_equals_astar_and_invariants(graph, engine) -> None:
    w, s, e, n = _fixture_bbox(graph)
    rnd = random.Random(2)
    routed = 0
    for _ in range(150):
        o = (rnd.uniform(w, e), rnd.uniform(s, n))
        d = (rnd.uniform(w, e), rnd.uniform(s, n))
        if haversine_m(o, d) < 5:
            continue
        r = RouteRequest(o, d, AT, profile=rnd.choice([Profile.STANDARD, Profile.REDUCED_MOBILITY]))
        try:
            dj, _ = engine.shortest_path(r, NULL, weight="generalized", algorithm="dijkstra")
            a, _ = engine.shortest_path(r, NULL, weight="generalized", algorithm="astar")
            res = engine.compare(r, NULL)
        except SnapError:
            continue
        routed += 1
        assert a.cost == pytest.approx(dj.cost, rel=1e-9, abs=1e-9)
        short, winter = res.routes
        assert short.distance_m <= winter.distance_m + 1e-6
        assert winter.generalized_cost_s <= short.generalized_cost_s + 1e-6
        for route in res.routes:
            assert route.unknown_share == 1.0
            states = {x.evidence_state for x in route.explanation}
            assert EvidenceState.SIMULATED not in states  # real data: never flagged simulated
            for lon, lat in route.coordinates:
                assert PILOT_BBOX[0] <= lon <= PILOT_BBOX[2]
                assert PILOT_BBOX[1] <= lat <= PILOT_BBOX[3]
        assert not any(w_.startswith("SIMULATED") for w_ in res.warnings)
    assert routed >= 100


def test_step_free_on_real_data_never_relaxed(graph, engine) -> None:
    # Only 2 directed edges in pilot_mini are tagged step-free; most requests must fail
    # (snap or NO_ROUTE) rather than fall back to untagged edges.
    rnd = random.Random(3)
    w, s, e, n = _fixture_bbox(graph)
    outcomes = {"route": 0, "snap": 0, "no_route": 0}
    for _ in range(60):
        o = (rnd.uniform(w, e), rnd.uniform(s, n))
        d = (rnd.uniform(w, e), rnd.uniform(s, n))
        if haversine_m(o, d) < 5:
            continue
        try:
            res = engine.compare(RouteRequest(o, d, AT, profile=Profile.STEP_FREE), NULL)
        except SnapError:
            outcomes["snap"] += 1
            continue
        except NoRouteError:
            outcomes["no_route"] += 1
            continue
        outcomes["route"] += 1
        for route in res.routes:
            assert all(graph.edges[x].step_free is True for x in route.edge_ids)
    assert outcomes["snap"] + outcomes["no_route"] > 0


def test_reduced_mobility_prefers_avoiding_steps_on_real_data(graph, engine) -> None:
    steps = [e for e in graph.edges.values() if e.edge_kind == "steps"]
    assert steps
    rnd = random.Random(4)
    w, s, e, n = _fixture_bbox(graph)
    std_steps = rm_steps = 0
    for _ in range(120):
        o = (rnd.uniform(w, e), rnd.uniform(s, n))
        d = (rnd.uniform(w, e), rnd.uniform(s, n))
        if haversine_m(o, d) < 5:
            continue
        try:
            std = engine.compare(RouteRequest(o, d, AT), NULL).routes[1]
            rm = engine.compare(RouteRequest(o, d, AT, profile=Profile.REDUCED_MOBILITY), NULL)
        except SnapError:
            continue
        std_steps += any(graph.edges[x].edge_kind == "steps" for x in std.edge_ids)
        rm_steps += any(graph.edges[x].edge_kind == "steps" for x in rm.routes[1].edge_ids)
    assert rm_steps <= std_steps


@pytest.mark.latency
def test_latency_100_random_pairs_real_pilot_mini(graph, engine, capsys) -> None:
    w, s, e, n = _fixture_bbox(graph)
    rnd = random.Random(42)
    times: list[float] = []
    snapped_out = 0
    while len(times) < 100:
        o = (rnd.uniform(w, e), rnd.uniform(s, n))
        d = (rnd.uniform(w, e), rnd.uniform(s, n))
        if haversine_m(o, d) < 5:
            continue
        t0 = time.perf_counter()
        try:
            engine.compare(RouteRequest(o, d, AT), NULL)
        except SnapError:
            snapped_out += 1
            continue
        times.append(time.perf_counter() - t0)
    times.sort()
    with capsys.disabled():
        print(
            f"\n[latency] REAL pilot_mini (OSM, {len(graph.edges)} edges) n=100 compare() "
            f"p50={statistics.median(times) * 1000:.1f} ms p95={times[94] * 1000:.1f} ms "
            f"max={times[-1] * 1000:.1f} ms (rejected >75 m from network: {snapped_out})"
        )
    assert times[94] < 2.0
