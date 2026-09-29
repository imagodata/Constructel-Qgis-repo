import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    SegmentHalf, plan_segment_sync, segment_half_changed, segment_half_geometry,
    segment_key,
)


def _half(a, b, half, side="R", road="rue x", category="vert", length=10.0):
    return SegmentHalf(
        point_a_intervention_id=a, point_b_intervention_id=b, half=half,
        depth_category=category, is_long=False, length_m=length, road_key=road,
        start_x=0.0, start_y=0.0, end_x=10.0, end_y=0.0, side=side, offset_m=3.0,
    )


def _state(half, **overrides):
    """Etat en base identique a ``half`` (geometrie decalee incluse)."""
    state = {
        "road_key": half.road_key, "depth_category": half.depth_category,
        "is_long": half.is_long, "length_m": half.length_m,
        "coords": segment_half_geometry(half),
    }
    state.update(overrides)
    return state


def test_premiere_synchro_tout_en_insertion_rien_a_supprimer():
    fresh = [_half("1", "2", "a"), _half("1", "2", "b")]
    plan = plan_segment_sync(fresh, existing={})
    assert len(plan.to_insert) == 2 and plan.to_update == []
    assert plan.to_delete == [] and plan.unchanged == 0


def test_rerun_sans_changement_ne_reecrit_rien():
    fresh = [_half("1", "2", "a"), _half("1", "2", "b")]
    existing = {segment_key(h): _state(h) for h in fresh}
    plan = plan_segment_sync(fresh, existing)
    assert plan.to_insert == [] and plan.to_update == [] and plan.to_delete == []
    assert plan.unchanged == 2


def test_segment_modifie_est_mis_a_jour_seulement_lui():
    a, b = _half("1", "2", "a"), _half("1", "2", "b")
    existing = {segment_key(a): _state(a), segment_key(b): _state(b, depth_category="rouge")}
    plan = plan_segment_sync([a, b], existing)
    assert plan.to_update == [b] and plan.unchanged == 1


def test_segment_disparu_est_marque_a_supprimer():
    fresh = [_half("1", "2", "a")]
    old = _half("2", "3", "a", side="L")
    existing = {segment_key(fresh[0]): _state(fresh[0]), segment_key(old): _state(old)}
    plan = plan_segment_sync(fresh, existing)
    assert plan.to_delete == [("2", "3", "a", "L")]


def test_la_cle_inclut_le_cote():
    assert segment_key(_half("1", "2", "a", side="L")) == ("1", "2", "a", "L")


def test_changement_de_cote_purge_l_ancienne_cle():
    new = _half("1", "2", "a", side="L")
    old = _half("1", "2", "a", side="R")
    plan = plan_segment_sync([new], {segment_key(old): _state(old)})
    assert [segment_key(h) for h in plan.to_insert] == [("1", "2", "a", "L")]
    assert plan.to_delete == [("1", "2", "a", "R")]


def test_purge_limitee_aux_routes_du_perimetre():
    fresh = [_half("1", "2", "a", road="rue x")]
    stale_x = _half("8", "9", "a", road="rue x")
    clean_y = _half("5", "6", "a", road="rue y")
    existing = {
        segment_key(fresh[0]): _state(fresh[0]),
        segment_key(stale_x): _state(stale_x),
        segment_key(clean_y): _state(clean_y),
    }
    plan = plan_segment_sync(fresh, existing, scope_roads={"rue x"})
    assert plan.to_delete == [segment_key(stale_x)]  # rue y (propre) jamais purgee
    full = plan_segment_sync(fresh, existing, scope_roads=None)
    assert sorted(full.to_delete) == sorted([segment_key(stale_x), segment_key(clean_y)])


def test_segment_half_changed_tolerances_et_valeurs_illisibles():
    h = _half("1", "2", "a")
    assert not segment_half_changed(h, _state(h, length_m=10.0 + 1e-9))
    assert segment_half_changed(h, _state(h, length_m=10.001))
    assert segment_half_changed(h, _state(h, coords=None))
    assert segment_half_changed(h, _state(h, is_long=None))
    assert segment_half_changed(h, _state(h, road_key="autre"))
    ((x1, y1), (x2, y2)), = segment_half_geometry(h)
    assert segment_half_changed(h, _state(h, coords=(((x1, y1 + 0.01), (x2, y2)),)))
    # Nombre de parties ou de sommets different -> change.
    assert segment_half_changed(h, _state(h, coords=(((x1, y1), (x2, y2)),) * 2))
    assert segment_half_changed(h, _state(h, coords=(((x1, y1), (x1, y1), (x2, y2)),)))
