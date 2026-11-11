"""score.py fails loudly and writes all-or-nothing. SYNTHETIC frames; no network."""

import pandas as pd
import pytest

from winterpath_ml import inference, score

CELLS = ["892baa441b3ffff", "892baa441a7ffff"]


def _table(n=2, p=(0.01, 0.02)):
    return pd.DataFrame({"h3": CELLS[:n], "p": list(p)[:n]})


def test_validate_accepts_complete_table():
    score.validate(_table(), CELLS, pd.Timestamp("2026-12-01"))


@pytest.mark.parametrize(
    "bad",
    [_table(n=1, p=(0.01,)), _table(p=(0.01, float("nan"))), _table(p=(0.01, 1.5))],
)
def test_validate_rejects_partial_or_invalid(bad):
    with pytest.raises(score.InputsIncomplete):
        score.validate(bad, CELLS, pd.Timestamp("2026-12-01"))


def test_verified_rejects_sha_mismatch(tmp_path, monkeypatch):
    f = tmp_path / "x.joblib"
    f.write_bytes(b"not the registered bytes")
    monkeypatch.setattr(inference, "artifact_path", lambda reg, e: f)
    with pytest.raises(score.ScoreError, match="sha256 mismatch"):
        score.verified({}, {"path": "x", "sha256": "0" * 64})


def test_incomplete_day_writes_nothing_and_exits_1(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise score.InputsIncomplete(
            "2026-12-01: 311 data ends 2026-11-29 < 2026-11-30"
        )

    monkeypatch.setattr(score, "prepare", boom)
    monkeypatch.setattr(score, "write", lambda plan: pytest.fail("write called"))
    assert score.main(["--start", "2026-12-01"]) == 1


def test_write_is_atomic_and_leaves_no_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(inference, "scores_dir", lambda reg, layer: tmp_path)
    t = _table().assign(day=pd.Timestamp("2026-12-01"))
    out = score.write(
        {"registry": {}, "layer": "heuristic", "tables": {"2026-12-01": t}}
    )
    assert out == [str(tmp_path / "2026-12-01.parquet")]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["2026-12-01.parquet"]


def test_out_of_season_only_is_a_noop(monkeypatch):
    monkeypatch.setattr(score, "verified", lambda *a: pytest.fail("artifacts touched"))
    plan = score.prepare(
        pd.Timestamp("2026-07-01").date(),
        pd.Timestamp("2026-07-02").date(),
        None,
        False,
    )
    assert plan["tables"] == {} and plan["out_of_season"] == [
        "2026-07-01",
        "2026-07-02",
    ]
