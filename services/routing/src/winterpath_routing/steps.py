"""List-based accessible directions (EN/FR) from a sequence of traversed edge pieces."""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass, replace

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


# ---------------------------------------------------------------------------------------------
# Steps v2 (ROUTING_STEPS_V2, off by default). Same Step shape (contract unchanged).
#
# * Consecutive pieces merge when they continue the same way: the same OSM ``name``, or — when
#   unnamed — the same footway class (sidewalk, footway, path, ...); consecutive crossing pieces
#   (a crossing split at a refuge island) and consecutive flights of steps merge too. A turn of
#   35° or more always starts a new step.
# * Turn angles use chord bearings over the last/first ``BEARING_WINDOW_M`` of each step, not
#   the last/first vertex pair, so a 1 m kink at a node does not read as a turn.
# * A walking step shorter than ``MIN_LEG_M`` is folded into a neighbouring step (its distance is
#   kept, never dropped). Crossings and steps are NEVER folded away or merged into walking: a
#   street crossing or a flight of stairs is safety- and accessibility-relevant at any length.
# * ``street_name`` is the OSM ``name`` when present, else a plain descriptor of the mapped way
#   type (EN/FR) from ``edge_kind``, which comes from OSM tags (footway=sidewalk, crossing,
#   ...). Crossings always get the descriptor (see street_label).
#   "crossing"/"traversée" is used rather than "crosswalk": an unmarked crossing is not a
#   crosswalk. Descriptors state the mapped way type only — never surface condition, clearing or
#   accessibility.
# ---------------------------------------------------------------------------------------------
MIN_LEG_M = 5.0
BEARING_WINDOW_M = 10.0

#: edge_kind -> (EN, FR, FR with article for "sur ...")
DESCRIPTORS: dict[str, tuple[str, str, str]] = {
    "sidewalk": ("sidewalk", "trottoir", "le trottoir"),
    "crossing": ("crossing", "traversée", "la traversée"),
    "footway": ("footpath", "sentier piétonnier", "le sentier piétonnier"),
    "path": ("path", "sentier", "le sentier"),
    "steps": ("stairs", "escalier", "l'escalier"),
    "pedestrian_street": ("pedestrian street", "rue piétonne", "la rue piétonne"),
    "shared_street": ("shared street", "rue partagée", "la rue partagée"),
}


def street_label(edge: Edge, locale: str) -> str | None:
    """OSM name, else the EN/FR descriptor of the mapped way type, else None.

    Crossings always get the descriptor: OSM ``name`` on a crossing way is inconsistent (often
    the street walked along rather than the one crossed), so it is not presented as such."""
    if edge.name and edge.edge_kind != "crossing":
        return edge.name
    d = DESCRIPTORS.get(edge.edge_kind)
    if d is None:
        return None
    return d[1] if locale == "fr" else d[0]


@dataclass(slots=True)
class _Group:
    key: tuple
    #: the edge that defines the step (kind, name, crossing); folded short legs never replace it
    edge: Edge
    pieces: list[Piece]
    length_m: float
    coords: list[tuple[float, float]]

    @property
    def kind(self) -> str:
        return self.key[0]


def _group_key(edge: Edge) -> tuple:
    kind = _kind_class(edge)
    if kind != "walk":
        return (kind,)
    return ("walk", edge.name, None) if edge.name else ("walk", None, edge.edge_kind)


def _chord_start(coords: Sequence[tuple[float, float]]) -> float:
    """Bearing from the first vertex to the point BEARING_WINDOW_M along (or the last vertex)."""
    acc = 0.0
    for a, b in itertools.pairwise(coords):
        seg = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        if acc + seg >= BEARING_WINDOW_M and seg > 0:
            f = (BEARING_WINDOW_M - acc) / seg
            return bearing_deg(coords[0], (a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])))
        acc += seg
    return bearing_deg(coords[0], coords[-1]) if len(coords) >= 2 else 0.0


def _chord_end(coords: Sequence[tuple[float, float]]) -> float:
    rev = list(reversed(coords))
    return (_chord_start(rev) + 180.0) % 360.0


def _append_coords(dst: list[tuple[float, float]], line: LineString) -> None:
    for c in line.coords:
        xy = (c[0], c[1])
        if not dst or dst[-1] != xy:
            dst.append(xy)


def _merge_into(a: _Group, b: _Group) -> _Group:
    """b appended to a (a keeps its key)."""
    a.pieces.extend(b.pieces)
    a.length_m += b.length_m
    for c in b.coords:
        if not a.coords or a.coords[-1] != c:
            a.coords.append(c)
    return a


def _prepend_into(b: _Group, a: _Group) -> _Group:
    """a prepended to b (b keeps its key)."""
    coords = list(a.coords)
    for c in b.coords:
        if not coords or coords[-1] != c:
            coords.append(c)
    b.pieces[:0] = a.pieces
    b.length_m += a.length_m
    b.coords = coords
    return b


def _same_way(a: _Group, b: _Group) -> bool:
    if a.key != b.key:
        return False
    return abs(turn_angle_deg(_chord_end(a.coords), _chord_start(b.coords))) < TURN_THRESHOLD_DEG


def _crossing_type(g: _Group) -> str | None:
    """The crossing type when every piece agrees; otherwise None (generic text). Never the
    'strongest' of mixed types: part of the crossing could be unmarked."""
    types = {p.edge.crossing_type for p in g.pieces if p.edge.edge_kind == "crossing"}
    return types.pop() if len(types) == 1 else None


def _turn_text_v2(
    angle: float,
    label: str | None,
    named: bool,
    locale: str,
    first: bool,
    bearing: float,
    kind: str | None,
) -> str:
    if locale == "fr":
        if label is None:
            on = ""
        elif named:
            on = f" sur {label}"
        else:
            on = f" sur {DESCRIPTORS[kind][2]}" if kind in DESCRIPTORS else ""
        if first:
            return f"Partez en direction {_cardinal(bearing, locale)}{on}"
        if abs(angle) < TURN_THRESHOLD_DEG:
            return f"Continuez{on}"
        side = "droite" if angle > 0 else "gauche"
        sharp = "franchement " if abs(angle) >= SHARP_TURN_DEG else ""
        return f"Tournez {sharp}à {side}{on}"
    if label is None:
        on = onto = ""
    elif named:
        on, onto = f" on {label}", f" onto {label}"
    else:
        on, onto = f" on the {label}", f" onto the {label}"
    if first:
        return f"Head {_cardinal(bearing, locale)}{on}"
    if abs(angle) < TURN_THRESHOLD_DEG:
        return f"Continue{on}"
    side = "right" if angle > 0 else "left"
    sharp = "sharp " if abs(angle) >= SHARP_TURN_DEG else ""
    return f"Turn {sharp}{side}{onto}"


def _groups_v2(pieces: Sequence[Piece]) -> list[_Group]:
    groups: list[_Group] = []
    for p in pieces:
        coords: list[tuple[float, float]] = []
        _append_coords(coords, p.metric_line)
        g = _Group(_group_key(p.edge), p.edge, [p], p.length_m, coords)
        if groups and _same_way(groups[-1], g):
            _merge_into(groups[-1], g)
        else:
            groups.append(g)

    changed = True
    while changed:
        changed = False
        # fold short walking legs into a neighbour (previous one first), never drop them
        for i, g in enumerate(groups):
            if g.kind != "walk" or g.length_m >= MIN_LEG_M or len(groups) == 1:
                continue
            if i > 0:
                _merge_into(groups[i - 1], g)
            else:
                _prepend_into(groups[i + 1], g)
            del groups[i]
            changed = True
            break
        # neighbours that now continue the same way become one step
        for i in range(len(groups) - 1):
            if _same_way(groups[i], groups[i + 1]):
                _merge_into(groups[i], groups.pop(i + 1))
                changed = True
                break
    return groups


def build_steps_v2(pieces: Sequence[Piece], locale: str = "en") -> list[Step]:
    pieces = [p for p in pieces if p.length_m > 0.05]
    arrived = Step("Vous êtes à destination" if locale == "fr" else "You have arrived", 0.0, None)
    if not pieces:
        return [arrived]
    steps: list[Step] = []
    prev_end: float | None = None
    for i, g in enumerate(_groups_v2(pieces)):
        e = g.edge
        b0 = _chord_start(g.coords)
        angle = turn_angle_deg(prev_end, b0) if prev_end is not None else 0.0
        label = street_label(e, locale)
        if g.kind == "crossing":
            ct = _crossing_type(g)
            text = _crossing_text(replace(e, crossing_type=ct), locale)
        elif g.kind == "steps":
            text = "Prenez l'escalier" if locale == "fr" else "Take the steps"
        else:
            text = _turn_text_v2(
                angle, label, bool(e.name), locale, i == 0, b0, None if e.name else e.edge_kind
            )
        steps.append(Step(text, g.length_m, label))
        prev_end = _chord_end(g.coords)
    steps.append(arrived)
    return steps
