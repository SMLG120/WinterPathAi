"""Risk adapter normalisation, settings parsing, PostGIS repos (skipped without DB), latency."""

from __future__ import annotations

import os
import random
import statistics
import time
from datetime import UTC, datetime

import pytest
from api_testlib import validate_response
from winterpath_routing import EvidenceState, RiskLevel

from winterpath_api.adapters import NormalisingRiskProvider, default_model_status
from winterpath_api.settings import PILOT_BBOX, Settings

AT = datetime(2026, 12, 1, tzinfo=UTC)


class _DictProvider:
    risk_layer = "heuristic"

    def edge_risk(self, edge_ids, at):
        return {
            "a": {
                "level": "high",
                "probability": None,
                "evidence": {"state": "model_estimate", "source_ids": ["mtl-311"]},
            },
            "b": {"level": "purple", "evidence": {"state": "model_estimate"}},
            "c": {"level": "low", "probability": 7.0, "evidence": {"state": "model_estimate"}},
        }


class _Broken:
    risk_layer = "model"

    def edge_risk(self, edge_ids, at):
        raise RuntimeError("boom")


def test_normalising_provider_maps_malformed_to_unknown() -> None:
    out = NormalisingRiskProvider(_DictProvider()).edge_risk(["a", "b", "c", "d"], AT)
    assert out["a"].level is RiskLevel.HIGH
    assert out["a"].evidence.state is EvidenceState.MODEL_ESTIMATE
    assert out["b"].level is RiskLevel.UNKNOWN  # invalid level
    assert out["c"].level is RiskLevel.UNKNOWN  # probability out of range
    assert "d" not in out  # missing ⇒ engine treats as unknown


def test_failing_provider_yields_unknown_not_invented() -> None:
    p = NormalisingRiskProvider(_Broken())
    out = p.edge_risk(["a"], AT)
    assert out["a"].level is RiskLevel.UNKNOWN
    assert out["a"].evidence.state is EvidenceState.UNKNOWN


def test_model_status_default() -> None:
    st = default_model_status(NormalisingRiskProvider(_DictProvider()))
    assert st["enabled"] is False and st["evaluation"] is None


def test_api_with_heuristic_risk_layer(make_client) -> None:
    from api_testlib import grid

    c = make_client(risk=NormalisingRiskProvider(_DictProvider()))
    r = c.post("/api/v1/routes/compare", json={"origin": grid(0, 0), "destination": grid(0, 2)})
    validate_response(r, "/routes/compare", "post")
    assert r.json()["risk_layer"] == "heuristic"
    codes = [e["code"] for e in r.json()["routes"][0]["explanation"]]
    assert "RISK_UNKNOWN_SHARE" in codes


def test_settings_from_env() -> None:
    s = Settings.from_env(
        {
            "API_CORS_ORIGINS": "http://a, http://b",
            "API_RATE_LIMIT_PER_MINUTE": "7",
            "ROUTING_GRAPH_SOURCE": "PostGIS",
        }
    )
    assert s.cors_origins == ["http://a", "http://b"]
    assert s.rate_limit_per_minute == 7 and s.graph_source == "postgis"
    assert s.fixture_dir.parts[-3:] == ("data", "fixtures", "pilot_mini")


def _db_skip_reason() -> str | None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "DATABASE_URL not set"
    try:
        from sqlalchemy import create_engine, text

        with create_engine(url, connect_args={"connect_timeout": 2}).connect() as c:
            ok = c.execute(text("SELECT to_regclass('wp.community_report') IS NOT NULL")).scalar()
        return None if ok else "wp.community_report absent (Data agent migrations not applied)"
    except Exception as exc:
        return f"PostGIS unreachable ({type(exc).__name__}); Docker Desktop paused?"


def test_postgis_report_repository_integration() -> None:
    reason = _db_skip_reason()
    if reason:
        pytest.skip(reason)
    from sqlalchemy import create_engine

    from winterpath_api.repositories.reports import PostgisReportRepository

    repo = PostgisReportRepository(create_engine(os.environ["DATABASE_URL"]))
    r = repo.create(
        category="ice",
        lon=-73.57,
        lat=45.50,
        description="integration test",
        deletion_token_hash="h",
        client_hash="c",
        now=AT,
    )
    assert repo.get(r.id, AT).status == "pending"
    assert repo.delete_own(r.id, AT)


def test_api_latency_100_random_pairs(client, capsys) -> None:
    """SYNTHETIC toy grid via the full HTTP stack (TestClient, in-process)."""
    rnd = random.Random(7)
    times = []
    while len(times) < 100:
        o = {"lon": rnd.uniform(-73.578, -73.575), "lat": rnd.uniform(45.503, 45.5044)}
        d = {"lon": rnd.uniform(-73.578, -73.575), "lat": rnd.uniform(45.503, 45.5044)}
        t0 = time.perf_counter()
        r = client.post("/api/v1/routes/compare", json={"origin": o, "destination": d})
        times.append(time.perf_counter() - t0)
        assert r.status_code in (200, 422), r.text
    times.sort()
    p50, p95 = statistics.median(times), times[94]
    with capsys.disabled():
        print(
            f"\n[latency] API POST /routes/compare SYNTHETIC toy grid (38 edges), n=100: "
            f"p50={p50 * 1000:.1f} ms p95={p95 * 1000:.1f} ms max={times[-1] * 1000:.1f} ms"
        )
    assert p95 < 2.0
    assert PILOT_BBOX[0] < -73.5
