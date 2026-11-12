"""Routing engine over a :class:`~winterpath_routing.compact.CompactGraph` (PROTOTYPE, behind
``ROUTING_COMPACT_GRAPH``; off by default).

Same cost function, exclusions, snapping, search and assembly as :class:`RoutingEngine` — only
the data layout differs:

* per-profile static data is one byte (allowed) and one float (default generalized cost) per
  edge, computed with vectorised arithmetic that performs the same IEEE operations, in the same
  order, as :func:`~winterpath_routing.costs.edge_cost` with risk unknown and no hazard
  (``tests/test_routing_compact.py`` asserts equality with ``edge_cost`` for every edge);
* the search runs over integer node/edge indices and the CSR adjacency, relaxing arcs in the same
  order with the same ``(priority, counter)`` heap keys and the same arithmetic, so it settles
  the same nodes and returns the same path (``tests/test_routing_golden.py``, compact variant).

Per-request costs that differ from the default (hazards, known risk estimates) are computed with
the real :func:`edge_cost` on a materialised ``Edge``.
"""

from __future__ import annotations

import heapq
import itertools
import math
from array import array
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from .compact import CompactGraph, EdgeMask
from .costs import CostConfig, EdgeCost, edge_cost
from .engine import (
    _MAX_EAGER_OVERRIDES,
    END,
    HEURISTIC_SAFETY,
    START,
    RouteRequest,
    RoutingEngine,
    Weight,
    _Context,
    _LazyWeights,
    _Snap,
)
from .models import EvidenceState, Hazard, Profile, RiskEstimate
from .risk import NullRiskProvider, RiskProvider
from .search import NoPathError, SearchResult

_START, _END = -1, -2


@dataclass(frozen=True, slots=True)
class _CompactStatic:
    """Request-independent data for one profile: one byte + one float per edge."""

    allowed: EdgeMask
    #: generalized cost with risk unknown and no hazard (0.0 for edges not allowed)
    generalized: array


class CompactRoutingEngine(RoutingEngine):
    def __init__(
        self,
        graph: CompactGraph,
        config: CostConfig | None = None,
        *,
        steps_v2: bool = False,
    ) -> None:
        self.graph = graph  # type: ignore[assignment]
        self.config = config or CostConfig()
        self.steps_v2 = steps_v2
        self._length = array("d", graph.length.tobytes())
        self._static = {p: self._build_static(p) for p in Profile}  # type: ignore[misc]

    # ------------------------------------------------------------------ static per profile
    def _build_static(self, profile: Profile) -> _CompactStatic:  # type: ignore[override]
        g, cfg = self.graph, self.config

        def where(attr: str, pred) -> np.ndarray:
            codes, values = g.edge_attr(attr)
            hits = [i for i, v in enumerate(values) if pred(v)]
            return np.isin(codes, hits) if hits else np.zeros(len(codes), dtype=bool)

        # exclusion_reason(): foot access, then step-free (STEP_FREE only), then main component
        # (the main-component mask already requires foot-legal edges).
        allowed = np.frombuffer(g.main_mask, dtype=np.uint8).astype(bool)
        if profile is Profile.STEP_FREE:
            allowed &= where("step_free", lambda v: v is True)

        # edge_cost(edge, profile, unknown, 0 disruptions, 0 reports, 0 possible closures):
        # total_s = base + disruption(0.0) + risk(0.0) + unknown + pref, left to right.
        length = g.length
        base = length / cfg.speed_for(profile)
        disruption = cfg.confirmed_disruption_penalty_s * 0
        unknown = cfg.unknown_penalty_s_per_100m * length / 100.0
        pref = np.zeros(len(length))
        lit_false = where("lit", lambda v: v is False)
        pref = np.where(lit_false, pref + base * cfg.unlit_penalty_factor, pref)
        if profile is Profile.REDUCED_MOBILITY:
            hard = where("step_free", lambda v: v is False) | where(
                "edge_kind", lambda v: v == "steps"
            )
            sf_none = where("step_free", lambda v: v is None) & ~hard
            pref = np.where(hard, pref + cfg.reduced_mobility_not_step_free_penalty_s, pref)
            pref = np.where(
                sf_none, pref + base * cfg.reduced_mobility_unknown_step_free_factor, pref
            )
        total = base + disruption + 0.0 + unknown + pref
        total = np.where(allowed, total, 0.0)
        return _CompactStatic(
            allowed=EdgeMask(g, bytearray(allowed.astype(np.uint8).tobytes())),
            generalized=array("d", np.ascontiguousarray(total, dtype=np.float64).tobytes()),
        )

    # ------------------------------------------------------------------ context
    def _context(
        self, req: RouteRequest, risk_provider: RiskProvider, hazards: Iterable[Hazard]
    ) -> _Context:
        g = self.graph
        closures, disruptions, possible, reports = self._match_hazards(req, hazards)
        st: _CompactStatic = self._static[req.profile]  # type: ignore[assignment]
        closed = {eid for eids in closures.values() for eid in eids}
        if closed:
            mask = bytearray(st.allowed.mask)
            for eid in closed:
                mask[g.edge_index(eid)] = 0
            allowed = EdgeMask(g, mask)
        else:
            allowed = st.allowed
        if isinstance(risk_provider, NullRiskProvider) or not len(allowed):
            raw: Mapping[str, RiskEstimate] = {}
        else:
            # O(edges) per request, as in RoutingEngine: see the island-feasibility report.
            raw = risk_provider.edge_risk(allowed.sorted_ids(), req.at)
        any_sim = any(
            r and r.evidence.state is EvidenceState.SIMULATED and eid in allowed
            for eid, r in raw.items()
        )
        risk = {eid: r for eid, r in raw.items() if r and not r.is_unknown and eid in allowed}
        touched = disruptions.keys() | possible.keys() | reports.keys() | risk.keys()
        overrides = frozenset(eid for eid in touched if eid in allowed)
        return _Context(
            req,
            allowed,  # type: ignore[arg-type]
            closures,
            disruptions,
            possible,
            reports,
            risk,
            self.config.speed_for(req.profile),
            any_sim,
            st,  # type: ignore[arg-type]
            overrides,
        )

    def _cost(self, ctx: _Context, eid: str) -> EdgeCost:
        c = ctx._costs.get(eid)
        if c is None:
            c = edge_cost(
                self.graph.edges[eid],
                ctx.req.profile,
                ctx.risk.get(eid) or RiskEstimate.unknown(),
                n_confirmed_disruptions=len(ctx.disruptions.get(eid, ())),
                n_unverified_reports=len(ctx.reports.get(eid, ())),
                avoid_unverified_reports=ctx.req.avoid_unverified_reports,
                config=self.config,
                n_possible_closures=len(ctx.possible.get(eid, ())),
            )
            ctx._costs[eid] = c
        return c

    def _weight(self, ctx: _Context, eid: str, weight: Weight) -> float:
        if weight == "distance":
            return self._length[self.graph.edge_index(eid)]
        c = self._cost(ctx, eid)
        return c.base_s if weight == "time" else c.total_s

    def _weights(self, ctx: _Context, weight: Weight) -> Any:  # type: ignore[override]
        """edge index → arc weight (same values as RoutingEngine._weights by edge id)."""
        name = self.graph.edge_id
        if weight == "distance":
            return self._length
        if weight == "time":
            return _LazyWeights(lambda i: self._cost(ctx, name(i)).base_s)
        st: _CompactStatic = ctx.static  # type: ignore[assignment]
        if not ctx.overrides:
            return st.generalized
        if len(ctx.overrides) <= _MAX_EAGER_OVERRIDES:
            w = array("d", st.generalized)
            for eid in ctx.overrides:
                w[self.graph.edge_index(eid)] = self._cost(ctx, eid).total_s
            return w
        return _LazyWeights(lambda i: self._cost(ctx, name(i)).total_s)

    # ------------------------------------------------------------------ search
    def _search(
        self,
        ctx: _Context,
        o: _Snap,
        t: _Snap,
        weight: Weight,
        algorithm: Literal["dijkstra", "astar"],
    ) -> SearchResult:
        g = self.graph
        idx = g.edge_index
        w = self._weight
        start_arcs = [
            (int(g.to_idx[idx(eid)]), (1.0 - f) * w(ctx, eid, weight), (eid, f, 1.0))
            for eid, f in o.candidates
        ]
        end_arcs: dict[int, list[tuple[int, float, tuple]]] = {}
        for eid, f in t.candidates:
            end_arcs.setdefault(int(g.from_idx[idx(eid)]), []).append(
                (_END, f * w(ctx, eid, weight), (eid, 0.0, f))
            )
        t_frac = dict(t.candidates)
        for eid, fo in o.candidates:
            ft = t_frac.get(eid)
            if ft is not None and ft >= fo:
                start_arcs.append((_END, (ft - fo) * w(ctx, eid, weight), (eid, fo, ft)))
        mask = ctx.allowed.mask  # type: ignore[attr-defined]
        weights = self._weights(ctx, weight)
        if algorithm == "dijkstra":
            res = self._run_idx(start_arcs, end_arcs, mask, weights, None, 0.0)
        else:
            per_m = (1.0 if weight == "distance" else 1.0 / ctx.speed) * HEURISTIC_SAFETY
            res = self._run_idx(start_arcs, end_arcs, mask, weights, t.points, per_m)
        name, node = g.edge_id, g._nids.name
        return SearchResult(
            res.cost,
            [START if n == _START else END if n == _END else node(n) for n in res.nodes],
            [(name(lab), 0.0, 1.0) if isinstance(lab, int) else lab for lab in res.labels],
            res.settled,
        )

    def _run_idx(
        self,
        start_arcs: list[tuple[int, float, tuple]],
        end_arcs: Mapping[int, list[tuple[int, float, tuple]]],
        mask: bytearray,
        weights: Any,
        targets: Sequence[tuple[float, float]] | None,
        per_m: float,
    ) -> SearchResult:
        """RoutingEngine._run over integer indices (same pushes, keys and arithmetic)."""
        g = self.graph
        adj_off, adj_to, adj_edge = g.adj_off, g.adj_to, g.adj_edge
        xs, ys = g.node_x, g.node_y
        hypot = math.hypot
        heappush, heappop = heapq.heappush, heapq.heappop
        inf = math.inf
        single = targets[0] if targets is not None and len(targets) == 1 else None

        def h(n: int) -> float:
            if targets is None or n == _END:
                return 0.0
            x, y = xs[n], ys[n]
            if single is not None:
                return hypot(x - single[0], y - single[1]) * per_m
            return min(hypot(x - tx, y - ty) for tx, ty in targets) * per_m

        counter = itertools.count()
        dist: dict[int, float] = {_START: 0.0}
        parent: dict[int, tuple[int, Any]] = {}
        closed: set[int] = set()
        heap: list[tuple[float, int, int]] = [(0.0, next(counter), _START)]
        no_end: tuple = ()
        while heap:
            _, _, u = heappop(heap)
            if u in closed:
                continue
            if u == _END:
                nodes = [u]
                labels: list[Any] = []
                while u in parent:
                    u, lab = parent[u]
                    labels.append(lab)
                    nodes.append(u)
                nodes.reverse()
                labels.reverse()
                return SearchResult(dist[_END], nodes, labels, len(closed) + 1)
            closed.add(u)
            du = dist[u]
            if u == _START:
                arcs: Iterable[tuple[int, float, Any]] = start_arcs
            else:
                for k in range(adj_off[u], adj_off[u + 1]):
                    e = adj_edge[k]
                    if not mask[e]:
                        continue
                    v = adj_to[k]
                    w = weights[e]
                    if w < 0:
                        raise ValueError(f"negative edge cost {w} on arc {u}->{v}")
                    if v in closed:
                        continue
                    nd = du + w
                    if nd < dist.get(v, inf):
                        dist[v] = nd
                        parent[v] = (u, e)
                        heappush(heap, (nd + h(v), next(counter), v))
                arcs = end_arcs.get(u, no_end)
            for v, w, lab in arcs:
                if w < 0:
                    raise ValueError(f"negative edge cost {w} on arc {u}->{v}")
                if v in closed:
                    continue
                nd = du + w
                if nd < dist.get(v, inf):
                    dist[v] = nd
                    parent[v] = (u, lab)
                    heappush(heap, (nd + h(v), next(counter), v))
        raise NoPathError(f"no path from {START!r} to {END!r}")
