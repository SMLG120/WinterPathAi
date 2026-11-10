"""Tag-mapping unit tests. Inputs are SYNTHETIC tag dicts (plainly labelled), not real data."""

from winterpath_ingestion.osm.graph import (
    crossing_type,
    edge_kind,
    exclusion_reason,
    foot_access,
    incline_percent,
    kerb_value,
    step_free,
)


def test_exclusions():
    assert exclusion_reason({"highway": "motorway"})
    assert exclusion_reason({"highway": "trunk"})
    assert exclusion_reason({"highway": "footway", "foot": "no"})
    assert exclusion_reason({"highway": "residential", "access": "private"})
    assert exclusion_reason({"highway": "primary", "foot": "use_sidepath"})
    assert exclusion_reason({"highway": "pedestrian", "area": "yes"})
    # explicit foot permission overrides general access restriction
    assert exclusion_reason({"highway": "footway", "access": "private", "foot": "yes"}) is None
    assert exclusion_reason({"highway": "footway"}) is None


def test_foot_access():
    assert foot_access({}) == "unknown"
    assert foot_access({"foot": "designated"}) == "designated"
    assert foot_access({"access": "no"}) == "no"
    assert foot_access({"foot": "use_sidepath"}) == "no"
    assert foot_access({"foot": "weird"}) == "unknown"


def test_edge_kind():
    assert edge_kind({"highway": "footway", "footway": "sidewalk"}) == "sidewalk"
    assert edge_kind({"highway": "footway", "footway": "crossing"}) == "crossing"
    assert edge_kind({"highway": "pedestrian"}) == "pedestrian_street"
    assert edge_kind({"highway": "living_street"}) == "shared_street"
    assert edge_kind({"highway": "residential"}) == "other"


def test_crossing_type():
    assert (
        crossing_type({"highway": "crossing", "crossing": "traffic_signals"}) == "traffic_signals"
    )
    assert crossing_type({"highway": "crossing", "crossing": "zebra"}) == "marked"
    assert crossing_type({"highway": "crossing", "crossing:markings": "zebra"}) == "marked"
    assert crossing_type({"highway": "crossing", "crossing": "unmarked"}) == "unmarked"
    assert crossing_type({"highway": "crossing"}) == "unknown"
    assert crossing_type({"highway": "traffic_signals"}) is None


def test_kerb_and_step_free():
    assert kerb_value({"kerb": "lowered"}) == "lowered"
    assert kerb_value({"kerb": "rolled"}) == "unknown"
    assert kerb_value({}) is None
    assert step_free({"highway": "steps", "wheelchair": "yes"}, []) is False
    assert step_free({"highway": "footway"}, []) is None  # unknown is never True
    assert step_free({"highway": "footway", "wheelchair": "yes"}, ["raised"]) is False
    assert step_free({"highway": "footway", "wheelchair": "yes"}, ["lowered"]) is True


def test_incline():
    assert incline_percent({"incline": "5%"}) == 5.0
    assert incline_percent({"incline": "up"}) is None
