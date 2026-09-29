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
