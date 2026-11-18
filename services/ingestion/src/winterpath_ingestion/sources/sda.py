"""Québec municipal limits (SDA 1/20 000) for regions beyond the Island of Montréal.

Source: Gouvernement du Québec, Ministère des Ressources naturelles et des Forêts,
« Découpages administratifs » (Système sur les découpages administratifs, SDA, 1/20 000),
Données Québec dataset `decoupages-administratifs`, licence **CC BY 4.0** (verified via CKAN
``package_show`` 2026-11-16). File: ``SDA.gpkg.zip`` (GeoPackage, layer ``munic_s``,
EPSG:4269). Attribution: "Contient des données du Gouvernement du Québec (MRNF), Découpages
administratifs, CC BY 4.0".

Municipalities are selected by their official geographic code (``MUS_CO_GEO``), never by name
(two Québec municipalities are called Saint-Lambert). Municipal polygons extend into the rivers
to the municipal limit; they are service areas, not land. Nothing here creates connectivity.

Also kept: the two MRC de Montréal unorganised territories (``TNO aquatique`` / ``TNO terrestre
de la MRC géographique de Montréal``). They are river water and islets between the agglomeration
and its neighbours; a bridge deck over them belongs to no municipality.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import geopandas as gpd

from ..config import METRIC_CRS, Settings
from ..http import download, sha256_file
from ..runs import RunResult, run_atomic

SOURCE_ID = "qc-sda"  # local QA / build input only; not a wp.source row (no contract)
SDA_URL = (
    "https://diffusion.mern.gouv.qc.ca/diffusion/RGQ/Vectoriel/Theme/Local/SDA_20k/GPKG/"
    "SDA.gpkg.zip"
)
DATASET = "https://www.donneesquebec.ca/recherche/dataset/decoupages-administratifs"
ATTRIBUTION = "Gouvernement du Québec (MRNF) — Découpages administratifs (SDA 1/20 000), CC BY 4.0"
LICENSE = "CC BY 4.0"
LAYER = "munic_s"
BUILD_VERSION = "1"

#: MUS_CO_GEO → expected name (checked; a mismatch fails the build instead of guessing)
MUNICIPALITIES: dict[str, str] = {
    "65005": "Laval",
    "58227": "Longueuil",
    "64008": "Terrebonne",
    "60013": "Repentigny",
    "58007": "Brossard",
    "58033": "Boucherville",
    "58012": "Saint-Lambert",
}
MRC_MONTREAL_WATER = (
    "TNO aquatique de la MRC géographique de Montréal",
    "TNO terrestre de la MRC géographique de Montréal",
)


def fetch(settings: Settings, *, refresh: bool = False) -> dict:
    d = settings.raw_dir / "boundaries" / "quebec_sda"
    r = download(
        SDA_URL, d / "SDA.gpkg.zip", user_agent=settings.user_agent, refresh=refresh, timeout=600
    )
    gpkg = d / "SDA.gpkg"
    if refresh or not gpkg.exists():
        with zipfile.ZipFile(r.path) as zf:
            names = [n for n in zf.namelist() if n.endswith(".gpkg")]
            if names != ["SDA.gpkg"]:
                raise ValueError(f"unexpected SDA archive content: {zf.namelist()}")
            tmp = gpkg.with_name("SDA.gpkg.part")
            with zf.open("SDA.gpkg") as src, tmp.open("wb") as dst:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
            tmp.replace(gpkg)
    return {
        "url": SDA_URL,
        "zip_sha256": r.sha256,
        "gpkg_sha256": sha256_file(gpkg),
        "fetched_at": r.fetched_at,
        "path": gpkg,
    }


def select(munic: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """(municipalities by code, MRC-de-Montréal water/islets) in EPSG:4326, 2-D, valid."""
    if munic.crs is None:
        raise ValueError("SDA layer without CRS — refusing to guess")
    m = munic.to_crs("EPSG:4326")
    m = m.assign(geometry=m.geometry.force_2d().make_valid())
    sel = m[m["MUS_CO_GEO"].isin(MUNICIPALITIES)].copy()
    found = dict(zip(sel["MUS_CO_GEO"], sel["MUS_NM_MUN"], strict=True))
    if found != MUNICIPALITIES:
        raise ValueError(f"SDA municipalities differ from expected codes: {found}")
    sel = sel.sort_values("MUS_CO_GEO", ignore_index=True)
    out = gpd.GeoDataFrame(
        {
            "code": sel["MUS_CO_GEO"],
            "name": sel["MUS_NM_MUN"],
            "mrc": sel["MUS_NM_MRC"],
            "region": sel["MUS_NM_REG"],
            "sda_version": sel["MUS_CO_VER"],
        },
        geometry=sel.geometry.values,
        crs="EPSG:4326",
    )
    out["area_km2"] = (out.to_crs(METRIC_CRS).area / 1e6).round(3)
    w = m[m["MUS_NM_MUN"].isin(MRC_MONTREAL_WATER)].sort_values("MUS_CO_GEO", ignore_index=True)
    if sorted(w["MUS_NM_MUN"]) != sorted(MRC_MONTREAL_WATER):
        raise ValueError("SDA: MRC de Montréal unorganised territories not found")
    water = gpd.GeoDataFrame(
        {"code": w["MUS_CO_GEO"], "name": w["MUS_NM_MUN"]}, geometry=w.geometry.values, crs=4326
    )
    return out, water


def run(settings: Settings, *, refresh: bool = False, force: bool = False) -> RunResult:
    raw = fetch(settings, refresh=refresh)
    codes = ",".join(sorted(MUNICIPALITIES))
    checksum = f"{raw['gpkg_sha256']}|{codes}|v{BUILD_VERSION}"

    def do_build(staging: Path, run_id: str) -> dict:
        munic = gpd.read_file(raw["path"], layer=LAYER)
        out, water = select(munic)
        out.to_file(staging / "municipalities.geojson", driver="GeoJSON", COORDINATE_PRECISION=7)
        water.to_file(
            staging / "mrc_montreal_water.geojson", driver="GeoJSON", COORDINATE_PRECISION=7
        )
        stats = {
            "municipalities": [
                {k: r[k] for k in ("code", "name", "mrc", "region", "sda_version", "area_km2")}
                for r in out.drop(columns="geometry").to_dict("records")
            ],
            "mrc_montreal_water": list(water["name"]),
        }
        (staging / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False))
        return {
            "source_id": SOURCE_ID,
            "dataset": DATASET,
            "attribution": ATTRIBUTION,
            "license": LICENSE,
            "raw": {k: v for k, v in raw.items() if k != "path"},
            "stats": stats,
        }

    return run_atomic("boundaries_sda", settings.processed_dir, checksum, do_build, force=force)


def load_municipalities(settings: Settings, codes: tuple[str, ...]) -> gpd.GeoDataFrame:
    p = settings.processed_dir / "boundaries_sda" / "municipalities.geojson"
    g = gpd.read_file(p)
    g["code"] = g["code"].astype(str)
    sel = g[g["code"].isin(codes)].sort_values("code", ignore_index=True)
    if sorted(sel["code"]) != sorted(codes):
        raise ValueError(f"municipality codes missing from SDA product: {codes}")
    return sel


def load_mrc_montreal_water(settings: Settings) -> gpd.GeoDataFrame:
    return gpd.read_file(settings.processed_dir / "boundaries_sda" / "mrc_montreal_water.geojson")


def path_of(settings: Settings) -> Path:
    return settings.processed_dir / "boundaries_sda"
