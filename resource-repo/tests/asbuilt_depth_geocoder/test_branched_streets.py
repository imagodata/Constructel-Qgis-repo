"""Rues ramifiees decoupees en chaines, voies carrossables seulement, garde d'axe."""
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    AXIS_GUARD_M, OsmWay, RoadLocation, build_segment_halves, index_ways_by_name,
    locate_on_ways, locate_rows_on_osm, merge_component, name_match_tier,
    normalize_street_name, offset_part_anomalies, offset_polyline, project_on_polyline,
    segment_geometry_anomalies, segment_half_geometry, segment_key,
    split_component_chains,
)

N = normalize_street_name("Hauptstraße")


def _w(way_id, coords, highway="residential", name="Hauptstraße"):
    return OsmWay(way_id, (normalize_street_name(name),) if name else (), highway, list(coords))


# Carrefour en Y (noeud (0,0)) : tronc vers l'ouest, deux branches ; plus un
# rond-point (boucle) au bout de la branche nord-est.
TRUNK = _w(10, [(-300.0, 0.0), (0.0, 0.0)])
NORTH = _w(20, [(0.0, 0.0), (200.0, 200.0)])
SOUTH = _w(30, [(0.0, 0.0), (300.0, -150.0)])
RING = _w(40, [(200.0, 200.0), (220.0, 220.0), (240.0, 200.0), (220.0, 180.0), (200.0, 200.0)])
Y = [TRUNK, NORTH, SOUTH, RING]


def test_chaines_sans_fourche_aucune_voie_perdue():
    chains = split_component_chains(Y)
    assert sorted(w for ids, _c in chains for w in ids) == [10, 20, 30, 40]
    assert [ids for ids, _c in chains] == [[10], [20], [30], [40]]
    for ids, coords in chains:                 # orientation deterministe
        if ids != [40]:
            assert tuple(coords[0]) <= tuple(coords[-1])


def test_rue_simple_une_seule_chaine_comme_avant():
    a = _w(1, [(0.0, 0.0), (100.0, 0.0)])
    b = _w(2, [(200.0, 0.0), (100.0, 0.0)])
    assert split_component_chains([b, a]) == [([1, 2], [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)])]
    assert merge_component([a, b]) == [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)]


def test_germe_jamais_abandonne():
    for way in Y:
        coords = merge_component(Y, seed_way_id=way.way_id)
        assert any(tuple(p) in {tuple(q) for q in coords} for p in way.coords)


def test_point_sur_une_branche_se_rattache_a_sa_chaine_pres_du_point():
    index = index_ways_by_name(Y)
    match, reason = locate_on_ways(250.0, -110.0, "Hauptstraße", index)   # pres de SOUTH
    assert reason is None and match["road_key"] == f"overpass:{N}:30"
    assert match["distance"] <= 15.0


def test_deux_points_meme_chaine_apparies_chaines_differentes_non():
    index = index_ways_by_name(Y)
    cache = {}
    pts = {"a": (-250.0, 8.0), "b": (-100.0, 8.0), "c": (100.0, 110.0)}
    locs = []
    for pid, (x, y) in pts.items():
        match, _ = locate_on_ways(x, y, "Hauptstraße", index, cache=cache)
        locs.append(RoadLocation(pid, "vert", match["road_key"], match["position_m"],
                                 match["x"], match["y"], side=match["side"]))
    halves = build_segment_halves(locs, {}, cache["lines"])
    pairs = {(h.point_a_intervention_id, h.point_b_intervention_id) for h in halves
             if not h.point_b_intervention_id.startswith("__")}
    assert pairs == {("a", "b")}                                 # c : autre chaine
    ab = next(h for h in halves if h.point_b_intervention_id == "b" and h.half == "a")
    assert ab.axis_parts and ab.length_m == 150.0                # relie le long de l'axe


def test_track_homonyme_a_0_m_ignore_au_profit_de_la_secondary_a_35_m():
    track = _w(302258099, [(-200.0, 0.0), (200.0, 0.0)], highway="track", name="An Sankersborn")
    road = _w(302260527, [(-300.0, 35.0), (300.0, 35.0)], highway="secondary", name="An Sankersborn")
    index = index_ways_by_name([track, road])
    cache = {}
    keys = set()
    for x in (-150.0, 0.0, 150.0):
        match, reason = locate_on_ways(x, 0.0, "An Sankersborn", index, cache=cache)
        assert reason is None and match["way_id"] == 302260527 and round(match["distance"]) == 35
        keys.add(match["road_key"])
    assert len(keys) == 1


def test_classes_de_voie_pour_le_nom():
    assert name_match_tier("secondary") == 1 and name_match_tier("primary_link") == 1
    assert name_match_tier("service") == 2 and name_match_tier("living_street") == 2
    assert name_match_tier("pedestrian") == 3
    for excluded in ("track", "path", "footway", "cycleway", "steps", None):
        assert name_match_tier(excluded) is None
    # Desserte seulement sans carrossable homonyme dans le rayon.
    service = _w(1, [(0.0, 5.0), (100.0, 5.0)], highway="service")
    street = _w(2, [(0.0, 60.0), (100.0, 60.0)])
    match, _ = locate_on_ways(50.0, 0.0, "Hauptstraße", index_ways_by_name([service, street]))
    assert match["way_id"] == 2
    match, _ = locate_on_ways(50.0, 0.0, "Hauptstraße", index_ways_by_name([service]))
    assert match["way_id"] == 1


def test_garde_d_axe_distance_germe_plus_10_m():
    results, reasons, _ = locate_rows_on_osm([("p", ("Hauptstraße",), 250.0, -110.0)], [], Y)
    match = results["p"][0]
    seed_dist = min(project_on_polyline(250.0, -110.0, w.coords)[0] for w in Y)
    assert match["distance"] <= seed_dist + AXIS_GUARD_M


# --- controle geometrique ------------------------------------------------------

def test_controle_detecte_crochet_et_retournement():
    axis = [(0.0, 0.0), (100.0, 0.0)]
    assert offset_part_anomalies(axis, offset_polyline(axis, 3.0, "L"), 3.0) == []
    hook = [(0.0, 3.0), (100.0, 3.0), (90.0, 3.0)]
    assert "retournement" in offset_part_anomalies(axis, hook, 3.0)
    loop = [(0.0, 3.0), (60.0, 3.0), (50.0, -5.0), (40.0, 8.0), (100.0, 3.0)]
    assert "auto-intersection" in offset_part_anomalies(axis, loop, 3.0)
    assert any("extrémité" in p for p in offset_part_anomalies(axis, [(0.0, 20.0), (100.0, 3.0)], 3.0))


def test_decalage_aberrant_remplace_par_l_axe():
    # Epingle serree : cote interieur degenere -> axe non decale plutot qu'un crochet.
    locs = [RoadLocation("A", "vert", "r", 10.0, 10.0, 0.0, side="L", highway="motorway"),
            RoadLocation("B", "vert", "r", 150.0, 50.0, 3.0, side="L", highway="motorway")]
    line = [(0.0, 0.0), (100.0, 0.0), (0.0, 6.0)]
    halves = build_segment_halves(locs, {}, {"r": line})
    for h in halves:
        geometry = segment_half_geometry(h)
        if segment_geometry_anomalies(h):
            parts = [list(p) for p in geometry]
            if h.point_b_intervention_id == "__ROAD_START__":
                parts = [list(reversed(p)) for p in reversed(parts)]
            assert parts == [[tuple(p) for p in part] for part in h.axis_parts]
        keys = [segment_key(x) for x in halves]
        assert len(keys) == len(set(keys))


def test_hameau_route_sans_nom_a_33_m_rayon_elargi_faible_confiance():
    from geocode_asbuilt_depth import COORD_FALLBACK_LONE_RADIUS_M, OSM_COORD_FALLBACK_RADIUS_M
    track = _w(1, [(-100.0, 19.0), (100.0, 19.0)], highway="track", name=None)
    road = _w(37659174, [(-100.0, -33.0), (100.0, -33.0)], highway="unclassified", name=None)
    far_name = _w(3, [(-100.0, 283.0), (100.0, 283.0)], highway="residential", name="Neidingen")
    results, reasons, lines = locate_rows_on_osm(
        [("p", ("Neidingen",), 0.0, 0.0)], [], [track, road, far_name]
    )
    match, method = results["p"]
    assert method == "coords" and match["road_key"] == "overpass-noname:37659174"
    assert OSM_COORD_FALLBACK_RADIUS_M < match["distance"] <= COORD_FALLBACK_LONE_RADIUS_M
    assert match["lone"] and "sans nom" in match["low_confidence"]
    from geocode_asbuilt_depth import assess_attachment
    assert assess_attachment(match, ("Neidingen",), None)[1] is None
    # Voie du nom de reference a <= 150 m : regle des 30 m conservee.
    near_name = _w(4, [(-100.0, 120.0), (100.0, 120.0)], highway="residential", name="Neidingen")
    results, _r, _l = locate_rows_on_osm([("p", ("Neidingen",), 0.0, 0.0)], [], [track, road, near_name])
    assert results["p"][0]["way_id"] == 4                          # par nom, a 120 m
