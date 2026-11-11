"""Geofabrik `quebec-latest.osm.pbf` → pilot-bbox clip (contract v1.5.0, user decision 2026-11-10).

The public Overpass instance is no longer used by the pipeline. Geofabrik states no quota;
OSM data is ODbL (attribution + share-alike on derived databases).

Download: `quebec-latest.osm.pbf` is a redirect to a dated file (e.g. `quebec-261108.osm.pbf`).
We resolve the redirect first and cache under the dated name, so a cached file can never be
mistaken for a newer extract. Integrity: the published `.md5` is checked; sha256 is recorded.
File date: the PBF header's `osmosis_replication_timestamp` (the OSM data timestamp), plus the
HTTP Last-Modified of the dated file.

Clip semantics replicate the previous Overpass query `way[highway~…](bbox); (._;>;);`:
a way is kept when any of its segments intersects the bbox (not only when a node lies inside),
and *all* of its nodes are kept, including those outside the bbox (complete ways). The result is
written in the same JSON shape Overpass returned, so `graph.build_graph` is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import requests
import shapely
from shapely.geometry import LineString

from ..http import DownloadError, download

log = logging.getLogger(__name__)

LATEST_URL = "https://download.geofabrik.de/north-america/canada/quebec-latest.osm.pbf"

# Downloaded superset; inclusion is decided in graph.py so excluded types are counted.
CLIP_HIGHWAYS = frozenset(
    "footway path pedestrian steps living_street residential tertiary secondary primary "
    "tertiary_link secondary_link primary_link unclassified service cycleway corridor track".split()
)
CLIP_VERSION = "1"  # bump when clip semantics change (part of the clip cache key)


@dataclass(frozen=True)
class PbfFile:
    path: Path
    url: str
    sha256: str
    md5: str
    last_modified: str | None
    replication_timestamp: str | None
    fetched_at: str
    from_cache: bool

    def provenance(self) -> dict:
        return {
            "provider": "geofabrik",
            "url": self.url,
            "file": self.path.name,
            "last_modified": self.last_modified,
            "osm_replication_timestamp": self.replication_timestamp,
            "md5": self.md5,
            "sha256": self.sha256,
            "fetched_at": self.fetched_at,
        }


def resolve_latest(user_agent: str, session: requests.Session | None = None) -> str:
    s = session or requests.Session()
    r = s.head(LATEST_URL, headers={"User-Agent": user_agent}, allow_redirects=False, timeout=60)
    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
        return requests.compat.urljoin(LATEST_URL, r.headers["Location"])
    if r.status_code == 200:
        return LATEST_URL
    raise DownloadError(f"HTTP {r.status_code} resolving {LATEST_URL}")


def md5_file(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pbf_header_timestamp(path: Path) -> str | None:
    import osmium

    r = osmium.io.Reader(str(path), osmium.osm.osm_entity_bits.NOTHING)
    try:
        return r.header().get("osmosis_replication_timestamp") or None
    finally:
        r.close()


def fetch(raw_dir: Path, user_agent: str, *, refresh: bool = False, url: str | None = None):
    """Download (or reuse) the dated Quebec PBF and verify it against Geofabrik's .md5."""
    if url is None:
        url = resolve_latest(user_agent)
    name = url.rsplit("/", 1)[-1]
    d = raw_dir / "osm" / "geofabrik"
    pbf = download(url, d / name, user_agent=user_agent, refresh=refresh, timeout=600)
    md5_raw = download(url + ".md5", d / (name + ".md5"), user_agent=user_agent, refresh=refresh)
    expected = md5_raw.path.read_text().split()[0].strip().lower()
    got = md5_file(pbf.path)
    if got != expected:
        raise DownloadError(f"MD5 mismatch for {name}: expected {expected}, got {got}")
    meta_p = pbf.path.with_name(pbf.path.name + ".meta.json")
    meta = json.loads(meta_p.read_text())
    if "last_modified" not in meta:
        h = requests.head(url, headers={"User-Agent": user_agent}, timeout=60)
        meta["last_modified"] = h.headers.get("Last-Modified")
        meta_p.write_text(json.dumps(meta))
    return PbfFile(
        path=pbf.path,
        url=url,
        sha256=pbf.sha256,
        md5=got,
        last_modified=meta.get("last_modified"),
        replication_timestamp=pbf_header_timestamp(pbf.path),
        fetched_at=pbf.fetched_at,
        from_cache=pbf.from_cache,
    )


def way_intersects_bbox(coords: list[tuple[float, float]], bbox) -> bool:
    """Overpass `(bbox)` semantics for ways: any segment intersects the box."""
    w, s, e, n = bbox
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    if max(xs) < w or min(xs) > e or max(ys) < s or min(ys) > n:
        return False
    if any(w <= x <= e and s <= y <= n for x, y in coords):
        return True
    if len(coords) < 2:
        return False
    return LineString(coords).intersects(shapely.box(w, s, e, n))


def clip(pbf_path: Path, bbox, snapshot: str | None) -> dict:
    """Two streaming passes over the PBF → Overpass-shaped dict for the bbox."""
    import osmium
    from osmium.filter import EntityFilter, IdFilter, KeyFilter

    ways = []
    needed: set[int] = set()
    missing_loc = 0
    fp = (
        osmium.FileProcessor(str(pbf_path))
        .with_locations("flex_mem")
        .with_filter(EntityFilter(osmium.osm.WAY))
        .with_filter(KeyFilter("highway"))
    )
    for w in fp:
        if w.tags.get("highway") not in CLIP_HIGHWAYS:
            continue
        coords = []
        for nr in w.nodes:
            try:
                coords.append((nr.location.lon, nr.location.lat))
            except osmium.InvalidLocationError:
                missing_loc += 1
        if not coords or not way_intersects_bbox(coords, bbox):
            continue
        ids = [nr.ref for nr in w.nodes]
        ways.append({"type": "way", "id": w.id, "nodes": ids, "tags": dict(w.tags)})
        needed.update(ids)

    nodes = []
    fp2 = osmium.FileProcessor(str(pbf_path), osmium.osm.NODE).with_filter(IdFilter(needed))
    for nd in fp2:
        e = {"type": "node", "id": nd.id, "lat": nd.location.lat, "lon": nd.location.lon}
        if len(nd.tags):
            e["tags"] = dict(nd.tags)
        nodes.append(e)
    nodes.sort(key=lambda e: e["id"])
    ways.sort(key=lambda e: e["id"])
    found = {e["id"] for e in nodes}
    return {
        "osm3s": {"timestamp_osm_base": snapshot},
        "generator": f"winterpath geofabrik clip v{CLIP_VERSION}",
        "clip_stats": {
            "ways": len(ways),
            "nodes": len(nodes),
            "nodes_missing": len(needed - found),
            "way_node_refs_without_location": missing_loc,
        },
        "elements": [*nodes, *ways],
    }


def clip_cached(pbf: PbfFile, bbox, *, refresh: bool = False) -> tuple[Path, dict]:
    """Clip once per (pbf sha256, bbox, clip version); cached next to the raw PBF."""
    key = hashlib.sha256(
        f"{pbf.sha256}|{','.join(map(str, bbox))}|v{CLIP_VERSION}".encode()
    ).hexdigest()[:16]
    out = pbf.path.parent / f"clip_{key}.json"
    if out.exists() and not refresh:
        return out, json.loads(out.read_text())
    log.info("clipping %s to %s (two streaming passes)", pbf.path.name, bbox)
    data = clip(pbf.path, bbox, pbf.replication_timestamp)
    tmp = out.with_name(out.name + ".part")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(out)
    return out, data
