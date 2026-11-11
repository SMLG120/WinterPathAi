"""Normalised weather records, provenance and freshness. Pure: no I/O, no clock reads.

Times: every stored datetime is timezone-aware UTC. Local semantics use America/Toronto (the IANA
zone that America/Montreal links to), so local labels and local-day bounds are right across DST
(e.g. 2026-11-01 has 25 local hours, 2027-03-14 has 23).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Toronto")
PROVIDER = "eccc-geomet"
ATTRIBUTION = "Data Source: Environment and Climate Change Canada"
LICENCE_URL = "https://eccc-msc.github.io/open-data/licence/readme_en/"

FreshnessState = Literal["current", "delayed", "stale", "unavailable"]
FRESHNESS_STATES: tuple[str, ...] = ("current", "delayed", "stale", "unavailable")


def utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError(f"naive datetime not allowed: {dt!r}")
    return dt.astimezone(UTC)


def parse_utc(s: Any) -> datetime:
    """Strict ISO-8601 with an explicit offset or Z; returns UTC. Raises ValueError otherwise."""
    if not isinstance(s, str) or not s:
        raise ValueError(f"not a timestamp: {s!r}")
    return utc(datetime.fromisoformat(s))


def local_iso(dt: datetime) -> str:
    """Local wall time with its UTC offset, e.g. 2026-11-01T01:00:00-05:00 (unambiguous)."""
    return utc(dt).astimezone(LOCAL_TZ).isoformat()


def local_day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    """[start, end) of local day `d` in UTC. 23 h / 25 h on DST change days."""
    start = datetime(d.year, d.month, d.day, tzinfo=LOCAL_TZ)
    nxt = d + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=LOCAL_TZ)
    return start.astimezone(UTC), end.astimezone(UTC)


@dataclass(frozen=True)
class FreshnessPolicy:
    """Age thresholds for one product. Ages beyond `delayed_after` are delayed, beyond `stale_after` stale.

    `issue_*` apply to the publisher's issue time; `fetch_*` to our last successful fetch (catches a
    failing refresh even when the publisher's last issue is recent).
    """

    ttl: timedelta  # refresh interval for the provider cache
    issue_delayed_after: timedelta | None
    issue_stale_after: timedelta | None
    fetch_delayed_after: timedelta
    fetch_stale_after: timedelta


# City Page Weather: ECCC documents hourly updates at a minimum (Datamart readme); qc-147 lastUpdated
# was 23:02:49Z when recorded at 23:10Z. Allow one missed hourly cycle before "delayed".
CITYPAGE_POLICY = FreshnessPolicy(
    ttl=timedelta(minutes=10),
    issue_delayed_after=timedelta(minutes=90),
    issue_stale_after=timedelta(hours=3),
    fetch_delayed_after=timedelta(minutes=30),
    fetch_stale_after=timedelta(hours=3),
)
# Alerts can be issued with < 30 min notice (ECCC alerts readme). An empty list has no issue time,
# so alert freshness is judged on our fetch age only.
ALERTS_POLICY = FreshnessPolicy(
    ttl=timedelta(minutes=5),
    issue_delayed_after=None,
    issue_stale_after=None,
    fetch_delayed_after=timedelta(minutes=15),
    fetch_stale_after=timedelta(hours=1),
)

_RANK = {s: i for i, s in enumerate(FRESHNESS_STATES)}


def _by_age(
    age: timedelta, delayed: timedelta | None, stale: timedelta | None
) -> FreshnessState:
    if stale is not None and age > stale:
        return "stale"
    if delayed is not None and age > delayed:
        return "delayed"
    return "current"


@dataclass(frozen=True)
class Provenance:
    provider: str
    product: str
    source_url: str
    issued_at: datetime | None
    valid_from: datetime | None
    valid_to: datetime | None
    fetched_at: datetime
    validated_at: datetime
    attribution: str = ATTRIBUTION
    licence_url: str = LICENCE_URL


@dataclass(frozen=True)
class Freshness:
    state: FreshnessState
    reason: str
    evaluated_at: datetime


def freshness(
    prov: Provenance | None,
    now: datetime,
    policy: FreshnessPolicy,
    last_error: str | None = None,
) -> Freshness:
    """Worst of issue-age and fetch-age; unavailable when there is no payload or validity ended."""
    now = utc(now)
    if prov is None:
        return Freshness("unavailable", last_error or "no validated payload yet", now)
    if prov.valid_to is not None and now >= prov.valid_to:
        return Freshness(
            "unavailable", f"validity ended at {prov.valid_to.isoformat()}", now
        )
    states: list[tuple[FreshnessState, str]] = []
    if prov.issued_at is not None:
        age = now - prov.issued_at
        s = _by_age(age, policy.issue_delayed_after, policy.issue_stale_after)
        states.append((s, f"issued {age.total_seconds() / 60:.0f} min ago"))
    fage = now - prov.fetched_at
    s = _by_age(fage, policy.fetch_delayed_after, policy.fetch_stale_after)
    note = f"fetched {fage.total_seconds() / 60:.0f} min ago"
    if last_error:
        note += f"; last refresh failed: {last_error}"
    states.append((s, note))
    worst = max(states, key=lambda x: _RANK[x[0]])[0]
    return Freshness(worst, "; ".join(n for _, n in states), now)


@dataclass(frozen=True)
class Snapshot:
    """What consumers get: data (or None), provenance, freshness, and any fallback instruction."""

    product: str
    data: Any
    provenance: Provenance | None
    freshness: Freshness
    fallback: str | None = (
        None  # e.g. "observations_only" when the city page is unavailable
    )
    notes: tuple[str, ...] = field(default_factory=tuple)

    def with_freshness(self, f: Freshness, fallback: str | None) -> Snapshot:
        return replace(self, freshness=f, fallback=fallback)


# ----------------------------------------------------------------- normalised records


@dataclass(frozen=True)
class Text:
    en: str | None
    fr: str | None


@dataclass(frozen=True)
class CurrentConditions:
    observed_at: datetime | None
    observed_at_local: str | None
    station_code: str | None
    station_name: Text
    condition: Text
    temperature_c: float | None
    dewpoint_c: float | None
    wind_chill: float | None
    relative_humidity_pct: float | None
    wind_speed_kmh: float | None
    wind_gust_kmh: float | None
    wind_direction: str | None
    pressure_kpa: float | None


@dataclass(frozen=True)
class HourlyForecast:
    time_utc: datetime
    time_local: str
    condition: Text
    temperature_c: float | None
    precip_probability_pct: float | None  # ECCC "lop" (likelihood of precipitation)
    precip_probability_category: Text
    wind_speed_kmh: float | None
    wind_gust_kmh: float | None
    wind_direction: str | None
    uv_index: float | None


@dataclass(frozen=True)
class PeriodForecast:
    """Named text period (e.g. "Tonight"). ECCC gives no start/end timestamps for these."""

    name: Text
    summary: Text
    temperature_high_c: float | None
    temperature_low_c: float | None
    wind_chill_text: Text
    wind_chill_c: float | None
    precipitation_text: Text


@dataclass(frozen=True)
class Warning:
    description: Text
    type: str | None
    colour: str | None
    issued_at: datetime | None
    expires_at: datetime | None
    url: Text


@dataclass(frozen=True)
class CityPage:
    location_id: str
    name: Text
    region: Text
    current: CurrentConditions | None
    hourly: tuple[HourlyForecast, ...]
    hourly_issued_at: datetime | None
    periods: tuple[PeriodForecast, ...]
    periods_issued_at: datetime | None
    warnings: tuple[Warning, ...]


@dataclass(frozen=True)
class Alert:
    """One ECCC alert feature (alert × area). Text is verbatim (licence: no alteration)."""

    id: str
    code: str | None
    type: str | None  # warning | watch | advisory | statement
    name: Text
    text: Text
    area_name: Text
    risk_colour: str | None
    status: Text
    confidence: Text
    impact: Text
    published_at: datetime | None
    valid_from: datetime | None
    expires_at: datetime | None
    event_end_at: datetime | None
    area_match: str  # how this alert was matched to the island


@dataclass(frozen=True)
class AlertSet:
    query_bbox: tuple[float, float, float, float]
    alerts: tuple[Alert, ...]
    number_matched: int | None

    def active(self, now: datetime) -> tuple[Alert, ...]:
        """Alerts not past their expiry at `now` (expiry unknown -> kept)."""
        now = utc(now)
        return tuple(
            a for a in self.alerts if a.expires_at is None or a.expires_at > now
        )
