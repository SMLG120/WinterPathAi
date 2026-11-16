"""Named places from the Geofabrik Québec extract (OpenStreetMap, ODbL 1.0).

Selection (documented in docs/SEARCH.md): named nodes, closed ways and multipolygons whose tags
match `classify()`. Food, shops (except malls/department stores) and offices are left out on
purpose: they change often and would dominate the results.
A place's point is the node itself, or the centroid of the largest outer ring (a representative
point inside it when the centroid falls outside). It is a label point for search, never a
verified entrance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Greater Montréal search area (lon/lat). Places are later kept only if they lie within 1.5 km
# of an indexed RQA address (see build.assign_municipality), which bounds them to the target
# municipalities.
BBOX = (-74.02, 45.38, -73.30, 45.84)

_AMENITY = {
    "university": "university",
    "college": "university",
    "school": "school",
    "hospital": "hospital",
    "clinic": "health",
    "library": "library",
    "townhall": "government",
    "courthouse": "government",
    "community_centre": "community",
    "theatre": "venue",
    "cinema": "venue",
    "arts_centre": "venue",
    "conference_centre": "venue",
    "exhibition_centre": "venue",
    "events_venue": "venue",
    "place_of_worship": "worship",
    "police": "government",
    "fire_station": "government",
    "post_office": "government",
    "marketplace": "market",
    "bus_station": "station",
    "ferry_terminal": "station",
}
_TOURISM = {
    "museum": "museum",
    "gallery": "museum",
    "attraction": "attraction",
    "zoo": "attraction",
    "aquarium": "attraction",
    "theme_park": "attraction",
    "viewpoint": "attraction",
    "hotel": "hotel",
}
_LEISURE = {
    "park": "park",
    "garden": "park",
    "nature_reserve": "park",
    "stadium": "sport",
    "sports_centre": "sport",
    "ice_rink": "sport",
}
_PLACE = {
    "neighbourhood": "neighbourhood",
    "suburb": "neighbourhood",
    "quarter": "neighbourhood",
    "square": "park",
}


def classify(tags) -> str | None:
    """Place kind for an OSM tag set, or None when not indexed."""
    get = tags.get
    if get("railway") in ("station", "halt") or get("public_transport") == "station":
        return "station"
    if get("aeroway") in ("aerodrome", "terminal"):
        return "airport"
    for key, table in (("amenity", _AMENITY), ("tourism", _TOURISM), ("leisure", _LEISURE)):
        k = table.get(get(key) or "")
        if k:
            return k
    if get("shop") in ("mall", "department_store"):
        return "mall"
    k = _PLACE.get(get("place") or "")
    if k:
        return k
    return None


NAME_KEYS = ("name", "name:fr", "name:en", "official_name", "alt_name", "short_name")


@dataclass
class Place:
    ref: str  # n123 / w456 / r789
    kind: str
    name: str
    names: list[str] = field(default_factory=list)  # distinct names, primary first
    lon_e5: int = 0
    lat_e5: int = 0


def _names(tags) -> list[str]:
    out: list[str] = []
    for k in NAME_KEYS:
        v = tags.get(k)
        if not v:
            continue
        for part in v.split(";"):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


def _in_bbox(lon: float, lat: float) -> bool:
    w, s, e, n = BBOX
    return w <= lon <= e and s <= lat <= n


def _area_point(area) -> tuple[float, float] | None:
    import shapely

    best = None
    for ring in area.outer_rings():
        coords = [(n.lon, n.lat) for n in ring]
        if len(coords) < 4:
            continue
        poly = shapely.Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            continue
        if best is None or poly.area > best.area:
            best = poly
    if best is None:
        return None
    c = best.centroid
    if not best.contains(c):
        c = best.representative_point()
    return c.x, c.y


def read_places(pbf: Path) -> tuple[list[Place], dict]:
    import osmium
    from osmium.filter import KeyFilter

    fp = (
        osmium.FileProcessor(str(pbf))
        .with_locations("flex_mem")
        .with_areas(KeyFilter("name"))
        .with_filter(KeyFilter("name"))
    )
    places: list[Place] = []
    stats = {"nodes": 0, "areas": 0, "area_no_geometry": 0}
    for o in fp:
        if o.is_node():
            kind = classify(o.tags)
            if not kind or not o.location.valid():
                continue
            lon, lat = o.location.lon, o.location.lat
            ref = f"n{o.id}"
            stats["nodes"] += 1
        elif o.is_area():
            kind = classify(o.tags)
            if not kind:
                continue
            # Quick bbox reject before building geometry.
            try:
                pt = _area_point(o)
            except osmium.InvalidLocationError:
                pt = None
            if pt is None:
                stats["area_no_geometry"] += 1
                continue
            lon, lat = pt
            ref = f"{'w' if o.from_way() else 'r'}{o.orig_id()}"
            stats["areas"] += 1
        else:
            continue
        if not _in_bbox(lon, lat):
            continue
        names = _names(o.tags)
        if not names:
            continue
        places.append(Place(ref, kind, names[0], names, round(lon * 1e5), round(lat * 1e5)))
    places.sort(key=lambda p: p.ref)
    return places, stats
