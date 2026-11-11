"""In-process provider: per-product TTL cache with single-flight refresh.

- One refresh per product per process at a time; concurrent callers wait for it and share the
  result (never one fetch per request).
- A fresh cache entry (younger than the TTL) is served without any fetch.
- After a failed refresh, no new attempt is made for `retry_after`, so an outage does not turn
  every request into a slow upstream call. The last validated payload keeps being served, and its
  freshness degrades (delayed → stale → unavailable when its validity ends).
- If City Page Weather is unavailable (no payload, 404, or expired), the snapshot carries
  `fallback="observations_only"`: consumers should show observations (SWOB) only, with no forecast.
- The clock and fetcher are injectable for tests; no wall-clock reads elsewhere.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from . import eccc
from .model import (
    ALERTS_POLICY,
    CITYPAGE_POLICY,
    FreshnessPolicy,
    Snapshot,
    freshness,
)

log = logging.getLogger(__name__)


@dataclass
class _Entry:
    snapshot: Snapshot | None = None
    last_attempt: datetime | None = None
    last_error: str | None = None
    product_missing: bool = False


class LiveWeatherProvider:
    def __init__(
        self,
        fetch_json: Callable[[str], Any] = eccc.http_get_json,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        location_id: str = eccc.CITYPAGE_ID,
        bbox: tuple[float, float, float, float] = eccc.ISLAND_BBOX,
        retry_after: timedelta = timedelta(seconds=60),
    ) -> None:
        self._fetch, self._clock = fetch_json, clock
        self.location_id, self.bbox, self.retry_after = location_id, bbox, retry_after
        self._entries = {"citypage": _Entry(), "alerts": _Entry()}
        self._locks = {k: threading.Lock() for k in self._entries}
        self.fetch_count = {k: 0 for k in self._entries}

    # -- public
    def citypage(self) -> Snapshot:
        return self._get(
            "citypage",
            eccc.citypage_url(self.location_id),
            CITYPAGE_POLICY,
            lambda doc, f, v, url: eccc.parse_citypage(
                doc,
                fetched_at=f,
                validated_at=v,
                source_url=url,
                expected_id=self.location_id,
            ),
        )

    def alerts(self) -> Snapshot:
        return self._get(
            "alerts",
            eccc.alerts_url(self.bbox),
            ALERTS_POLICY,
            lambda doc, f, v, url: eccc.parse_alerts(
                doc, fetched_at=f, validated_at=v, source_url=url, bbox=self.bbox
            ),
        )

    # -- internals
    def _due(self, e: _Entry, now: datetime, policy: FreshnessPolicy) -> bool:
        if (
            e.last_attempt is not None
            and e.last_error
            and now - e.last_attempt < self.retry_after
        ):
            return False
        if e.snapshot is None or e.snapshot.provenance is None:
            return True
        return now - e.snapshot.provenance.fetched_at >= policy.ttl

    def _get(self, key, url, policy, parse) -> Snapshot:
        e = self._entries[key]
        with self._locks[key]:  # single-flight: one refresh at a time per product
            now = self._clock()
            if self._due(e, now, policy):
                e.last_attempt = now
                self.fetch_count[key] += 1
                try:
                    doc = self._fetch(url)
                    fetched = self._clock()
                    data, prov = parse(doc, fetched, self._clock(), url)
                    e.snapshot = Snapshot(
                        key, data, prov, freshness(prov, fetched, policy)
                    )
                    e.last_error, e.product_missing = None, False
                except eccc.ProductUnavailable as x:
                    e.last_error, e.product_missing = str(x), True
                    log.warning("weather_live_product_unavailable: %s", key)
                except (eccc.FetchError, eccc.MalformedPayload) as x:
                    e.last_error = f"{type(x).__name__}: {x}"
                    log.warning(
                        "weather_live_refresh_failed: %s %s", key, type(x).__name__
                    )
            return self._view(key, e, policy)

    def _view(self, key: str, e: _Entry, policy: FreshnessPolicy) -> Snapshot:
        now = self._clock()
        prov = e.snapshot.provenance if e.snapshot else None
        f = freshness(prov, now, policy, e.last_error)
        if e.product_missing and f.state == "current":
            f = type(f)("delayed", f.reason + "; product currently not published", now)
        fallback = (
            "observations_only"
            if key == "citypage" and (f.state == "unavailable" or e.product_missing)
            else None
        )
        if e.snapshot is None:
            return Snapshot(key, None, None, f, fallback)
        return e.snapshot.with_freshness(f, fallback)
