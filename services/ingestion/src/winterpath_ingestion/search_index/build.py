"""Static, prefix-sharded place-search index for the web client (format `winterpath-search/1`).

Layout under OUT (served same-origin, e.g. apps/web/public/search):
  manifest.json              sources, licences, versions, vocabularies, sha256 of every shard
  v/<build_id>/s/<key>.json  token shards: streets and places whose name has a token starting
                             with <key> (first 2 characters of a canonical token)
  v/<build_id>/a/<n>.json    address buckets: civic numbers per street (street id % buckets)

Deterministic: same inputs -> byte-identical output and the same build_id (no wall-clock time in
any shipped file). The build timestamp only goes to the optional --report file.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .normalize import KEY_LEN, fold, shard_key, tokens
from .osm_places import Place
from .rqa import QUALITIES, Street

FORMAT = "winterpath-search/1"
ADDRESS_BUCKETS = 512
PLACE_MAX_DIST_M = 1500.0
PLACE_DEDUPE_M = 300.0

RQA_SOURCE = {
    "id": "rqa",
    "title": "Référentiel québécois des adresses (RQA)",
    "publisher": "Ministère des Ressources naturelles et des Forêts (MRNF), Gouvernement du Québec",
    "licence": "CC BY 4.0",
    "licence_url": "https://creativecommons.org/licenses/by/4.0/",
    "url": "https://www.donneesquebec.ca/recherche/dataset/referentiel-quebecois-des-adresses",
    "attribution": {
        "fr": (
            "Adresses : Référentiel québécois des adresses, MRNF, Gouvernement du Québec "
            "(CC BY 4.0). Données filtrées et réorganisées par WinterPath."
        ),
        "en": (
            "Addresses: Référentiel québécois des adresses, MRNF, Gouvernement du Québec "
            "(CC BY 4.0). Data filtered and reorganised by WinterPath."
        ),
    },
}
OSM_SOURCE = {
    "id": "osm",
    "title": "OpenStreetMap (Geofabrik Québec extract)",
    "publisher": "OpenStreetMap contributors",
    "licence": "ODbL 1.0",
    "licence_url": "https://opendatacommons.org/licenses/odbl/1-0/",
    "url": "https://www.openstreetmap.org/copyright",
    "attribution": {
        "fr": "Lieux : © les contributeurs d’OpenStreetMap (ODbL).",
        "en": "Places: © OpenStreetMap contributors (ODbL).",
    },
}


def _dumps(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _civic_sort(civic_key: str) -> tuple[int, str]:
    digits = ""
    for ch in civic_key:
        if ch.isdigit():
            digits += ch
        else:
            break
    return (int(digits) if digits else 0, civic_key)


def _dist_m(lon1: int, lat1: int, lon2: int, lat2: int) -> float:
    k = 1.11195  # metres per 1e-5 degree of latitude
    dx = (lon2 - lon1) * k * math.cos(math.radians(lat1 / 1e5))
    dy = (lat2 - lat1) * k
    return math.hypot(dx, dy)


class _Grid:
    """Nearest RQA address (municipality) lookup for place points; cells of 0.02 degree."""

    CELL = 2000  # in 1e-5 degree

    def __init__(self) -> None:
        self.cells: dict[tuple[int, int], list[tuple[int, int, int]]] = defaultdict(list)

    def add(self, lon: int, lat: int, muni: int) -> None:
        self.cells[(lon // self.CELL, lat // self.CELL)].append((lon, lat, muni))

    def nearest(self, lon: int, lat: int, max_m: float) -> int | None:
        cx, cy = lon // self.CELL, lat // self.CELL
        best, best_d = None, max_m
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for x, y, m in self.cells.get((cx + dx, cy + dy), ()):
                    d = _dist_m(lon, lat, x, y)
                    if d <= best_d:
                        best, best_d = m, d
        return best


def dedupe_places(places: list[Place]) -> list[Place]:
    """Same kind + same folded primary name within 300 m -> keep one (relation > way > node)."""
    prio = {"r": 0, "w": 1, "n": 2}
    groups: dict[tuple[str, str], list[Place]] = defaultdict(list)
    for p in places:
        groups[(p.kind, fold(p.name))].append(p)
    out: list[Place] = []
    for key in sorted(groups):
        kept: list[Place] = []
        for p in sorted(groups[key], key=lambda p: (prio[p.ref[0]], int(p.ref[1:]))):
            if all(_dist_m(p.lon_e5, p.lat_e5, k.lon_e5, k.lat_e5) > PLACE_DEDUPE_M for k in kept):
                kept.append(p)
        out.extend(kept)
    out.sort(key=lambda p: p.ref)
    return out


@dataclass
class BuildResult:
    build_id: str
    files: dict[str, str]  # relative path -> sha256
    raw_bytes: int
    gzip_bytes: int
    counts: dict
    per_municipality: dict


def build_index(
    streets: dict[tuple[str, str], Street],
    places: list[Place],
    out: Path,
    sources: list[dict],
) -> BuildResult:
    if out.name != "search":
        raise ValueError(f"refusing to write outside a directory named 'search': {out}")
    # Municipalities and street ids (sorted -> deterministic ids).
    munis = sorted({(s.muni_code, s.muni_name) for s in streets.values()})
    muni_ix = {code: i for i, (code, _) in enumerate(munis)}
    ordered = [streets[k] for k in sorted(streets) if streets[k].addresses]

    token_shards: dict[str, list] = defaultdict(list)
    buckets: dict[int, dict[str, list]] = defaultdict(dict)
    grid = _Grid()
    per_muni: dict[str, dict[str, int]] = defaultdict(
        lambda: {"streets": 0, "addresses": 0, "address_bytes": 0, "places": 0}
    )
    quality_counts = [0] * (len(QUALITIES) + 1)

    for sid, s in enumerate(ordered):
        mi = muni_ix[s.muni_code]
        rows = []
        plon = plat = 0
        for ck in sorted(s.addresses, key=_civic_sort):
            civic, lon, lat, q, _rid = s.addresses[ck]
            rows.append([civic, lon - plon, lat - plat, q])
            plon, plat = lon, lat
            quality_counts[q] += 1
        # About 8 samples per street are plenty for assigning places to a municipality.
        for _civic, lon, lat, _q, _rid in list(s.addresses.values())[
            :: max(1, len(s.addresses) // 8)
        ]:
            grid.add(lon, lat, mi)
        buckets[sid % ADDRESS_BUCKETS][str(sid)] = rows
        # Middle address (by civic order): a proximity tie-breaker for ranking, never a target.
        mid = s.addresses[sorted(s.addresses, key=_civic_sort)[len(s.addresses) // 2]]
        entry = [
            "s", sid, s.display, mi, " ".join(s.tokens), s.generic, s.direction, len(rows),
            mid[1], mid[2],
        ]  # fmt: skip
        for key in sorted({shard_key(t) for t in s.tokens}):
            token_shards[key].append(entry)
        m = per_muni[s.muni_name]
        m["streets"] += 1
        m["addresses"] += len(rows)
        m["address_bytes"] += len(_dumps(rows))

    kept_places = 0
    dropped_far = 0
    for pid, p in enumerate(dedupe_places(places)):
        mi = grid.nearest(p.lon_e5, p.lat_e5, PLACE_MAX_DIST_M)
        if mi is None:
            dropped_far += 1
            continue
        kept_places += 1
        per_muni[munis[mi][1]]["places"] += 1
        seen_variants: set[str] = set()
        for name in p.names:
            toks = tokens(name)
            variant = " ".join(toks)
            if not toks or variant in seen_variants:
                continue
            seen_variants.add(variant)
            entry = [
                "p",
                pid,
                name,
                mi,
                variant,
                p.kind,
                p.lon_e5,
                p.lat_e5,
                p.ref,
                "" if name == p.name else p.name,
            ]
            for key in sorted({shard_key(t) for t in toks}):
                token_shards[key].append(entry)

    # Serialise into a staging dir, hash, then swap in.
    files: dict[str, bytes] = {}
    for key in sorted(token_shards):
        files[f"s/{key}.json"] = _dumps({"v": 1, "e": token_shards[key]})
    for b in range(ADDRESS_BUCKETS):
        files[f"a/{b}.json"] = _dumps({"v": 1, "s": buckets.get(b, {})})
    hashes = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
    build_id = hashlib.sha256(
        "\n".join(f"{p} {h}" for p, h in sorted(hashes.items())).encode()
    ).hexdigest()[:16]

    counts = {
        "streets": len(ordered),
        "addresses": sum(len(s.addresses) for s in ordered),
        "places": kept_places,
        "places_outside_area": dropped_far,
        "token_shards": len(token_shards),
        "address_buckets": ADDRESS_BUCKETS,
        "addresses_by_quality": {q: quality_counts[i] for i, q in enumerate(QUALITIES)}
        | {"other": quality_counts[-1]},
    }
    manifest = {
        "format": FORMAT,
        "build_id": build_id,
        "base": f"v/{build_id}/",
        "key_len": KEY_LEN,
        "address_buckets": ADDRESS_BUCKETS,
        "municipalities": [[code, name] for code, name in munis],
        "qualities": QUALITIES,
        "sources": sources,
        "counts": counts,
        "shards": hashes,
    }

    out.mkdir(parents=True, exist_ok=True)
    stage = out / f".stage-{build_id}"
    if stage.exists():
        shutil.rmtree(stage)
    for path, data in files.items():
        dest = stage / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    vdir = out / "v"
    vdir.mkdir(exist_ok=True)
    final = vdir / build_id
    if final.exists():
        shutil.rmtree(final)
    stage.rename(final)
    tmp_manifest = out / "manifest.json.tmp"
    tmp_manifest.write_bytes(_dumps(manifest))
    tmp_manifest.replace(out / "manifest.json")
    for old in vdir.iterdir():
        if old.name != build_id:
            shutil.rmtree(old)

    raw = sum(len(d) for d in files.values()) + (out / "manifest.json").stat().st_size
    gz = sum(len(gzip.compress(d, 9, mtime=0)) for d in files.values())
    gz += len(gzip.compress((out / "manifest.json").read_bytes(), 9, mtime=0))
    return BuildResult(build_id, hashes, raw, gz, counts, dict(per_muni))
