"""Prebuilt graph artifact: a :class:`~winterpath_routing.compact.CompactGraph` on disk.

Loading a large graph from PostGIS at boot builds one Python ``Edge`` per row first (about 1.1 GiB
for the Island of Montréal, see ``docs/agent-reports/routing.md``), which does not fit a 512 MB
instance. The artifact stores the finished arrays instead, so start-up is a file read.

Format: one ``.npz`` (NumPy arrays only; loaded with ``allow_pickle=False``, so reading a file
cannot run code) plus a JSON header array for metadata and the dictionary-encoded column values.
:func:`sha256_file` lets the caller pin the exact file before loading it.

Extra named arrays (``extras``) ride along untouched: the API stores its edge → risk-cell index
there. They are returned by :func:`load` and never interpreted here.
"""

from __future__ import annotations

import hashlib
import json
from array import array
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from .compact import (
    EDGE_ATTRS,
    NODE_ATTRS,
    CompactGraph,
    EdgeMask,
    _EdgeMap,
    _IdIndex,
    _MetricLines,
    _NodeMap,
    _NodeXY,
)
from .models import GraphMetadata

FORMAT = "winterpath-compact-graph"
FORMAT_VERSION = 1
EXTRA_PREFIX = "x_"


class ArtifactError(ValueError):
    """The file is not a readable graph artifact of this format version."""


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# -- exact JSON encoding of column values (None, bool, int, float, str, tuple, datetime) ----------
def _enc(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            raise ArtifactError("non-finite float in a graph attribute")
        return {"f": v.hex()}
    if isinstance(v, tuple):
        return {"t": [_enc(x) for x in v]}
    if isinstance(v, datetime):
        return {"dt": v.isoformat()}
    raise ArtifactError(f"unsupported attribute value type {type(v).__name__}")


def _dec(v: Any) -> Any:
    if isinstance(v, dict):
        if "f" in v:
            return float.fromhex(v["f"])
        if "t" in v:
            return tuple(_dec(x) for x in v["t"])
        if "dt" in v:
            return datetime.fromisoformat(v["dt"])
        raise ArtifactError("unknown value tag in graph artifact")
    return v


def _meta_to_json(m: GraphMetadata) -> dict[str, Any]:
    return {
        "simulated": m.simulated,
        "osm_snapshot": m.osm_snapshot,
        "built_at": m.built_at.isoformat() if m.built_at else None,
        "source_freshness": {
            k: (v.isoformat() if v else None) for k, v in m.source_freshness.items()
        },
        "description": m.description,
    }


def _meta_from_json(d: dict[str, Any]) -> GraphMetadata:
    def dt(v: str | None) -> datetime | None:
        return datetime.fromisoformat(v) if v else None

    return GraphMetadata(
        simulated=bool(d["simulated"]),
        osm_snapshot=d.get("osm_snapshot"),
        built_at=dt(d.get("built_at")),
        source_freshness={k: dt(v) for k, v in (d.get("source_freshness") or {}).items()},
        description=str(d.get("description") or ""),
    )


def save(
    g: CompactGraph,
    path: str | Path,
    *,
    extras: dict[str, np.ndarray] | None = None,
    info: dict[str, Any] | None = None,
    compressed: bool = False,
) -> None:
    """Write ``g`` to ``path`` (.npz). ``info`` is free-form JSON kept in the header."""
    header = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "metadata": _meta_to_json(g.metadata),
        "nvals": {a: [_enc(v) for v in g._nvals[a]] for a in NODE_ATTRS},
        "evals": {a: [_enc(v) for v in g._evals[a]] for a in EDGE_ATTRS},
        "grid": [g._gx0, g._gy0, g._gny, g._gnx],
        "largest_component_share": float(g.largest_component_share).hex(),
        "info": info or {},
    }
    arrays: dict[str, np.ndarray] = {
        "header": np.frombuffer(json.dumps(header).encode(), dtype=np.uint8),
        "nid_sorted": g._nids.sorted_ids,
        "nid_perm": g._nids.perm,
        "nid_rank": g._nids.rank,
        "eid_sorted": g._eids.sorted_ids,
        "eid_perm": g._eids.perm,
        "eid_rank": g._eids.rank,
        "node_lon": g.node_lon,
        "node_lat": g.node_lat,
        "node_x": np.frombuffer(g.node_x, dtype=np.float64),
        "node_y": np.frombuffer(g.node_y, dtype=np.float64),
        "from_idx": g.from_idx,
        "to_idx": g.to_idx,
        "length": g.length,
        "voff": g.voff,
        "wgs": g.wgs,
        "metric": g.metric,
        "adj_off": np.frombuffer(g.adj_off, dtype=np.int64),
        "adj_to": np.frombuffer(g.adj_to, dtype=np.int32),
        "adj_edge": np.frombuffer(g.adj_edge, dtype=np.int32),
        "mbox": g.mbox,
        "wbox": g.wbox,
        "grid_keys": g.grid_keys,
        "grid_edges": g.grid_edges,
        "legal": g.legal,
        "comp_roots": g._comp_roots,
        "comp_edges": g._comp_edges,
        "node_comp": g._node_comp,
        "main_mask": np.frombuffer(bytes(g.main_mask), dtype=np.uint8),
    }
    for a in NODE_ATTRS:
        arrays[f"ncode_{a}"] = g._ncodes[a]
    for a in EDGE_ATTRS:
        arrays[f"ecode_{a}"] = g._ecodes[a]
    for k, v in (extras or {}).items():
        arrays[EXTRA_PREFIX + k] = np.asarray(v)
    (np.savez_compressed if compressed else np.savez)(str(path), **arrays)


def _id_index(sorted_ids: np.ndarray, perm: np.ndarray, rank: np.ndarray) -> _IdIndex:
    ix = _IdIndex.__new__(_IdIndex)
    ix.sorted_ids, ix.perm, ix.rank = sorted_ids, perm, rank
    return ix


def load(path: str | Path) -> tuple[CompactGraph, dict[str, np.ndarray], dict[str, Any]]:
    """``(graph, extras, info)``. Raises :class:`ArtifactError` on a foreign or damaged file."""
    try:
        z = np.load(str(path), allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise ArtifactError(f"cannot read graph artifact {path}: {exc}") from exc
    with z:
        try:
            header = json.loads(bytes(z["header"]).decode())
        except (KeyError, ValueError) as exc:
            raise ArtifactError("graph artifact has no readable header") from exc
        if header.get("format") != FORMAT or header.get("version") != FORMAT_VERSION:
            raise ArtifactError(
                f"unsupported graph artifact {header.get('format')!r} v{header.get('version')!r}"
            )
        try:
            g = CompactGraph.__new__(CompactGraph)
            g.metadata = _meta_from_json(header["metadata"])
            g._nids = _id_index(z["nid_sorted"], z["nid_perm"], z["nid_rank"])
            g._eids = _id_index(z["eid_sorted"], z["eid_perm"], z["eid_rank"])
            g.node_lon, g.node_lat = z["node_lon"], z["node_lat"]
            g.node_x = array("d", z["node_x"].tobytes())
            g.node_y = array("d", z["node_y"].tobytes())
            g._ncodes = {a: z[f"ncode_{a}"] for a in NODE_ATTRS}
            g._nvals = {a: [_dec(v) for v in header["nvals"][a]] for a in NODE_ATTRS}
            g.from_idx, g.to_idx = z["from_idx"], z["to_idx"]
            g.length, g.voff = z["length"], z["voff"]
            g.wgs, g.metric = z["wgs"], z["metric"]
            g._ecodes = {a: z[f"ecode_{a}"] for a in EDGE_ATTRS}
            g._evals = {a: [_dec(v) for v in header["evals"][a]] for a in EDGE_ATTRS}
            g.adj_off = array("q", z["adj_off"].tobytes())
            g.adj_to = array("i", z["adj_to"].tobytes())
            g.adj_edge = array("i", z["adj_edge"].tobytes())
            g.mbox, g.wbox = z["mbox"], z["wbox"]
            g._gx0, g._gy0, g._gny, g._gnx = (int(v) for v in header["grid"])
            g.grid_keys, g.grid_edges = z["grid_keys"], z["grid_edges"]
            g.legal = z["legal"]
            g._comp_roots, g._comp_edges = z["comp_roots"], z["comp_edges"]
            g._node_comp = z["node_comp"]
            g.main_mask = bytearray(z["main_mask"].tobytes())
            g.largest_component_share = float.fromhex(header["largest_component_share"])
            extras = {k[len(EXTRA_PREFIX) :]: z[k] for k in z.files if k.startswith(EXTRA_PREFIX)}
        except KeyError as exc:
            raise ArtifactError(f"graph artifact is missing {exc}") from exc
    n, e = len(g._nids), len(g._eids)
    if not (
        len(g.node_lon) == n
        and len(g.from_idx) == len(g.to_idx) == len(g.length) == e
        and len(g.voff) == e + 1
        and len(g.adj_off) == n + 1
        and len(g.adj_to) == len(g.adj_edge) == e
        and len(g.main_mask) == e
        and (e == 0 or (0 <= int(g.from_idx.min()) and int(g.to_idx.max()) < n))
    ):
        raise ArtifactError("graph artifact arrays are inconsistent")
    g.main_component_edge_ids = EdgeMask(g, g.main_mask)
    g.edges = _EdgeMap(g)
    g.nodes = _NodeMap(g)
    g.metric_lines = _MetricLines(g)
    g._node_xy = _NodeXY(g)
    return g, extras, dict(header.get("info") or {})
