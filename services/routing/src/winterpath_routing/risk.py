"""Risk provider protocol (mirrors integration-rules §2 ``winterpath_ml.inference.RiskProvider``).

Until the ML package lands, the API uses :class:`NullRiskProvider`, which returns ``unknown`` for
every edge. Unknown is never treated as low risk.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

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
