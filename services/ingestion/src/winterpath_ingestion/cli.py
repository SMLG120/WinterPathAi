"""`wp-ingest <pipeline>` entry point."""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date

from .config import get_settings

# canonical wp.source ids accepted by `load --source` (kept in sync with db_load.SOURCE_LOADERS;
# listed here so `--help` needs no heavy imports)
SOURCE_IDS = ["osm", "mtl-voirie", "mtl-entraves", "mtl-311", "eccc-geomet"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wp-ingest")
    ap.add_argument(
        "pipeline",
        choices=[
            "osm",
            "fixture",
            "voirie",
            "entraves",
            "311",
            "eccc",
            "all",
            "load",
            "boundaries",
            "osm-island",
        ],
    )
    ap.add_argument("--refresh", action="store_true", help="re-download raw inputs")
    ap.add_argument("--force", action="store_true", help="rebuild even if checksum unchanged")
    ap.add_argument(
        "--weather-since",
        type=date.fromisoformat,
        metavar="YYYY-MM-DD",
        help="load only: bound wp.weather_obs to observed_at >= this local (America/Montreal) "
        "date; older rows are skipped and pruned (e.g. for the hosted DB)",
    )
    ap.add_argument(
        "--source",
        action="append",
        choices=SOURCE_IDS,
        # no metavar: usage then shows the choice list as one unbreakable token, so
        # `wp-ingest load --help | grep eccc-geomet` works at any terminal width
        help="load only: load just this canonical source id (repeatable), with the same "
        "per-source transaction, staging and checksum no-op as a full load",
    )
    ap.add_argument(
        "--osm-graph",
        choices=["pilot", "island"],
        default="pilot",
        help="load only: which processed OSM graph the `osm` source loads (default pilot; "
        "island = data/processed/osm_island, for the local wp_island DB)",
    )
    args = ap.parse_args(argv)
    if args.weather_since is not None and args.pipeline != "load":
        ap.error("--weather-since only applies to `load`")
    if args.source and args.pipeline != "load":
        ap.error("--source only applies to `load`")
    if args.osm_graph != "pilot" and args.pipeline != "load":
        ap.error("--osm-graph only applies to `load`")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    s = get_settings()
    if args.pipeline == "load":
        from .db_load import LOADERS, SOURCE_LOADERS, load

        which = (
            list(dict.fromkeys(SOURCE_LOADERS[x] for x in args.source))
            if args.source
            else list(LOADERS)
        )
        for r in load(
            s,
            which,
            force=args.force,
            weather_since=args.weather_since,
            osm_graph=args.osm_graph,
        ):
            print(json.dumps(r, default=str))
        return 0

    steps = (
        ["osm", "voirie", "fixture", "entraves", "311", "eccc"]
        if args.pipeline == "all"
        else [args.pipeline]
    )
    for step in steps:
        if step == "osm":
            from .osm.pipeline import run
        elif step == "fixture":
            from .fixture import run
        elif step == "voirie":
            from .sources.voirie import run
        elif step == "entraves":
            from .sources.entraves import run
        elif step == "311":
            from .sources.r311 import run
        elif step == "boundaries":
            from .sources.boundaries import run
        elif step == "osm-island":
            from .osm.island import run
        else:
            from .sources.eccc import run
        r = run(s, refresh=args.refresh, force=args.force)
        summary = {k: r.manifest.get(k) for k in ("input_checksum", "ingest_run_id")}
        summary["stats"] = r.manifest.get("stats")
        print(
            json.dumps(
                {"pipeline": step, "noop": r.noop, "out": str(r.out_dir), **summary},
                indent=2,
                default=str,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
