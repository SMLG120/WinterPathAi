"""Record real ECCC responses as labelled test fixtures.

    uv run python -m winterpath_ml.weather_live.record --out services/ml/tests/fixtures/eccc

Each response is saved byte-for-byte with a sidecar `<name>.meta.json`: source URL, retrieval time
(UTC), HTTP status, sha256, and the licence/attribution. Fixtures are recorded data, not synthetic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from . import eccc
from .model import ATTRIBUTION, LICENCE_URL

TARGETS = {
    "citypage_qc-147": eccc.citypage_url("qc-147"),
    "alerts_island_bbox": eccc.alerts_url(eccc.ISLAND_BBOX),
    # structure samples (not Montréal): a city page with warnings, and Canada-wide alerts
    "citypage_bc-98_with_warnings": eccc.citypage_url("bc-98"),
    "alerts_canada_sample": f"{eccc.BASE}/collections/weather-alerts/items?f=json&limit=5",
    "citypage_missing_item_404": eccc.citypage_url("qc-99999"),
}


def record(out: Path, names: list[str]) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    metas = []
    for name in names:
        url = TARGETS[name]
        at = datetime.now(UTC).replace(microsecond=0)
        req = urllib.request.Request(url, headers={"User-Agent": eccc.USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                status, body = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read()
        stamp = at.strftime("%Y%m%dT%H%M%SZ")
        f = out / f"{name}_{stamp}.json"
        f.write_bytes(body)
        meta = {
            "label": "RECORDED real response (not synthetic)",
            "source_url": url,
            "retrieved_at": at.isoformat(),
            "http_status": status,
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
            "attribution": ATTRIBUTION,
            "licence": f"ECCC Data Server End-use Licence ({LICENCE_URL})",
        }
        (out / f"{name}_{stamp}.meta.json").write_text(
            json.dumps(meta, indent=2) + "\n"
        )
        metas.append({"file": f.name, **meta})
    return metas


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", nargs="*", default=list(TARGETS))
    a = ap.parse_args(argv)
    for m in record(a.out, a.only):
        print(
            f"{m['file']}  HTTP {m['http_status']}  {m['bytes']} B  sha256 {m['sha256'][:12]}…  {m['retrieved_at']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
