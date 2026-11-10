"""Latency measurement on SYNTHETIC graphs (no real pilot graph available yet).

Prints p50/p95 for 100 random OD pairs. Asserts only a loose sanity bound (p95 < 2 s, the spec's
target); measured numbers are reported verbatim in docs/agent-reports/routing.md.
"""

from __future__ import annotations

import random
import statistics
import time

import pytest
from routing_testlib import AT, build_graph

from winterpath_routing import NullRiskProvider, RouteRequest, RoutingEngine
from winterpath_routing.geo import haversine_m

PILOT = (-73.5880, 45.4960, -73.5620, 45.5130)


def _grid(n_rows: int, n_cols: int):
    w, s, e, nb = PILOT
    nodes = {}
    for r in range(n_rows):
        for c in range(n_cols):
            nodes[f"g{r}_{c}"] = (w + (e - w) * c / (n_cols - 1), s + (nb - s) * r / (n_rows - 1))
    edges = []
    for r in range(n_rows):
        for c in range(n_cols):
            if c + 1 < n_cols:
                edges.append((f"g{r}_{c}", f"g{r}_{c + 1}", {"step_free": (r + c) % 3 != 0}))
            if r + 1 < n_rows:
                edges.append((f"g{r}_{c}", f"g{r + 1}_{c}", {"lit": c % 4 != 0}))
    return build_graph(nodes, edges)


def _measure(engine: RoutingEngine, n: int, seed: int) -> tuple[float, float, float]:
    rnd = random.Random(seed)
    w, s, e, nb = PILOT
    times = []
    risk = NullRiskProvider()
    while len(times) < n:
        o = (rnd.uniform(w, e), rnd.uniform(s, nb))
        d = (rnd.uniform(w, e), rnd.uniform(s, nb))
        if haversine_m(o, d) < 50:
            continue
        t0 = time.perf_counter()
        engine.compare(RouteRequest(o, d, AT), risk)
        times.append(time.perf_counter() - t0)
    times.sort()
    p50 = statistics.median(times)
    p95 = times[int(0.95 * len(times)) - 1]
    return p50, p95, max(times)


@pytest.mark.latency
@pytest.mark.parametrize("rows,cols", [(25, 25), (60, 60)])
def test_latency_100_random_pairs(rows: int, cols: int, capsys) -> None:
    g = _grid(rows, cols)
    eng = RoutingEngine(g)
    p50, p95, mx = _measure(eng, 100, seed=42)
    with capsys.disabled():
        print(
            f"\n[latency] SYNTHETIC grid {rows}x{cols} over PILOT_BBOX: nodes={len(g.nodes)} "
            f"directed_edges={len(g.edges)} n=100 compare() "
            f"p50={p50 * 1000:.1f} ms p95={p95 * 1000:.1f} ms max={mx * 1000:.1f} ms"
        )
    assert p95 < 2.0
