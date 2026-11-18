"""`graph_artifact --from-processed`: build from an ingestion output directory (no database).

The graph is the REAL pilot_mini OSM fixture laid out as an ingestion output (edges, nodes and a
run manifest). The reference is the existing ``--from-fixture`` build of the same files.
"""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
from api_testlib import PILOT_MINI
from winterpath_routing import compact_io

from winterpath_api import graph_artifact


@pytest.fixture(scope="module")
def processed(tmp_path_factory):
    d = tmp_path_factory.mktemp("osm_region")
    for f in ("edges.geojson", "nodes.geojson"):
        shutil.copy(PILOT_MINI / f, d / f)
    (d / "manifest.json").write_text(
        json.dumps(
            {
                "source_id": "osm",
                "region": "test_region",
                "title": "TEST region",
                "osm_snapshot": "2026-11-08T21:21:00Z",
                "finished_at": "2026-11-16T12:00:00+00:00",
            }
        )
    )
    return d


def _build(tmp_path, *src):
    out = tmp_path / "g.npz"
    args = ["--out", str(out), *src, "--coverage-name", "TEST", "--no-risk-index"]
    assert graph_artifact.main(args) == 0
    return out


def test_from_processed_equals_fixture_graph(tmp_path, processed) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = _build(tmp_path / "a", "--from-processed", str(processed))
    b = _build(tmp_path / "b", "--from-fixture", str(PILOT_MINI))
    ga, _, _ = compact_io.load(a)
    gb, _, _ = compact_io.load(b)
    assert np.array_equal(ga._eids.sorted_ids, gb._eids.sorted_ids)
    assert np.array_equal(ga._nids.sorted_ids, gb._nids.sorted_ids)
    pa, pb = ga._eids.perm, gb._eids.perm
    assert np.array_equal(ga.length[pa], gb.length[pb])
    assert np.array_equal(ga.legal[pa], gb.legal[pb])
    assert ga.largest_component_share == gb.largest_component_share
    m = ga.metadata
    assert m.simulated is False  # real OSM data, stated by the run manifest's source
    assert m.osm_snapshot == "2026-11-08T21:21:00Z"
    assert set(m.source_freshness) == {"osm"}  # nothing claimed for sources not in the build
    assert "TEST region" in m.description


def test_from_processed_is_deterministic(tmp_path, processed) -> None:
    (tmp_path / "1").mkdir()
    (tmp_path / "2").mkdir()
    a = _build(tmp_path / "1", "--from-processed", str(processed))
    b = _build(tmp_path / "2", "--from-processed", str(processed))
    assert compact_io.sha256_file(a) == compact_io.sha256_file(b)


def test_from_processed_refuses_non_osm_output(tmp_path, processed) -> None:
    d = tmp_path / "bad"
    shutil.copytree(processed, d)
    m = json.loads((d / "manifest.json").read_text())
    (d / "manifest.json").write_text(json.dumps({**m, "source_id": "mtl-voirie"}))
    with pytest.raises(SystemExit):
        graph_artifact.main(
            ["--out", str(tmp_path / "x.npz"), "--from-processed", str(d), "--coverage-name", "x"]
        )


def test_unparseable_snapshot_is_unknown_freshness_not_a_crash(tmp_path, processed) -> None:
    """Code review PR #2: the fixture loader treats a non-ISO snapshot as unknown; so must this."""
    d = tmp_path / "odd"
    shutil.copytree(processed, d)
    m = json.loads((d / "manifest.json").read_text())
    m["osm_snapshot"] = "sequence 4321"  # e.g. a replication sequence, not a timestamp
    m["finished_at"] = "not a date"
    (d / "manifest.json").write_text(json.dumps(m))
    g = graph_artifact.graph_from_processed(d)
    assert g.metadata.osm_snapshot == "sequence 4321"
    assert g.metadata.source_freshness == {"osm": None}
    assert g.metadata.built_at is None
