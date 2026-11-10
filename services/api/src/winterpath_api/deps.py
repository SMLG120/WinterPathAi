from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from .state import AppState


def get_state(request: Request) -> AppState:
    return request.app.state.wp


class GeoJSONResponse(JSONResponse):
    media_type = "application/geo+json"
