"""Live ECCC weather for the API: City Page Weather (qc-147, Montréal) and weather alerts.

Named `weather_live` (not `weather`) because `winterpath_ml.weather` is the climate-daily feature
loader whose sha256 is pinned by the pre-registered gate (`models/gate-logreg-2026.md`); a package of
the same name would replace that module and void the gate run.

Layers (all pure except `provider` and `eccc.http_get_json`):
- `model`    — normalised dataclasses, provenance, freshness rules, DST-safe local-time helpers.
- `eccc`     — fetch → validate → normalise for `citypageweather-realtime` and `weather-alerts`.
- `provider` — per-product TTL cache with single-flight refresh; serves the last validated
               payload, marked delayed/stale, when a refresh fails.

Honesty rules: missing variables stay None (never 0); an empty alert list means "ECCC reported no
alerts for the queried area at fetched_at", never "safe"; alert text is passed through verbatim
(ECCC licence: no alteration of the content or intent of an alert).

Data Source: Environment and Climate Change Canada.
"""

from .model import (
    ATTRIBUTION,
    FRESHNESS_STATES,
    LOCAL_TZ,
    Freshness,
    Provenance,
    Snapshot,
    local_day_bounds_utc,
)
from .provider import LiveWeatherProvider

__all__ = [
    "ATTRIBUTION",
    "FRESHNESS_STATES",
    "LOCAL_TZ",
    "Freshness",
    "LiveWeatherProvider",
    "Provenance",
    "Snapshot",
    "local_day_bounds_utc",
]
