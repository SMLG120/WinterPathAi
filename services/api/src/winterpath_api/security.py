"""Admin bearer auth (hash compare), client hashing for rate limits, in-process token bucket."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from datetime import UTC, datetime

from fastapi import Request

from .errors import ApiError


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def check_admin(request: Request, expected_hash: str) -> None:
    """Raise 401 unless ``Authorization: Bearer <token>`` hashes to ``expected_hash``."""
    challenge = {"WWW-Authenticate": "Bearer"}
    expected = expected_hash.removeprefix("sha256:").strip().lower()
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if not expected or scheme.lower() != "bearer" or not token.strip():
        raise ApiError(401, "UNAUTHORIZED", "Missing or invalid admin token.", headers=challenge)
    if not hmac.compare_digest(sha256_hex(token.strip()), expected):
        raise ApiError(401, "UNAUTHORIZED", "Missing or invalid admin token.", headers=challenge)


class ClientHasher:
    """Salted, daily-rotated hash of the client address. Raw IPs are never stored or logged."""

    def __init__(self) -> None:
        self._secret = secrets.token_bytes(32)

    def __call__(self, request: Request, now: datetime | None = None) -> str:
        day = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
        host = request.client.host if request.client else "unknown"
        return hmac.new(self._secret, f"{day}|{host}".encode(), hashlib.sha256).hexdigest()[:32]


class RateLimiter:
    """Token bucket per (bucket, client). Thread-safe; in-process (v1, architecture §9)."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[tuple[str, str], tuple[float, float]] = {}

    def check(self, bucket: str, client: str, per_minute: int) -> None:
        if per_minute <= 0:
            return
        now = self._clock()
        rate = per_minute / 60.0
        with self._lock:
            tokens, last = self._buckets.get((bucket, client), (float(per_minute), now))
            tokens = min(float(per_minute), tokens + (now - last) * rate)
            if tokens < 1.0:
                retry = max(1, int((1.0 - tokens) / rate + 0.999))
                self._buckets[(bucket, client)] = (tokens, now)
                raise ApiError(
                    429,
                    "RATE_LIMITED",
                    "Too many requests.",
                    details={"retry_after_s": retry},
                    headers={"Retry-After": str(retry)},
                )
            self._buckets[(bucket, client)] = (tokens - 1.0, now)
            if len(self._buckets) > 50_000:
                self._buckets.clear()
