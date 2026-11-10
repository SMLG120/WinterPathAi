"""External-provider adapters: risk (ML) and weather (ECCC).

Risk: wraps any object implementing ``edge_risk(edge_ids, at)`` (integration-rules §2,
``winterpath_ml.inference.RiskProvider``) and normalises results to routing ``RiskEstimate``;
anything malformed becomes ``unknown``. Default is :class:`NullRiskProvider`.

Weather: :class:`WeatherAdapter` protocol. No adapter is configured by default, so weather
endpoints return 503 ``UPSTREAM_UNAVAILABLE`` — values are never invented.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

import structlog
from winterpath_routing import (
    Evidence,
    EvidenceState,
    NullRiskProvider,
    RiskEstimate,
    RiskLevel,
    RiskProvider,
)

log = structlog.get_logger("winterpath_api.adapters")

ML_TARGET = "P(>=1 winter-related 311 report in H3 res-9 cell within next 24h)"


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _parse_dt(v: Any) -> datetime | None:
    if v is None or isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def normalise_estimate(v: Any) -> RiskEstimate:
    if isinstance(v, RiskEstimate):
        return v
    try:
        level = RiskLevel(str(_get(v, "level")))
        ev = _get(v, "evidence")
        state = EvidenceState(str(_get(ev, "state")))
        prob = _get(v, "probability")
        prob = float(prob) if prob is not None else None
        if prob is not None and not 0.0 <= prob <= 1.0:
            raise ValueError("probability out of range")
        conf = _get(ev, "confidence")
        evidence = Evidence(
            state=state,
            source_ids=tuple(str(s) for s in (_get(ev, "source_ids") or ())),
            observed_at=_parse_dt(_get(ev, "observed_at")),
            retrieved_at=_parse_dt(_get(ev, "retrieved_at")),
            confidence=float(conf) if conf is not None else None,
            note=_get(ev, "note"),
        )
        return RiskEstimate(level=level, evidence=evidence, probability=prob)
    except (TypeError, ValueError):
        return RiskEstimate.unknown("Risk provider returned an unreadable estimate.")


class NormalisingRiskProvider:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        layer = str(getattr(inner, "risk_layer", "heuristic"))
        self.risk_layer = layer if layer in ("model", "heuristic", "none") else "heuristic"

    def edge_risk(self, edge_ids: Sequence[str], at: datetime) -> Mapping[str, RiskEstimate]:
        try:
            raw = self.inner.edge_risk(list(edge_ids), at) or {}
        except Exception as exc:
            log.warning("risk_provider_failed", error_type=type(exc).__name__)
            return NullRiskProvider().edge_risk(edge_ids, at)
        return {eid: normalise_estimate(raw[eid]) for eid in edge_ids if eid in raw}

    def model_status(self) -> dict[str, Any] | None:
        fn = getattr(self.inner, "model_status", None) or getattr(self.inner, "status", None)
        return fn() if callable(fn) else None


def load_risk_provider(spec: str) -> RiskProvider:
    """``none`` → NullRiskProvider; ``pkg.module:factory`` → factory() wrapped for normalisation."""
    if not spec or spec.lower() == "none":
        return NullRiskProvider()
    module_name, _, attr = spec.partition(":")
    factory = getattr(importlib.import_module(module_name), attr or "RiskProvider")
    return NormalisingRiskProvider(factory() if callable(factory) else factory)


def default_model_status(provider: Any) -> dict[str, Any]:
    status_fn = getattr(provider, "model_status", None)
    status = status_fn() if callable(status_fn) else None
    if status:
        return {"target": ML_TARGET, **status}
    layer = getattr(provider, "risk_layer", "none")
    return {
        "risk_layer": layer,
        "enabled": False,
        "model_id": None,
        "target": ML_TARGET,
        "trained_at": None,
        "training_window": None,
        "evaluation": None,
        "limitations": [
            "No risk model or heuristic layer is loaded in this API instance; every segment's "
            "risk is reported as unknown.",
            "The target measures winter-related 311 reporting behaviour, not physical ice or "
            "sidewalk safety.",
        ]
        if layer == "none"
        else ["Provider did not report model status."],
    }


class WeatherUnavailableError(RuntimeError):
    pass


class WeatherAdapter(Protocol):
    def current(self) -> dict[str, Any]:
        """WeatherCurrent payload or raise WeatherUnavailableError."""
        ...

    def forecast(self, hours: int) -> dict[str, Any]:
        """WeatherForecast payload or raise WeatherUnavailableError."""
        ...
