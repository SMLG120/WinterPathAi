"""Error envelope (openapi ``Error``) and exception handlers. No stack traces leak to clients."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger("winterpath_api.errors")


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def envelope(request: Request, code: str, message: str, details: dict | None = None) -> dict:
    body: dict[str, Any] = {"code": code, "message": message}
    if details:
        body["details"] = details
    rid = getattr(request.state, "request_id", None)
    if rid:
        body["request_id"] = rid
    return body


def _resp(request: Request, status: int, code: str, message: str, details=None, headers=None):
    return JSONResponse(
        envelope(request, code, message, details), status_code=status, headers=headers
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return _resp(request, exc.status, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        # Never echo input values back (may contain coordinates or e-mail addresses).
        safe = [
            {"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg"), "type": e.get("type")}
            for e in errors
        ]
        if any(e.get("type") == "json_invalid" for e in errors):
            return _resp(request, 400, "VALIDATION_ERROR", "Malformed JSON body.", {"errors": safe})
        return _resp(
            request, 422, "VALIDATION_ERROR", "Request validation failed.", {"errors": safe}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        code = {
            401: "UNAUTHORIZED",
            404: "NOT_FOUND",
            429: "RATE_LIMITED",
        }.get(exc.status_code)
        if code is None:
            code = "INTERNAL" if exc.status_code >= 500 else "VALIDATION_ERROR"
        msg = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _resp(request, exc.status_code, code, msg, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.error("unhandled_exception", error_type=type(exc).__name__, path=request.url.path)
        return _resp(request, 500, "INTERNAL", "Internal server error.")
