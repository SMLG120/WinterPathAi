"""structlog JSON logging. Coordinates are rounded to 3 dp (≈100 m) before any log is written."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import structlog

COORD_KEYS = frozenset({"lon", "lat", "origin", "destination", "location", "coordinates", "point"})
DROP_KEYS = frozenset({"contact_email", "email", "description", "deletion_token", "token"})


def _round(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 3)
    if isinstance(v, list | tuple):
        return [_round(x) for x in v]
    if isinstance(v, Mapping):
        return {k: _round(x) for k, x in v.items()}
    return v


def scrub_privacy(_logger: Any, _method: str, event: dict[str, Any]) -> dict[str, Any]:
    """Round coordinate-like values to 3 dp and drop personal fields, whatever the caller passed."""
    for k in list(event):
        if k in DROP_KEYS:
            event[k] = "[redacted]"
        elif k in COORD_KEYS:
            event[k] = _round(event[k])
    return event


def add_timestamp(_logger: Any, _method: str, event: dict[str, Any]) -> dict[str, Any]:
    """UTC ISO-8601 timestamp at millisecond precision.

    Microsecond seconds fields (e.g. ``…:40.010135Z``) look like precise coordinates to log
    privacy scanners; milliseconds are sufficient for request logs.
    """
    event["timestamp"] = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return event


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))
    # Uvicorn's own access log writes full query strings (e.g. precise bbox coordinates) and
    # client IPs. Our middleware logs path/status/duration only, so silence uvicorn's.
    access = logging.getLogger("uvicorn.access")
    access.disabled = True
    access.propagate = False
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            add_timestamp,
            scrub_privacy,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=False,
    )
