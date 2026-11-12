"""`wp-ingest` CLI: `load --source` wiring (offline; the DB side is in test_postgis.py)."""

import pytest

from winterpath_ingestion import cli, db_load
from winterpath_ingestion.sources.registry import SOURCES


def test_source_ids_match_loaders_and_registry(tmp_path):
    from winterpath_ingestion.config import Settings

    assert cli.SOURCE_IDS == list(db_load.SOURCE_LOADERS)
    assert set(db_load.SOURCE_LOADERS.values()) == set(db_load.LOADERS)
    assert set(cli.SOURCE_IDS) <= {s["source_id"] for s in SOURCES}
    s = Settings(data_dir=tmp_path, user_agent="test")  # empty: every manifest is None
    for sid, key in db_load.SOURCE_LOADERS.items():
        source_id, manifest, _ = db_load.LOADERS[key](s)
        assert (source_id, manifest) == (sid, None)


@pytest.mark.parametrize("columns", ["40", "80", "200"])
def test_help_lists_source_ids_unbroken(monkeypatch, capsys, columns):
    """Platform's scheduled.yml greps `wp-ingest load --help` for `--source` and `eccc-geomet`."""
    monkeypatch.setenv("COLUMNS", columns)
    with pytest.raises(SystemExit) as e:
        cli.main(["load", "--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "--source" in out
    for sid in cli.SOURCE_IDS:
        assert sid in out


def test_load_source_selects_only_that_loader(monkeypatch, capsys):
    seen = {}

    def fake_load(
        settings,
        which,
        url=None,
        force=False,
        weather_since=None,
        osm_graph="pilot",
        wait=False,
        r311_recent=False,
    ):
        seen.update(which=which, force=force, weather_since=weather_since, osm_graph=osm_graph)
        return [{"source_id": "eccc-geomet", "noop": True}]

    monkeypatch.setattr(db_load, "load", fake_load)
    assert cli.main(["load", "--source", "eccc-geomet", "--source", "eccc-geomet"]) == 0
    assert seen == {"which": ["eccc"], "force": False, "weather_since": None, "osm_graph": "pilot"}
    assert cli.main(["load", "--source", "mtl-311", "--source", "osm", "--force"]) == 0
    assert seen["which"] == ["311", "osm"] and seen["force"] is True
    assert cli.main(["load"]) == 0
    assert seen["which"] == list(db_load.LOADERS)
    assert cli.main(["load", "--source", "osm", "--osm-graph", "island"]) == 0
    assert seen["which"] == ["osm"] and seen["osm_graph"] == "island"


@pytest.mark.parametrize(
    "argv",
    [
        ["load", "--source", "eccc"],  # pipeline name, not a source_id
        ["load", "--source", "mtl-planif-neige"],  # registered, but has no loader
        ["eccc", "--source", "eccc-geomet"],  # --source only applies to load
        ["osm", "--osm-graph", "island"],  # --osm-graph only applies to load
        ["load", "--osm-graph", "laval"],
        ["load", "--recent"],  # --recent needs --source mtl-311
        ["load", "--source", "eccc-geomet", "--recent"],
        ["eccc", "--recent-days", "14"],  # --recent-days only for 311
    ],
)
def test_load_source_rejects(argv):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 2
