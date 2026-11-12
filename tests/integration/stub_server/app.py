"""WinterPath SCHEMA-ONLY STUB API (Platform agent, tests only).

This is NOT the WinterPath API. It exists so contract/smoke/privacy/CORS tests can run before
services/api lands. It validates requests against docs/contracts/openapi.yaml, returns canned
SIMULATED payloads (fixtures.py), stores nothing, and logs per infra/OBSERVABILITY.md.
After merge, point API_BASE_URL at the real API instead.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from . import fixtures
from .contract import Operation, RequestInvalid, operations, validate_request

API_PREFIX = "/api/v1"
ADMIN_TOKEN = os.environ.get("STUB_ADMIN_TOKEN", "stub-admin-token-not-a-secret")
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "API_CORS_ORIGINS", "http://localhost:5173,http://localhost:5174,http://localhost:5175"
    ).split(",")
    if o.strip()
]

log = logging.getLogger("winterpath.stub")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "event": record.getMessage(),
            "service": "api-stub",
            "version": fixtures.STUB_VERSION,
        }
        entry.update(getattr(record, "fields", {}))
        return json.dumps(entry, separators=(",", ":"))


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    log.handlers[:] = [handler]
    log.setLevel(logging.INFO)
    log.propagate = False


def coord_3dp(p: dict[str, Any]) -> list[str]:
    """Privacy rounding for logs: 3 decimals (~100 m), as strings to avoid float repr noise."""
    return [f"{float(p['lon']):.3f}", f"{float(p['lat']):.3f}"]


def error(status: int, code: str, message: str, request_id: str, details: Any = None) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if details:
        body["details"] = {"errors": details} if isinstance(details, list) else details
    return JSONResponse(body, status_code=status)


def parse_bbox(raw: str) -> tuple[float, float, float, float]:
    w, s, e, n = (float(x) for x in raw.split(","))
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise RequestInvalid("invalid", "bbox must be minLon,minLat,maxLon,maxLat with min < max")
    if (e - w) * (n - s) > fixtures.MAX_BBOX_AREA_DEG2:
        raise RequestInvalid("too_large", "bbox area exceeds 0.0025 deg²")
    return w, s, e, n


def handle(op: Operation, request: Request, data: dict[str, Any], rid: str, ctx: dict[str, Any]) -> Response:
    params, body = data["params"], data["body"]
    match op.operation_id:
        case "getHealth":
            return JSONResponse(fixtures.health())
        case "getCoverage":
            return JSONResponse(fixtures.coverage())
        case "listDataSources":
            return JSONResponse([])
        case "getCurrentWeather" | "getWeatherForecast" | "getWeatherAlerts":
            # 503, not an empty alert list: an empty list would assert "ECCC reported no alerts".
            return error(503, "UPSTREAM_UNAVAILABLE", "stub has no weather source (ECCC not connected)", rid)
        case "getDataStatus":
            return JSONResponse(fixtures.data_status())
        case "getModelStatus":
            return JSONResponse(fixtures.model_status())
        case "listHazards" | "listSegments":
            bbox = parse_bbox(params["bbox"])
            payload = fixtures.hazards(bbox) if op.operation_id == "listHazards" else fixtures.segments(bbox)
            return JSONResponse(payload, media_type="application/geo+json")
        case "compareRoutes":
            o, d = body["origin"], body["destination"]
            ctx["origin_3dp"], ctx["destination_3dp"] = coord_3dp(o), coord_3dp(d)
            if not (fixtures.in_pilot(o["lon"], o["lat"]) and fixtures.in_pilot(d["lon"], d["lat"])):
                return error(422, "OUTSIDE_COVERAGE", "origin or destination outside pilot bbox", rid)
            return JSONResponse(fixtures.route_compare(o, d, rid))
        case "createReport":
            ctx["location_3dp"] = coord_3dp(body["location"])
            return JSONResponse(fixtures.report_receipt(str(uuid.uuid4())), status_code=201)
        case "deleteOwnReport" | "moderateReport":
            return error(404, "NOT_FOUND", "stub stores no reports", rid)
        case "listReportsForModeration":
            return JSONResponse({"items": [], "next_cursor": None})
        case "createPilotRequest":
            return Response(status_code=201)  # body discarded, never logged
    return error(500, "INTERNAL", "stub has no handler", rid)  # pragma: no cover


def make_endpoint(ops_for_path: dict[str, Operation]):
    async def endpoint(request: Request) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        start = time.perf_counter()
        ctx: dict[str, Any] = {}
        op = ops_for_path.get("GET" if request.method == "HEAD" else request.method)
        try:
            if op is None:
                resp = error(405, "VALIDATION_ERROR", "method not allowed", rid)
                resp.headers["Allow"] = ", ".join(sorted(ops_for_path))
            elif op.secured and not _authorized(request):
                resp = error(401, "UNAUTHORIZED", "missing or invalid admin token", rid)
                resp.headers["WWW-Authenticate"] = "Bearer"
            else:
                data = validate_request(
                    op,
                    query={k: request.query_params.getlist(k) for k in request.query_params},
                    path_params={k: str(v) for k, v in request.path_params.items()},
                    headers={k.lower(): v for k, v in request.headers.items()},
                    content_type=request.headers.get("content-type"),
                    body=await request.body(),
                )
                resp = handle(op, request, data, rid, ctx)
        except RequestInvalid as exc:
            if exc.kind == "malformed" and (op is None or "400" in op.declared_statuses):
                resp = error(400, "VALIDATION_ERROR", str(exc), rid, exc.details)
            elif exc.kind == "too_large":
                resp = error(422, "BBOX_TOO_LARGE", str(exc), rid)
            else:
                resp = error(422, "VALIDATION_ERROR", str(exc), rid, exc.details)
        except Exception as exc:  # noqa: BLE001 — safe envelope, no stack trace to client
            log.error(
                "unhandled_error", extra={"fields": {"request_id": rid, "error.type": type(exc).__name__}}
            )
            resp = error(500, "INTERNAL", "internal error", rid)
        resp.headers["X-Request-ID"] = rid
        log.info(
            "http_request",
            extra={
                "fields": {
                    "request_id": rid,
                    "method": request.method,
                    "route": API_PREFIX + (op.path if op else request.scope.get("route_path", "?")),
                    "status": resp.status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                    **ctx,
                }
            },
        )
        return resp

    return endpoint


def _authorized(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(token.encode(), ADMIN_TOKEN.encode())


def build_app() -> Starlette:
    configure_logging()
    by_path: dict[str, dict[str, Operation]] = {}
    for op in operations().values():
        by_path.setdefault(op.path, {})[op.method] = op
    routes = [
        Route(path, make_endpoint(ops), methods=[*ops, *(["HEAD"] if "GET" in ops else [])])
        for path, ops in by_path.items()
    ]

    # Unknown paths under the prefix get the contract error envelope.
    async def not_found(request: Request) -> Response:
        return error(404, "NOT_FOUND", "unknown endpoint", uuid.uuid4().hex)

    return Starlette(
        routes=[Mount(API_PREFIX, routes=routes), Route("/{rest:path}", not_found)],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=CORS_ORIGINS,
                allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                allow_headers=["Content-Type", "Authorization", "X-Deletion-Token", "X-Request-ID"],
                expose_headers=["X-Request-ID", "Retry-After"],
                allow_credentials=False,
                max_age=600,
            )
        ],
    )


app = build_app()
