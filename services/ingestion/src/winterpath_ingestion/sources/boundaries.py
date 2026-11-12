"""Montréal agglomeration boundaries → main-island polygon, per-unit polygons, other islands.

Sources (both CC BY 4.0, Ville de Montréal, verified via CKAN package_show 2026-11-11):
- `limites-administratives-agglomeration` (WGS 84 GeoJSON): 19 arrondissements + 15 villes liées.
  Administrative limits extend into the river; they are clipped to land here.
- `archipel-agglomeration` (GPKG, EPSG:2950, photogrammetry 2020): ONE MultiPolygon of land.
  Each part is one island; the largest part is the main island (Île de Montréal).

Islands are identified only by geometry and by the administrative units they intersect. No island
name is invented: other islands are reported with their area, centroid and the units they fall in.
Laval and Longueuil are outside both datasets and are therefore never labelled island.
"""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import shapely

from ..config import METRIC_CRS, Settings
from ..http import download
from ..runs import RunResult, run_atomic

SOURCE_ID = "mtl-limites-archipel"  # local QA products only; not a wp.source row (no contract)
_L = "https://donnees.montreal.ca/dataset/9797a946-9da8-41ec-8815-f6b276dec7e9/resource/"
_A = "https://donnees.montreal.ca/dataset/7c4ffd4b-8473-4874-87b0-ca265ce36e3a/resource/"
LIMITS_URL = (
    _L
    + "e18bfd07-edc8-4ce8-8a5a-3b617662a794/download/limites-administratives-agglomeration.geojson"
)
ARCHIPEL_URL = _A + "f0b26281-bc3c-4851-b2c9-607a6546ca50/download/carto_dra_archipel.gpkg"
DATASETS = {
    "limits": "https://donnees.montreal.ca/dataset/limites-administratives-agglomeration",
    "archipel": "https://donnees.montreal.ca/dataset/archipel-agglomeration",
}
ATTRIBUTION = "Ville de Montréal — Limites administratives; Archipel de l'agglomération (CC BY 4.0)"
BUILD_VERSION = "1"


def fetch(settings: Settings, *, refresh: bool = False) -> dict:
    d = settings.raw_dir / "boundaries"
    out = {}
    for key, url in (("limits", LIMITS_URL), ("archipel", ARCHIPEL_URL)):
        r = download(
            url, d / url.rsplit("/", 1)[1], user_agent=settings.user_agent, refresh=refresh
        )
        out[key] = {"url": url, "file": r.path.name, "sha256": r.sha256, "fetched_at": r.fetched_at}
        out[key]["path"] = r.path
    return out


def islands_from_archipel(archipel: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Explode the archipel MultiPolygon into islands (EPSG:4326), largest first."""
    if archipel.crs is None:
        raise ValueError("archipel layer without CRS — refusing to guess")
    land = archipel.geometry.make_valid().union_all()
    parts = [p for p in shapely.get_parts(land) if p.geom_type == "Polygon" and p.area > 0]
    gdf = gpd.GeoDataFrame(geometry=parts, crs=archipel.crs)
    gdf["area_km2"] = gdf.to_crs(METRIC_CRS).area / 1e6
    gdf = gdf.sort_values("area_km2", ascending=False, ignore_index=True).to_crs("EPSG:4326")
    gdf["island_id"] = [f"isl-{i:04d}" for i in range(len(gdf))]
    gdf["is_main_island"] = gdf.index == 0
    return gdf


def build(limits: gpd.GeoDataFrame, archipel: gpd.GeoDataFrame) -> dict:
    """→ {main_island, islands, units, stats} (GeoDataFrames in EPSG:4326 + plain stats)."""
    if limits.crs is None:
        raise ValueError("limits layer without CRS — refusing to guess")
    limits = limits.to_crs("EPSG:4326")
    limits = limits.assign(geometry=limits.geometry.make_valid())
    islands = islands_from_archipel(archipel)
    main = islands.iloc[[0]][["island_id", "area_km2", "geometry"]].reset_index(drop=True)
    main_geom = main.geometry.iloc[0]
    other_geom = islands.iloc[1:].geometry.union_all() if len(islands) > 1 else None

    # islands → admin units they intersect (by area of overlap, metric)
    lm = limits.to_crs(METRIC_CRS)
    im = islands.to_crs(METRIC_CRS)
    hits = gpd.sjoin(
        im[["island_id", "geometry"]], lm[["NOM", "TYPE", "geometry"]], predicate="intersects"
    )
    units_of: dict[str, list[str]] = {}
    for iid, grp in hits.groupby("island_id"):
        units_of[iid] = sorted(grp["NOM"].unique())
    islands["admin_units"] = islands["island_id"].map(lambda i: units_of.get(i, []))
    cm = im.geometry.centroid.to_crs("EPSG:4326")
    islands["centroid_lon"] = cm.x.round(5)
    islands["centroid_lat"] = cm.y.round(5)

    # admin units clipped to the main island and to the other islands (separately flagged)
    rows = []
    for _, u in limits.iterrows():
        for part, geom in (("main_island", main_geom), ("other_islands", other_geom)):
            if geom is None:
                continue
            g = shapely.make_valid(shapely.intersection(u.geometry, geom))
            g = shapely.MultiPolygon(
                [p for p in shapely.get_parts(g) if p.geom_type == "Polygon" and p.area > 0]
            )
            if g.is_empty:
                continue
            rows.append(
                {
                    "unit_name": u["NOM"],
                    "unit_type": u["TYPE"],  # Arrondissement | Ville liée
                    "unit_code": u["CODEMAMH"],
                    "land": part,
                    "geometry": g,
                }
            )
    units = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    units["area_km2"] = units.to_crs(METRIC_CRS).area / 1e6

    unit_types = limits.groupby("TYPE")["NOM"].count().to_dict()
    stats = {
        "admin_units": int(len(limits)),
        "admin_units_by_type": {k: int(v) for k, v in unit_types.items()},
        "islands": int(len(islands)),
        "main_island_area_km2": round(float(main.area_km2.iloc[0]), 2),
        "other_islands_area_km2": round(float(islands.area_km2.iloc[1:].sum()), 2),
        "other_islands_ge_0_1_km2": [
            {
                "island_id": r.island_id,
                "area_km2": round(float(r.area_km2), 3),
                "admin_units": r.admin_units,
                "centroid": [r.centroid_lon, r.centroid_lat],
            }
            for r in islands.iloc[1:].itertuples()
            if r.area_km2 >= 0.1
        ],
        "units_on_main_island": sorted(units.loc[units.land == "main_island", "unit_name"]),
        "units_without_main_island_land": sorted(
            set(limits["NOM"]) - set(units.loc[units.land == "main_island", "unit_name"])
        ),
        "units_with_other_island_land": sorted(
            units.loc[units.land == "other_islands", "unit_name"]
        ),
    }
    return {
        "main_island": main,
        "islands": islands,
        "units": units,
        "limits": limits,
        "stats": stats,
    }


def _write(gdf: gpd.GeoDataFrame, path: Path) -> None:
    gdf.to_file(path, driver="GeoJSON", COORDINATE_PRECISION=7)


def run(settings: Settings, *, refresh: bool = False, force: bool = False) -> RunResult:
    raw = fetch(settings, refresh=refresh)
    checksum = f"{raw['limits']['sha256']}|{raw['archipel']['sha256']}|v{BUILD_VERSION}"

    def do_build(staging: Path, run_id: str) -> dict:
        limits = gpd.read_file(raw["limits"]["path"])
        archipel = gpd.read_file(raw["archipel"]["path"])
        res = build(limits, archipel)
        _write(res["main_island"], staging / "main_island.geojson")
        isl = res["islands"].copy()
        isl["admin_units"] = isl["admin_units"].map(json.dumps)
        _write(isl, staging / "islands.geojson")
        _write(res["units"], staging / "units_on_land.geojson")
        _write(res["limits"], staging / "admin_limits.geojson")
        (staging / "stats.json").write_text(json.dumps(res["stats"], indent=2, ensure_ascii=False))
        return {
            "source_id": SOURCE_ID,
            "datasets": DATASETS,
            "attribution": ATTRIBUTION,
            "license": "CC BY 4.0",
            "raw": {k: {kk: vv for kk, vv in v.items() if kk != "path"} for k, v in raw.items()},
            "stats": res["stats"],
        }

    return run_atomic("boundaries", settings.processed_dir, checksum, do_build, force=force)


def load_main_island(settings: Settings):
    p = settings.processed_dir / "boundaries" / "main_island.geojson"
    return gpd.read_file(p).geometry.iloc[0]


def load_land(settings: Settings):
    """All agglomeration land (every island) as one geometry, EPSG:4326."""
    p = settings.processed_dir / "boundaries" / "islands.geojson"
    return gpd.read_file(p).geometry.union_all()
