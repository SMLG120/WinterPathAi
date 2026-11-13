"""Contract v1.8 ``GET /data-status``: freshness of every dynamic data product.

Never triggers a refresh: live weather is read with ``LiveWeather.peek`` (the last snapshot this
process obtained); everything else comes from what is already stored (``wp.source``,
``wp.weather_obs``, ``wp.risk_cell_score``, the loaded graph). A product whose state cannot be
determined is ``unavailable`` with the reason; this endpoint itself never fails with 503.

Thresholds are stated in each product's ``notes``. "manual" products have no promised cadence;
their thresholds only say when the data should no longer be presented as current.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

log = structlog.get_logger("winterpath_api.data_status")

H, D = timedelta(hours=1), timedelta(days=1)


def _age_state(age: timedelta, delayed: timedelta, stale: timedelta) -> tuple[str, str]:
    mins = age.total_seconds() / 60
    txt = f"{mins / 60:.1f} h" if mins >= 120 else f"{mins:.0f} min"
    if age > stale:
        return "stale", f"last update {txt} ago (stale after {stale})"
    if age > delayed:
        return "delayed", f"last update {txt} ago (delayed after {delayed})"
    return "current", f"last update {txt} ago"


def _product(
    pid: str,
    mechanism: str,
    now: datetime,
    at: datetime | None,
    delayed: timedelta,
    stale: timedelta,
    *,
    cadence: str | None,
    notes: str,
    missing: str,
    last_success_at: datetime | None = None,
) -> dict[str, Any]:
    if at is None:
        state, reason = "unavailable", missing
    else:
        state, reason = _age_state(now - at, delayed, stale)
    return {
        "id": pid,
        "freshness": {"state": state, "reason": reason, "evaluated_at": now},
        "last_success_at": last_success_at if last_success_at is not None else at,
        "expected_cadence": cadence,
        "mechanism": mechanism,
        "notes": notes,
    }


def _sources(state) -> tuple[dict[str, datetime | None], str | None]:
    try:
        return {r["id"]: r.get("last_success_at") for r in state.sources.list()}, None
    except Exception as exc:  # registry down: every source-backed product is unavailable
        log.warning("data_status_sources_failed", error_type=type(exc).__name__)
        return {}, f"source registry unavailable ({type(exc).__name__})"


def _latest_obs(state) -> tuple[Any, str]:
    store = getattr(state.weather, "store", None)
    if store is None:
        return None, "no observation store configured in this deployment"
    try:
        obs = store.latest_obs(getattr(state.weather, "station_ids", []))
    except Exception as exc:
        return None, f"observation store unavailable ({type(exc).__name__})"
    return obs, "no ECCC observation ingested"


def _weather_max_age_minutes(state) -> int:
    """WEATHER_MAX_AGE_MINUTES (the /health limit); 180 like Settings when unavailable."""
    v = getattr(getattr(state, "settings", None), "weather_max_age_minutes", None)
    return v if isinstance(v, int) and v > 0 else 180


def _hm(d: timedelta) -> str:
    m = int(d.total_seconds() // 60)
    return f"{m // 60} h" if m % 60 == 0 else f"{m // 60} h {m % 60:02d} min"


def _latest_scores(state) -> tuple[datetime | None, str]:
    if state.db_engine is None:
        return None, "no database configured in this deployment"
    try:
        from sqlalchemy import text

        with state.db_engine.connect() as c:
            if not c.execute(text("SELECT to_regclass('wp.risk_cell_score') IS NOT NULL")).scalar():
                return None, "wp.risk_cell_score does not exist"
            at = c.execute(text("SELECT max(scored_at) FROM wp.risk_cell_score")).scalar()
    except Exception as exc:
        return None, f"score table unavailable ({type(exc).__name__})"
    return at, "no score row written yet"


def data_status(state, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    products: list[dict[str, Any]] = []

    # ---- weather observations (scheduled ingest into wp.weather_obs)
    obs, why = _latest_obs(state)
    # "delayed" uses the same limit as /health (WEATHER_MAX_AGE_MINUTES, 300 in production since
    # 2026-11-13), so the two endpoints never disagree; a 3-h cron + ~1 h ECCC lag routinely
    # exceeds 90 min. "stale" stays at 6 h, and is always at least 1 h after "delayed".
    obs_delayed = timedelta(minutes=_weather_max_age_minutes(state))
    obs_stale = max(6 * H, obs_delayed + H)
    products.append(
        _product(
            "weather_observations",
            "scheduled_job",
            now,
            obs.observed_at if obs else None,
            obs_delayed,
            obs_stale,
            cadence="PT3H",
            notes="ECCC SWOB observations ingested by the scheduled job (best effort); age is the "
            f"observation time. Delayed after {_hm(obs_delayed)}, stale after {_hm(obs_stale)}.",
            missing=why,
            last_success_at=getattr(obs, "retrieved_at", None) if obs else None,
        )
    )

    # ---- live forecast / alerts (API on demand, never refreshed here)
    lw = state.live_weather
    for pid, product, cadence, note in (
        ("weather_forecast", "citypage", "PT10M", "ECCC City Page Weather qc-147"),
        ("weather_alerts", "alerts", "PT5M", "ECCC weather-alerts (island bbox)"),
    ):
        if lw is None:
            f = {
                "state": "unavailable",
                "reason": "live ECCC weather is disabled in this deployment",
                "evaluated_at": now,
            }
            last = None
        else:
            pk = lw.peek(product)
            f, last = pk.freshness, pk.last_success_at
        products.append(
            {
                "id": pid,
                "freshness": f,
                "last_success_at": last,
                "expected_cadence": cadence,
                "mechanism": "api_on_demand",
                "notes": f"{note}, refreshed in memory by the API when requested and its cache "
                "is older than the cadence. Nothing refreshes while the service sleeps; this "
                "endpoint does not refresh it.",
            }
        )

    # ---- source-registry products
    src, src_err = _sources(state)

    def last(source_id: str) -> tuple[datetime | None, str]:
        if src_err:
            return None, src_err
        at = src.get(source_id)
        return at, f"no recorded successful refresh of {source_id}"

    at, why = last("mtl-entraves")
    products.append(
        _product(
            "closures",
            "scheduled_job",
            now,
            at,
            2 * D,
            7 * D,
            cadence="PT12H",
            notes="Ville de Montréal entraves (permits), refreshed by a scheduled job twice a day "
            "(GitHub Actions cron, best effort). Delayed after 2 days, stale after 7.",
            missing=why,
        )
    )
    at, why = last("mtl-311")
    products.append(
        _product(
            "reports_311",
            "scheduled_job",
            now,
            at,
            2 * D,
            7 * D,
            cadence="P1D",
            notes="Ville de Montréal 311 requests (reports, not confirmed obstacles), aggregated "
            "by a daily scheduled job (best effort) plus a weekly full rebuild. Delayed after 2 "
            "days, stale after 7. last_success_at is the ingest time, not the date of the latest "
            "request.",
            missing=why,
        )
    )

    # ---- risk scores (scheduled job writes wp.risk_cell_score)
    at, why = _latest_scores(state)
    products.append(
        _product(
            "risk_scores",
            "scheduled_job",
            now,
            at,
            20 * H,
            48 * H,
            cadence="PT12H",
            notes="Heuristic/model scores written by the scheduled scoring job (12:00 and 18:00 "
            "UTC, best effort). Delayed after 20 h, stale after 48 h.",
            missing=why,
        )
    )

    # ---- pedestrian graph
    g = state.engine.graph if state.engine is not None else None
    if g is None:
        at, why = None, f"no pedestrian graph loaded ({state.graph_error})"
    else:
        at = g.metadata.built_at
        if at is None:
            at, why = last("osm")
        else:
            why = ""
    products.append(
        _product(
            "pedestrian_graph",
            "manual",
            now,
            at,
            30 * D,
            90 * D,
            cadence=None,
            notes="OpenStreetMap-derived graph, rebuilt manually. Delayed after 30 days, stale "
            "after 90.",
            missing=why or "graph build time unknown",
        )
    )
    return {"generated_at": now, "products": products}
