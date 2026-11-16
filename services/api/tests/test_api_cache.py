"""Response caches (``winterpath_api.cache``): bounds, TTL, validity horizon, single flight, and
that every cached answer is the answer the API would have computed (SYNTHETIC toy-grid data)."""

from __future__ import annotations

import json
import random
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from api_testlib import grid, validate_response
from winterpath_routing import (
    Evidence,
    EvidenceState,
    Hazard,
    HazardKind,
    RiskEstimate,
    RiskLevel,
)

from winterpath_api import cache as cache_mod
from winterpath_api.cache import ResponseCache, key_digest, norm_bbox
from winterpath_api.params import bbox_intersects
from winterpath_api.repositories.hazards import InMemoryHazardRepository
from winterpath_api.repositories.reports import InMemoryReportRepository
from winterpath_api.routers import map as map_router
from winterpath_api.routers import routing as routing_router

BBOX_OK = "-73.5790,45.5025,-73.5740,45.5050"
SEG_URL = f"/api/v1/map/segments?bbox={BBOX_OK}&limit=50"
ROUTE = {"origin": grid(0, 0), "destination": grid(0, 2)}


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


# ---------------------------------------------------------------------------- ResponseCache
def test_cache_is_bounded_by_entries_and_bytes() -> None:
    c = ResponseCache("t", max_entries=3, max_bytes=100, ttl_s=60, max_entry_bytes=100)
    for i in range(5):
        c.put(i, b"x" * 10)
    assert len(c) == 3 and c.get(0) is None and c.get(4) is not None
    c.get(2)  # 2 becomes most recently used
    c.put("big", b"y" * 85)  # 30 + 85 > 100 → evict LRU until it fits
    assert c.nbytes <= 100
    assert c.get("big") is not None
    assert c.get(3) is None  # least recently used went first
    assert c.stats.evictions >= 3


def test_oversized_body_is_served_but_not_stored() -> None:
    c = ResponseCache("t", max_entries=3, max_bytes=100, ttl_s=60)  # max entry = 25 bytes
    entry, hit = c.get_or_build("k", lambda: (b"z" * 40, {}))
    assert entry.body == b"z" * 40 and not hit
    assert len(c) == 0 and c.nbytes == 0


def test_ttl_and_validity_horizon() -> None:
    clock = Clock()
    wall = [datetime(2026, 12, 1, 12, 0, tzinfo=UTC)]
    c = ResponseCache(
        "t", max_entries=8, max_bytes=1000, ttl_s=60, clock=clock, wall=lambda: wall[0]
    )
    c.put("a", b"1")
    c.put("b", b"2", ttl_s=10)
    c.put("c", b"3", ttl_s=600)  # capped at the cache TTL (60 s)
    c.put("d", b"4", valid_until=wall[0] + timedelta(seconds=5))
    clock.t += 6
    wall[0] += timedelta(seconds=6)
    assert c.get("d") is None  # a hazard boundary passed: never served after it
    assert c.get("b") is not None
    clock.t += 5
    assert c.get("b") is None
    assert c.get("a") is not None and c.get("c") is not None
    clock.t += 50
    assert c.get("a") is None and c.get("c") is None
    assert c.nbytes == 0


def test_single_flight_builds_once_and_errors_are_not_cached() -> None:
    c = ResponseCache("t", max_entries=8, max_bytes=10_000, ttl_s=60)
    calls = 0
    gate = threading.Event()

    def build():
        nonlocal calls
        calls += 1
        gate.wait(2)
        return b"body", {}

    results: list[tuple[bytes, bool]] = []

    def worker():
        e, hit = c.get_or_build("k", build)
        results.append((e.body, hit))

    ts = [threading.Thread(target=worker) for _ in range(6)]
    for t in ts:
        t.start()
    time.sleep(0.1)
    gate.set()
    for t in ts:
        t.join()
    assert calls == 1
    assert [b for b, _ in results] == [b"body"] * 6
    assert sum(1 for _, hit in results if not hit) == 1

    def boom():
        raise RuntimeError("upstream down")

    with pytest.raises(RuntimeError):
        c.get_or_build("err", boom)
    assert c.get("err") is None
    e, hit = c.get_or_build("err", lambda: (b"ok", {}))
    assert e.body == b"ok" and not hit


def test_key_digest_hides_coordinates() -> None:
    key = ("routes", (-73.567891, 45.501234))
    d = key_digest(key)
    assert len(d) == 12
    assert "-73.567891" not in d and "45.501234" not in d
    assert key_digest(key) == d and key_digest(("routes", (-73.567892, 45.501234))) != d


def test_norm_bbox_is_canonical() -> None:
    assert norm_bbox((-73.5790000001, 45.5025, -0.0, 45.505)) == (-73.579, 45.5025, 0.0, 45.505)


# ---------------------------------------------------------------------------- /map/segments
def _count_segments(monkeypatch) -> list[int]:
    calls = [0]
    real = map_router._segments

    def counting(*a, **k):
        calls[0] += 1
        return real(*a, **k)

    monkeypatch.setattr(map_router, "_segments", counting)
    return calls


def test_segments_cached_body_is_identical(make_client, monkeypatch) -> None:
    calls = _count_segments(monkeypatch)
    c = make_client()
    r1, r2 = c.get(SEG_URL), c.get(SEG_URL)
    assert r1.status_code == r2.status_code == 200
    assert r1.headers["content-type"].startswith("application/geo+json")
    validate_response(r2, "/map/segments", "get")
    assert r1.content == r2.content and calls[0] == 1
    # same box written differently (trailing zeros) is the same key
    assert c.get(SEG_URL.replace("45.5025", "45.502500")).content == r1.content
    assert calls[0] == 1
    # another page, another box: built
    c.get(SEG_URL.replace("limit=50", "limit=10"))
    assert calls[0] == 2

    monkeypatch.setenv(cache_mod.ENV_SWITCH, "false")
    off = make_client()
    r3, r4 = off.get(SEG_URL), off.get(SEG_URL)
    assert calls[0] == 4  # kill switch: built every time
    assert json.loads(r3.content) == json.loads(r1.content) == json.loads(r4.content)


def test_segments_not_built_for_a_client_that_left(make_client, monkeypatch) -> None:
    calls = _count_segments(monkeypatch)

    async def gone(self) -> bool:
        return True

    monkeypatch.setattr("starlette.requests.Request.is_disconnected", gone)
    r = make_client().get(SEG_URL)
    assert r.status_code == map_router.CLIENT_CLOSED and calls[0] == 0


def test_segments_with_unknowable_risk_version_are_not_cached(make_client, monkeypatch) -> None:
    calls = _count_segments(monkeypatch)

    class OpaqueRisk:  # no snapshot, not the null provider: answers could change any time
        risk_layer = "heuristic"

        def edge_risk(self, edge_ids, at):
            return {e: RiskEstimate.unknown("test") for e in edge_ids}

    c = make_client(risk=OpaqueRisk())
    c.get(SEG_URL)
    c.get(SEG_URL)
    assert calls[0] == 2


# ---------------------------------------------------------------------------- /hazards
def _closure(i: int, lon: float, lat: float, **kw) -> Hazard:
    return Hazard(
        hazard_id=f"entrave:test-{i:03d}",
        kind=HazardKind.SIDEWALK_CLOSURE,
        geometry={"type": "Point", "coordinates": [lon, lat]},
        evidence=Evidence(EvidenceState.CONFIRMED, ("test",)),
        blocks_passage=True,
        **kw,
    )


def test_hazard_index_matches_plain_scan() -> None:
    rng = random.Random(7)
    hazards = []
    for i in range(300):
        lon, lat = -73.60 + rng.random() * 0.05, 45.49 + rng.random() * 0.03
        if i % 3 == 0:  # some lines and polygons too
            geom = {"type": "LineString", "coordinates": [[lon, lat], [lon + 0.002, lat + 0.001]]}
        elif i % 3 == 1:
            d = 0.0007
            ring = [[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]
            geom = {"type": "Polygon", "coordinates": [ring]}
        else:
            geom = {"type": "Point", "coordinates": [lon, lat]}
        hazards.append(
            Hazard(
                hazard_id=f"h{i:03d}",
                kind=HazardKind.SIDEWALK_CLOSURE,
                geometry=geom,
                evidence=Evidence(EvidenceState.CONFIRMED, ("test",)),
            )
        )
    for _ in range(50):
        w, s = -73.61 + rng.random() * 0.05, 45.48 + rng.random() * 0.03
        box = (w, s, w + rng.random() * 0.02, s + rng.random() * 0.01)
        scan = [h for h in hazards if bbox_intersects(h.geometry, box)]
        assert map_router._hazards_in(hazards, ("test", 1), box) == scan


def test_hazards_cache_follows_the_list_version(make_client) -> None:
    a = grid(0, 0)
    reports = InMemoryReportRepository()
    repo = InMemoryHazardRepository(reports, [_closure(1, a["lon"], a["lat"])])
    c = make_client(reports=reports, hazards=repo)
    url = f"/api/v1/hazards?bbox={BBOX_OK}"
    r1 = c.get(url)
    validate_response(r1, "/hazards", "get")
    assert c.get(url).content == r1.content
    caches = c.app.state.wp_caches
    assert caches.hazards.stats.hits == 1
    # a new hazard in the list → new version → rebuilt, never the old answer
    repo.hazards.append(_closure(2, a["lon"] + 0.0005, a["lat"]))
    ids = [f["id"] for f in c.get(url).json()["features"]]
    assert ids == ["entrave:test-001", "entrave:test-002"]
    # a hazard whose validity ended drops out at once (the active set is part of the version)
    repo.hazards[1] = _closure(
        2, a["lon"] + 0.0005, a["lat"], valid_to=datetime.now(UTC) - timedelta(seconds=1)
    )
    assert [f["id"] for f in c.get(url).json()["features"]] == ["entrave:test-001"]
    # evidence states pass through unchanged
    assert c.get(url).json()["features"][0]["properties"]["evidence"]["state"] == "confirmed"


# ---------------------------------------------------------------------------- /routes/compare
def _count_compare(c) -> list[int]:
    engine = c.app.state.wp.engine
    real = engine.compare
    calls = [0]

    def counting(*a, **k):
        calls[0] += 1
        return real(*a, **k)

    engine.compare = counting
    return calls


def test_route_cache_hit_is_the_same_answer_with_its_own_request_id(make_client) -> None:
    c = make_client()
    calls = _count_compare(c)
    r1 = c.post("/api/v1/routes/compare", json=ROUTE)
    r2 = c.post("/api/v1/routes/compare", json=ROUTE)
    validate_response(r2, "/routes/compare", "post")
    assert calls[0] == 1
    j1, j2 = r1.json(), r2.json()
    assert j1["request_id"] == r1.headers["X-Request-ID"]
    assert j2["request_id"] == r2.headers["X-Request-ID"] != j1["request_id"]
    j1.pop("request_id"), j2.pop("request_id")
    assert j1 == j2  # computed_at is the original computation time (honest age of the answer)
    for route in j2["routes"]:
        assert {e["evidence_state"] for e in route["explanation"]} <= {
            "confirmed",
            "unverified_report",
            "model_estimate",
            "unknown",
            "simulated",
        }


@pytest.mark.parametrize(
    "change",
    [
        {"locale": "fr"},
        {"profile": "step_free"},
        {"avoid_unverified_reports": False},
        {"departure_time": "2026-12-01T08:00:00Z"},
        {"destination": grid(0, 3)},
        {"origin": {**grid(0, 0), "lon": grid(0, 0)["lon"] + 1e-6}},
    ],
)
def test_route_cache_key_includes_every_input(make_client, change) -> None:
    c = make_client()
    calls = _count_compare(c)
    c.post("/api/v1/routes/compare", json=ROUTE)
    r = c.post("/api/v1/routes/compare", json={**ROUTE, **change})
    assert r.status_code in (200, 404)
    assert calls[0] == 2


def test_explicit_departure_is_not_shared_with_leave_now(make_client) -> None:
    c = make_client()
    calls = _count_compare(c)
    dep = {**ROUTE, "departure_time": "2026-12-01T08:00:00Z"}
    c.post("/api/v1/routes/compare", json=dep)
    c.post("/api/v1/routes/compare", json={**dep, "departure_time": "2026-12-01T03:00:00-05:00"})
    assert calls[0] == 1  # the same instant written with another offset
    c.post("/api/v1/routes/compare", json=ROUTE)
    assert calls[0] == 2


def test_route_not_cached_when_hazard_version_unknown(make_client) -> None:
    class Unversioned(InMemoryHazardRepository):
        def list_versioned(self, at):  # cannot say whether its list changed
            return super().list_versioned(at)[0], None

    reports = InMemoryReportRepository()
    c = make_client(reports=reports, hazards=Unversioned(reports))
    calls = _count_compare(c)
    c.post("/api/v1/routes/compare", json=ROUTE)
    c.post("/api/v1/routes/compare", json=ROUTE)
    assert calls[0] == 2


def test_leave_now_route_expires_at_next_hazard_change(make_client) -> None:
    """A listed closure that stops applying in 30 s bounds a "leave now" answer (a closure that
    starts later is not listed yet; when it starts, the list version changes instead)."""
    a = grid(0, 0)
    end = datetime.now(UTC) + timedelta(seconds=30)
    reports = InMemoryReportRepository()
    ending = _closure(9, a["lon"] + 0.0005, a["lat"], valid_to=end)
    c = make_client(reports=reports, hazards=InMemoryHazardRepository(reports, [ending]))
    c.post("/api/v1/routes/compare", json=ROUTE)
    entry = next(iter(c.app.state.wp_caches.routes._data.values()))
    assert entry.valid_until == end
    assert routing_router._next_activity_change([ending], end) is None
    starting = _closure(10, a["lon"], a["lat"], valid_from=end)
    assert routing_router._next_activity_change([starting], end - timedelta(seconds=1)) == end
    # an explicit departure time has no horizon (its time does not move)
    c.post("/api/v1/routes/compare", json={**ROUTE, "departure_time": "2026-12-01T08:00:00Z"})
    assert sum(e.valid_until is None for e in c.app.state.wp_caches.routes._data.values()) == 1


def test_weather_context_is_evaluated_per_request(make_client) -> None:
    class Live:
        n = 0

        def context_at(self, at):
            self.n += 1
            return {
                "departure_time": at,
                "used_for": "display_only",
                "freshness": {
                    "state": "current",
                    "reason": f"call {self.n}",
                    "evaluated_at": datetime.now(UTC),
                },
            }

    c = make_client(live_weather=Live())
    calls = _count_compare(c)
    w1 = c.post("/api/v1/routes/compare", json=ROUTE).json()["weather_context"]
    w2 = c.post("/api/v1/routes/compare", json=ROUTE).json()["weather_context"]
    assert calls[0] == 1
    assert w1["freshness"]["reason"] == "call 1" and w2["freshness"]["reason"] == "call 2"


# ---------------------------------------------------------------------------- risk snapshots
def test_snapshot_version_is_stable_until_estimates_change() -> None:
    import numpy as np

    from winterpath_api.risk_cells import RiskCellIndex, SnapshotSource

    index = RiskCellIndex(["a", "b"], np.array([0, 1, 2]), np.array([0, 1], dtype=np.int32))
    clock = Clock()
    level = {"b": RiskLevel.LOW}

    def est(cell, at):
        if cell == "a":
            return RiskEstimate.unknown("no score")
        return RiskEstimate(level["b"], Evidence(EvidenceState.MODEL_ESTIMATE, ("m",)), 0.1)

    src = SnapshotSource(index, est, lambda at: at.date(), ttl_s=300, clock=clock)
    at = datetime(2026, 12, 1, 12, tzinfo=UTC)
    s1 = src.at(at)
    clock.t += 301
    s2 = src.at(at)
    assert s2 is s1 and s2.version == s1.version  # rebuilt, nothing changed → same version
    assert s1.estimate(0).is_unknown  # unknown stays unknown
    level["b"] = RiskLevel.HIGH
    clock.t += 301
    s3 = src.at(at)
    assert s3.version != s1.version and s3.estimate(1).level is RiskLevel.HIGH
