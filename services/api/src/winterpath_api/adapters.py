"""External-provider adapters: risk (ML) and weather (ECCC).

Risk: two provider shapes are accepted and normalised to routing ``RiskEstimate`` (anything
malformed or raising becomes ``unknown``; default is :class:`NullRiskProvider`):

* id-keyed — ``edge_risk(edge_ids, at) -> {edge_id: estimate}`` (:class:`NormalisingRiskProvider`);
* coordinate-keyed — ``winterpath_ml.inference.RiskProvider`` (integration-rules §2):
  ``edge_risk(coords, valid_from) -> estimate`` plus ``cell_risk`` and ``status()``
  (:class:`CoordinateRiskAdapter`, which looks edge geometry up in the routing graph). Its layer
  comes from ``status()["risk_layer"]``; a heuristic layer reports ``probability: null``.

Weather: :class:`WeatherAdapter` protocol. No adapter is configured by default, so weather
endpoints return 503 ``UPSTREAM_UNAVAILABLE`` — values are never invented.
"""

from __future__ import annotations

import importlib
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from threading import Lock
from typing import Any, Protocol
from zoneinfo import ZoneInfo

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
        self.risk_layer = _layer(layer)

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


EdgeCoords = Callable[[str], Sequence[Sequence[float]] | None]
LOCAL_TZ = ZoneInfo("America/Montreal")  # ML score tables are keyed by Montréal local day


def _layer(v: Any) -> str:
    return v if v in ("model", "heuristic", "none") else "heuristic"


def is_coordinate_provider(obj: Any) -> bool:
    """``winterpath_ml.inference.RiskProvider`` shape (has ``cell_risk`` and ``status``)."""
    return callable(getattr(obj, "cell_risk", None)) and callable(getattr(obj, "status", None))


class CoordinateRiskAdapter:
    """Adapts a coordinate-keyed ML provider to the routing ``RiskProvider`` protocol.

    Results are cached per (edge id, Montréal local day): the ML layers are daily score tables,
    so the estimate for an edge cannot change within a day for a loaded provider.
    """

    def __init__(self, inner: Any, edge_coords: EdgeCoords, cache_size: int = 200_000) -> None:
        self.inner = inner
        self.edge_coords = edge_coords
        try:
            status = inner.status() or {}
        except Exception as exc:
            log.warning("risk_status_failed", error_type=type(exc).__name__)
            status = {}
        self._status = dict(status)
        self.risk_layer = _layer(self._status.get("risk_layer"))
        self._cache: OrderedDict[tuple[str, Any], RiskEstimate] = OrderedDict()
        self._cache_size = cache_size
        self._lock = Lock()

    def _one(self, eid: str, at: datetime) -> RiskEstimate:
        coords = self.edge_coords(eid)
        if not coords or len(coords) < 2:
            return RiskEstimate.unknown("Segment geometry unavailable to the risk layer.")
        try:
            return normalise_estimate(self.inner.edge_risk(coords, at))
        except Exception as exc:
            log.warning("risk_provider_failed", error_type=type(exc).__name__)
            return RiskEstimate.unknown("Risk provider failed for this segment.")

    def edge_risk(self, edge_ids: Sequence[str], at: datetime) -> Mapping[str, RiskEstimate]:
        if self.risk_layer == "none":
            return NullRiskProvider().edge_risk(edge_ids, at)
        day = at.astimezone(LOCAL_TZ).date()
        out: dict[str, RiskEstimate] = {}
        for eid in edge_ids:
            key = (eid, day)
            with self._lock:
                hit = self._cache.get(key)
            if hit is None:
                hit = self._one(eid, at)
                with self._lock:
                    self._cache[key] = hit
                    if len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
            out[eid] = hit
        return out

    def model_status(self) -> dict[str, Any] | None:
        return self._status or None


def load_risk_provider(spec: str, edge_coords: EdgeCoords | None = None) -> RiskProvider:
    """``none`` → NullRiskProvider; ``pkg.module:factory`` → factory() wrapped for normalisation.

    A coordinate-keyed provider (``winterpath_ml.inference``) needs ``edge_coords``; without a
    graph there is nothing to look up, so every edge is unknown (NullRiskProvider).
    """
    if not spec or spec.lower() == "none":
        return NullRiskProvider()
    module_name, _, attr = spec.partition(":")
    factory = getattr(importlib.import_module(module_name), attr or "RiskProvider")
    inner = factory() if callable(factory) else factory
    if is_coordinate_provider(inner):
        if edge_coords is None:
            log.warning("risk_provider_without_graph")
            return NullRiskProvider()
        return CoordinateRiskAdapter(inner, edge_coords)
    return NormalisingRiskProvider(inner)


def default_model_status(provider: Any) -> dict[str, Any]:
    status_fn = getattr(provider, "model_status", None)
    status = status_fn() if callable(status_fn) else None
    if status and (status.get("risk_layer") != "none" or status.get("limitations")):
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
