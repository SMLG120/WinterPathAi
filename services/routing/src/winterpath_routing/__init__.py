"""WinterPath AI routing core — pure Python (no web framework). Graph in → route out."""

from .costs import CostConfig, EdgeCost, edge_cost
from .engine import (
    CompareResult,
    DegenerateRequestError,
    NoRouteError,
    RouteRequest,
    RouteResult,
    RoutingEngine,
    RoutingError,
    SnapError,
)
from .filters import ExclusionReason, exclusion_reason
from .graph import Gap, GraphIntegrityError, PedestrianGraph
from .models import (
    Edge,
    Evidence,
    EvidenceState,
    GraphData,
    GraphMetadata,
    Hazard,
    HazardKind,
    Node,
    Profile,
    RiskEstimate,
    RiskLevel,
    Variant,
)
from .providers import (
    FixtureGraphProvider,
    GraphProvider,
    GraphUnavailableError,
    PostgisGraphProvider,
)
from .risk import NullRiskProvider, RiskProvider

__version__ = "0.1.0"

__all__ = [
    "CompareResult",
    "CostConfig",
    "DegenerateRequestError",
    "Edge",
    "EdgeCost",
    "Evidence",
    "EvidenceState",
    "ExclusionReason",
    "FixtureGraphProvider",
    "Gap",
    "GraphData",
    "GraphIntegrityError",
    "GraphMetadata",
    "GraphProvider",
    "GraphUnavailableError",
    "Hazard",
    "HazardKind",
    "NoRouteError",
    "Node",
    "NullRiskProvider",
    "PedestrianGraph",
    "PostgisGraphProvider",
    "Profile",
    "RiskEstimate",
    "RiskLevel",
    "RiskProvider",
    "RouteRequest",
    "RouteResult",
    "RoutingEngine",
    "RoutingError",
    "SnapError",
    "Variant",
    "edge_cost",
    "exclusion_reason",
]
