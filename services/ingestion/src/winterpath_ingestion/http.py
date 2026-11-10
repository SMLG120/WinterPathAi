"""Polite HTTP downloads: custom User-Agent, ≤3 retries with backoff, raw cache + sha256.

Raw responses are written under ``data/raw/`` (git-ignored). Never substitutes data on failure.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import requests

log = logging.getLogger(__name__)

MAX_RETRIES = 3


class DownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class RawFile:
    path: Path
    sha256: str
    url: str
    fetched_at: str  # ISO UTC
    from_cache: bool


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _meta_path(path: Path) -> Path:
    return path.with_name(path.name + ".meta.json")


def download(
    url: str,
    dest: Path,
    *,
    user_agent: str,
    method: str = "GET",
    data: dict | None = None,
    params: dict | None = None,
    refresh: bool = False,
    timeout: int = 300,
    sleep=time.sleep,
    session: requests.Session | None = None,
) -> RawFile:
    """Download ``url`` to ``dest`` (streamed, atomic rename). Reuses the cached file unless
    ``refresh``. Retries up to MAX_RETRIES with exponential backoff; HTTP 429 waits ≥30 s
    (Overpass policy)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    meta = _meta_path(dest)
    if dest.exists() and meta.exists() and not refresh:
        m = json.loads(meta.read_text())
        return RawFile(dest, sha256_file(dest), m["url"], m["fetched_at"], True)

    s = session or requests.Session()
    headers = {"User-Agent": user_agent}
    last: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with s.request(
                method,
                url,
                data=data,
                params=params,
                headers=headers,
                stream=True,
                timeout=timeout,
            ) as r:
                if r.status_code == 429 or r.status_code >= 500:
                    raise DownloadError(f"HTTP {r.status_code} from {url}")
                r.raise_for_status()
                tmp = dest.with_name(dest.name + ".part")
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                os.replace(tmp, dest)
            fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
            meta.write_text(json.dumps({"url": url, "params": params, "fetched_at": fetched_at}))
            return RawFile(dest, sha256_file(dest), url, fetched_at, False)
        except (requests.RequestException, DownloadError) as e:
            last = e
            log.warning("download attempt %d/%d failed: %s", attempt, MAX_RETRIES, e)
            if attempt < MAX_RETRIES:
                wait = 30 if "429" in str(e) else 2**attempt * 5
                sleep(wait)
    raise DownloadError(f"giving up after {MAX_RETRIES} attempts: {last}")
