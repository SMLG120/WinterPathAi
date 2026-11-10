import pytest
import requests

from winterpath_ingestion import http
from winterpath_ingestion.runs import run_atomic


def test_noop_on_same_checksum(tmp_path):
    calls = []

    def build(st, rid):
        calls.append(rid)
        (st / "out.txt").write_text("v1")
        return {}

    r1 = run_atomic("x", tmp_path, "abc", build)
    r2 = run_atomic("x", tmp_path, "abc", build)
    assert not r1.noop and r2.noop and len(calls) == 1


def test_failed_run_keeps_previous_output(tmp_path):
    run_atomic("x", tmp_path, "abc", lambda st, rid: (st / "out.txt").write_text("v1") and {})

    def boom(st, rid):
        (st / "out.txt").write_text("partial")
        raise RuntimeError("upstream failure")

    with pytest.raises(RuntimeError):
        run_atomic("x", tmp_path, "def", boom)
    assert (tmp_path / "x" / "out.txt").read_text() == "v1"
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".x.staging")]


class _FailingSession:
    def __init__(self):
        self.n = 0

    def request(self, *a, **k):
        self.n += 1
        raise requests.ConnectionError("down")


def test_download_retries_three_times_then_raises(tmp_path):
    s = _FailingSession()
    waits = []
    with pytest.raises(http.DownloadError):
        http.download(
            "https://example.invalid/x",
            tmp_path / "x",
            user_agent="t",
            session=s,
            sleep=waits.append,
        )
    assert s.n == 3 and len(waits) == 2
    assert not (tmp_path / "x").exists()
