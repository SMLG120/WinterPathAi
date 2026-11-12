"""Routing engine: snapping, exclusions, costing, Dijkstra/A*, route assembly.

Performance (cycle 14): everything that does not depend on the request is computed once per
engine — the adjacency (in networkx's own iteration order, so tie-breaking is unchanged), the
per-profile set of statically allowed edges and each edge's default cost (risk unknown, no
hazard). Per request only hazards, closures and known risk estimates are applied on top, and
the two searches run in a specialised loop that performs exactly the same pushes, in the same
order, with the same floating-point arithmetic as :func:`winterpath_routing.search.astar`, so
routes are identical to the generic implementation (tests/test_routing_golden.py).
"""

from __future__ import annotations

import heapq
import itertools
import math
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from shapely.ops import substring

from .costs import CostConfig, EdgeCost, edge_cost
from .explain import Explanation, explain
from .filters import exclusion_reason
from .geo import dedupe_consecutive, geojson_to_metric, haversine_m, line_to_wgs84
from .graph import PedestrianGraph
from .models import (
    EvidenceState,
    Hazard,
    LonLat,
    Profile,
    RiskEstimate,
    Variant,
    _iso,
)
from .risk import NullRiskProvider, RiskProvider
from .search import NoPathError, SearchResult
from .steps import Piece, Step, build_steps, build_steps_v2

Weight = Literal["distance", "time", "generalized"]
START: Hashable = ("__start__",)
END: Hashable = ("__end__",)
#: Planar distance in EPSG:32188 vs. edge length_m — keep the A* heuristic strictly below.
HEURISTIC_SAFETY = 0.999
MIN_OD_SEPARATION_M = 2.0
#: Up to this many per-request cost overrides are applied eagerly to a copy of the static
#: weights; beyond it weights are computed lazily, only for edges the search reaches.
_MAX_EAGER_OVERRIDES = 2048


class RoutingError(Exception):
    code = "INTERNAL"


class SnapError(RoutingError):
    """Origin/destination farther than ``snap_max_m`` from any routable edge."""

    code = "OUTSIDE_COVERAGE"

    def __init__(self, which: str, nearest_m: float | None, max_m: float) -> None:
        self.which = which
        self.nearest_m = nearest_m
        self.max_m = max_m
        super().__init__(f"{which} is more than {max_m:.0f} m from the routable pedestrian network")


class NoRouteError(RoutingError):
    code = "NO_ROUTE"

    def __init__(self, profile: Profile, detail: str) -> None:
        self.profile = profile
        self.detail = detail
        super().__init__(detail)


class DegenerateRequestError(RoutingError):
    code = "VALIDATION_ERROR"


@dataclass(frozen=True, slots=True)
class RouteRequest:
    origin: LonLat
    destination: LonLat
    at: datetime
    profile: Profile = Profile.STANDARD
    avoid_unverified_reports: bool = True
    locale: str = "en"


@dataclass(slots=True)
class RouteResult:
    variant: Variant
    coordinates: list[LonLat]
    distance_m: float
    duration_s: float
    generalized_cost_s: float
    edge_ids: list[str]
    unknown_share: float
    hazards_on_route: list[str]
    hazards_avoided: list[str]
    explanation: list[Explanation]
    steps: list[Step]
    data_freshness: dict[str, datetime | None]
    risk_cost_s: float = 0.0
    labels: list[tuple[str, float, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        coords = [[round(x, 7), round(y, 7)] for x, y in self.coordinates]
        if len(coords) == 1:
            coords = coords * 2
        return {
            "variant": self.variant.value,
            "geometry": {"type": "LineString", "coordinates": coords},
            "distance_m": round(self.distance_m, 1),
            "duration_s": round(self.duration_s, 1),
            "generalized_cost_s": round(self.generalized_cost_s, 1),
            "edge_ids": self.edge_ids,
            "unknown_share": round(min(1.0, max(0.0, self.unknown_share)), 4),
            "hazards_avoided": self.hazards_avoided,
            "hazards_on_route": self.hazards_on_route,
            "explanation": [e.to_dict() for e in self.explanation],
            "steps": [s.to_dict() for s in self.steps],
            "data_freshness": {k: _iso(v) for k, v in self.data_freshness.items()},
        }


@dataclass(slots=True)
class CompareResult:
    routes: list[RouteResult]
    identical: bool
    risk_layer: str
    warnings: list[str]


@dataclass(slots=True)
class _Snap:
    candidates: list[tuple[str, float]]  # (edge_id, fraction along edge)
    distance_m: float  # from the requested point to the network
    #: snapped points on the network (EPSG:32188), one per candidate — NOT the raw request point
    points: list[tuple[float, float]]


@dataclass(slots=True)
class _Context:
    req: RouteRequest
    allowed: frozenset[str]
    closures: dict[str, list[str]]  # hazard_id -> edge ids (hard-excluded)
    disruptions: dict[str, list[str]]  # edge_id -> hazard ids (confirmed, passable)
    possible: dict[str, list[str]]  # edge_id -> hazard ids (blocking, activity unknown)
    reports: dict[str, list[str]]  # edge_id -> hazard ids (unverified)
    #: the provider's estimates for allowed edges; a missing edge means unknown
    risk: Mapping[str, RiskEstimate]
    speed: float
    any_simulated_risk: bool
    static: _ProfileStatic
    #: allowed edges whose cost may differ from the static default (hazard or known risk)
    overrides: frozenset[str]
    _costs: dict[str, EdgeCost] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _ProfileStatic:
    """Request-independent data for one profile (computed once per engine)."""

    #: edges not excluded by foot access, the step-free rule or the main-component rule
    allowed: frozenset[str]
    allowed_sorted: tuple[str, ...]
    #: cost with risk unknown and no hazard — what edge_cost() returns in that case
    costs: dict[str, EdgeCost]
    #: costs[eid].total_s
    generalized: dict[str, float]


class _LazyWeights(dict):
    """eid → weight, computed on first use (only edges the search actually reaches)."""

    __slots__ = ("_f",)

    def __init__(self, f) -> None:
        super().__init__()
        self._f = f

    def __missing__(self, eid: str) -> float:
        w = self._f(eid)
        self[eid] = w
        return w


class RoutingEngine:
    def __init__(
        self,
        graph: PedestrianGraph,
        config: CostConfig | None = None,
        *,
        steps_v2: bool = False,
    ) -> None:
        self.graph = graph
        self.config = config or CostConfig()
        #: ``ROUTING_STEPS_V2`` (off by default): merged, named steps (steps.build_steps_v2)
        self.steps_v2 = steps_v2
        g = graph.g
        # Same order as ``g.out_edges(n, keys=True)`` at search time (the graph is never mutated
        # after load), so arcs are relaxed in the same order as before.
        self._adj: dict[Hashable, tuple[tuple[Hashable, str], ...]] = {
            n: tuple((v, k) for _, v, k in g.out_edges(n, keys=True)) for n in g.nodes
        }
        self._length: dict[str, float] = {eid: e.length_m for eid, e in graph.edges.items()}
        self._static: dict[Profile, _ProfileStatic] = {p: self._build_static(p) for p in Profile}

    def _build_static(self, profile: Profile) -> _ProfileStatic:
        g, cfg = self.graph, self.config
        allowed = frozenset(
            eid
            for eid, e in g.edges.items()
            if exclusion_reason(e, profile, main_component_edge_ids=g.main_component_edge_ids)
            is None
        )
        unknown = RiskEstimate.unknown()
        costs = {
            eid: edge_cost(
                g.edges[eid],
                profile,
                unknown,
                n_confirmed_disruptions=0,
                n_unverified_reports=0,
                avoid_unverified_reports=True,
                config=cfg,
                n_possible_closures=0,
            )
            for eid in allowed
        }
        return _ProfileStatic(
            allowed=allowed,
            allowed_sorted=tuple(sorted(allowed)),
            costs=costs,
            generalized={eid: c.total_s for eid, c in costs.items()},
        )

    # ------------------------------------------------------------------ context
    def _match_hazards(
        self, req: RouteRequest, hazards: Iterable[Hazard]
    ) -> tuple[
        dict[str, list[str]], dict[str, list[str]], dict[str, list[str]], dict[str, list[str]]
    ]:
        """(closures, disruptions, possible closures, reports) for hazards active at req.at."""
        g, cfg = self.graph, self.config
        closures: dict[str, list[str]] = {}
        disruptions: dict[str, list[str]] = {}
        possible: dict[str, list[str]] = {}
        reports: dict[str, list[str]] = {}
        for hz in hazards:
            if not hz.active_at(req.at):
                continue
            geom = geojson_to_metric(hz.geometry)
            if hz.is_hard_closure:
                eids = g.edges_near_metric(geom, cfg.closure_match_tolerance_m)
                if eids:
                    closures[hz.hazard_id] = eids
            elif hz.is_possible_closure:
                for eid in g.edges_near_metric(geom, cfg.closure_match_tolerance_m):
                    possible.setdefault(eid, []).append(hz.hazard_id)
            elif hz.evidence.state is EvidenceState.CONFIRMED:
                for eid in g.edges_near_metric(geom, cfg.closure_match_tolerance_m):
                    disruptions.setdefault(eid, []).append(hz.hazard_id)
            elif hz.evidence.state is EvidenceState.UNVERIFIED_REPORT:
                for eid in g.edges_near_metric(geom, cfg.report_match_tolerance_m):
                    reports.setdefault(eid, []).append(hz.hazard_id)
            # other evidence states (unknown/model/simulated hazards) do not affect routing
        return closures, disruptions, possible, reports

    def _context(
        self, req: RouteRequest, risk_provider: RiskProvider, hazards: Iterable[Hazard]
    ) -> _Context:
        closures, disruptions, possible, reports = self._match_hazards(req, hazards)
        cfg = self.config
        closed_ids = {eid for eids in closures.values() for eid in eids}
        # Static exclusions (foot access, step-free rule, main component) are precomputed per
        # profile; confirmed closures active at this time are removed on top.
        st = self._static[req.profile]
        if closed_ids:
            allowed = st.allowed - closed_ids
            ids = [eid for eid in st.allowed_sorted if eid not in closed_ids]
        else:
            allowed = st.allowed
            ids = list(st.allowed_sorted)
        if isinstance(risk_provider, NullRiskProvider) or not ids:
            # NullRiskProvider answers "unknown" (never simulated) for every edge: same as no
            # estimate at all, without building and scanning a dict over every edge.
            raw: Mapping[str, RiskEstimate] = {}
        else:
            raw = risk_provider.edge_risk(ids, req.at)
        # Unknown and missing estimates cost the same and are reported the same (unknown, never
        # zero risk), so only *known* estimates for allowed edges are kept.
        any_sim = any(
            r and r.evidence.state is EvidenceState.SIMULATED and eid in allowed
            for eid, r in raw.items()
        )
        risk = {eid: r for eid, r in raw.items() if r and not r.is_unknown and eid in allowed}
        overrides = (disruptions.keys() | possible.keys() | reports.keys() | risk.keys()) & allowed
        return _Context(
            req,
            allowed,
            closures,
            disruptions,
            possible,
            reports,
            risk,
            cfg.speed_for(req.profile),
            any_sim,
            st,
            frozenset(overrides),
        )

    def _cost(self, ctx: _Context, eid: str) -> EdgeCost:
        c = ctx._costs.get(eid)
        if c is None:
            r = ctx.risk.get(eid)
            if (
                (r is None or r.is_unknown)
                and eid not in ctx.disruptions
                and eid not in ctx.possible
                and eid not in ctx.reports
            ):
                # identical to edge_cost(...) with risk unknown and no hazard on the edge
                c = ctx.static.costs.get(eid)
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
            return self.graph.edges[eid].length_m
        c = self._cost(ctx, eid)
        return c.base_s if weight == "time" else c.total_s

    def _weights(self, ctx: _Context, weight: Weight) -> Mapping[str, float]:
        """eid → arc weight; equal to ``_weight(ctx, eid, weight)`` for every allowed edge."""
        if weight == "distance":
            return self._length
        if weight == "time":
            return _LazyWeights(lambda eid: self._cost(ctx, eid).base_s)
        if not ctx.overrides:
            return ctx.static.generalized
        if len(ctx.overrides) <= _MAX_EAGER_OVERRIDES:
            w = dict(ctx.static.generalized)  # C-level copy, then the few hazard/risk edges
            for eid in ctx.overrides:
                w[eid] = self._cost(ctx, eid).total_s
            return w
        # e.g. a risk layer with an estimate on most edges: cost only what the search reaches
        return _LazyWeights(lambda eid: self._cost(ctx, eid).total_s)

    # ------------------------------------------------------------------ snapping
    def _snap(self, which: str, lonlat: LonLat, allowed: frozenset[str]) -> _Snap:
        max_m = self.config.snap_max_m
        eids, d, p = self.graph.nearest_edges(lonlat[0], lonlat[1], max_m, allowed)
        if not eids:
            # report nearest distance among any allowed edge (bounded search) for diagnostics
            _, dn, _ = self.graph.nearest_edges(lonlat[0], lonlat[1], max_m * 4, allowed)
            raise SnapError(which, None if math.isinf(dn) else round(dn, 1), max_m)
        cands = []
        pts = []
        for eid in eids:
            line = self.graph.metric_lines[eid]
            frac = line.project(p) / line.length if line.length > 0 else 0.0
            frac = min(1.0, max(0.0, frac))
            cands.append((eid, frac))
            sp = line.interpolate(frac * line.length)
            pts.append((sp.x, sp.y))
        return _Snap(cands, d, pts)

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
        edges = g.edges
        allowed = ctx.allowed
        w = self._weight

        start_arcs = [
            (edges[eid].to_node_id, (1.0 - f) * w(ctx, eid, weight), (eid, f, 1.0))
            for eid, f in o.candidates
        ]
        end_arcs: dict[Hashable, list[tuple[Hashable, float, tuple]]] = {}
        for eid, f in t.candidates:
            end_arcs.setdefault(edges[eid].from_node_id, []).append(
                (END, f * w(ctx, eid, weight), (eid, 0.0, f))
            )
        t_frac = dict(t.candidates)
        for eid, fo in o.candidates:
            ft = t_frac.get(eid)
            if ft is not None and ft >= fo:
                start_arcs.append((END, (ft - fo) * w(ctx, eid, weight), (eid, fo, ft)))

        if algorithm == "dijkstra":
            return self._run(start_arcs, end_arcs, allowed, self._weights(ctx, weight), None, 0.0)

        # Admissible heuristic: straight-line metric distance to the nearest *snapped* destination
        # point (on the network), converted to the weight's unit. Every arc costs at least its
        # metric length / speed, so this never overestimates.
        per_m = (1.0 if weight == "distance" else 1.0 / ctx.speed) * HEURISTIC_SAFETY
        return self._run(start_arcs, end_arcs, allowed, self._weights(ctx, weight), t.points, per_m)

    def _run(
        self,
        start_arcs: list[tuple[Hashable, float, tuple]],
        end_arcs: Mapping[Hashable, list[tuple[Hashable, float, tuple]]],
        allowed: frozenset[str],
        weights: Mapping[str, float],
        targets: Sequence[tuple[float, float]] | None,
        per_m: float,
    ) -> SearchResult:
        """:func:`search.astar` from START to END, specialised for this graph.

        Same relaxation order (start arcs; then, per node, its out-arcs in networkx order
        followed by its end arcs), same ``(priority, counter)`` heap keys and the same
        arithmetic, so it settles the same nodes and returns the same path. ``targets=None``
        is Dijkstra (heuristic 0).
        """
        adj = self._adj
        xy = self.graph._node_xy
        hypot = math.hypot
        heappush, heappop = heapq.heappush, heapq.heappop
        inf = math.inf
        single = targets[0] if targets is not None and len(targets) == 1 else None

        def h(n: Hashable) -> float:
            if targets is None or n is END:
                return 0.0
            x, y = xy[n]  # type: ignore[index]
            if single is not None:
                return hypot(x - single[0], y - single[1]) * per_m
            return min(hypot(x - tx, y - ty) for tx, ty in targets) * per_m

        counter = itertools.count()
        dist: dict[Hashable, float] = {START: 0.0}
        parent: dict[Hashable, tuple[Hashable, Any]] = {}
        closed: set[Hashable] = set()
        heap: list[tuple[float, int, Hashable]] = [(0.0, next(counter), START)]
        no_end: tuple = ()
        while heap:
            _, _, u = heappop(heap)
            if u in closed:
                continue
            if u is END:
                nodes = [u]
                labels: list[Any] = []
                while u in parent:
                    u, lab = parent[u]
                    labels.append(lab)
                    nodes.append(u)
                nodes.reverse()
                labels.reverse()
                return SearchResult(dist[END], nodes, labels, len(closed) + 1)
            closed.add(u)
            du = dist[u]
            if u is START:
                arcs: Iterable[tuple[Hashable, float, tuple]] = start_arcs
            else:
                for v, eid in adj[u]:
                    if eid not in allowed:
                        continue
                    w = weights[eid]
                    if w < 0:
                        raise ValueError(f"negative edge cost {w} on arc {u}->{v}")
                    if v in closed:
                        continue
                    nd = du + w
                    if nd < dist.get(v, inf):
                        dist[v] = nd
                        parent[v] = (u, (eid, 0.0, 1.0))
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

    def shortest_path(
        self,
        req: RouteRequest,
        risk_provider: RiskProvider,
        hazards: Iterable[Hazard] = (),
        *,
        weight: Weight = "distance",
        algorithm: Literal["dijkstra", "astar"] = "dijkstra",
    ) -> tuple[SearchResult, _Context]:
        """Low-level search (exposed for tests and benchmarks)."""
        self._check_separation(req)
        ctx = self._context(req, risk_provider, hazards)
        o = self._snap("origin", req.origin, ctx.allowed)
        t = self._snap("destination", req.destination, ctx.allowed)
        try:
            return self._search(ctx, o, t, weight, algorithm), ctx
        except NoPathError as exc:
            raise NoRouteError(req.profile, _no_route_detail(req.profile)) from exc

    @staticmethod
    def _check_separation(req: RouteRequest) -> None:
        if haversine_m(req.origin, req.destination) < MIN_OD_SEPARATION_M:
            raise DegenerateRequestError("origin and destination are the same point")

    # ------------------------------------------------------------------ public API
    def compare(
        self,
        req: RouteRequest,
        risk_provider: RiskProvider,
        hazards: Sequence[Hazard] = (),
        extra_freshness: Mapping[str, datetime | None] | None = None,
    ) -> CompareResult:
        self._check_separation(req)
        ctx = self._context(req, risk_provider, hazards)
        o = self._snap("origin", req.origin, ctx.allowed)
        t = self._snap("destination", req.destination, ctx.allowed)
        try:
            short = self._search(ctx, o, t, "distance", "dijkstra")
            winter = self._search(ctx, o, t, "generalized", "astar")
        except NoPathError as exc:
            raise NoRouteError(req.profile, _no_route_detail(req.profile)) from exc

        freshness: dict[str, datetime | None] = dict(self.graph.metadata.source_freshness)
        freshness.update(extra_freshness or {})

        r_short = self._assemble(ctx, Variant.SHORTEST, short, freshness)
        r_winter = self._assemble(ctx, Variant.WINTER_AWARE, winter, freshness)
        identical = r_short.labels == r_winter.labels

        winter_set = set(r_winter.hazards_on_route)
        r_winter.hazards_avoided = [h for h in r_short.hazards_on_route if h not in winter_set]

        risk_layer = getattr(risk_provider, "risk_layer", "none")
        r_short.explanation = self._explain(ctx, r_short, None, identical, risk_layer)
        r_winter.explanation = self._explain(ctx, r_winter, r_short, identical, risk_layer)

        return CompareResult(
            routes=[r_short, r_winter],
            identical=identical,
            risk_layer=risk_layer,
            warnings=self._warnings(ctx, risk_layer, o, t, (r_short, r_winter)),
        )

    # ------------------------------------------------------------------ assembly
    def _assemble(
        self,
        ctx: _Context,
        variant: Variant,
        res: SearchResult,
        freshness: dict[str, datetime | None],
    ) -> RouteResult:
        g = self.graph
        coords: list[LonLat] = []
        pieces: list[Piece] = []
        edge_ids: list[str] = []
        hz_on: list[str] = []
        dist = dur = gen = risk_s = unknown_len = 0.0
        for eid, a, b in res.labels:
            e = g.edges[eid]
            frac = max(0.0, b - a)
            line = g.metric_lines[eid]
            if a <= 0.0 and b >= 1.0:
                part_coords = list(e.coords)
                part_line = line
            else:
                part_line = substring(line, a * line.length, b * line.length)
                if part_line.geom_type != "LineString" or len(part_line.coords) < 2:
                    pt = next(iter(part_line.coords)) if not part_line.is_empty else line.coords[0]
                    part_coords = [g.metric_to_lonlat(*pt)]
                else:
                    part_coords = line_to_wgs84(part_line)
            coords.extend(part_coords)
            plen = e.length_m * frac
            dist += plen
            c = self._cost(ctx, eid)
            dur += c.base_s * frac
            gen += c.total_s * frac
            risk_s += c.risk_s * frac
            if (ctx.risk.get(eid) or RiskEstimate.unknown()).is_unknown:
                unknown_len += plen
            if frac > 0:
                if not edge_ids or edge_ids[-1] != eid:
                    edge_ids.append(eid)
                if part_line.geom_type == "LineString" and len(part_line.coords) >= 2:
                    pieces.append(Piece(e, part_line, plen))
                for hid in (
                    *ctx.possible.get(eid, ()),
                    *ctx.disruptions.get(eid, ()),
                    *ctx.reports.get(eid, ()),
                ):
                    if hid not in hz_on:
                        hz_on.append(hid)
        return RouteResult(
            variant=variant,
            coordinates=dedupe_consecutive(coords),
            distance_m=dist,
            duration_s=dur,
            generalized_cost_s=gen,
            edge_ids=edge_ids,
            unknown_share=(unknown_len / dist) if dist > 0 else 1.0,
            hazards_on_route=hz_on,
            hazards_avoided=[],
            explanation=[],
            steps=(build_steps_v2 if self.steps_v2 else build_steps)(pieces, ctx.req.locale),
            data_freshness=freshness,
            risk_cost_s=risk_s,
            labels=[lab for lab in res.labels if lab[2] - lab[1] > 0],
        )

    def _explain(
        self,
        ctx: _Context,
        r: RouteResult,
        shortest: RouteResult | None,
        identical: bool,
        risk_layer: str,
    ) -> list[Explanation]:
        loc = ctx.req.locale
        out: list[Explanation] = []
        if self.graph.metadata.simulated or ctx.any_simulated_risk:
            out.append(explain("SIMULATED_DATA", loc))
        if r.variant is Variant.SHORTEST:
            out.append(explain("SHORTEST_DISTANCE", loc))
        else:
            out.append(explain("WINTER_AWARE_COST", loc))
            if identical:
                out.append(explain("IDENTICAL_TO_SHORTEST", loc))
        if ctx.closures:
            out.append(explain("EXCLUDES_CONFIRMED_CLOSURE", loc, n=len(ctx.closures)))

        on_poss = {h for eid in r.edge_ids for h in ctx.possible.get(eid, ())}
        on_disr = {h for eid in r.edge_ids for h in ctx.disruptions.get(eid, ())}
        on_rep = {h for eid in r.edge_ids for h in ctx.reports.get(eid, ())}
        if shortest is not None:
            all_poss = {h for hs in ctx.possible.values() for h in hs}
            all_disr = {h for hs in ctx.disruptions.values() for h in hs}
            avoided = set(r.hazards_avoided)
            n_ap = len(avoided & all_poss)
            n_ad = len(avoided & all_disr)
            n_ar = len(avoided - all_disr - all_poss)
            if n_ap:
                out.append(explain("AVOIDS_POSSIBLE_CLOSURE", loc, n=n_ap))
            if n_ad:
                out.append(explain("AVOIDS_CONFIRMED_DISRUPTION", loc, n=n_ad))
            if n_ar:
                out.append(explain("AVOIDS_UNVERIFIED_REPORT", loc, n=n_ar))
            if risk_layer != "none" and r.risk_cost_s + 1e-6 < shortest.risk_cost_s:
                out.append(explain("LOWER_MODELED_RISK", loc))
        if on_poss:
            out.append(explain("PASSES_POSSIBLE_CLOSURE", loc, n=len(on_poss)))
        if on_disr:
            out.append(explain("PASSES_CONFIRMED_DISRUPTION", loc, n=len(on_disr)))
        if on_rep:
            out.append(explain("PASSES_UNVERIFIED_REPORT", loc, n=len(on_rep)))

        if risk_layer == "none":
            out.append(explain("RISK_LAYER_UNAVAILABLE", loc))
        elif r.unknown_share > 0:
            out.append(explain("RISK_UNKNOWN_SHARE", loc, pct=round(100 * r.unknown_share)))

        if ctx.req.profile is Profile.STEP_FREE:
            out.append(explain("STEP_FREE_TAGGED_ONLY", loc))
        elif ctx.req.profile is Profile.REDUCED_MOBILITY:
            out.append(explain("REDUCED_MOBILITY_SPEED", loc, speed=ctx.speed))
        if any(self.graph.edges[eid].edge_kind == "steps" for eid in r.edge_ids):
            out.append(explain("INCLUDES_STEPS", loc))
        return out

    def _warnings(
        self,
        ctx: _Context,
        risk_layer: str,
        o: _Snap,
        t: _Snap,
        routes: Sequence[RouteResult] = (),
    ) -> list[str]:
        fr = ctx.req.locale == "fr"
        w: list[str] = []
        if self.graph.metadata.simulated or ctx.any_simulated_risk:
            w.append(
                "SIMULÉ : données de démonstration synthétiques."
                if fr
                else "SIMULATED: synthetic demo data."
            )
        if risk_layer == "none":
            w.append(
                "Aucune couche de risque : risque inconnu sur tout le trajet."
                if fr
                else "No risk layer: risk is unknown along the whole route."
            )
        elif risk_layer == "heuristic":
            w.append(
                "Niveaux de risque heuristiques (fréquence historique des requêtes 311 "
                "hivernales × météo observée) : ce ne sont ni des probabilités ni l'état des "
                "trottoirs."
                if fr
                else "Risk levels are a heuristic (historical winter 311 report frequency × "
                "observed weather): not probabilities and not sidewalk conditions."
            )
        if any(ctx.possible.get(eid) for r in routes for eid in r.edge_ids):
            w.append(
                "Une fermeture autorisée du trottoir se trouve sur un trajet, mais son horaire à "
                "ce moment est inconnu : elle peut être en vigueur."
                if fr
                else "A permitted sidewalk closure lies on a route, but its schedule at this time "
                "is unknown: it may be in effect."
            )
        for label_en, label_fr, s in (("Origin", "Le départ", o), ("Destination", "L'arrivée", t)):
            if s.distance_m > 25:
                d = round(s.distance_m)
                w.append(
                    f"{label_fr} est à {d} m du réseau piéton cartographié."
                    if fr
                    else f"{label_en} is {d} m from the mapped pedestrian network."
                )
        return w


def _no_route_detail(profile: Profile) -> str:
    if profile is Profile.STEP_FREE:
        return (
            "No route made only of segments verified step-free connects these points. "
            "The step-free constraint is not relaxed."
        )
    return "No legal pedestrian path connects these points with current closures excluded."
