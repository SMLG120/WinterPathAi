"""Risk provider protocol (mirrors integration-rules §2 ``winterpath_ml.inference.RiskProvider``).

Until the ML package lands, the API uses :class:`NullRiskProvider`, which returns ``unknown`` for
every edge. Unknown is never treated as low risk.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from .models import RiskEstimate

RiskLayer = Literal["model", "heuristic", "none"]


@runtime_checkable
class RiskProvider(Protocol):
    #: which layer produced the estimates (surfaced as RouteCompareResponse.risk_layer)
    risk_layer: RiskLayer

    def edge_risk(self, edge_ids: Sequence[str], at: datetime) -> Mapping[str, RiskEstimate]:
        """Return a risk estimate per edge id. Missing ids are treated as ``unknown``."""
        ...


class NullRiskProvider:
    """No risk layer: every edge is ``unknown``."""

    risk_layer: RiskLayer = "none"

    def edge_risk(self, edge_ids: Sequence[str], at: datetime) -> Mapping[str, RiskEstimate]:
        est = RiskEstimate.unknown("No risk layer is loaded.")
        return dict.fromkeys(edge_ids, est)


class EdgeRiskSnapshot(Protocol):
    """Risk for every edge of one graph at one time, as arrays (optional provider capability).

    A provider that can answer for the whole graph at once exposes
    ``edge_risk_snapshot(at) -> EdgeRiskSnapshot | None``. The compact engine then never builds
    a list of every edge id per request (O(edges) on an island-sized graph). ``None`` means the
    capability is unavailable for this graph; the engine falls back to :meth:`edge_risk`.
    """

    #: changes whenever any estimate changes (weights derived from a snapshot are cached by it)
    token: Any
    #: ``levels[i]`` indexes ``level_values`` for edge index ``i`` (uint8 array, graph edge order)
    levels: Any
    level_values: Sequence[Any]  # RiskLevel per code
    any_simulated: bool

    def estimate(self, edge_index: int) -> RiskEstimate | None:
        """The full estimate for one edge (``None`` or unknown when not known)."""
        ...
