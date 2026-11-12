"""winterpath_ml.weather_live: recorded ECCC fixtures + SYNTHETIC variants (labelled) for edge cases.

Recorded fixtures live in tests/fixtures/eccc/ with a .meta.json (URL, retrieval time, sha256).
Every SYNTHETIC case below is derived from a recorded fixture by an explicit, named mutation.
"""

import copy
import hashlib
import io
import json
import threading
import time
import urllib.error
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from winterpath_ml.weather_live import LiveWeatherProvider, eccc, local_day_bounds_utc
from winterpath_ml.weather_live.model import (
    ALERTS_POLICY,
    CITYPAGE_POLICY,
    freshness,
    local_iso,
)

FX = Path(__file__).parent / "fixtures" / "eccc"


def _fx(prefix: str) -> tuple[dict | list, dict]:
    f = sorted(FX.glob(f"{prefix}_2*.json"))
    f = [x for x in f if not x.name.endswith(".meta.json")][-1]
    meta = json.loads(f.with_name(f.stem + ".meta.json").read_text())
    assert (
        hashlib.sha256(f.read_bytes()).hexdigest() == meta["sha256"]
    )  # untouched recording
    return json.loads(f.read_bytes()), meta


CPW, CPW_META = _fx("citypage_qc-147")
FETCHED = datetime.fromisoformat(CPW_META["retrieved_at"])


class Clock:
    def __init__(self, t: datetime):
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t += timedelta(**kw)


def _parse(doc, at=FETCHED):
    return eccc.parse_citypage(
        doc, fetched_at=at, validated_at=at, source_url="fixture"
    )


# ----------------------------------------------------------------- recorded fixtures


def test_recorded_fixtures_are_labelled():
    metas = [json.loads(p.read_text()) for p in FX.glob("*.meta.json")]
    assert len(metas) >= 5
    assert all(m["label"].startswith("RECORDED") and m["retrieved_at"] for m in metas)
    assert all(
        "Environment and Climate Change Canada" in m["attribution"] for m in metas
    )


def test_citypage_qc147_recorded_parses():
    page, prov = _parse(CPW)
    p = CPW["properties"]
    assert prov.issued_at == datetime.fromisoformat(p["lastUpdated"])
    assert (
        prov.provider == "eccc-geomet"
        and prov.product == "citypageweather-realtime/qc-147"
    )
    assert len(page.hourly) == 24
    assert all(h.time_utc.tzinfo == UTC for h in page.hourly)
    assert prov.valid_to == page.hourly[-1].time_utc + timedelta(hours=1)
    assert (
        page.current.temperature_c
        == p["currentConditions"]["temperature"]["value"]["en"]
    )
    assert page.current.wind_chill == p["currentConditions"]["windChill"]["value"]["en"]
    assert (
        page.hourly[0].precip_probability_pct
        == p["hourlyForecastGroup"]["hourlyForecasts"][0]["lop"]["value"]["en"]
    )
    assert len(page.periods) == len(p["forecastGroup"]["forecasts"])
    assert page.warnings == ()
    # icons are not carried (commercial use of ECCC icons needs prior consent)
    assert "icon" not in json.dumps([h.__dict__ for h in page.hourly], default=str)


def test_missing_fields_stay_none_not_zero():
    doc, _ = _fx("citypage_bc-98_with_warnings")
    page, _ = eccc.parse_citypage(
        doc,
        fetched_at=FETCHED,
        validated_at=FETCHED,
        source_url="f",
        expected_id="bc-98",
    )
    assert "condition" not in doc["properties"]["currentConditions"]
    assert page.current.condition.en is None  # absent upstream -> None
    syn = copy.deepcopy(CPW)  # SYNTHETIC: drop lop / blank temperature on hour 0
    h0 = syn["properties"]["hourlyForecastGroup"]["hourlyForecasts"][0]
    del h0["lop"]
    h0["temperature"]["value"]["en"] = ""
    page, _ = _parse(syn)
    assert page.hourly[0].precip_probability_pct is None
    assert page.hourly[0].temperature_c is None


def test_warnings_structure_from_recorded_sample():
    doc, _ = _fx("citypage_bc-98_with_warnings")
    page, _ = eccc.parse_citypage(
        doc,
        fetched_at=FETCHED,
        validated_at=FETCHED,
        source_url="f",
        expected_id="bc-98",
    )
    raw = doc["properties"]["warnings"]
    assert len(page.warnings) == len(raw) > 0
    w = page.warnings[0]
    assert w.description.en == raw[0]["description"]["en"]
    assert w.expires_at == datetime.fromisoformat(raw[0]["expiryTime"]["en"])


def test_alerts_island_empty_is_not_safe_just_empty():
    doc, meta = _fx("alerts_island_bbox")
    at = datetime.fromisoformat(meta["retrieved_at"])
    s, prov = eccc.parse_alerts(doc, fetched_at=at, validated_at=at, source_url="f")
    assert s.alerts == () and s.number_matched == 0
    assert (
        prov.issued_at is None
    )  # nothing published: freshness comes from fetch age only
    assert freshness(prov, at + timedelta(minutes=20), ALERTS_POLICY).state == "delayed"


def test_alerts_recorded_partial_page_is_rejected_as_truncated():
    doc, _ = _fx("alerts_canada_sample")  # recorded with limit=5 while more matched
    assert doc["numberMatched"] > doc["numberReturned"]
    with pytest.raises(eccc.MalformedPayload, match="truncated"):
        eccc.parse_alerts(doc, fetched_at=FETCHED, validated_at=FETCHED, source_url="f")


def test_alerts_sample_text_is_verbatim():
    doc, meta = _fx("alerts_canada_sample")
    doc = copy.deepcopy(doc)
    doc["numberMatched"] = doc[
        "numberReturned"
    ]  # SYNTHETIC: treat the 5 features as complete
    at = datetime.fromisoformat(meta["retrieved_at"])
    s, prov = eccc.parse_alerts(doc, fetched_at=at, validated_at=at, source_url="f")
    assert len(s.alerts) == len(doc["features"]) > 0
    for a, f in zip(s.alerts, doc["features"], strict=True):
        assert a.text.en == f["properties"].get("alert_text_en")
        assert a.text.fr == f["properties"].get("alert_text_fr")
        assert a.area_match == "bbox_intersects"
    assert prov.issued_at == max(a.published_at for a in s.alerts)
    exp = min(a.expires_at for a in s.alerts)
    assert all(a.expires_at > exp for a in s.active(exp))


# ----------------------------------------------------------------- malformed payloads


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["properties"].update(identifier="qc-1"),
        lambda d: d["properties"].pop("lastUpdated"),
        lambda d: d["properties"].update(lastUpdated="2026-11-11T23:02:49"),  # naive
        lambda d: d["properties"]["hourlyForecastGroup"].update(hourlyForecasts={}),
        lambda d: d["properties"]["hourlyForecastGroup"]["hourlyForecasts"].reverse(),
        lambda d: d.update(type="FeatureCollection"),
    ],
    ids=[
        "wrong-id",
        "no-lastUpdated",
        "naive-time",
        "hourly-not-list",
        "unordered",
        "not-feature",
    ],
)
def test_malformed_citypage_rejected(mutate):
    doc = copy.deepcopy(CPW)  # SYNTHETIC mutation of the recorded payload
    mutate(doc)
    with pytest.raises(eccc.MalformedPayload):
        _parse(doc)


def test_malformed_refresh_keeps_last_good_payload():
    clock = Clock(FETCHED)
    docs = [CPW, {"type": "Feature", "properties": {"identifier": "qc-147"}}]
    p = LiveWeatherProvider(fetch_json=lambda url: docs.pop(0), clock=clock)
    good = p.citypage()
    assert good.freshness.state == "current" and good.data is not None
    clock.advance(minutes=31)
    s = p.citypage()
    assert s.data is good.data and s.freshness.state == "delayed"
    assert "MalformedPayload" in s.freshness.reason


# ----------------------------------------------------------------- outage, TTL, single-flight


def test_outage_without_payload_is_unavailable_with_fallback():
    def down(url):
        raise eccc.FetchError("URLError: connection refused")

    p = LiveWeatherProvider(fetch_json=down, clock=Clock(FETCHED))
    s = p.citypage()
    assert s.data is None and s.freshness.state == "unavailable"
    assert (
        s.fallback == "observations_only" and "connection refused" in s.freshness.reason
    )
    a = p.alerts()
    assert a.data is None and a.freshness.state == "unavailable" and a.fallback is None


def test_outage_degrades_last_payload_and_backs_off():
    clock = Clock(FETCHED)
    up = {"ok": True}

    def fetch(url):
        if not up["ok"]:
            raise eccc.FetchError("timeout")
        return CPW

    p = LiveWeatherProvider(fetch_json=fetch, clock=clock)
    assert p.citypage().freshness.state == "current"
    up["ok"] = False
    clock.advance(minutes=11)  # past TTL -> one attempt, fails
    s = p.citypage()
    assert s.freshness.state == "current" and p.fetch_count["citypage"] == 2
    for _ in range(5):  # within retry_after: no new upstream calls
        p.citypage()
    assert p.fetch_count["citypage"] == 2
    clock.advance(minutes=25)  # 36 min since fetch
    assert p.citypage().freshness.state == "delayed"
    clock.advance(hours=3)
    s = p.citypage()
    assert s.freshness.state == "stale" and s.data is not None and s.fallback is None


def test_ttl_serves_cache_without_fetch():
    clock = Clock(FETCHED)
    p = LiveWeatherProvider(fetch_json=lambda url: CPW, clock=clock)
    p.citypage()
    clock.advance(minutes=9)
    p.citypage()
    assert p.fetch_count["citypage"] == 1
    clock.advance(minutes=1)
    p.citypage()
    assert p.fetch_count["citypage"] == 2


def test_single_flight_one_fetch_for_concurrent_callers():
    calls = []

    def slow(url):
        calls.append(url)
        time.sleep(0.2)
        return CPW

    p = LiveWeatherProvider(fetch_json=slow, clock=Clock(FETCHED))
    out = []
    ts = [threading.Thread(target=lambda: out.append(p.citypage())) for _ in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(calls) == 1 and len(out) == 20
    assert all(s.data is out[0].data for s in out)


# ----------------------------------------------------------------- expiry, product loss


def test_expired_forecast_is_unavailable_with_fallback():
    clock = Clock(FETCHED)
    p = LiveWeatherProvider(fetch_json=lambda url: CPW, clock=clock)
    p.citypage()
    page = p.citypage().data
    clock.t = page.hourly[-1].time_utc + timedelta(hours=1)
    # refresh keeps returning the same (old) recorded payload -> still expired
    s = p.citypage()
    assert s.freshness.state == "unavailable" and "validity ended" in s.freshness.reason
    assert s.fallback == "observations_only"


def test_product_disappearing_falls_back_to_observations():
    clock = Clock(FETCHED)
    state = {"gone": False}

    def fetch(url):
        if state["gone"]:
            raise eccc.ProductUnavailable(f"HTTP 404 for {url}")
        return CPW

    p = LiveWeatherProvider(fetch_json=fetch, clock=clock)
    assert p.citypage().fallback is None
    state["gone"] = True
    clock.advance(minutes=10)
    s = p.citypage()
    assert s.fallback == "observations_only" and s.freshness.state == "delayed"
    assert "not published" in s.freshness.reason


def test_http_404_maps_to_product_unavailable(monkeypatch):
    body = max(FX.glob("citypage_missing_item_404_2*[0-9]Z.json")).read_bytes()

    def fake_urlopen(req, timeout):
        raise urllib.error.HTTPError(
            req.full_url, 404, "Not Found", {}, io.BytesIO(body)
        )

    monkeypatch.setattr(eccc.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(eccc.ProductUnavailable):
        eccc.http_get_json(eccc.citypage_url("qc-99999"))


def test_non_json_body_is_malformed(monkeypatch):
    class R(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        eccc.urllib.request, "urlopen", lambda req, timeout: R(b"<html>")
    )
    with pytest.raises(eccc.MalformedPayload):
        eccc.http_get_json("https://example.invalid")


# ----------------------------------------------------------------- DST


def _shift_hourly(start_utc: datetime) -> dict:
    """SYNTHETIC: the recorded payload with hourly timestamps moved to start at `start_utc`."""
    doc = copy.deepcopy(CPW)
    hs = doc["properties"]["hourlyForecastGroup"]["hourlyForecasts"]
    for i, h in enumerate(hs):
        h["timestamp"] = (start_utc + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc["properties"]["lastUpdated"] = (start_utc - timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    return doc


def test_dst_fall_back_2026_11_01_keeps_both_1am_hours():
    page, _ = _parse(_shift_hourly(datetime(2026, 11, 1, 2, tzinfo=UTC)))
    loc = {h.time_utc.hour: h.time_local for h in page.hourly if h.time_utc.day == 1}
    assert loc[5] == "2026-11-01T01:00:00-04:00"  # EDT
    assert (
        loc[6] == "2026-11-01T01:00:00-05:00"
    )  # EST, same wall clock, distinct instant
    assert len({h.time_local for h in page.hourly}) == 24
    gaps = {b.time_utc - a.time_utc for a, b in zip(page.hourly, page.hourly[1:])}
    assert gaps == {timedelta(hours=1)}
    s, e = local_day_bounds_utc(date(2026, 11, 1))
    assert (s, e - s) == (datetime(2026, 11, 1, 4, tzinfo=UTC), timedelta(hours=25))
    assert (
        sum(s <= h.time_utc < e for h in page.hourly) == 22
    )  # 02Z..23Z of the 25 h day


def test_dst_spring_forward_2027_03_14_has_no_2am():
    page, _ = _parse(_shift_hourly(datetime(2027, 3, 14, 5, tzinfo=UTC)))
    loc = [h.time_local for h in page.hourly]
    assert "2027-03-14T01:00:00-05:00" in loc and "2027-03-14T03:00:00-04:00" in loc
    assert not any(x.startswith("2027-03-14T02:") for x in loc)
    s, e = local_day_bounds_utc(date(2027, 3, 14))
    assert e - s == timedelta(hours=23)
    assert (
        local_iso(datetime(2027, 3, 14, 7, tzinfo=UTC)) == "2027-03-14T03:00:00-04:00"
    )


def test_freshness_across_dst_uses_utc_ages():
    _, prov = _parse(_shift_hourly(datetime(2026, 11, 1, 6, tzinfo=UTC)))
    # issued 05:00Z (01:00 EDT); 80 real minutes later the wall clock reads 01:20 EST
    f = freshness(prov, datetime(2026, 11, 1, 6, 20, tzinfo=UTC), CITYPAGE_POLICY)
    assert f.state == "current" and "issued 80 min ago" in f.reason
