"""Shared fixtures for WinterPath integration tests.

Target selection:
  * API_BASE_URL set   -> tests run against that server (e.g. the real API after merge).
                          Log-based privacy tests need API_LOG_FILE (path the server writes to);
                          otherwise they SKIP with an explicit message.
  * API_BASE_URL unset -> the SCHEMA-ONLY STUB (stub_server/) is started on 127.0.0.1:$STUB_PORT
                          (default 8105) with stdout captured to a temp log file.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

HERE = Path(__file__).resolve().parent


@dataclass
class Target:
    base_url: str
    log_file: Path | None
    is_stub: bool
    admin_token: str | None


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(scope="session")
def target(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Target]:
    external = os.environ.get("API_BASE_URL")
    if external:
        log = os.environ.get("API_LOG_FILE")
        yield Target(
            external.rstrip("/"), Path(log) if log else None, False, os.environ.get("API_ADMIN_TOKEN")
        )
        return

    port = int(os.environ.get("STUB_PORT", "8105"))
    if _port_open(port):
        pytest.exit(f"port {port} already in use; set STUB_PORT or API_BASE_URL", returncode=3)
    log_path = tmp_path_factory.mktemp("stub") / "stub.log"
    token = "stub-admin-token-not-a-secret"  # noqa: S105 — test-only stub value
    env = {**os.environ, "STUB_PORT": str(port), "STUB_ADMIN_TOKEN": token}
    with open(log_path, "wb") as log_fh:
        proc = subprocess.Popen(  # noqa: S603 — fixed argv, our own module
            [sys.executable, "-m", "stub_server"], cwd=HERE, env=env, stdout=log_fh, stderr=subprocess.STDOUT
        )
        base = f"http://127.0.0.1:{port}/api/v1"
        try:
            deadline = time.monotonic() + 20
            while True:
                try:
                    if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                if proc.poll() is not None or time.monotonic() > deadline:
                    pytest.exit(f"stub server failed to start; log:\n{log_path.read_text()}", returncode=3)
                time.sleep(0.2)
            yield Target(base, log_path, True, token)
        finally:
            proc.terminate()
            proc.wait(timeout=10)


@pytest.fixture(scope="session")
def client(target: Target) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=target.base_url, timeout=10) as c:
        yield c
