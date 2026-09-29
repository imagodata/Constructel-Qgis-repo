"""Recalcul incremental des segments : points sales -> routes a recalculer."""
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    ROAD_END_SENTINEL, ROAD_START_SENTINEL, RoadExtent, RoadLocation,
    build_segment_halves, expand_dirty_roads, index_existing_segments,
    initial_dirty_ids, plan_segment_sync, point_changed, segment_half_geometry,
    segment_key,
)

EXTENTS = {
    "rue x": RoadExtent(100.0, 0.0, 0.0, 100.0, 0.0),
    "rue y": RoadExtent(100.0, 0.0, 50.0, 100.0, 50.0),
}
# Position de chaque point sur son axe (le "monde" que la localisation voit).
WORLD = {
    "x1": ("rue x", 10.0), "x2": ("rue x", 50.0), "x3": ("rue x", 90.0),
    "y1": ("rue y", 20.0), "y2": ("rue y", 70.0),
}
CATEGORY = {i: "vert" for i in WORLD}


def _loc(i, category=None):
    road, pos = WORLD[i]
    y = 0.0 if road == "rue x" else 50.0
    return RoadLocation(i, category or CATEGORY[i], road, pos, pos, y)


def _state(h):
    return {
        "road_key": h.road_key, "depth_category": h.depth_category,
        "is_long": h.is_long, "length_m": h.length_m,
        "coords": segment_half_geometry(h),
    }


def _db(ids, categories=None):
    """Table segments issue d'une reconstruction complete de ``ids``."""
    categories = categories or CATEGORY
    halves = build_segment_halves([_loc(i, categories[i]) for i in sorted(ids)], EXTENTS)
    return {segment_key(h): _state(h) for h in halves}


def _incremental(existing, changed, eligible, categories=None):
    """Simule _sync_segments en mode incremental (localisation = WORLD)."""
    categories = categories or CATEGORY
    road_ids, id_roads, covered = index_existing_segments(existing)
    dirty = initial_dirty_ids(changed, eligible, eligible, covered)
    calls = []

    def locate(ids):
        calls.extend(ids)
        return {i: WORLD[i][0] for i in ids}

    roads, located = expand_dirty_roads(dirty, eligible, road_ids, id_roads, locate)
    locs = [_loc(i, categories[i]) for i in sorted(located)]
    fresh = build_segment_halves(locs, EXTENTS)
    return roads, sorted(calls), plan_segment_sync(fresh, existing, roads)


def test_rien_de_change_rien_a_recalculer():
    existing = _db(WORLD)
    roads, calls, plan = _incremental(existing, changed=set(), eligible=set(WORLD))
    assert roads == set() and calls == []
    assert plan.to_insert == plan.to_update == plan.to_delete == []


def test_ajout_au_milieu_ne_recalcule_que_sa_route_et_la_route_propre_est_intacte():
    existing = _db({"x1", "x3", "y1", "y2"})
    roads, calls, plan = _incremental(existing, changed={"x2"}, eligible=set(WORLD))
    assert roads == {"rue x"}
    assert calls == ["x1", "x2", "x3"]  # rue y jamais relocalisee
    touched = {h.road_key for h in plan.to_insert + plan.to_update}
    assert touched == {"rue x"}
    assert all(existing[k]["road_key"] == "rue x" for k in plan.to_delete)
    assert ("x1", "x3", "a", "R") in plan.to_delete  # l'ancienne paire directe
    # Les bouts de rue x1->debut et x3->fin sont identiques : non reecrits.
    assert plan.unchanged == 2


def test_point_passe_en_gris_sa_route_est_refaite_sans_lui():
    existing = _db(WORLD)
    eligible = set(WORLD) - {"x2"}  # x2 devenu 'manquante'
    roads, calls, plan = _incremental(existing, changed={"x2"}, eligible=eligible)
    assert roads == {"rue x"} and "x2" not in calls
    assert all("x2" not in k[:2] for k in (segment_key(h) for h in plan.to_insert))
    assert {k for k in plan.to_delete if "x2" in k[:2]} == {
        k for k in existing if "x2" in k[:2]
    }


def test_point_supprime_de_la_table_detecte_sans_changed_ids():
    existing = _db(WORLD)
    eligible = set(WORLD) - {"y2"}  # supprime hors script
    roads, calls, plan = _incremental(existing, changed=set(), eligible=eligible)
    assert roads == {"rue y"} and calls == ["y1"]
    assert all(existing[k]["road_key"] == "rue y" for k in plan.to_delete)
    assert any(k[0] == "y1" and k[1] == ROAD_END_SENTINEL for k in
               (segment_key(h) for h in plan.to_insert))  # y1 devient dernier point


def test_point_jamais_localise_est_retente():
    existing = _db({"x1", "x2", "x3"})  # rue y jamais construite
    roads, calls, plan = _incremental(existing, changed=set(), eligible=set(WORLD))
    assert roads == {"rue y"} and calls == ["y1", "y2"]
    assert {h.road_key for h in plan.to_insert} == {"rue y"}
    assert plan.to_delete == []


def test_changement_de_couleur_reecrit_seulement_les_moities_concernees():
    existing = _db(WORLD)
    categories = dict(CATEGORY, x2="rouge")
    roads, _calls, plan = _incremental(existing, {"x2"}, set(WORLD), categories)
    assert roads == {"rue x"} and plan.to_insert == [] and plan.to_delete == []
    assert {segment_key(h) for h in plan.to_update} == {
        ("x1", "x2", "b", "R"), ("x2", "x3", "a", "R"),
    }


def test_incremental_equivaut_a_la_reconstruction_complete():
    existing = _db({"x1", "x3", "y1", "y2"})
    _roads, _calls, plan = _incremental(existing, {"x2"}, set(WORLD))
    after = {k: v for k, v in existing.items() if k not in plan.to_delete}
    after.update({segment_key(h): _state(h) for h in plan.to_insert + plan.to_update})
    assert after == _db(WORLD)


def test_point_qui_change_de_route_rend_les_deux_routes_sales():
    existing = _db(WORLD)
    world_moved = dict(WORLD, x2=("rue y", 45.0))
    road_ids, id_roads, covered = index_existing_segments(existing)

    def locate(ids):
        return {i: world_moved[i][0] for i in ids}

    roads, located = expand_dirty_roads({"x2"}, set(WORLD), road_ids, id_roads, locate)
    assert roads == {"rue x", "rue y"} and set(located) == set(WORLD)


def test_index_ignore_les_sentinelles():
    existing = _db({"x1"})
    road_ids, id_roads, covered = index_existing_segments(existing)
    assert covered == {"x1"} and road_ids == {"rue x": {"x1"}}
    assert ROAD_START_SENTINEL not in covered


def test_point_changed():
    new = {"depth_category": "vert", "address_raw": "Rue X 1", "x": 1.0, "y": 2.0}
    assert point_changed(None, new)
    assert not point_changed(dict(new), new)
    assert not point_changed(dict(new, x=1.0 + 1e-9), new)
    assert point_changed(dict(new, x=1.5), new)
    assert point_changed(dict(new, depth_category="rouge"), new)
    assert point_changed(dict(new, address_raw="Rue X 3"), new)
    assert point_changed(dict(new, x=None), new)


def test_initial_dirty_ids():
    dirty = initial_dirty_ids(
        changed_ids={"a"}, eligible_ids={"a", "b", "c", "n"},
        locatable_ids={"a", "b", "c"}, covered_ids={"a", "c", "g"},
    )
    # a modifie ; b non couvert ; g couvert mais gris/supprime ; n sans nom de
    # rue : pas retente ; c propre.
    assert dirty == {"a", "b", "g"}


def test_segments_perimes_apres_purge_suspendue_sont_detectes():
    from geocode_asbuilt_depth import inconsistent_roads
    existing = _db({"x1", "x3", "y1", "y2"})
    assert inconsistent_roads(existing) == set()
    # Run avec x2 ajoute mais purge suspendue : insert/update ecrits, pas de delete.
    _roads, _calls, plan = _incremental(existing, {"x2"}, set(WORLD))
    blocked = dict(existing)
    blocked.update({segment_key(h): _state(h) for h in plan.to_insert + plan.to_update})
    assert inconsistent_roads(blocked) == {"rue x"}  # (x1,x3) ET (x1,x2) sortants
    # Run sain suivant, aucun point modifie : la route incoherente est refaite.
    road_ids, _id_roads, _covered = index_existing_segments(blocked)
    dirty = set()
    for road in inconsistent_roads(blocked):
        dirty |= road_ids[road]
    roads, _calls2, plan2 = _incremental_from(blocked, dirty)
    after = {k: v for k, v in blocked.items() if k not in plan2.to_delete}
    after.update({segment_key(h): _state(h) for h in plan2.to_insert + plan2.to_update})
    assert roads == {"rue x"} and after == _db(WORLD)


def _incremental_from(existing, extra_dirty):
    road_ids, id_roads, covered = index_existing_segments(existing)
    dirty = initial_dirty_ids(set(), set(WORLD), set(WORLD), covered) | extra_dirty
    roads, located = expand_dirty_roads(
        dirty, set(WORLD), road_ids, id_roads, lambda ids: {i: WORLD[i][0] for i in ids}
    )
    fresh = build_segment_halves([_loc(i) for i in sorted(located)], EXTENTS)
    return roads, sorted(located), plan_segment_sync(fresh, existing, roads)


def test_debut_de_route_en_double_detecte():
    from geocode_asbuilt_depth import inconsistent_roads
    existing = _db({"x2"})
    stale_start = ("x1", ROAD_START_SENTINEL, "a", "R")
    existing[stale_start] = dict(next(iter(existing.values())))
    assert inconsistent_roads(existing) == {"rue x"}


def test_point_present_sur_deux_cotes_ou_deux_routes_detecte():
    from geocode_asbuilt_depth import inconsistent_roads
    existing = _db({"x1", "y1"})
    # Restes d'un x1 passe cote L sans purge : chaine L complete ET chaine R.
    left = build_segment_halves([RoadLocation("x1", "vert", "rue x", 10.0, 10.0, 0.0, side="L")], EXTENTS)
    existing.update({segment_key(h): _state(h) for h in left})
    assert inconsistent_roads(existing) == {"rue x"}


# --- fusion des points co-localises -------------------------------------------
from geocode_asbuilt_depth import (  # noqa: E402
    colocated_raw_groups, count_zero_length_pairs, filter_protected_deletions,
    merge_colocated, with_companions,
)


def test_fusion_meme_point_projete_plus_petit_id_et_pire_categorie():
    locs = [
        RoadLocation("30", "vert", "rue x", 10.0, 10.0, 0.0),
        RoadLocation("20", "rouge", "rue x", 10.2, 10.2, 0.0),
        RoadLocation("10", "orange", "rue x", 10.0, 10.0, 0.3),
        RoadLocation("40", "vert", "rue x", 50.0, 50.0, 0.0),
    ]
    nodes, members = merge_colocated(locs)
    assert [(n.intervention_id, n.depth_category) for n in nodes] == [("10", "rouge"), ("40", "vert")]
    assert members == {"10": ("10", "20", "30")}
    halves = build_segment_halves(nodes, EXTENTS)
    assert count_zero_length_pairs(halves) == 0
    keys = [segment_key(h) for h in halves]
    assert len(keys) == len(set(keys))
    assert ("10", "40", "a", "R") in keys


def test_fusion_respecte_route_cote_et_tolerance():
    locs = [
        RoadLocation("1", "vert", "rue x", 10.0, 10.0, 0.0, side="R"),
        RoadLocation("2", "rouge", "rue x", 10.0, 10.0, 0.0, side="L"),   # autre cote
        RoadLocation("3", "rouge", "rue y", 10.0, 10.0, 0.0),             # autre route
        RoadLocation("4", "rouge", "rue x", 10.6, 10.6, 0.0, side="R"),   # > 0,5 m
    ]
    nodes, members = merge_colocated(locs)
    assert len(nodes) == 4 and members == {}


def test_groupes_bruts_meme_rue_meme_position():
    groups = colocated_raw_groups([
        ("1", "Rue X", 100.0, 100.0), ("2", "RUE X", 100.2, 100.0),
        ("3", "Rue Y", 100.0, 100.0), ("4", "Rue X", 200.0, 100.0), ("5", "", 100.0, 100.0),
    ])
    assert groups == {"1": frozenset({"1", "2"}), "2": frozenset({"1", "2"})}
    assert with_companions({"2", "4"}, groups) == {"1", "2", "4"}


def test_incremental_membre_fusionne_ni_retente_ni_perdu():
    # x2b : meme adresse/position que x2 (fusionne sous x2, plus petit id).
    world = dict(WORLD, x2b=("rue x", 50.0))
    categories = dict(CATEGORY, x2b="rouge")

    def locs_of(ids):
        out = []
        for i in sorted(ids):
            road, pos = world[i]
            y = 0.0 if road == "rue x" else 50.0
            out.append(RoadLocation(i, categories[i], road, pos, pos, y))
        return merge_colocated(out)[0]

    existing = {segment_key(h): _state(h) for h in build_segment_halves(locs_of(world), EXTENTS)}
    companions = colocated_raw_groups([
        (i, world[i][0], world[i][1], 0.0) for i in world
    ])
    road_ids, id_roads, covered = index_existing_segments(existing)
    assert "x2b" not in covered  # jamais cite par un segment...
    covered_g = with_companions(covered, companions)
    dirty = initial_dirty_ids(set(), set(world), set(world), covered_g)
    assert dirty == set()          # ... mais pas retente pour autant
    # Le membre non representant change : tout le groupe et sa route sont refaits.
    dirty = initial_dirty_ids({"x2b"}, set(world), set(world), covered_g)
    calls = []

    def locate(ids):
        calls.extend(ids)
        return {i: world[i][0] for i in ids}

    roads, located = expand_dirty_roads(dirty, set(world), road_ids, id_roads, locate,
                                        companions=companions)
    assert roads == {"rue x"} and {"x2", "x2b"} <= set(calls)
    fresh = build_segment_halves(locs_of(located), EXTENTS)
    plan = plan_segment_sync(fresh, existing, roads)
    assert plan.to_insert == [] and plan.to_delete == [] and plan.to_update == []


def test_purge_protegee_pour_les_routes_des_points_overpass_indisponible():
    existing = _db(WORLD)
    to_delete = sorted(existing)
    kept, blocked = filter_protected_deletions(to_delete, existing, {"rue x"})
    assert all(existing[k]["road_key"] == "rue y" for k in kept)
    assert blocked == sum(1 for k in existing if existing[k]["road_key"] == "rue x")
