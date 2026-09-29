"""Segments qui suivent l'axe de rue decale (MultiLineString)."""
import math
import sys
from pathlib import Path


sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    ROAD_END_SENTINEL, ROAD_START_SENTINEL, RoadLocation, build_segment_halves,
    geometry_for_column, is_multilinestring_type, looks_like_chord_segments,
    multiline_length, multiline_substring, offset_polyline, parse_wkt_lines,
    point_at_distance, polyline_substring, road_line_matches, segment_half_geometry,
    segment_key,
)

L = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]  # coude a 90 deg a gauche


def _segments_cross(p1, p2, q1, q2):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def _self_intersects(coords):
    segs = list(zip(coords, coords[1:]))
    return any(
        _segments_cross(*segs[i], *segs[j])
        for i in range(len(segs)) for j in range(i + 2, len(segs))
    )


# --- abscisse / sous-ligne ---------------------------------------------------

def test_point_a_distance_et_bornes():
    assert point_at_distance(L, 50.0) == (50.0, 0.0)
    assert point_at_distance(L, 150.0) == (100.0, 50.0)
    assert point_at_distance(L, -5.0) == (0.0, 0.0)
    assert point_at_distance(L, 999.0) == (100.0, 100.0)


def test_sous_ligne_a_cheval_sur_un_sommet():
    assert polyline_substring(L, 80.0, 130.0) == [(80.0, 0.0), (100.0, 0.0), (100.0, 30.0)]


def test_sous_ligne_degeneree():
    assert polyline_substring(L, 40.0, 40.0) == [(40.0, 0.0), (40.0, 0.0)]
    assert multiline_substring(L, 40.0, 40.0) == [[(40.0, 0.0), (40.0, 0.0)]]


def test_sous_ligne_a_cheval_sur_deux_parties():
    parts = [[(0.0, 0.0), (50.0, 0.0)], [(60.0, 0.0), (110.0, 0.0)]]
    assert multiline_length(parts) == 100.0
    out = multiline_substring(parts, 30.0, 70.0)
    assert out == [[(30.0, 0.0), (50.0, 0.0)], [(60.0, 0.0), (80.0, 0.0)]]


# --- decalage ----------------------------------------------------------------

def test_decalage_ligne_droite_gauche_droite_et_nul():
    line = [(0.0, 0.0), (10.0, 0.0)]
    assert offset_polyline(line, 3.0, "L") == [(0.0, 3.0), (10.0, 3.0)]
    assert offset_polyline(line, 3.0, "R") == [(0.0, -3.0), (10.0, -3.0)]
    assert offset_polyline(line, 0.0, "L") == line


def test_decalage_coude_90_interieur_et_exterieur():
    inner = offset_polyline(L, 5.0, "L")   # virage a gauche : cote gauche = interieur
    assert inner == [(0.0, 5.0), (95.0, 5.0), (95.0, 100.0)]
    outer = offset_polyline(L, 5.0, "R")   # onglet exterieur (rapport sqrt(2) <= 2)
    assert outer == [(0.0, -5.0), (105.0, -5.0), (105.0, 100.0)]


def test_decalage_courbe_parallele():
    arc = [(10 * math.cos(a), 10 * math.sin(a)) for a in [i * math.pi / 20 for i in range(11)]]
    out = offset_polyline(arc, 2.0, "R")   # arc parcouru dans le sens trigo : droite = exterieur
    for x, y in out[1:-1]:
        assert 11.9 < math.hypot(x, y) < 12.1
    assert not _self_intersects(out)


def test_angle_aigu_pas_de_boucle():
    hairpin = [(0.0, 0.0), (100.0, 0.0), (0.0, 10.0)]  # ~6 deg
    for side in ("L", "R"):
        out = offset_polyline(hairpin, 8.0, side)
        assert not _self_intersects(out)
    # Virage a gauche : droite = exterieur -> biseau (2 points au sommet)
    # plutot qu'un onglet a des centaines de metres.
    outer = offset_polyline(hairpin, 8.0, "R")
    assert len(outer) == 4 and all(abs(x) < 200 and abs(y) < 200 for x, y in outer)
    # Gauche = interieur d'une epingle plus etroite que le decalage : sommet omis.
    assert len(offset_polyline(hairpin, 8.0, "L")) == 2


def test_troncons_courts_interieur_sans_boucle():
    zigzag = [(0.0, 0.0), (10.0, 0.0), (11.0, 1.0), (11.0, 11.0)]
    out = offset_polyline(zigzag, 5.0, "L")
    assert not _self_intersects(out)


def test_decalage_ligne_degeneree_inchangee():
    assert offset_polyline([(1.0, 1.0), (1.0, 1.0)], 3.0, "L") == [(1.0, 1.0), (1.0, 1.0)]


# --- segments le long de l'axe ----------------------------------------------------

def _locs():
    return [
        RoadLocation("A", "rouge", "r", 20.0, 20.0, 0.0, side="L", highway="residential"),
        RoadLocation("B", "vert", "r", 140.0, 100.0, 40.0, side="L", highway="residential"),
    ]


def test_moities_suivent_l_axe_et_longueur_curviligne():
    halves = build_segment_halves(_locs(), {}, {"r": L})
    a = next(h for h in halves if h.half == "a" and h.point_b_intervention_id == "B")
    b = next(h for h in halves if h.half == "b")
    assert a.length_m == b.length_m == 120.0      # le long de l'axe, pas la corde (~89 m)
    assert a.is_long and b.is_long                # >= 100 m
    assert (a.end_x, a.end_y) == (80.0, 0.0)      # milieu CURVILIGNE (20 + 120/2)
    assert a.axis_parts == (((20.0, 0.0), (80.0, 0.0)),)
    assert b.axis_parts == (((80.0, 0.0), (100.0, 0.0), (100.0, 40.0)),)  # passe le coude
    # Decale a gauche de 3 m (residential), jointure interieure au coude.
    assert segment_half_geometry(a) == (((20.0, 3.0), (80.0, 3.0)),)
    assert segment_half_geometry(b) == (((80.0, 3.0), (97.0, 3.0), (97.0, 40.0)),)


def test_bouts_de_rue_le_long_de_l_axe_et_debut_dessine_a_rebours():
    halves = {h.point_b_intervention_id: h for h in build_segment_halves(_locs(), {}, {"r": L})
              if h.point_b_intervention_id.startswith("__")}
    start, end = halves[ROAD_START_SENTINEL], halves[ROAD_END_SENTINEL]
    from geocode_asbuilt_depth import ROAD_END_STUB_M
    # Petits segments depuis A (debut, axe de 20 m seulement) et B (fin).
    s_start = min(ROAD_END_STUB_M, 20.0)
    s_end = min(ROAD_END_STUB_M, 60.0)
    assert start.length_m == s_start and end.length_m == s_end
    assert not start.is_long and not end.is_long
    # Debut : du point A vers le debut de l'axe, decale a GAUCHE du sens de l'axe.
    assert segment_half_geometry(start) == (((20.0, 3.0), (20.0 - s_start, 3.0)),)
    assert segment_half_geometry(end) == (((97.0, 40.0), (97.0, 40.0 + s_end)),)


def test_bout_de_rue_axe_plus_court_que_15_m():
    halves = build_segment_halves(
        [RoadLocation("A", "vert", "r", 10.0, 10.0, 0.0), RoadLocation("B", "vert", "r", 95.0, 95.0, 0.0)],
        {}, {"r": [(0.0, 0.0), (100.0, 0.0)]})
    from geocode_asbuilt_depth import ROAD_END_STUB_M
    assert ROAD_END_STUB_M > 10.0
    ends = {h.point_b_intervention_id: h.length_m for h in halves if h.point_b_intervention_id.startswith("__")}
    assert ends == {ROAD_START_SENTINEL: 10.0, ROAD_END_SENTINEL: 5.0}  # arret aux extremites


def test_point_isole_deux_petits_segments_de_part_et_d_autre():
    from geocode_asbuilt_depth import ROAD_END_STUB_M
    line = [(0.0, 0.0), (1000.0, 0.0)]
    for side, dy in (("L", 3.0), ("R", -3.0)):
        (a, b) = sorted(
            build_segment_halves([RoadLocation("P", "rouge", "r", 500.0, 500.0, 0.0, side=side)],
                                 {}, {"r": line}),
            key=lambda h: h.point_b_intervention_id,
        )
        assert {a.point_b_intervention_id, b.point_b_intervention_id} == {ROAD_END_SENTINEL, ROAD_START_SENTINEL}
        assert a.length_m == b.length_m == ROAD_END_STUB_M
        assert not a.is_long and not b.is_long
        geoms = {h.point_b_intervention_id: segment_half_geometry(h) for h in (a, b)}
        assert geoms[ROAD_START_SENTINEL] == (((500.0, dy), (500.0 - ROAD_END_STUB_M, dy)),)
        assert geoms[ROAD_END_SENTINEL] == (((500.0, dy), (500.0 + ROAD_END_STUB_M, dy)),)


def test_axe_absent_repli_en_cordes():
    halves = build_segment_halves(_locs(), {}, {})
    pair = next(h for h in halves if h.point_b_intervention_id == "B")
    assert pair.axis_parts == () and round(pair.length_m, 3) == round(math.hypot(80, 40), 3)


def test_axe_fragmente_multipartie():
    parts = [[(0.0, 0.0), (50.0, 0.0)], [(60.0, 0.0), (160.0, 0.0)]]
    locs = [RoadLocation("A", "vert", "r", 10.0, 10.0, 0.0),
            RoadLocation("B", "vert", "r", 90.0, 100.0, 0.0)]
    halves = build_segment_halves(locs, {}, {"r": parts})
    a = next(h for h in halves if h.half == "a" and h.point_b_intervention_id == "B")
    b = next(h for h in halves if h.half == "b")
    assert a.axis_parts == (((10.0, 0.0), (50.0, 0.0)),)
    assert b.axis_parts == (((60.0, 0.0), (100.0, 0.0)),)  # milieu = 50 : bord de partie
    full = build_segment_halves(
        [RoadLocation("A", "vert", "r", 10.0, 10.0, 0.0),
         RoadLocation("C", "vert", "r", 150.0, 140.0, 0.0)], {}, {"r": parts})
    a = next(h for h in full if h.half == "a" and h.point_b_intervention_id == "C")
    geom = segment_half_geometry(a)          # 10 -> 80 : deux parties, chacune decalee
    assert len(geom) == 2 and all(y == -3.0 for part in geom for _x, y in part)
    keys = [segment_key(h) for h in full]
    assert len(keys) == len(set(keys))


# --- compatibilite colonne / lecture / WKT -----------------------------------------

def test_colonne_linestring_premiere_partie_seulement():
    parts = (((0, 0), (1, 0)), ((2, 0), (3, 0)))
    assert geometry_for_column(parts, True) == (parts, 0)
    assert geometry_for_column(parts, False) == (parts[:1], 1)
    assert geometry_for_column(parts[:1], False) == (parts[:1], 0)
    assert is_multilinestring_type("MULTILINESTRING") and not is_multilinestring_type("LINESTRING")
    assert not is_multilinestring_type(None)


def test_parse_wkt_et_garde_de_longueur():
    assert parse_wkt_lines("LINESTRING(0 0, 10 0)") == [[(0.0, 0.0), (10.0, 0.0)]]
    assert parse_wkt_lines("SRID=31370;MULTILINESTRING((0 0,1 0),(2 0,3 0))") == [
        [(0.0, 0.0), (1.0, 0.0)], [(2.0, 0.0), (3.0, 0.0)]]
    assert parse_wkt_lines("LINESTRING Z (0 0 5, 3 4 5)") == [[(0.0, 0.0), (3.0, 4.0)]]
    assert parse_wkt_lines("POINT(1 2)") is None and parse_wkt_lines(None) is None
    assert road_line_matches([[(0.0, 0.0), (10.0, 0.0)]], 10.4)
    assert not road_line_matches([[(0.0, 0.0), (10.0, 0.0)]], 12.0)
    assert not road_line_matches(None, 10.0)


def test_segments_existants_en_cordes_detectes():
    chords = {("a", "b", "a", "R"): {"coords": (((0, 0), (1, 0)),)}}
    assert looks_like_chord_segments(chords)
    chords[("b", "c", "a", "R")] = {"coords": (((0, 0), (1, 0), (1, 1)),)}
    assert not looks_like_chord_segments(chords)


# --- connecteurs ----------------------------------------------------------------
from geocode_asbuilt_depth import (  # noqa: E402
    build_connectors, merge_colocated, plan_connector_sync, segment_endpoints,
)


def test_connecteur_point_sur_l_axe_longueur_egale_au_decalage():
    locs = [RoadLocation("A", "vert", "r", 20.0, 20.0, 0.0, side="L", highway="residential"),
            RoadLocation("B", "rouge", "r", 60.0, 60.0, 0.0, side="L", highway="residential")]
    halves = build_segment_halves(locs, {}, {"r": [(0.0, 0.0), (100.0, 0.0)]})
    points = {"A": (20.0, 0.0, "vert"), "B": (60.0, 0.0, "rouge")}
    conns = {c.intervention_id: c for c in build_connectors(points, locs, halves)}
    assert conns["A"].length_m == 3.0 and (conns["A"].end_x, conns["A"].end_y) == (20.0, 3.0)
    assert conns["B"].depth_category == "rouge" and conns["B"].side == "L"


def test_connecteur_cote_droit_et_longueur():
    locs = [RoadLocation("A", "vert", "r", 20.0, 20.0, 0.0, side="R", highway="primary")]
    halves = build_segment_halves(locs, {}, {"r": [(0.0, 0.0), (100.0, 0.0)]})
    (conn,) = build_connectors({"A": (20.0, -15.0, "vert")}, locs, halves)
    assert (conn.end_x, conn.end_y) == (20.0, -6.0) and conn.length_m == 9.0


def test_connecteurs_des_points_fusionnes_vers_le_meme_noeud():
    locs = [RoadLocation("1", "vert", "r", 20.0, 20.0, 0.0, side="L"),
            RoadLocation("2", "rouge", "r", 20.1, 20.1, 0.0, side="L")]
    nodes, members = merge_colocated(locs)
    halves = build_segment_halves(nodes, {}, {"r": [(0.0, 0.0), (100.0, 0.0)]})
    points = {"1": (20.0, 10.0, "vert"), "2": (20.1, 10.0, "rouge")}
    conns = build_connectors(points, nodes, halves, members)
    assert [c.intervention_id for c in conns] == ["1", "2"]
    assert {(c.end_x, c.end_y) for c in conns} == {(20.0, 3.0)}
    assert [c.depth_category for c in conns] == ["vert", "rouge"]  # categorie propre


def test_point_gris_sans_connecteur_et_geometrie_2_sommets():
    locs = [RoadLocation("A", "vert", "r", 20.0, 20.0, 0.0, side="L")]
    halves = build_segment_halves(locs, {}, {"r": [(0.0, 0.0), (100.0, 0.0)]})
    assert build_connectors({"A": (20.0, 5.0, "manquante")}, locs, halves) == []
    assert build_connectors({}, locs, halves) == []
    assert segment_endpoints(halves)["A"] == (20.0, 3.0)


def test_plan_connecteurs_incremental():
    locs = [RoadLocation("A", "vert", "r", 20.0, 20.0, 0.0, side="L")]
    halves = build_segment_halves(locs, {}, {"r": [(0.0, 0.0), (100.0, 0.0)]})
    (conn,) = build_connectors({"A": (20.0, 5.0, "vert")}, locs, halves)
    state = {"depth_category": "vert", "side": "L", "road_key": "r", "length_m": 2.0,
             "coords": ((20.0, 5.0), (20.0, 3.0))}
    plan = plan_connector_sync([conn], {"A": state, "G": state, "Z": state},
                               scope_ids={"A"}, eligible_ids={"A", "Z"})
    assert plan.unchanged == 1 and plan.to_insert == plan.to_update == []
    assert plan.to_delete == ["G"]               # G devenu gris/supprime ; Z hors perimetre
    moved = dict(state, coords=((20.0, 5.0), (20.0, 4.0)))
    assert plan_connector_sync([conn], {"A": moved}).to_update == [conn]
    assert plan_connector_sync([conn], {}).to_insert == [conn]
