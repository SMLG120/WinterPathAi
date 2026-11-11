"""Inference interface consumed by `services/api` (integration-rules §2).

Providers never compute features on the fly; they read per-day score tables produced by
`winterpath_ml.score` from the versioned artifacts listed in `models/registry.json`.

Honesty rules enforced here:
- Anything outside coverage (unknown cell, out-of-season day, unscored day, partial edge
  coverage) -> level `unknown`, probability None. Unknown is never mapped to `low`.
- The heuristic layer never exposes a probability.
- A model that failed the gate cannot be loaded as a probability provider.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

import h3
import pandas as pd

from . import config

log = logging.getLogger("winterpath_ml.inference")

LOCAL_TZ = ZoneInfo("America/Montreal")
LEVELS = ("low", "moderate", "elevated", "high")
SOURCE_IDS = ["mtl-311", "eccc-geomet"]  # ids from wp.source (Data agent registry)
EDGE_SAMPLE_M = 10.0


class ModelDisabledError(RuntimeError):
    """Raised when a caller asks for model probabilities but the registry has the model disabled."""


@dataclass(frozen=True)
class Evidence:
    state: str
    source_ids: list[str]
    observed_at: str | None
    retrieved_at: str | None = None
    confidence: float | None = None
    note: str | None = None


@dataclass(frozen=True)
class RiskEstimate:
    """Mirrors OpenAPI `RiskEstimate`."""

    level: str
    probability: float | None
    evidence: Evidence

    def to_dict(self) -> dict:
        return asdict(self)


def unknown(note: str) -> RiskEstimate:
    return RiskEstimate("unknown", None, Evidence("unknown", [], None, note=note))


@runtime_checkable
class RiskProvider(Protocol):
    def cell_risk(self, h3_cell: str, valid_from: datetime) -> RiskEstimate: ...

    def edge_risk(
        self, coords: Sequence[Sequence[float]], valid_from: datetime
    ) -> RiskEstimate: ...

    def status(self) -> dict: ...


def level_for(p: float, thresholds: dict[str, float]) -> str:
    if p >= thresholds["high"]:
        return "high"
    if p >= thresholds["elevated"]:
        return "elevated"
    if p >= thresholds["moderate"]:
        return "moderate"
    return "low"


def local_day(valid_from: datetime) -> pd.Timestamp:
    if valid_from.tzinfo is None:
        raise ValueError("valid_from must be timezone-aware")
    return pd.Timestamp(valid_from.astimezone(LOCAL_TZ).date())


def _haversine_m(a: Sequence[float], b: Sequence[float]) -> float:
    lon1, lat1, lon2, lat2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = (
        sin((lat2 - lat1) / 2) ** 2
        + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371008.8 * asin(sqrt(h))


def cells_along(
    coords: Sequence[Sequence[float]],
    res: int = config.H3_RES,
    step_m: float = EDGE_SAMPLE_M,
) -> list[str]:
    """H3 cells touched by a [lon, lat] polyline, sampled every `step_m` metres (order preserved)."""
    if len(coords) < 2:
        raise ValueError("edge needs at least 2 coordinates")
    seen: dict[str, None] = {}
    for a, b in pairwise(coords):
        n = max(1, int(_haversine_m(a, b) // step_m))
        for i in range(n + 1):
            t = i / n
            lon, lat = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            seen[h3.latlng_to_cell(lat, lon, res)] = None
    return list(seen)


def load_registry(path: Path = config.REGISTRY_PATH) -> dict:
    return json.loads(Path(path).read_text())


def _artifact_dir(registry: dict) -> Path:
    return config.ARTIFACT_DIR / registry["run_id"]


def artifact_path(registry: dict, entry: dict | str) -> Path:
    """Resolve a registry artifact entry under config.ARTIFACT_DIR (honours MODEL_ARTIFACT_DIR).

    Registry paths are recorded repo-relative (``models/artifacts/<run_id>/<file>``) for provenance;
    only the part after ``<run_id>`` is used, so artifacts can live anywhere.
    """
    rel = Path(entry["path"] if isinstance(entry, dict) else entry)
    run_id = registry["run_id"]
    parts = rel.parts
    tail = (
        Path(*parts[parts.index(run_id) + 1 :]) if run_id in parts else Path(rel.name)
    )
    return _artifact_dir(registry) / tail


def scores_dir(registry: dict, layer: str) -> Path:
    return _artifact_dir(registry) / "scores" / registry["layers"][layer]["id"]


@dataclass
class _ScoreTableProvider:
    """Shared logic: look up (cell, local day) in score tables."""

    registry: dict
    layer: str
    scores: pd.DataFrame = field(
        repr=False
    )  # columns: h3, day, p (calibrated), scored_at, data_through
    coverage: frozenset[str] = field(repr=False)

    def __post_init__(self) -> None:
        self.thresholds = self.registry["levels"]["thresholds"]
        s = self.scores.copy()
        s["day"] = pd.to_datetime(s["day"]).dt.normalize()
        self._lookup = {
            (h, d): (p, (obs, at))
            for h, d, p, obs, at in zip(
                s["h3"], s["day"], s["p"], s["data_through"], s["scored_at"]
            )
        }
        self._days = frozenset(s["day"])

    # -- subclass hooks
    def _estimate(
        self, p: float, times: tuple[str, str]
    ) -> RiskEstimate:  # pragma: no cover - abstract
        raise NotImplementedError

    def _cell(self, h3_cell: str, day: pd.Timestamp) -> RiskEstimate | float:
        if day.month not in self.registry["season_months"]:
            return unknown("Outside the Nov–Apr season the layer is defined for.")
        if h3_cell not in self.coverage:
            return unknown("Cell outside model coverage (no 311 history).")
        if day not in self._days:
            return unknown("No score computed for this day (inputs not yet available).")
        hit = self._lookup.get((h3_cell, day))
        if hit is None or pd.isna(hit[0]):
            return unknown("No score for this cell and day.")
        return self._estimate(float(hit[0]), hit[1])

    def cell_risk(self, h3_cell: str, valid_from: datetime) -> RiskEstimate:
        return self._cell(h3_cell, local_day(valid_from))

    def edge_risk(
        self, coords: Sequence[Sequence[float]], valid_from: datetime
    ) -> RiskEstimate:
        """Max level over the cells the edge touches; any unknown cell -> whole edge unknown."""
        day = local_day(valid_from)
        ests = [self._cell(c, day) for c in cells_along(coords)]
        if any(e.level == "unknown" for e in ests):
            notes = sorted({e.evidence.note for e in ests if e.level == "unknown"})
            return unknown("Edge not fully covered: " + " ".join(notes))
        return max(ests, key=lambda e: (LEVELS.index(e.level), e.probability or 0.0))

    def status(self) -> dict:
        return model_status(self.registry)


class HeuristicRiskProvider(_ScoreTableProvider):
    def _estimate(self, p: float, times: tuple[str, str]) -> RiskEstimate:
        return RiskEstimate(
            level=level_for(p, self.thresholds),
            probability=None,
            evidence=Evidence(
                state="model_estimate",
                source_ids=SOURCE_IDS,
                observed_at=times[0],
                retrieved_at=times[1],
                note=(
                    "Heuristic, not a validated probability: historical winter 311 report frequency × recent "
                    "observed weather. Reflects reporting behaviour, not sidewalk condition."
                ),
            ),
        )


class ModelRiskProvider(_ScoreTableProvider):
    def __post_init__(self) -> None:
        if not self.registry["layers"]["model"]["enabled"]:
            raise ModelDisabledError(
                f"{self.registry['layers']['model']['id']} failed its evaluation gate; use the heuristic layer."
            )
        super().__post_init__()

    def _estimate(self, p: float, times: tuple[str, str]) -> RiskEstimate:
        return RiskEstimate(
            level=level_for(p, self.thresholds),
            probability=p,
            evidence=Evidence(
                state="model_estimate",
                source_ids=SOURCE_IDS,
                observed_at=times[0],
                retrieved_at=times[1],
                confidence=None,
                note="Calibrated P(>=1 winter 311 report in this ~0.1 km² cell today). Not a measure of ice or safety.",
            ),
        )


class NullRiskProvider:
    """Everything unknown (used when no artifacts are available)."""

    def cell_risk(self, h3_cell: str, valid_from: datetime) -> RiskEstimate:
        return unknown("No risk layer available.")

    def edge_risk(
        self, coords: Sequence[Sequence[float]], valid_from: datetime
    ) -> RiskEstimate:
        return unknown("No risk layer available.")

    def status(self) -> dict:
        return {
            "risk_layer": "none",
            "enabled": False,
            "model_id": None,
            "target": config.TARGET,
            "trained_at": None,
            "training_window": None,
            "evaluation": None,
            "limitations": [],
        }


def model_status(registry: dict) -> dict:
    """OpenAPI `ModelStatus` built only from measured numbers in the registry."""
    m = registry["layers"]["model"]
    ev = m.get("evaluation")
    lim = list(registry.get("limitations", []))
    if not m["enabled"]:
        lim.insert(
            0,
            "The ML model did not pass its pre-registered evaluation gate; the map shows a labelled heuristic and no probabilities.",
        )
    return {
        "risk_layer": registry["active_layer"],
        "enabled": bool(m["enabled"]),
        "model_id": m["id"],
        "target": registry["target"],
        "trained_at": registry["generated_at"],
        "training_window": registry["training_window"],
        "evaluation": None
        if ev is None
        else {
            k: ev[k]
            for k in (
                "split",
                "pr_auc",
                "brier",
                "precision_at_k",
                "recall_at_k",
                "baseline_pr_auc",
                "n_test",
            )
        },
        "limitations": lim,
    }


def _read_scores(d: Path) -> pd.DataFrame:
    files = sorted(d.glob("*.parquet")) if d.exists() else []
    if not files:
        log.warning(
            "risk_scores_missing: no score tables in %s; every edge will be unknown", d
        )
        return pd.DataFrame(
            {
                "h3": [],
                "day": pd.to_datetime([]),
                "p": [],
                "scored_at": [],
                "data_through": [],
            }
        )
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def _coverage(registry: dict) -> frozenset[str]:
    return frozenset(
        pd.read_parquet(artifact_path(registry, registry["coverage"]))["h3"]
    )


def load_provider(registry_path: Path = config.REGISTRY_PATH) -> RiskProvider:
    """Provider for the registry's active layer; NullRiskProvider if registry/artifacts are missing."""
    try:
        reg = load_registry(registry_path)
    except FileNotFoundError:
        log.warning(
            "risk_registry_missing: %s not found; using NullRiskProvider (all unknown)",
            registry_path,
        )
        return NullRiskProvider()
    try:
        cov = _coverage(reg)
    except FileNotFoundError:
        log.warning(
            "risk_artifacts_missing: %s not found (MODEL_ARTIFACT_DIR=%s); using NullRiskProvider (all unknown)",
            artifact_path(reg, reg["coverage"]),
            config.ARTIFACT_DIR,
        )
        return NullRiskProvider()
    layer = reg["active_layer"]
    cls = ModelRiskProvider if layer == "model" else HeuristicRiskProvider
    return cls(reg, layer, _read_scores(scores_dir(reg, layer)), cov)


def edge_risk_rows(
    edges: Iterable[tuple[str, Sequence[Sequence[float]]]],
    provider: RiskProvider,
    valid_from: datetime,
    model_id: str | None,
) -> list[dict]:
    """Rows shaped like `wp.edge_risk` (edge_id, valid_from, valid_to, level, probability, evidence_state, model_id)."""
    day = local_day(valid_from)
    start = datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ).astimezone(UTC)
    nxt = day + pd.Timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=LOCAL_TZ).astimezone(UTC)
    rows = []
    for edge_id, coords in edges:
        e = provider.edge_risk(coords, valid_from)
        rows.append(
            {
                "edge_id": edge_id,
                "valid_from": start,
                "valid_to": end,
                "level": e.level,
                "probability": e.probability,
                "evidence_state": e.evidence.state,
                "model_id": model_id if e.level != "unknown" else None,
            }
        )
    return rows


# --- Adapter for services/api + services/routing (edge-id protocol) ---------------------------------
# winterpath_routing.RiskProvider is `risk_layer` + `edge_risk(edge_ids, at) -> {edge_id: RiskEstimate}`.
# The API wraps whatever it loads in NormalisingRiskProvider, which accepts our dicts.
# Use with: RISK_PROVIDER=winterpath_ml.inference:api_provider

DEFAULT_EDGES_GEOJSON = (
    config.REPO_ROOT / "data" / "fixtures" / "pilot_mini" / "edges.geojson"
)


class EdgeIdRiskProvider:
    """Maps edge ids to geometry (from a GeoJSON FeatureCollection) and delegates to a cell provider."""

    def __init__(
        self, inner: RiskProvider, edge_coords: dict[str, Sequence[Sequence[float]]]
    ):
        self.inner = inner
        self.edge_coords = edge_coords
        st = inner.status()
        self.risk_layer = (
            st["risk_layer"]
            if st["risk_layer"] in ("model", "heuristic", "none")
            else "none"
        )

    @classmethod
    def from_geojson(cls, inner: RiskProvider, path: Path) -> EdgeIdRiskProvider:
        fc = json.loads(Path(path).read_text())
        coords = {}
        for f in fc["features"]:
            eid = f.get("id") or f["properties"].get("edge_id")
            if eid and f["geometry"]["type"] == "LineString":
                coords[str(eid)] = f["geometry"]["coordinates"]
        return cls(inner, coords)

    def edge_risk(self, edge_ids: Sequence[str], at: datetime) -> dict[str, dict]:
        out = {}
        for eid in edge_ids:
            coords = self.edge_coords.get(eid)
            est = (
                unknown("Edge geometry not available to the risk layer.")
                if coords is None
                else self.inner.edge_risk(coords, at)
            )
            out[eid] = est.to_dict()
        return out

    def model_status(self) -> dict:
        return self.inner.status()


def api_provider() -> EdgeIdRiskProvider:
    """Factory for the API's RISK_PROVIDER setting. Edge geometry from WP_EDGES_GEOJSON (default: pilot_mini)."""
    path = Path(os.environ.get("WP_EDGES_GEOJSON", DEFAULT_EDGES_GEOJSON))
    inner = load_provider()
    if not path.exists():
        return EdgeIdRiskProvider(inner, {})  # every edge -> unknown, never low
    return EdgeIdRiskProvider.from_geojson(inner, path)
