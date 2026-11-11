"""score.py exit policy. SYNTHETIC frames; no network."""

import urllib.error
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from winterpath_ml import config, inference, score

CELLS = ["892baa441b3ffff", "892baa441a7ffff"]


def _table(n=2, p=(0.01, 0.02)):
    return pd.DataFrame({"h3": CELLS[:n], "p": list(p)[:n]})


def _plan(tables=None, not_ready=None, oos=None):
    return {
        "registry": {},
        "layer": "heuristic",
        "tables": tables or {},
        "not_ready": not_ready or {},
        "out_of_season": oos or [],
    }


@pytest.fixture
def scores(tmp_path, monkeypatch):
    monkeypatch.setattr(inference, "scores_dir", lambda reg, layer: tmp_path)
    return tmp_path


def test_validate_accepts_complete_table():
    score.validate(_table(), CELLS, pd.Timestamp("2026-12-01"))


@pytest.mark.parametrize(
    "bad",
    [_table(n=1, p=(0.01,)), _table(p=(0.01, float("nan"))), _table(p=(0.01, 1.5))],
)
def test_validate_rejects_partial_or_invalid(bad):
    with pytest.raises(score.ValidationFailed):
        score.validate(bad, CELLS, pd.Timestamp("2026-12-01"))


def test_verified_rejects_sha_mismatch(tmp_path, monkeypatch):
    f = tmp_path / "x.joblib"
    f.write_bytes(b"not the registered bytes")
    monkeypatch.setattr(inference, "artifact_path", lambda reg, e: f)
    with pytest.raises(score.ScoreError, match="sha256 mismatch"):
        score.verified({}, {"path": "x", "sha256": "0" * 64})


def test_write_is_atomic_and_leaves_no_temp(scores):
    t = _table().assign(day=pd.Timestamp("2026-12-01"))
    out = score.write(_plan({"2026-12-01": t}))
    assert out == [str(scores / "2026-12-01.parquet")]
    assert sorted(p.name for p in scores.iterdir()) == ["2026-12-01.parquet"]


def test_validation_failure_writes_nothing_exit_1(scores, monkeypatch):
    def boom(*a, **k):
        raise score.ValidationFailed("2026-12-01: invalid score table (1 rows)")

    monkeypatch.setattr(score, "prepare", boom)
    assert score.main(["--start", "2026-12-01"]) == 1
    assert list(scores.iterdir()) == []


def test_not_ready_is_notice_exit_0_when_fresh(scores, monkeypatch, capsys):
    (scores / "2026-12-01.parquet").write_bytes(b"")
    nr = {"2026-12-02": "311 data ends 2026-11-30 < 2026-12-01"}
    monkeypatch.setattr(score, "prepare", lambda *a: _plan(not_ready=nr))
    now = datetime(2026, 12, 1, 20, tzinfo=UTC)  # 15 h after local 2026-12-01 00:00
    assert score.main(["--start", "2026-12-02"], now=now) == 0
    assert "2026-12-02 not scored yet" in capsys.readouterr().err


def test_stale_newest_day_exit_4(scores, monkeypatch):
    (scores / "2026-12-01.parquet").write_bytes(b"")
    monkeypatch.setattr(
        score, "prepare", lambda *a: _plan(not_ready={"2026-12-03": "x"})
    )
    now = datetime(
        2026, 12, 2, 18, tzinfo=UTC
    )  # 37 h after local 2026-12-01 00:00 (UTC-5)
    assert score.main(["--start", "2026-12-03"], now=now) == 4


def test_staleness_ignored_out_of_season(scores):
    assert score.staleness(scores, datetime(2026, 7, 1, tzinfo=UTC)) is None


def test_download_error_is_explicit_exit_3(scores, monkeypatch, capsys):
    def no_net(*a, **k):
        raise urllib.error.URLError("[Errno 8] nodename nor servname provided")

    monkeypatch.setattr(score.urllib.request, "urlopen", no_net)
    monkeypatch.setattr(score, "SCORE_CACHE", scores)
    with pytest.raises(score.DownloadFailed, match="donnees.montreal.ca"):
        score.fetch_311(scores / "raw")
    assert not (scores / "raw" / "requetes311.csv.part").exists()
    monkeypatch.setattr(
        score,
        "prepare",
        lambda *a: (_ for _ in ()).throw(
            score.DownloadFailed("311 CSV download failed: GET x")
        ),
    )
    assert score.main(["--start", "2026-12-01"]) == 3


def test_github_annotations(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    score._annotate("notice", "hello")
    assert "::notice title=winterpath_ml.score::hello" in capsys.readouterr().out


def test_out_of_season_only_is_a_noop(monkeypatch):
    monkeypatch.setattr(score, "verified", lambda *a: pytest.fail("artifacts touched"))
    plan = score.prepare(date(2026, 7, 1), date(2026, 7, 2), None, False)
    assert plan["tables"] == {} and plan["out_of_season"] == [
        "2026-07-01",
        "2026-07-02",
    ]
    assert 7 not in config.SEASON_MONTHS
