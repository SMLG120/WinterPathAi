"""POST /routes/compare."""

from __future__ import annotations

import json
from collections.abc import Hashable, Sequence
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from winterpath_routing import (
    DegenerateRequestError,
    Hazard,
    NoRouteError,
    Profile,
    RouteRequest,
    SnapError,
)

from ..cache import (
    ROUTES_NOW_TTL_S,
    caches_for,
    graph_version,
    hazard_version,
    key_digest,
    norm_coord,
    risk_version,
)
from ..deps import get_state
from ..errors import ApiError
from ..params import in_coverage, outside_area
from ..schemas import RouteCompareRequest, RouteCompareResponse, WeatherContext
from ..state import AppState

router = APIRouter(tags=["routing"])
log = structlog.get_logger("winterpath_api.routing")

#: placeholder request id in a cached body; replaced by each request's own id
_RID = "wp-cache-request-id-placeholder"
_RID_FIELD = json.dumps({"request_id": _RID}, separators=(",", ":"))[1:-1].encode()
_WC_NULL = b'"weather_context":null'


def _json_body(content: Any) -> bytes:
    return JSONResponse(content=content).body


def _weather_context_json(wc: dict[str, Any] | None) -> bytes:
    if wc is None:
        return _WC_NULL
    dumped = WeatherContext.model_validate(wc).model_dump(
        mode="json", by_alias=True, exclude_unset=True
    )
    return b'"weather_context":' + _json_body(dumped)


def _personalise(body: bytes, request_id: str, wc: dict[str, Any] | None) -> bytes:
    """A stored body with this request's id and its own departure-time weather context (that
    context's freshness is evaluated "now", so it is never reused)."""
    out = body.replace(_RID_FIELD, _json_body({"request_id": request_id})[1:-1], 1)
    return out.replace(_WC_NULL, _weather_context_json(wc), 1)


def _next_activity_change(hazards: Sequence[Hazard], at: datetime) -> datetime | None:
    """Earliest moment after ``at`` when a listed hazard starts or stops applying
    (``Hazard.active_at``): a "leave now" route must not be reused past it."""
    nxt: datetime | None = None
    for h in hazards:
        for t in (h.valid_from, h.valid_to):
            if t is not None and t > at and (nxt is None or t < nxt):
                nxt = t
    return nxt


def _route_key(
    state: AppState,
    body: RouteCompareRequest,
    at: datetime,
    hv: Hashable | None,
    fresh: dict[str, datetime | None],
) -> Hashable | None:
    """Everything the answer depends on, or ``None`` if a data version is unknowable."""
    gv, rv = graph_version(state), risk_version(state.risk, at)
    if gv is None or rv is None or hv is None:
        return None
    prefs = body.model_dump(mode="json", exclude={"origin", "destination", "departure_time"})
    departure = ("now",) if body.departure_time is None else ("at", at.astimezone(UTC))
    return (
        "routes",
        gv,
        rv,
        hv,
        tuple(sorted((k, v.isoformat() if v else None) for k, v in fresh.items())),
        (norm_coord(body.origin.lon, 9), norm_coord(body.origin.lat, 9)),
        (norm_coord(body.destination.lon, 9), norm_coord(body.destination.lat, 9)),
        tuple(sorted(prefs.items())),
        departure,
    )


@router.post(
    "/routes/compare", response_model=RouteCompareResponse, response_model_exclude_unset=True
)
async def compare_routes(
    body: RouteCompareRequest, request: Request, state: AppState = Depends(get_state)
) -> Response:
    state.limiter.check("routes", state.client_hash(request), state.settings.rate_limit_per_minute)

    for which, p in (("origin", body.origin), ("destination", body.destination)):
        if not in_coverage(p.lon, p.lat, state.coverage_bbox):
            raise ApiError(
                422,
                "OUTSIDE_COVERAGE",
                f"{which} is outside the coverage area.",
                {"which": which, "coverage_bbox": list(state.coverage_bbox)},
            )
    engine = state.engine
    if engine is None:
        raise ApiError(
            503,
            "UPSTREAM_UNAVAILABLE",
            "No pedestrian graph is loaded.",
            {"reason": state.graph_error},
        )

    at = body.departure_time or datetime.now(UTC)
    if at.tzinfo is None:
        raise ApiError(422, "VALIDATION_ERROR", "departure_time must include a UTC offset.")

    req = RouteRequest(
        origin=(body.origin.lon, body.origin.lat),
        destination=(body.destination.lon, body.destination.lat),
        at=at,
        profile=Profile(body.profile),
        avoid_unverified_reports=body.avoid_unverified_reports,
        locale=body.locale,
    )

    caches = caches_for(request.app.state, state)

    def compute() -> tuple[bytes, bool, dict[str, Any]]:
        # Runs on the pre-warmed compute pool (blocking DB/CPU work stays off the event loop).
        try:
            hazards, hv = hazard_version(state.hazards, at)
            hazard_fresh = state.hazards.freshness()
        except Exception as exc:
            raise ApiError(503, "UPSTREAM_UNAVAILABLE", "Hazard store unavailable.") from exc

        def build() -> tuple[bytes, dict[str, Any]]:
            result = engine.compare(req, state.risk, hazards, hazard_fresh)
            model = RouteCompareResponse.model_validate(
                {
                    "request_id": _RID,
                    "routes": [r.to_dict() for r in result.routes],
                    "identical": result.identical,
                    "risk_layer": result.risk_layer,
                    "computed_at": datetime.now(UTC),
                    # v1.8: set per request below (display only, freshness evaluated "now")
                    "weather_context": None,
                    "warnings": result.warnings,
                }
            )
            content = model.model_dump(mode="json", by_alias=True, exclude_unset=True)
            meta = {
                "identical": result.identical,
                "distance_m": [round(r.distance_m) for r in result.routes],
            }
            opts: dict[str, Any] = {"meta": meta}
            if body.departure_time is None:
                # "leave now": reuse briefly, and never past a hazard starting/ending
                opts["ttl_s"] = ROUTES_NOW_TTL_S
                opts["valid_until"] = _next_activity_change(hazards, at)
            return _json_body(content), opts

        key = _route_key(state, body, at, hv, hazard_fresh) if caches.enabled else None
        if key is None:
            raw, opts = build()
            return raw, False, opts["meta"]
        entry, hit = caches.routes.get_or_build(key, build)
        if hit:
            log.info("route_cache_hit", key=key_digest(key), profile=body.profile)
        return entry.body, hit, entry.meta

    try:
        raw, hit, meta = await state.compute.run(compute)
    except SnapError as exc:
        # Inside the bbox but outside the served outline (e.g. Laval, Longueuil): the honest
        # answer is "not covered", not "move closer to a sidewalk". Only reached after snapping
        # failed, so a point the graph can serve is never refused because of the outline.
        p = body.origin if exc.which == "origin" else body.destination
        if exc.which in ("origin", "destination") and outside_area(
            p.lon, p.lat, state.coverage_area
        ):
            raise ApiError(
                422,
                "OUTSIDE_COVERAGE",
                f"{exc.which} is outside the coverage area.",
                {"which": exc.which, "coverage_bbox": list(state.coverage_bbox)},
            ) from exc
        raise ApiError(
            422,
            "OFF_NETWORK",
            str(exc),
            {
                "which": exc.which,
                "max_snap_distance_m": exc.max_m,
                "nearest_network_m": exc.nearest_m,
            },
        ) from exc
    except NoRouteError as exc:
        raise ApiError(404, "NO_ROUTE", exc.detail, {"profile": exc.profile.value}) from exc
    except DegenerateRequestError as exc:
        raise ApiError(422, "VALIDATION_ERROR", str(exc)) from exc

    if not hit:
        log.info(
            "route_computed",
            origin=[body.origin.lon, body.origin.lat],  # rounded to 3 dp by the log processor
            destination=[body.destination.lon, body.destination.lat],
            profile=body.profile,
            identical=meta.get("identical"),
            distance_m=meta.get("distance_m"),
        )
    # v1.8: forecast hour covering the departure, display only (the risk score does not use
    # forecasts). From the cached forecast; null when there is none or the departure is outside
    # it. Never triggers a weather refresh. Evaluated per request, never taken from a cache.
    wc = state.live_weather.context_at(at) if state.live_weather is not None else None
    rid = getattr(request.state, "request_id", "")
    return Response(content=_personalise(raw, rid, wc), media_type="application/json")
