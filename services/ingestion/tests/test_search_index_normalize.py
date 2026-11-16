import json
from pathlib import Path

import pytest

from winterpath_ingestion.search_index.normalize import direction, fold, generic, tokens

VECTORS = (
    Path(__file__).resolve().parents[3] / "apps/web/src/features/search/normalize.vectors.json"
)


@pytest.mark.parametrize("v", json.loads(VECTORS.read_text()), ids=lambda v: v["in"] or "empty")
def test_shared_vectors(v):
    """Same vectors as apps/web normalize.test.ts: builder and client must agree."""
    assert fold(v["in"]) == v["fold"]
    assert tokens(v["in"]) == v["tokens"]


def test_generic_and_direction():
    assert generic("Boulevard") == "boulevard"
    assert generic("Côte") == "cote"
    assert generic("Montée") == "montee"
    assert generic("") == ""
    assert direction("Ouest") == "o"
    assert direction("Est") == "e"
    assert direction("") == ""
