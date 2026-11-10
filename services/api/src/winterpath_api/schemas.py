"""Pydantic v2 models hand-written from docs/contracts/openapi.yaml (v1.0.0).

Request models forbid extra fields. Response models are serialised with ``exclude_unset`` so
optional, non-nullable contract fields are omitted rather than sent as ``null``; nullable required
fields are always set explicitly. Conformance is enforced by tests that validate real responses
against the contract file with jsonschema.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

EvidenceStateT = Literal["confirmed", "unverified_report", "model_estimate", "unknown", "simulated"]
ErrorCode = Literal[
    "VALIDATION_ERROR",
    "OUTSIDE_COVERAGE",
    "BBOX_TOO_LARGE",
    "NO_ROUTE",
    "NOT_FOUND",
    "UNAUTHORIZED",
    "RATE_LIMITED",
    "UPSTREAM_UNAVAILABLE",
    "INTERNAL",
]
Locale = Literal["en", "fr"]
Position = Annotated[list[float], Field(min_length=2, max_length=2)]


class _Req(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Resp(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ----------------------------------------------------------------------------- common
class Error(_Resp):
    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None
    request_id: str | None = None


class Evidence(_Resp):
    state: EvidenceStateT
    source_ids: list[str]
    observed_at: datetime | None
    retrieved_at: datetime | None = None
    confidence: Annotated[float, Field(ge=0, le=1)] | None = None
    note: str | None = None


class LonLat(_Req):
    lon: Annotated[float, Field(ge=-180, le=180)]
    lat: Annotated[float, Field(ge=-90, le=90)]


class LineString(_Resp):
    type: Literal["LineString"] = "LineString"
    coordinates: Annotated[list[Position], Field(min_length=2)]


class Point(_Resp):
    type: Literal["Point"] = "Point"
    coordinates: Position


class Polygon(_Resp):
    type: Literal["Polygon"] = "Polygon"
    coordinates: list[list[Position]]


# ----------------------------------------------------------------------------- system
class HealthCheck(_Resp):
    status: Literal["ok", "degraded", "down", "disabled"]
    detail: str | None = None


class Health(_Resp):
    status: Literal["ok", "degraded", "down"]
    version: str
    checks: dict[str, HealthCheck]


class CoverageGraph(_Resp):
    node_count: int
    edge_count: int
    largest_component_share: Annotated[float, Field(ge=0, le=1)] | None = None
    built_at: datetime | None
    osm_snapshot: str | None


class KnownGap(_Resp):
    description: str
    geometry: Polygon | Point | None = None


class Coverage(_Resp):
    pilot_name: str
    bbox: Annotated[list[float], Field(min_length=4, max_length=4)]
    area: Polygon
    graph: CoverageGraph
    known_gaps: list[KnownGap]


class DataSource(_Resp):
    id: str
    name: str
    publisher: str
    license: str
    license_url: str
    commercial_use: Literal["allowed", "allowed_with_conditions", "not_allowed", "unverified"]
    attribution: str
    url: str
    status: Literal["active", "stale", "disabled", "requires_credentials", "error"]
    last_success_at: datetime | None = None
    record_count: int | None = None
    notes: str | None = None


class PilotRequest(_Req):
    organization: Annotated[str, Field(max_length=120)]
    contact_name: Annotated[str, Field(max_length=120)] | None = None
    contact_email: EmailStr
    segment: Literal["university", "campus", "municipality", "property_manager", "other"]
    message: Annotated[str, Field(max_length=1000)] | None = None
    consent: Literal[True]
    locale: Locale | None = None


# ----------------------------------------------------------------------------- weather
class WeatherCurrent(_Resp):
    station_id: str
    station_name: str | None = None
    observed_at: datetime
    temperature_c: float | None = None
    precipitation_mm_1h: float | None = None
    snow_depth_cm: float | None = None
    wind_speed_kmh: float | None = None
    freeze_thaw_24h: bool | None = None
    evidence: Evidence


class ForecastPeriod(_Resp):
    start: datetime
    end: datetime
    summary_en: str
    summary_fr: str
    temperature_c: float | None = None
    pop_percent: int | None = None


class WeatherAlert(_Resp):
    id: str
    headline: str
    text: str
    language: Locale
    severity: str | None = None
    issued_at: datetime
    expires_at: datetime | None = None


class WeatherForecast(_Resp):
    issued_at: datetime
    periods: list[ForecastPeriod]
    alerts: list[WeatherAlert]
    evidence: Evidence


# ----------------------------------------------------------------------------- map
HazardKindT = Literal[
    "sidewalk_closure", "construction_impact", "report_311_aggregate", "community_report"
]


class HazardProperties(_Resp):
    kind: HazardKindT
    evidence: Evidence
    blocks_passage: bool | None
    title_en: str | None = None
    title_fr: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    report_count: int | None = None


class HazardFeature(_Resp):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: Point | LineString | Polygon
    properties: HazardProperties


class HazardCollection(_Resp):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[HazardFeature]
    next_cursor: str | None


class CrossingInfo(_Resp):
    type: Literal["marked", "traffic_signals", "unmarked", "uncontrolled", "unknown"] | None = None
    kerb: Literal["lowered", "flush", "raised", "unknown"] | None = None


class Accessibility(_Resp):
    step_free: bool | None
    incline_percent: float | None = None
    width_m: float | None = None
    surface: str | None = None


class RiskEstimate(_Resp):
    level: Literal["low", "moderate", "elevated", "high", "unknown"]
    probability: Annotated[float, Field(ge=0, le=1)] | None = None
    evidence: Evidence


EdgeKind = Literal[
    "sidewalk",
    "footway",
    "path",
    "pedestrian_street",
    "crossing",
    "shared_street",
    "steps",
    "other",
]


class SegmentProperties(_Resp):
    length_m: Annotated[float, Field(ge=0)]
    edge_kind: EdgeKind
    crossing: CrossingInfo | None = None
    connectivity_confidence: Literal["high", "medium", "low"]
    accessibility: Accessibility
    risk: RiskEstimate
    sources: list[str]
    updated_at: datetime | None = None


class SegmentFeature(_Resp):
    type: Literal["Feature"] = "Feature"
    id: str
    geometry: LineString
    properties: SegmentProperties


class SegmentCollection(_Resp):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[SegmentFeature]
    next_cursor: str | None


# ----------------------------------------------------------------------------- models
class ModelEvaluation(_Resp):
    split: str | None = None
    pr_auc: float | None = None
    brier: float | None = None
    precision_at_k: float | None = None
    recall_at_k: float | None = None
    baseline_pr_auc: float | None = None
    n_test: int | None = None


class ModelStatus(_Resp):
    risk_layer: Literal["model", "heuristic", "none"]
    enabled: bool
    model_id: str | None = None
    target: str
    trained_at: datetime | None = None
    training_window: str | None = None
    evaluation: ModelEvaluation | None
    limitations: list[str] | None = None


# ----------------------------------------------------------------------------- routing
class RouteCompareRequest(_Req):
    origin: LonLat
    destination: LonLat
    profile: Literal["standard", "step_free", "reduced_mobility"] = "standard"
    departure_time: datetime | None = None
    avoid_unverified_reports: bool = True
    locale: Locale = "en"


class ExplanationItem(_Resp):
    code: str
    text: str
    evidence_state: EvidenceStateT


class RouteStep(_Resp):
    instruction: str
    distance_m: float
    street_name: str | None = None


class Route(_Resp):
    variant: Literal["shortest", "winter_aware"]
    geometry: LineString
    distance_m: Annotated[float, Field(ge=0)]
    duration_s: Annotated[float, Field(ge=0)]
    generalized_cost_s: Annotated[float, Field(ge=0)] | None = None
    edge_ids: list[str]
    unknown_share: Annotated[float, Field(ge=0, le=1)]
    hazards_avoided: list[str] | None = None
    hazards_on_route: list[str] | None = None
    explanation: list[ExplanationItem]
    steps: list[RouteStep] | None = None
    data_freshness: dict[str, datetime | None]


class RouteCompareResponse(_Resp):
    request_id: str
    routes: Annotated[list[Route], Field(min_length=1, max_length=2)]
    identical: bool | None = None
    risk_layer: Literal["model", "heuristic", "none"]
    computed_at: datetime
    warnings: list[str] | None = None


# ----------------------------------------------------------------------------- reports
ReportCategory = Literal["snow", "ice", "obstructed_ramp", "construction", "other"]
ModerationStatus = Literal["pending", "approved", "rejected", "expired", "deleted"]


class ReportCreate(_Req):
    category: ReportCategory
    location: LonLat
    location_consent: Literal[True]
    description: Annotated[str, Field(max_length=280)] | None = None
    locale: Locale | None = None


class ReportReceipt(_Resp):
    id: UUID
    status: ModerationStatus
    expires_at: datetime
    deletion_token: str


class ReportAdminView(_Resp):
    id: UUID
    category: ReportCategory
    location: LonLat
    description: str | None
    status: ModerationStatus
    created_at: datetime
    expires_at: datetime
    moderated_at: datetime | None
    moderation_note: str | None


class ReportAdminList(_Resp):
    items: list[ReportAdminView]
    next_cursor: str | None


class ModerationDecision(_Req):
    decision: Literal["approve", "reject", "expire"]
    note: Annotated[str, Field(max_length=500)] | None = None
