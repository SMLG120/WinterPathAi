"""Hand-checked routing behaviour on SYNTHETIC toy graphs."""

from __future__ import annotations

import random
from datetime import timedelta

import pytest
from routing_testlib import AT, StaticRiskProvider, build_graph, eid, gid, grid_node

from winterpath_routing import (
    CostConfig,
    DegenerateRequestError,
    Evidence,
    EvidenceState,
    Hazard,
    HazardKind,
    NoRouteError,
    NullRiskProvider,
    Profile,
    RiskLevel,
    RouteRequest,
    RoutingEngine,
    SnapError,
)
from winterpath_routing.geo import haversine_m

NULL = NullRiskProvider()


def req(o, d, **kw) -> RouteRequest:
    return RouteRequest(origin=o, destination=d, at=AT, **kw)


def length(graph, *pairs) -> float:
    return sum(graph.edges[eid(a, b)].length_m for a, b in pairs)


def codes(route) -> list[str]:
    return [e.code for e in route.explanation]


def mid(a, b, f=0.5):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def point_hazard(hid, at_lonlat, *, blocks, state=EvidenceState.CONFIRMED, **kw) -> Hazard:
    kind = HazardKind.SIDEWALK_CLOSURE if blocks else HazardKind.CONSTRUCTION_IMPACT
    if state is EvidenceState.UNVERIFIED_REPORT:
        kind = HazardKind.COMMUNITY_REPORT
    return Hazard(
        hazard_id=hid,
        kind=kind,
        geometry={"type": "Point", "coordinates": list(at_lonlat)},
        evidence=Evidence(state, ("test",)),
        blocks_passage=blocks,
        **kw,
    )


# --------------------------------------------------------------------------- baseline


def test_shortest_hand_checked_and_never_uses_prohibited_shortcut(engine, toy_graph) -> None:
    res = engine.compare(req(grid_node(0, 0), grid_node(1, 1)), NULL)
    short = res.routes[0]
    # Diagonal r0c0→r1c1 (≈110 m) has foot_access=no; legal path is two edges (≈156 m).
    expected = length(toy_graph, (gid(0, 0), gid(0, 1)), (gid(0, 1), gid(1, 1)))
    alt = length(toy_graph, (gid(0, 0), gid(1, 0)), (gid(1, 0), gid(1, 1)))
    assert short.distance_m == pytest.approx(min(expected, alt), abs=0.01)
    assert eid(gid(0, 0), gid(1, 1)) not in short.edge_ids
    assert short.duration_s == pytest.approx(short.distance_m / 1.3, rel=1e-6)


@pytest.mark.parametrize("seed", range(5))
def test_prohibited_edges_never_used_random_pairs(engine, toy_graph, seed) -> None:
    rnd = random.Random(seed)
    for _ in range(20):
        o = (rnd.uniform(-73.578, -73.575), rnd.uniform(45.503, 45.5044))
        d = (rnd.uniform(-73.578, -73.575), rnd.uniform(45.503, 45.5044))
        if haversine_m(o, d) < 5:
            continue
        for r in engine.compare(req(o, d), NULL).routes:
            for e in r.edge_ids:
                assert toy_graph.edges[e].foot_access not in ("no", "private")


@pytest.mark.parametrize("seed", range(5))
def test_dijkstra_equals_astar_generalized_cost(engine, toy_graph, seed) -> None:
    rnd = random.Random(100 + seed)
    levels = {e: rnd.choice(list(RiskLevel)) for e in toy_graph.edges if rnd.random() < 0.7}
    risk = StaticRiskProvider(levels)
    hazards = [
        point_hazard("dis-1", mid(grid_node(1, 1), grid_node(1, 2)), blocks=False),
        point_hazard(
            "rep-1",
            mid(grid_node(2, 0), grid_node(2, 1)),
            blocks=None,
            state=EvidenceState.UNVERIFIED_REPORT,
        ),
    ]
    for _ in range(15):
        o = (rnd.uniform(-73.578, -73.575), rnd.uniform(45.503, 45.5044))
        d = (rnd.uniform(-73.578, -73.575), rnd.uniform(45.503, 45.5044))
        if haversine_m(o, d) < 5:
            continue
        r = req(o, d, profile=rnd.choice([Profile.STANDARD, Profile.REDUCED_MOBILITY]))
        dj, _ = engine.shortest_path(r, risk, hazards, weight="generalized", algorithm="dijkstra")
        a, _ = engine.shortest_path(r, risk, hazards, weight="generalized", algorithm="astar")
        assert a.cost == pytest.approx(dj.cost, rel=1e-9, abs=1e-9)
        assert a.settled <= dj.settled
        # shortest-time Dijkstra and A* agree too
        dj_t, _ = engine.shortest_path(r, risk, hazards, weight="time", algorithm="dijkstra")
        a_t, _ = engine.shortest_path(r, risk, hazards, weight="time", algorithm="astar")
        assert a_t.cost == pytest.approx(dj_t.cost, rel=1e-9, abs=1e-9)


# --------------------------------------------------------------------------- closures


def test_confirmed_blocking_closure_is_excluded_not_penalised(engine, toy_graph) -> None:
    a, b = gid(0, 0), gid(0, 1)
    closure = point_hazard("entrave:1", mid(grid_node(0, 0), grid_node(0, 1)), blocks=True)
    res = engine.compare(req(grid_node(0, 0), grid_node(0, 1)), NULL, [closure])
    for r in res.routes:
        assert eid(a, b) not in r.edge_ids and eid(b, a) not in r.edge_ids
        assert r.distance_m > length(toy_graph, (a, b)) * 2
        assert "EXCLUDES_CONFIRMED_CLOSURE" in codes(r)


def test_closure_outside_validity_window_is_ignored(engine, toy_graph) -> None:
    closure = point_hazard(
        "entrave:2",
        mid(grid_node(0, 0), grid_node(0, 1)),
        blocks=True,
        valid_to=AT - timedelta(days=1),
    )
    res = engine.compare(req(grid_node(0, 0), grid_node(0, 1)), NULL, [closure])
    assert res.routes[0].edge_ids == [eid(gid(0, 0), gid(0, 1))]


def test_unconfirmed_blocking_report_is_not_a_hard_exclusion(engine) -> None:
    rep = point_hazard(
        "community:1",
        mid(grid_node(0, 0), grid_node(0, 1)),
        blocks=True,
        state=EvidenceState.UNVERIFIED_REPORT,
    )
    res = engine.compare(req(grid_node(0, 0), grid_node(0, 1)), NULL, [rep])
    assert res.routes[0].edge_ids == [eid(gid(0, 0), gid(0, 1))]
    assert res.routes[0].hazards_on_route == ["community:1"]
    assert "PASSES_UNVERIFIED_REPORT" in codes(res.routes[0])


# --------------------------------------------------------------------------- winter-aware


def _diamond():
    # A→B→D ≈ 2×100 m (north then east); A→C→D slightly longer (C offset).
    lon, lat = -73.575, 45.505
    dlat100 = 100 / 111_195
    dlon100 = 100 / 77_950
    nodes = {
        "A": (lon, lat),
        "B": (lon, lat + dlat100),
        "D": (lon + dlon100, lat + dlat100),
        "C": (lon + dlon100 * 1.05, lat - dlat100 * 0.05),
    }
    edges = [("A", "B", {}), ("B", "D", {}), ("A", "C", {}), ("C", "D", {})]
    return build_graph(nodes, edges), nodes


def test_winter_aware_avoids_confirmed_disruption_shortest_does_not() -> None:
    g, n = _diamond()
    eng = RoutingEngine(g)
    dis = point_hazard("entrave:9", mid(n["A"], n["B"]), blocks=False)
    res = eng.compare(req(n["A"], n["D"]), NULL, [dis])
    short, winter = res.routes
    assert short.edge_ids == ["A>B:0", "B>D:0"]
    assert winter.edge_ids == ["A>C:0", "C>D:0"]
    assert short.hazards_on_route == ["entrave:9"]
    assert winter.hazards_avoided == ["entrave:9"]
    assert "AVOIDS_CONFIRMED_DISRUPTION" in codes(winter)
    assert "PASSES_CONFIRMED_DISRUPTION" in codes(short)
    assert not res.identical


def test_unverified_reports_only_penalised_when_requested() -> None:
    g, n = _diamond()
    eng = RoutingEngine(g)
    rep = point_hazard(
        "311:abc", mid(n["B"], n["D"]), blocks=None, state=EvidenceState.UNVERIFIED_REPORT
    )
    avoid = eng.compare(req(n["A"], n["D"], avoid_unverified_reports=True), NULL, [rep])
    keep = eng.compare(req(n["A"], n["D"], avoid_unverified_reports=False), NULL, [rep])
    assert avoid.routes[1].edge_ids == ["A>C:0", "C>D:0"]
    assert "AVOIDS_UNVERIFIED_REPORT" in codes(avoid.routes[1])
    assert keep.routes[1].edge_ids == ["A>B:0", "B>D:0"]
    assert keep.identical


def test_model_risk_changes_winter_route_and_is_explained() -> None:
    g, n = _diamond()
    eng = RoutingEngine(g)
    levels = {e: RiskLevel.LOW for e in g.edges}
    levels["A>B:0"] = RiskLevel.HIGH
    res = eng.compare(req(n["A"], n["D"]), StaticRiskProvider(levels), [])
    short, winter = res.routes
    assert short.edge_ids == ["A>B:0", "B>D:0"]
    assert winter.edge_ids == ["A>C:0", "C>D:0"]
    assert "LOWER_MODELED_RISK" in codes(winter)
    assert winter.unknown_share == 0.0
    assert res.risk_layer == "heuristic"


def test_risk_with_non_model_evidence_is_treated_as_unknown() -> None:
    g, n = _diamond()
    eng = RoutingEngine(g)
    levels = dict.fromkeys(g.edges, RiskLevel.LOW)
    res = eng.compare(
        req(n["A"], n["D"]), StaticRiskProvider(levels, state=EvidenceState.UNVERIFIED_REPORT), []
    )
    assert res.routes[0].unknown_share == 1.0


def test_unknown_risk_is_never_zero_cost(engine) -> None:
    res = engine.compare(req(grid_node(0, 0), grid_node(0, 3)), NULL)
    for r in res.routes:
        assert r.unknown_share == 1.0
        assert r.generalized_cost_s > r.duration_s  # unknown penalty applied
        assert "RISK_LAYER_UNAVAILABLE" in codes(r)
    cfg = CostConfig()
    expected_unknown = cfg.unknown_penalty_s_per_100m * res.routes[0].distance_m / 100
    assert res.routes[0].generalized_cost_s == pytest.approx(
        res.routes[0].duration_s + expected_unknown, rel=1e-6
    )


def test_partial_unknown_share() -> None:
    g, n = _diamond()
    eng = RoutingEngine(g)
    levels = {"A>B:0": RiskLevel.LOW}  # B>D unknown
    res = eng.compare(req(n["A"], n["D"]), StaticRiskProvider(levels), [])
    short = res.routes[0]
    ab, bd = g.edges["A>B:0"].length_m, g.edges["B>D:0"].length_m
    assert short.unknown_share == pytest.approx(bd / (ab + bd), rel=1e-6)
    assert "RISK_UNKNOWN_SHARE" in codes(short)


# --------------------------------------------------------------------------- accessibility


def test_step_free_is_hard_constraint(engine, toy_graph) -> None:
    std = engine.compare(req(grid_node(0, 0), grid_node(2, 0)), NULL)
    sf = engine.compare(req(grid_node(0, 0), grid_node(2, 0), profile=Profile.STEP_FREE), NULL)
    assert std.routes[0].distance_m == pytest.approx(
        length(toy_graph, (gid(0, 0), gid(1, 0)), (gid(1, 0), gid(2, 0))), abs=0.01
    )
    for r in sf.routes:
        assert all(toy_graph.edges[e].step_free is True for e in r.edge_ids)
        assert "STEP_FREE_TAGGED_ONLY" in codes(r)
    # around the perimeter: r0 row (3) + c3 column (2) + r2 row (3)
    perimeter = length(
        toy_graph,
        *[(gid(0, c), gid(0, c + 1)) for c in range(3)],
        (gid(0, 3), gid(1, 3)),
        (gid(1, 3), gid(2, 3)),
        *[(gid(2, c), gid(2, c - 1)) for c in range(3, 0, -1)],
    )
    assert sf.routes[0].distance_m == pytest.approx(perimeter, abs=0.01)


def test_step_free_no_route_is_404_not_fallback() -> None:
    lon, lat, d = -73.575, 45.505, 0.0008
    nodes = {"A": (lon, lat), "B": (lon + d, lat), "C": (lon + 2 * d, lat), "D": (lon + 3 * d, lat)}
    g = build_graph(
        nodes,
        [
            ("A", "B", {"step_free": True}),
            ("B", "C", {"step_free": None}),
            ("C", "D", {"step_free": True}),
        ],
    )
    eng = RoutingEngine(g)
    assert eng.compare(req(nodes["A"], nodes["D"]), NULL).routes[0].distance_m > 0
    with pytest.raises(NoRouteError) as ei:
        eng.compare(req(nodes["A"], nodes["D"], profile=Profile.STEP_FREE), NULL)
    assert "step-free" in str(ei.value)


def test_reduced_mobility_avoids_steps_when_alternative_exists(engine, toy_graph) -> None:
    o, d = grid_node(1, 1), grid_node(2, 1)
    std = engine.compare(req(o, d), NULL)
    rm = engine.compare(req(o, d, profile=Profile.REDUCED_MOBILITY), NULL)
    steps_edge = eid(gid(1, 1), gid(2, 1))
    assert std.routes[0].edge_ids == [steps_edge]
    assert "INCLUDES_STEPS" in codes(std.routes[0])
    assert steps_edge not in rm.routes[1].edge_ids
    assert rm.routes[0].duration_s == pytest.approx(rm.routes[0].distance_m / 0.9, rel=1e-6)
    assert "REDUCED_MOBILITY_SPEED" in codes(rm.routes[1])


# --------------------------------------------------------------------------- snapping


def test_snap_rejects_points_far_from_network(engine) -> None:
    far = (grid_node(0, 0)[0], grid_node(0, 0)[1] - 0.0012)  # ≈133 m south
    with pytest.raises(SnapError) as ei:
        engine.compare(req(far, grid_node(1, 1)), NULL)
    assert ei.value.which == "origin"


def test_snap_within_limit_and_partial_edges(engine, toy_graph) -> None:
    o = mid(grid_node(0, 0), grid_node(0, 1))
    d = mid(grid_node(0, 1), grid_node(0, 2))
    near = (o[0], o[1] - 0.0004)  # ≈44 m south of the edge: still snaps
    r = engine.compare(req(near, d), NULL).routes[0]
    half = (
        length(toy_graph, (gid(0, 0), gid(0, 1))) / 2
        + length(toy_graph, (gid(0, 1), gid(0, 2))) / 2
    )
    assert r.distance_m == pytest.approx(half, abs=0.05)
    assert r.edge_ids == [eid(gid(0, 0), gid(0, 1)), eid(gid(0, 1), gid(0, 2))]
    # geometry starts at the snapped point, [lon, lat] order
    first = r.coordinates[0]
    assert first[0] == pytest.approx(o[0], abs=1e-6) and first[1] == pytest.approx(o[1], abs=1e-6)
    assert any(
        "44 m" in w or "45 m" in w or "43 m" in w
        for w in engine.compare(req(near, d), NULL).warnings
    )


def test_same_edge_forward_and_reverse(engine, toy_graph) -> None:
    a, b = grid_node(0, 0), grid_node(0, 1)
    seg = length(toy_graph, (gid(0, 0), gid(0, 1)))
    fwd = engine.compare(req(mid(a, b, 0.25), mid(a, b, 0.75)), NULL).routes[0]
    assert fwd.edge_ids == [eid(gid(0, 0), gid(0, 1))]
    assert fwd.distance_m == pytest.approx(seg / 2, abs=0.05)
    rev = engine.compare(req(mid(a, b, 0.75), mid(a, b, 0.25)), NULL).routes[0]
    assert rev.edge_ids == [eid(gid(0, 1), gid(0, 0))]
    assert rev.distance_m == pytest.approx(seg / 2, abs=0.05)


def test_degenerate_same_point_rejected(engine) -> None:
    with pytest.raises(DegenerateRequestError):
        engine.compare(req(grid_node(0, 0), grid_node(0, 0)), NULL)


def test_disconnected_component_reported_and_not_routable(engine, toy_graph) -> None:
    gaps = toy_graph.gaps()
    assert len(gaps) == 1 and gaps[0].edge_count == 2
    assert toy_graph.largest_component_share == pytest.approx(34 / 36)
    iso = (-73.5780 + 7.5 * 0.0010, 45.5030)  # on the isolated path, >75 m from main network
    with pytest.raises(SnapError):
        engine.compare(req(iso, grid_node(0, 0)), NULL)


# --------------------------------------------------------------------------- output


def test_simulated_graph_is_flagged(engine) -> None:
    res = engine.compare(req(grid_node(0, 0), grid_node(0, 2)), NULL)
    assert any(w.startswith("SIMULATED") for w in res.warnings)
    for r in res.routes:
        assert r.explanation[0].code == "SIMULATED_DATA"
        assert r.explanation[0].evidence_state is EvidenceState.SIMULATED


def test_steps_and_localization(engine) -> None:
    # r0c0 → r0c3 is a straight eastward walk along Synthetic Street A (unique shortest path)
    en = engine.compare(req(grid_node(0, 0), grid_node(0, 3)), NULL).routes[0]
    fr = engine.compare(req(grid_node(0, 0), grid_node(0, 3), locale="fr"), NULL).routes[0]
    assert en.steps[0].instruction == "Head east on Synthetic Street A"
    assert len(en.steps) == 2  # one maneuver + arrival
    assert en.steps[-1].instruction == "You have arrived"
    assert fr.steps[0].instruction.startswith("Partez en direction de l'est")
    assert fr.steps[-1].instruction == "Vous êtes à destination"
    assert sum(s.distance_m for s in en.steps) == pytest.approx(en.distance_m, abs=0.5)
    assert fr.explanation[1].text.startswith("Plus courte distance")


def test_no_safety_wording_in_catalog() -> None:
    from winterpath_routing.explain import CATALOG

    banned = (
        "safe ",
        "safe.",
        "cleared",
        "ice-free",
        "wheelchair accessible",
        "sécuritaire",
        "déneigé",
    )
    for _, en, fr in CATALOG.values():
        for word in banned:
            assert word not in en.lower() and word not in fr.lower()


def test_route_dict_shape(engine) -> None:
    res = engine.compare(req(grid_node(0, 0), grid_node(0, 2)), NULL)
    d = res.routes[0].to_dict()
    assert d["geometry"]["type"] == "LineString"
    assert len(d["geometry"]["coordinates"]) >= 2
    assert -74 < d["geometry"]["coordinates"][0][0] < -73
    assert set(d) >= {
        "variant",
        "geometry",
        "distance_m",
        "duration_s",
        "edge_ids",
        "explanation",
        "data_freshness",
        "unknown_share",
    }
