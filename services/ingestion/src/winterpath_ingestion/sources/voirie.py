"""Ville de Montréal Voirie sidewalk (trottoir) and island (îlot) polygons → edge enrichment.

Licence: CC BY 4.0 (CKAN `voirie-trottoir-ilot`, license_id=cc-by, verified 2026-11-10).
Publisher warning: polygons are "not necessarily up to date across the whole territory".

Enrichment only: polygons NEVER create or remove graph connectivity. Match rule (documented,
deterministic): an edge is matched to a polygon when the part of the edge lying inside the
polygon buffered by MATCH_TOLERANCE_M (EPSG:32188) is ≥ MIN_OVERLAP_SHARE of the edge length.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

from ..config import METRIC_CRS, PILOT_BBOX, Settings
from ..http import download
from ..osm.pipeline import read_geojson, write_geojson
from ..runs import RunResult, read_manifest, run_atomic

SOURCE_ID = "mtl-voirie"
DATASET = "https://donnees.montreal.ca/dataset/voirie-trottoir-ilot"
_B = "https://donnees.montreal.ca/dataset/cbea9e7b-9808-42b3-ac05-7d4313a65f98/resource/"
RESOURCES = {
    "trottoir": (
        _B + "594c8dc3-ccd7-48d9-bc38-c5518a0d16ad/download/voi_trottoir_s_t12_geojson.zip",
        "VOI_TROTTOIR_S_T12_GeoJSON.json",
    ),
    "ilot": (
        _B + "a4596f85-07b8-4811-95fc-6db622319d10/download/voi_ilot_s_m12_geojson.zip",
        "VOI_ILOT_S_M12_GeoJSON.json",
    ),
}
MATCH_TOLERANCE_M = 1.0
MIN_OVERLAP_SHARE = 0.5

FIELDS = {
    "trottoir": (
        "ID_VOI_TROTTOIR",
        "CATEGORIETROTTOIR_REF",
        "TYPETROTTOIR_REF",
        "MATERIAUTROTTOIR_REF",
    ),
    "ilot": ("ID_VOI_ILOT", None, "TYPEILOT_REF", "MATERIAUILOT_REF"),
}


def normalise(raw: gpd.GeoDataFrame, layer: str) -> gpd.GeoDataFrame:
    id_col, cat_col, type_col, mat_col = FIELDS[layer]
    if raw.crs is None:
        raise ValueError("Voirie layer without CRS — refusing to guess")
    gdf = raw.to_crs("EPSG:4326")
    geom = gdf.geometry.make_valid()
    geom = geom.map(_to_multipolygon)
    attrs_cols = [c for c in gdf.columns if c not in ("geometry", id_col)]
    out = gpd.GeoDataFrame(
        {
            "polygon_id": [f"{layer}:{int(v)}" for v in gdf[id_col]],
            "layer": layer,
            "category": gdf[cat_col] if cat_col else "Îlot",
            "type": gdf[type_col],
            "material": gdf[mat_col],
            "surveyed_at": None,  # no survey date published; DATE_VERSION is the dataset version
            "attrs": [
                {c: _jsonable(r[c]) for c in attrs_cols} for _, r in gdf[attrs_cols].iterrows()
            ],
            "source_id": SOURCE_ID,
        },
        geometry=geom.values,
        crs="EPSG:4326",
    )
    out = out[~out.geometry.is_empty & out.geometry.notna()]
    return out.sort_values("polygon_id").reset_index(drop=True)


def _to_multipolygon(g):
    from shapely.geometry import MultiPolygon

    if g is None:
        return None
    if g.geom_type == "Polygon":
        return MultiPolygon([g])
    if g.geom_type == "MultiPolygon":
        return g
    polys = [p for p in getattr(g, "geoms", []) if p.geom_type in ("Polygon", "MultiPolygon")]
    flat = []
    for p in polys:
        flat.extend(p.geoms if p.geom_type == "MultiPolygon" else [p])
    return MultiPolygon(flat) if flat else None


def _jsonable(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if hasattr(v, "item"):
        return v.item()
    return v if isinstance(v, (int, float, str, bool)) else str(v)


def match_edges(edges: gpd.GeoDataFrame, polys: gpd.GeoDataFrame) -> dict[str, list[str]]:
    """edge_id → sorted polygon_ids. Pure spatial overlap; no topology change."""
    em = edges[["edge_id", "geometry"]].to_crs(METRIC_CRS)
    pm = polys[["polygon_id", "geometry"]].to_crs(METRIC_CRS)
    pm = pm.assign(geometry=pm.geometry.buffer(MATCH_TOLERANCE_M))
    cand = gpd.sjoin(em, pm, predicate="intersects", how="inner")
    out: dict[str, list[str]] = {e: [] for e in edges["edge_id"]}
    pgeom = dict(zip(pm["polygon_id"], pm.geometry, strict=True))
    for r in cand.itertuples():
        line = r.geometry
        if line.length <= 0:
            continue
        share = line.intersection(pgeom[r.polygon_id]).length / line.length
        if share >= MIN_OVERLAP_SHARE:
            out[r.edge_id].append(r.polygon_id)
    return {k: sorted(set(v)) for k, v in out.items()}


def match_rates(edges: gpd.GeoDataFrame, mapping: dict[str, list[str]]) -> dict:
    kinds = Counter(edges["edge_kind"])
    matched = Counter(
        k for e, k in zip(edges["edge_id"], edges["edge_kind"], strict=True) if mapping.get(e)
    )
    return {
        k: {"edges": kinds[k], "matched": matched[k], "rate": round(matched[k] / kinds[k], 4)}
        for k in sorted(kinds)
    } | {
        "all": {
            "edges": len(edges),
            "matched": sum(matched.values()),
            "rate": round(sum(matched.values()) / max(len(edges), 1), 4),
        }
    }


def run(settings: Settings, *, refresh: bool = False, force: bool = False) -> RunResult:
    raws = {
        layer: download(
            url,
            settings.raw_dir / "voirie" / url.rsplit("/", 1)[1],
            user_agent=settings.user_agent,
            refresh=refresh,
        )
        for layer, (url, _) in RESOURCES.items()
    }
    osm = read_manifest(settings.processed_dir / "osm_pilot")
    if osm is None:
        raise RuntimeError("run `wp-ingest osm` first")
    checksum = hashlib.sha256(
        "|".join(
            [
                raws["trottoir"].sha256,
                raws["ilot"].sha256,
                osm["input_checksum"],
                str(MATCH_TOLERANCE_M),
                str(MIN_OVERLAP_SHARE),
            ]
        ).encode()
    ).hexdigest()

    def build(staging: Path, run_id: str) -> dict:
        frames = []
        counts = {}
        for layer, (_, member) in RESOURCES.items():
            path = f"/vsizip/{raws[layer].path}/{member}"
            raw = pyogrio.read_dataframe(path, bbox=PILOT_BBOX)
            counts[layer] = len(raw)
            frames.append(normalise(raw, layer))
        polys = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
        polys["ingest_run_id"] = run_id
        write_geojson(polys, staging / "sidewalk_polygons.geojson")
        edges = read_geojson(settings.processed_dir / "osm_pilot" / "edges.geojson")
        mapping = match_edges(edges, polys)
        (staging / "edge_sidewalk_polygons.json").write_text(
            json.dumps(mapping, sort_keys=True, indent=0)
        )
        rates = match_rates(edges, mapping)
        return {
            "source_id": SOURCE_ID,
            "raw_sha256": {k: v.sha256 for k, v in raws.items()},
            "osm_input_checksum": osm["input_checksum"],
            "match_rule": {
                "tolerance_m": MATCH_TOLERANCE_M,
                "min_overlap_share": MIN_OVERLAP_SHARE,
                "crs": METRIC_CRS,
            },
            "stats": {
                "polygons_in_bbox": counts,
                "polygons_written": len(polys),
                "match_rates": rates,
            },
        }

    return run_atomic("voirie", settings.processed_dir, checksum, build, force=force)
