"""ROUTING_COMPACT_GRAPH prototype: CompactGraph/CompactRoutingEngine must be indistinguishable
from PedestrianGraph/RoutingEngine — same graph surface, same static costs bit for bit, and the
same full compare() output (every field of every route, unrounded) on the REAL pilot_mini OSM
fixture and the SYNTHETIC golden grid (hazards of every kind, a static TEST risk layer)."""

from __future__ import annotations

import random

import pytest
from routing_testlib import PILOT_MINI, build_graph
from test_routing_golden import AT, PROFILES, _cases, _graph_data, _synthetic_graph

from winterpath_routing import (
    Edge,
    FixtureGraphProvider,
    GraphData,
    GraphIntegrityError,
    GraphMetadata,
    Node,
    PedestrianGraph,
    Profile,
    RiskEstimate,
    RouteRequest,
    RoutingEngine,
    RoutingError,
    edge_cost,
)
from winterpath_routing.compact import CompactGraph
from winterpath_routing.compact_engine import CompactRoutingEngine
from winterpath_routing.geo import point_to_metric


def _pair(g: PedestrianGraph) -> tuple[PedestrianGraph, CompactGraph]:
    return g, CompactGraph.from_graph_data(_graph_data(g))


@pytest.fixture(scope="module", params=["pilot_mini", "synthetic"])
def graphs(request) -> tuple[PedestrianGraph, CompactGraph]:
    if request.param == "pilot_mini":
        return _pair(PedestrianGraph(FixtureGraphProvider(PILOT_MINI).load()))
    return _pair(_synthetic_graph())


def test_graph_surface_identical(graphs) -> None:
    pg, cg = graphs
    assert list(cg.edges) == list(pg.edges) and list(cg.nodes) == list(pg.nodes)
    assert all(cg.edges[e] == pg.edges[e] for e in pg.edges)
    assert all(cg.nodes[n] == pg.nodes[n] for n in pg.nodes)
    assert all(cg.node_xy(n) == pg.node_xy(n) for n in pg.nodes)
    assert all(list(cg.metric_lines[e].coords) == list(pg.metric_lines[e].coords) for e in pg.edges)
    assert set(cg.main_component_edge_ids) == pg.main_component_edge_ids
    assert cg.largest_component_share == pg.largest_component_share
    assert cg.components == pg.components
    assert [g.edge_count for g in cg.gaps()] == [g.edge_count for g in pg.gaps()]
    assert "nope" not in cg.edges and cg.edges.get("nope") is None


def test_adjacency_in_networkx_order(graphs) -> None:
    pg, cg = graphs
    adj = RoutingEngine(pg)._adj
    for i, n in enumerate(pg.nodes):
        got = [
            (cg._nids.name(cg.adj_to[k]), cg.edge_id(cg.adj_edge[k]))
            for k in range(cg.adj_off[i], cg.adj_off[i + 1])
        ]
        assert got == list(adj[n]), n


def test_spatial_queries_identical(graphs) -> None:
    pg, cg = graphs
    w = min(e.coords[0][0] for e in pg.edges.values())
    e_ = max(e.coords[0][0] for e in pg.edges.values())
    s = min(e.coords[0][1] for e in pg.edges.values())
    n = max(e.coords[0][1] for e in pg.edges.values())
    rnd = random.Random(5)
    for _ in range(150):
        lon, lat = rnd.uniform(w - 0.001, e_ + 0.001), rnd.uniform(s - 0.001, n + 0.001)
        for allowed in (None, pg.main_component_edge_ids):
            a = pg.nearest_edges(lon, lat, 75.0, allowed)
            b = cg.nearest_edges(
                lon, lat, 75.0, None if allowed is None else cg.main_component_edge_ids
            )
            assert (a[0], a[1]) == (b[0], b[1])
        p = point_to_metric(lon, lat)
        for geom in (p, p.buffer(12.0)):
            for tol in (5.0, 15.0):
                assert cg.edges_near_metric(geom, tol) == pg.edges_near_metric(geom, tol)
        dx, dy = rnd.uniform(1e-4, 4e-3), rnd.uniform(1e-4, 4e-3)
        assert cg.edges_in_bbox(lon, lat, lon + dx, lat + dy) == pg.edges_in_bbox(
            lon, lat, lon + dx, lat + dy
        )


def test_static_costs_equal_edge_cost_bit_for_bit(graphs) -> None:
    pg, cg = graphs
    ref = RoutingEngine(pg)
    eng = CompactRoutingEngine(cg)
    unknown = RiskEstimate.unknown()
    for p in Profile:
        st = eng._static[p]
        assert set(st.allowed) == ref._static[p].allowed
        assert st.allowed.sorted_ids() == list(ref._static[p].allowed_sorted)
        for eid in ref._static[p].allowed:
            c = edge_cost(
                pg.edges[eid],
                p,
                unknown,
                n_confirmed_disruptions=0,
                n_unverified_reports=0,
                avoid_unverified_reports=True,
                config=ref.config,
            )
            assert st.generalized[cg.edge_index(eid)] == c.total_s, (p, eid)


def _full(eng, req, risk, hz):
    try:
        c = eng.compare(req, risk, hz)
    except RoutingError as exc:
        return {"error": exc.code, "detail": str(exc)}
    return {
        "identical": c.identical,
        "risk_layer": c.risk_layer,
        "warnings": c.warnings,
        "routes": [r.to_dict() for r in c.routes],
        "raw": [(r.distance_m, r.duration_s, r.generalized_cost_s, r.labels) for r in c.routes],
    }


def test_compare_output_identical_unrounded() -> None:
    ref = _cases(compact=False)
    new = _cases(compact=True)
    assert [c[0] for c in ref] == [c[0] for c in new]
    for (cid, e1, req, r1, h1), (_, e2, _, r2, h2) in zip(ref, new, strict=True):
        assert isinstance(e2, CompactRoutingEngine)
        assert _full(e2, req, r2, h2) == _full(e1, req, r1, h1), cid


def test_time_weight_search_identical(graphs) -> None:
    pg, cg = graphs
    nodes = list(pg.nodes.values())
    rnd = random.Random(9)
    e1, e2 = RoutingEngine(pg), CompactRoutingEngine(cg)
    for i in range(12):
        a, b = rnd.sample(nodes, 2)
        req = RouteRequest((a.lon, a.lat), (b.lon, b.lat), AT, PROFILES[i % 3])
        for algo in ("dijkstra", "astar"):
            try:
                r1, _ = e1.shortest_path(req, _null(), weight="time", algorithm=algo)
            except RoutingError as exc:
                with pytest.raises(type(exc)):
                    e2.shortest_path(req, _null(), weight="time", algorithm=algo)
                continue
            r2, _ = e2.shortest_path(req, _null(), weight="time", algorithm=algo)
            assert (r2.cost, r2.labels, r2.nodes, r2.settled) == (
                r1.cost,
                r1.labels,
                r1.nodes,
                r1.settled,
            )


def _null():
    from winterpath_routing import NullRiskProvider

    return NullRiskProvider()


def test_integrity_errors_match() -> None:
    meta = GraphMetadata(simulated=True)
    n = {k: Node(k, -73.57 + i * 1e-3, 45.5) for i, k in enumerate("ab")}
    coords = ((-73.57, 45.5), (-73.569, 45.5))
    ok = Edge("e1", "a", "b", coords, 78.0, "footway")
    for edges in (
        [ok, ok],  # duplicate id
        [Edge("e2", "a", "zz", coords, 78.0, "footway")],  # unknown node
        [Edge("e3", "a", "b", coords, 0.0, "footway")],  # non-positive length
    ):
        data = GraphData(nodes=n, edges=edges, metadata=meta)
        with pytest.raises(GraphIntegrityError) as e1:
            PedestrianGraph(data)
        with pytest.raises(GraphIntegrityError) as e2:
            CompactGraph.from_graph_data(data)
        assert str(e1.value) == str(e2.value)


def test_component_order_ties_by_min_node_id() -> None:
    # two disjoint components of equal size: the one with the smaller min node id comes first
    nodes = {
        "z1": (-73.570, 45.500),
        "z2": (-73.569, 45.500),
        "a1": (-73.560, 45.500),
        "a2": (-73.559, 45.500),
        "solo": (-73.550, 45.500),
    }
    pg, cg = _pair(build_graph(nodes, [("z1", "z2", {}), ("a1", "a2", {})]))
    assert cg.components == pg.components == [{"a1", "a2"}, {"z1", "z2"}]
    assert set(cg.main_component_edge_ids) == pg.main_component_edge_ids
