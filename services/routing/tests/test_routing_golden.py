"""Regression: route output on fixed OD sets must not change when the engine is optimised.

The golden file was generated from the engine BEFORE the cycle-14 performance work
(``WP_REGEN_GOLDEN=1`` rewrites it; never regenerate to make a failing run pass without
explaining why outputs changed). It covers the REAL pilot_mini OSM fixture and a SYNTHETIC
grid with mixed attributes (lit, step_free, steps, one-way, no foot access), hazards of every
routing-relevant kind (hard closure, possible closure, confirmed disruption, unverified report),
no risk layer and a static TEST risk layer, all three profiles, both locales, and off-network
points (errors are part of the expected output).

Compared exactly: error code, edge sequences of both routes, ``identical``, warnings and
explanation codes. Compared to 0.05: distance, duration and generalized cost (rounded output;
tolerance only absorbs cross-platform floating-point differences in the last digit).
"""

from __future__ import annotations

import json
import os
import random
from datetime import UTC, datetime
from pathlib import Path

import pytest
from routing_testlib import PILOT_MINI, StaticRiskProvider, build_graph

from winterpath_routing import (
    Evidence,
    EvidenceState,
    FixtureGraphProvider,
    GraphData,
    Hazard,
    HazardKind,
    NullRiskProvider,
    PedestrianGraph,
    Profile,
    RiskLevel,
    RouteRequest,
    RoutingEngine,
    RoutingError,
)
from winterpath_routing.compact import CompactGraph
from winterpath_routing.compact_engine import CompactRoutingEngine

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "compare_golden.json"
AT = datetime(2026, 12, 15, 15, 0, tzinfo=UTC)
PROFILES = [Profile.STANDARD, Profile.REDUCED_MOBILITY, Profile.STEP_FREE]
W, S, E, N = (-73.5800, 45.5000, -73.5700, 45.5070)  # synthetic grid extent
NUM_TOL = 0.05


def _synthetic_graph() -> PedestrianGraph:
    rnd = random.Random(14)
    rows, cols = 12, 14
    nodes = {
        f"s{r}_{c}": (W + (E - W) * c / (cols - 1), S + (N - S) * r / (rows - 1))
        for r in range(rows)
        for c in range(cols)
    }
    edges = []
    for r in range(rows):
        for c in range(cols):
            for dr, dc in ((0, 1), (1, 0), (1, 1)):
                rr, cc = r + dr, c + dc
                if rr >= rows or cc >= cols or (dr and dc and rnd.random() < 0.7):
                    continue
                x = rnd.random()
                props = {
                    "lit": rnd.choice([True, False, None]),
                    "step_free": rnd.choice([True, True, False, None]),
                    "edge_kind": "steps" if x < 0.04 else "footway",
                    "oneway": 0.04 <= x < 0.08,
                    "foot_access": "no" if 0.08 <= x < 0.10 else "yes",
                }
                edges.append((f"s{r}_{c}", f"s{rr}_{cc}", props))
    return build_graph(nodes, edges)


def _hazard(hid, lonlat, kind, state, blocks, active=True) -> Hazard:
    return Hazard(
        hazard_id=hid,
        kind=kind,
        geometry={"type": "Point", "coordinates": list(lonlat)},
        evidence=Evidence(state, ("test",)),
        blocks_passage=blocks,
        active=active,
    )


def _synthetic_hazards(g: PedestrianGraph) -> list[Hazard]:
    rnd = random.Random(7)
    picks = rnd.sample(sorted(g.edges), 40)
    out = []
    specs = [
        (HazardKind.SIDEWALK_CLOSURE, EvidenceState.CONFIRMED, True, True),  # hard closure
        (HazardKind.SIDEWALK_CLOSURE, EvidenceState.CONFIRMED, True, None),  # possible closure
        (HazardKind.CONSTRUCTION_IMPACT, EvidenceState.CONFIRMED, False, True),  # disruption
        (HazardKind.COMMUNITY_REPORT, EvidenceState.UNVERIFIED_REPORT, False, True),  # report
    ]
    for i, edge_id in enumerate(picks):
        (a, b) = g.edges[edge_id].coords[0], g.edges[edge_id].coords[-1]
        kind, state, blocks, active = specs[i % 4]
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        out.append(_hazard(f"TEST-HZ-{i}", mid, kind, state, blocks, active))
    return out


def _risk_for(g: PedestrianGraph) -> StaticRiskProvider:
    rnd = random.Random(3)
    levels = [RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.ELEVATED, RiskLevel.HIGH]
    return StaticRiskProvider(
        {e: rnd.choice(levels) for e in sorted(g.edges) if rnd.random() < 0.6}
    )


def _ods(bbox, n, seed):
    w, s, e, nb = bbox
    rnd = random.Random(seed)
    return [
        (
            (round(rnd.uniform(w, e), 6), round(rnd.uniform(s, nb), 6)),
            (round(rnd.uniform(w, e), 6), round(rnd.uniform(s, nb), 6)),
        )
        for _ in range(n)
    ]


def _cases(compact: bool = False):
    """(case_id, engine, request, risk, hazards) — deterministic.

    ``compact``: the same graphs as :class:`CompactGraph` routed by :class:`CompactRoutingEngine`
    (ROUTING_COMPACT_GRAPH prototype); it must reproduce the golden file exactly too.
    """
    pm = PedestrianGraph(FixtureGraphProvider(PILOT_MINI).load())
    meta = json.loads((PILOT_MINI / "metadata.json").read_text())
    syn = _synthetic_graph()
    out = []
    for name, g, bbox, hz in (
        ("pilot_mini", pm, meta["bbox"], []),
        ("synthetic", syn, (W, S, E, N), _synthetic_hazards(syn)),
    ):
        if compact:
            g = CompactGraph.from_graph_data(_graph_data(g))
            eng = CompactRoutingEngine(g)
        else:
            eng = RoutingEngine(g)
        risks = {"none": NullRiskProvider(), "static": _risk_for(g)}
        for i, (o, d) in enumerate(_ods(bbox, 24, seed=len(name))):
            profile = PROFILES[i % 3]
            locale = "fr" if i % 2 else "en"
            for rname, risk in risks.items():
                req = RouteRequest(
                    o, d, AT, profile, avoid_unverified_reports=i % 4 != 3, locale=locale
                )
                out.append((f"{name}/{i}/{profile.value}/{rname}", eng, req, risk, hz))
    return out


def _observe(eng, req, risk, hz) -> dict:
    try:
        c = eng.compare(req, risk, hz)
    except RoutingError as exc:
        return {"error": exc.code}
    return {
        "identical": c.identical,
        "warnings": c.warnings,
        "routes": [
            {
                "variant": r.variant.value,
                "edge_ids": r.edge_ids,
                "distance_m": round(r.distance_m, 1),
                "duration_s": round(r.duration_s, 1),
                "generalized_cost_s": round(r.generalized_cost_s, 1),
                "unknown_share": round(r.unknown_share, 4),
                "hazards_on_route": r.hazards_on_route,
                "hazards_avoided": r.hazards_avoided,
                "explanation": [e.code for e in r.explanation],
                "n_steps": len(r.steps),
            }
            for r in c.routes
        ],
    }


def _graph_data(g: PedestrianGraph) -> GraphData:
    return GraphData(nodes=dict(g.nodes), edges=list(g.edges.values()), metadata=g.metadata)


@pytest.fixture(scope="module", params=["networkx", "compact"])
def observed(request) -> dict[str, dict]:
    compact = request.param == "compact"
    return {
        cid: _observe(eng, req, risk, hz) for cid, eng, req, risk, hz in _cases(compact=compact)
    }


def test_golden_compare_outputs_unchanged(observed) -> None:
    if os.environ.get("WP_REGEN_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(observed, indent=1, sort_keys=True) + "\n")
        pytest.skip(f"golden regenerated: {GOLDEN}")
    golden = json.loads(GOLDEN.read_text())
    assert set(observed) == set(golden)
    # The fixed set must actually exercise both outcomes and the hazard paths.
    oks = [v for v in golden.values() if "routes" in v]
    assert len(oks) >= 60 and len(golden) - len(oks) >= 5
    assert any(r["hazards_on_route"] or r["hazards_avoided"] for v in oks for r in v["routes"])
    assert any(not v["identical"] for v in oks)
    for cid, exp in golden.items():
        got = observed[cid]
        if "error" in exp:
            assert got == exp, cid
            continue
        assert "routes" in got, (cid, got)
        assert (got["identical"], got["warnings"]) == (exp["identical"], exp["warnings"]), cid
        for gr, er in zip(got["routes"], exp["routes"], strict=True):
            for k in (
                "variant",
                "edge_ids",
                "hazards_on_route",
                "hazards_avoided",
                "explanation",
                "n_steps",
            ):
                assert gr[k] == er[k], (cid, k)
            for k in ("distance_m", "duration_s", "generalized_cost_s", "unknown_share"):
                assert abs(gr[k] - er[k]) <= NUM_TOL, (cid, k, gr[k], er[k])
