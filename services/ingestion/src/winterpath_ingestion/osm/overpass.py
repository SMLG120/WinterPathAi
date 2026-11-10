"""Overpass download for the pilot bbox (one query, cached in data/raw/osm/).

Policy (verified 2026-11-10, see agent report): overpass-api.de asks for < 10 000 queries and
< 1 GB per day (÷100 for regular use), an identifying User-Agent, no parallel scripts, a 30 s
pause after 429. Commercial use should move to a self-hosted Overpass or a Geofabrik extract.
A single cached query per snapshot is well inside those limits.
"""

from __future__ import annotations

from pathlib import Path

from ..http import RawFile, download

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Downloaded superset; inclusion is decided in Python (graph.INCLUDED_HIGHWAYS) so that excluded
# types can be counted and reported rather than silently missing.
DOWNLOAD_HIGHWAYS = (
    "footway|path|pedestrian|steps|living_street|residential|tertiary|secondary|primary"
    "|tertiary_link|secondary_link|primary_link|unclassified|service|cycleway|corridor|track"
)


def build_query(bbox: tuple[float, float, float, float], timeout: int = 180) -> str:
    w, s, e, n = bbox
    return (
        f"[out:json][timeout:{timeout}];"
        f'(way["highway"~"^({DOWNLOAD_HIGHWAYS})$"]({s},{w},{n},{e}););'
        "(._;>;);"
        "out body;"
    )


def fetch_pilot(
    raw_dir: Path, bbox: tuple[float, float, float, float], user_agent: str, refresh: bool = False
) -> RawFile:
    w, s, e, n = bbox
    dest = raw_dir / "osm" / f"overpass_{w}_{s}_{e}_{n}.json"
    return download(
        OVERPASS_URL,
        dest,
        user_agent=user_agent,
        method="POST",
        data={"data": build_query(bbox)},
        refresh=refresh,
    )
