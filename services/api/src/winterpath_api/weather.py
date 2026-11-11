"""ECCC weather from ingested observations (``wp.weather_obs`` / ``wp.weather_daily``).

Honesty rules implemented here:

* ``current()`` returns the latest *observation* for the configured station(s), unaltered. If
  there is none, or it is older than ``max_age`` (e.g. only historical training data is loaded),
  it raises :class:`WeatherUnavailableError` → the API answers 503. Values are never invented,
  interpolated or carried forward beyond ``max_age``.
* ``freeze_thaw_24h`` is derived from hourly temperatures in the 24 h before the observation:
  ``True`` if the minimum is below 0 °C and the maximum above 0 °C; ``False`` only when coverage
  is sufficient (≥ ``MIN_HOURS_FOR_FREEZE_THAW`` distinct hours with a temperature) and no
  crossing occurred; otherwise ``null``.
* ``snow_depth_cm`` falls back to ``wp.weather_daily.snow_on_ground_cm`` for the observation's
  climate day (LST = UTC−5, as ECCC climate products use) only when the hourly value is null; the
  evidence note says so. Daily precipitation totals are never presented as 1-hour precipitation.
* ``forecast()`` always raises: no forecast product is ingested, and observations are not a
  forecast.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, Protocol

from .adapters import WeatherUnavailableError

ECCC_SOURCE_ID = "eccc-geomet"
LST = timezone(timedelta(hours=-5))  # ECCC climate "Local Standard Time" for Montréal (no DST)
MIN_HOURS_FOR_FREEZE_THAW = 18


@dataclass(frozen=True, slots=True)
class ObsRow:
    station_id: str
    observed_at: datetime
    temperature_c: float | None
    precip_mm: float | None
    snow_depth_cm: float | None
    wind_kmh: float | None
    source_collection: str
    retrieved_at: datetime | None = None  # ingest run finish time, when known


@dataclass(frozen=True, slots=True)
class DailyRow:
    station_id: str
    day: date
    snow_on_ground_cm: float | None
    retrieved_at: datetime | None = None


class WeatherStore(Protocol):
    def latest_obs(self, station_ids: Sequence[str]) -> ObsRow | None: ...

    def obs_between(self, station_id: str, start: datetime, end: datetime) -> list[ObsRow]: ...

    def daily(self, station_id: str, day: date) -> DailyRow | None: ...


class ObservationWeatherAdapter:
    """Implements :class:`winterpath_api.adapters.WeatherAdapter` over a :class:`WeatherStore`."""

    def __init__(
        self,
        store: WeatherStore,
        *,
        max_age: timedelta = timedelta(hours=3),
        station_ids: Sequence[str] = (),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.store = store
        self.max_age = max_age
        self.station_ids = list(station_ids)
        self.clock = clock

    def current(self) -> dict[str, Any]:
        try:
            obs = self.store.latest_obs(self.station_ids)
        except Exception as exc:
            raise WeatherUnavailableError(f"weather store error: {type(exc).__name__}") from exc
        if obs is None:
            raise WeatherUnavailableError("no ECCC observation ingested")
        age = self.clock() - obs.observed_at
        if age > self.max_age:
            raise WeatherUnavailableError(
                f"latest ECCC observation is stale ({age} old; max {self.max_age})"
            )

        notes = [f"ECCC {obs.source_collection} observation, station {obs.station_id}."]
        snow = obs.snow_depth_cm
        if snow is None:
            day = obs.observed_at.astimezone(LST).date()
            daily = self.store.daily(obs.station_id, day)
            if daily is not None and daily.snow_on_ground_cm is not None:
                snow = daily.snow_on_ground_cm
                notes.append(
                    f"snow_depth_cm is the climate-daily snow on ground for {day.isoformat()} "
                    "(LST), not an hourly reading."
                )

        freeze = self._freeze_thaw(obs)
        if freeze is None:
            notes.append("freeze_thaw_24h unknown: insufficient hourly temperatures in prior 24 h.")

        return {
            "station_id": obs.station_id,
            "observed_at": obs.observed_at,
            "temperature_c": obs.temperature_c,
            "precipitation_mm_1h": obs.precip_mm,
            "snow_depth_cm": snow,
            "wind_speed_kmh": obs.wind_kmh,
            "freeze_thaw_24h": freeze,
            "evidence": {
                "state": "confirmed",
                "source_ids": [ECCC_SOURCE_ID],
                "observed_at": obs.observed_at,
                "retrieved_at": obs.retrieved_at,
                "confidence": None,
                "note": " ".join(notes),
            },
        }

    def _freeze_thaw(self, obs: ObsRow) -> bool | None:
        rows = self.store.obs_between(
            obs.station_id, obs.observed_at - timedelta(hours=24), obs.observed_at
        )
        temps = [r.temperature_c for r in rows if r.temperature_c is not None]
        hours = {
            r.observed_at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
            for r in rows
            if r.temperature_c is not None
        }
        if temps and min(temps) < 0.0 < max(temps):
            return True  # a crossing is observed regardless of coverage
        if len(hours) < MIN_HOURS_FOR_FREEZE_THAW:
            return None
        return False

    def forecast(self, hours: int) -> dict[str, Any]:
        raise WeatherUnavailableError(
            "no ECCC forecast product is ingested; observations are not a forecast"
        )

    def status(self) -> tuple[str, str]:
        """(health status, detail) without raising."""
        try:
            cur = self.current()
        except WeatherUnavailableError as exc:
            return "degraded", str(exc)
        return "ok", f"latest observation {cur['observed_at'].isoformat()}"


class PostgisWeatherStore:
    """Reads ``wp.weather_obs`` (migration 0001) and ``wp.weather_daily`` (data-model v1.2) when
    the latter exists."""

    OBS_COLS = (
        "o.station_id, o.observed_at, o.temperature_c, o.precip_mm, o.snow_depth_cm, o.wind_kmh,"
        " o.source_collection, r.finished_at AS retrieved_at"
    )
    OBS_FROM = (
        " FROM wp.weather_obs o LEFT JOIN wp.ingest_run r ON r.ingest_run_id = o.ingest_run_id"
    )

    def __init__(self, engine) -> None:
        self.engine = engine
        self._has_daily: bool | None = None

    @staticmethod
    def _obs(m) -> ObsRow:
        return ObsRow(**dict(m))

    def latest_obs(self, station_ids: Sequence[str]) -> ObsRow | None:
        from sqlalchemy import text

        sql = "SELECT " + self.OBS_COLS + self.OBS_FROM
        params: dict[str, Any] = {}
        if station_ids:
            sql += " WHERE o.station_id = ANY(:ids)"
            params["ids"] = list(station_ids)
        # Priority: configured order first, then most recent.
        sql += (
            " ORDER BY array_position(CAST(:order AS text[]), o.station_id) NULLS LAST,"
            " o.observed_at DESC LIMIT 1"
        )
        params["order"] = list(station_ids)
        with self.engine.connect() as conn:
            m = conn.execute(text(sql), params).mappings().first()
        return self._obs(m) if m else None

    def obs_between(self, station_id: str, start: datetime, end: datetime) -> list[ObsRow]:
        from sqlalchemy import text

        sql = (
            "SELECT " + self.OBS_COLS + self.OBS_FROM + " WHERE o.station_id = :sid"
            " AND o.observed_at >= :start AND o.observed_at <= :end ORDER BY o.observed_at"
        )
        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), {"sid": station_id, "start": start, "end": end})
            return [self._obs(m) for m in rows.mappings()]

    def daily(self, station_id: str, day: date) -> DailyRow | None:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            if self._has_daily is None:
                exists = text("SELECT to_regclass('wp.weather_daily') IS NOT NULL")
                self._has_daily = bool(conn.execute(exists).scalar())
            if not self._has_daily:
                return None
            m = (
                conn.execute(
                    text(
                        "SELECT d.station_id, d.day, d.snow_on_ground_cm, r.finished_at AS"
                        " retrieved_at FROM wp.weather_daily d LEFT JOIN wp.ingest_run r"
                        " ON r.ingest_run_id = d.ingest_run_id"
                        " WHERE d.station_id = :sid AND d.day = :day"
                    ),
                    {"sid": station_id, "day": day},
                )
                .mappings()
                .first()
            )
        return DailyRow(**dict(m)) if m else None
