"""FastAPI application factory. Run: ``uv run uvicorn winterpath_api.main:app --port 8102``."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import CONTRACT_VERSION, __version__
from .errors import install_error_handlers
from .logs import configure_logging
from .routers import map as map_router
from .routers import reports, routing, system
from .settings import Settings
from .state import AppState, build_state, warm_up

API_PREFIX = "/api/v1"
log = structlog.get_logger("winterpath_api.access")
lifecycle = structlog.get_logger("winterpath_api.lifecycle")


def shutdown_state(state: AppState) -> None:
    """Release process resources. Runs on SIGTERM/SIGINT via uvicorn's lifespan shutdown,
    after in-flight requests have drained; safe to call more than once."""
    state.compute.shutdown()
    if state.db_engine is not None:
        state.db_engine.dispose()
    lifecycle.info("shutdown_complete")


def create_app(settings: Settings | None = None, state: AppState | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.routing_warmup:
            warm_up(app.state.wp)
        yield
        shutdown_state(app.state.wp)

    app = FastAPI(
        lifespan=lifespan,
        title="WinterPath AI API",
        version=CONTRACT_VERSION,
        summary=f"Implementation {__version__} of contract v{CONTRACT_VERSION}.",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.state.wp = state or build_state(settings)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,  # explicit allow-list; never "*"
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "X-Deletion-Token"],
            expose_headers=["X-Request-ID", "Retry-After"],
            max_age=600,
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = uuid.uuid4().hex
        request.state.request_id = rid
        t0 = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        # Path only — never query strings or bodies; no client IP.
        log.info(
            "request",
            request_id=rid,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        )
        return response

    install_error_handlers(app)
    for r in (system.router, map_router.router, routing.router, reports.router):
        app.include_router(r, prefix=API_PREFIX)
    return app


def __getattr__(name: str):
    # Lazily build the module-level ASGI app so importing this module has no side effects.
    if name == "app":
        global app
        app = create_app()
        return app
    raise AttributeError(name)
