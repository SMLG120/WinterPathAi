"""Pedestrian graph for a named region: the Island of Montréal, or the island plus neighbouring
municipalities (Greater Montréal, staged). Local build only.

The island is one region definition (:data:`ISLAND`). Under graph policy ``v1.6.0`` its output was
byte-identical to the Wave 1 build (proof in ``docs/GREATER_MONTREAL_COVERAGE.md``); the seasonal
rule (``v1.6.0+seasonal-v1``, contract v1.9.0) changes the island graph too: 7 seasonal ways and the
ways reachable only through them are excluded, so the island must be rebuilt and revalidated.
Graph rules are exactly the pilot's (:func:`graph.build_graph`): same inclusion policy, splitting
and stable IDs; two edges connect only where OSM ways share a node; near-misses are reported,
never repaired.

Area rule (deterministic):

* **Island** — see :mod:`.island`: clip to agglomeration land (Ville de Montréal archipel), keep
  components with a node on the main island.
* **Greater regions** — clip area = agglomeration land ∪ agglomeration administrative limits
  (they extend into the rivers) ∪ the MRC de Montréal unorganised water/islet territories ∪ the
  selected municipalities' official limits (Québec SDA, which also extend to mid-river). A way is
  kept whole if any part of it intersects that area, so a bridge deck over the river is kept and
  so is its far end. Component rule: keep a component if it has a node on the main island or
  inside one of the selected municipalities. A municipality network that no foot-legal way links
  to the island therefore stays in the graph as a separate component and is *reported*; it is not
  routable from the island (the API routes on the largest component only).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely

from ..config import Settings
from ..runs import RunResult, read_manifest, run_atomic
from ..sources import boundaries, sda
from . import geofabrik
from .graph import build_graph
from .island import (
    ISLAND_VERSION,
    OUT_NAME,
    component_report,
    filter_to_main_island,
    label_nodes,
    per_unit,
)
from .pipeline import GRAPH_POLICY, write_geojson

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegionSpec:
    key: str  # CLI name
    out_name: str  # data/processed/<out_name>
    region: str  # manifest "region"
    version: str  # build-rule version (part of the run checksum)
    title: str
    municipalities: tuple[str, ...] = ()  # Québec SDA codes (MUS_CO_GEO) beyond the agglomeration


ISLAND = RegionSpec("island", OUT_NAME, "montreal_island", ISLAND_VERSION, "Island of Montréal")
STAGE1 = RegionSpec(
    "stage1",
    "osm_greater_stage1",
    "greater_montreal_stage1",
    "1",
    "Island of Montréal, Laval and Longueuil",
    ("65005", "58227"),
)
#: Stage 1 without Longueuil: Longueuil's only foot link to the island is a way OSM tags
#: seasonal=spring;summer;fall (docs/GREATER_MONTREAL_COVERAGE.md), so this is the winter candidate.
STAGE1_LAVAL = RegionSpec(
    "stage1-laval",
    "osm_greater_stage1_laval",
    "greater_montreal_stage1_laval",
    "1",
    "Island of Montréal and Laval",
    ("65005",),
)
STAGE2 = RegionSpec(
    "stage2",
    "osm_greater_stage2",
    "greater_montreal_stage2",
    "1",
    "Island of Montréal, Laval, Longueuil, Terrebonne, Repentigny, Brossard, Boucherville and "
    "Saint-Lambert",
    ("65005", "58227", "64008", "60013", "58007", "58033", "58012"),
)
REGIONS = {r.key: r for r in (ISLAND, STAGE1, STAGE1_LAVAL, STAGE2)}
SDA_UNIT_TYPE = "Municipalité (SDA)"


def pinned_pbf_url(settings: Settings) -> str | None:
    """Same Geofabrik extract as the pilot graph (osm_pilot manifest provenance), so every region
    and the pilot share one OSM snapshot and the cached PBF is reused. None → resolve latest."""
    m = read_manifest(settings.processed_dir / "osm_pilot")
    return ((m or {}).get("provenance") or {}).get("url")


@dataclass
class _Areas:
    islands: gpd.GeoDataFrame
    limits: gpd.GeoDataFrame  # units for per_unit (NOM, TYPE)
    clip: object  # shapely geometry
    anchor: object  # shapely geometry
    key_parts: str  # extra inputs of the clip key / run checksum ("" for the island)
    provenance: dict


def _areas(settings: Settings, spec: RegionSpec, refresh: bool) -> _Areas:
    bdir = settings.processed_dir / "boundaries"
    islands = gpd.read_file(bdir / "islands.geojson")
    limits = gpd.read_file(bdir / "admin_limits.geojson")
    main_geom = islands.loc[islands["is_main_island"].astype(bool)].geometry.iloc[0]
    land = islands.geometry.union_all()
    if not spec.municipalities:
        return _Areas(islands, limits, land, main_geom, "", {})

    sda.run(settings, refresh=refresh)
    sm = read_manifest(sda.path_of(settings))
    munis = sda.load_municipalities(settings, spec.municipalities)
    water = sda.load_mrc_montreal_water(settings)
    clip = shapely.union_all(
        [land, limits.geometry.union_all(), water.geometry.union_all(), munis.geometry.union_all()]
    )
    anchor = shapely.union_all([main_geom, munis.geometry.union_all()])
    units = pd.concat(
        [
            limits[["NOM", "TYPE", "geometry"]],
            gpd.GeoDataFrame(
                {"NOM": munis["name"], "TYPE": SDA_UNIT_TYPE},
                geometry=munis.geometry.values,
                crs="EPSG:4326",
            ),
        ],
        ignore_index=True,
    )
    units = gpd.GeoDataFrame(units, geometry="geometry", crs="EPSG:4326")
    key_parts = f"|sda:{sm['input_checksum']}|munis:{','.join(spec.municipalities)}"
    prov = {
        "municipal_limits": {
            "dataset": sda.DATASET,
            "attribution": sda.ATTRIBUTION,
            "license": sda.LICENSE,
            "gpkg_sha256": sm["raw"]["gpkg_sha256"],
            "municipalities": [
                {"code": c, "name": n} for c, n in zip(munis["code"], munis["name"], strict=True)
            ],
        }
    }
    return _Areas(islands, units, clip, anchor, key_parts, prov)


def run_keys(spec: RegionSpec, pbf_sha256: str, boundaries_checksum: str, key_parts: str):
    """(clip cache file name, run checksum). For the island these are the Wave 1 strings
    verbatim (``clip_island_<key>.json``; checksum over pbf|boundaries|clip|policy|island-v1), so
    the cached clip and the no-op check keep working and the output does not move."""
    tag = f"{spec.key}-v{spec.version}"
    head = f"{pbf_sha256}|{boundaries_checksum}{key_parts}"
    key = hashlib.sha256(f"{head}|{tag}|clip-v{geofabrik.CLIP_VERSION}".encode()).hexdigest()
    clip_name = f"clip_{spec.key}_{key[:16]}.json"
    checksum = hashlib.sha256(f"{head}|{clip_name}|{GRAPH_POLICY}|{tag}".encode()).hexdigest()
    return clip_name, checksum


def run_region(
    settings: Settings, spec: RegionSpec, *, refresh: bool = False, force: bool = False
) -> RunResult:
    t0 = time.perf_counter()
    timings: dict[str, float] = {}

    def lap(name: str, since: float) -> float:
        now = time.perf_counter()
        timings[name] = round(now - since, 1)
        return now

    boundaries.run(settings, refresh=refresh)
    bm = read_manifest(settings.processed_dir / "boundaries")
    pbf = geofabrik.fetch(
        settings.raw_dir, settings.user_agent, refresh=refresh, url=pinned_pbf_url(settings)
    )
    areas = _areas(settings, spec, refresh)
    t = lap("fetch_and_boundaries_s", t0)

    clip_name, checksum = run_keys(spec, pbf.sha256, bm["input_checksum"], areas.key_parts)
    clip_path = pbf.path.parent / clip_name
    greater = bool(spec.municipalities)

    def build(staging: Path, run_id: str) -> dict:
        nonlocal t
        timings["clip_cached"] = clip_path.exists() and not refresh
        if timings["clip_cached"]:
            osm = json.loads(clip_path.read_text())
        else:
            log.info("clipping %s to the %s area (two streaming passes)", pbf.path.name, spec.key)
            osm = geofabrik.clip_area(pbf.path, areas.clip, pbf.replication_timestamp)
            tmp = clip_path.with_name(clip_path.name + ".part")
            tmp.write_text(json.dumps(osm, separators=(",", ":")))
            tmp.replace(clip_path)
        t = lap("clip_s", t)
        osm_f, fstats = filter_to_main_island(osm, areas.anchor)
        t = lap("component_filter_s", t)
        res = build_graph(osm_f, snapshot=pbf.replication_timestamp, ingest_run_id=run_id)
        t = lap("build_graph_s", t)
        nodes = label_nodes(res.nodes, areas.islands)
        comp_main = nodes.groupby("component_id")["land"].apply(
            lambda s: (s == "main_island").any()
        )
        edges = res.edges
        t = lap("label_s", t)
        units = per_unit(edges, nodes, areas.limits, with_largest=greater)
        comps = component_report(edges, nodes, areas.limits)
        t = lap("report_s", t)
        write_geojson(edges, staging / "edges.geojson")
        write_geojson(nodes, staging / "nodes.geojson")
        (staging / "gaps.json").write_text(json.dumps(res.gaps, indent=1))
        t = lap("write_s", t)
        timings["total_s"] = round(time.perf_counter() - t0, 1)
        lands = Counter(nodes["land"])
        other = Counter(nodes.loc[nodes["land"] == "other_island", "island_id"])
        stats = {
            **res.stats,
            "clip": osm["clip_stats"],
            "component_filter": fstats,
            "components_without_main_island_node_after_build": int((~comp_main).sum()),
            "network_km_undirected": round(res.stats["total_length_m_undirected"] / 1000, 1),
            "nodes_by_land": dict(lands),
            "nodes_by_other_island": dict(other.most_common()),
            "per_unit": units,
            "component_report": comps,
            "timings_s": timings,
        }
        (staging / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False))
        area_rule = (
            "osm.island module docstring (clip to agglomeration land; keep "
            "components with a main-island node)"
            if not greater
            else "osm.region module docstring (clip to agglomeration land and limits, MRC de "
            "Montréal water, selected municipal limits; keep components with a node on the main "
            "island or in a selected municipality)"
        )
        manifest = {
            "source_id": "osm",
            "region": spec.region,
            "osm_snapshot": pbf.replication_timestamp,
            "raw_file": pbf.path.name,
            "raw_sha256": pbf.sha256,
            "boundaries_checksum": bm["input_checksum"],
            "graph_policy": GRAPH_POLICY,
            "provenance": {
                **pbf.provenance(),
                "area_rule": area_rule,
                "clip": osm["clip_stats"],
                **areas.provenance,
            },
            "stats": stats,
        }
        if greater:
            manifest["title"] = spec.title
            manifest["municipalities"] = list(spec.municipalities)
        return manifest

    return run_atomic(spec.out_name, settings.processed_dir, checksum, build, force=force)
