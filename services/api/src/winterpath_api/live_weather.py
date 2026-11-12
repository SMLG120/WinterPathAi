"""Contract v1.8: live ECCC forecast and alerts, served from ML's in-process provider.

``winterpath_ml.weather_live.LiveWeatherProvider`` keeps City Page Weather (qc-147) and the
weather-alerts collection in a per-product TTL cache with a single-flight refresh. This module
turns its snapshots into contract payloads. Rules:

* One provider per process (``AppState.live_weather``), injectable for tests.
* ``/weather/forecast``, ``/weather/alerts`` and ``/weather/current`` call the provider: a refresh
  happens only when the product's TTL has passed, and concurrent requests share it.
* ``/data-status`` and ``routes/compare``'s ``weather_context`` use :meth:`peek`: the last snapshot
  this process obtained, with its freshness recomputed for "now". They never trigger a refresh.
* 503 only when no validated payload exists or the last one's validity has ended (freshness
  ``unavailable``). Otherwise the cached payload is served with its degraded freshness.
* Missing values stay null; alert text is passed through verbatim; an empty alert list means
  ECCC reported no alert for the queried area at ``provenance.fetched_at``, never "safe".
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .adapters import WeatherUnavailableError

ECCC_SOURCE_ID = "eccc-geomet"


@dataclass(frozen=True, slots=True)
class Peek:
    """Freshness of a product without refreshing it."""

    freshness: dict[str, Any]
    last_success_at: datetime | None
    snapshot: Any  # winterpath_ml Snapshot | None


def _text(t: Any) -> dict[str, str | None]:
    return {"en": getattr(t, "en", None), "fr": getattr(t, "fr", None)}


def _freshness(f: Any) -> dict[str, Any]:
    return {"state": f.state, "reason": f.reason, "evaluated_at": f.evaluated_at}


def _provenance(p: Any) -> dict[str, Any] | None:
    if p is None:
        return None
    return {
        "provider": p.provider,
        "product": p.product,
        "source_url": p.source_url,
        "issued_at": p.issued_at,
        "valid_from": p.valid_from,
        "valid_to": p.valid_to,
        "fetched_at": p.fetched_at,
        "validated_at": p.validated_at,
        "attribution": p.attribution,
        "licence_url": p.licence_url,
    }


def _pop(v: float | None) -> int | None:
    return None if v is None else round(v)


class LiveWeather:
    """Contract payloads over one ``LiveWeatherProvider`` (see the module docstring)."""

    def __init__(self, provider: Any, clock: Callable[[], datetime] | None = None) -> None:
        from winterpath_ml.weather_live.model import ALERTS_POLICY, CITYPAGE_POLICY

        self.provider = provider
        self.clock = clock or getattr(provider, "_clock", None) or (lambda: datetime.now(UTC))
        self._policies = {"citypage": CITYPAGE_POLICY, "alerts": ALERTS_POLICY}
        self._last: dict[str, Any] = {"citypage": None, "alerts": None}

    # ------------------------------------------------------------------ provider access
    def _get(self, product: str) -> Any:
        snap = self.provider.citypage() if product == "citypage" else self.provider.alerts()
        if snap.data is not None:
            self._last[product] = snap
        elif self._last[product] is None:
            self._last[product] = snap  # remember "never obtained" with its reason
        return snap

    def peek(self, product: str) -> Peek:
        """Freshness now, from the last snapshot this process obtained. Never refreshes."""
        from winterpath_ml.weather_live.model import freshness

        now = self.clock()
        snap = self._last[product]
        prov = snap.provenance if snap is not None and snap.data is not None else None
        if prov is None:
            reason = (
                snap.freshness.reason
                if snap is not None
                else "not requested since this API process started (fetched on demand)"
            )
            f = {"state": "unavailable", "reason": reason, "evaluated_at": now}
            return Peek(f, None, None)
        return Peek(
            _freshness(freshness(prov, now, self._policies[product])), prov.fetched_at, snap
        )

    @staticmethod
    def _usable(snap: Any) -> bool:
        return snap is not None and snap.data is not None and snap.freshness.state != "unavailable"

    # ------------------------------------------------------------------ /weather/forecast
    def forecast(self, hours: int) -> dict[str, Any]:
        snap = self._get("citypage")
        if not self._usable(snap):
            raise WeatherUnavailableError(f"ECCC forecast unavailable: {snap.freshness.reason}")
        page, prov = snap.data, snap.provenance
        issued = page.hourly_issued_at or prov.issued_at
        if issued is None:
            raise WeatherUnavailableError("ECCC forecast has no issue time")
        now = self.clock()
        periods = [
            {
                "start": h.time_utc,
                "end": h.time_utc + timedelta(hours=1),
                # The contract requires strings; a condition ECCC did not publish is "" (empty),
                # never an invented description.
                "summary_en": h.condition.en or "",
                "summary_fr": h.condition.fr or "",
                "temperature_c": h.temperature_c,
                "pop_percent": _pop(h.precip_probability_pct),
                "wind_speed_kmh": h.wind_speed_kmh,
                "wind_gust_kmh": h.wind_gust_kmh,
            }
            for h in page.hourly
            if h.time_utc + timedelta(hours=1) > now
        ][:hours]
        text_periods = [
            {
                "name": _text(p.name),
                "summary": _text(p.summary),
                "temperature_high_c": p.temperature_high_c,
                "temperature_low_c": p.temperature_low_c,
                "wind_chill_c": p.wind_chill_c,
                "precipitation": _text(p.precipitation_text),
            }
            for p in page.periods
        ]
        alerts, alert_note = self._forecast_alerts()
        note = (
            "ECCC City Page Weather forecast (Montréal, qc-147): a forecast, not an observation. "
            f"Freshness {snap.freshness.state}: {snap.freshness.reason}. {alert_note}"
        )
        if snap.fallback:
            note += f" Provider fallback: {snap.fallback}."
        return {
            "issued_at": issued,
            "periods": periods,
            "text_periods": text_periods,
            "location": page.location_id,
            "freshness": _freshness(snap.freshness),
            "provenance": _provenance(prov),
            "alerts": alerts,
            "evidence": {
                "state": "model_estimate",
                "source_ids": [ECCC_SOURCE_ID],
                "observed_at": None,
                "retrieved_at": prov.fetched_at,
                "confidence": None,
                "note": note.strip(),
            },
        }

    def _forecast_alerts(self) -> tuple[list[dict[str, Any]], str]:
        """v1.7 ``alerts`` items (one per language) from the alerts product, verbatim."""
        snap = self._get("alerts")
        if not self._usable(snap):
            return [], (
                "Alerts are unavailable right now (see /weather/alerts); an empty list here "
                "does not mean there are no alerts."
            )
        out: list[dict[str, Any]] = []
        skipped = 0
        for a in snap.data.active(self.clock()):
            if a.published_at is None:  # issued_at is required; never invented
                skipped += 1
                continue
            for lang in ("en", "fr"):
                text = getattr(a.text, lang)
                if not text:
                    continue
                out.append(
                    {
                        "id": a.id,
                        "headline": getattr(a.name, lang) or "",
                        "text": text,
                        "language": lang,
                        "severity": a.type,
                        "issued_at": a.published_at,
                        "expires_at": a.expires_at,
                    }
                )
        note = f"Alerts: ECCC weather-alerts ({a_match(snap)}), freshness {snap.freshness.state}."
        if skipped:
            note += (
                f" {skipped} alert(s) without a publication time are listed only in "
                "/weather/alerts."
            )
        return out, note

    # ------------------------------------------------------------------ /weather/alerts
    def alerts(self) -> dict[str, Any]:
        snap = self._get("alerts")
        if not self._usable(snap):
            raise WeatherUnavailableError(f"ECCC alerts unavailable: {snap.freshness.reason}")
        return {
            "alerts": [
                {
                    "id": a.id,
                    "type": a.type,
                    "name": _text(a.name),
                    "text": _text(a.text),
                    "area_name": _text(a.area_name),
                    "risk_colour": a.risk_colour,
                    "published_at": a.published_at,
                    "valid_from": a.valid_from,
                    "expires_at": a.expires_at,
                    "area_match": a.area_match,
                }
                for a in snap.data.active(self.clock())
            ],
            "freshness": _freshness(snap.freshness),
            "provenance": _provenance(snap.provenance),
        }

    # ------------------------------------------------------------------ /weather/current
    def current_conditions(self) -> tuple[Any, Any] | None:
        """(CurrentConditions, Snapshot) when City Page current conditions are usable."""
        snap = self._get("citypage")
        if not self._usable(snap) or snap.data.current is None:
            return None
        return snap.data.current, snap

    # ------------------------------------------------------------------ weather_context
    def context_at(self, departure: datetime) -> dict[str, Any] | None:
        """Hourly forecast covering ``departure`` from the cached forecast; None outside it.
        Never refreshes (routing latency is not tied to an upstream call)."""
        pk = self.peek("citypage")
        if pk.snapshot is None or pk.freshness["state"] == "unavailable":
            return None
        for h in pk.snapshot.data.hourly:
            if h.time_utc <= departure < h.time_utc + timedelta(hours=1):
                return {
                    "departure_time": departure,
                    "used_for": "display_only",
                    "hour_start": h.time_utc,
                    "condition": _text(h.condition),
                    "temperature_c": h.temperature_c,
                    "pop_percent": _pop(h.precip_probability_pct),
                    "freshness": pk.freshness,
                }
        return None


def a_match(snap: Any) -> str:
    matches = {a.area_match for a in snap.data.alerts}
    return ", ".join(sorted(matches)) if matches else "no alert matched the queried area"


def build_live_weather(user_agent: str) -> LiveWeather:
    """Production wiring: one provider per process, real HTTP with the configured User-Agent."""
    from winterpath_ml.weather_live import LiveWeatherProvider, eccc

    def fetch(url: str) -> Any:
        # eccc.http_get_json reads the module-level USER_AGENT at call time.
        eccc.USER_AGENT = user_agent
        return eccc.http_get_json(url)

    return LiveWeather(LiveWeatherProvider(fetch_json=fetch))
