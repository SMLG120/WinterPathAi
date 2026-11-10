"""Generate the SYNTHETIC toy grid fixture (``toy_grid/``). Not real streets.

Run: ``uv run python tests/fixtures/synthetic/build_toy_grid.py`` from services/routing.

Layout (rows r0..r2 south→north, cols c0..c3 west→east, ~78 m spacing, inside PILOT_BBOX):

    r2  o----o----o----o      r2 row: step_free = true
        |    |    |    |
    r1  o----o----o----o      r1 row: step_free = null (unknown)
        |  / S    |    |      S = r1c1–r2c1 steps (step_free = false); c3 column step_free = true
    r0  o----o----o----o      r0 row: step_free = true
        ^ r0c0→r1c1 diagonal shortcut has foot_access = "no" (must never be used)

Plus a disconnected pair of nodes ~300 m east (a reported gap, never bridged).
"""

from __future__ import annotations

import json
from pathlib import Path

from winterpath_routing.geo import metric_length_m

LON0, LAT0 = -73.5780, 45.5030
DLON, DLAT = 0.0010, 0.0007
ROWS, COLS = 3, 4
OUT = Path(__file__).parent / "toy_grid"


def nid(r: int, c: int) -> str:
    return f"syn:r{r}c{c}"


def main() -> None:
    nodes = {
        nid(r, c): (round(LON0 + c * DLON, 7), round(LAT0 + r * DLAT, 7))
        for r in range(ROWS)
        for c in range(COLS)
    }
    nodes["syn:iso1"] = (round(LON0 + 7 * DLON, 7), round(LAT0, 7))
    nodes["syn:iso2"] = (round(LON0 + 8 * DLON, 7), round(LAT0, 7))

    undirected: list[tuple[str, str, dict]] = []
    row_names = {0: "Synthetic Street A", 1: "Synthetic Street B", 2: "Synthetic Street C"}
    for r in range(ROWS):
        for c in range(COLS - 1):
            sf = True if r in (0, 2) else None
            undirected.append(
                (
                    nid(r, c),
                    nid(r, c + 1),
                    {
                        "edge_kind": "sidewalk",
                        "step_free": sf,
                        "name": row_names[r],
                        "foot_access": "yes",
                        "lit": True,
                    },
                )
            )
    for r in range(ROWS - 1):
        for c in range(COLS):
            props = {
                "edge_kind": "footway",
                "step_free": True if c == 3 else None,
                "name": f"Synthetic Lane {c}",
                "foot_access": "yes",
                "lit": c != 2,
            }
            if (r, c) == (1, 1):
                props.update(edge_kind="steps", step_free=False, name="Synthetic Steps")
            if (r, c) == (0, 2):
                props.update(
                    edge_kind="crossing", crossing_type="marked", kerb="lowered", name=None
                )
            undirected.append((nid(r, c), nid(r + 1, c), props))
    undirected.append(
        (
            nid(0, 0),
            nid(1, 1),
            {
                "edge_kind": "footway",
                "foot_access": "no",
                "step_free": True,
                "name": "Private Shortcut",
            },
        )
    )
    undirected.append(
        (
            "syn:iso1",
            "syn:iso2",
            {
                "edge_kind": "footway",
                "foot_access": "yes",
                "step_free": None,
                "name": "Isolated Path",
            },
        )
    )

    feats = []
    for a, b, props in undirected:
        for u, v in ((a, b), (b, a)):
            coords = [list(nodes[u]), list(nodes[v])]
            eid = f"{u}>{v}:0"
            p = {
                "edge_id": eid,
                "from_node_id": u,
                "to_node_id": v,
                "length_m": round(metric_length_m(coords), 3),
                "connectivity_confidence": "high",
                "source_ids": ["synthetic"],
                "surface": "concrete",
                **props,
            }
            feats.append(
                {
                    "type": "Feature",
                    "id": eid,
                    "properties": p,
                    "geometry": {"type": "LineString", "coordinates": coords},
                }
            )

    node_feats = [
        {
            "type": "Feature",
            "id": k,
            "properties": {"node_id": k, "kind": "synthetic"},
            "geometry": {"type": "Point", "coordinates": list(v)},
        }
        for k, v in nodes.items()
    ]
    OUT.mkdir(exist_ok=True)
    (OUT / "edges.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, indent=1) + "\n"
    )
    (OUT / "nodes.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": node_feats}, indent=1) + "\n"
    )
    (OUT / "metadata.json").write_text(
        json.dumps(
            {
                "simulated": True,
                "description": (
                    "SYNTHETIC toy grid for routing tests. Not real streets or conditions."
                ),
                "osm_snapshot": None,
                "built_at": "2026-11-10T00:00:00Z",
                "source_freshness": {"synthetic": "2026-11-10T00:00:00Z"},
                "bbox": [LON0, LAT0, LON0 + 8 * DLON, LAT0 + 2 * DLAT],
            },
            indent=1,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
