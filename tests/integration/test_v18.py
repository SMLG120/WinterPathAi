"""Contract v1.8 invariants (/data-status, /weather/alerts, freshness, route weather_context).

Target-agnostic: runs against the stub and against a real API that implements v1.8.
Schema conformance of every operation is also covered by test_contract.py; these tests pin the
semantic rules the schema cannot express.
"""

from __future__ import annotations

import pytest

from stub_server.contract import component_schema, schema_errors

pytestmark = pytest.mark.smoke

PRODUCT_IDS = {
    "weather_observations",
    "weather_forecast",
    "weather_alerts",
    "closures",
    "reports_311",
    "risk_scores",
    "pedestrian_graph",
}
# docs/agents/v2-plan.md, routing item 3.
EXPECTED_MECHANISM = {
    "weather_forecast": "api_on_demand",
    "weather_alerts": "api_on_demand",
    "weather_observations": "scheduled_job",
    "risk_scores": "scheduled_job",
    "closures": "manual",
    "reports_311": "manual",
    "pedestrian_graph": "manual",
}
FRESHNESS_STATES = {"current", "delayed", "stale", "unavailable"}
PILOT_PAIR = {"origin": {"lon": -73.5800, "lat": 45.5030}, "destination": {"lon": -73.5720, "lat": 45.5060}}


def _check_freshness(f: dict) -> None:
    assert schema_errors(component_schema("Freshness"), f) == []
    assert f["state"] in FRESHNESS_STATES
    assert f["reason"].strip(), "freshness.reason must explain the state"


def test_data_status_lists_every_product_once(client) -> None:
    r = client.get("/data-status")
    assert r.status_code == 200
    body = r.json()
    assert schema_errors(component_schema("DataStatus"), body) == []
    ids = [p["id"] for p in body["products"]]
    assert len(ids) == len(set(ids)), f"duplicate product ids: {ids}"
    assert set(ids) == PRODUCT_IDS


def test_data_status_mechanisms_and_freshness(client) -> None:
    for p in client.get("/data-status").json()["products"]:
        assert p["mechanism"] == EXPECTED_MECHANISM[p["id"]], p["id"]
        _check_freshness(p["freshness"])
        # "current" with no recorded success would be an unfounded freshness claim.
        if p["freshness"]["state"] == "current":
            assert p.get("last_success_at"), f"{p['id']}: current without last_success_at"


def test_weather_alerts_shape_or_declared_503(client) -> None:
    r = client.get("/weather/alerts")
    assert r.status_code in (200, 503), r.status_code
    body = r.json()
    if r.status_code == 503:
        assert body["code"] == "UPSTREAM_UNAVAILABLE"
        return
    assert schema_errors(component_schema("WeatherAlerts"), body) == []
    _check_freshness(body["freshness"])
    if body["alerts"] or body["freshness"]["state"] != "unavailable":
        # Any list (including "ECCC reported none") is only meaningful with provenance.
        assert body["provenance"], "alerts list without provenance"
    if body["provenance"] is None:
        assert body["alerts"] == [], "alerts present but provenance is null"


@pytest.mark.parametrize("path", ["/weather/current", "/weather/forecast"])
def test_weather_freshness_when_served(client, path) -> None:
    r = client.get(path)
    assert r.status_code in (200, 503), r.status_code
    if r.status_code == 200:
        _check_freshness(r.json()["freshness"])


def test_route_weather_context_is_display_only(client) -> None:
    r = client.post("/routes/compare", json=PILOT_PAIR)
    if r.status_code == 422:
        pytest.skip(f"no route for the pilot pair on this target: {r.json().get('code')}")
    assert r.status_code == 200, r.text
    ctx = r.json().get("weather_context")
    if ctx is not None:
        assert ctx["used_for"] == "display_only"
        _check_freshness(ctx["freshness"])
