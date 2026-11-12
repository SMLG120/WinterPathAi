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


_FALSE = {"0", "false", "no", "off"}
_TRUE = {"1", "true", "yes", "on"}


def _bool(v: str | None, default: bool) -> bool:
    """Unset/empty → ``default``; anything that is neither true-ish nor false-ish is an error."""
    if v is None or not v.strip():
        return default
    x = v.strip().lower()
    if x in _TRUE:
        return True
    if x in _FALSE:
        return False
    raise ValueError(f"expected a boolean, got {v!r}")


def _choice(v: str | None, default: str, allowed: tuple[str, ...]) -> str:
    x = (v or "").strip().lower() or default
    if x not in allowed:
        raise ValueError(f"expected one of {allowed}, got {v!r}")
    return x


def _int(v: str | None, default: int, minimum: int = 0) -> int:
    n = int(v) if v and v.strip() else default
    if n < minimum:
        raise ValueError(f"expected an integer >= {minimum}, got {n}")
    return n


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
    #: v1.7: where the ML risk provider reads daily scores: file (models/artifacts, local dev) |
    #: postgis (wp.risk_cell_score through the API's shared engine)
    risk_score_source: str = "file"
    #: v1.7: false → POST /reports and POST /pilot-requests return 503 WRITES_DISABLED
    public_writes: bool = True
    #: Wave 1 prototypes, OFF by default (production behaviour unchanged):
    #: ROUTING_COMPACT_GRAPH → array-backed CompactGraph + CompactRoutingEngine (same routes);
    #: ROUTING_STEPS_V2 → merged, named steps (same Step shape, contract unchanged).
    #: v1.8: live ECCC forecast/alerts in memory (winterpath_ml.weather_live). Off by default
    #: (tests never call ECCC); the deploy docs turn it on.
    weather_live_enabled: bool = False
    weather_live_user_agent: str = "WinterPathAI-API/1.8"
    routing_compact_graph: bool = False
    routing_steps_v2: bool = False
    #: v1.7: SQLAlchemy pool, sized for Supabase's session pooler on a free-tier host. One engine
    #: is shared by every repository and the weather store; the graph load uses its own
    #: short-lived connection at startup and releases it.
    db_pool_size: int = 3
    db_max_overflow: int = 2
    #: recycle pooled connections before the pooler/NAT can drop them silently
    db_pool_recycle_s: int = 300
    #: fail fast (→ 503) rather than queue requests behind an exhausted pool
    db_pool_timeout_s: int = 10
    db_connect_timeout_s: int = 10

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        return cls(
            cors_origins=_csv(e.get("API_CORS_ORIGINS")),
            log_level=e.get("API_LOG_LEVEL") or "INFO",
            admin_token_hash=(e.get("API_ADMIN_TOKEN_HASH") or "").strip(),
            rate_limit_per_minute=_int(e.get("API_RATE_LIMIT_PER_MINUTE"), 60, minimum=1),
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
            public_writes=_bool(e.get("API_PUBLIC_WRITES"), True),
            weather_live_enabled=_bool(e.get("WEATHER_LIVE_ENABLED"), False),
            weather_live_user_agent=(e.get("WEATHER_LIVE_USER_AGENT") or "").strip()
            or "WinterPathAI-API/1.8",
            routing_compact_graph=_bool(e.get("ROUTING_COMPACT_GRAPH"), False),
            routing_steps_v2=_bool(e.get("ROUTING_STEPS_V2"), False),
            risk_score_source=_choice(e.get("RISK_SCORE_SOURCE"), "file", ("file", "postgis")),
            db_pool_size=_int(e.get("DATABASE_POOL_SIZE"), 3, minimum=1),
            db_max_overflow=_int(e.get("DATABASE_MAX_OVERFLOW"), 2),
        )
