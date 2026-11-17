"""Search index builder: RQA filtering, OSM classification, deterministic sharded output.

The CSV rows below are synthetic test fixtures (RQA header, invented values).
"""

import csv
import hashlib
import json

import pytest

from winterpath_ingestion.search_index.build import ADDRESS_BUCKETS, build_index, dedupe_places
from winterpath_ingestion.search_index.osm_places import Place, classify
from winterpath_ingestion.search_index.rqa import read_rqa

HEADER = (
    "identifiant_unique_adresse,date_diffusion_version,date_creation,date_modification,date_fin,"
    "numero_municipal,numero_municipal_suffixe,numero_unite,type_unite,code_postal,seqodo,"
    "generique_odonyme,particule_odonyme,specifique_odonyme,point_cardinal_odonyme,"
    "odonyme_recompose_normal,odonyme_recompose_court,odonyme_recompose_long,odonyme_recompose_tri,"
    "odonyme_specifique_tri,discriminant_odonyme,odonyme_officiel_ctop,renvoi_seqodo,"
    "renvoi_specifique_odonyme,adresse_formatee,qualite_positionnement_geometrique,etat,"
    "code_utilisation,categorie,nombre_unite,numero_lot,matricule_unite_evaluation,nosqnocivq,"
    "caracteristique_adresse,code_region_administrative,nom_region_administrative,code_mrc,nom_mrc,"
    "code_municipalite,nom_municipalite,nom_municipalite_complet,code_arrondissement,"
    "nom_arrondissement,code_communaute_metropolitaine,nom_communaute_metropolitaine,"
    "identifiant_reseau_routier,cote_route,longitude,latitude"
).split(",")


def row(
    uid, num, seq, generic, part, spec, card, quality, region, muni_code, muni, lon, lat,
    *, suffix="", unit="", etat="Certifiée", date_fin="", postal="H3G1M8",
):  # fmt: skip
    normal = " ".join(x for x in (generic, part, spec, card) if x)
    d = dict.fromkeys(HEADER, "")
    d.update(
        identifiant_unique_adresse=uid,
        date_diffusion_version="20261101",
        date_fin=date_fin,
        numero_municipal=num,
        numero_municipal_suffixe=suffix,
        numero_unite=unit,
        code_postal=postal,
        seqodo=seq,
        generique_odonyme=generic,
        particule_odonyme=part,
        specifique_odonyme=spec,
        point_cardinal_odonyme=card,
        odonyme_recompose_normal=normal,
        qualite_positionnement_geometrique=quality,
        etat=etat,
        code_region_administrative=region,
        code_municipalite=muni_code,
        nom_municipalite=muni,
        longitude=str(lon),
        latitude=str(lat),
    )
    return [d[h] for h in HEADER]


MTL = ("06", "66023", "Montréal")
LAVAL = ("13", "65005", "Laval")
QUEBEC_CITY = ("03", "23027", "Québec")
DM = ("Boulevard", "De", "Maisonneuve", "Ouest")


@pytest.fixture
def rqa_csv(tmp_path):
    rows = [
        row("a1", "1455", "10", *DM, "Géocodée", *MTL, -73.579, 45.4973),
        # Two unit rows of the same civic: merged, best quality kept.
        row("a2", "1451", "10", *DM, "Incertaine", *MTL, -73.5791, 45.4972, unit="2"),
        row("a3", "1451", "10", *DM, "Bâtiment", *MTL, -73.57905, 45.49725, unit="1"),
        row("a4", "1451", "10", *DM, "Géocodée", *MTL, -73.5791, 45.4972, suffix="A"),
        # Removed / not certified / outside the target municipalities: dropped.
        row("a5", "1500", "10", *DM, "Bâtiment", *MTL, -73.58, 45.497, etat="Détruite"),
        row("a6", "1502", "10", *DM, "Bâtiment", *MTL, -73.58, 45.497, date_fin="20260101"),
        row("a7", "1504", "10", *DM, "Bâtiment", *MTL, -73.58, 45.497, etat="Non certifiée"),
        row("a8", "1", "99", "Rue", "", "Principale", "", "Bâtiment", *QUEBEC_CITY, -71.2, 46.8),
        row("a9", "1555", "20", "Boulevard", "", "Chomedey", "", "Bâtiment", *LAVAL, -73.75, 45.55),
        row("b1", "5664", "30", "Avenue", "", "1re", "", "Incertaine", *MTL, -73.5808, 45.5463),
    ]
    p = tmp_path / "rqa.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, quoting=csv.QUOTE_ALL)
        w.writerow(HEADER)
        w.writerows(rows)
    return p


PLACES = [
    Place(
        "r1",
        "university",
        "Université McGill",
        ["Université McGill", "McGill University"],
        -7357871,
        4550689,
    ),  # noqa: E501  # fmt: skip
    Place("n2", "station", "Gare Centrale", ["Gare Centrale"], -7356669, 4549993),
    Place("n3", "station", "Gare Centrale", ["Gare Centrale"], -7356700, 4550000),  # duplicate
    # Far from every address: dropped.
    Place("n4", "park", "Parc lointain", ["Parc lointain"], -7330000, 4583000),
]


def test_read_rqa_filters_and_merges(rqa_csv):
    streets, st = read_rqa(rqa_csv)
    assert st.rows_read == 10
    assert st.rows_in_area == 9  # Québec City row skipped
    assert st.skipped_state == 3
    assert st.version == "20261101"
    dm = streets[("66023", "10")]
    assert dm.display == "Boulevard De Maisonneuve Ouest"
    assert dm.tokens == ["maisonneuve"] and dm.generic == "boulevard" and dm.direction == "o"
    assert sorted(dm.addresses) == ["1451", "1451a", "1455"]
    civic, lon, lat, q, rid = dm.addresses["1451"]
    assert (civic, q, rid) == ("1451", 0, "a3")  # Bâtiment wins over Incertaine
    assert dm.addresses["1451a"][0] == "1451A"
    assert streets[("66023", "30")].tokens == ["1"]


def test_build_index_layout_hashes_and_determinism(rqa_csv, tmp_path):
    streets, _ = read_rqa(rqa_csv)
    out = tmp_path / "web" / "search"
    r1 = build_index(streets, PLACES, out, [{"id": "rqa"}])
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["format"] == "winterpath-search/1"
    assert manifest["base"] == f"v/{r1.build_id}/"
    assert manifest["address_buckets"] == ADDRESS_BUCKETS
    assert [m[1] for m in manifest["municipalities"]] == ["Laval", "Montréal"]
    # Every shard listed with its sha256, and nothing else on disk.
    vdir = out / "v" / r1.build_id
    on_disk = {p.relative_to(vdir).as_posix() for p in vdir.rglob("*.json")}
    assert on_disk == set(manifest["shards"])
    for rel, sha in manifest["shards"].items():
        assert hashlib.sha256((vdir / rel).read_bytes()).hexdigest() == sha
    # Token shards: street under its specific-name key, place under every name token's key.
    ma = json.loads((vdir / "s/ma.json").read_text())["e"]
    assert [e[2] for e in ma] == ["Boulevard De Maisonneuve Ouest"]
    assert {e[2] for e in json.loads((vdir / "s/mc.json").read_text())["e"]} == {
        "Université McGill",
        "McGill University",
    }
    ga = json.loads((vdir / "s/ga.json").read_text())["e"]
    assert len(ga) == 1  # duplicate station within 300 m removed
    assert "s/pa.json" not in manifest["shards"]  # the far-away park was dropped
    assert r1.counts["places_outside_area"] == 1
    # Postal codes never copied.
    blob = b"".join(p.read_bytes() for p in out.rglob("*.json"))
    assert b"H3G1M8" not in blob
    # Deterministic: rebuilding gives the same id and bytes; old versions are removed.
    r2 = build_index(streets, PLACES, out, [{"id": "rqa"}])
    assert r2.build_id == r1.build_id and r2.files == r1.files
    assert [p.name for p in (out / "v").iterdir()] == [r1.build_id]


def test_address_rows_are_delta_encoded_and_sorted(rqa_csv, tmp_path):
    streets, _ = read_rqa(rqa_csv)
    out = tmp_path / "search"
    res = build_index(streets, [], out, [])
    manifest = json.loads((out / "manifest.json").read_text())
    ma = json.loads((out / manifest["base"] / "s/ma.json").read_text())["e"][0]
    sid = ma[1]
    bucket = json.loads((out / manifest["base"] / f"a/{sid % ADDRESS_BUCKETS}.json").read_text())
    rows = bucket["s"][str(sid)]
    assert [r[0] for r in rows] == ["1451", "1451A", "1455"]
    lon = lat = 0
    pts = []
    for _c, dl, dt, q in rows:
        lon += dl
        lat += dt
        pts.append((lon, lat, q))
    assert pts[-1] == (-7357900, 4549730, 5)  # Géocodée = 5
    assert res.counts["addresses"] == 5


def test_refuses_output_dir_not_named_search(tmp_path):
    with pytest.raises(ValueError):
        build_index({}, [], tmp_path / "public", [])


def test_classify_osm_tags():
    assert classify({"amenity": "university"}) == "university"
    assert classify({"railway": "station"}) == "station"
    assert classify({"public_transport": "station", "amenity": "bus_station"}) == "station"
    assert classify({"leisure": "park"}) == "park"
    assert classify({"shop": "mall"}) == "mall"
    assert classify({"amenity": "restaurant"}) is None
    assert classify({"shop": "convenience"}) is None
    assert classify({"highway": "residential"}) is None


def test_dedupe_places_keeps_far_apart_namesakes():
    a = Place("n1", "park", "Parc X", ["Parc X"], -7357000, 4550000)
    b = Place("n2", "park", "Parc X", ["Parc X"], -7357100, 4550000)  # ~80 m
    c = Place("n3", "park", "Parc X", ["Parc X"], -7300000, 4550000)  # ~45 km
    kept = dedupe_places([a, b, c])
    assert [p.ref for p in kept] == ["n1", "n3"]
