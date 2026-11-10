"""Every v1 endpoint exists and its responses validate against docs/contracts/openapi.yaml.

Graph = SYNTHETIC toy grid (simulated=True). No real data, weather or risk is fabricated.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from api_testlib import grid, spec, validate_response, validate_schema
from winterpath_routing import (
    Edge,
    Evidence,
    EvidenceState,
    GraphData,
    GraphMetadata,
    Hazard,
    HazardKind,
    Node,
)
from winterpath_routing.geo import metric_length_m

BBOX_OK = "-73.5790,45.5025,-73.5740,45.5050"


def test_all_contract_operations_are_implemented(client) -> None:
    generated = client.get("/api/v1/openapi.json").json()["paths"]
    app_ops = {(path, m.lower()) for path, ops in generated.items() for m in ops}
    for path, ops in spec()["paths"].items():
        for method in ops:
            assert (f"/api/v1{path}", method) in app_ops, f"{method.upper()} {path} missing"


# ----------------------------------------------------------------------------- system
def test_health(client) -> None:
    r = client.get("/api/v1/health")
    validate_response(r, "/health", "get")
    body = r.json()
    assert body["checks"]["graph"]["status"] == "degraded"  # SIMULATED fixture
    assert body["checks"]["risk"]["status"] == "disabled"
    assert body["checks"]["weather"]["status"] == "disabled"
    assert r.headers["x-request-id"]


def test_health_without_graph(make_client, tmp_path) -> None:
    c = make_client(fixture_dir=tmp_path)
    r = c.get("/api/v1/health")
    validate_response(r, "/health", "get")
    assert r.json()["checks"]["graph"]["status"] == "down"
    r = c.post("/api/v1/routes/compare", json={"origin": grid(0, 0), "destination": grid(0, 2)})
    assert r.status_code == 503 and r.json()["code"] == "UPSTREAM_UNAVAILABLE"
    validate_schema(r.json(), "Error")
    cov = c.get("/api/v1/coverage")
    validate_response(cov, "/coverage", "get")
    assert cov.json()["graph"]["edge_count"] == 0


def test_coverage_reports_gaps_and_simulation(client) -> None:
    r = client.get("/api/v1/coverage")
    validate_response(r, "/coverage", "get")
    body = r.json()
    assert body["bbox"] == [-73.588, 45.496, -73.562, 45.513]
    assert body["graph"]["edge_count"] == 38
    descs = [g["description"] for g in body["known_gaps"]]
    assert any(d.startswith("SIMULATED") for d in descs)
    assert any("Disconnected" in d for d in descs)


def test_data_sources_never_claim_ingestion(client) -> None:
    r = client.get("/api/v1/data-sources")
    validate_response(r, "/data-sources", "get")
    rows = r.json()
    assert {s["id"] for s in rows} >= {"osm", "mtl-311", "mtl-entraves", "eccc-geomet"}
    for s in rows:
        assert s["status"] in ("disabled", "requires_credentials")
        assert s["last_success_at"] is None and s["record_count"] is None


def test_model_status_reports_no_layer(client) -> None:
    r = client.get("/api/v1/models/status")
    validate_response(r, "/models/status", "get")
    body = r.json()
    assert body["risk_layer"] == "none" and body["enabled"] is False
    assert body["evaluation"] is None


@pytest.mark.parametrize("path", ["/weather/current", "/weather/forecast"])
def test_weather_unavailable_is_503_not_invented(client, path) -> None:
    r = client.get(f"/api/v1{path}")
    assert r.status_code == 503
    validate_response(r, path, "get")
    body = r.json()
    assert body["code"] == "UPSTREAM_UNAVAILABLE"
    assert "temperature_c" not in r.text


def test_weather_adapter_payload_is_validated(make_client) -> None:
    class FixtureWeather:  # TEST FIXTURE values, not real observations
        def current(self):
            return {
                "station_id": "TEST",
                "observed_at": "2026-12-01T12:00:00Z",
                "temperature_c": -5.0,
                "evidence": {
                    "state": "simulated",
                    "source_ids": ["test"],
                    "observed_at": "2026-12-01T12:00:00Z",
                },
            }

        def forecast(self, hours):
            from winterpath_api.adapters import WeatherUnavailableError

            raise WeatherUnavailableError("down")

    c = make_client(weather=FixtureWeather())
    r = c.get("/api/v1/weather/current")
    validate_response(r, "/weather/current", "get")
    assert r.json()["evidence"]["state"] == "simulated"
    r = c.get("/api/v1/weather/forecast?hours=12")
    assert r.status_code == 503
    assert c.get("/api/v1/weather/forecast?hours=49").status_code == 422


def test_pilot_requests(client) -> None:
    ok = {
        "organization": "Test Org",
        "contact_email": "person@example.org",
        "segment": "university",
        "consent": True,
    }
    r = client.post("/api/v1/pilot-requests", json=ok)
    validate_response(r, "/pilot-requests", "post")
    assert r.status_code == 201
    for bad in (
        {**ok, "consent": False},
        {**ok, "contact_email": "nope"},
        {**ok, "segment": "bank"},
        {**ok, "extra": 1},
    ):
        r = client.post("/api/v1/pilot-requests", json=bad)
        assert r.status_code == 422
        validate_response(r, "/pilot-requests", "post")
        assert "person@example.org" not in r.text  # inputs never echoed


# ----------------------------------------------------------------------------- routing
@pytest.mark.parametrize("profile", ["standard", "step_free", "reduced_mobility"])
@pytest.mark.parametrize("locale", ["en", "fr"])
def test_compare_routes_schema_valid(client, profile, locale) -> None:
    body = {"origin": grid(0, 0), "destination": grid(2, 3), "profile": profile, "locale": locale}
    r = client.post("/api/v1/routes/compare", json=body)
    assert r.status_code == 200, r.text
    validate_response(r, "/routes/compare", "post")
    data = r.json()
    assert [x["variant"] for x in data["routes"]] == ["shortest", "winter_aware"]
    assert data["risk_layer"] == "none"
    for route in data["routes"]:
        assert route["unknown_share"] == 1.0  # unknown flows through as unknown
        codes = [e["code"] for e in route["explanation"]]
        assert codes[0] == "SIMULATED_DATA" and "RISK_LAYER_UNAVAILABLE" in codes
        lon, lat = route["geometry"]["coordinates"][0]
        assert -74 < lon < -73 and 45 < lat < 46  # [lon, lat]
    assert any(w.startswith(("SIMULATED", "SIMULÉ")) for w in data["warnings"])


def test_compare_routes_error_cases(client) -> None:
    url = "/api/v1/routes/compare"

    def check(resp, status, code):
        assert resp.status_code == status, resp.text
        validate_response(resp, "/routes/compare", "post")
        assert resp.json()["code"] == code
        assert resp.json()["request_id"]

    outside = {"lon": -73.60, "lat": 45.50}
    check(
        client.post(url, json={"origin": outside, "destination": grid(0, 0)}),
        422,
        "OUTSIDE_COVERAGE",
    )
    # inside the pilot bbox but > 75 m from any routable edge
    far = {"lon": -73.570, "lat": 45.510}
    r = client.post(url, json={"origin": grid(0, 0), "destination": far})
    check(r, 422, "OUTSIDE_COVERAGE")
    assert r.json()["details"]["which"] == "destination"
    check(
        client.post(url, content=b"{not json", headers={"content-type": "application/json"}),
        400,
        "VALIDATION_ERROR",
    )
    check(client.post(url, json={"origin": grid(0, 0)}), 422, "VALIDATION_ERROR")
    check(
        client.post(url, json={"origin": grid(0, 0), "destination": grid(0, 1), "x": 1}),
        422,
        "VALIDATION_ERROR",
    )
    check(
        client.post(url, json={"origin": {"lon": -73.5, "lat": 91}, "destination": grid(0, 1)}),
        422,
        "VALIDATION_ERROR",
    )
    check(
        client.post(url, json={"origin": grid(0, 0), "destination": grid(0, 1), "profile": "bike"}),
        422,
        "VALIDATION_ERROR",
    )
    check(
        client.post(url, json={"origin": grid(0, 0), "destination": grid(0, 0)}),
        422,
        "VALIDATION_ERROR",
    )


class _StepGapProvider:
    """SYNTHETIC: A–B step-free, B–C unknown, C–D step-free (inside pilot bbox)."""

    def load(self) -> GraphData:
        lon, lat, d = -73.575, 45.505, 0.0008
        pts = {
            "A": (lon, lat),
            "B": (lon + d, lat),
            "C": (lon + 2 * d, lat),
            "D": (lon + 3 * d, lat),
        }
        nodes = {k: Node(k, *v) for k, v in pts.items()}
        edges = []
        for (u, v), sf in zip(
            (("A", "B"), ("B", "C"), ("C", "D")), (True, None, True), strict=True
        ):
            for a, b in ((u, v), (v, u)):
                coords = (pts[a], pts[b])
                edges.append(
                    Edge(
                        f"{a}>{b}:0",
                        a,
                        b,
                        coords,
                        metric_length_m(coords),
                        "footway",
                        "yes",
                        step_free=sf,
                        source_ids=("synthetic",),
                    )
                )
        return GraphData(nodes, edges, GraphMetadata(simulated=True))


def test_step_free_no_route_returns_404(make_client) -> None:
    c = make_client(graph_provider=_StepGapProvider())
    body = {
        "origin": {"lon": -73.575, "lat": 45.505},
        "destination": {"lon": -73.575 + 0.0024, "lat": 45.505},
    }
    assert c.post("/api/v1/routes/compare", json=body).status_code == 200
    r = c.post("/api/v1/routes/compare", json={**body, "profile": "step_free"})
    assert r.status_code == 404
    validate_response(r, "/routes/compare", "post")
    assert r.json()["code"] == "NO_ROUTE"


def test_confirmed_closure_excluded_end_to_end(make_client) -> None:
    a, b = grid(0, 0), grid(0, 1)
    closure = Hazard(
        hazard_id="entrave:test-1",
        kind=HazardKind.SIDEWALK_CLOSURE,
        geometry={"type": "Point", "coordinates": [(a["lon"] + b["lon"]) / 2, a["lat"]]},
        evidence=Evidence(EvidenceState.CONFIRMED, ("test",)),
        blocks_passage=True,
    )
    from winterpath_api.repositories.hazards import InMemoryHazardRepository
    from winterpath_api.repositories.reports import InMemoryReportRepository

    reports = InMemoryReportRepository()
    c = make_client(reports=reports, hazards=InMemoryHazardRepository(reports, [closure]))
    r = c.post("/api/v1/routes/compare", json={"origin": a, "destination": b})
    validate_response(r, "/routes/compare", "post")
    for route in r.json()["routes"]:
        assert "syn:r0c0>syn:r0c1:0" not in route["edge_ids"]
        assert "EXCLUDES_CONFIRMED_CLOSURE" in [e["code"] for e in route["explanation"]]
    h = c.get(f"/api/v1/hazards?bbox={BBOX_OK}")
    validate_response(h, "/hazards", "get")
    feat = h.json()["features"][0]
    assert feat["properties"]["evidence"]["state"] == "confirmed"
    assert feat["properties"]["blocks_passage"] is True


def test_departure_time_without_offset_rejected(client) -> None:
    r = client.post(
        "/api/v1/routes/compare",
        json={
            "origin": grid(0, 0),
            "destination": grid(0, 2),
            "departure_time": "2026-12-01T08:00:00",
        },
    )
    assert r.status_code == 422


# ----------------------------------------------------------------------------- map
def test_hazards_bbox_validation(client) -> None:
    for q, status, code in [
        ("", 400, "VALIDATION_ERROR"),
        ("?bbox=abc", 400, "VALIDATION_ERROR"),
        ("?bbox=-73.57,45.50,-73.58,45.51", 400, "VALIDATION_ERROR"),
        ("?bbox=-73.70,45.40,-73.50,45.60", 422, "BBOX_TOO_LARGE"),
        ("?bbox=-73.70,45.40,-73.69,45.41", 422, "OUTSIDE_COVERAGE"),
        (f"?bbox={BBOX_OK}&kind=volcano", 400, "VALIDATION_ERROR"),
        (f"?bbox={BBOX_OK}&cursor=!!!", 400, "VALIDATION_ERROR"),
    ]:
        r = client.get(f"/api/v1/hazards{q}")
        assert r.status_code == status, (q, r.text)
        validate_response(r, "/hazards", "get")
        assert r.json()["code"] == code
    r = client.get(f"/api/v1/hazards?bbox={BBOX_OK}&kind=sidewalk_closure,community_report")
    validate_response(r, "/hazards", "get")
    assert r.headers["content-type"].startswith("application/geo+json")
    assert r.json() == {"type": "FeatureCollection", "features": [], "next_cursor": None}


def test_segments_pagination_and_unknown_risk(client) -> None:
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        q = f"/api/v1/map/segments?bbox={BBOX_OK}&limit=7" + (f"&cursor={cursor}" if cursor else "")
        r = client.get(q)
        validate_response(r, "/map/segments", "get")
        assert r.headers["content-type"].startswith("application/geo+json")
        body = r.json()
        for f in body["features"]:
            assert f["properties"]["risk"]["level"] == "unknown"
            assert f["properties"]["risk"]["evidence"]["state"] == "unknown"
            assert "synthetic" in f["properties"]["sources"]
        seen += [f["id"] for f in body["features"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    # 38 directed edges − 2 foot_access=no − 2 isolated (outside bbox) = 34
    assert len(seen) == len(set(seen)) == 34
    assert pages == 5
    crossing = client.get(f"/api/v1/map/segments?bbox={BBOX_OK}&limit=1000").json()
    kinds = {f["properties"]["edge_kind"] for f in crossing["features"]}
    assert "crossing" in kinds and "steps" in kinds


# ----------------------------------------------------------------------------- reports
def _report(client, **kw):
    body = {"category": "ice", "location": grid(1, 1), "location_consent": True, **kw}
    return client.post("/api/v1/reports", json=body)


def test_report_lifecycle_and_moderation(client, admin) -> None:
    r = _report(client, description="Patch of ice near the steps")
    assert r.status_code == 201
    validate_response(r, "/reports", "post")
    receipt = r.json()
    rid, token = receipt["id"], receipt["deletion_token"]
    assert receipt["status"] == "pending" and len(token) >= 32

    # pending reports never appear as guidance
    hz = client.get(f"/api/v1/hazards?bbox={BBOX_OK}").json()
    assert hz["features"] == []

    lst = client.get("/api/v1/admin/reports?status=pending", headers=admin)
    validate_response(lst, "/admin/reports", "get")
    assert [i["id"] for i in lst.json()["items"]] == [rid]

    m = client.post(
        f"/api/v1/admin/reports/{rid}/moderation",
        headers=admin,
        json={"decision": "approve", "note": "ok"},
    )
    validate_response(m, "/admin/reports/{reportId}/moderation", "post")
    assert m.json()["status"] == "approved"

    hz = client.get(f"/api/v1/hazards?bbox={BBOX_OK}")
    validate_response(hz, "/hazards", "get")
    f = hz.json()["features"][0]
    assert f["properties"]["kind"] == "community_report"
    assert f["properties"]["evidence"]["state"] == "unverified_report"
    assert f["properties"]["blocks_passage"] is None

    route = client.post(
        "/api/v1/routes/compare", json={"origin": grid(1, 0), "destination": grid(1, 2)}
    )
    validate_response(route, "/routes/compare", "post")

    # deletion: wrong token / missing token / bad id → 404; right token → 204
    bad = client.delete(f"/api/v1/reports/{rid}", headers={"X-Deletion-Token": "x" * 40})
    assert bad.status_code == 404
    validate_response(bad, "/reports/{reportId}", "delete")
    assert client.delete(f"/api/v1/reports/{rid}").status_code == 404
    assert (
        client.delete("/api/v1/reports/not-a-uuid", headers={"X-Deletion-Token": token}).status_code
        == 404
    )
    ok = client.delete(f"/api/v1/reports/{rid}", headers={"X-Deletion-Token": token})
    assert ok.status_code == 204
    assert (
        client.delete(f"/api/v1/reports/{rid}", headers={"X-Deletion-Token": token}).status_code
        == 404
    )
    assert client.get(f"/api/v1/hazards?bbox={BBOX_OK}").json()["features"] == []
    deleted = client.get("/api/v1/admin/reports?status=deleted", headers=admin).json()["items"]
    assert deleted[0]["description"] is None


def test_report_validation(client) -> None:
    for kw, status in [
        ({"location_consent": False}, 422),
        ({"description": "x" * 281}, 422),
        ({"category": "pothole"}, 422),
        ({"location": {"lon": -73.7, "lat": 45.5}}, 422),
    ]:
        r = _report(client, **kw)
        assert r.status_code == status
        validate_response(r, "/reports", "post")


def test_admin_auth(client, admin) -> None:
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic abc"}):
        r = client.get("/api/v1/admin/reports", headers=headers)
        assert r.status_code == 401
        validate_response(r, "/admin/reports", "get")
        assert r.headers["www-authenticate"] == "Bearer"
    r = client.post(
        "/api/v1/admin/reports/00000000-0000-0000-0000-000000000000/moderation",
        headers=admin,
        json={"decision": "approve"},
    )
    assert r.status_code == 404
    validate_response(r, "/admin/reports/{reportId}/moderation", "post")


def test_admin_disabled_when_no_hash(make_client, admin) -> None:
    c = make_client(admin_token_hash="")
    assert c.get("/api/v1/admin/reports", headers=admin).status_code == 401


def test_admin_pagination(client, admin) -> None:
    ids = [_report(client).json()["id"] for _ in range(5)]
    got, cursor = [], None
    while True:
        q = "/api/v1/admin/reports?limit=2" + (f"&cursor={cursor}" if cursor else "")
        body = client.get(q, headers=admin).json()
        got += [i["id"] for i in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert got == ids


# ----------------------------------------------------------------------------- cross-cutting
def test_rate_limit(make_client) -> None:
    c = make_client(rate_limit_per_minute=3)
    body = {"origin": grid(0, 0), "destination": grid(0, 2)}
    codes = [c.post("/api/v1/routes/compare", json=body).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    r = c.post("/api/v1/routes/compare", json=body)
    validate_response(r, "/routes/compare", "post")
    assert r.json()["code"] == "RATE_LIMITED" and int(r.headers["retry-after"]) >= 1


def test_cors_allow_list(client) -> None:
    pre = {"Access-Control-Request-Method": "POST"}
    ok = client.options(
        "/api/v1/routes/compare", headers={"Origin": "http://localhost:5173", **pre}
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options(
        "/api/v1/routes/compare", headers={"Origin": "https://evil.example", **pre}
    )
    assert "access-control-allow-origin" not in bad.headers


def test_unknown_path_envelope(client) -> None:
    r = client.get("/api/v1/nope")
    assert r.status_code == 404
    validate_schema(r.json(), "Error")


def test_logs_round_coordinates(client, capsys) -> None:
    capsys.readouterr()
    body = {
        "origin": {"lon": -73.57812345, "lat": 45.50312345},
        "destination": {"lon": -73.57587654, "lat": 45.50387654},
    }
    assert client.post("/api/v1/routes/compare", json=body).status_code == 200
    _report(client, location={"lon": -73.57698765, "lat": 45.50376543}, description="secret text")
    out = capsys.readouterr().out + capsys.readouterr().err
    assert "route_computed" in out and "report_created" in out
    for raw in ("73.5781", "45.5031", "73.5758", "45.5038", "73.5769", "45.5037"):
        assert raw not in out, raw
    assert "-73.578" in out
    assert "secret text" not in out


def test_report_expiry_and_purge() -> None:
    from winterpath_api.repositories.reports import InMemoryReportRepository

    repo = InMemoryReportRepository()
    t0 = datetime(2026, 12, 1, tzinfo=UTC)
    r = repo.create(
        category="ice",
        lon=-73.57,
        lat=45.50,
        description=None,
        deletion_token_hash="h",
        client_hash="c",
        now=t0,
    )
    repo.moderate(r.id, "approve", None, t0)
    assert [x.id for x in repo.approved_active(t0 + timedelta(hours=71))] == [r.id]
    assert repo.approved_active(t0 + timedelta(hours=73)) == []
    assert repo.get(r.id, t0 + timedelta(hours=73)).status == "expired"
    assert repo.purge(t0 + timedelta(days=20)) == 0
    assert repo.purge(t0 + timedelta(days=34)) == 1
    assert repo.get(r.id, t0 + timedelta(days=34)) is None
