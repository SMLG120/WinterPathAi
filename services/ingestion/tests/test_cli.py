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
        region="pilot",
        wait=False,
        r311_recent=False,
    ):
        seen.update(which=which, force=force, weather_since=weather_since, region=region)
        return [{"source_id": "eccc-geomet", "noop": True}]

    monkeypatch.setattr(db_load, "load", fake_load)
    assert cli.main(["load", "--source", "eccc-geomet", "--source", "eccc-geomet"]) == 0
    assert seen == {"which": ["eccc"], "force": False, "weather_since": None, "region": "pilot"}
    assert cli.main(["load", "--source", "mtl-311", "--source", "osm", "--force"]) == 0
    assert seen["which"] == ["311", "osm"] and seen["force"] is True
    assert cli.main(["load"]) == 0
    assert seen["which"] == list(db_load.LOADERS)
    assert cli.main(["load", "--source", "osm", "--osm-graph", "island"]) == 0
    assert seen["which"] == ["osm"] and seen["region"] == "island"


@pytest.mark.parametrize(
    "argv",
    [
        ["load", "--source", "eccc"],  # pipeline name, not a source_id
        ["load", "--source", "mtl-planif-neige"],  # registered, but has no loader
        ["eccc", "--source", "eccc-geomet"],  # --source only applies to load
        ["osm", "--osm-graph", "island"],  # --region/--osm-graph not for the osm build
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


@pytest.mark.parametrize(
    ("flags", "refresh", "force"), [([], False, False), (["--refresh", "--force"], True, True)]
)
def test_fixed_links_passes_refresh_and_force(monkeypatch, tmp_path, capsys, flags, refresh, force):
    """Code review PR #2: `fixed-links --refresh` must not reuse the cached SDA GPKG and PBF."""
    from types import SimpleNamespace

    from winterpath_ingestion.config import Settings
    from winterpath_ingestion.osm import geofabrik, links
    from winterpath_ingestion.sources import sda

    seen = {}
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(data_dir=tmp_path, user_agent="test"))
    monkeypatch.setattr(sda, "run", lambda s, **kw: seen.setdefault("sda", kw))

    def fake_fetch(*a, **kw):
        seen["pbf"] = kw
        return SimpleNamespace(path=tmp_path / "x.pbf")

    monkeypatch.setattr(geofabrik, "fetch", fake_fetch)
    monkeypatch.setattr(links, "run", lambda *a, **kw: [])
    assert cli.main(["fixed-links", *flags]) == 0
    assert seen["sda"] == {"refresh": refresh, "force": force}
    assert seen["pbf"]["refresh"] is refresh
