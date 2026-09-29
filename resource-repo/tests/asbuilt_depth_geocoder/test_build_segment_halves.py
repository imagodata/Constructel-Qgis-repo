# resource-repo-work/tests/asbuilt_depth_geocoder/test_build_segment_halves.py
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    RoadLocation, RoadExtent, SegmentHalf,
    build_segment_halves, ROAD_START_SENTINEL, ROAD_END_SENTINEL,
    LONG_SEGMENT_THRESHOLD_M,
)


def _extent(length_m, start=(0.0, 0.0), end=None):
    end = end or (length_m, 0.0)
    return RoadExtent(length_m=length_m, start_x=start[0], start_y=start[1],
                       end_x=end[0], end_y=end[1])


def test_paire_adjacente_produit_deux_moities():
    locs = [
        RoadLocation("1", "rouge", "rue x", position_m=0.0, x=0.0, y=0.0),
        RoadLocation("2", "vert", "rue x", position_m=40.0, x=40.0, y=0.0),
    ]
    halves = build_segment_halves(locs, {"rue x": _extent(100.0)})
    pair_halves = [h for h in halves if h.point_b_intervention_id == "2"]
    assert len(pair_halves) == 2
    a = next(h for h in pair_halves if h.half == "a")
    b = next(h for h in pair_halves if h.half == "b")
    assert a.depth_category == "rouge" and a.start_x == 0.0 and a.end_x == 20.0
    assert b.depth_category == "vert" and b.start_x == 20.0 and b.end_x == 40.0
    assert a.length_m == 40.0 and b.length_m == 40.0  # longueur totale de la paire, pas de la moitie
    assert not a.is_long and not b.is_long


def test_pointille_si_longueur_superieure_ou_egale_100m():
    locs = [
        RoadLocation("1", "rouge", "rue x", position_m=0.0, x=0.0, y=0.0),
        RoadLocation("2", "vert", "rue x", position_m=100.0, x=100.0, y=0.0),
    ]
    halves = build_segment_halves(locs, {"rue x": _extent(200.0)})
    pair_halves = [h for h in halves if h.point_b_intervention_id == "2"]
    assert all(h.is_long for h in pair_halves)


def test_points_gris_deja_exclus_en_amont_ne_cassent_pas_la_chaine():
    # 'manquante' est filtre par l'appelant (cf. Task 7) avant meme d'arriver
    # ici : A et C, adjacents dans la liste fournie, forment un segment normal.
    locs = [
        RoadLocation("A", "rouge", "rue x", position_m=0.0, x=0.0, y=0.0),
        RoadLocation("C", "vert", "rue x", position_m=60.0, x=60.0, y=0.0),
    ]
    halves = build_segment_halves(locs, {"rue x": _extent(100.0)})
    assert {h.point_b_intervention_id for h in halves if h.point_a_intervention_id == "A"} == {"C", ROAD_START_SENTINEL}


def test_segment_longueur_zero_ne_plante_pas_et_nest_pas_pointille():
    locs = [
        RoadLocation("1", "rouge", "rue x", position_m=10.0, x=10.0, y=0.0),
        RoadLocation("2", "vert", "rue x", position_m=10.0, x=10.0, y=0.0),
    ]
    halves = build_segment_halves(locs, {"rue x": _extent(50.0)})
    pair_halves = [h for h in halves if h.point_b_intervention_id == "2"]
    assert len(pair_halves) == 2
    assert all(h.length_m == 0.0 and not h.is_long for h in pair_halves)


def test_point_isole_produit_deux_segments_de_bout_de_route():
    locs = [RoadLocation("1", "orange", "rue x", position_m=30.0, x=30.0, y=0.0)]
    halves = build_segment_halves(locs, {"rue x": _extent(80.0)})
    assert len(halves) == 2
    targets = {h.point_b_intervention_id for h in halves}
    assert targets == {ROAD_START_SENTINEL, ROAD_END_SENTINEL}
    assert all(h.half == "a" and h.depth_category == "orange" for h in halves)
    start_seg = next(h for h in halves if h.point_b_intervention_id == ROAD_START_SENTINEL)
    end_seg = next(h for h in halves if h.point_b_intervention_id == ROAD_END_SENTINEL)
    assert start_seg.length_m == 30.0
    assert end_seg.length_m == 50.0


def test_road_key_sans_extent_ignore_les_bouts_de_route_sans_planter():
    locs = [RoadLocation("1", "vert", "rue inconnue", position_m=5.0, x=5.0, y=0.0)]
    halves = build_segment_halves(locs, {})
    assert halves == []


def test_deux_groupes_de_road_key_independants():
    locs = [
        RoadLocation("1", "rouge", "rue a", position_m=0.0, x=0.0, y=0.0),
        RoadLocation("2", "vert", "rue a", position_m=10.0, x=10.0, y=0.0),
        RoadLocation("3", "orange", "rue b", position_m=0.0, x=0.0, y=100.0),
    ]
    extents = {"rue a": _extent(10.0), "rue b": _extent(5.0, start=(0.0, 100.0), end=(5.0, 100.0))}
    halves = build_segment_halves(locs, extents)
    # "2" apparait aussi comme point_a : c'est le dernier point de "rue a",
    # donc le point_a legitime du segment de bout de route (-> ROAD_END_SENTINEL).
    assert {h.point_a_intervention_id for h in halves} == {"1", "2", "3"}


# --- cotes de la route + decalage par type de voie --------------------------
from geocode_asbuilt_depth import (  # noqa: E402
    DEFAULT_HIGHWAY_OFFSET_M, HIGHWAY_OFFSET_M, offset_for_highway,
    segment_half_geometry,
)


def test_cotes_opposes_ne_s_apparient_pas():
    locs = [
        RoadLocation("1", "rouge", "rue x", position_m=0.0, x=0.0, y=0.0, side="L"),
        RoadLocation("2", "vert", "rue x", position_m=10.0, x=10.0, y=0.0, side="R"),
        RoadLocation("3", "orange", "rue x", position_m=20.0, x=20.0, y=0.0, side="L"),
    ]
    halves = build_segment_halves(locs, {"rue x": _extent(30.0)})
    pairs = {
        (h.point_a_intervention_id, h.point_b_intervention_id)
        for h in halves if not h.point_b_intervention_id.startswith("__")
    }
    assert pairs == {("1", "3")}  # 2 (cote R) n'est relie a aucun point cote L
    assert all(h.side == "L" for h in halves if h.point_a_intervention_id in ("1", "3"))


def test_bouts_de_rue_par_cote():
    locs = [
        RoadLocation("1", "rouge", "rue x", position_m=5.0, x=5.0, y=0.0, side="L"),
        RoadLocation("2", "vert", "rue x", position_m=10.0, x=10.0, y=0.0, side="R"),
        RoadLocation("3", "orange", "rue x", position_m=20.0, x=20.0, y=0.0, side="L"),
    ]
    halves = build_segment_halves(locs, {"rue x": _extent(30.0)})
    ends = {
        (h.point_a_intervention_id, h.point_b_intervention_id, h.side)
        for h in halves if h.point_b_intervention_id.startswith("__")
    }
    assert ends == {
        ("1", ROAD_START_SENTINEL, "L"), ("3", ROAD_END_SENTINEL, "L"),
        ("2", ROAD_START_SENTINEL, "R"), ("2", ROAD_END_SENTINEL, "R"),
    }
    # Les cles (a, b, half, side) sont uniques.
    keys = [(h.point_a_intervention_id, h.point_b_intervention_id, h.half, h.side)
            for h in halves]
    assert len(keys) == len(set(keys))


def test_decalage_selon_highway_du_point_porteur():
    locs = [
        RoadLocation("1", "rouge", "rue x", 0.0, 0.0, 0.0, side="L", highway="primary"),
        RoadLocation("2", "vert", "rue x", 40.0, 40.0, 0.0, side="L", highway="residential"),
    ]
    halves = build_segment_halves(locs, {})
    a = next(h for h in halves if h.half == "a")
    b = next(h for h in halves if h.half == "b")
    assert a.offset_m == HIGHWAY_OFFSET_M["primary"]
    assert b.offset_m == HIGHWAY_OFFSET_M["residential"]


def test_offset_for_highway_link_et_defaut():
    assert offset_for_highway("primary_link") == HIGHWAY_OFFSET_M["primary"]
    assert offset_for_highway("Motorway") == 8.0
    assert offset_for_highway("") == DEFAULT_HIGHWAY_OFFSET_M
    assert offset_for_highway(None) == DEFAULT_HIGHWAY_OFFSET_M
    assert offset_for_highway("footway") == DEFAULT_HIGHWAY_OFFSET_M


def _half(b, side, offset=3.0, start=(10.0, 0.0), end=(20.0, 0.0)):
    return SegmentHalf(
        point_a_intervention_id="1", point_b_intervention_id=b, half="a",
        depth_category="vert", is_long=False, length_m=10.0, road_key="rue x",
        start_x=start[0], start_y=start[1], end_x=end[0], end_y=end[1],
        side=side, offset_m=offset,
    )


def test_geometrie_decalee_a_gauche_et_a_droite_de_l_axe():
    # Axe oriente +x : gauche = +y, droite = -y.
    assert segment_half_geometry(_half("2", "L")) == (((10.0, 3.0), (20.0, 3.0)),)
    assert segment_half_geometry(_half("2", "R")) == (((10.0, -3.0), (20.0, -3.0)),)


def test_bout_de_rue_debut_decale_du_bon_cote_malgre_le_dessin_a_rebours():
    # Segment point(10,0) -> debut de route (0,0) : dessine vers -x, mais le
    # cote reste relatif au sens de l'axe (+x) : gauche = +y.
    half = _half(ROAD_START_SENTINEL, "L", start=(10.0, 0.0), end=(0.0, 0.0))
    assert segment_half_geometry(half) == (((10.0, 3.0), (0.0, 3.0)),)
    half = _half(ROAD_END_SENTINEL, "L", start=(10.0, 0.0), end=(30.0, 0.0))
    assert segment_half_geometry(half) == (((10.0, 3.0), (30.0, 3.0)),)


def test_longueur_nulle_ou_decalage_nul_reste_sur_l_axe():
    assert segment_half_geometry(_half("2", "L", start=(5.0, 5.0), end=(5.0, 5.0))) == (
        ((5.0, 5.0), (5.0, 5.0)),)
    assert segment_half_geometry(_half("2", "L", offset=0.0)) == (((10.0, 0.0), (20.0, 0.0)),)


def test_longueur_et_pointille_mesures_sur_l_axe_pas_sur_le_decalage():
    locs = [
        RoadLocation("1", "rouge", "rue x", 0.0, 0.0, 0.0, side="L", highway="motorway"),
        RoadLocation("2", "vert", "rue x", 99.0, 99.0, 0.0, side="L", highway="motorway"),
    ]
    halves = [h for h in build_segment_halves(locs, {}) if h.point_b_intervention_id == "2"]
    assert all(h.length_m == 99.0 and not h.is_long for h in halves)


# --- pas de doublon de cle / points gris ignores -----------------------------
from geocode_asbuilt_depth import count_zero_length_pairs, segment_key  # noqa: E402


def _keys(halves):
    return [segment_key(h) for h in halves]


def test_meme_intervention_localisee_deux_fois_pas_de_cle_en_double():
    locs = [
        RoadLocation("1", "rouge", "rue x", 0.0, 0.0, 0.0),
        RoadLocation("2", "vert", "rue x", 10.0, 10.0, 0.0),
        RoadLocation("1", "rouge", "rue x", 20.0, 20.0, 0.0),  # doublon
    ]
    keys = _keys(build_segment_halves(locs, {"rue x": _extent(30.0)}))
    assert len(keys) == len(set(keys))
    assert ("1", "2", "a", "R") in keys and ("2", "1", "a", "R") not in keys


def test_points_ex_aequo_de_position_cles_uniques_et_longueur_nulle_comptee():
    locs = [
        RoadLocation("1", "rouge", "rue x", 10.0, 10.0, 0.0),
        RoadLocation("2", "vert", "rue x", 10.0, 10.0, 0.0),
        RoadLocation("3", "vert", "rue x", 10.0, 10.0, 0.0),
    ]
    halves = build_segment_halves(locs, {"rue x": _extent(30.0)})
    keys = _keys(halves)
    assert len(keys) == len(set(keys))
    assert count_zero_length_pairs(halves) == 2  # (1,2) et (2,3)


def test_point_gris_entre_deux_colores_jamais_relie():
    locs = [
        RoadLocation("A", "rouge", "rue x", 0.0, 0.0, 0.0),
        RoadLocation("G", "manquante", "rue x", 10.0, 10.0, 0.0),
        RoadLocation("B", "vert", "rue x", 20.0, 20.0, 0.0),
    ]
    halves = build_segment_halves(locs, {"rue x": _extent(30.0)})
    assert all("G" not in (h.point_a_intervention_id, h.point_b_intervention_id)
               for h in halves)
    pair = [h for h in halves if (h.point_a_intervention_id, h.point_b_intervention_id) == ("A", "B")]
    assert {h.half for h in pair} == {"a", "b"}


def test_point_gris_en_tete_ou_queue_ne_cree_pas_de_bout_de_rue():
    locs = [
        RoadLocation("G1", "manquante", "rue x", 0.0, 0.0, 0.0),
        RoadLocation("A", "rouge", "rue x", 10.0, 10.0, 0.0),
        RoadLocation("G2", "", "rue x", 30.0, 30.0, 0.0),
    ]
    halves = build_segment_halves(locs, {"rue x": _extent(40.0)})
    ends = {(h.point_a_intervention_id, h.point_b_intervention_id) for h in halves}
    assert ends == {("A", ROAD_START_SENTINEL), ("A", ROAD_END_SENTINEL)}


def test_rue_avec_uniquement_des_points_gris_ne_produit_rien():
    locs = [
        RoadLocation("G1", "manquante", "rue x", 0.0, 0.0, 0.0),
        RoadLocation("G2", "manquante", "rue x", 10.0, 10.0, 0.0),
    ]
    assert build_segment_halves(locs, {"rue x": _extent(40.0)}) == []
