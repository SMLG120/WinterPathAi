"""Bounded response caches for the read endpoints (``/map/segments``, ``/hazards``,
``/routes/compare``).

Rules (CLAUDE.md honesty + Render Free's 512 MiB):

* Every cache has an explicit capacity (entries **and** bytes) and a TTL. Values are the
  serialised response body (``bytes``), never live Python object graphs, so an entry costs about
  what the client downloads and nothing more.
* A key always contains the version of every input the answer depends on (graph, risk snapshot,
  hazard list, ...). When an input has no knowable version, the caller does not cache.
* An entry may also carry an absolute ``valid_until`` (wall clock): the moment the answer could
  change even though no input changed (a closure starting, the Montréal day ending). It is never
  served after that.
* Concurrent requests for the same missing key build it once (single flight); the others wait
  for that result. A failed build is not cached and the waiters build again themselves.
* Keys never appear in logs: :func:`key_digest` gives a short salted hash for log lines (keys
  contain precise coordinates for routes).
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

#: per-process salt so key digests in logs cannot be reversed by brute-forcing coordinates
_SALT = secrets.token_bytes(16)

#: ``API_RESPONSE_CACHE=false`` disables every response cache (kill switch; default on)
ENV_SWITCH = "API_RESPONSE_CACHE"


def enabled_from_env(env: dict[str, str] | None = None) -> bool:
    raw = (env if env is not None else os.environ).get(ENV_SWITCH, "")
    return raw.strip().lower() not in ("0", "false", "no", "off")


def key_digest(key: Hashable) -> str:
    """Short, salted, non-reversible label for a cache key (safe to log)."""
    return hashlib.blake2b(repr(key).encode(), key=_SALT, digest_size=6).hexdigest()


def norm_coord(v: float, dp: int = 6) -> float:
    """Canonical coordinate for a key: rounded to ``dp`` decimals (6 dp ≈ 0.1 m), ``-0.0`` → 0."""
    return round(float(v), dp) + 0.0


def norm_bbox(box: tuple[float, float, float, float], dp: int = 6) -> tuple[float, ...]:
    return tuple(norm_coord(v, dp) for v in box)


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    joins: int = 0  # requests that waited for an identical build in flight
    stores: int = 0
    evictions: int = 0
    expired: int = 0
    uncacheable: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class _Entry:
    body: bytes
    expires_mono: float
    valid_until: datetime | None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Flight:
    done: threading.Event = field(default_factory=threading.Event)
    entry: _Entry | None = None


class ResponseCache:
    """Thread-safe LRU + TTL cache of response bodies, bounded by entries and total bytes."""

    def __init__(
        self,
        name: str,
        *,
        max_entries: int,
        max_bytes: int,
        ttl_s: float,
        max_entry_bytes: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] | None = None,
    ) -> None:
        if max_entries < 1 or max_bytes < 1 or ttl_s <= 0:
            raise ValueError("cache capacity and TTL must be positive")
        self.name = name
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.ttl_s = ttl_s
        #: a body larger than this is returned but never stored (default: a quarter of the budget)
        self.max_entry_bytes = max_entry_bytes or max_bytes // 4
        self._clock = clock
        self._wall = wall
        self._lock = threading.Lock()
        self._data: OrderedDict[Hashable, _Entry] = OrderedDict()
        self._bytes = 0
        self._flights: dict[Hashable, _Flight] = {}
        self.stats = CacheStats()

    # ------------------------------------------------------------------ introspection
    def __len__(self) -> int:
        return len(self._data)

    @property
    def nbytes(self) -> int:
        return self._bytes

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._bytes = 0

    # ------------------------------------------------------------------ core
    def _now_wall(self) -> datetime:
        if self._wall is not None:
            return self._wall()
        from datetime import UTC

        return datetime.now(UTC)

    def _live(self, e: _Entry) -> bool:
        if self._clock() >= e.expires_mono:
            return False
        return e.valid_until is None or self._now_wall() < e.valid_until

    def _drop(self, key: Hashable) -> None:
        e = self._data.pop(key, None)
        if e is not None:
            self._bytes -= len(e.body)

    def get(self, key: Hashable) -> _Entry | None:
        with self._lock:
            e = self._data.get(key)
            if e is None:
                return None
            if not self._live(e):
                self._drop(key)
                self.stats.expired += 1
                return None
            self._data.move_to_end(key)
            return e

    def put(
        self,
        key: Hashable,
        body: bytes,
        *,
        ttl_s: float | None = None,
        valid_until: datetime | None = None,
        meta: dict[str, Any] | None = None,
    ) -> _Entry:
        ttl = self.ttl_s if ttl_s is None else min(ttl_s, self.ttl_s)
        e = _Entry(body, self._clock() + ttl, valid_until, meta or {})
        if len(body) > self.max_entry_bytes or ttl <= 0:
            return e  # served once, never stored
        with self._lock:
            self._drop(key)
            self._data[key] = e
            self._bytes += len(body)
            self.stats.stores += 1
            while self._data and (
                len(self._data) > self.max_entries or self._bytes > self.max_bytes
            ):
                _, oe = self._data.popitem(last=False)
                self._bytes -= len(oe.body)
                self.stats.evictions += 1
        return e

    def get_or_build(
        self,
        key: Hashable,
        build: Callable[[], tuple[bytes, dict[str, Any]]],
    ) -> tuple[_Entry, bool]:
        """``(entry, hit)``. ``build`` returns ``(body, options)`` where options may hold
        ``ttl_s``, ``valid_until`` and ``meta`` (see :meth:`put`). Identical concurrent misses
        wait for one build. Exceptions from ``build`` propagate to its caller only; waiters then
        build for themselves (errors are never cached)."""
        while True:
            hit = self.get(key)
            if hit is not None:
                with self._lock:
                    self.stats.hits += 1
                return hit, True
            with self._lock:
                flight = self._flights.get(key)
                leader = flight is None
                if leader:
                    flight = self._flights[key] = _Flight()
                    self.stats.misses += 1
                else:
                    self.stats.joins += 1
            if leader:
                try:
                    body, opts = build()
                    flight.entry = self.put(key, body, **opts)
                    return flight.entry, False
                finally:
                    with self._lock:
                        self._flights.pop(key, None)
                    flight.done.set()
            flight.done.wait()
            if flight.entry is not None and self._live(flight.entry):
                with self._lock:
                    self.stats.hits += 1
                return flight.entry, True
            # leader failed (or its answer was not storable/live): try again from the top


@dataclass
class Caches:
    """The response caches of one :class:`~winterpath_api.state.AppState`."""

    owner: Any
    enabled: bool
    segments: ResponseCache
    hazards: ResponseCache
    routes: ResponseCache


#: capacities (bytes are response-body bytes; a full segments page is ~0.2-0.4 MB of JSON)
SEGMENTS_MAX_ENTRIES, SEGMENTS_MAX_BYTES, SEGMENTS_TTL_S = 48, 12 * 2**20, 120.0
HAZARDS_MAX_ENTRIES, HAZARDS_MAX_BYTES, HAZARDS_TTL_S = 64, 6 * 2**20, 120.0
ROUTES_MAX_ENTRIES, ROUTES_MAX_BYTES, ROUTES_TTL_S = 32, 6 * 2**20, 300.0
#: a "leave now" route is reused for at most this long (its departure time moves on)
ROUTES_NOW_TTL_S = 60.0

_caches_lock = threading.Lock()


def caches_for(app_state: Any, wp_state: Any) -> Caches:
    """The caches attached to a Starlette ``app.state`` for the current ``AppState``; a new
    ``AppState`` (tests, reloads) gets fresh, empty caches."""
    with _caches_lock:
        c = getattr(app_state, "wp_caches", None)
        if c is None or c.owner is not wp_state:
            c = Caches(
                owner=wp_state,
                enabled=enabled_from_env(),
                segments=ResponseCache(
                    "segments",
                    max_entries=SEGMENTS_MAX_ENTRIES,
                    max_bytes=SEGMENTS_MAX_BYTES,
                    ttl_s=SEGMENTS_TTL_S,
                ),
                hazards=ResponseCache(
                    "hazards",
                    max_entries=HAZARDS_MAX_ENTRIES,
                    max_bytes=HAZARDS_MAX_BYTES,
                    ttl_s=HAZARDS_TTL_S,
                ),
                routes=ResponseCache(
                    "routes",
                    max_entries=ROUTES_MAX_ENTRIES,
                    max_bytes=ROUTES_MAX_BYTES,
                    ttl_s=ROUTES_TTL_S,
                ),
            )
            app_state.wp_caches = c
        return c


# ---------------------------------------------------------------------- data versions
def graph_version(state: Any) -> Hashable | None:
    """The loaded graph's identity: the pinned artifact SHA-256 when there is one, else this
    process's graph object (a graph never changes after start-up)."""
    if state.engine is None:
        return None
    sha = getattr(state.settings, "graph_artifact_sha256", "") or ""
    g = state.engine.graph
    return ("graph", sha or f"proc:{id(g):x}", len(g.edges), bool(g.metadata.simulated))


def risk_version(risk: Any, at: datetime) -> Hashable | None:
    """Version of the risk answers for ``at``, or ``None`` when it cannot be known (then the
    caller must not cache). Known: no risk layer at all, or a whole-graph snapshot (compact
    graphs: one snapshot per Montréal day, rebuilt every few minutes)."""
    from winterpath_routing import NullRiskProvider

    if type(risk) is NullRiskProvider:
        return ("risk", "none")
    snap_fn = getattr(risk, "edge_risk_snapshot", None)
    if getattr(risk, "risk_layer", None) == "none" and callable(snap_fn):
        return ("risk", "none")  # CoordinateRiskAdapter with no layer: always unknown
    if not callable(snap_fn):
        return None
    try:
        snap = snap_fn(at)
    except Exception:
        return None
    version = getattr(snap, "version", None)
    return ("risk", version) if version is not None else None


def hazard_version(hazards_repo: Any, at: datetime) -> tuple[list[Any], Hashable | None]:
    """``(hazards, version)`` from one repository read. ``version`` is ``None`` when the
    repository cannot tell whether its list changed (no TTL cache) — callers then don't cache."""
    fn = getattr(hazards_repo, "list_versioned", None)
    if callable(fn):
        return fn(at)
    return hazards_repo.list(at), None


__all__ = [
    "CacheStats",
    "Caches",
    "ResponseCache",
    "caches_for",
    "enabled_from_env",
    "graph_version",
    "hazard_version",
    "key_digest",
    "norm_bbox",
    "norm_coord",
    "risk_version",
]
