"""311 rolling-window refresh (v2 Wave 2b) — offline: a fake DataStore stands in for the portal.

Rows are synthetic (fake coordinates/dates); no real 311 data is implied.
"""

from datetime import date

import pytest

from winterpath_ingestion.config import Settings
from winterpath_ingestion.sources import r311


class FakeDS:
    """Mimics datastore_search_sql: COUNT query and paged SELECT ... LIMIT/OFFSET."""

    def __init__(self, rows, count=None):
        self.rows, self.count, self.sqls = rows, count, []

    def __call__(self, url, json, headers, timeout):
        sql = json["sql"]
        self.sqls.append(sql)
        if "count(*)" in sql:
            recs = [{"n": len(self.rows) if self.count is None else self.count}]
        elif "max(" in sql:
            recs = [{"mx": "2026-11-12T08:00:00"}]
        else:
            lim = int(sql.split("LIMIT ")[1].split()[0])
            off = int(sql.split("OFFSET ")[1])
            recs = self.rows[off : off + lim]

        class R:
            content = b"x" * 10

            def raise_for_status(self):
                pass

            def json(self):
                return {"success": True, "result": {"records": recs}}

        return R()


def row(day, cat="Trottoir glissant", nature="Requete", lat="45.5", lon="-73.6"):
    return {
        "ACTI_NOM": cat,
        "NATURE": nature,
        "LOC_ERREUR_GDT": "0",
        "LOC_LAT": lat,
        "LOC_LONG": lon,
        "DDS_DATE_CREATION": f"{day}T10:00:00",
    }


def test_window_is_inclusive_local_days():
    assert r311.window(14, date(2026, 11, 12)) == ("2026-10-30", "2026-11-12")
    assert r311.window(1, date(2026, 11, 12)) == ("2026-11-12", "2026-11-12")
    with pytest.raises(ValueError):
        r311.window(0)


def test_fetch_pages_and_checks_count(tmp_path, monkeypatch):
    monkeypatch.setattr(r311, "PAGE", 2)
    s = Settings(data_dir=tmp_path, user_agent="test")
    rows = [row("2026-11-10") for _ in range(5)]
    ds = FakeDS(rows)
    got, info = r311.fetch_recent(s, "2026-10-30", post=ds)
    assert len(got) == 5 and info["rows"] == 5
    assert info["source_data_through"] == "2026-11-12T08:00:00"
    assert info["latest_winter_row"] == "2026-11-10T10:00:00"
    assert sum("OFFSET" in q for q in ds.sqls) == 3  # 2 + 2 + 1
    filtered = [q for q in ds.sqls if "max(" not in q]  # the freshness query spans all rows
    assert len(filtered) == 4
    assert all("'Trottoir glissant'" in q and ">= '2026-10-30'" in q for q in filtered)
    assert (tmp_path / "raw" / "311" / "recent_window.jsonl").exists()  # raw stays in raw/
    with pytest.raises(RuntimeError, match="inconsistent"):
        r311.fetch_recent(s, "2026-10-30", post=FakeDS(rows, count=7))
    with pytest.raises(ValueError):
        r311.fetch_recent(s, "2026-10-30' OR 1=1 --", post=ds)  # never inlined


def test_run_recent_same_rules_as_full_build(tmp_path):
    s = Settings(data_dir=tmp_path, user_agent="test")
    rows = [
        row("2026-11-10"),
        row("2026-11-10"),
        row("2026-11-10", nature="Information"),
        row("2026-11-11", cat="Opération déneigement", nature="Plainte"),
        {**row("2026-11-11"), "LOC_ERREUR_GDT": "1"},  # borough office → skipped
        row("2026-11-13"),  # after the window end → dropped
    ]
    r = r311.run_recent(s, days=14, today=date(2026, 11, 12), post=FakeDS(rows))
    m = r.manifest
    assert m["window"] == ["2026-10-30", "2026-11-12"] and m["mode"] == "recent_window"
    lines = (r.out_dir / "report_311_cell.csv").read_text().splitlines()
    body = sorted(",".join(x.split(",")[1:5]) for x in lines[1:])
    assert body == [
        "2026-11-10,sidewalk_slippery,information,1",
        "2026-11-10,sidewalk_slippery,requete,2",
        "2026-11-11,snow_clearing,plainte,1",
    ]  # n<3 rows are kept as counts (unchanged rule: consumers suppress after SUM)
    assert m["stats"]["rows_by_reason"]["located_at_borough_office"] == 1
    again = r311.run_recent(s, days=14, today=date(2026, 11, 12), post=FakeDS(rows))
    assert again.noop is True
    assert again.manifest["fetch_this_run"]["source_data_through"] == "2026-11-12T08:00:00"
