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
from collections import OrderedDict
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
    #: median generalized cost per metre of an allowed edge (sizes the first search radius)
    per_m: float = 1.0


class _SnapshotRisk:
    """``ctx.risk`` backed by an :class:`EdgeRiskSnapshot`: only ``.get(edge_id)`` is used, and
    only for edges on a route or under a hazard, so nothing is materialised per request."""

    __slots__ = ("_g", "_known", "_mask", "_snap")

    def __init__(self, g: CompactGraph, snap: Any, known: np.ndarray, mask: bytearray) -> None:
        self._g, self._snap, self._known, self._mask = g, snap, known, mask

    def get(self, eid: str, default: RiskEstimate | None = None) -> RiskEstimate | None:
        i = self._g.edge_index(eid)
        if i < 0 or not self._mask[i] or not self._known[i]:
            return default
        est = self._snap.estimate(i)
        return default if est is None or est.is_unknown else est


class CompactRoutingEngine(RoutingEngine):
    def __init__(
        self,
        graph: CompactGraph,
        config: CostConfig | None = None,
        *,
        steps_v2: bool = False,
        fast_search: bool = False,
    ) -> None:
        self.graph = graph  # type: ignore[assignment]
        self.config = config or CostConfig()
        self.steps_v2 = steps_v2
        #: compiled Dijkstra (SciPy) instead of the Python search loop: same optimal cost, but
        #: ties between equal-cost paths may resolve differently (see ``_search_fast``)
        self.fast_search = fast_search
        if fast_search:
            self._dijkstra()  # fail at start-up, not on the first request, if SciPy is missing
        self._length = array("d", graph.length.tobytes())
        self._adj_off_np = np.frombuffer(graph.adj_off, dtype=np.int64)
        self._adj_to_np = np.frombuffer(graph.adj_to, dtype=np.int32)
        self._adj_edge_np = np.frombuffer(graph.adj_edge, dtype=np.int32)
        self._static = {p: self._build_static(p) for p in Profile}  # type: ignore[misc]
        #: (profile, snapshot token) -> per-edge generalized weights with that snapshot's risk
        self._risk_weights: OrderedDict[tuple, np.ndarray] = OrderedDict()

    # ------------------------------------------------------------------ static per profile
    def _parts(self, profile: Profile) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """(allowed, base_s, unknown_s, preference_s) per edge, as ``edge_cost`` computes them."""
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
        return allowed, base, unknown, pref

    def _build_static(self, profile: Profile) -> _CompactStatic:  # type: ignore[override]
        g, cfg = self.graph, self.config
        allowed, base, unknown, pref = self._parts(profile)
        disruption = cfg.confirmed_disruption_penalty_s * 0
        total = base + disruption + 0.0 + unknown + pref
        total = np.where(allowed, total, 0.0)
        ok = total[allowed] / g.length[allowed] if allowed.any() else np.ones(1)
        return _CompactStatic(
            allowed=EdgeMask(g, bytearray(allowed.astype(np.uint8).tobytes())),
            generalized=array("d", np.ascontiguousarray(total, dtype=np.float64).tobytes()),
            per_m=float(np.median(ok)),
        )

    def _risk_generalized(self, profile: Profile, snap: Any) -> np.ndarray:
        """Per-edge generalized cost with the snapshot's known risk levels and no hazard.

        Same IEEE operations, in the same order, as ``edge_cost`` (``total_s`` is
        ``base + disruption + risk + unknown + pref``): a known level replaces the unknown
        penalty by ``base * factor``. Cached per (profile, snapshot token).
        """
        key = (profile, snap.token)
        w = self._risk_weights.get(key)
        if w is None:
            cfg = self.config
            allowed, base, unknown, pref = self._parts(profile)
            disruption = cfg.confirmed_disruption_penalty_s * 0
            factor = np.array(
                [cfg.risk_penalty_factor.get(lv, 0.0) for lv in snap.level_values], dtype=float
            )
            known = self._known(snap)
            levels = np.asarray(snap.levels)
            w_known = base + disruption + base * factor[levels] + 0.0 + pref
            w_unknown = base + disruption + 0.0 + unknown + pref
            w = np.where(allowed, np.where(known, w_known, w_unknown), 0.0)
            self._risk_weights[key] = w
            while len(self._risk_weights) > 2 * len(Profile):
                self._risk_weights.popitem(last=False)
        return w

    @staticmethod
    def _known(snap: Any) -> np.ndarray:
        unknown_codes = [i for i, lv in enumerate(snap.level_values) if str(lv) == "unknown"]
        return ~np.isin(np.asarray(snap.levels), unknown_codes)

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
        snap_fn = getattr(risk_provider, "edge_risk_snapshot", None)
        snap = (
            snap_fn(req.at)
            if callable(snap_fn) and not isinstance(risk_provider, NullRiskProvider)
            else None
        )
        if snap is not None and len(snap.levels) != len(g.length):
            snap = None  # built for another graph: fall back to the id-keyed call
        if snap is not None:
            touched = disruptions.keys() | possible.keys() | reports.keys()
            return _Context(
                req,
                allowed,  # type: ignore[arg-type]
                closures,
                disruptions,
                possible,
                reports,
                _SnapshotRisk(g, snap, self._known(snap), allowed.mask),  # type: ignore[arg-type]
                self.config.speed_for(req.profile),
                bool(snap.any_simulated),
                st,  # type: ignore[arg-type]
                frozenset(eid for eid in touched if eid in allowed),
                risk_snapshot=snap,
            )
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
        if ctx.risk_snapshot is not None:
            return array("d", self._weights_np(ctx, weight).tobytes())
        if not ctx.overrides:
            return st.generalized
        if len(ctx.overrides) <= _MAX_EAGER_OVERRIDES:
            w = array("d", st.generalized)
            for eid in ctx.overrides:
                w[self.graph.edge_index(eid)] = self._cost(ctx, eid).total_s
            return w
        return _LazyWeights(lambda i: self._cost(ctx, name(i)).total_s)

    def _weights_np(self, ctx: _Context, weight: Weight) -> np.ndarray:
        """edge index → arc weight as a float64 array (values equal to :meth:`_weight`)."""
        g = self.graph
        if weight == "distance":
            return g.length
        if weight == "time":
            return g.length / ctx.speed
        if ctx.risk_snapshot is not None:
            w = self._risk_generalized(ctx.req.profile, ctx.risk_snapshot)
        else:
            w = np.frombuffer(ctx.static.generalized, dtype=np.float64)  # type: ignore[attr-defined]
        if ctx.overrides:
            w = w.copy()
            for eid in ctx.overrides:
                w[g.edge_index(eid)] = self._cost(ctx, eid).total_s
        return w

    # ------------------------------------------------------------------ search
    @staticmethod
    def _dijkstra() -> Any:
        try:
            from scipy.sparse import csr_matrix
            from scipy.sparse.csgraph import dijkstra
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RuntimeError("fast_search needs SciPy (scipy.sparse.csgraph)") from exc
        return csr_matrix, dijkstra

    def _search_fast(self, ctx: _Context, o: _Snap, t: _Snap, weight: Weight) -> SearchResult:
        """Exact shortest path with SciPy's compiled Dijkstra.

        Same graph, same arc weights, same virtual START/END arcs as :meth:`_search`; the
        returned cost is the same optimum. Among several paths of exactly equal cost the choice
        may differ from the Python loop (which is why this is opt-in). The search is bounded by a
        radius that grows until the best END cost found is within it — then no path leaving the
        radius can be cheaper, so the result is exact, not a heuristic.
        """
        csr_matrix, dijkstra = self._dijkstra()
        g = self.graph
        idx = g.edge_index
        w1 = self._weight
        n = len(self._adj_off_np) - 1
        best_start: dict[int, tuple[float, tuple]] = {}
        for eid, f in o.candidates:
            v, w, lab = int(g.to_idx[idx(eid)]), (1.0 - f) * w1(ctx, eid, weight), (eid, f, 1.0)
            if v not in best_start or w < best_start[v][0]:
                best_start[v] = (w, lab)
        ends = [
            (int(g.from_idx[idx(eid)]), f * w1(ctx, eid, weight), (eid, 0.0, f))
            for eid, f in t.candidates
        ]
        best: tuple[float, int, tuple | None] = (math.inf, -1, None)  # cost, end node, label
        t_frac = dict(t.candidates)
        for eid, fo in o.candidates:  # origin and destination on the same edge, in order
            ft = t_frac.get(eid)
            if ft is not None and ft >= fo:
                w = (ft - fo) * w1(ctx, eid, weight)
                if w < best[0]:
                    best = (w, -1, (eid, fo, ft))

        weights = self._weights_np(ctx, weight)
        mask = np.frombuffer(ctx.allowed.mask, dtype=np.uint8)  # type: ignore[attr-defined]
        ae = self._adj_edge_np
        arc_w = np.where(mask[ae] != 0, weights[ae], np.inf)
        if len(arc_w) and float(arc_w.min()) < 0:
            raise ValueError("negative edge cost")
        s_to = np.fromiter(best_start.keys(), dtype=np.int32, count=len(best_start))
        s_w = np.array([best_start[int(v)][0] for v in s_to], dtype=np.float64)
        matrix = csr_matrix(
            (
                np.concatenate([arc_w, s_w]),
                np.concatenate([self._adj_to_np, s_to]),
                np.concatenate([self._adj_off_np, [len(arc_w) + len(s_w)]]),
            ),
            shape=(n + 1, n + 1),
        )
        straight = min(math.hypot(ox - tx, oy - ty) for ox, oy in o.points for tx, ty in t.points)
        unit = (
            1.0
            if weight == "distance"
            else 1.0 / ctx.speed
            if weight == "time"
            else ctx.static.per_m  # type: ignore[attr-defined]
        )
        first = (1.5 * straight + 500.0) * unit
        dist = pred = None
        settled = 0
        end_w = 0.0
        for limit in (first, 4.0 * first, math.inf):
            dist, pred = dijkstra(
                matrix, directed=True, indices=n, return_predecessors=True, limit=limit
            )
            settled = int(np.isfinite(dist).sum())
            for u, w, lab in ends:
                c = float(dist[u]) + w
                if c < best[0]:
                    best, end_w = (c, u, lab), w
            if best[0] <= limit:
                break
        if best[2] is None or math.isinf(best[0]):
            raise NoPathError(f"no path from {START!r} to {END!r}")
        name, node = g.edge_id, g._nids.name
        if best[1] < 0:  # same-edge segment
            return SearchResult(best[0], [START, END], [best[2]], settled)
        chain = [best[1]]
        while True:
            p = int(pred[chain[-1]])
            if p == n:
                break
            if p < 0:
                raise NoPathError(f"no path from {START!r} to {END!r}")
            chain.append(p)
        chain.reverse()
        off, to, edge = g.adj_off, g.adj_to, g.adj_edge
        bmask = ctx.allowed.mask  # type: ignore[attr-defined]
        start_w, start_lab = best_start[chain[0]]
        cost = 0.0 + start_w
        labels: list[tuple] = [start_lab]
        for u, v in itertools.pairwise(chain):
            pick, pick_w = -1, math.inf
            for k in range(off[u], off[u + 1]):
                e = edge[k]
                if to[k] == v and bmask[e]:
                    w = float(weights[e])
                    if w < pick_w:
                        pick, pick_w = e, w
            if pick < 0:
                raise NoPathError(f"no path from {START!r} to {END!r}")
            cost += pick_w
            labels.append((name(pick), 0.0, 1.0))
        labels.append(best[2])
        cost += end_w
        return SearchResult(cost, [START, *(node(i) for i in chain), END], labels, settled)

    def _search(
        self,
        ctx: _Context,
        o: _Snap,
        t: _Snap,
        weight: Weight,
        algorithm: Literal["dijkstra", "astar"],
    ) -> SearchResult:
        if self.fast_search:
            return self._search_fast(ctx, o, t, weight)
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
