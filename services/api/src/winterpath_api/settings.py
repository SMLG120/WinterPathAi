"""Runtime settings from environment variables (names in .env.example + routing additions)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: architecture.md §3 — west, south, east, north (EPSG:4326)
PILOT_BBOX: tuple[float, float, float, float] = (-73.5880, 45.4960, -73.5620, 45.5130)
PILOT_NAME = "McGill / Downtown pilot"
#: openapi.yaml Bbox parameter: max area 0.0025 deg²
MAX_BBOX_AREA_DEG2 = 0.0025

REPO_ROOT = Path(__file__).resolve().parents[4]


def _csv(v: str | None) -> list[str]:
    return [s.strip() for s in (v or "").split(",") if s.strip()]


@dataclass(frozen=True)
class Settings:
    cors_origins: list[str] = field(default_factory=list)
    log_level: str = "INFO"
    #: SHA-256 hex digest of the admin bearer token (optionally prefixed "sha256:"). Empty → admin
    #: endpoints always return 401.
    admin_token_hash: str = ""
    rate_limit_per_minute: int = 60
    database_url: str | None = None
    #: fixture | postgis | none
    graph_source: str = "fixture"
    fixture_dir: Path = REPO_ROOT / "data" / "fixtures" / "pilot_mini"
    #: memory | postgis
    store_backend: str = "memory"
    #: "none" or "package.module:factory" returning a RiskProvider
    risk_provider: str = "none"
    #: size of the pre-warmed route-computation thread pool
    routing_workers: int = 4
    #: none | postgis (reads wp.weather_obs / wp.weather_daily)
    weather_source: str = "none"
    #: observations older than this are not served as "current" (→ 503)
    weather_max_age_minutes: int = 180
    #: station priority order; empty = most recent across stations
    weather_station_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        return cls(
            cors_origins=_csv(e.get("API_CORS_ORIGINS")),
            log_level=e.get("API_LOG_LEVEL") or "INFO",
            admin_token_hash=(e.get("API_ADMIN_TOKEN_HASH") or "").strip(),
            rate_limit_per_minute=int(e.get("API_RATE_LIMIT_PER_MINUTE") or 60),
            database_url=e.get("DATABASE_URL") or None,
            graph_source=(e.get("ROUTING_GRAPH_SOURCE") or "fixture").lower(),
            fixture_dir=Path(e["ROUTING_FIXTURE_DIR"])
            if e.get("ROUTING_FIXTURE_DIR")
            else REPO_ROOT / "data" / "fixtures" / "pilot_mini",
            store_backend=(e.get("API_STORE_BACKEND") or "memory").lower(),
            risk_provider=e.get("RISK_PROVIDER") or "none",
            routing_workers=int(e.get("ROUTING_WORKERS") or 4),
            weather_source=(e.get("WEATHER_SOURCE") or "none").lower(),
            weather_max_age_minutes=int(e.get("WEATHER_MAX_AGE_MINUTES") or 180),
            weather_station_ids=_csv(e.get("WEATHER_STATION_IDS")),
        )
