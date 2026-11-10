import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def overpass_small() -> dict:
    return json.loads((FIX / "overpass_mcgill_small.json").read_text())


@pytest.fixture(scope="session")
def built(overpass_small):
    from winterpath_ingestion.osm.graph import build_graph

    return build_graph(overpass_small, snapshot=overpass_small["osm3s"]["timestamp_osm_base"])
