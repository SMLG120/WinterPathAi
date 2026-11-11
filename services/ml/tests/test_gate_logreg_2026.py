"""Guards for the pre-registered logistic-regression gate. Nothing here fits or scores real data."""

from datetime import date

import h3
import pandas as pd
import pytest

from winterpath_ml import config
from winterpath_ml import gate_logreg_2026 as g


def test_pinned_files_unchanged():
    # Fails CI if anyone edits a file the pre-registration froze (an addendum is required instead).
    g.check_pins()


def test_hashes_match_gate_document():
    doc = g.GATE_DOC.read_text()
    for name, sha in g.PINNED_SHA256.items():
        assert f"{sha}  services/ml/src/winterpath_ml/{name}" in doc
    assert g.COVERAGE_TXT_SHA256 in doc


def test_refuses_before_earliest_run():
    with pytest.raises(g.GuardError):
        g.check_date(date(2026, 11, 10))
    with pytest.raises(g.GuardError):
        g.check_date(date(2027, 5, 7))
    g.check_date(date(2027, 5, 8))


def test_main_refuses_today_without_fitting(capsys):
    assert date.today() < g.EARLIEST_RUN
    assert g.main([]) == 2
    assert "REFUSED" in capsys.readouterr().err


def test_coverage_list_matches_v2_parquet():
    cells = g.load_coverage()
    assert len(cells) == 2930
    pq = config.ARTIFACT_DIR / "v2-8d19aa86" / "coverage_cells.parquet"
    if pq.exists():
        assert cells == pd.read_parquet(pq)["h3"].tolist()


def test_roles():
    cells = sorted(h3.grid_disk(h3.latlng_to_cell(45.5, -73.6, 9), 30))
    days = pd.to_datetime(["2025-01-10", "2026-01-10", "2027-01-10"])
    panel = pd.DataFrame([(c, d) for d in days for c in cells], columns=["h3", "day"])
    panel["winter"] = [config.winter_of(d.date()) for d in panel["day"]]
    r = pd.Series(g.assign(panel, cells))
    assert set(r[panel["day"] == days[0]]) <= {
        "train",
        "unused",
    }  # winter 2024 now trains
    assert set(r[panel["day"] == days[1]]) <= {
        "calib",
        "unused",
    }  # old test winter -> calibration only
    assert set(r[panel["day"] == days[2]]) == {"test_chrono", "test_spatial"}
    assert not set(panel.loc[(r == "test_spatial").to_numpy(), "h3"]) & set(
        panel.loc[(r == "train").to_numpy(), "h3"]
    )


def _SYNTHETIC_results(cand_pr, cand_brier):
    base = {
        "baseline_hist_freq": {"pr_auc": 0.08, "brier": 0.03},
        "baseline_freq_x_weather": {"pr_auc": 0.10, "brier": 0.029},
    }
    return {
        s: {**base, "baseline_logistic": {"pr_auc": cand_pr, "brier": cand_brier}}
        for s in ("test_chrono", "test_spatial")
    }


OK_BORO = [{"borough": "SYNTH", "positives": 500, "obs_rate": 0.03, "mean_pred": 0.035}]
CI_POS = {"test_chrono": (0.01, 0.05), "test_spatial": (0.005, 0.04)}


def test_decide_pass_and_each_failure_mode():
    assert g.decide(_SYNTHETIC_results(0.12, 0.028), CI_POS, OK_BORO)["pass"]
    assert not g.decide(_SYNTHETIC_results(0.105, 0.028), CI_POS, OK_BORO)[
        "pass"
    ]  # margin < 0.010
    assert not g.decide(_SYNTHETIC_results(0.12, 0.0295), CI_POS, OK_BORO)[
        "pass"
    ]  # Brier not below 0.029
    ci_bad = {**CI_POS, "test_spatial": (-0.001, 0.04)}
    assert not g.decide(_SYNTHETIC_results(0.12, 0.028), ci_bad, OK_BORO)["pass"]
    bad_boro = OK_BORO + [
        {"borough": "SYNTH2", "positives": 150, "obs_rate": 0.02, "mean_pred": 0.05}
    ]
    d = g.decide(_SYNTHETIC_results(0.12, 0.028), CI_POS, bad_boro)
    assert not d["pass"] and d["borough_calibration"]["offenders"] == ["SYNTH2"]
    small = OK_BORO + [
        {"borough": "SMALL", "positives": 99, "obs_rate": 0.001, "mean_pred": 0.05}
    ]
    assert g.decide(_SYNTHETIC_results(0.12, 0.028), CI_POS, small)[
        "pass"
    ]  # <100 positives not judged
