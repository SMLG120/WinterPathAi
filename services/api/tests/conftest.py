from __future__ import annotations

from dataclasses import replace

import pytest
from api_testlib import ADMIN_TOKEN, TOY_DIR
from fastapi.testclient import TestClient

from winterpath_api.main import create_app
from winterpath_api.security import sha256_hex
from winterpath_api.settings import Settings
from winterpath_api.state import build_state


@pytest.fixture
def settings() -> Settings:
    return Settings(
        cors_origins=["http://localhost:5173"],
        admin_token_hash="sha256:" + sha256_hex(ADMIN_TOKEN),
        rate_limit_per_minute=10_000,
        graph_source="fixture",
        fixture_dir=TOY_DIR,
        store_backend="memory",
        risk_provider="none",
    )


@pytest.fixture
def make_client(settings):
    def make(**overrides):
        s = replace(settings, **{k: v for k, v in overrides.items() if hasattr(settings, k)})
        state_kw = {k: v for k, v in overrides.items() if not hasattr(settings, k)}
        app = create_app(s, build_state(s, **state_kw))
        return TestClient(app)

    return make


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def admin() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}
