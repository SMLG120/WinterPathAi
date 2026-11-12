"""Ad-hoc archive of issued Montréal City Page Weather XML (EN) from the MSC Datamart.

    uv run python -m winterpath_ml.weather_live.datamart_archive --start 2026-10-13
    uv run python -m winterpath_ml.weather_live.datamart_archive            # daily, by hand

Coordinator decision 2026-11-11: run a one-time backfill now, then once a day by hand until the
owner chooses long-term storage. No AMQP subscriber, no cloud storage, nothing committed but code.

Behaviour (ECCC usage policy):
- Sequential requests, at least MIN_INTERVAL_S apart (≤ 1 request/s); identifying User-Agent; no
  Cache-Control/Pragma headers; gentle retries (5 s, 15 s, 45 s) on timeouts and 5xx/429.
- Source: dated directories `https://dd.weather.gc.ca/{YYYYMMDD}/WXO-DD/citypage_weather/QC/{HH}/`
  (about 30 days retained). Only `*_MSC_CitypageWeather_s0000635_en.xml` is downloaded.
- Idempotent: files already archived are skipped. A UTC day whose 24 hour directories were all
  listed after the day ended is marked complete and is not listed again.
- Storage (git-ignored): `data/raw/eccc_citypage/s0000635/en/YYYY/MM/DD/<file>.xml.gz`, written via
  a .part file. `manifest.jsonl` has one line per file (URL, retrieved_at, sha256 of the XML and of
  the gzip, sizes). `days.json` has per-day status (files, hours with files, empty or missing hours).
- Each XML is parsed and must name site s0000635 ("Montréal") before it is stored; failures are
  recorded and not stored.

Data Source: Environment and Climate Change Canada (ECCC Data Server End-use Licence).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .. import config
from . import eccc

SITE = "s0000635"
LANG = "en"
DD = "https://dd.weather.gc.ca"
MIN_INTERVAL_S = 1.05
RETRY_WAITS_S = (5, 15, 45)
OUT = config.REPO_ROOT / "data" / "raw" / "eccc_citypage"
FILE_RE = re.compile(
    rf'href="(\d{{8}}T\d{{6}}\.\d+Z_MSC_CitypageWeather_{SITE}_{LANG}\.xml)"'
)


class Client:
    """Sequential HTTP GET with a minimum spacing between requests and gentle retries."""

    def __init__(
        self,
        min_interval: float = MIN_INTERVAL_S,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.min_interval, self._sleep, self._clock = min_interval, sleep, clock
        self._last = None
        self.requests = 0

    def get(self, url: str) -> bytes | None:
        """Body, or None on 404. Raises after the retries are exhausted."""
        for attempt in range(len(RETRY_WAITS_S) + 1):
            if self._last is not None:
                wait = self.min_interval - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()
            self.requests += 1
            req = urllib.request.Request(url, headers={"User-Agent": eccc.USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code not in (429, 500, 502, 503, 504) or attempt == len(
                    RETRY_WAITS_S
                ):
                    raise
                err = f"HTTP {e.code}"
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                if attempt == len(RETRY_WAITS_S):
                    raise
                err = f"{type(e).__name__}"
            print(
                f"  retry in {RETRY_WAITS_S[attempt]} s after {err}: {url}",
                file=sys.stderr,
            )
            self._sleep(RETRY_WAITS_S[attempt])
        raise AssertionError("unreachable")


def check_xml(body: bytes) -> None:
    root = ET.fromstring(body)
    loc = root.find("location/name")
    if loc is None or loc.get("code") != SITE:
        raise ValueError(
            f"location code {None if loc is None else loc.get('code')!r} != {SITE}"
        )


def _load_json(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default


def archive_day(
    d: date, client: Client, out: Path, known: set[str], now: datetime
) -> dict:
    ymd = d.strftime("%Y%m%d")
    day = {
        "date": str(d),
        "files": 0,
        "new_files": 0,
        "hours_with_files": [],
        "empty_hours": [],
        "missing_hour_dirs": [],
        "errors": [],
    }
    for hh in range(24):
        hdir = f"{DD}/{ymd}/WXO-DD/citypage_weather/QC/{hh:02d}/"
        listing = client.get(hdir)
        if listing is None:
            day["missing_hour_dirs"].append(hh)
            continue
        names = sorted(set(FILE_RE.findall(listing.decode("utf-8", "replace"))))
        if not names:
            day["empty_hours"].append(hh)
            continue
        day["hours_with_files"].append(hh)
        for name in names:
            day["files"] += 1
            if name in known:
                continue
            url = hdir + name
            body = client.get(url)
            at = datetime.now(UTC).replace(microsecond=0).isoformat()
            if body is None:
                day["errors"].append(f"{name}: 404 after listing")
                continue
            try:
                check_xml(body)
            except (ET.ParseError, ValueError) as e:
                day["errors"].append(f"{name}: {type(e).__name__}: {e}")
                continue
            dest = out / SITE / LANG / d.strftime("%Y/%m/%d") / (name + ".gz")
            dest.parent.mkdir(parents=True, exist_ok=True)
            gz = gzip.compress(body, compresslevel=9, mtime=0)
            part = dest.with_name(dest.name + ".part")
            part.write_bytes(gz)
            part.replace(dest)
            rec = {
                "file": str(dest.relative_to(out)),
                "source_url": url,
                "retrieved_at": at,
                "sha256_xml": hashlib.sha256(body).hexdigest(),
                "sha256_gz": hashlib.sha256(gz).hexdigest(),
                "bytes_xml": len(body),
                "bytes_gz": len(gz),
                "utc_hour_dir": hh,
                "attribution": "Data Source: Environment and Climate Change Canada",
            }
            with open(out / "manifest.jsonl", "a") as m:
                m.write(json.dumps(rec) + "\n")
            known.add(name)
            day["new_files"] += 1
    day["complete"] = now.date() > d and not day["errors"]
    day["listed_at"] = now.replace(microsecond=0).isoformat()
    return day


def run(start: date, end: date, out: Path = OUT, client: Client | None = None) -> dict:
    client = client or Client()
    out.mkdir(parents=True, exist_ok=True)
    known = (
        {
            Path(json.loads(line)["file"]).name.removesuffix(".gz")
            for line in (out / "manifest.jsonl").read_text().splitlines()
        }
        if (out / "manifest.jsonl").exists()
        else set()
    )
    days = _load_json(out / "days.json", {})
    d = start
    while d <= end:
        if days.get(str(d), {}).get("complete"):
            d += timedelta(days=1)
            continue
        now = datetime.now(UTC)
        print(f"{d}: listing 24 hour directories …", file=sys.stderr)
        days[str(d)] = archive_day(d, client, out, known, now)
        r = days[str(d)]
        print(
            f"{d}: {r['files']} files ({r['new_files']} new), hours with files {len(r['hours_with_files'])}/24,"
            f" empty {r['empty_hours']}, missing dirs {r['missing_hour_dirs']}, errors {len(r['errors'])},"
            f" complete={r['complete']}",
            file=sys.stderr,
        )
        tmp = out / "days.json.part"
        tmp.write_text(json.dumps(days, indent=1, sort_keys=True))
        tmp.replace(out / "days.json")
        d += timedelta(days=1)
    return {"days": days, "requests": client.requests}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    today = datetime.now(UTC).date()
    ap.add_argument(
        "--start", type=date.fromisoformat, default=today - timedelta(days=2)
    )
    ap.add_argument("--end", type=date.fromisoformat, default=today)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    t0 = time.monotonic()
    res = run(a.start, a.end, a.out)
    print(
        json.dumps(
            {"requests": res["requests"], "wall_s": round(time.monotonic() - t0)}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
