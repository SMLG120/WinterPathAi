"""Core value types for the routing library.

These mirror the contract v1 schemas (docs/contracts/openapi.yaml, data-model.md) but carry no
web-framework dependency. Coordinates are always ``(lon, lat)`` in EPSG:4326.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

LonLat = tuple[float, float]


class EvidenceState(StrEnum):
    CONFIRMED = "confirmed"
    UNVERIFIED_REPORT = "unverified_report"
    MODEL_ESTIMATE = "model_estimate"
    UNKNOWN = "unknown"
    SIMULATED = "simulated"


class RiskLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    ELEVATED = "elevated"
    HIGH = "high"
    UNKNOWN = "unknown"


class Profile(StrEnum):
    STANDARD = "standard"
    STEP_FREE = "step_free"
    REDUCED_MOBILITY = "reduced_mobility"


class Variant(StrEnum):
    SHORTEST = "shortest"
    WINTER_AWARE = "winter_aware"


class HazardKind(StrEnum):
    SIDEWALK_CLOSURE = "sidewalk_closure"
    CONSTRUCTION_IMPACT = "construction_impact"
    REPORT_311_AGGREGATE = "report_311_aggregate"
    COMMUNITY_REPORT = "community_report"


#: Values of ``edge.foot_access`` that make an edge non-routable (data-model.md).
NON_ROUTABLE_FOOT_ACCESS = frozenset({"no", "private"})


@dataclass(frozen=True, slots=True)
class Evidence:
    state: EvidenceState
    source_ids: tuple[str, ...] = ()
    observed_at: datetime | None = None
    retrieved_at: datetime | None = None
    confidence: float | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "source_ids": list(self.source_ids),
            "observed_at": _iso(self.observed_at),
            "retrieved_at": _iso(self.retrieved_at),
            "confidence": self.confidence,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class RiskEstimate:
    level: RiskLevel
    evidence: Evidence
    probability: float | None = None

    @classmethod
    def unknown(cls, note: str = "No risk estimate available for this segment.") -> RiskEstimate:
        return cls(level=RiskLevel.UNKNOWN, evidence=Evidence(EvidenceState.UNKNOWN, note=note))

    @property
    def is_unknown(self) -> bool:
        """True when this estimate must be treated as *unknown* for costing.

        Risk penalties only come from ``model_estimate`` (validated model or labelled heuristic) or
        ``simulated`` (demo) layers (architecture §5). Anything else — including a level carried by
        another evidence state — is treated as unknown, never as low risk.
        """
        return self.level is RiskLevel.UNKNOWN or self.evidence.state not in (
            EvidenceState.MODEL_ESTIMATE,
            EvidenceState.SIMULATED,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "probability": self.probability,
            "evidence": self.evidence.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class Node:
    node_id: str
    lon: float
    lat: float
    kind: str = "street_node"
    crossing_type: str | None = None
    kerb: str | None = None


@dataclass(frozen=True, slots=True)
class Edge:
    edge_id: str
    from_node_id: str
    to_node_id: str
    coords: tuple[LonLat, ...]
    length_m: float
    edge_kind: str
    foot_access: str = "unknown"
    step_free: bool | None = None
    incline_percent: float | None = None
    width_m: float | None = None
    surface: str | None = None
    lit: bool | None = None
    name: str | None = None
    connectivity_confidence: str = "high"
    component_id: int | None = None
    source_ids: tuple[str, ...] = ("osm",)
    updated_at: datetime | None = None
    crossing_type: str | None = None
    kerb: str | None = None

    @property
    def foot_legal(self) -> bool:
        return self.foot_access not in NON_ROUTABLE_FOOT_ACCESS


@dataclass(frozen=True, slots=True)
class GraphMetadata:
    simulated: bool
    osm_snapshot: str | None = None
    built_at: datetime | None = None
    #: source_id -> last successful refresh (None when unknown)
    source_freshness: dict[str, datetime | None] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True, slots=True)
class GraphData:
    nodes: dict[str, Node]
    edges: list[Edge]
    metadata: GraphMetadata


@dataclass(frozen=True, slots=True)
class Hazard:
    """A closure, disruption or report that may affect routing.

    ``geometry`` is a GeoJSON geometry dict in EPSG:4326.
    """

    hazard_id: str
    kind: HazardKind
    geometry: dict[str, Any]
    evidence: Evidence
    blocks_passage: bool | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    title_en: str | None = None
    title_fr: str | None = None
    report_count: int | None = None
    #: Source-rule activity at the query time (``wp.closure_active_at``, data-model v1.4):
    #: True = active, None = unknown (e.g. no usable weekly schedule). Rows the rule reports as
    #: inactive are not returned at all. Unknown is never treated as clear.
    active: bool | None = True

    def active_at(self, at: datetime) -> bool:
        if self.valid_from is not None and at < self.valid_from:
            return False
        return not (self.valid_to is not None and at > self.valid_to)

    @property
    def is_hard_closure(self) -> bool:
        """Only a *confirmed* closure explicitly blocking passage **and active** is excluded."""
        return (
            self.blocks_passage is True
            and self.active is True
            and self.evidence.state is EvidenceState.CONFIRMED
        )

    @property
    def is_possible_closure(self) -> bool:
        """Confirmed passage-blocking permit whose activity at the query time is unknown:
        penalised and flagged, never excluded and never treated as clear."""
        return (
            self.blocks_passage is True
            and self.active is None
            and self.evidence.state is EvidenceState.CONFIRMED
        )


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat().replace("+00:00", "Z") if dt is not None else None
