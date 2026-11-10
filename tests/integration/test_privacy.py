"""Privacy: server logs must never contain coordinates with more than 3 decimal places."""

from __future__ import annotations

import time

import pytest

from log_scan import precise_coordinates

pytestmark = pytest.mark.privacy

# Distinctive 6-dp values inside the pilot bbox.
ORIGIN = {"lon": -73.577213, "lat": 45.504871}
DEST = {"lon": -73.569847, "lat": 45.501733}
REPORT_AT = {"lon": -73.574519, "lat": 45.503297}
SENT = ["73.577213", "45.504871", "73.569847", "45.501733", "73.574519", "45.503297"]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('{"origin":[-73.577213,45.504871]}', ["-73.577213", "45.504871"]),
        (
            "GET /api/v1/hazards?bbox=-73.5800%2C45.5000%2C-73.5700%2C45.5060",
            ["-73.5700", "-73.5800", "45.5000", "45.5060"],
        ),
        ('{"origin_3dp":["-73.577","45.505"]}', []),
        ('{"duration_ms":12.3456,"ratio":0.123456}', []),
        ('{"ts":"2026-11-10T20:46:14.093Z"}', []),
    ],
)
def test_scanner(line: str, expected: list[str]) -> None:
    assert precise_coordinates(line) == sorted(expected)


def test_logs_contain_no_precise_coordinates(client, target) -> None:
    if target.log_file is None:
        pytest.skip("API_LOG_FILE not set: cannot read the target server's logs (set it to the API log path)")
    client.post("/routes/compare", json={"origin": ORIGIN, "destination": DEST})
    client.post(
        "/reports",
        json={
            "category": "ice",
            "location": REPORT_AT,
            "location_consent": True,
            "description": "privacy probe",
        },
    )
    client.get("/hazards", params={"bbox": "-73.577213,45.501733,-73.569847,45.504871"})
    client.get("/map/segments", params={"bbox": "-73.577213,45.501733,-73.569847,45.504871"})
    time.sleep(0.5)  # let the server flush
    text = target.log_file.read_text(encoding="utf-8", errors="replace")
    assert text.strip(), "log file is empty — cannot assert privacy on no evidence"
    assert precise_coordinates(text) == []
    assert [s for s in SENT if s in text] == []
    assert "privacy probe" not in text, "report description must not be logged"
