"""Test helpers (importable by unique name). All data here is SYNTHETIC."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from winterpath_routing import (
    Edge,
    Evidence,
    EvidenceState,
    GraphData,
    GraphMetadata,
    Node,
    PedestrianGraph,
    RiskEstimate,
    RiskLevel,
)
from winterpath_routing.geo import metric_length_m

TOY_DIR = Path(__file__).parent / "fixtures" / "synthetic" / "toy_grid"
AT = datetime(2026, 12, 15, 8, 0, tzinfo=UTC)
LON0, LAT0, DLON, DLAT = -73.5780, 45.5030, 0.0010, 0.0007


def grid_node(r: int, c: int) -> tuple[float, float]:
    return (LON0 + c * DLON, LAT0 + r * DLAT)


def gid(r: int, c: int) -> str:
    return f"syn:r{r}c{c}"


def eid(a: str, b: str) -> str:
    return f"{a}>{b}:0"


class StaticRiskProvider:
    """Test provider returning fixed levels; unspecified edges are omitted (→ unknown)."""

    def __init__(
        self,
        levels: Mapping[str, RiskLevel],
        state: EvidenceState = EvidenceState.MODEL_ESTIMATE,
        layer: str = "heuristic",
    ) -> None:
        self.levels = dict(levels)
        self.state = state
        self.risk_layer = layer

    def edge_risk(self, edge_ids: Sequence[str], at: datetime) -> Mapping[str, RiskEstimate]:
        return {
            eid: RiskEstimate(self.levels[eid], Evidence(self.state, ("test",)))
            for eid in edge_ids
            if eid in self.levels
        }


def build_graph(
    nodes: Mapping[str, tuple[float, float]],
    edges: Sequence[tuple[str, str, dict]],
) -> PedestrianGraph:
    ns = {k: Node(k, lon, lat, kind="synthetic") for k, (lon, lat) in nodes.items()}
    es: list[Edge] = []
    for u, v, props in edges:
        props = dict(props)
        oneway = props.pop("oneway", False)
        pairs = [(u, v)] if oneway else [(u, v), (v, u)]
        for a, b in pairs:
            coords = (nodes[a], nodes[b])
            es.append(
                Edge(
                    edge_id=f"{a}>{b}:0",
                    from_node_id=a,
                    to_node_id=b,
                    coords=coords,
                    length_m=metric_length_m(coords),
                    edge_kind=props.get("edge_kind", "footway"),
                    foot_access=props.get("foot_access", "yes"),
                    step_free=props.get("step_free"),
                    lit=props.get("lit"),
                    name=props.get("name"),
                    source_ids=("synthetic",),
                )
            )
    return PedestrianGraph(GraphData(ns, es, GraphMetadata(simulated=True)))
