"""OSM pilot graph pipeline: Geofabrik Quebec PBF (cached, MD5-verified) → bbox clip → build →
write processed outputs atomically. No public Overpass (contract v1.5.0)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..config import PILOT_BBOX, Settings
from ..runs import RunResult, run_atomic
from . import geofabrik
from .graph import CONDITIONAL_HIGHWAYS, INCLUDED_HIGHWAYS, build_graph

# Part of the run checksum: a policy change must rebuild even if the PBF is unchanged.
GRAPH_POLICY = (
    "v1.5.0:"
    + ",".join(sorted(INCLUDED_HIGHWAYS))
    + "|cond:"
    + ",".join(sorted(CONDITIONAL_HIGHWAYS))
)


def write_geojson(gdf, path: Path) -> None:
    """Deterministic GeoJSON: sorted keys, 7-decimal coords (≈1 cm), nested values kept."""
    feats = []
    for row in gdf.to_dict("records"):
        geom = row.pop("geometry")
        props = {k: _clean(v) for k, v in row.items()}
        fid = props.get("edge_id") or props.get("node_id")
        feats.append({"type": "Feature", "id": fid, "geometry": _geom(geom), "properties": props})
    path.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": feats}, sort_keys=True, ensure_ascii=False
        )
        + "\n",
        encoding="utf-8",
    )


def read_geojson(path: Path):
    """Inverse of write_geojson without type coercion (pyogrio would parse dates / stringify
    nested objects)."""
    import geopandas as gpd
    from shapely.geometry import shape

    fc = json.loads(path.read_text(encoding="utf-8"))
    rows = [{**f["properties"], "geometry": shape(f["geometry"])} for f in fc["features"]]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def _geom(g) -> dict:
    from shapely.geometry import mapping

    def rnd(c):
        if isinstance(c, (int, float)):
            return round(c, 7)
        return [rnd(x) for x in c]

    m = mapping(g)
    return {"type": m["type"], "coordinates": rnd(m["coordinates"])}


def _clean(v):
    import math

    if isinstance(v, float):
        return None if math.isnan(v) else round(v, 3)
    if hasattr(v, "item"):  # numpy scalar
        return _clean(v.item())
    return v


def run(settings: Settings, *, refresh: bool = False, force: bool = False) -> RunResult:
    pbf = geofabrik.fetch(settings.raw_dir, settings.user_agent, refresh=refresh)
    clip_path, osm = geofabrik.clip_cached(pbf, PILOT_BBOX, refresh=refresh)
    snapshot = pbf.replication_timestamp
    provenance = {**pbf.provenance(), "bbox": list(PILOT_BBOX), "clip": osm["clip_stats"]}
    checksum = hashlib.sha256(f"{pbf.sha256}|{clip_path.name}|{GRAPH_POLICY}".encode()).hexdigest()

    def build(staging: Path, run_id: str) -> dict:
        res = build_graph(osm, snapshot=snapshot, ingest_run_id=run_id)
        write_geojson(res.edges, staging / "edges.geojson")
        write_geojson(res.nodes, staging / "nodes.geojson")
        (staging / "gaps.json").write_text(json.dumps(res.gaps, indent=1))
        (staging / "stats.json").write_text(json.dumps(res.stats, indent=2))
        return {
            "source_id": "osm",
            "osm_snapshot": snapshot,
            "raw_file": pbf.path.name,
            "raw_sha256": pbf.sha256,
            "fetched_at": pbf.fetched_at,
            "bbox": list(PILOT_BBOX),
            "graph_policy": GRAPH_POLICY,
            "provenance": provenance,
            "stats": res.stats,
        }

    return run_atomic("osm_pilot", settings.processed_dir, checksum, build, force=force)
