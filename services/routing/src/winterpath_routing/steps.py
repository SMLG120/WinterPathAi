"""List-based accessible directions (EN/FR) from a sequence of traversed edge pieces."""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

from shapely.geometry import LineString

from .geo import bearing_deg, turn_angle_deg
from .models import Edge

TURN_THRESHOLD_DEG = 35.0
SHARP_TURN_DEG = 120.0

_CARDINALS_EN = [
    "north",
    "northeast",
    "east",
    "southeast",
    "south",
    "southwest",
    "west",
    "northwest",
]
_CARDINALS_FR = [
    "du nord",
    "du nord-est",
    "de l'est",
    "du sud-est",
    "du sud",
    "du sud-ouest",
    "de l'ouest",
    "du nord-ouest",
]


@dataclass(frozen=True, slots=True)
class Piece:
    """A traversed portion of an edge, in travel direction, with metric geometry."""

    edge: Edge
    metric_line: LineString
    length_m: float


@dataclass(frozen=True, slots=True)
class Step:
    instruction: str
    distance_m: float
    street_name: str | None

    def to_dict(self) -> dict:
        return {
            "instruction": self.instruction,
            "distance_m": round(self.distance_m, 1),
            "street_name": self.street_name,
        }


def _cardinal(bearing: float, locale: str) -> str:
    idx = int(((bearing + 22.5) % 360) // 45)
    return (_CARDINALS_FR if locale == "fr" else _CARDINALS_EN)[idx]


def _start_bearing(line: LineString) -> float:
    c = list(line.coords)
    return bearing_deg(c[0], c[1]) if len(c) >= 2 else 0.0


def _end_bearing(line: LineString) -> float:
    c = list(line.coords)
    return bearing_deg(c[-2], c[-1]) if len(c) >= 2 else 0.0


def _kind_class(edge: Edge) -> str:
    if edge.edge_kind in ("crossing", "steps"):
        return edge.edge_kind
    return "walk"


def _crossing_text(edge: Edge, locale: str) -> str:
    ct = edge.crossing_type
    if locale == "fr":
        if ct == "traffic_signals":
            return "Traversez au feu de circulation"
        if ct == "marked":
            return "Traversez au passage piéton marqué"
        return "Traversez la rue"
    if ct == "traffic_signals":
        return "Cross at the traffic signals"
    if ct == "marked":
        return "Cross at the marked crosswalk"
    return "Cross the street"


def _turn_text(angle: float, name: str | None, locale: str, first: bool, bearing: float) -> str:
    if locale == "fr":
        on = f" sur {name}" if name else ""
        if first:
            return f"Partez en direction {_cardinal(bearing, locale)}{on}"
        if abs(angle) < TURN_THRESHOLD_DEG:
            return f"Continuez{on}"
        side = "droite" if angle > 0 else "gauche"
        sharp = "franchement " if abs(angle) >= SHARP_TURN_DEG else ""
        return f"Tournez {sharp}à {side}{on}"
    on = f" on {name}" if name else ""
    if first:
        return f"Head {_cardinal(bearing, locale)}{on}"
    if abs(angle) < TURN_THRESHOLD_DEG:
        return f"Continue{on}"
    side = "right" if angle > 0 else "left"
    sharp = "sharp " if abs(angle) >= SHARP_TURN_DEG else ""
    onto = f" onto {name}" if name else ""
    return f"Turn {sharp}{side}{onto}"


def build_steps(pieces: Sequence[Piece], locale: str = "en") -> list[Step]:
    pieces = [p for p in pieces if p.length_m > 0.05]
    steps: list[Step] = []
    if not pieces:
        return [
            Step("Vous êtes à destination" if locale == "fr" else "You have arrived", 0.0, None)
        ]

    # Group consecutive pieces into maneuvers.
    groups: list[list[Piece]] = [[pieces[0]]]
    for prev, cur in itertools.pairwise(pieces):
        angle = turn_angle_deg(_end_bearing(prev.metric_line), _start_bearing(cur.metric_line))
        same = (
            cur.edge.name == prev.edge.name
            and _kind_class(cur.edge) == _kind_class(prev.edge) == "walk"
            and abs(angle) < TURN_THRESHOLD_DEG
        )
        if same:
            groups[-1].append(cur)
        else:
            groups.append([cur])

    prev_end: float | None = None
    for i, grp in enumerate(groups):
        e = grp[0].edge
        dist = sum(p.length_m for p in grp)
        b0 = _start_bearing(grp[0].metric_line)
        angle = turn_angle_deg(prev_end, b0) if prev_end is not None else 0.0
        kind = _kind_class(e)
        if kind == "crossing":
            text = _crossing_text(e, locale)
        elif kind == "steps":
            text = "Prenez l'escalier" if locale == "fr" else "Take the steps"
        else:
            text = _turn_text(angle, e.name, locale, first=(i == 0), bearing=b0)
        steps.append(Step(text, dist, e.name))
        prev_end = _end_bearing(grp[-1].metric_line)

    steps.append(
        Step("Vous êtes à destination" if locale == "fr" else "You have arrived", 0.0, None)
    )
    return steps
