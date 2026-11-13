"""Compact pedestrian graph (PROTOTYPE, behind ``ROUTING_COMPACT_GRAPH``; off by default).

Same public surface as :class:`~winterpath_routing.graph.PedestrianGraph`, but the graph is held
in flat arrays instead of Python objects, so memory grows by roughly a hundred bytes per edge
instead of a few kilobytes (measured in ``docs/agent-reports/routing.md`` → Island feasibility):

* adjacency in CSR form (``offsets`` / ``targets`` / ``edge index``), per node in exactly the
  order networkx's ``MultiDiGraph.out_edges(n, keys=True)`` yields it — first by neighbour in
  first-insertion order, then by key in insertion order — so searches relax arcs in the same
  order as the networkx-backed engine and break ties the same way;
* WGS84 and EPSG:32188 vertex arrays with per-edge offsets (the metric coordinates are the same
  pyproj transform :func:`~winterpath_routing.geo.line_to_metric` applies);
* every other edge/node attribute as a dictionary-encoded column (exact values, ``None`` kept);
* ids as sorted fixed-width byte arrays (binary search), not as dictionaries of Python strings;
* a uniform grid over edge bounding boxes for spatial queries. It only *selects candidates*; the
  final predicate and distance are the same GEOS calls the STRtree path makes, on the same
  coordinates, so results are identical.

``Edge``/``Node`` objects and shapely lines are materialised on access (``graph.edges[eid]``),
never stored. Connectivity comes only from the provider's node ids; nothing is inferred.
"""

from __future__ import annotations

import math
from array import array
from collections.abc import Iterable, Iterator, Mapping, Set
from dataclasses import fields
from typing import Any

import numpy as np
import shapely
from shapely.geometry import LineString, Point, box
from shapely.geometry.base import BaseGeometry

from .geo import _TO_METRIC, point_to_metric, to_wgs84_lonlat
from .graph import Gap, GraphIntegrityError
from .models import NON_ROUTABLE_FOOT_ACCESS, Edge, GraphData, GraphMetadata, Node

#: Edge attributes stored as dictionary-encoded columns (everything but id/topology/geometry).
EDGE_ATTRS: tuple[str, ...] = tuple(
    f.name
    for f in fields(Edge)
    if f.name not in ("edge_id", "from_node_id", "to_node_id", "coords", "length_m")
)
NODE_ATTRS: tuple[str, ...] = ("kind", "crossing_type", "kerb")
#: Grid cell size for the spatial index, metres (EPSG:32188).
GRID_CELL_M = 100.0
#: Materialised Edge / LineString objects kept per graph (bounded; cleared when full). Route
#: assembly, costing, explanations and steps touch each route edge several times.
OBJECT_CACHE_SIZE = 8192


def _key(v: Any) -> tuple:
    # 1 == 1.0 == True and 0.0 == -0.0 hash alike; keep type and float sign distinct.
    if isinstance(v, float):
        return (float, v, math.copysign(1.0, v))
    return (type(v), v)


class _Column:
    """Dictionary-encoded column: exact values (any hashable, ``None`` included)."""

    __slots__ = ("_codes", "_index", "values")

    def __init__(self) -> None:
        self.values: list[Any] = []
        self._index: dict[tuple, int] = {}
        self._codes = array("I")

    def append(self, v: Any) -> None:
        k = _key(v)
        c = self._index.get(k)
        if c is None:
            c = self._index[k] = len(self.values)
            self.values.append(v)
        self._codes.append(c)

    def freeze(self) -> np.ndarray:
        n = len(self.values)
        dtype = np.uint8 if n <= 0xFF else np.uint16 if n <= 0xFFFF else np.uint32
        codes = np.frombuffer(self._codes, dtype=np.uint32).astype(dtype)
        self._codes = array("I")
        self._index = {}
        return codes


class _IdIndex:
    """Ids as fixed-width UTF-8 bytes, stored once in sorted order, plus two permutations.

    UTF-8 byte order equals code-point order, so ``sorted_ids`` is also ``sorted(str ids)``.
    ``perm[j]`` = insertion index of the j-th smallest id; ``rank[i]`` = its inverse.
    """

    def __init__(self, ids: list[bytes]) -> None:
        width = max((len(b) for b in ids), default=1) or 1
        arr = np.array(ids, dtype=f"S{width}")
        self.perm = np.argsort(arr, kind="stable").astype(np.int32)
        self.sorted_ids = arr[self.perm]
        del arr
        self.rank = np.empty(len(self.perm), dtype=np.int32)
        self.rank[self.perm] = np.arange(len(self.perm), dtype=np.int32)

    def __len__(self) -> int:
        return len(self.perm)

    def find(self, key: str) -> int:
        """Insertion index of ``key`` or -1."""
        b = key.encode() if isinstance(key, str) else None
        if b is None or len(b) > self.sorted_ids.dtype.itemsize or b.endswith(b"\0"):
            return -1
        j = int(np.searchsorted(self.sorted_ids, b))
        if j < len(self.sorted_ids) and self.sorted_ids[j] == b:
            return int(self.perm[j])
        return -1

    def name(self, i: int) -> str:
        return self.sorted_ids[self.rank[i]].decode()

    def names(self) -> Iterator[str]:
        """All ids in insertion order."""
        s = self.sorted_ids
        return (s[j].decode() for j in self.rank)

    def nbytes(self) -> int:
        return self.sorted_ids.nbytes + self.perm.nbytes + self.rank.nbytes

    def duplicate(self) -> str | None:
        s = self.sorted_ids
        if len(s) < 2:
            return None
        dup = np.flatnonzero(s[1:] == s[:-1])
        return s[dup[0]].decode() if len(dup) else None


class CompactGraphBuilder:
    """Accumulates nodes then edges (streamed: no ``Edge`` list is kept) and builds a graph."""

    def __init__(self) -> None:
        self._node_idx: dict[str, int] = {}
        self._node_ids: list[bytes] = []
        self._lon = array("d")
        self._lat = array("d")
        self._ncols = {a: _Column() for a in NODE_ATTRS}
        self._edge_ids: list[bytes] = []
        self._from = array("i")
        self._to = array("i")
        self._length = array("d")
        self._voff = array("q", [0])
        self._wgs = array("d")
        self._ecols = {a: _Column() for a in EDGE_ATTRS}

    # -- nodes ---------------------------------------------------------------------------
    def add_node(self, n: Node) -> None:
        if n.node_id in self._node_idx:  # dict semantics of GraphData.nodes: last one wins
            raise GraphIntegrityError(f"duplicate node_id {n.node_id}")
        self._node_idx[n.node_id] = len(self._node_ids)
        self._node_ids.append(n.node_id.encode())
        self._lon.append(n.lon)
        self._lat.append(n.lat)
        for a in NODE_ATTRS:
            self._ncols[a].append(getattr(n, a))

    def node(self, node_id: str) -> Node | None:
        """A node added so far (for loaders that enrich edges from their nodes)."""
        i = self._node_idx.get(node_id)
        if i is None:
            return None
        return Node(
            node_id,
            self._lon[i],
            self._lat[i],
            **{a: self._ncols[a].values[self._ncols[a]._codes[i]] for a in NODE_ATTRS},
        )

    # -- edges ---------------------------------------------------------------------------
    def add_edge(self, e: Edge) -> None:
        # Same checks, same messages and the same order as PedestrianGraph (duplicate ids are
        # detected when building, on the sorted id array, instead of with a per-edge set).
        fi = self._node_idx.get(e.from_node_id)
        ti = self._node_idx.get(e.to_node_id)
        if fi is None or ti is None:
            raise GraphIntegrityError(f"edge {e.edge_id} references unknown node")
        if e.length_m <= 0 or len(e.coords) < 2:
            raise GraphIntegrityError(f"edge {e.edge_id} has non-positive length/geometry")
        self._edge_ids.append(e.edge_id.encode())
        self._from.append(fi)
        self._to.append(ti)
        self._length.append(e.length_m)
        for x, y in e.coords:
            self._wgs.append(x)
            self._wgs.append(y)
        self._voff.append(len(self._wgs) // 2)
        for a in EDGE_ATTRS:
            self._ecols[a].append(getattr(e, a))

    def build(self, metadata: GraphMetadata) -> CompactGraph:
        g = CompactGraph.__new__(CompactGraph)
        g._init_from_builder(self, metadata)
        return g


class _EdgeMap(Mapping[str, Edge]):
    __slots__ = ("_cache", "_g")

    def __init__(self, g: CompactGraph) -> None:
        self._g = g
        self._cache: dict[str, Edge] = {}

    def __getitem__(self, eid: str) -> Edge:
        e = self._cache.get(eid)
        if e is not None:
            return e
        i = self._g._eids.find(eid)
        if i < 0:
            raise KeyError(eid)
        e = self._g.edge_at(i)
        if len(self._cache) >= OBJECT_CACHE_SIZE:
            self._cache.clear()
        self._cache[eid] = e
        return e

    def __contains__(self, eid: object) -> bool:
        return isinstance(eid, str) and self._g._eids.find(eid) >= 0

    def __iter__(self) -> Iterator[str]:
        return self._g._eids.names()

    def __len__(self) -> int:
        return len(self._g._eids)


class _NodeMap(Mapping[str, Node]):
    __slots__ = ("_g",)

    def __init__(self, g: CompactGraph) -> None:
        self._g = g

    def __getitem__(self, nid: str) -> Node:
        i = self._g._nids.find(nid)
        if i < 0:
            raise KeyError(nid)
        return self._g.node_at(i)

    def __contains__(self, nid: object) -> bool:
        return isinstance(nid, str) and self._g._nids.find(nid) >= 0

    def __iter__(self) -> Iterator[str]:
        return self._g._nids.names()

    def __len__(self) -> int:
        return len(self._g._nids)


class _MetricLines(Mapping[str, LineString]):
    __slots__ = ("_cache", "_g")

    def __init__(self, g: CompactGraph) -> None:
        self._g = g
        self._cache: dict[str, LineString] = {}

    def __getitem__(self, eid: str) -> LineString:
        line = self._cache.get(eid)
        if line is not None:
            return line
        i = self._g._eids.find(eid)
        if i < 0:
            raise KeyError(eid)
        line = self._g.metric_line_at(i)
        if len(self._cache) >= OBJECT_CACHE_SIZE:
            self._cache.clear()
        self._cache[eid] = line
        return line

    def __iter__(self) -> Iterator[str]:
        return iter(self._g.edges)

    def __len__(self) -> int:
        return len(self._g._eids)


class _NodeXY(Mapping[str, tuple[float, float]]):
    __slots__ = ("_g",)

    def __init__(self, g: CompactGraph) -> None:
        self._g = g

    def __getitem__(self, nid: str) -> tuple[float, float]:
        i = self._g._nids.find(nid)
        if i < 0:
            raise KeyError(nid)
        return (self._g.node_x[i], self._g.node_y[i])

    def __iter__(self) -> Iterator[str]:
        return iter(self._g.nodes)

    def __len__(self) -> int:
        return len(self._g._nids)


class EdgeMask(Set[str]):
    """Set of edge ids backed by one byte per edge (``mask[i]`` = 1 when edge ``i`` is in)."""

    __slots__ = ("_g", "_n", "mask")

    def __init__(self, g: CompactGraph, mask: bytearray) -> None:
        self._g = g
        self.mask = mask
        self._n = len(mask) - mask.count(0)

    def __contains__(self, eid: object) -> bool:
        if not isinstance(eid, str):
            return False
        i = self._g._eids.find(eid)
        return i >= 0 and self.mask[i] == 1

    def __iter__(self) -> Iterator[str]:
        name = self._g._eids.name
        m = np.frombuffer(self.mask, dtype=np.uint8)
        return (name(int(i)) for i in np.flatnonzero(m))

    def __len__(self) -> int:
        return self._n

    def sorted_ids(self) -> list[str]:
        """``sorted(self)`` without sorting strings: walks the pre-sorted id array."""
        idx = self._g._eids
        m = np.frombuffer(self.mask, dtype=np.uint8)[idx.perm]
        return [b.decode() for b in idx.sorted_ids[m == 1]]


class CompactGraph:
    """Array-backed pedestrian graph; see the module docstring. Build with
    :meth:`from_graph_data` or :class:`CompactGraphBuilder`."""

    @classmethod
    def from_graph_data(cls, data: GraphData) -> CompactGraph:
        b = CompactGraphBuilder()
        for n in data.nodes.values():
            b.add_node(n)
        for e in data.edges:
            b.add_edge(e)
        return b.build(data.metadata)

    # ------------------------------------------------------------------ build
    def _init_from_builder(self, b: CompactGraphBuilder, metadata: GraphMetadata) -> None:
        self.metadata = metadata
        n_nodes, n_edges = len(b._node_ids), len(b._edge_ids)
        self._nids = _IdIndex(b._node_ids)
        self._eids = _IdIndex(b._edge_ids)
        b._node_ids = b._edge_ids = []
        b._node_idx = {}
        dup = self._eids.duplicate()
        if dup is not None:
            raise GraphIntegrityError(f"duplicate edge_id {dup}")

        self.node_lon = np.frombuffer(b._lon, dtype=np.float64).copy()
        self.node_lat = np.frombuffer(b._lat, dtype=np.float64).copy()
        self._ncodes = {a: b._ncols[a].freeze() for a in NODE_ATTRS}
        self._nvals = {a: b._ncols[a].values for a in NODE_ATTRS}

        self.from_idx = np.frombuffer(b._from, dtype=np.int32).copy()
        self.to_idx = np.frombuffer(b._to, dtype=np.int32).copy()
        self.length = np.frombuffer(b._length, dtype=np.float64).copy()
        self.voff = np.frombuffer(b._voff, dtype=np.int64).copy()
        self.wgs = np.frombuffer(b._wgs, dtype=np.float64).copy().reshape(-1, 2)
        self._ecodes = {a: b._ecols[a].freeze() for a in EDGE_ATTRS}
        self._evals = {a: b._ecols[a].values for a in EDGE_ATTRS}
        b._lon = b._lat = b._length = b._wgs = array("d")
        b._from = b._to = array("i")

        # Metric vertices: the transform line_to_metric() applies, done once for all vertices.
        mx, my = _TO_METRIC.transform(self.wgs[:, 0], self.wgs[:, 1])
        self.metric = np.column_stack([np.asarray(mx, float), np.asarray(my, float)])
        nx_, ny_ = _TO_METRIC.transform(self.node_lon, self.node_lat)
        # array('d') indexing returns Python floats: fast in the search loop, 8 B per value.
        self.node_x = array("d", np.asarray(nx_, float).tobytes())
        self.node_y = array("d", np.asarray(ny_, float).tobytes())

        self._build_adjacency(n_nodes, n_edges)
        self._build_bboxes()
        self._build_grid()
        self._compute_components()

        self.edges: Mapping[str, Edge] = _EdgeMap(self)
        self.nodes: Mapping[str, Node] = _NodeMap(self)
        self.metric_lines: Mapping[str, LineString] = _MetricLines(self)
        self._node_xy: Mapping[str, tuple[float, float]] = _NodeXY(self)

    def _build_adjacency(self, n_nodes: int, n_edges: int) -> None:
        """CSR in networkx MultiDiGraph out-edge order (see module docstring)."""
        # Rank of each edge among the edges u→v: its neighbour block is ordered by the first
        # edge index of each (u, v) pair; inside a block, by edge index (key insertion order).
        pair = self.from_idx.astype(np.int64) * max(n_nodes, 1) + self.to_idx
        order = np.lexsort((np.arange(n_edges), pair))
        sp = pair[order]
        starts = np.ones(n_edges, dtype=bool)
        starts[1:] = sp[1:] != sp[:-1]
        first_of_pair_sorted = np.maximum.accumulate(np.where(starts, np.arange(n_edges), 0))
        first_edge = np.empty(n_edges, dtype=np.int64)
        first_edge[order] = order[first_of_pair_sorted]
        csr = np.lexsort((np.arange(n_edges), first_edge, self.from_idx))
        counts = np.bincount(self.from_idx, minlength=n_nodes)
        off = np.zeros(n_nodes + 1, dtype=np.int64)
        np.cumsum(counts, out=off[1:])
        self.adj_off = array("q", off.tobytes())
        self.adj_to = array("i", self.to_idx[csr].astype(np.int32).tobytes())
        self.adj_edge = array("i", csr.astype(np.int32).tobytes())

    def _build_bboxes(self) -> None:
        """Per-edge bounding boxes in float32, rounded OUTWARD (a superset filter only)."""
        s = self.voff[:-1]
        self.mbox = np.empty((len(s), 4), dtype=np.float32)
        self.wbox = np.empty((len(s), 4), dtype=np.float32)
        for out, xy in ((self.mbox, self.metric), (self.wbox, self.wgs)):
            if len(s):
                for col, f, ax, inf in (
                    (0, np.minimum, 0, -np.inf),
                    (1, np.minimum, 1, -np.inf),
                    (2, np.maximum, 0, np.inf),
                    (3, np.maximum, 1, np.inf),
                ):
                    v = f.reduceat(xy[:, ax], s)
                    v32 = v.astype(np.float32)
                    # float32 rounding may move the bound inward: step it one ulp outward
                    inward = (v32 > v) if inf < 0 else (v32 < v)
                    v32[inward] = np.nextafter(v32[inward], np.float32(inf))
                    out[:, col] = v32

    def _build_grid(self) -> None:
        c = GRID_CELL_M
        n = len(self.mbox)
        if not n:
            self._gx0 = self._gy0 = 0
            self._gny = self._gnx = 1
            self.grid_keys = np.zeros(0, np.int64)
            self.grid_edges = np.zeros(0, np.int32)
            return
        cx0 = np.floor(self.mbox[:, 0] / c).astype(np.int64)
        cy0 = np.floor(self.mbox[:, 1] / c).astype(np.int64)
        cx1 = np.floor(self.mbox[:, 2] / c).astype(np.int64)
        cy1 = np.floor(self.mbox[:, 3] / c).astype(np.int64)
        self._gx0, self._gy0 = int(cx0.min()), int(cy0.min())
        self._gny = int(cy1.max()) - self._gy0 + 1
        self._gnx = int(cx1.max()) - self._gx0 + 1
        w, h = cx1 - cx0 + 1, cy1 - cy0 + 1
        cnt = w * h
        eidx = np.repeat(np.arange(n, dtype=np.int64), cnt)
        start = np.repeat(np.cumsum(cnt) - cnt, cnt)
        k = np.arange(len(eidx), dtype=np.int64) - start
        hh = h[eidx]
        gx = cx0[eidx] + k // hh - self._gx0
        gy = cy0[eidx] + k % hh - self._gy0
        keys = gx * self._gny + gy
        order = np.lexsort((eidx, keys))
        self.grid_keys = keys[order]
        self.grid_edges = eidx[order].astype(np.int32)

    def _grid_candidates(self, minx: float, miny: float, maxx: float, maxy: float) -> np.ndarray:
        """Sorted edge indices whose metric bbox intersects the given box."""
        c = GRID_CELL_M
        gx0 = max(math.floor(minx / c) - self._gx0, 0)
        gx1 = min(math.floor(maxx / c) - self._gx0, self._gnx - 1)
        gy0 = max(math.floor(miny / c) - self._gy0, 0)
        gy1 = min(math.floor(maxy / c) - self._gy0, self._gny - 1)
        if gx1 < gx0 or gy1 < gy0:
            return np.zeros(0, np.int64)
        gx = np.arange(gx0, gx1 + 1, dtype=np.int64)
        lo = np.searchsorted(self.grid_keys, gx * self._gny + gy0, "left")
        hi = np.searchsorted(self.grid_keys, gx * self._gny + gy1, "right")
        parts = [self.grid_edges[a:b] for a, b in zip(lo, hi, strict=True) if b > a]
        if not parts:
            return np.zeros(0, np.int64)
        cand = np.unique(np.concatenate(parts))
        bb = self.mbox[cand]
        keep = (bb[:, 0] <= maxx) & (bb[:, 2] >= minx) & (bb[:, 1] <= maxy) & (bb[:, 3] >= miny)
        return cand[keep]

    def _compute_components(self) -> None:
        """Weakly connected components of the foot-legal graph, ordered like PedestrianGraph:
        by (-legal edge count, min node id). Isolated nodes are not components."""
        n = len(self._nids)
        fa = self._ecodes["foot_access"]
        bad = [i for i, v in enumerate(self._evals["foot_access"]) if v in NON_ROUTABLE_FOOT_ACCESS]
        self.legal = ~np.isin(fa, bad) if bad else np.ones(len(fa), dtype=bool)
        u = self.from_idx[self.legal].astype(np.int64)
        v = self.to_idx[self.legal].astype(np.int64)
        # Vectorised union-find (hook roots to the smaller root, then full pointer jumping):
        # converges to label = smallest node index of each weakly connected component.
        label = np.arange(n, dtype=np.int64)
        while True:
            before = label.copy()
            lu, lv = label[u], label[v]
            m = np.minimum(lu, lv)
            np.minimum.at(label, lu, m)
            np.minimum.at(label, lv, m)
            while True:
                nxt = label[label]
                if np.array_equal(nxt, label):
                    break
                label = nxt
            if np.array_equal(label, before):
                break
        edge_comp = label[u]
        roots, counts = np.unique(edge_comp, return_counts=True)
        # min node id (string order) per component
        rank = np.empty(n, dtype=np.int64)
        rank[self._nids.perm] = np.arange(n)
        min_rank = np.full(n, n, dtype=np.int64)
        has_edge = np.zeros(n, dtype=bool)
        has_edge[u] = True
        has_edge[v] = True
        np.minimum.at(min_rank, label[has_edge], rank[has_edge])
        order = np.lexsort((min_rank[roots], -counts))
        self._comp_roots = roots[order]
        self._comp_edges = counts[order]
        self._node_comp = label
        main = self._comp_roots[0] if len(self._comp_roots) else -1
        in_main = self.legal & (label[self.from_idx] == main) & (label[self.to_idx] == main)
        self.main_mask = bytearray(in_main.astype(np.uint8).tobytes())
        self.main_component_edge_ids: Set[str] = EdgeMask(self, self.main_mask)
        legal_edges = int(self.legal.sum())
        self.largest_component_share: float = (
            len(self.main_component_edge_ids) / legal_edges if legal_edges else 0.0
        )

    # ------------------------------------------------------------------ materialisation
    def edge_index(self, eid: str) -> int:
        return self._eids.find(eid)

    def edge_id(self, i: int) -> str:
        return self._eids.name(i)

    def edge_attr(self, name: str) -> tuple[np.ndarray, list[Any]]:
        """(codes per edge, values) of one attribute column."""
        return self._ecodes[name], self._evals[name]

    def edge_at(self, i: int) -> Edge:
        s, t = int(self.voff[i]), int(self.voff[i + 1])
        attrs = {a: self._evals[a][self._ecodes[a][i]] for a in EDGE_ATTRS}
        return Edge(
            edge_id=self._eids.name(i),
            from_node_id=self._nids.name(int(self.from_idx[i])),
            to_node_id=self._nids.name(int(self.to_idx[i])),
            coords=tuple(map(tuple, self.wgs[s:t].tolist())),
            length_m=float(self.length[i]),
            **attrs,
        )

    def node_at(self, i: int) -> Node:
        return Node(
            node_id=self._nids.name(i),
            lon=float(self.node_lon[i]),
            lat=float(self.node_lat[i]),
            **{a: self._nvals[a][self._ncodes[a][i]] for a in NODE_ATTRS},
        )

    def metric_line_at(self, i: int) -> LineString:
        return LineString(self.metric[int(self.voff[i]) : int(self.voff[i + 1])])

    def _metric_lines_at(self, idx: np.ndarray) -> np.ndarray:
        if not len(idx):
            return np.empty(0, dtype=object)
        s, t = self.voff[idx], self.voff[idx + 1]
        cnt = t - s
        vi = np.repeat(s - np.cumsum(cnt) + cnt, cnt) + np.arange(int(cnt.sum()))
        return shapely.linestrings(self.metric[vi], indices=np.repeat(np.arange(len(idx)), cnt))

    # ------------------------------------------------------------------ components
    @property
    def components(self) -> list[set[str]]:
        """Node-id sets per component (materialised on demand; the main one can be large)."""
        return [
            {self._nids.name(i) for i in np.flatnonzero(self._node_comp == r)}
            for r in self._comp_roots
        ]

    def gaps(self) -> list[Gap]:
        out: list[Gap] = []
        for r, n_edges in zip(self._comp_roots[1:], self._comp_edges[1:], strict=True):
            members = np.flatnonzero(self._node_comp == r)
            # isolated singletons share their own label only; a component has ≥1 legal edge
            lon = sum(float(x) for x in self.node_lon[members]) / len(members)
            lat = sum(float(x) for x in self.node_lat[members]) / len(members)
            out.append(
                Gap(
                    description=(
                        f"Disconnected pedestrian sub-network ({int(n_edges)} directed edges) "
                        "not reachable from the main network; not used for routing."
                    ),
                    lon=lon,
                    lat=lat,
                    edge_count=int(n_edges),
                )
            )
        return out

    # ------------------------------------------------------------------ spatial queries
    def _near_idx(self, geom: BaseGeometry, tolerance_m: float) -> np.ndarray:
        minx, miny, maxx, maxy = geom.bounds
        cand = self._grid_candidates(
            minx - tolerance_m, miny - tolerance_m, maxx + tolerance_m, maxy + tolerance_m
        )
        if not len(cand):
            return cand
        ok = shapely.dwithin(self._metric_lines_at(cand), geom, tolerance_m)
        return cand[ok]

    def edges_near_metric(self, geom: BaseGeometry, tolerance_m: float) -> list[str]:
        return [self._eids.name(int(i)) for i in self._near_idx(geom, tolerance_m)]

    def edges_in_bbox(
        self,
        west: float,
        south: float,
        east: float,
        north: float,
        *,
        foot_legal_only: bool = False,
    ) -> list[str]:
        """``foot_legal_only`` filters on the ``legal`` array (same rule as ``Edge.foot_legal``)
        without building an ``Edge`` per candidate."""
        bb = self.wbox
        cand = np.flatnonzero(
            (bb[:, 0] <= east) & (bb[:, 2] >= west) & (bb[:, 1] <= north) & (bb[:, 3] >= south)
        )
        if foot_legal_only:
            cand = cand[self.legal[cand]]
        if len(cand):
            s, t = self.voff[cand], self.voff[cand + 1]
            cnt = t - s
            vi = np.repeat(s - np.cumsum(cnt) + cnt, cnt) + np.arange(int(cnt.sum()))
            lines = shapely.linestrings(self.wgs[vi], indices=np.repeat(np.arange(len(cand)), cnt))
            cand = cand[shapely.intersects(lines, box(west, south, east, north))]
        return sorted(self._eids.name(int(i)) for i in cand)

    def nearest_edges(
        self, lon: float, lat: float, max_m: float, allowed: Iterable[str] | None = None
    ) -> tuple[list[str], float, Point]:
        """Same contract as :meth:`PedestrianGraph.nearest_edges`."""
        p = point_to_metric(lon, lat)
        idx = self._near_idx(p, max_m)
        if allowed is not None and len(idx):
            if isinstance(allowed, EdgeMask) and allowed._g is self:
                m = np.frombuffer(allowed.mask, dtype=np.uint8)
                idx = idx[m[idx] == 1]
            else:
                aset = allowed if isinstance(allowed, (set, frozenset, Set)) else set(allowed)
                idx = np.array([i for i in idx if self._eids.name(int(i)) in aset], dtype=np.int64)
        if not len(idx):
            return [], float("inf"), p
        d = shapely.distance(self._metric_lines_at(idx), p)
        dmin = float(d.min())
        return (
            sorted(
                self._eids.name(int(i)) for i, di in zip(idx, d, strict=True) if di <= dmin + 0.01
            ),
            dmin,
            p,
        )

    def node_xy(self, node_id: str) -> tuple[float, float]:
        return self._node_xy[node_id]

    @staticmethod
    def metric_to_lonlat(x: float, y: float) -> tuple[float, float]:
        return to_wgs84_lonlat(x, y)

    # ------------------------------------------------------------------ accounting
    def nbytes(self) -> dict[str, int]:
        """Bytes held by the arrays (not Python object overhead)."""
        out = {
            "ids": self._eids.nbytes() + self._nids.nbytes(),
            "topology": self.from_idx.nbytes + self.to_idx.nbytes + self.length.nbytes,
            "adjacency": sum(
                a.itemsize * len(a) for a in (self.adj_off, self.adj_to, self.adj_edge)
            ),
            "vertices": self.voff.nbytes + self.wgs.nbytes + self.metric.nbytes,
            "bboxes": self.mbox.nbytes + self.wbox.nbytes,
            "grid": self.grid_keys.nbytes + self.grid_edges.nbytes,
            "attributes": sum(c.nbytes for c in self._ecodes.values())
            + sum(c.nbytes for c in self._ncodes.values()),
            "nodes": self.node_lon.nbytes * 4 + self._node_comp.nbytes,
            "components": len(self.main_mask) + self.legal.nbytes,
        }
        out["total"] = sum(out.values())
        return out
