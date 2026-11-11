"""Shared fixtures. All graphs here are SYNTHETIC (simulated=True) test data."""

from __future__ import annotations

import pytest
from routing_testlib import TOY_DIR

from winterpath_routing import CostConfig, FixtureGraphProvider, PedestrianGraph, RoutingEngine


@pytest.fixture(scope="session")
def toy_graph() -> PedestrianGraph:
    return PedestrianGraph(FixtureGraphProvider(TOY_DIR).load())


@pytest.fixture(scope="session")
def engine(toy_graph: PedestrianGraph) -> RoutingEngine:
    return RoutingEngine(toy_graph, CostConfig())
