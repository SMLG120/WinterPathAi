"""Contract v1.8: live ECCC forecast/alerts, /data-status and routes/compare weather_context.

Uses ML's RECORDED ECCC responses (services/ml/tests/fixtures/eccc, sha256-checked, retrieval time
in the .meta.json). Cases that need something ECCC did not publish at recording time are SYNTHETIC
and say so (an explicit, named mutation of a recorded payload). No test calls ECCC.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from datetime import UTC, datetime, timedelta

import pytest
from api_testlib import PILOT_MINI, REPO, pilot_route_points, validate_response
from test_api_weather import FakeStore, hourly
from winterpath_ml.weather_live import LiveWeatherProvider, eccc

from winterpath_api.live_weather import LiveWeather
from winterpath_api.settings import Settings
from winterpath_api.weather import ObservationWeatherAdapter

FX = REPO / "services" / "ml" / "tests" / "fixtures" / "eccc"


def _fx(prefix: str) -> tuple[dict, datetime]:
    f = [x for x in sorted(FX.glob(f"{prefix}_2*.json")) if not x.name.endswith(".meta.json")][-1]
    meta = json.loads(f.with_name(f.stem + ".meta.json").read_text())
    assert meta["label"].startswith("RECORDED")
    assert hashlib.sha256(f.read_bytes()).hexdigest() == meta["sha256"]  # untouched recording
    return json.loads(f.read_bytes()), datetime.fromisoformat(meta["retrieved_at"])


CPW, T0 = _fx("citypage_qc-147")
ALERTS_EMPTY, _ = _fx("alerts_island_bbox")
_SAMPLE, _ = _fx("alerts_canada_sample")
# SYNTHETIC mutation: the Canada-wide sample was recorded with limit=5 while more matched; mark the
# 5 recorded features as the complete result so the parser accepts it (texts stay verbatim).
ALERTS_SAMPLE = copy.deepcopy(_SAMPLE)
ALERTS_SAMPLE["numberMatched"] = ALERTS_SAMPLE["numberReturned"]


class Clock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


class Upstream:
    """Fake ECCC: serves recorded documents; can be switched off (outage)."""

    def __init__(self, citypage=CPW, alerts=ALERTS_EMPTY) -> None:
        self.docs = {"citypage": citypage, "alerts": alerts}
        self.down = False
        self.calls = {"citypage": 0, "alerts": 0}

    def __call__(self, url: str):
        key = "citypage" if "citypageweather" in url else "alerts"
        self.calls[key] += 1
        if self.down:
            raise eccc.FetchError("SYNTHETIC outage (test)")
        return self.docs[key]


def _live(up: Upstream, clock: Clock) -> LiveWeather:
    return LiveWeather(LiveWeatherProvider(fetch_json=up, clock=clock), clock=clock)


@pytest.fixture
def env(make_client):
    up, clock = Upstream(), Clock(T0)
    return make_client(fixture_dir=PILOT_MINI, live_weather=_live(up, clock)), up, clock


# ----------------------------------------------------------------------------- settings
def test_env_names_and_safe_defaults() -> None:
    s = Settings.from_env({})
    assert s.weather_live_enabled is False and s.weather_live_user_agent
    s = Settings.from_env(
        {"WEATHER_LIVE_ENABLED": "true", "WEATHER_LIVE_USER_AGENT": "WinterPathAI-test/1"}
    )
    assert (s.weather_live_enabled, s.weather_live_user_agent) == (True, "WinterPathAI-test/1")


def test_disabled_live_weather_keeps_v17_behaviour(make_client) -> None:
    c = make_client()
    assert c.get("/api/v1/weather/forecast").status_code == 503
    r = c.get("/api/v1/weather/alerts")
    assert r.status_code == 503
    validate_response(r, "/weather/alerts", "get")


# ----------------------------------------------------------------------------- forecast
def test_forecast_from_recorded_citypage(env) -> None:
    c, up, _ = env
    r = c.get("/api/v1/weather/forecast?hours=48")
    assert r.status_code == 200, r.text
    validate_response(r, "/weather/forecast", "get")
    j = r.json()
    assert j["location"] == "qc-147"
    assert j["provenance"]["product"] == "citypageweather-realtime/qc-147"
    assert j["provenance"]["attribution"].startswith("Data Source: Environment and Climate")
    assert j["freshness"]["state"] == "current"
    assert j["evidence"]["state"] == "model_estimate"
    hours = CPW["properties"]["hourlyForecastGroup"]["hourlyForecasts"]
    assert len(j["periods"]) == len(hours) <= 48  # fewer than `hours` when ECCC publishes fewer
    for p in j["periods"]:
        start = datetime.fromisoformat(p["start"].replace("Z", "+00:00"))
        assert datetime.fromisoformat(p["end"].replace("Z", "+00:00")) - start == timedelta(hours=1)
    assert j["text_periods"] and all(t["name"]["en"] for t in j["text_periods"])
    assert j["alerts"] == []
    assert "not mean there are no alerts" not in j["evidence"]["note"]  # alerts were fetched
    assert up.calls == {"citypage": 1, "alerts": 1}


def test_forecast_hours_limit_and_cache_without_refetch(env) -> None:
    c, up, clock = env
    assert len(c.get("/api/v1/weather/forecast?hours=3").json()["periods"]) == 3
    for _ in range(5):
        assert c.get("/api/v1/weather/forecast").status_code == 200
    clock.t += timedelta(minutes=9)  # inside the 10 min TTL
    c.get("/api/v1/weather/forecast")
    assert up.calls["citypage"] == 1


def test_concurrent_requests_share_one_refresh(make_client) -> None:
    gate = threading.Event()
    up, clock = Upstream(), Clock(T0)

    def slow(url):
        gate.wait(2)
        return up(url)

    c = make_client(live_weather=LiveWeather(LiveWeatherProvider(fetch_json=slow, clock=clock)))
    codes: list[int] = []
    ts = [
        threading.Thread(target=lambda: codes.append(c.get("/api/v1/weather/alerts").status_code))
        for _ in range(6)
    ]
    for t in ts:
        t.start()
    gate.set()
    for t in ts:
        t.join()
    assert codes == [200] * 6 and up.calls["alerts"] == 1


def test_outage_without_payload_is_503(env) -> None:
    c, up, _ = env
    up.down = True
    for path in ("/weather/forecast", "/weather/alerts"):
        r = c.get(f"/api/v1{path}")
        assert r.status_code == 503, path
        validate_response(r, path, "get")
        assert r.json()["code"] == "UPSTREAM_UNAVAILABLE"


def test_outage_serves_last_payload_degraded_then_503_after_validity(env) -> None:
    c, up, clock = env
    assert c.get("/api/v1/weather/forecast").status_code == 200
    up.down = True
    clock.t = T0 + timedelta(minutes=45)
    j = c.get("/api/v1/weather/forecast").json()
    assert (
        j["freshness"]["state"] == "delayed" and "last refresh failed" in j["freshness"]["reason"]
    )
    clock.t = T0 + timedelta(hours=4)
    r = c.get("/api/v1/weather/forecast")
    assert r.status_code == 200 and r.json()["freshness"]["state"] == "stale"
    # back-off: one failed attempt per retry window, never one per request
    n = up.calls["citypage"]
    for _ in range(5):
        c.get("/api/v1/weather/forecast")
    assert up.calls["citypage"] == n
    valid_to = datetime.fromisoformat(j["provenance"]["valid_to"].replace("Z", "+00:00"))
    clock.t = valid_to + timedelta(minutes=1)
    assert c.get("/api/v1/weather/forecast").status_code == 503  # expired


# ----------------------------------------------------------------------------- alerts
def test_alerts_empty_is_empty_not_safe(env) -> None:
    c, _, _ = env
    r = c.get("/api/v1/weather/alerts")
    assert r.status_code == 200
    validate_response(r, "/weather/alerts", "get")
    j = r.json()
    assert j["alerts"] == [] and j["provenance"]["product"] == "weather-alerts"
    assert j["freshness"]["state"] == "current"


def test_alerts_text_verbatim(make_client) -> None:
    up, clock = Upstream(alerts=ALERTS_SAMPLE), Clock(T0)
    c = make_client(live_weather=_live(up, clock))
    r = c.get("/api/v1/weather/alerts")
    assert r.status_code == 200
    validate_response(r, "/weather/alerts", "get")
    by_id = {f["id"]: f["properties"] for f in ALERTS_SAMPLE["features"]}
    got = r.json()["alerts"]
    assert got
    for a in got:
        p = by_id[a["id"]]
        assert a["text"] == {"en": p.get("alert_text_en"), "fr": p.get("alert_text_fr")}
        assert a["area_match"] == "bbox_intersects"
    f = c.get("/api/v1/weather/forecast")
    validate_response(f, "/weather/forecast", "get")
    for a in f.json()["alerts"]:
        assert a["text"] == by_id[a["id"]][f"alert_text_{a['language']}"]


# ----------------------------------------------------------------------------- current
def test_current_observation_primary_with_citypage_additions(make_client) -> None:
    rows = hourly([-1.0] * 25, end=datetime.now(UTC) - timedelta(minutes=20))
    up, clock = Upstream(), Clock(T0)
    c = make_client(
        weather=ObservationWeatherAdapter(FakeStore(rows)), live_weather=_live(up, clock)
    )
    r = c.get("/api/v1/weather/current")
    assert r.status_code == 200
    validate_response(r, "/weather/current", "get")
    j = r.json()
    cur = CPW["properties"]["currentConditions"]
    assert j["station_id"] == "TEST-A" and j["temperature_c"] == -1.0  # the observation
    assert j["wind_chill_c"] == -2.0 and j["condition"]["en"] == "Partly Cloudy"  # City Page
    assert cur["condition"]["en"] == "Partly Cloudy"
    assert j["freshness"]["state"] == "current"
    assert "City Page Weather (qc-147)" in j["evidence"]["note"]


def test_current_falls_back_to_citypage_when_no_observation(env) -> None:
    c, _, _ = env
    r = c.get("/api/v1/weather/current")
    assert r.status_code == 200
    validate_response(r, "/weather/current", "get")
    j = r.json()
    assert j["provenance"]["product"] == "citypageweather-realtime/qc-147"
    assert j["precipitation_mm_1h"] is None and j["freeze_thaw_24h"] is None  # unknown, not 0
    assert "No ingested observation" in j["evidence"]["note"]


# ----------------------------------------------------------------------------- data-status
def test_data_status_lists_every_product_and_never_refreshes(env) -> None:
    c, up, _ = env
    r = c.get("/api/v1/data-status")
    assert r.status_code == 200
    validate_response(r, "/data-status", "get")
    prods = {p["id"]: p for p in r.json()["products"]}
    assert set(prods) == {
        "weather_observations",
        "weather_forecast",
        "weather_alerts",
        "closures",
        "reports_311",
        "risk_scores",
        "pedestrian_graph",
    }
    assert prods["weather_forecast"]["mechanism"] == "api_on_demand"
    assert prods["weather_alerts"]["mechanism"] == "api_on_demand"
    assert prods["weather_observations"]["mechanism"] == "scheduled_job"
    assert prods["risk_scores"]["mechanism"] == "scheduled_job"
    assert {prods[k]["mechanism"] for k in ("closures", "reports_311", "pedestrian_graph")} == {
        "manual"
    }
    assert prods["weather_forecast"]["freshness"]["state"] == "unavailable"  # never fetched yet
    assert up.calls == {"citypage": 0, "alerts": 0}
    c.get("/api/v1/weather/forecast")
    prods = {p["id"]: p for p in c.get("/api/v1/data-status").json()["products"]}
    assert prods["weather_forecast"]["freshness"]["state"] == "current"
    assert prods["weather_forecast"]["last_success_at"]
    assert up.calls == {"citypage": 1, "alerts": 1}
    # no database in this client: unknown, never "current"
    assert prods["risk_scores"]["freshness"]["state"] == "unavailable"


# ----------------------------------------------------------------------------- weather_context
def _compare(c, departure: datetime):
    o, d = pilot_route_points()
    r = c.post(
        "/api/v1/routes/compare",
        json={"origin": o, "destination": d, "departure_time": departure.isoformat()},
    )
    assert r.status_code == 200, r.text
    validate_response(r, "/routes/compare", "post")
    return r.json()


def test_weather_context_from_cached_forecast_only(env) -> None:
    c, up, _ = env
    dep = T0 + timedelta(hours=3, minutes=10)
    assert _compare(c, dep)["weather_context"] is None  # nothing cached: no refresh by compare
    assert up.calls["citypage"] == 0
    c.get("/api/v1/weather/forecast")
    ctx = _compare(c, dep)["weather_context"]
    assert ctx["used_for"] == "display_only"
    hour = datetime.fromisoformat(ctx["hour_start"].replace("Z", "+00:00"))
    assert hour <= dep < hour + timedelta(hours=1)
    assert ctx["freshness"]["state"] == "current"
    assert _compare(c, T0 + timedelta(days=5))["weather_context"] is None  # outside the range
    assert up.calls["citypage"] == 1
