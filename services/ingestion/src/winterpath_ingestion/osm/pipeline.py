"""OSM pilot graph pipeline: download (cached) → build → write processed outputs atomically."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import PILOT_BBOX, Settings
from ..runs import RunResult, run_atomic
from .graph import build_graph, load_overpass
from .overpass import fetch_pilot


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
    raw = fetch_pilot(settings.raw_dir, PILOT_BBOX, settings.user_agent, refresh=refresh)
    osm = load_overpass(raw.path)
    snapshot = osm.get("osm3s", {}).get("timestamp_osm_base")

    def build(staging: Path, run_id: str) -> dict:
        res = build_graph(osm, snapshot=snapshot, ingest_run_id=run_id)
        write_geojson(res.edges, staging / "edges.geojson")
        write_geojson(res.nodes, staging / "nodes.geojson")
        (staging / "gaps.json").write_text(json.dumps(res.gaps, indent=1))
        (staging / "stats.json").write_text(json.dumps(res.stats, indent=2))
        return {
            "source_id": "osm",
            "osm_snapshot": snapshot,
            "raw_file": raw.path.name,
            "raw_sha256": raw.sha256,
            "fetched_at": raw.fetched_at,
            "bbox": list(PILOT_BBOX),
            "stats": res.stats,
        }

    return run_atomic("osm_pilot", settings.processed_dir, raw.sha256, build, force=force)
