import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    LOCATE_RADIUS_MAX_M, OsmWay, OverpassError, build_overpass_query,
    index_ways_by_name, locate_on_ways, merge_component, normalize_street_name,
    overpass_fetch, parse_overpass_ways, project_on_polyline,
    side_from_probe_positions, side_of_point, side_probe_points,
)


# --- normalisation / requete / parsing --------------------------------------

def test_normalize_street_name_minuscules_sans_accents_eszett():
    assert normalize_street_name("Malmedyer Straße") == "malmedyer strasse"
    assert normalize_street_name("  Rue de l'Église ") == "rue de l'eglise"
    assert normalize_street_name(None) == ""


def test_build_overpass_query_filtree_par_noms_emprise_et_geometrie():
    query = build_overpass_query(["Rue X"], 50.1, 6.0, 50.2, 6.1)
    assert query.startswith("[out:json][timeout:25];")
    assert "(50.1000000,6.0000000,50.2000000,6.1000000)" in query
    for key in ("name", "name:fr", "name:nl", "name:de"):
        assert f'way["highway"]["{key}"~' in query
    assert ",i]" in query  # insensible a la casse
    assert query.endswith("out geom;")


FAKE_RESPONSE = {
    "version": 0.6,
    "elements": [
        {"type": "node", "id": 1, "lat": 50.0, "lon": 6.0},
        {"type": "way", "id": 11, "tags": {"highway": "residential", "name": "Malmedyer Straße"},
         "geometry": [{"lat": 50.40, "lon": 6.10}, {"lat": 50.41, "lon": 6.11}]},
        {"type": "way", "id": 12, "tags": {"highway": "tertiary", "name:de": "Hauptstraße"},
         "geometry": [{"lat": 50.40, "lon": 6.10}, None, {"lat": "x", "lon": 6.2},
                      {"lat": 50.42, "lon": 6.12}]},
        {"type": "way", "id": 13, "tags": {"highway": "service"},
         "geometry": [{"lat": 50.40, "lon": 6.10}, {"lat": 50.41, "lon": 6.11}]},
        {"type": "way", "id": 14, "tags": {"highway": "primary", "name": "Kurz"},
         "geometry": [{"lat": 50.40, "lon": 6.10}]},
        {"type": "way", "id": 15, "tags": {"highway": "primary", "name": "Rue X",
                                          "name:fr": "Rue X", "name:nl": "X-straat"},
         "geometry": [{"lat": 50.0, "lon": 4.0}, {"lat": 50.1, "lon": 4.1}]},
    ],
}


def test_parse_overpass_ways_reponse_factice():
    ways = {w.way_id: w for w in parse_overpass_ways(FAKE_RESPONSE)}
    assert set(ways) == {11, 12, 15}  # noeud, voie sans nom, voie a 1 sommet ignores
    assert ways[11].names == ("malmedyer strasse",)
    assert ways[11].highway == "residential"
    assert ways[11].coords == [(6.10, 50.40), (6.11, 50.41)]  # (lon, lat)
    assert ways[12].names == ("hauptstrasse",)
    assert ways[12].coords == [(6.10, 50.40), (6.12, 50.42)]  # sommets invalides ignores
    assert ways[15].names == ("rue x", "x-straat")  # doublon name/name:fr fusionne


def test_parse_overpass_ways_entree_malformee_ne_leve_pas():
    assert parse_overpass_ways(None) == []
    assert parse_overpass_ways({"elements": None}) == []
    assert parse_overpass_ways({"elements": [42, {"type": "way"}]}) == []


# --- overpass_fetch (reseau simule) -----------------------------------------

class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(behaviours):
    calls = []

    def urlopen(request, timeout):
        calls.append((request.full_url, request.get_header("User-agent"), timeout))
        behaviour = behaviours[len(calls) - 1]
        if isinstance(behaviour, Exception):
            raise behaviour
        return _FakeResponse(json.dumps(behaviour).encode("utf-8"))

    return urlopen, calls


def test_overpass_fetch_bascule_sur_les_miroirs_suivants():
    urlopen, calls = _fake_urlopen([
        urllib.error.URLError("timeout"),
        {"elements": [], "remark": "runtime error: Query timed out"},
        FAKE_RESPONSE,
    ])
    data = overpass_fetch("q", "UA/1.0", mirrors=("https://m1/i", "https://m2/i", "https://m3/i"),
                          urlopen=urlopen, check_status=False, fallback_attempts=1)
    assert data is not None and len(data["elements"]) == len(FAKE_RESPONSE["elements"])
    assert [c[0] for c in calls] == ["https://m1/i", "https://m2/i", "https://m3/i"]
    assert all(c[1] == "UA/1.0" for c in calls)


def test_overpass_fetch_tous_les_miroirs_en_echec_leve_overpass_error():
    urlopen, _ = _fake_urlopen([OSError("reset"), {"pas": "d'elements"}])
    with pytest.raises(OverpassError) as info:
        overpass_fetch("q", "UA", mirrors=("https://m1/i", "https://m2/i"), urlopen=urlopen,
                       check_status=False)
    assert "m1" in str(info.value) and "m2" in str(info.value)


# --- geometrie / cote -------------------------------------------------------

def test_project_on_polyline_abscisse_curviligne_et_direction():
    dist, pos, qx, qy, dx, dy = project_on_polyline(15.0, 3.0, [(0, 0), (10, 0), (10, 10)])
    # Plus proche du 2e troncon (x=10) : distance 5 ; ou du 1er : distance hypot(5,3).
    assert (qx, qy) == (10.0, 3.0) and pos == 13.0 and dist == 5.0
    assert (dx, dy) == (0.0, 10.0)


def test_side_of_point_convention():
    assert side_of_point(1.0, 0.0, 0.0, 2.0) == "L"
    assert side_of_point(1.0, 0.0, 0.0, -2.0) == "R"
    assert side_of_point(1.0, 0.0, 0.0, 0.0) == "R"  # sur l'axe -> R


def test_sondes_de_cote_coherentes_avec_le_produit_vectoriel():
    # Axe +x ; point a gauche (0, 5), projete (0, 0).
    plus, minus = side_probe_points(0.0, 5.0, 0.0, 0.0, eps=1.0)
    assert plus == (-1.0, 0.0) and minus == (1.0, 0.0)
    # position_m = x le long de l'axe +x.
    assert side_from_probe_positions(plus[0], minus[0]) == "L"
    plus, minus = side_probe_points(0.0, -5.0, 0.0, 0.0, eps=1.0)
    assert side_from_probe_positions(plus[0], minus[0]) == "R"
    assert side_probe_points(0.0, 0.0, 0.0, 0.0) is None
    assert side_from_probe_positions(3.0, 3.0) is None
    assert side_from_probe_positions(None, 3.0) is None


# --- localisation Python -----------------------------------------------------

def _way(way_id, coords, name="Rue X", highway="residential"):
    return OsmWay(way_id=way_id, names=(normalize_street_name(name),),
                  highway=highway, coords=list(coords))


def test_merge_component_deterministe_quel_que_soit_le_sens_des_voies():
    a = merge_component([_way(20, [(100, 0), (200, 0)]), _way(10, [(0, 0), (100, 0)])])
    b = merge_component([_way(10, [(100, 0), (0, 0)]), _way(20, [(200, 0), (100, 0)])])
    assert a == b == [(0, 0), (100, 0), (200, 0)]


def test_locate_on_ways_rue_en_deux_troncons_meme_road_key_et_cote():
    index = index_ways_by_name([
        _way(20, [(200, 0), (100, 0)], highway="tertiary"),
        _way(10, [(0, 0), (100, 0.4)]),  # raccord a 0.4 m < tolerance 1 m
    ])
    cache = {}
    m1, r1 = locate_on_ways(150.0, 5.0, "rue x", index, cache=cache)
    m2, r2 = locate_on_ways(50.0, -5.0, "RUE  X", index, cache=cache)
    assert r1 is None and r2 is None
    assert m1["road_key"] == m2["road_key"] == "overpass:rue x:10"
    assert m1["side"] == "L" and m2["side"] == "R"
    assert m1["position_m"] > m2["position_m"]
    assert m1["highway"] == "tertiary" and m2["highway"] == "residential"
    assert m1["extent"].start_x == 0 and m1["extent"].end_x == 200
    assert m1["extent"].length_m == pytest.approx(200.0, abs=0.01)


def test_locate_on_ways_homonymes_non_connectes_ambigu():
    index = index_ways_by_name([_way(1, [(0, 0), (100, 0)]), _way(2, [(0, 30), (100, 30)])])
    match, reason = locate_on_ways(50.0, 15.0, "Rue X", index)
    assert match is None and reason == "ambiguous"


def test_locate_on_ways_homonyme_lointain_n_est_pas_ambigu():
    index = index_ways_by_name([_way(1, [(0, 0), (100, 0)]), _way(2, [(0, 500), (100, 500)])])
    match, reason = locate_on_ways(50.0, 5.0, "Rue X", index)
    assert reason is None and match["road_key"] == "overpass:rue x:1"


def test_locate_on_ways_hors_rayon_ou_autre_nom():
    index = index_ways_by_name([_way(1, [(0, 0), (100, 0)])])
    assert locate_on_ways(50.0, 151.0, "Rue X", index) == (None, "no_match")  # > 150 m
    assert locate_on_ways(50.0, 5.0, "Rue Y", index) == (None, "no_match")
    assert locate_on_ways(50.0, 5.0, "", index) == (None, "no_match")
    # Rayon borne a LOCATE_RADIUS_MAX_M.
    assert locate_on_ways(50.0, LOCATE_RADIUS_MAX_M + 1, "Rue X", index,
                          radius=10_000) == (None, "no_match")
