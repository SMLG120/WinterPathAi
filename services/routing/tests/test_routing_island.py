"""Island-scale additions to the compact engine (v2): the prebuilt graph artifact, the compiled
search (``fast_search``) and array-backed risk (``EdgeRiskSnapshot``).

Run on the REAL pilot_mini OSM fixture and the SYNTHETIC golden grid (hazards of every kind, a
static TEST risk layer). The reference is always the existing engine on the same inputs.
"""

from __future__ import annotations

import dataclasses
import itertools
import math

import numpy as np
import pytest
from test_routing_golden import _cases

from winterpath_routing import (
    Evidence,
    EvidenceState,
    RiskEstimate,
    RiskLevel,
    RoutingError,
    compact_io,
)
from winterpath_routing.compact_engine import CompactRoutingEngine

LEVELS = (RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.ELEVATED, RiskLevel.HIGH, RiskLevel.UNKNOWN)


def _outcome(engine, req, risk, hazards):
    try:
        return engine.compare(req, risk, hazards)
    except RoutingError as exc:
        return type(exc)


def _plain(res):
    return [dataclasses.asdict(r) for r in res.routes], res.identical, res.warnings


@pytest.fixture(scope="module")
def cases():
    return _cases(compact=True)


@pytest.fixture(scope="module")
def graphs(cases):
    return list({id(c[1].graph): c[1].graph for c in cases}.values())


# ----------------------------------------------------------------------------- artifact
@pytest.mark.parametrize("mmap", [False, True])
def test_artifact_round_trip_is_exact(cases, graphs, tmp_path, mmap) -> None:
    loaded = {}
    for k, g in enumerate(graphs):
        path = tmp_path / f"g{k}.npz"
        extra = np.arange(5, dtype=np.int32)
        compact_io.save(g, path, extras={"demo": extra}, info={"coverage": {"name": "TEST"}})
        g2, extras, info = compact_io.load(path, mmap=mmap)
        assert info == {"coverage": {"name": "TEST"}} and np.array_equal(extras["demo"], extra)
        assert g2.metadata == g.metadata
        assert list(g2.edges) == list(g.edges) and list(g2.nodes) == list(g.nodes)
        assert all(g2.edges[e] == g.edges[e] for e in g.edges)
        assert all(g2.nodes[n] == g.nodes[n] for n in g.nodes)
        assert set(g2.main_component_edge_ids) == set(g.main_component_edge_ids)
        assert g2.largest_component_share == g.largest_component_share
        assert [x.edge_count for x in g2.gaps()] == [x.edge_count for x in g.gaps()]
        loaded[id(g)] = CompactRoutingEngine(g2)
    for cid, engine, req, risk, hazards in cases:
        a = _outcome(engine, req, risk, hazards)
        b = _outcome(loaded[id(engine.graph)], req, risk, hazards)
        assert (a if isinstance(a, type) else _plain(a)) == (
            b if isinstance(b, type) else _plain(b)
        ), cid


def test_artifact_rejects_foreign_files(tmp_path) -> None:
    bad = tmp_path / "bad.npz"
    np.savez(bad, header=np.frombuffer(b'{"format": "other", "version": 1}', dtype=np.uint8))
    with pytest.raises(compact_io.ArtifactError):
        compact_io.load(bad)
    junk = tmp_path / "junk.npz"
    junk.write_bytes(b"not a zip")
    with pytest.raises(compact_io.ArtifactError):
        compact_io.load(junk)
    with pytest.raises(compact_io.ArtifactError):
        compact_io.load(junk, mmap=True)
    with pytest.raises(compact_io.ArtifactError):
        compact_io.load(bad, mmap=True)
    assert len(compact_io.sha256_file(junk)) == 64


# ----------------------------------------------------------------------------- fast search
def test_fast_search_finds_the_same_optimum(cases) -> None:
    fast = {}
    compared = 0
    for cid, engine, req, risk, hazards in cases:
        f = fast.setdefault(id(engine.graph), CompactRoutingEngine(engine.graph, fast_search=True))
        a, b = _outcome(engine, req, risk, hazards), _outcome(f, req, risk, hazards)
        if isinstance(a, type):
            assert b is a, cid
            continue
        assert not isinstance(b, type), cid
        short_a, winter_a = a.routes
        short_b, winter_b = b.routes
        assert math.isclose(short_a.distance_m, short_b.distance_m, rel_tol=1e-12), cid
        assert math.isclose(
            winter_a.generalized_cost_s, winter_b.generalized_cost_s, rel_tol=1e-12
        ), cid
        # a valid route: consecutive, allowed edges from origin to destination
        g = engine.graph
        for r in b.routes:
            es = [g.edges[e] for e in r.edge_ids]
            assert all(x.to_node_id == y.from_node_id for x, y in itertools.pairwise(es)), cid
            assert all(e.foot_legal for e in es), cid
        compared += 1
    assert compared >= 10


def test_fast_search_time_weight_and_no_path(cases) -> None:
    cid, engine, req, risk, hazards = next(
        c for c in cases if not isinstance(_outcome(*c[1:]), type)
    )
    f = CompactRoutingEngine(engine.graph, fast_search=True)
    for weight in ("distance", "time", "generalized"):
        r1, _ = engine.shortest_path(req, risk, hazards, weight=weight)
        r2, _ = f.shortest_path(req, risk, hazards, weight=weight)
        assert math.isclose(r1.cost, r2.cost, rel_tol=1e-12), (cid, weight)
        assert r2.nodes[0] == r1.nodes[0] and r2.nodes[-1] == r1.nodes[-1]


# ----------------------------------------------------------------------------- snapshot risk
class _Snap:
    level_values = LEVELS
    any_simulated = False

    def __init__(self, graph, levels_by_id, state) -> None:
        self.token = ("TEST", 1)
        self.levels = np.full(len(graph.length), LEVELS.index(RiskLevel.UNKNOWN), dtype=np.uint8)
        self._est = {}
        for eid, lv in levels_by_id.items():
            i = graph.edge_index(eid)
            if i >= 0:
                self.levels[i] = LEVELS.index(lv)
                self._est[i] = RiskEstimate(lv, Evidence(state, ("test",)))
        self.any_simulated = state is EvidenceState.SIMULATED and bool(self._est)

    def estimate(self, i):
        return self._est.get(i)


class _SnapshotProvider:
    """The id-keyed TEST provider, plus the whole-graph capability built from the same levels."""

    def __init__(self, inner, graph) -> None:
        self.inner, self.risk_layer = inner, inner.risk_layer
        self.snap = _Snap(graph, inner.levels, inner.state)
        self.id_calls = 0

    def edge_risk(self, edge_ids, at):
        self.id_calls += 1
        return self.inner.edge_risk(edge_ids, at)

    def edge_risk_snapshot(self, at):
        return self.snap


@pytest.mark.parametrize("fast", [False, True])
def test_snapshot_risk_matches_id_keyed_risk(cases, fast) -> None:
    engines = {}
    with_risk = 0
    for cid, engine, req, risk, hazards in cases:
        if not hasattr(risk, "levels"):
            continue
        e = engines.setdefault(
            id(engine.graph), CompactRoutingEngine(engine.graph, fast_search=fast)
        )
        provider = _SnapshotProvider(risk, engine.graph)
        a, b = _outcome(e, req, risk, hazards), _outcome(e, req, provider, hazards)
        assert provider.id_calls == 0, cid  # never asks for every edge id
        if isinstance(a, type):
            assert b is a, cid
            continue
        assert _plain(a) == _plain(b), cid
        with_risk += any(r.risk_cost_s > 0 for r in a.routes)
    assert with_risk >= 1


def test_snapshot_for_another_graph_is_ignored(cases) -> None:
    _cid, engine, req, risk, hazards = next(c for c in cases if hasattr(c[3], "levels"))
    provider = _SnapshotProvider(risk, engine.graph)
    provider.snap.levels = provider.snap.levels[:-1]  # wrong length → fall back to edge_risk
    a, b = _outcome(engine, req, risk, hazards), _outcome(engine, req, provider, hazards)
    assert provider.id_calls == 1
    assert (a if isinstance(a, type) else _plain(a)) == (b if isinstance(b, type) else _plain(b))
