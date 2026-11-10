"""API on the REAL OSM pilot_mini fixture (simulated=false). Responses validated against the
contract; nothing on this graph may be flagged SIMULATED, and risk stays unknown (no layer)."""

from __future__ import annotations

import json
import random
import statistics
import time

import pytest
from api_testlib import PILOT_MINI, validate_response

pytestmark = pytest.mark.skipif(
    not (PILOT_MINI / "edges.geojson").exists(), reason="data/fixtures/pilot_mini not present"
)

META = json.loads((PILOT_MINI / "metadata.json").read_text()) if PILOT_MINI.exists() else {}
W, S, E, N = META.get("bbox", [0, 0, 0, 0])
BBOX = f"{W:.6f},{S:.6f},{E:.6f},{N:.6f}"


@pytest.fixture
def real(make_client):
    return make_client(fixture_dir=PILOT_MINI)


def _node_points(k: int, seed: int) -> list[dict]:
    feats = json.loads((PILOT_MINI / "nodes.geojson").read_text())["features"]
    rnd = random.Random(seed)
    return [
        {"lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1]}
        for f in rnd.sample(feats, k)
    ]


def test_health_and_coverage_report_real_graph(real) -> None:
    h = real.get("/api/v1/health")
    validate_response(h, "/health", "get")
    assert h.json()["checks"]["graph"]["status"] == "ok"
    c = real.get("/api/v1/coverage")
    validate_response(c, "/coverage", "get")
    g = c.json()["graph"]
    assert (g["node_count"], g["edge_count"]) == (88, 200)
    assert g["osm_snapshot"] == META["osm_snapshot"]
    assert g["largest_component_share"] == 1.0
    assert not any("SIMULATED" in x["description"] for x in c.json()["known_gaps"])


@pytest.mark.parametrize("profile", ["standard", "reduced_mobility", "step_free"])
@pytest.mark.parametrize("locale", ["en", "fr"])
def test_compare_on_real_graph_schema_valid(real, profile, locale) -> None:
    pts = _node_points(16, seed=11)
    statuses = []
    for o, d in zip(pts[::2], pts[1::2], strict=True):
        r = real.post(
            "/api/v1/routes/compare",
            json={"origin": o, "destination": d, "profile": profile, "locale": locale},
        )
        validate_response(r, "/routes/compare", "post")
        statuses.append(r.status_code)
        if r.status_code != 200:
            assert profile == "step_free" and r.json()["code"] in ("NO_ROUTE", "OUTSIDE_COVERAGE")
            continue
        body = r.json()
        assert not any(w.startswith(("SIMULATED", "SIMULÉ")) for w in body["warnings"])
        for route in body["routes"]:
            assert route["unknown_share"] == 1.0
            codes = [x["code"] for x in route["explanation"]]
            assert "SIMULATED_DATA" not in codes and "RISK_LAYER_UNAVAILABLE" in codes
            assert set(route["data_freshness"]) >= {"osm"}
    if profile != "step_free":
        assert set(statuses) == {200}


def test_segments_on_real_graph(real) -> None:
    seen, cursor = [], None
    while True:
        q = f"/api/v1/map/segments?bbox={BBOX}&limit=60" + (f"&cursor={cursor}" if cursor else "")
        r = real.get(q)
        validate_response(r, "/map/segments", "get")
        body = r.json()
        for f in body["features"]:
            p = f["properties"]
            assert p["risk"]["level"] == "unknown" and "synthetic" not in p["sources"]
            if p["edge_kind"] == "crossing":
                assert p["crossing"]["type"] in ("marked", "traffic_signals", "unmarked")
        seen += [f["id"] for f in body["features"]]
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 200


def test_api_latency_real_pilot_mini(real, capsys) -> None:
    pts = _node_points(80, seed=5)
    rnd = random.Random(6)
    times = []
    for _ in range(100):
        o, d = rnd.sample(pts, 2)
        t0 = time.perf_counter()
        r = real.post("/api/v1/routes/compare", json={"origin": o, "destination": d})
        times.append(time.perf_counter() - t0)
        assert r.status_code == 200, r.text
    times.sort()
    with capsys.disabled():
        print(
            f"\n[latency] API POST /routes/compare REAL pilot_mini (200 edges), n=100 node-pair "
            f"ODs: p50={statistics.median(times) * 1000:.1f} ms p95={times[94] * 1000:.1f} ms "
            f"max={times[-1] * 1000:.1f} ms"
        )
    assert times[94] < 2.0
