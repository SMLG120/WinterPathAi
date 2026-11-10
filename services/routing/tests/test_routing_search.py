"""Search algorithm correctness against NetworkX on random SYNTHETIC graphs."""

from __future__ import annotations

import random

import networkx as nx
import pytest

from winterpath_routing.search import NoPathError, astar, dijkstra


def _neighbors(g: nx.DiGraph):
    def nb(n):
        for _, v, d in g.out_edges(n, data=True):
            yield v, d["weight"], (n, v)

    return nb


@pytest.mark.parametrize("seed", range(20))
def test_dijkstra_matches_networkx(seed: int) -> None:
    rnd = random.Random(seed)
    g = nx.gnp_random_graph(40, 0.12, seed=seed, directed=True)
    for u, v in g.edges:
        g[u][v]["weight"] = rnd.uniform(0.0, 10.0)
    for _ in range(10):
        s, t = rnd.randrange(40), rnd.randrange(40)
        try:
            expected = nx.dijkstra_path_length(g, s, t)
        except nx.NetworkXNoPath:
            with pytest.raises(NoPathError):
                dijkstra(s, t, _neighbors(g))
            continue
        res = dijkstra(s, t, _neighbors(g))
        assert res.cost == pytest.approx(expected)
        assert res.nodes[0] == s and res.nodes[-1] == t
        assert sum(g[a][b]["weight"] for a, b in res.labels) == pytest.approx(expected)


def test_astar_with_zero_heuristic_equals_dijkstra() -> None:
    g = nx.DiGraph()
    g.add_weighted_edges_from([(0, 1, 1.0), (1, 2, 1.0), (0, 2, 5.0), (2, 3, 1.0)])
    a = astar(0, 3, _neighbors(g), lambda n: 0.0)
    d = dijkstra(0, 3, _neighbors(g))
    assert a.cost == d.cost == 3.0
    assert a.nodes == d.nodes == [0, 1, 2, 3]


def test_negative_weight_rejected() -> None:
    g = nx.DiGraph()
    g.add_weighted_edges_from([(0, 1, -1.0)])
    with pytest.raises(ValueError, match="negative"):
        dijkstra(0, 1, _neighbors(g))
