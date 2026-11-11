"""Deploy blocker regression: a non-editable install (API image) must find the registry and artifacts.

The package is copied into <tmp>/venv/lib/python3.12/site-packages/winterpath_ml and imported from
there in a fresh interpreter (PYTHONPATH first, cwd elsewhere), so config.REPO_ROOT points inside
the fake venv exactly as in the image. Registry and the two committed artifacts are copied to
<tmp>/app/models/..., mirroring MODEL_ARTIFACT_DIR=/app/models/artifacts in the image.
"""

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from winterpath_ml import config

SRC = Path(__file__).resolve().parents[1] / "src" / "winterpath_ml"
RUN = "v2-8d19aa86"
PROBE = textwrap.dedent(
    """
    import json, logging, sys
    from datetime import datetime, timezone
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    import winterpath_ml
    from winterpath_ml import config, inference
    reg = inference.load_registry() if config.REGISTRY_PATH.exists() else None
    p = inference.load_provider()
    out = {
        "pkg_file": winterpath_ml.__file__,
        "repo_root": str(config.REPO_ROOT),
        "registry_path": str(config.REGISTRY_PATH),
        "artifact_dir": str(config.ARTIFACT_DIR),
        "coverage_path": str(inference.artifact_path(reg, reg["coverage"])) if reg else None,
        "provider": type(p).__name__,
        "level": p.cell_risk("892baa441b3ffff", datetime(2026, 7, 1, 12, tzinfo=timezone.utc)).level,
    }
    print(json.dumps(out))
    """
)


@pytest.fixture
def layout(tmp_path):
    if not (config.ARTIFACT_DIR / RUN / "coverage_cells.parquet").exists():
        pytest.skip("committed coverage artifact not present")
    site = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    shutil.copytree(
        SRC, site / "winterpath_ml", ignore=shutil.ignore_patterns("__pycache__")
    )
    app = tmp_path / "app" / "models"
    (app / "artifacts" / RUN).mkdir(parents=True)
    shutil.copy(config.REPO_ROOT / "models" / "registry.json", app / "registry.json")
    for f in ("coverage_cells.parquet", "winter311-heuristic-v1.joblib"):
        shutil.copy(config.ARTIFACT_DIR / RUN / f, app / "artifacts" / RUN / f)
    work = tmp_path / "cwd"
    work.mkdir()
    return tmp_path, site, app, work


def _probe(site, work, **env):
    e = {
        k: v
        for k, v in os.environ.items()
        if k not in ("MODEL_ARTIFACT_DIR", "MODEL_REGISTRY_PATH", "RISK_SCORE_SOURCE")
    }
    e.update(PYTHONPATH=str(site), **env)
    r = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=work,
        env=e,
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1]), r.stderr


def test_nonedit_without_env_reproduces_missing_registry(layout):
    tmp, site, _, work = layout
    out, err = _probe(site, work)
    assert out["pkg_file"].startswith(str(site))  # really imported from the fake venv
    assert out["repo_root"] == str(tmp / "venv")  # what the image showed: /opt/venv
    assert out["provider"] == "NullRiskProvider" and "risk_registry_missing" in err


def test_nonedit_with_env_finds_registry_and_artifacts(layout):
    _, site, app, work = layout
    out, err = _probe(
        site,
        work,
        MODEL_REGISTRY_PATH=str(app / "registry.json"),
        MODEL_ARTIFACT_DIR=str(app / "artifacts"),
    )
    assert out["pkg_file"].startswith(str(site))
    assert out["registry_path"] == str(app / "registry.json")
    assert out["coverage_path"] == str(
        app / "artifacts" / RUN / "coverage_cells.parquet"
    )
    assert out["provider"] == "HeuristicRiskProvider", err
    assert "risk_registry_missing" not in err and "risk_artifacts_missing" not in err
    assert out["level"] == "unknown"  # July: out of season, never low


def test_empty_env_values_mean_default(layout):
    _, site, _, work = layout
    out, _ = _probe(site, work, MODEL_REGISTRY_PATH="", MODEL_ARTIFACT_DIR="")
    venv = Path(out["repo_root"])
    assert out["registry_path"] == str(venv / "models" / "registry.json")
    assert out["artifact_dir"] == str(venv / "models" / "artifacts")
