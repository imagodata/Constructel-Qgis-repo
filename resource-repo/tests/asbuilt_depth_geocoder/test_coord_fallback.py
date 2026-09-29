"""Repli par coordonnees (voie carrossable la plus proche) + chaine complete."""
import json
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    OSM_COORD_FALLBACK_RADIUS_M, OsmWay, OverpassError, RoadLocation,
    build_overpass_coord_query, build_segment_halves, highway_allowed_for_coords,
    locate_on_single_way, locate_rows_on_osm, nearest_way, normalize_street_name,
    parse_overpass_ways, plan_coord_requests, run_overpass_requests, segment_key,
)


def _way(way_id, coords, name=None, highway="residential"):
    names = (normalize_street_name(name),) if name else ()
    return OsmWay(way_id=way_id, names=names, highway=highway, coords=list(coords))


MAIN = _way(10, [(0.0, 0.0), (100.0, 0.0)], "Malmedyer Straße")
MAIN2 = _way(11, [(100.0, 0.0), (200.0, 0.0)], "Malmedyer Straße")   # suite de la rue
CROSS = _way(20, [(150.0, -100.0), (150.0, 100.0)], "Kirchweg")
PATH = _way(30, [(0.0, 5.0), (100.0, 5.0)], "Sentier", highway="footway")
NONAME = _way(40, [(0.0, 300.0), (80.0, 300.0)], None, highway="service")


def test_types_de_voie_retenus():
    assert highway_allowed_for_coords("residential") and highway_allowed_for_coords("primary_link")
    for excluded in ("footway", "path", "cycleway", "steps", "track", "pedestrian", ""):
        assert not highway_allowed_for_coords(excluded)


def test_voie_la_plus_proche_hors_chemins():
    way, reason = nearest_way(50.0, 4.0, [MAIN, PATH])   # le sentier est plus proche
    assert reason is None and way is MAIN


def test_rayon_depasse():
    assert nearest_way(50.0, OSM_COORD_FALLBACK_RADIUS_M + 1, [MAIN]) == (None, "no_match")


def test_carrefour_ambigu():
    # A 2 m de la rue principale et 3 m du Kirchweg : autre nom a < 5 m de plus.
    assert nearest_way(147.0, 2.0, [MAIN, MAIN2, CROSS]) == (None, "ambiguous")
    # Loin du carrefour : pas d'ambiguite.
    way, reason = nearest_way(120.0, 2.0, [MAIN, MAIN2, CROSS])
    assert reason is None and way is MAIN2


def test_troncons_d_une_meme_rue_ne_sont_pas_ambigus():
    way, reason = nearest_way(100.0, 3.0, [MAIN, MAIN2])
    assert reason is None and way.names == MAIN.names


def test_voie_sans_nom_troncon_isole():
    match = locate_on_single_way(40.0, 305.0, NONAME)
    assert match["road_key"] == "overpass-noname:40"
    assert match["position_m"] == 40.0 and match["side"] == "L"
    assert match["extent"].length_m == 80.0


def test_meme_road_key_par_nom_et_par_coordonnees_et_appariement():
    ways = [MAIN, MAIN2, CROSS, NONAME]
    results, reasons, lines = locate_rows_on_osm(
        name_items=[("1", "Malmedyer Strasse", 30.0, 5.0)],        # par nom
        coord_items=[("2", 170.0, 6.0), ("3", 40.0, 305.0)],       # sans nom d'adresse
        ways=ways,
    )
    (m1, how1), (m2, how2), (m3, how3) = results["1"], results["2"], results["3"]
    assert (how1, how2, how3) == ("name", "coords", "coords")
    assert m1["road_key"] == m2["road_key"] == "overpass:malmedyer strasse:10"
    assert m3["road_key"] == "overpass-noname:40"
    assert set(lines) == {m1["road_key"], "overpass-noname:40"}
    locs = [RoadLocation(i, "vert", m["road_key"], m["position_m"], m["x"], m["y"], side=m["side"])
            for i, (m, _h) in results.items()]
    halves = build_segment_halves(locs, {}, lines)
    assert ("1", "2", "a", "L") in [segment_key(h) for h in halves]  # apparies
    assert reasons == {}


def test_nom_d_adresse_different_rattrape_par_les_coordonnees():
    results, reasons, _ = locate_rows_on_osm(
        name_items=[("1", "Malmedyer Str.", 30.0, 5.0)], coord_items=[], ways=[MAIN, MAIN2],
    )
    assert results["1"][1] == "coords"
    assert results["1"][0]["road_key"] == "overpass:malmedyer strasse:10"


def test_raisons_non_localises():
    results, reasons, _ = locate_rows_on_osm(
        name_items=[], coord_items=[("far", 50.0, 500.0), ("x", 147.0, 2.0)],
        ways=[MAIN, MAIN2, CROSS],
    )
    assert results == {} and reasons == {"far": "no_match", "x": "ambiguous"}


def test_requete_et_regroupement_par_coordonnees():
    query = build_overpass_coord_query(50.40, 6.24, 50.42, 6.28)
    assert '["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|' in query
    assert "(_link)?$" in query and "around" not in query
    assert "(50.4000000,6.2400000,50.4200000,6.2800000)" in query
    reqs = plan_coord_requests([("1", 280_010.0, 125_010.0), ("2", 280_500.0, 125_300.0),
                                ("3", 150_000.0, 170_000.0)])
    assert len(reqs) == 2 and reqs[0].names == ()
    near = next(r for r in reqs if "1" in r.ids)
    assert near.bbox == (279_900.0, 124_900.0, 280_600.0, 125_400.0)  # ± 50 m, grille 100 m


def test_parse_garde_les_voies_sans_nom_pour_le_repli():
    data = {"elements": [{"type": "way", "id": 5, "tags": {"highway": "service"},
                          "geometry": [{"lat": 50.0, "lon": 6.0}, {"lat": 50.1, "lon": 6.1}]}]}
    assert parse_overpass_ways(data) == []
    (way,) = parse_overpass_ways(data, keep_unnamed=True)
    assert way.names == () and way.highway == "service"


def test_echec_isole_d_une_requete_par_coordonnees():
    reqs = plan_coord_requests([("1", 280_010.0, 125_010.0), ("3", 150_000.0, 170_000.0)])

    def fetch(req):
        if "1" in req.ids:
            raise OverpassError("HTTP 504")
        return {"elements": []}, False

    outcomes = run_overpass_requests(reqs, fetch)
    assert sorted((o.request.ids, o.data is not None) for o in outcomes) == [
        (("1",), False), (("3",), True)]
    json.dumps([o.error for o in outcomes])  # erreurs serialisables (journal)


def test_rues_homonymes_de_deux_localites_deux_road_key():
    village_a = _way(100, [(0.0, 0.0), (100.0, 0.0)], "Hauptstraße")
    village_b = _way(200, [(5000.0, 0.0), (5100.0, 0.0)], "Hauptstraße")
    results, _reasons, _lines = locate_rows_on_osm(
        name_items=[("a", "Hauptstrasse", 50.0, 3.0), ("b", "Hauptstraße", 5050.0, 3.0)],
        coord_items=[], ways=[village_a, village_b],
    )
    assert results["a"][0]["road_key"] == "overpass:hauptstrasse:100"
    assert results["b"][0]["road_key"] == "overpass:hauptstrasse:200"
