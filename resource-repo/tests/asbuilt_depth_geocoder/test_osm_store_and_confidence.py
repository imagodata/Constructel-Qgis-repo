"""Alimentation de ref.osm_roads (lot JSON) et confiance du rattachement a l'axe."""
import json
import re
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    FAROIS_HIGHWAY_TYPES, NominatimHit, OsmWay, assess_attachment,
    build_overpass_ids_query, build_store_payload, locate_rows_on_osm,
    nominatim_precision, normalize_street_name, osm_oneway, parse_nominatim_result,
    parse_overpass_ways, postal_mismatch, reference_street_names, store_osm_ways_sql,
)


# --- A) lot pour fn_asbuilt_store_osm_ways ------------------------------------

NASTY = "Rue de l'Église \\ $osmw$ \"x\""
OVERPASS = {"elements": [
    {"type": "way", "id": 1, "tags": {"highway": "residential", "name": "Am Sidders",
                                      "name:de": "Am Sidders", "maxspeed": "30",
                                      "oneway": "-1", "lanes": "1"},
     "geometry": [{"lat": 50.40, "lon": 6.25}, {"lat": 50.41, "lon": 6.26}]},
    {"type": "way", "id": 2, "tags": {"highway": "service", "name": "Parking"},
     "geometry": [{"lat": 50.40, "lon": 6.25}, {"lat": 50.41, "lon": 6.26}]},
    {"type": "way", "id": 3, "tags": {"highway": "tertiary_link", "name:de": "Zur Mühle"},
     "geometry": [{"lat": 50.40, "lon": 6.25}, {"lat": 50.41, "lon": 6.26}]},
    {"type": "way", "id": 4, "tags": {"highway": "residential",
                                      "name": NASTY},
     "geometry": [{"lat": 50.40, "lon": 6.25}, {"lat": 50.41, "lon": 6.26}]},
]}


def _ways():
    return parse_overpass_ways(OVERPASS, keep_unnamed=True)


def test_tags_et_geometrie_wgs84_conserves():
    way = next(w for w in _ways() if w.way_id == 3)
    assert way.tags["name:de"] == "Zur Mühle" and way.coords_wgs84 == ((6.25, 50.40), (6.26, 50.41))


def test_filtre_des_types_farois_et_dedup():
    payload, ids = build_store_payload(_ways() + _ways(), already_sent={4})
    assert ids == [1, 3]                       # service exclu, 4 deja envoye, doublons retires
    assert all(p["highway"] in FAROIS_HIGHWAY_TYPES for p in payload)
    first = payload[0]
    assert first["name_de"] == "Am Sidders" and first["maxspeed"] == "30"
    assert first["oneway"] is True             # '-1' -> sens unique (booleen JSON)
    assert first["wkt"] == "LINESTRING(6.2500000 50.4000000, 6.2600000 50.4100000)"  # WGS84 lon lat
    assert payload[1]["name"] == "" and payload[1]["name_de"] == "Zur Mühle"


def test_oneway():
    for value, expected in (("yes", True), ("-1", True), ("1", True), ("no", False),
                            ("reversible", False), (None, False)):
        assert osm_oneway(value) is expected


def test_echappement_sql_apostrophes_antislash_et_balise():
    payload, _ = build_store_payload(_ways())
    sql = store_osm_ways_sql(payload)
    match = re.fullmatch(r"SELECT public\.fn_asbuilt_store_osm_ways\((\$[a-z0-9]+\$)(.*)\1::jsonb\)",
                         sql, re.S)
    assert match, sql
    tag, body = match.group(1), match.group(2)
    assert tag != "$osmw$"                     # balise presente dans les donnees -> changee
    decoded = json.loads(body)                 # le texte entre balises est du JSON valide
    assert decoded == payload
    assert next(p["name"] for p in decoded if p["osm_id"] == 4) == NASTY


def test_requete_par_identifiants():
    assert build_overpass_ids_query([30, 10, 30]) == "[out:json][timeout:25];way(id:10,30);out geom;"


# --- B) metadonnees Nominatim ---------------------------------------------------

HOUSE = {"lat": "50.41", "lon": "6.26", "class": "building", "type": "house",
         "addresstype": "building", "osm_type": "way", "osm_id": "123", "importance": 0.1,
         "address": {"house_number": "3", "road": "Am Sidders", "village": "Büllingen",
                     "postcode": "4760"}}
STREET = {"lat": "50.41", "lon": "6.26", "class": "highway", "type": "residential",
          "addresstype": "road", "osm_type": "way", "osm_id": "555",
          "address": {"road": "Malmedyer Straße", "village": "Büllingen", "postcode": "4760"}}
LOCALITY = {"lat": "50.41", "lon": "6.26", "class": "boundary", "type": "administrative",
            "addresstype": "village", "osm_type": "relation", "osm_id": "9",
            "address": {"village": "Büllingen", "postcode": "4760"}}


def test_parse_resultat_complet():
    hit = parse_nominatim_result(HOUSE, 50.41, 6.26)
    assert (hit.road, hit.city, hit.postcode) == ("Am Sidders", "Büllingen", "4760")
    assert (hit.osm_type, hit.osm_id, hit.osm_class, hit.precision) == ("way", 123, "building", "house")


def test_precision():
    assert nominatim_precision(HOUSE) == "house"
    assert nominatim_precision(STREET) == "street"
    assert nominatim_precision(LOCALITY) == "locality"
    assert nominatim_precision(None) == "locality"


def test_nom_canonique_d_abord_puis_adresse():
    hit = parse_nominatim_result(STREET, 50.41, 6.26)
    assert reference_street_names("Malmedyer Str.", hit) == ("Malmedyer Straße", "Malmedyer Str.")
    assert reference_street_names("Malmedyer Strasse", hit) == ("Malmedyer Straße",)  # identiques
    assert reference_street_names("Rue X", None) == ("Rue X",)
    assert reference_street_names("", None) == ()


def test_code_postal_different():
    hit = parse_nominatim_result(HOUSE, 50.41, 6.26)
    assert postal_mismatch("4761", hit) and not postal_mismatch("4760", hit)
    assert not postal_mismatch("", hit) and not postal_mismatch("4760", None)


def _way(way_id, coords, name, highway="residential"):
    return OsmWay(way_id=way_id, names=(normalize_street_name(name),) if name else (),
                  highway=highway, coords=list(coords))


def test_voie_designee_par_nominatim_prioritaire():
    main = _way(555, [(0.0, 0.0), (100.0, 0.0)], "Malmedyer Straße")
    other = _way(556, [(0.0, 6.0), (100.0, 6.0)], "Kirchweg")      # plus proche du point
    results, _r, _l = locate_rows_on_osm(
        [("p", ("Truc",), 50.0, 5.0)], [], [main, other], preferred_ways={"p": 555},
    )
    match, method = results["p"]
    assert method == "osm_id" and match["way_id"] == 555


def test_rattachement_locality_rejete():
    hit = parse_nominatim_result(LOCALITY, 50.41, 6.26)
    score, cause = assess_attachment({"method": "db", "distance": 3.0}, ("Rue X",), hit)
    assert cause and "localité" in cause and score < 50


def test_rattachement_par_nom_confiant():
    hit = parse_nominatim_result(HOUSE, 50.41, 6.26)
    score, cause = assess_attachment({"method": "name", "distance": 8.0,
                                      "way_names": ("am sidders",)}, ("Am Sidders",), hit)
    assert cause is None and score == 84.0


def test_coords_nom_different_et_meme_nom_proche_rejete():
    match = {"method": "coords", "distance": 12.0, "way_names": ("kirchweg",),
             "same_name_nearby": True, "highway": "residential"}
    _score, cause = assess_attachment(match, ("Am Sidders",), None)
    assert cause and "même nom" in cause
    match["same_name_nearby"] = False
    assert assess_attachment(match, ("Am Sidders",), None)[1] is None


def test_coords_trop_loin_rejete():
    assert assess_attachment({"method": "coords", "distance": 31.0}, (), None)[1]


def test_autoroute_pour_une_adresse_rejetee_sauf_meme_nom():
    hit = parse_nominatim_result(HOUSE, 50.41, 6.26)
    match = {"method": "coords", "distance": 10.0, "way_names": ("e42",), "highway": "motorway_link"}
    assert "implausible" in assess_attachment(match, ("Am Sidders",), hit)[1]
    match["way_names"] = ("am sidders",)
    assert assess_attachment(match, ("Am Sidders",), hit)[1] is None


def test_coords_match_note_la_voie_du_meme_nom_proche():
    sidders = _way(1, [(0.0, 175.0), (100.0, 175.0)], "Am Sidders")   # a 170 m : > rayon par nom
    kirch = _way(2, [(0.0, 0.0), (100.0, 0.0)], "Kirchweg")            # a 5 m
    results, _r, _l = locate_rows_on_osm([("p", ("Am Sidders",), 50.0, 5.0)], [], [sidders, kirch])
    match, method = results["p"]
    assert method == "coords" and match["same_name_nearby"] is True
    assert assess_attachment(match, ("Am Sidders",), None)[1]


def test_hit_par_defaut_sans_metadonnees():
    hit = NominatimHit(lat=50.0, lon=6.0)
    assert hit.precision == "" and assess_attachment({"method": "db", "distance": 5.0}, (), hit)[1] is None
