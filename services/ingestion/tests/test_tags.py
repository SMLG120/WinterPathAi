"""Tag-mapping unit tests. Inputs are SYNTHETIC tag dicts (plainly labelled), not real data."""

from winterpath_ingestion.osm.graph import (
    admitted_by_foot_override,
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


def test_foot_permission_overrides_access_cr_data_7():
    """Contract v1.6.0: explicit foot=yes|designated|permissive overrides access=private|no;
    foot=no|use_sidepath always excludes; any other foot value does not override."""
    for acc in ("private", "no"):
        for f in ("yes", "designated", "permissive"):
            for hw in ("footway", "service", "steps"):
                t = {"highway": hw, "access": acc, "foot": f}
                assert exclusion_reason(t) is None
                assert admitted_by_foot_override(t)
        for f in ("no", "use_sidepath", "private"):
            assert exclusion_reason({"highway": "footway", "access": acc, "foot": f})
        for f in ("customers", "destination", "unknown"):  # not an explicit permission
            assert exclusion_reason({"highway": "footway", "access": acc, "foot": f})
        assert exclusion_reason({"highway": "footway", "access": acc})
    assert exclusion_reason({"highway": "footway", "access": "yes", "foot": "no"})
    assert exclusion_reason({"highway": "footway", "access": "yes", "foot": "use_sidepath"})
    assert not admitted_by_foot_override({"highway": "footway", "foot": "yes"})


def test_service_cycleway_only_with_explicit_foot_permission():
    """Contract v1.5.0 path policy (user decision 2026-11-10)."""
    for hw in ("service", "cycleway"):
        assert exclusion_reason({"highway": hw})  # untagged → excluded, never assumed walkable
        assert exclusion_reason({"highway": hw, "foot": "no"})
        assert exclusion_reason({"highway": hw, "foot": "use_sidepath"})
        assert exclusion_reason({"highway": hw, "foot": "unknown"})
        for f in ("yes", "designated", "permissive"):
            assert exclusion_reason({"highway": hw, "foot": f}) is None
    assert exclusion_reason({"highway": "service", "foot": "yes", "area": "yes"})
    assert exclusion_reason({"highway": "corridor", "foot": "yes"})  # indoor stays excluded
    assert edge_kind({"highway": "cycleway", "foot": "designated"}) == "path"
    assert edge_kind({"highway": "service", "foot": "yes"}) == "other"


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
