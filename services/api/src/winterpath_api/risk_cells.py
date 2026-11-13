"""Array-backed risk for a compact graph (island scale).

The ML layers are keyed by H3 cell and day. Asking them edge by edge costs one Python call per
edge per request, which is fine for 16,000 pilot edges and not for 650,000 island edges. Here the
cells each edge touches are computed once (:class:`RiskCellIndex`, stored in the graph artifact),
and a whole-graph :class:`Snapshot` is derived from one ``cell_risk`` call per cell, refreshed
every few minutes. Honesty rules are unchanged: an edge with any unknown cell is unknown, and
unknown is never a level.
"""

from __future__ import annotations

import inspect
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime
from threading import Lock
from typing import Any

import numpy as np
import structlog
from winterpath_routing import EvidenceState, RiskEstimate, RiskLevel

log = structlog.get_logger("winterpath_api.risk_cells")

#: codes in ``Snapshot.levels``; rank order LOW < MODERATE < ELEVATED < HIGH, then UNKNOWN
LEVELS: tuple[RiskLevel, ...] = (
    RiskLevel.LOW,
    RiskLevel.MODERATE,
    RiskLevel.ELEVATED,
    RiskLevel.HIGH,
    RiskLevel.UNKNOWN,
)
_UNKNOWN = len(LEVELS) - 1
#: build the index at start-up only for graphs up to this size; larger graphs must ship it
MAX_STARTUP_INDEX_EDGES = 60_000
EXTRA_OFF, EXTRA_IDX, EXTRA_CELLS = "risk_cell_off", "risk_cell_idx", "risk_cell_ids"


def sampler_of(inner: Any) -> tuple[Callable[..., list[str]], dict[str, Any]] | None:
    """The provider module's ``cells_along(coords)`` and its default parameters, if it has one."""
    mod = sys.modules.get(type(inner).__module__)
    fn = getattr(mod, "cells_along", None)
    if not callable(fn):
        return None
    params = {
        k: p.default
        for k, p in inspect.signature(fn).parameters.items()
        if p.default is not inspect.Parameter.empty
    }
    return fn, params


class RiskCellIndex:
    """edge index → the cells along that edge, in the sampler's order (CSR)."""

    def __init__(self, cells: list[str], off: np.ndarray, idx: np.ndarray) -> None:
        self.cells, self.off, self.idx = cells, off, idx

    def __len__(self) -> int:
        return len(self.off) - 1

    @classmethod
    def build(cls, graph: Any, cells_along: Callable[..., list[str]]) -> RiskCellIndex:
        table: dict[str, int] = {}
        off = np.zeros(len(graph.length) + 1, dtype=np.int64)
        idx: list[int] = []
        voff, wgs = graph.voff, graph.wgs
        for i in range(len(graph.length)):
            coords = wgs[int(voff[i]) : int(voff[i + 1])].tolist()
            for c in cells_along(coords):
                idx.append(table.setdefault(c, len(table)))
            off[i + 1] = len(idx)
        return cls(list(table), off, np.asarray(idx, dtype=np.int32))

    def to_extras(self) -> dict[str, np.ndarray]:
        width = max((len(c) for c in self.cells), default=1)
        return {
            EXTRA_OFF: self.off,
            EXTRA_IDX: self.idx,
            EXTRA_CELLS: np.array([c.encode() for c in self.cells], dtype=f"S{width}"),
        }

    @classmethod
    def from_extras(cls, extras: dict[str, np.ndarray], n_edges: int) -> RiskCellIndex | None:
        if not all(k in extras for k in (EXTRA_OFF, EXTRA_IDX, EXTRA_CELLS)):
            return None
        off, idx = extras[EXTRA_OFF], extras[EXTRA_IDX]
        cells = [b.decode() for b in extras[EXTRA_CELLS]]
        if len(off) != n_edges + 1 or (len(idx) and int(idx.max()) >= len(cells)):
            return None
        if len(off) > 1 and int(np.diff(off).min()) < 1:
            return None  # every edge touches at least one cell
        return cls(cells, off, idx)


class Snapshot:
    """One evaluation of every cell at one time (``winterpath_routing.EdgeRiskSnapshot``)."""

    level_values = LEVELS

    def __init__(self, index: RiskCellIndex, cell_est: list[RiskEstimate], token: Any) -> None:
        self._index = index
        self._cell_est = cell_est
        self.token = token
        rank = np.array(
            [_UNKNOWN if e.is_unknown else LEVELS.index(e.level) for e in cell_est],
            dtype=np.uint8,
        )
        self._rank = rank
        if len(index):
            self.levels = np.maximum.reduceat(rank[index.idx], index.off[:-1])
        else:
            self.levels = np.zeros(0, dtype=np.uint8)
        self.any_simulated = any(e.evidence.state is EvidenceState.SIMULATED for e in cell_est)

    def estimate(self, edge_index: int) -> RiskEstimate | None:
        ix = self._index
        cells = ix.idx[int(ix.off[edge_index]) : int(ix.off[edge_index + 1])]
        ests = [self._cell_est[int(c)] for c in cells]
        unknown = [e for e in ests if e.is_unknown]
        if unknown or not ests:
            notes = sorted({e.evidence.note or "" for e in unknown})
            return RiskEstimate.unknown("Edge not fully covered: " + " ".join(notes))
        # same rule as the ML layer: highest level, then highest probability, first one wins
        return max(ests, key=lambda e: (LEVELS.index(e.level), e.probability or 0.0))


class SnapshotSource:
    """Builds and caches :class:`Snapshot` objects per Montréal local day, for ``ttl_s`` seconds
    (a day's scores may land, or be replaced, while the process is running)."""

    def __init__(
        self,
        index: RiskCellIndex,
        cell_estimate: Callable[[str, datetime], RiskEstimate],
        local_day: Callable[[datetime], Any],
        ttl_s: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.index = index
        self._cell_estimate = cell_estimate
        self._local_day = local_day
        self._ttl_s = ttl_s
        self._clock = clock
        self._lock = Lock()
        self._cache: dict[Any, tuple[float, Snapshot]] = {}
        self._serial = 0

    def at(self, at: datetime) -> Snapshot:
        day = self._local_day(at)
        with self._lock:
            hit = self._cache.get(day)
            if hit is not None and self._clock() < hit[0]:
                return hit[1]
            ests = [self._cell_estimate(c, at) for c in self.index.cells]
            self._serial += 1
            snap = Snapshot(self.index, ests, (day, self._serial))
            if hit is not None and np.array_equal(hit[1].levels, snap.levels):
                snap.token = hit[1].token  # same levels: weights derived from them stay valid
            if len(self._cache) > 3:
                self._cache.clear()
            self._cache[day] = (self._clock() + self._ttl_s, snap)
            return snap


def index_for(
    graph: Any,
    inner: Any,
    shipped: tuple[dict[str, np.ndarray], dict[str, Any] | None] | None,
) -> RiskCellIndex | None:
    """The shipped index if it matches this provider's sampler, else one built now for a small
    compact graph, else ``None`` (the caller then uses the per-edge path)."""
    sampler = sampler_of(inner)
    if sampler is None or not hasattr(graph, "voff"):
        return None
    cells_along, params = sampler
    n_edges = len(graph.length)
    extras, declared = shipped or ({}, None)
    if declared is not None:
        if declared.get("params") == _jsonable(params):
            ix = RiskCellIndex.from_extras(extras, n_edges)
            if ix is not None:
                return ix
        log.warning("risk_cell_index_rejected", declared=declared, expected=_jsonable(params))
    if n_edges > MAX_STARTUP_INDEX_EDGES:
        log.warning("risk_cell_index_missing", edges=n_edges)
        return None
    return RiskCellIndex.build(graph, cells_along)


def _jsonable(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in params.items() if isinstance(v, (int, float, str, bool))}


def describe(inner: Any) -> dict[str, Any] | None:
    """What an artifact must record next to a shipped index (``info["risk_cells"]``)."""
    sampler = sampler_of(inner)
    return {"params": _jsonable(sampler[1])} if sampler else None


__all__: Sequence[str] = (
    "LEVELS",
    "RiskCellIndex",
    "Snapshot",
    "SnapshotSource",
    "describe",
    "index_for",
    "sampler_of",
)
