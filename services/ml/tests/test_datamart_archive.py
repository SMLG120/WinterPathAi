"""Datamart archiver: rate limit, retries, headers, idempotence, gaps. No network; SYNTHETIC XML/listings."""

import gzip
import io
import json
import urllib.error
from datetime import UTC, date, datetime

from winterpath_ml.weather_live import datamart_archive as dm

XML = (  # SYNTHETIC minimal siteData with the Montréal site code
    b'<?xml version="1.0"?><siteData><location><name code="s0000635">Montreal</name>'
    b"</location></siteData>"
)
NAME = "20261111T120350.771Z_MSC_CitypageWeather_s0000635_en.xml"
OTHER = "20261111T120350.771Z_MSC_CitypageWeather_s0000635_fr.xml"


class FakeClock:
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def clock(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(round(s, 3))
        self.t += s


def test_client_spacing_retry_and_headers(monkeypatch):
    fc = FakeClock()
    seen, script = [], [503, 200, 404]

    def fake_urlopen(req, timeout):
        seen.append(dict(req.header_items()))
        code = script.pop(0)
        if code != 200:
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(b""))
        return io.BytesIO(b"ok")

    monkeypatch.setattr(dm.urllib.request, "urlopen", fake_urlopen)
    c = dm.Client(sleep=fc.sleep, clock=fc.clock)
    assert c.get("https://dd.example/a") == b"ok"  # 503 -> wait 5 s -> 200
    assert c.get("https://dd.example/b") is None  # 404 -> None, no retry
    assert c.requests == 3 and 5 in fc.sleeps
    assert all(s >= 0 for s in fc.sleeps)
    for h in seen:
        assert h.get("User-agent", "").startswith("WinterPathAI")
        assert not {k.lower() for k in h} & {"cache-control", "pragma"}


def test_client_min_interval_between_requests(monkeypatch):
    fc = FakeClock()
    monkeypatch.setattr(
        dm.urllib.request, "urlopen", lambda req, timeout: io.BytesIO(b"x")
    )
    c = dm.Client(sleep=fc.sleep, clock=fc.clock)
    for _ in range(3):
        c.get("https://dd.example/x")
    assert fc.sleeps == [dm.MIN_INTERVAL_S, dm.MIN_INTERVAL_S]


class FakeClient:
    def __init__(self, pages):
        self.pages, self.requests, self.urls = pages, 0, []

    def get(self, url):
        self.requests += 1
        self.urls.append(url)
        return self.pages.get(url)


def _pages(d: date):
    ymd = d.strftime("%Y%m%d")
    base = f"{dm.DD}/{ymd}/WXO-DD/citypage_weather/QC"
    pages = {
        f"{base}/{h:02d}/": b"<html></html>" for h in range(23)
    }  # 00..22 empty; 23 missing
    pages[f"{base}/12/"] = f'<a href="{NAME}">x</a> <a href="{OTHER}">y</a>'.encode()
    pages[f"{base}/12/{NAME}"] = XML
    return pages


def test_archive_day_writes_gzip_manifest_and_reports_gaps(tmp_path):
    d = date(2026, 11, 11)
    fc = FakeClient(_pages(d))
    r = dm.archive_day(d, fc, tmp_path, set(), datetime(2026, 11, 12, 1, tzinfo=UTC))
    assert (r["files"], r["new_files"], r["hours_with_files"]) == (1, 1, [12])
    assert r["missing_hour_dirs"] == [23] and len(r["empty_hours"]) == 22
    assert r["complete"] is True and not r["errors"]
    assert not any(u.endswith(OTHER) for u in fc.urls)  # French file never downloaded
    rec = json.loads((tmp_path / "manifest.jsonl").read_text())
    stored = tmp_path / rec["file"]
    assert gzip.decompress(stored.read_bytes()) == XML
    assert rec["source_url"].endswith(NAME) and rec["retrieved_at"]
    assert not list(tmp_path.rglob("*.part"))


def test_today_is_not_complete_and_known_files_are_skipped(tmp_path):
    d = date(2026, 11, 12)
    fc = FakeClient(_pages(d))
    r = dm.archive_day(d, fc, tmp_path, {NAME}, datetime(2026, 11, 12, 13, tzinfo=UTC))
    assert r["complete"] is False and r["new_files"] == 0 and r["files"] == 1
    assert fc.requests == 24  # listings only, no download


def test_wrong_site_is_rejected_not_stored(tmp_path):
    d = date(2026, 11, 11)
    pages = _pages(d)
    pages[next(k for k in pages if k.endswith(NAME))] = XML.replace(
        b"s0000635", b"s0000001"
    )
    r = dm.archive_day(
        d, FakeClient(pages), tmp_path, set(), datetime(2026, 11, 12, tzinfo=UTC)
    )
    assert r["new_files"] == 0 and r["errors"] and r["complete"] is False
    assert not (tmp_path / "manifest.jsonl").exists()


def test_run_skips_complete_days(tmp_path):
    d = date(2026, 11, 11)
    fc = FakeClient(_pages(d))
    dm.run(d, d, tmp_path, fc)
    n = fc.requests
    dm.run(d, d, tmp_path, fc)
    assert fc.requests == n  # complete day not listed again
    days = json.loads((tmp_path / "days.json").read_text())
    assert days["2026-11-11"]["complete"] is True
