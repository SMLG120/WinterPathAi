"""Idempotent, atomic pipeline outputs.

Each pipeline writes into ``<processed>/<name>/`` a ``manifest.json`` holding the input checksum.
If the input checksum is unchanged and outputs exist the run is a no-op. New outputs are written
to a staging directory and swapped in with ``os.replace`` so a failed run never replaces current
data.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class RunResult:
    name: str
    out_dir: Path
    noop: bool
    manifest: dict


def read_manifest(out_dir: Path) -> dict | None:
    p = out_dir / "manifest.json"
    return json.loads(p.read_text()) if p.exists() else None


def run_atomic(
    name: str,
    base_dir: Path,
    input_checksum: str,
    build: Callable[[Path, str], dict],
    *,
    force: bool = False,
) -> RunResult:
    """``build(staging, ingest_run_id) -> manifest_extra``; no-op when checksum matches."""
    out_dir = base_dir / name
    current = read_manifest(out_dir)
    if current and current.get("input_checksum") == input_checksum and not force:
        return RunResult(name, out_dir, True, current)

    base_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    staging = base_dir / f".{name}.staging-{run_id}"
    staging.mkdir()
    try:
        extra = build(staging, run_id)
        manifest = {
            "name": name,
            "ingest_run_id": run_id,
            "input_checksum": input_checksum,
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            **extra,
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
        old = base_dir / f".{name}.old-{run_id}"
        if out_dir.exists():
            os.replace(out_dir, old)
        os.replace(staging, out_dir)
        if old.exists():
            shutil.rmtree(old)
        return RunResult(name, out_dir, False, manifest)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
