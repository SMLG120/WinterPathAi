"""Generic label-setting shortest path (Dijkstra; A* when a heuristic is given).

Operates on a ``neighbors(node) -> Iterable[(next_node, cost, label)]`` callback so virtual
origin/destination nodes (snap points) can be overlaid without mutating the shared graph.
"""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Callable, Hashable, Iterable
from dataclasses import dataclass
from typing import Any

Neighbors = Callable[[Hashable], Iterable[tuple[Hashable, float, Any]]]
Heuristic = Callable[[Hashable], float]


@dataclass(frozen=True, slots=True)
class SearchResult:
    cost: float
    nodes: list[Hashable]
    labels: list[Any]  # one per traversed arc
    settled: int


class NoPathError(Exception):
    pass


def astar(
    source: Hashable,
    target: Hashable,
    neighbors: Neighbors,
    heuristic: Heuristic | None = None,
) -> SearchResult:
    """A* search; with ``heuristic=None`` this is Dijkstra.

    Costs must be ≥ 0 (checked). The heuristic must be admissible and consistent for optimality.
    """
    h = heuristic or (lambda _n: 0.0)
    counter = itertools.count()
    dist: dict[Hashable, float] = {source: 0.0}
    parent: dict[Hashable, tuple[Hashable, Any]] = {}
    closed: set[Hashable] = set()
    heap: list[tuple[float, int, Hashable]] = [(h(source), next(counter), source)]
    while heap:
        _, _, u = heapq.heappop(heap)
        if u in closed:
            continue
        if u == target:
            nodes = [u]
            labels: list[Any] = []
            while u in parent:
                u, lab = parent[u]
                labels.append(lab)
                nodes.append(u)
            nodes.reverse()
            labels.reverse()
            return SearchResult(dist[target], nodes, labels, len(closed) + 1)
        closed.add(u)
        du = dist[u]
        for v, w, lab in neighbors(u):
            if w < 0:
                raise ValueError(f"negative edge cost {w} on arc {u}->{v}")
            if v in closed:
                continue
            nd = du + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                parent[v] = (u, lab)
                heapq.heappush(heap, (nd + h(v), next(counter), v))
    raise NoPathError(f"no path from {source!r} to {target!r}")


def dijkstra(source: Hashable, target: Hashable, neighbors: Neighbors) -> SearchResult:
    return astar(source, target, neighbors, None)
