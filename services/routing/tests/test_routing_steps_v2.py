"""ROUTING_STEPS_V2 (off by default): merged, named steps. All geometry here is SYNTHETIC."""

from __future__ import annotations

from shapely.geometry import LineString

from winterpath_routing import Edge
from winterpath_routing.steps import Piece, build_steps, build_steps_v2, street_label

X0, Y0 = 300_000.0, 5_040_000.0  # EPSG:32188 metres


def _piece(i, pts, kind="sidewalk", name=None, crossing_type=None) -> Piece:
    pts = [(X0 + x, Y0 + y) for x, y in pts]
    line = LineString(pts)
    e = Edge(
        f"t{i}",
        f"n{i}",
        f"n{i + 1}",
        ((-73.57, 45.5), (-73.569, 45.5)),
        line.length,
        kind,
        name=name,
        crossing_type=crossing_type,
    )
    return Piece(e, line, line.length)


def _chain(specs):
    """specs: (dx, dy, kind, name, crossing_type) legs walked one after another."""
    x = y = 0.0
    out = []
    for i, (dx, dy, kind, name, ct) in enumerate(specs):
        out.append(_piece(i, [(x, y), (x + dx, y + dy)], kind, name, ct))
        x, y = x + dx, y + dy
    return out


def _walk(steps):
    return [s for s in steps if s.instruction != "You have arrived"]


def test_same_street_merges_across_sidewalk_and_footway() -> None:
    p = _chain([(0, 40, "sidewalk", "Rue A", None), (0, 30, "footway", "Rue A", None)])
    assert len(_walk(build_steps_v2(p))) == 1


def test_unnamed_merges_by_footway_class_only() -> None:
    p = _chain([(0, 40, "sidewalk", None, None), (0, 30, "sidewalk", None, None)])
    assert len(_walk(build_steps_v2(p))) == 1
    p = _chain([(0, 40, "sidewalk", None, None), (0, 30, "footway", None, None)])
    assert len(_walk(build_steps_v2(p))) == 2


def test_short_walk_leg_folded_distance_kept() -> None:
    p = _chain(
        [
            (0, 40, "sidewalk", "Rue A", None),
            (3, 0, "footway", None, None),  # 3 m connector: folded
            (0, 40, "sidewalk", "Rue A", None),
        ]
    )
    v1, v2 = _walk(build_steps(p)), _walk(build_steps_v2(p))
    assert len(v1) == 3 and len(v2) == 1
    assert abs(v2[0].distance_m - 83.0) < 1e-6
    assert v2[0].street_name == "Rue A"


def test_crossings_and_steps_never_folded() -> None:
    p = _chain(
        [
            (0, 40, "sidewalk", "Rue A", None),
            (0, 1.5, "crossing", None, "marked"),  # 1.5 m crossing stays its own step
            (0, 2, "steps", None, None),
            (0, 40, "sidewalk", "Rue A", None),
        ]
    )
    texts = [s.instruction for s in _walk(build_steps_v2(p))]
    assert "Cross at the marked crosswalk" in texts and "Take the steps" in texts


def test_split_crossing_merges_and_mixed_types_are_generic() -> None:
    same = _chain([(0, 6, "crossing", None, "marked"), (0, 6, "crossing", None, "marked")])
    s = _walk(build_steps_v2(same))
    assert len(s) == 1 and s[0].instruction == "Cross at the marked crosswalk"
    mixed = _chain([(0, 6, "crossing", None, "marked"), (0, 6, "crossing", None, "unmarked")])
    s = _walk(build_steps_v2(mixed))
    assert len(s) == 1 and s[0].instruction == "Cross the street"  # never the strongest


def test_turns_still_split_and_small_kinks_do_not() -> None:
    turn = _chain([(0, 40, "sidewalk", "Rue A", None), (40, 0, "sidewalk", "Rue A", None)])
    s = _walk(build_steps_v2(turn))
    assert len(s) == 2 and s[1].instruction == "Turn right onto Rue A"
    # 1 m sideways kink at a node: v1 sees a 45° turn, v2's 10 m chord does not
    kink = _chain(
        [
            (0, 40, "sidewalk", None, None),
            (1, 1, "sidewalk", None, None),
            (0, 40, "sidewalk", None, None),
        ]
    )
    assert len(_walk(build_steps_v2(kink))) == 1


def test_street_label_descriptors() -> None:
    e = _piece(0, [(0, 0), (0, 10)], "sidewalk").edge
    assert (street_label(e, "en"), street_label(e, "fr")) == ("sidewalk", "trottoir")
    c = _piece(0, [(0, 0), (0, 10)], "crossing", name="Rue A").edge
    assert (street_label(c, "en"), street_label(c, "fr")) == ("crossing", "traversée")
    o = _piece(0, [(0, 0), (0, 10)], "other").edge
    assert street_label(o, "en") is None
    n = _piece(0, [(0, 0), (0, 10)], "footway", name="Sentier X").edge
    assert street_label(n, "fr") == "Sentier X"
    fr = _walk(build_steps_v2(_chain([(0, 40, "sidewalk", None, None)]), "fr"))
    assert fr[0].instruction == "Partez en direction du nord sur le trottoir"
    assert fr[0].street_name == "trottoir"
