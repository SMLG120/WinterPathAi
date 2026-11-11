"""Load processed pipeline outputs into PostGIS (`wp` schema, migration 0001).

Atomicity: each source loads inside ONE transaction — COPY into a temp staging table, upsert into
the target, delete target rows of that source that are no longer present, mark the ingest_run
succeeded. Any error rolls everything back and a separate transaction records a failed run, so
current data is never replaced by a failed load. Idempotent: if a succeeded ingest_run with the
same input_checksum exists for the source, the load is skipped.
"""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from .config import Settings
from .osm.pipeline import read_geojson
from .runs import read_manifest
from .sources.registry import SOURCES


def _v(x):
    """pandas/numpy → plain Python; NaN → None (never store 'NaN' for a missing value)."""
    if x is None:
        return None
    if hasattr(x, "item") and not isinstance(x, (list, dict, str)):
        x = x.item()
    if isinstance(x, float) and x != x:
        return None
    return x


def connect(url: str | None = None) -> psycopg.Connection:
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    # autocommit: each `conn.transaction()` block is then a real BEGIN/COMMIT, so one source's
    # load commits independently and a failed-run record survives the rollback of the load.
    return psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://"), autocommit=True)


def upsert_sources(conn: psycopg.Connection) -> None:
    cols = list(SOURCES[0].keys())
    sql = (
        f"INSERT INTO wp.source ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
        f"ON CONFLICT (source_id) DO UPDATE SET "
        + ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "source_id")
    )
    with conn.cursor() as cur:
        cur.executemany(sql, [[s[c] for c in cols] for s in SOURCES])


def _already_loaded(conn, source_id: str, checksum: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM wp.ingest_run WHERE source_id=%s AND input_checksum=%s "
        "AND status='succeeded' LIMIT 1",
        (source_id, checksum),
    ).fetchone()
    return row is not None


def _geom_sql(col: str, target: str) -> str:
    g = f"ST_SetSRID(ST_GeomFromText({col}), 4326)"
    if "MultiPolygon" in target:  # coordinate rounding can invalidate rings → repair
        g = f"ST_Multi(ST_CollectionExtract(ST_MakeValid({g}), 3))"
    return f"{g}::{target}"


def _stage_and_merge(
    cur,
    *,
    table: str,
    columns: list[str],
    types: dict[str, str],
    rows: Iterable[tuple],
    key: list[str],
    geom_cols: dict[str, str] | None = None,
    prune_where: str | None = None,
) -> int:
    """COPY rows into a temp table then upsert into wp.<table>. Geometry columns are given as
    WKT text and converted with ST_GeomFromText(...,4326)."""
    geom_cols = geom_cols or {}
    stage = f"stage_{table}"
    coldefs = ", ".join(f"{c} {'text' if c in geom_cols else types[c]}" for c in columns)
    cur.execute(f"CREATE TEMP TABLE {stage} ({coldefs}) ON COMMIT DROP")
    n = 0
    with cur.copy(f"COPY {stage} ({', '.join(columns)}) FROM STDIN") as cp:
        for r in rows:
            cp.write_row([_v(x) for x in r])
            n += 1
    select = ", ".join(_geom_sql(c, geom_cols[c]) if c in geom_cols else c for c in columns)
    updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in columns if c not in key)
    cur.execute(
        f"INSERT INTO wp.{table} ({', '.join(columns)}) SELECT {select} FROM {stage} "
        f"ON CONFLICT ({', '.join(key)}) DO UPDATE SET {updates}"
    )
    match = " AND ".join(f"s.{k} = t.{k}" for k in key)
    where = f" AND {prune_where}" if prune_where else ""
    cur.execute(
        f"DELETE FROM wp.{table} t WHERE NOT EXISTS (SELECT 1 FROM {stage} s WHERE {match}){where}"
    )
    return n


def _record_count(counts: dict) -> int:
    """Rows written; keys starting with `_` are diagnostics (e.g. rows skipped by a bound)."""
    return sum(v for k, v in counts.items() if not k.startswith("_"))


def _run_log(manifest: dict, counts: dict) -> dict:
    """ingest_run.log: counts plus the source's provenance (URL, file date, checksums) when the
    pipeline recorded it — e.g. Geofabrik for OSM (contract v1.5.0)."""
    out = {"counts": counts}
    if manifest.get("provenance"):
        out["provenance"] = manifest["provenance"]
    return out


def _load(conn, source_id: str, manifest: dict, fn, force: bool = False) -> dict:
    checksum = manifest["input_checksum"]
    if not force and _already_loaded(conn, source_id, checksum):
        return {"source_id": source_id, "noop": True}
    run_id = manifest["ingest_run_id"]
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO wp.ingest_run (ingest_run_id, source_id, status, input_checksum)"
                    " VALUES (%s, %s, 'running', %s) ON CONFLICT (ingest_run_id) DO UPDATE SET "
                    "status='running', started_at=now(), input_checksum=EXCLUDED.input_checksum",
                    (run_id, source_id, checksum),
                )
                counts = fn(cur, run_id)
                cur.execute(
                    "UPDATE wp.ingest_run SET status='succeeded', finished_at=now(), "
                    "record_count=%s, log=%s WHERE ingest_run_id=%s",
                    (_record_count(counts), Jsonb(_run_log(manifest, counts)), run_id),
                )
                cur.execute(
                    "UPDATE wp.source SET last_success_at=now(), status='active' "
                    "WHERE source_id=%s",
                    (source_id,),
                )
        return {"source_id": source_id, "noop": False, "counts": counts}
    except Exception as e:
        with conn.transaction():
            conn.execute(
                "INSERT INTO wp.ingest_run (ingest_run_id, source_id, status, input_checksum, "
                "finished_at, log) VALUES (gen_random_uuid(), %s, 'failed', %s, now(), %s)",
                (source_id, checksum, Jsonb({"error": type(e).__name__, "msg": str(e)[:500]})),
            )
        raise


# ------------------------------------------------------------------------------ per source
def _osm(settings: Settings):
    d = settings.processed_dir / "osm_pilot"
    m = read_manifest(d)
    voirie = settings.processed_dir / "voirie"
    vm = read_manifest(voirie)
    mapping = {}
    if vm and vm.get("osm_input_checksum") == m["input_checksum"]:
        mapping = json.loads((voirie / "edge_sidewalk_polygons.json").read_text())
        m = {**m, "input_checksum": m["input_checksum"] + "+" + vm["input_checksum"]}

    def fn(cur, run_id):
        nodes = read_geojson(d / "nodes.geojson")
        edges = read_geojson(d / "edges.geojson")
        node_cols = [
            "node_id",
            "geom",
            "osm_id",
            "kind",
            "crossing_type",
            "kerb",
            "source_id",
            "ingest_run_id",
        ]
        n_nodes = _stage_and_merge(
            cur,
            table="node",
            columns=node_cols,
            types={
                "node_id": "text",
                "osm_id": "bigint",
                "kind": "text",
                "crossing_type": "text",
                "kerb": "text",
                "source_id": "text",
                "ingest_run_id": "uuid",
            },
            rows=(
                (
                    r.node_id,
                    r.geometry.wkt,
                    r.osm_id,
                    r.kind,
                    r.crossing_type,
                    r.kerb,
                    "osm",
                    run_id,
                )
                for r in nodes.itertuples()
            ),
            key=["node_id"],
            geom_cols={"geom": "geometry(Point,4326)"},
            prune_where="t.source_id='osm' AND NOT EXISTS (SELECT 1 FROM wp.edge e WHERE "
            "e.from_node_id=t.node_id OR e.to_node_id=t.node_id)",
        )
        edge_cols = [
            "edge_id",
            "from_node_id",
            "to_node_id",
            "geom",
            "length_m",
            "edge_kind",
            "osm_way_id",
            "foot_access",
            "step_free",
            "incline_percent",
            "width_m",
            "surface",
            "lit",
            "name",
            "crossing_type",
            "crossing_kerb",
            "highway",
            "osm_snapshot",
            "sidewalk_polygon_ids",
            "connectivity_confidence",
            "component_id",
            "source_id",
            "ingest_run_id",
        ]
        types = {
            "edge_id": "text",
            "from_node_id": "text",
            "to_node_id": "text",
            "length_m": "double precision",
            "edge_kind": "text",
            "osm_way_id": "bigint",
            "foot_access": "text",
            "step_free": "boolean",
            "incline_percent": "double precision",
            "width_m": "double precision",
            "surface": "text",
            "lit": "boolean",
            "name": "text",
            "crossing_type": "text",
            "crossing_kerb": "text",
            "highway": "text",
            "osm_snapshot": "timestamptz",
            "sidewalk_polygon_ids": "text[]",
            "connectivity_confidence": "text",
            "component_id": "integer",
            "source_id": "text",
            "ingest_run_id": "uuid",
        }
        n_edges = _stage_and_merge(
            cur,
            table="edge",
            columns=edge_cols,
            types=types,
            rows=(
                (
                    r.edge_id,
                    r.from_node_id,
                    r.to_node_id,
                    r.geometry.wkt,
                    r.length_m,
                    r.edge_kind,
                    r.osm_way_id,
                    r.foot_access,
                    r.step_free,
                    r.incline_percent,
                    r.width_m,
                    r.surface,
                    r.lit,
                    getattr(r, "name", None),
                    _crossing(r.crossing, "type"),
                    _crossing(r.crossing, "kerb"),
                    r.highway,
                    r.osm_snapshot,
                    mapping.get(r.edge_id, []),
                    r.connectivity_confidence,
                    r.component_id,
                    "osm",
                    run_id,
                )
                for r in edges.itertuples()
            ),
            key=["edge_id"],
            geom_cols={"geom": "geometry(LineString,4326)"},
            prune_where="t.source_id='osm'",
        )
        # nodes orphaned by pruned edges
        cur.execute(
            "DELETE FROM wp.node t WHERE t.source_id='osm' AND NOT EXISTS (SELECT 1 FROM "
            "wp.edge e WHERE e.from_node_id=t.node_id OR e.to_node_id=t.node_id)"
        )
        return {"node": n_nodes, "edge": n_edges}

    return "osm", m, fn


def _crossing(c, key: str):
    """CrossingInfo dict → one field; non-crossing edges (None/NaN) → None."""
    return c.get(key) if isinstance(c, dict) else None


def _voirie(settings: Settings):
    d = settings.processed_dir / "voirie"
    m = read_manifest(d)

    def fn(cur, run_id):
        polys = read_geojson(d / "sidewalk_polygons.geojson")
        cols = [
            "polygon_id",
            "geom",
            "category",
            "type",
            "material",
            "surveyed_at",
            "attrs",
            "source_id",
            "ingest_run_id",
        ]
        n = _stage_and_merge(
            cur,
            table="sidewalk_polygon",
            columns=cols,
            types={
                "polygon_id": "text",
                "category": "text",
                "type": "text",
                "material": "text",
                "surveyed_at": "date",
                "attrs": "jsonb",
                "source_id": "text",
                "ingest_run_id": "uuid",
            },
            rows=(
                (
                    r.polygon_id,
                    r.geometry.wkt,
                    r.category,
                    r.type,
                    r.material,
                    None,
                    json.dumps(r.attrs, ensure_ascii=False),
                    "mtl-voirie",
                    run_id,
                )
                for r in polys.itertuples()
            ),
            key=["polygon_id"],
            geom_cols={"geom": "geometry(MultiPolygon,4326)"},
            prune_where="t.source_id='mtl-voirie'",
        )
        return {"sidewalk_polygon": n}

    return "mtl-voirie", m, fn


def _entraves(settings: Settings):
    d = settings.processed_dir / "entraves"
    m = read_manifest(d)

    def fn(cur, run_id):
        cl = read_geojson(d / "closures.geojson")
        cols = [
            "closure_id",
            "geom",
            "sidewalk_blockedtype",
            "blocks_passage",
            "backsidewalk_blocks_passage",
            "attrs",
            "valid_from",
            "valid_to",
            "status",
            "source_id",
            "ingest_run_id",
        ]
        n = _stage_and_merge(
            cur,
            table="closure",
            columns=cols,
            types={
                "closure_id": "text",
                "sidewalk_blockedtype": "text",
                "blocks_passage": "boolean",
                "backsidewalk_blocks_passage": "boolean",
                "attrs": "jsonb",
                "valid_from": "timestamptz",
                "valid_to": "timestamptz",
                "status": "text",
                "source_id": "text",
                "ingest_run_id": "uuid",
            },
            rows=(
                (
                    r.closure_id,
                    r.geometry.wkt,
                    r.sidewalk_blockedtype,
                    r.blocks_passage,
                    r.backsidewalk_blocks_passage,
                    json.dumps(r.attrs if isinstance(r.attrs, dict) else {}, ensure_ascii=False),
                    r.valid_from,
                    r.valid_to,
                    r.status,
                    "mtl-entraves",
                    run_id,
                )
                for r in cl.itertuples()
            ),
            key=["closure_id"],
            geom_cols={"geom": "geometry(Geometry,4326)"},
            prune_where="t.source_id='mtl-entraves'",
        )
        return {"closure": n}

    return "mtl-entraves", m, fn


def _csv_rows(path: Path, cols: list[str], run_id: str):
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            r["ingest_run_id"] = run_id
            yield tuple((r[c] if r[c] != "" else None) for c in cols)


def _r311(settings: Settings):
    d = settings.processed_dir / "report_311"
    m = read_manifest(d)

    def fn(cur, run_id):
        cols = ["h3", "day", "category", "nature", "n", "source_id", "ingest_run_id"]
        n = _stage_and_merge(
            cur,
            table="report_311_cell",
            columns=cols,
            types={
                "h3": "text",
                "day": "date",
                "category": "text",
                "nature": "text",
                "n": "integer",
                "source_id": "text",
                "ingest_run_id": "uuid",
            },
            rows=_csv_rows(d / "report_311_cell.csv", cols, run_id),
            key=["h3", "day", "category", "nature"],
        )
        return {"report_311_cell": n}

    return "mtl-311", m, fn


def _weather(settings: Settings, since: date | None = None):
    """`since` bounds wp.weather_obs (hourly) to observed_at >= `since` 00:00 America/Montreal:
    older staged rows are not inserted AND older rows already in the table are deleted, so a
    hosted DB stays bounded. weather_daily (small, used for ML features) is not bounded. The
    cutoff is part of the load checksum, so a bounded and an unbounded load never no-op each
    other."""
    d = settings.processed_dir / "weather_obs"
    m = read_manifest(d)
    if m is not None and since is not None:
        m = {**m, "input_checksum": f"{m['input_checksum']}|weather_since={since.isoformat()}"}

    def fn(cur, run_id):
        cols = [
            "station_id",
            "observed_at",
            "temperature_c",
            "precip_mm",
            "snow_depth_cm",
            "wind_kmh",
            "source_collection",
            "ingest_run_id",
        ]
        types = {
            "station_id": "text",
            "observed_at": "timestamptz",
            "temperature_c": "double precision",
            "precip_mm": "double precision",
            "snow_depth_cm": "double precision",
            "wind_kmh": "double precision",
            "source_collection": "text",
            "ingest_run_id": "uuid",
        }
        # weather is append/upsert only: realtime rows age out upstream, keep history
        stage_cols = ", ".join(f"{c} {types[c]}" for c in cols)
        cur.execute(f"CREATE TEMP TABLE stage_weather ({stage_cols}) ON COMMIT DROP")
        n = 0
        with cur.copy(f"COPY stage_weather ({', '.join(cols)}) FROM STDIN") as cp:
            for r in _csv_rows(d / "weather_obs.csv", cols, run_id):
                cp.write_row(r)
                n += 1
        upd = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols[2:])
        counts = {"weather_obs": n}
        cutoff = "(%(since)s::date)::timestamp AT TIME ZONE 'America/Montreal'"
        bound = f"WHERE observed_at >= {cutoff} " if since is not None else ""
        params = {"since": since}
        if since is not None:
            cur.execute(f"DELETE FROM stage_weather WHERE NOT (observed_at >= {cutoff})", params)
            counts["_weather_obs_skipped_before_since"] = cur.rowcount
            counts["weather_obs"] = n - cur.rowcount
        cur.execute(
            f"INSERT INTO wp.weather_obs ({', '.join(cols)}) SELECT {', '.join(cols)} FROM "
            f"stage_weather {bound}ON CONFLICT (station_id, observed_at) DO UPDATE SET {upd} "
            "WHERE wp.weather_obs.source_collection='swob-realtime' "
            "OR EXCLUDED.source_collection='climate-hourly'",
            params if since is not None else None,
        )
        if since is not None:
            cur.execute(f"DELETE FROM wp.weather_obs WHERE observed_at < {cutoff}", params)
            counts["_weather_obs_pruned_before_since"] = cur.rowcount
        daily_csv = d / "weather_daily.csv"
        if daily_csv.exists():
            dcols = [
                "station_id",
                "day",
                "total_precip_mm",
                "total_snow_cm",
                "snow_on_ground_cm",
                "min_temp_c",
                "max_temp_c",
                "source_collection",
                "ingest_run_id",
            ]
            dtypes = {c: "double precision" for c in dcols[2:7]} | {
                "station_id": "text",
                "day": "date",
                "source_collection": "text",
                "ingest_run_id": "uuid",
            }
            # history is kept (no prune): past days are immutable upstream
            counts["weather_daily"] = _stage_and_merge(
                cur,
                table="weather_daily",
                columns=dcols,
                types=dtypes,
                rows=_csv_rows(daily_csv, dcols, run_id),
                key=["station_id", "day"],
                prune_where="FALSE",
            )
        return counts

    return "eccc-geomet", m, fn


LOADERS = {"osm": _osm, "voirie": _voirie, "entraves": _entraves, "311": _r311, "eccc": _weather}
# canonical source_id (contract v1.3, wp.source) → LOADERS key; `wp-ingest load --source <id>`
SOURCE_LOADERS = {
    "osm": "osm",
    "mtl-voirie": "voirie",
    "mtl-entraves": "entraves",
    "mtl-311": "311",
    "eccc-geomet": "eccc",
}


def load(
    settings: Settings,
    which: list[str],
    url: str | None = None,
    force: bool = False,
    weather_since: date | None = None,
) -> list[dict]:
    results = []
    with connect(url) as conn:
        with conn.transaction():
            upsert_sources(conn)
        for name in which:
            if name == "eccc":
                source_id, manifest, fn = _weather(settings, weather_since)
            else:
                source_id, manifest, fn = LOADERS[name](settings)
            if manifest is None:
                results.append({"source_id": source_id, "skipped": "no processed output"})
                continue
            results.append(_load(conn, source_id, manifest, fn, force=force))
    return results
