"""Build the static search index.

    uv run python -m winterpath_ingestion.search_index \
        --rqa  ../../../winterpath-data/data/raw/addresses/RQA_CSV.zip \
        --osm  ../../../winterpath-data/data/raw/osm/geofabrik/quebec-261110.osm.pbf \
        --out  ../../apps/web/public/search \
        --report /tmp/search-index-report.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import time
from pathlib import Path

from .build import OSM_SOURCE, RQA_SOURCE, build_index
from .osm_places import read_places
from .rqa import read_rqa

log = logging.getLogger("search_index")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def osm_snapshot(pbf: Path) -> str:
    import osmium

    r = osmium.io.Reader(str(pbf), osmium.osm.osm_entity_bits.NOTHING)
    try:
        return r.header().get("osmosis_replication_timestamp") or ""
    finally:
        r.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="search_index", description=__doc__)
    ap.add_argument("--rqa", type=Path, required=True, help="RQA_CSV.zip (or an extracted RQA CSV)")
    ap.add_argument("--osm", type=Path, required=True, help="Geofabrik Québec .osm.pbf")
    ap.add_argument("--out", type=Path, required=True, help="output dir, must be named 'search'")
    ap.add_argument("--report", type=Path, help="optional build report JSON (timings, sizes)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    t0 = time.monotonic()
    streets, rstats = read_rqa(a.rqa)
    t_rqa = time.monotonic() - t0
    log.info("rqa: %d streets, %s (%.0fs)", len(streets), rstats, t_rqa)
    t1 = time.monotonic()
    places, pstats = read_places(a.osm)
    t_osm = time.monotonic() - t1
    log.info("osm: %d places, %s (%.0fs)", len(places), pstats, t_osm)

    rqa_src = RQA_SOURCE | {
        "version": rstats.version,
        "input_file": a.rqa.name,
        "input_sha256": sha256_file(a.rqa),
    }
    osm_src = OSM_SOURCE | {
        "version": osm_snapshot(a.osm),
        "input_file": a.osm.name,
        "input_sha256": sha256_file(a.osm),
    }
    t2 = time.monotonic()
    res = build_index(streets, places, a.out, [rqa_src, osm_src])
    t_write = time.monotonic() - t2
    total = time.monotonic() - t0
    log.info(
        "index %s: %d files, %.1f MB raw, %.1f MB gzip, %.0fs total",
        res.build_id,
        len(res.files) + 1,
        res.raw_bytes / 1e6,
        res.gzip_bytes / 1e6,
        total,
    )
    if a.report:
        biggest = max(res.files, key=lambda p: (a.out / "v" / res.build_id / p).stat().st_size)
        report = {
            "built_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "build_id": res.build_id,
            "seconds": {
                "rqa": round(t_rqa),
                "osm": round(t_osm),
                "write": round(t_write),
                "total": round(total),
            },
            "files": len(res.files) + 1,
            "raw_bytes": res.raw_bytes,
            "gzip_bytes": res.gzip_bytes,
            "largest_file": [biggest, (a.out / "v" / res.build_id / biggest).stat().st_size],
            "rqa": vars(rstats),
            "osm": pstats,
            "counts": res.counts,
            "per_municipality": res.per_municipality,
        }
        a.report.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
