"""POST /routes/compare."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, Request
from winterpath_routing import (
    CompareResult,
    DegenerateRequestError,
    NoRouteError,
    Profile,
    RouteRequest,
    SnapError,
)

from ..deps import get_state
from ..errors import ApiError
from ..params import in_coverage
from ..schemas import RouteCompareRequest, RouteCompareResponse
from ..state import AppState

router = APIRouter(tags=["routing"])
log = structlog.get_logger("winterpath_api.routing")


@router.post(
    "/routes/compare", response_model=RouteCompareResponse, response_model_exclude_unset=True
)
async def compare_routes(
    body: RouteCompareRequest, request: Request, state: AppState = Depends(get_state)
) -> RouteCompareResponse:
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

    def compute() -> CompareResult:
        # Runs on the pre-warmed compute pool (blocking DB/CPU work stays off the event loop).
        try:
            hazards = state.hazards.list(at)
            hazard_fresh = state.hazards.freshness()
        except Exception as exc:
            raise ApiError(503, "UPSTREAM_UNAVAILABLE", "Hazard store unavailable.") from exc
        return engine.compare(req, state.risk, hazards, hazard_fresh)

    try:
        result = await state.compute.run(compute)
    except SnapError as exc:
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

    log.info(
        "route_computed",
        origin=[body.origin.lon, body.origin.lat],  # rounded to 3 dp by the log processor
        destination=[body.destination.lon, body.destination.lat],
        profile=body.profile,
        identical=result.identical,
        distance_m=[round(r.distance_m) for r in result.routes],
    )
    return RouteCompareResponse.model_validate(
        {
            "request_id": getattr(request.state, "request_id", ""),
            "routes": [r.to_dict() for r in result.routes],
            "identical": result.identical,
            "risk_layer": result.risk_layer,
            "computed_at": datetime.now(UTC),
            # v1.8: forecast hour covering the departure, display only (the risk score does not
            # use forecasts). From the cached forecast; null when there is none or the departure
            # is outside it. Never triggers a weather refresh.
            "weather_context": (
                state.live_weather.context_at(at) if state.live_weather is not None else None
            ),
            "warnings": result.warnings,
        }
    )
