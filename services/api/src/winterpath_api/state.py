"""Application state container (built once at startup; injectable for tests)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog
from winterpath_routing import (
    FixtureGraphProvider,
    GraphProvider,
    GraphUnavailableError,
    NullRiskProvider,
    PedestrianGraph,
    PostgisGraphProvider,
    RiskProvider,
    RoutingEngine,
)

from .adapters import WeatherAdapter, load_risk_provider
from .compute import ComputePool
from .db import create_db_engine, needs_db
from .repositories.hazards import (
    HazardRepository,
    InMemoryHazardRepository,
    PostgisHazardRepository,
)
from .repositories.reports import (
    InMemoryReportRepository,
    PostgisReportRepository,
    ReportRepository,
)
from .repositories.sources import (
    InMemoryPilotRequestRepository,
    PilotRequestRepository,
    PostgisPilotRequestRepository,
    PostgisSourceRepository,
    SourceRepository,
    StaticSourceRepository,
)
from .security import ClientHasher, RateLimiter
from .settings import PILOT_BBOX, Settings

log = structlog.get_logger("winterpath_api.state")


@dataclass
class AppState:
    settings: Settings
    engine: RoutingEngine | None
    graph_error: str | None
    risk: RiskProvider
    reports: ReportRepository
    hazards: HazardRepository
    sources: SourceRepository
    pilot_requests: PilotRequestRepository
    weather: WeatherAdapter | None = None
    db_engine: Any = None
    limiter: RateLimiter = field(default_factory=RateLimiter)
    client_hash: ClientHasher = field(default_factory=ClientHasher)
    compute: ComputePool = field(default_factory=ComputePool)


def _load_graph(
    settings: Settings, provider: GraphProvider | None
) -> tuple[RoutingEngine | None, str | None]:
    if provider is None:
        if settings.graph_source == "none":
            return None, "graph source disabled"
        if settings.graph_source == "postgis":
            if not settings.database_url:
                return None, "ROUTING_GRAPH_SOURCE=postgis but DATABASE_URL is not set"
            # One short-lived connection, released after the load (NullPool): the graph is read
            # once at startup and never again, so it must not hold a pooled connection.
            provider = PostgisGraphProvider(
                settings.database_url,
                PILOT_BBOX,
                connect_timeout_s=settings.db_connect_timeout_s,
            )
        else:
            provider = FixtureGraphProvider(settings.fixture_dir)
    try:
        data = provider.load()
        if settings.routing_compact_graph:
            from winterpath_routing.compact import CompactGraph

            graph = CompactGraph.from_graph_data(data)
        else:
            graph = PedestrianGraph(data)
        del data
    except (GraphUnavailableError, ValueError) as exc:
        log.warning("graph_unavailable", reason=str(exc))
        return None, str(exc)
    log.info(
        "graph_loaded",
        nodes=len(graph.nodes),
        edges=len(graph.edges),
        simulated=graph.metadata.simulated,
        compact=settings.routing_compact_graph,
        steps_v2=settings.routing_steps_v2,
    )
    if settings.routing_compact_graph:
        from winterpath_routing.compact_engine import CompactRoutingEngine

        return CompactRoutingEngine(graph, steps_v2=settings.routing_steps_v2), None
    return RoutingEngine(graph, steps_v2=settings.routing_steps_v2), None


def build_state(
    settings: Settings,
    *,
    graph_provider: GraphProvider | None = None,
    risk: RiskProvider | None = None,
    reports: ReportRepository | None = None,
    hazards: HazardRepository | None = None,
    sources: SourceRepository | None = None,
    pilot_requests: PilotRequestRepository | None = None,
    weather: WeatherAdapter | None = None,
) -> AppState:
    engine, graph_error = _load_graph(settings, graph_provider)

    # One pooled engine per process, shared by every PostGIS-backed component.
    db_engine = create_db_engine(settings) if needs_db(settings) else None
    store_db = db_engine if settings.store_backend == "postgis" else None
    # Personal data (community reports, pilot requests) lives in tables the read-only API role
    # (wp_reader) deliberately cannot SELECT (PII; migration 0001). With public writes disabled
    # the API neither stores nor reads them: those two stores stay in memory (empty), while
    # hazards (closures, 311 aggregates) and sources are still read from PostGIS.
    pii_db = store_db if settings.public_writes else None

    if reports is None:
        reports = PostgisReportRepository(pii_db) if pii_db else InMemoryReportRepository()
    if hazards is None:
        hazards = (
            PostgisHazardRepository(store_db, reports)
            if store_db
            else InMemoryHazardRepository(reports)
        )
    if sources is None:
        sources = PostgisSourceRepository(store_db) if store_db else StaticSourceRepository()
    if pilot_requests is None:
        pilot_requests = (
            PostgisPilotRequestRepository(pii_db) if pii_db else InMemoryPilotRequestRepository()
        )
    if risk is None:
        try:
            edge_coords = None
            if engine is not None:
                edges = engine.graph.edges

                def edge_coords(eid: str):
                    e = edges.get(eid)
                    return e.coords if e is not None else None

            risk = load_risk_provider(
                settings.risk_provider,
                edge_coords,
                engine=db_engine,
                score_source=settings.risk_score_source,
            )
        except (ImportError, AttributeError) as exc:
            log.warning("risk_provider_unavailable", error_type=type(exc).__name__)
            risk = NullRiskProvider()

    if weather is None and settings.weather_source == "postgis" and settings.database_url:
        from datetime import timedelta

        from .weather import ObservationWeatherAdapter, PostgisWeatherStore

        weather = ObservationWeatherAdapter(
            PostgisWeatherStore(db_engine),
            max_age=timedelta(minutes=settings.weather_max_age_minutes),
            station_ids=settings.weather_station_ids,
        )

    compute = ComputePool(settings.routing_workers)
    compute.warm()
    return AppState(
        compute=compute,
        settings=settings,
        engine=engine,
        graph_error=graph_error,
        risk=risk,
        reports=reports,
        hazards=hazards,
        sources=sources,
        pilot_requests=pilot_requests,
        weather=weather,
        db_engine=db_engine,
    )
