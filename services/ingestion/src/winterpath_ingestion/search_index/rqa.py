"""Référentiel québécois des adresses (RQA, MRNF, CC BY 4.0) -> streets + civic addresses.

Filtering (documented in docs/SEARCH.md):
- municipality in TARGET_MUNICIPALITIES (all 16 municipalities of the Montréal agglomeration plus
  Laval, Longueuil, Brossard, Boucherville, Saint-Lambert, Terrebonne, Repentigny);
- `etat == "Certifiée"` and `date_fin` empty (the guide: only certified addresses are used for
  addressing; "Détruite" = removed);
- one entry per (street, civic number, civic suffix): apartment/unit rows are merged, keeping the
  best positioning quality (then the smallest `identifiant_unique_adresse`, for determinism);
- postal codes are NOT copied (the guide: "Code postal" is an official mark of Canada Post and the
  RQA includes information licensed from Canada Post).
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .normalize import direction, generic, tokens

# Montréal agglomeration = administrative region 06 (all 16 municipalities).
TARGET_REGIONS = frozenset({"06"})
TARGET_MUNICIPALITIES = {
    "65005": "Laval",
    "58227": "Longueuil",
    "58007": "Brossard",
    "58033": "Boucherville",
    "58012": "Saint-Lambert",
    "64008": "Terrebonne",
    "60013": "Repentigny",
}

# Positioning quality vocabulary (RQA user guide, `qualite_positionnement_geometrique`).
# Index order = code stored in the shards; lower = more precise.
QUALITIES = [
    "Bâtiment",  # 0 position on the building
    "Front lot",  # 1 position at the front of the lot
    "Accès propriété",  # 2 main access to the property
    "Centre lot",  # 3 centre of the lot
    "Site",  # 4 a place with no clear boundary (park, picnic area...)
    "Géocodée",  # 5 approximate, interpolated along the road segment's address range
    "Incertaine",  # 6 uncertain position
]
QUALITY_CODE = {q: i for i, q in enumerate(QUALITIES)}
UNKNOWN_QUALITY = len(QUALITIES)  # 7: value not in the documented vocabulary


@dataclass
class Street:
    muni_code: str
    muni_name: str
    seqodo: str
    display: str
    tokens: list[str]
    generic: str
    direction: str
    # civic_key -> (civic_display, lon_e5, lat_e5, quality, row_id)
    addresses: dict[str, tuple[str, int, int, int, str]] = field(default_factory=dict)


@dataclass
class RqaStats:
    rows_read: int = 0
    rows_in_area: int = 0
    rows_kept: int = 0
    skipped_state: int = 0
    skipped_bad_coord: int = 0
    unknown_quality: int = 0
    version: str = ""


def _open_rows(path: Path) -> Iterator[list[str]]:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
            with z.open(name) as raw:
                yield from csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
    else:
        with path.open(encoding="utf-8-sig", newline="") as f:
            yield from csv.reader(f)


def _e5(v: str) -> int:
    return round(float(v) * 1e5)


def read_rqa(path: Path) -> tuple[dict[tuple[str, str], Street], RqaStats]:
    rows = _open_rows(path)
    header = next(rows)
    ix = {name: i for i, name in enumerate(header)}
    c = {
        k: ix[k]
        for k in (
            "identifiant_unique_adresse",
            "date_diffusion_version",
            "date_fin",
            "numero_municipal",
            "numero_municipal_suffixe",
            "seqodo",
            "generique_odonyme",
            "specifique_odonyme",
            "point_cardinal_odonyme",
            "odonyme_recompose_normal",
            "qualite_positionnement_geometrique",
            "etat",
            "code_region_administrative",
            "code_municipalite",
            "nom_municipalite",
            "longitude",
            "latitude",
        )
    }
    streets: dict[tuple[str, str], Street] = {}
    st = RqaStats()
    versions: set[str] = set()
    for r in rows:
        st.rows_read += 1
        muni = r[c["code_municipalite"]]
        if (
            r[c["code_region_administrative"]] not in TARGET_REGIONS
            and muni not in TARGET_MUNICIPALITIES
        ):
            continue
        st.rows_in_area += 1
        versions.add(r[c["date_diffusion_version"]])
        if r[c["etat"]] != "Certifiée" or r[c["date_fin"]]:
            st.skipped_state += 1
            continue
        try:
            lon, lat = _e5(r[c["longitude"]]), _e5(r[c["latitude"]])
        except ValueError:
            st.skipped_bad_coord += 1
            continue
        if not (-7500000 < lon < -7200000 and 4500000 < lat < 4650000):
            st.skipped_bad_coord += 1
            continue
        q = QUALITY_CODE.get(r[c["qualite_positionnement_geometrique"]], UNKNOWN_QUALITY)
        if q == UNKNOWN_QUALITY:
            st.unknown_quality += 1
        seq = r[c["seqodo"]]
        key = (muni, seq)
        s = streets.get(key)
        if s is None:
            s = streets[key] = Street(
                muni_code=muni,
                muni_name=r[c["nom_municipalite"]],
                seqodo=seq,
                display=r[c["odonyme_recompose_normal"]].strip(),
                tokens=tokens(r[c["specifique_odonyme"]]),
                generic=generic(r[c["generique_odonyme"]]),
                direction=direction(r[c["point_cardinal_odonyme"]]),
            )
        num = r[c["numero_municipal"]].strip()
        suf = r[c["numero_municipal_suffixe"]].strip()
        if not num:
            continue
        civic = f"{num}{suf}" if not suf or suf[0].isalpha() else f"{num} {suf}"
        ckey = (num + suf).lower().replace(" ", "")
        rid = r[c["identifiant_unique_adresse"]]
        prev = s.addresses.get(ckey)
        if prev is None or (q, rid) < (prev[3], prev[4]):
            s.addresses[ckey] = (civic, lon, lat, q, rid)
    st.version = ",".join(sorted(v for v in versions if v))
    st.rows_kept = sum(len(s.addresses) for s in streets.values())
    return streets, st
