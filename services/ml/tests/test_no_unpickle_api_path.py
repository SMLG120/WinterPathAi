"""The API path (inference.load_provider / api_provider + lookups) never unpickles anything.

Runs in a fresh interpreter with a CPython audit hook: any pickle global lookup
(`pickle.find_class`) or pickle.load(s) raises (marshal is not hooked: the import system uses it for .pyc), and joblib must never be imported.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

from winterpath_ml import config

SCRIPT = textwrap.dedent(
    """
    import sys, json, pickle
    events = []
    def hook(event, args):
        if event == "pickle.find_class":
            events.append(event)
            raise RuntimeError("deserialisation on API path: " + event)
    sys.addaudithook(hook)
    _orig = (pickle.load, pickle.loads)
    def _deny(*a, **k):
        events.append("pickle.load(s)")
        raise RuntimeError("pickle.load(s) on API path")
    pickle.load = pickle.loads = _deny

    from datetime import datetime, timezone
    from winterpath_ml import inference
    p = inference.load_provider()
    p.cell_risk("892baa441b3ffff", datetime(2026, 12, 1, 12, tzinfo=timezone.utc))
    p.edge_risk([[-73.5772, 45.5048], [-73.5760, 45.5052]], datetime(2026, 12, 1, 12, tzinfo=timezone.utc))
    p.status()
    print(json.dumps({"provider": type(p).__name__, "joblib": "joblib" in sys.modules,
                      "sklearn": "sklearn" in sys.modules, "events": events}))
    """
)


def test_api_path_never_unpickles():
    r = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["events"] == [] and out["joblib"] is False and out["sklearn"] is False, (
        out
    )


@pytest.mark.skipif(
    not (config.ARTIFACT_DIR / "v2-8d19aa86" / "coverage_cells.parquet").exists(),
    reason="local artifacts not present (provider would be NullRiskProvider)",
)
def test_api_path_with_real_artifacts_uses_score_tables():
    r = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ,
    )
    assert (
        json.loads(r.stdout.strip().splitlines()[-1])["provider"]
        == "HeuristicRiskProvider"
    )
