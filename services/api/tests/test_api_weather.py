"""ECCC observation-backed weather adapter. Rows here are TEST FIXTURES (station ids prefixed
TEST-), never presented as real observations outside tests."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta

import pytest
from api_testlib import validate_response, validate_schema

from winterpath_api.adapters import WeatherUnavailableError
from winterpath_api.weather import (
    DailyRow,
    ObservationWeatherAdapter,
    ObsRow,
    PostgisWeatherStore,
)

NOW = datetime(2026, 12, 15, 14, 0, tzinfo=UTC)


def obs(t: datetime, temp: float | None, **kw) -> ObsRow:
    base = dict(
        station_id="TEST-A",
        observed_at=t,
        temperature_c=temp,
        precip_mm=None,
        snow_depth_cm=None,
        wind_kmh=None,
        source_collection="swob-realtime",
    )
    base.update(kw)
    return ObsRow(**base)


class FakeStore:
    def __init__(self, rows: list[ObsRow], daily: list[DailyRow] = ()) -> None:
        self.rows = rows
        self.daily_rows = list(daily)

    def latest_obs(self, station_ids):
        cands = [r for r in self.rows if not station_ids or r.station_id in station_ids]
        if not cands:
            return None
        order = {s: i for i, s in enumerate(station_ids)}
        return min(cands, key=lambda r: (order.get(r.station_id, 1e9), -r.observed_at.timestamp()))

    def obs_between(self, station_id, start, end):
        return [
            r for r in self.rows if r.station_id == station_id and start <= r.observed_at <= end
        ]

    def daily(self, station_id, day):
        return next(
            (d for d in self.daily_rows if (d.station_id, d.day) == (station_id, day)), None
        )


def hourly(temps: list[float | None], end: datetime = NOW, **kw) -> list[ObsRow]:
    """One row per hour ending at ``end`` (last element = latest)."""
    n = len(temps)
    return [obs(end - timedelta(hours=n - 1 - i), t, **kw) for i, t in enumerate(temps)]


def adapter(rows, daily=(), **kw) -> ObservationWeatherAdapter:
    return ObservationWeatherAdapter(FakeStore(rows, daily), clock=lambda: NOW, **kw)


def test_current_passes_values_through_unaltered_and_validates() -> None:
    rows = hourly([-2.0] * 24 + [-1.5])
    rows[-1] = obs(
        NOW,
        -1.5,
        precip_mm=0.4,
        snow_depth_cm=12.0,
        wind_kmh=18.0,
        retrieved_at=NOW + timedelta(minutes=5),
    )
    cur = adapter(rows).current()
    assert (
        cur["temperature_c"],
        cur["precipitation_mm_1h"],
        cur["snow_depth_cm"],
        cur["wind_speed_kmh"],
    ) == (-1.5, 0.4, 12.0, 18.0)
    assert cur["evidence"]["state"] == "confirmed"
    assert cur["evidence"]["source_ids"] == ["eccc-geomet"]
    assert cur["freeze_thaw_24h"] is False  # 25 hours, all below zero
    from winterpath_api.schemas import WeatherCurrent

    validate_schema(
        WeatherCurrent.model_validate(cur).model_dump(mode="json", exclude_unset=True),
        "WeatherCurrent",
    )


def test_stale_or_missing_observation_is_unavailable() -> None:
    with pytest.raises(WeatherUnavailableError, match="no ECCC observation"):
        adapter([]).current()
    old = [obs(NOW - timedelta(hours=4), -3.0)]
    with pytest.raises(WeatherUnavailableError, match="stale"):
        adapter(old).current()
    assert adapter(old, max_age=timedelta(hours=5)).current()["temperature_c"] == -3.0


def test_store_failure_is_unavailable() -> None:
    class Broken(FakeStore):
        def latest_obs(self, station_ids):
            raise RuntimeError("db down")

    a = ObservationWeatherAdapter(Broken([]), clock=lambda: NOW)
    with pytest.raises(WeatherUnavailableError):
        a.current()
    assert a.status()[0] == "degraded"


@pytest.mark.parametrize(
    ("temps", "expected"),
    [
        ([-3.0] * 12 + [2.0] * 13, True),  # crossed 0 °C
        ([-3.0, 1.0], True),  # crossing observed even with sparse coverage
        ([1.0] * 25, False),  # full coverage, never below zero
        ([-1.0] * 10, None),  # only 10 hours: unknown, not False
        ([None] * 24 + [-1.0], None),  # temperatures missing
        ([0.0] * 12 + [-1.0] * 13, False),  # touching 0 is not a crossing
    ],
)
def test_freeze_thaw(temps, expected) -> None:
    assert adapter(hourly(temps)).current()["freeze_thaw_24h"] is expected


def test_freeze_thaw_unknown_is_noted() -> None:
    cur = adapter(hourly([-1.0] * 3)).current()
    assert cur["freeze_thaw_24h"] is None
    assert "insufficient hourly temperatures" in cur["evidence"]["note"]


def test_daily_snow_on_ground_fallback_is_labelled() -> None:
    rows = hourly([-2.0] * 25)
    lst_day = (NOW - timedelta(hours=5)).date()
    daily = [DailyRow("TEST-A", lst_day, 23.0)]
    cur = adapter(rows, daily).current()
    assert cur["snow_depth_cm"] == 23.0
    assert f"climate-daily snow on ground for {lst_day.isoformat()}" in cur["evidence"]["note"]
    assert cur["precipitation_mm_1h"] is None  # daily totals never presented as 1-hour precip
    # other days' daily rows are not used
    cur2 = adapter(rows, [DailyRow("TEST-A", lst_day - timedelta(days=1), 23.0)]).current()
    assert cur2["snow_depth_cm"] is None


def test_hourly_snow_depth_wins_over_daily() -> None:
    rows = hourly([-2.0] * 24, end=NOW - timedelta(hours=1))
    rows.append(obs(NOW, -2.0, snow_depth_cm=10.0))
    daily = [DailyRow("TEST-A", (NOW - timedelta(hours=5)).date(), 23.0)]
    cur = adapter(rows, daily).current()
    assert cur["snow_depth_cm"] == 10.0 and "climate-daily" not in cur["evidence"]["note"]


def test_station_priority() -> None:
    rows = [obs(NOW, -1.0, station_id="TEST-B"), obs(NOW - timedelta(minutes=30), -2.0)]
    assert adapter(rows).current()["station_id"] == "TEST-B"  # most recent
    assert adapter(rows, station_ids=["TEST-A", "TEST-B"]).current()["station_id"] == "TEST-A"


def test_forecast_never_invented() -> None:
    with pytest.raises(WeatherUnavailableError, match="no ECCC forecast"):
        adapter(hourly([-1.0] * 25)).forecast(24)


# ----------------------------------------------------------------------------- via the API
def test_api_weather_with_fresh_observations(make_client) -> None:
    rows = hourly([-4.0] * 12 + [1.0] * 13, end=datetime.now(UTC) - timedelta(minutes=20))
    c = make_client(weather=ObservationWeatherAdapter(FakeStore(rows)))
    r = c.get("/api/v1/weather/current")
    assert r.status_code == 200
    validate_response(r, "/weather/current", "get")
    assert r.json()["freeze_thaw_24h"] is True
    f = c.get("/api/v1/weather/forecast")
    assert f.status_code == 503
    validate_response(f, "/weather/forecast", "get")
    h = c.get("/api/v1/health").json()
    assert h["checks"]["weather"]["status"] == "ok"


def test_api_weather_stale_is_503_and_health_degraded(make_client) -> None:
    rows = [obs(datetime.now(UTC) - timedelta(days=30), -8.0)]  # e.g. historical training data
    c = make_client(weather=ObservationWeatherAdapter(FakeStore(rows)))
    r = c.get("/api/v1/weather/current")
    assert r.status_code == 503
    validate_response(r, "/weather/current", "get")
    assert r.json()["code"] == "UPSTREAM_UNAVAILABLE" and "-8" not in r.text
    assert c.get("/api/v1/health").json()["checks"]["weather"]["status"] == "degraded"


# ----------------------------------------------------------------------------- PostGIS
STATION = "TEST-IT-ROUTING"


def _pg_reason() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "DATABASE_URL not set"
    try:
        from sqlalchemy import create_engine, text

        with create_engine(url, connect_args={"connect_timeout": 10}).connect() as c:
            if not c.execute(text("SELECT to_regclass('wp.weather_obs') IS NOT NULL")).scalar():
                return "wp.weather_obs absent (Data agent migrations not applied)"
    except Exception as exc:
        return f"PostGIS unreachable ({type(exc).__name__})"
    return None


@pytest.mark.skipif(_pg_reason() is not None, reason=_pg_reason() or "")
def test_postgis_weather_store_end_to_end(make_client) -> None:
    from sqlalchemy import create_engine, text

    eng = create_engine(os.environ["DATABASE_URL"])
    end = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10)
    rows = hourly([-3.0] * 12 + [2.5] * 13, end=end, station_id=STATION, wind_kmh=11.0)
    with eng.begin() as c:
        c.execute(
            text(
                "INSERT INTO wp.weather_obs (station_id, observed_at, temperature_c, precip_mm,"
                " snow_depth_cm, wind_kmh, source_collection) VALUES (:station_id, :observed_at,"
                " :temperature_c, :precip_mm, :snow_depth_cm, :wind_kmh, :source_collection)"
            ),
            [
                {
                    k: getattr(r, k)
                    for k in (
                        "station_id",
                        "observed_at",
                        "temperature_c",
                        "precip_mm",
                        "snow_depth_cm",
                        "wind_kmh",
                        "source_collection",
                    )
                }
                for r in rows
            ],
        )
    try:
        store = PostgisWeatherStore(eng)
        latest = store.latest_obs([STATION])
        assert latest is not None and latest.observed_at == end
        assert len(store.obs_between(STATION, end - timedelta(hours=24), end)) == 25
        assert store.daily(STATION, date(2026, 12, 15)) is None  # absent table or row
        c = make_client(
            weather_source="postgis",
            database_url=os.environ["DATABASE_URL"],
            weather_station_ids=[STATION],
        )
        r = c.get("/api/v1/weather/current")
        assert r.status_code == 200, r.text
        validate_response(r, "/weather/current", "get")
        body = r.json()
        assert body["station_id"] == STATION
        assert (body["temperature_c"], body["wind_speed_kmh"], body["freeze_thaw_24h"]) == (
            2.5,
            11.0,
            True,
        )
    finally:
        with eng.begin() as c:
            c.execute(text("DELETE FROM wp.weather_obs WHERE station_id = :s"), {"s": STATION})
