"""/health, /coverage, /data-sources, /data-status, /models/status, /pilot-requests, /weather/*."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request, Response

from .. import CONTRACT_VERSION, __version__
from ..adapters import WeatherUnavailableError, default_model_status
from ..db import ping as db_ping
from ..deps import get_state, require_public_writes
from ..errors import ApiError
from ..repositories.sources import PilotRequestRow
from ..schemas import (
    Coverage,
    DataSource,
    DataStatus,
    Health,
    ModelStatus,
    PilotRequest,
    WeatherAlerts,
    WeatherCurrent,
    WeatherForecast,
)
from ..settings import PILOT_BBOX, PILOT_NAME
from ..state import AppState

router = APIRouter()


@router.get("/health", response_model=Health, response_model_exclude_unset=True, tags=["system"])
def get_health(state: AppState = Depends(get_state)) -> Health:
    checks: dict[str, dict] = {}
    if state.engine is None:
        checks["graph"] = {"status": "down", "detail": f"No pedestrian graph: {state.graph_error}"}
    elif state.engine.graph.metadata.simulated:
        checks["graph"] = {"status": "degraded", "detail": "SIMULATED fixture graph loaded."}
    else:
        checks["graph"] = {"status": "ok"}

    if state.db_engine is None:
        checks["database"] = {"status": "disabled", "detail": "In-memory stores (no DATABASE)."}
    else:
        # Ping the shared engine itself: with in-memory stores it may serve only weather and
        # risk scores, and an in-memory store's ping would always say "ok".
        checks["database"] = (
            {"status": "ok"}
            if db_ping(state.db_engine)
            else {"status": "down", "detail": "PostGIS unreachable."}
        )

    layer = getattr(state.risk, "risk_layer", "none")
    checks["risk"] = (
        {"status": "disabled", "detail": "No risk layer; risk reported as unknown."}
        if layer == "none"
        else {
            "status": "ok",
            "detail": f"risk_layer={layer}; score_source={state.settings.risk_score_source}",
        }
    )
    if state.weather is None:
        checks["weather"] = {"status": "disabled", "detail": "No ECCC adapter configured."}
    elif callable(getattr(state.weather, "status", None)):
        st, detail = state.weather.status()
        checks["weather"] = {"status": st, "detail": detail}
    else:
        checks["weather"] = {"status": "ok"}
    statuses = {c["status"] for c in checks.values()}
    overall = "ok" if statuses <= {"ok", "disabled"} else "degraded"
    return Health.model_validate(
        {
            "status": overall,
            "version": f"{__version__} (contract {CONTRACT_VERSION})",
            "checks": checks,
        }
    )


@router.get(
    "/coverage", response_model=Coverage, response_model_exclude_unset=True, tags=["system"]
)
def get_coverage(state: AppState = Depends(get_state)) -> Coverage:
    w, s, e, n = PILOT_BBOX
    area = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
    gaps: list[dict] = []
    if state.engine is None:
        graph = {"node_count": 0, "edge_count": 0, "built_at": None, "osm_snapshot": None}
        gaps.append(
            {
                "description": "No pedestrian graph is loaded; routing is unavailable.",
                "geometry": None,
            }
        )
    else:
        g = state.engine.graph
        graph = {
            "node_count": len(g.nodes),
            "edge_count": len(g.edges),
            "largest_component_share": round(g.largest_component_share, 4),
            "built_at": g.metadata.built_at,
            "osm_snapshot": g.metadata.osm_snapshot,
        }
        if g.metadata.simulated:
            gaps.append(
                {
                    "description": "SIMULATED: the loaded graph is a synthetic fixture, not "
                    "real streets.",
                    "geometry": None,
                }
            )
        for gap in g.gaps():
            gaps.append(
                {
                    "description": gap.description,
                    "geometry": {
                        "type": "Point",
                        "coordinates": [round(gap.lon, 6), round(gap.lat, 6)],
                    },
                }
            )
    return Coverage.model_validate(
        {
            "pilot_name": PILOT_NAME,
            "bbox": list(PILOT_BBOX),
            "area": area,
            "graph": graph,
            "known_gaps": gaps,
        }
    )


@router.get(
    "/data-sources",
    response_model=list[DataSource],
    response_model_exclude_unset=True,
    tags=["system"],
)
def list_data_sources(state: AppState = Depends(get_state)) -> list[DataSource]:
    try:
        rows = state.sources.list()
    except Exception as exc:
        raise ApiError(503, "UPSTREAM_UNAVAILABLE", "Source registry unavailable.") from exc
    return [DataSource.model_validate(r) for r in rows]


@router.get(
    "/models/status", response_model=ModelStatus, response_model_exclude_unset=True, tags=["models"]
)
def get_model_status(state: AppState = Depends(get_state)) -> ModelStatus:
    return ModelStatus.model_validate(default_model_status(state.risk))


@router.post(
    "/pilot-requests",
    status_code=201,
    tags=["system"],
    dependencies=[Depends(require_public_writes)],
)
def create_pilot_request(
    body: PilotRequest, request: Request, state: AppState = Depends(get_state)
) -> Response:
    client = state.client_hash(request)
    state.limiter.check("pilot", client, min(5, state.settings.rate_limit_per_minute))
    state.pilot_requests.create(
        PilotRequestRow(
            id=uuid.uuid4(),
            organization=body.organization,
            contact_name=body.contact_name,
            contact_email=str(body.contact_email),
            segment=body.segment,
            message=body.message,
            locale=body.locale,
            created_at=datetime.now(UTC),
        )
    )
    return Response(status_code=201)


def _weather_unavailable(what: str) -> ApiError:
    return ApiError(
        503,
        "UPSTREAM_UNAVAILABLE",
        f"ECCC {what} is unavailable; no weather values are returned.",
        {"source_id": "eccc-geomet"},
    )


@router.get(
    "/weather/current",
    response_model=WeatherCurrent,
    response_model_exclude_unset=True,
    tags=["weather"],
)
def get_current_weather(state: AppState = Depends(get_state)) -> WeatherCurrent:
    """SWOB observation (PostGIS) is primary; City Page current conditions add wind chill and
    condition. When no observation can be served, City Page current conditions alone are
    returned. The evidence note names the source of every field."""
    obs, obs_err = None, "no observation adapter configured"
    if state.weather is not None:
        try:
            obs = state.weather.current()
        except WeatherUnavailableError as exc:
            obs_err = str(exc)
    cc = state.live_weather.current_conditions() if state.live_weather is not None else None
    if obs is None and cc is None:
        raise _weather_unavailable("current observation")
    if obs is not None:
        if cc is not None:
            cur, snap = cc
            obs["wind_chill_c"] = cur.wind_chill
            obs["condition"] = {"en": cur.condition.en, "fr": cur.condition.fr}
            obs["evidence"]["note"] += (
                " wind_chill_c and condition: ECCC City Page Weather (qc-147) current "
                f"conditions observed {_iso(cur.observed_at)}, fetched "
                f"{_iso(snap.provenance.fetched_at)} (freshness {snap.freshness.state}); every "
                "other field: the observation above."
            )
        return WeatherCurrent.model_validate(obs)
    cur, snap = cc
    if cur.observed_at is None:
        raise _weather_unavailable("current observation")
    return WeatherCurrent.model_validate(
        {
            "station_id": cur.station_code or snap.data.location_id,
            "station_name": cur.station_name.en or cur.station_name.fr,
            "observed_at": cur.observed_at,
            "temperature_c": cur.temperature_c,
            "precipitation_mm_1h": None,
            "snow_depth_cm": None,
            "wind_speed_kmh": cur.wind_speed_kmh,
            "freeze_thaw_24h": None,
            "wind_chill_c": cur.wind_chill,
            "condition": {"en": cur.condition.en, "fr": cur.condition.fr},
            "freshness": {
                "state": snap.freshness.state,
                "reason": snap.freshness.reason,
                "evaluated_at": snap.freshness.evaluated_at,
            },
            "provenance": _live_provenance(snap.provenance),
            "evidence": {
                "state": "confirmed",
                "source_ids": ["eccc-geomet"],
                "observed_at": cur.observed_at,
                "retrieved_at": snap.provenance.fetched_at,
                "confidence": None,
                "note": "Every field: ECCC City Page Weather (qc-147) current conditions. "
                f"No ingested observation could be served ({obs_err}); precipitation, snow "
                "depth and freeze-thaw are therefore unknown.",
            },
        }
    )


@router.get(
    "/weather/forecast",
    response_model=WeatherForecast,
    response_model_exclude_unset=True,
    tags=["weather"],
)
def get_weather_forecast(
    hours: int = Query(24, ge=1, le=48), state: AppState = Depends(get_state)
) -> WeatherForecast:
    source = state.live_weather if state.live_weather is not None else state.weather
    if source is None:
        raise _weather_unavailable("forecast (no adapter configured)")
    try:
        return WeatherForecast.model_validate(source.forecast(hours))
    except WeatherUnavailableError as exc:
        raise _weather_unavailable("forecast") from exc


@router.get(
    "/weather/alerts",
    response_model=WeatherAlerts,
    response_model_exclude_unset=True,
    tags=["weather"],
)
def get_weather_alerts(state: AppState = Depends(get_state)) -> WeatherAlerts:
    if state.live_weather is None:
        raise _weather_unavailable("alerts (live weather disabled)")
    try:
        return WeatherAlerts.model_validate(state.live_weather.alerts())
    except WeatherUnavailableError as exc:
        raise _weather_unavailable("alerts") from exc


@router.get(
    "/data-status", response_model=DataStatus, response_model_exclude_unset=True, tags=["system"]
)
def get_data_status(state: AppState = Depends(get_state)) -> DataStatus:
    from ..data_status import data_status

    return DataStatus.model_validate(data_status(state))


def _iso(dt) -> str:
    return dt.isoformat().replace("+00:00", "Z") if dt is not None else "unknown"


def _live_provenance(p) -> dict:
    from ..live_weather import _provenance

    return _provenance(p)
