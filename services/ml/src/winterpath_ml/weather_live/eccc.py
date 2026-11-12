"""ECCC MSC GeoMet OGC API: fetch → validate → normalise. Parsing functions are pure.

Products (api.weather.gc.ca):
- `citypageweather-realtime` item `qc-147` (Montréal): current conditions, 24 hourly forecasts,
  named text periods, warnings.
- `weather-alerts` items intersecting a bbox. Until Data publishes the island polygon, matching is
  "bbox intersects" and is labelled so (neighbouring areas such as Laval can match).

Only structures seen in recorded responses are parsed. Unknown or missing fields stay None.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from .model import (
    PROVIDER,
    Alert,
    AlertSet,
    CityPage,
    CurrentConditions,
    HourlyForecast,
    PeriodForecast,
    Provenance,
    Text,
    Warning,
    local_iso,
    parse_utc,
)

BASE = "https://api.weather.gc.ca"
CITYPAGE_ID = "qc-147"
# Approximate envelope of the Island of Montréal (main island plus nearby islands). Replaced by
# Data's island polygon in Wave 3; the bbox can match alerts for neighbouring areas.
ISLAND_BBOX = (-73.98, 45.40, -73.47, 45.71)
USER_AGENT = os.environ.get(
    "HTTP_USER_AGENT", "WinterPathAI-dev/0.1 (local development)"
)


class FetchError(RuntimeError):
    """Network or HTTP failure (not a statement about the weather)."""


class ProductUnavailable(FetchError):
    """HTTP 404: the product, item or collection is not (or no longer) published."""


class MalformedPayload(ValueError):
    """The response does not have the structure this parser was written and tested against."""


def citypage_url(location_id: str = CITYPAGE_ID) -> str:
    return f"{BASE}/collections/citypageweather-realtime/items/{location_id}?f=json"


def alerts_url(bbox: tuple[float, float, float, float] = ISLAND_BBOX) -> str:
    q = urllib.parse.urlencode(
        {"f": "json", "bbox": ",".join(f"{v:g}" for v in bbox), "limit": 500}
    )
    return f"{BASE}/collections/weather-alerts/items?{q}"


def http_get_json(url: str, timeout: float = 8.0) -> Any:
    """GET + JSON decode. Raises ProductUnavailable on 404, FetchError on other failures."""
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ProductUnavailable(f"HTTP 404 for {url}") from e
        raise FetchError(f"HTTP {e.code} for {url}") from e
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise FetchError(f"{type(e).__name__}: {e} for {url}") from e
    try:
        return json.loads(body)
    except ValueError as e:
        raise MalformedPayload(f"response is not JSON: {e}") from e


# ----------------------------------------------------------------- small typed accessors


def _get(node: Any, *path: str) -> Any:
    for k in path:
        if not isinstance(node, dict) or k not in node:
            return None
        node = node[k]
    return node


def _lang(node: Any, lang: str) -> Any:
    """ECCC bilingual leaf: {"en": x, "fr": y} -> x; a plain scalar passes through."""
    if isinstance(node, dict):
        return node.get(lang)
    return node


def _text(node: Any) -> Text:
    en, fr = _lang(node, "en"), _lang(node, "fr")
    return Text(
        en if isinstance(en, str) and en else None,
        fr if isinstance(fr, str) and fr else None,
    )


def _num(node: Any) -> float | None:
    """Numeric leaf (possibly bilingual, possibly a numeric string). Missing/blank -> None, never 0."""
    v = _lang(node, "en")
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int | float):
        return float(v)
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _str(node: Any) -> str | None:
    v = _lang(node, "en")
    return v if isinstance(v, str) and v else None


def _ts(node: Any) -> datetime | None:
    v = _lang(node, "en")
    if v is None:
        return None
    try:
        return parse_utc(v)
    except ValueError:
        return None


# ----------------------------------------------------------------- City Page Weather


def parse_citypage(
    doc: Any,
    *,
    fetched_at: datetime,
    validated_at: datetime,
    source_url: str,
    expected_id: str = CITYPAGE_ID,
) -> tuple[CityPage, Provenance]:
    if not isinstance(doc, dict) or doc.get("type") != "Feature":
        raise MalformedPayload("expected a GeoJSON Feature")
    p = doc.get("properties")
    if not isinstance(p, dict):
        raise MalformedPayload("missing properties")
    if p.get("identifier") != expected_id:
        raise MalformedPayload(
            f"identifier {p.get('identifier')!r} != expected {expected_id!r}"
        )
    try:
        issued = parse_utc(p.get("lastUpdated"))
    except ValueError as e:
        raise MalformedPayload(f"lastUpdated: {e}") from e

    cc = p.get("currentConditions")
    current = None
    if isinstance(cc, dict) and cc:
        obs = _ts(cc.get("timestamp"))
        current = CurrentConditions(
            observed_at=obs,
            observed_at_local=local_iso(obs) if obs else None,
            station_code=_str(_get(cc, "station", "code")),
            station_name=_text(_get(cc, "station", "value")),
            condition=_text(cc.get("condition")),
            temperature_c=_num(_get(cc, "temperature", "value")),
            dewpoint_c=_num(_get(cc, "dewpoint", "value")),
            wind_chill=_num(_get(cc, "windChill", "value")),
            relative_humidity_pct=_num(_get(cc, "relativeHumidity", "value")),
            wind_speed_kmh=_num(_get(cc, "wind", "speed", "value")),
            wind_gust_kmh=_num(_get(cc, "wind", "gust", "value")),
            wind_direction=_str(_get(cc, "wind", "direction", "value")),
            pressure_kpa=_num(_get(cc, "pressure", "value")),
        )

    hg = p.get("hourlyForecastGroup")
    hourly: list[HourlyForecast] = []
    hourly_issued = None
    if hg is not None:
        items = _get(hg, "hourlyForecasts")
        if not isinstance(items, list):
            raise MalformedPayload("hourlyForecastGroup.hourlyForecasts is not a list")
        hourly_issued = _ts(_get(hg, "timestamp"))
        for i, h in enumerate(items):
            if not isinstance(h, dict):
                raise MalformedPayload(f"hourly[{i}] is not an object")
            try:
                t = parse_utc(_lang(h.get("timestamp"), "en"))
            except ValueError as e:
                raise MalformedPayload(f"hourly[{i}].timestamp: {e}") from e
            hourly.append(
                HourlyForecast(
                    time_utc=t,
                    time_local=local_iso(t),
                    condition=_text(h.get("condition")),
                    temperature_c=_num(_get(h, "temperature", "value")),
                    precip_probability_pct=_num(_get(h, "lop", "value")),
                    precip_probability_category=_text(_get(h, "lop", "category")),
                    wind_speed_kmh=_num(_get(h, "wind", "speed", "value")),
                    wind_gust_kmh=_num(_get(h, "wind", "gust", "value")),
                    wind_direction=_str(_get(h, "wind", "direction", "value")),
                    uv_index=_num(_get(h, "uv", "index", "value")),
                )
            )
        times = [h.time_utc for h in hourly]
        if times != sorted(times) or len(set(times)) != len(times):
            raise MalformedPayload("hourly timestamps are not strictly increasing")

    fg = p.get("forecastGroup")
    periods: list[PeriodForecast] = []
    periods_issued = None
    if fg is not None:
        items = _get(fg, "forecasts")
        if not isinstance(items, list):
            raise MalformedPayload("forecastGroup.forecasts is not a list")
        periods_issued = _ts(_get(fg, "timestamp"))
        for f in items:
            if not isinstance(f, dict):
                raise MalformedPayload("forecast period is not an object")
            temps = _get(f, "temperatures", "temperature") or []
            hi = lo = None
            for t in temps if isinstance(temps, list) else []:
                cls = _str(_get(t, "class"))
                if cls == "high":
                    hi = _num(_get(t, "value"))
                elif cls == "low":
                    lo = _num(_get(t, "value"))
            periods.append(
                PeriodForecast(
                    name=_text(_get(f, "period", "textForecastName")),
                    summary=_text(f.get("textSummary")),
                    temperature_high_c=hi,
                    temperature_low_c=lo,
                    wind_chill_text=_text(_get(f, "windChill", "textSummary")),
                    wind_chill_c=_num(_get(f, "windChill", "calculated")),
                    precipitation_text=_text(_get(f, "precipitation", "textSummary")),
                )
            )

    ws = p.get("warnings")
    if ws is not None and not isinstance(ws, list):
        raise MalformedPayload("warnings is not a list")
    warnings = tuple(
        Warning(
            description=_text(w.get("description")),
            type=_str(w.get("type")),
            colour=_str(w.get("alertColourLevel")),
            issued_at=_ts(w.get("eventIssue")),
            expires_at=_ts(w.get("expiryTime")),
            url=_text(w.get("url")),
        )
        for w in (ws or [])
        if isinstance(w, dict)
    )

    page = CityPage(
        location_id=expected_id,
        name=_text(p.get("name")),
        region=_text(p.get("region")),
        current=current,
        hourly=tuple(hourly),
        hourly_issued_at=hourly_issued,
        periods=tuple(periods),
        periods_issued_at=periods_issued,
        warnings=warnings,
    )
    from datetime import timedelta

    valid_to = hourly[-1].time_utc + timedelta(hours=1) if hourly else None
    prov = Provenance(
        provider=PROVIDER,
        product=f"citypageweather-realtime/{expected_id}",
        source_url=source_url,
        issued_at=issued,
        valid_from=hourly[0].time_utc if hourly else issued,
        valid_to=valid_to,
        fetched_at=fetched_at,
        validated_at=validated_at,
    )
    return page, prov


# ----------------------------------------------------------------- weather alerts


def parse_alerts(
    doc: Any,
    *,
    fetched_at: datetime,
    validated_at: datetime,
    source_url: str,
    bbox: tuple[float, float, float, float] = ISLAND_BBOX,
) -> tuple[AlertSet, Provenance]:
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection":
        raise MalformedPayload("expected a GeoJSON FeatureCollection")
    feats = doc.get("features")
    if not isinstance(feats, list):
        raise MalformedPayload("features is not a list")
    alerts = []
    for i, f in enumerate(feats):
        p = _get(f, "properties")
        if not isinstance(p, dict) or not isinstance(f.get("id"), str):
            raise MalformedPayload(f"feature[{i}] lacks id/properties")
        alerts.append(
            Alert(
                id=f["id"],
                code=_str(p.get("alert_code")),
                type=_str(p.get("alert_type")),
                name=Text(_str(p.get("alert_name_en")), _str(p.get("alert_name_fr"))),
                text=Text(p.get("alert_text_en"), p.get("alert_text_fr")),
                area_name=Text(
                    _str(p.get("feature_name_en")), _str(p.get("feature_name_fr"))
                ),
                risk_colour=_str(p.get("risk_colour_en")),
                status=Text(_str(p.get("status_en")), _str(p.get("status_fr"))),
                confidence=Text(
                    _str(p.get("confidence_en")), _str(p.get("confidence_fr"))
                ),
                impact=Text(_str(p.get("impact_en")), _str(p.get("impact_fr"))),
                published_at=_ts(p.get("publication_datetime")),
                valid_from=_ts(p.get("validity_datetime")),
                expires_at=_ts(p.get("expiration_datetime")),
                event_end_at=_ts(p.get("event_end_datetime")),
                area_match="bbox_intersects",
            )
        )
    nm = doc.get("numberMatched")
    returned = doc.get("numberReturned")
    if isinstance(nm, int) and isinstance(returned, int) and nm > returned:
        raise MalformedPayload(
            f"truncated: numberMatched {nm} > numberReturned {returned} (raise limit)"
        )
    pubs = [a.published_at for a in alerts if a.published_at]
    prov = Provenance(
        provider=PROVIDER,
        product="weather-alerts",
        source_url=source_url,
        issued_at=max(pubs) if pubs else None,
        valid_from=None,
        valid_to=None,
        fetched_at=fetched_at,
        validated_at=validated_at,
    )
    return AlertSet(
        query_bbox=bbox,
        alerts=tuple(alerts),
        number_matched=nm if isinstance(nm, int) else None,
    ), prov
