from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from .errors import ApiError
from .state import AppState


def get_state(request: Request) -> AppState:
    return request.app.state.wp


def require_public_writes(request: Request) -> None:
    """v1.7 read-only demo: ``API_PUBLIC_WRITES=false`` → 503 WRITES_DISABLED.

    Used as a route dependency, so it answers before body validation, rate limiting or any
    store access, and nothing about the rejected request is stored.
    """
    if not request.app.state.wp.settings.public_writes:
        raise ApiError(
            503,
            "WRITES_DISABLED",
            "This deployment is read-only: public submissions are disabled.",
        )


class GeoJSONResponse(JSONResponse):
    media_type = "application/geo+json"
