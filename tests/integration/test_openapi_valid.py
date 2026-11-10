"""The frozen contract must be a valid OpenAPI 3.1 document, and the stub's canned payloads
must satisfy it (so a green contract run means the *contract* was exercised, not the stub's
assumptions)."""

from __future__ import annotations

import pytest
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

from stub_server import fixtures
from stub_server.contract import CONTRACT_PATH, component_schema, load_spec, operations, schema_errors


def test_contract_is_valid_openapi_31() -> None:
    spec_dict, _ = read_from_filename(str(CONTRACT_PATH))
    validate(spec_dict)  # raises on error
    assert spec_dict["openapi"].startswith("3.1")


def test_contract_version_is_v1() -> None:
    assert load_spec()["info"]["version"].split(".")[0] == "1"


def test_every_operation_has_an_operation_id_and_success_response() -> None:
    ops = operations()
    assert len(ops) == 14  # contract v1
    for op in ops.values():
        assert any(s.startswith("2") for s in op.declared_statuses), op.operation_id


BBOX = (-73.58, 45.50, -73.57, 45.506)


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        ("Health", fixtures.health()),
        ("Coverage", fixtures.coverage()),
        ("ModelStatus", fixtures.model_status()),
        ("HazardCollection", fixtures.hazards(BBOX)),
        ("SegmentCollection", fixtures.segments(BBOX)),
        (
            "RouteCompareResponse",
            fixtures.route_compare(
                {"lon": -73.5772, "lat": 45.5048}, {"lon": -73.5698, "lat": 45.5017}, "r1"
            ),
        ),
        ("ReportReceipt", fixtures.report_receipt("6f1c1f1e-8f4e-4d8a-9a51-0c1d2e3f4a5b")),
    ],
)
def test_stub_payloads_conform_to_contract(schema: str, payload: dict) -> None:
    assert schema_errors(component_schema(schema), payload) == []


def test_stub_payloads_are_labelled_simulated() -> None:
    hz = fixtures.hazards(BBOX)["features"][0]["properties"]["evidence"]
    seg = fixtures.segments(BBOX)["features"][0]["properties"]["risk"]
    assert hz["state"] == "simulated" and "SIMULATED" in hz["note"]
    assert seg["evidence"]["state"] == "simulated" and seg["level"] == "unknown"


def test_stub_pilot_bbox_matches_architecture_doc() -> None:
    assert fixtures.PILOT_BBOX == (-73.5880, 45.4960, -73.5620, 45.5130)
