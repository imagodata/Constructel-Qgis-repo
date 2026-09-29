import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import SegmentHalf, plan_segment_sync


def _half(a, b, half):
    return SegmentHalf(
        point_a_intervention_id=a, point_b_intervention_id=b, half=half,
        depth_category="vert", is_long=False, length_m=10.0, road_key="rue x",
        start_x=0.0, start_y=0.0, end_x=10.0, end_y=0.0,
    )


def test_premiere_synchro_tout_en_upsert_rien_a_supprimer():
    fresh = [_half("1", "2", "a"), _half("1", "2", "b")]
    to_upsert, to_delete = plan_segment_sync(fresh, existing_keys=set())
    assert len(to_upsert) == 2
    assert to_delete == []


def test_rerun_sans_changement_est_idempotent():
    fresh = [_half("1", "2", "a"), _half("1", "2", "b")]
    existing = {("1", "2", "a"), ("1", "2", "b")}
    to_upsert, to_delete = plan_segment_sync(fresh, existing_keys=existing)
    assert len(to_upsert) == 2  # upsert = toujours rejoue (ON CONFLICT DO UPDATE cote SQL)
    assert to_delete == []


def test_segment_disparu_est_marque_a_supprimer():
    fresh = [_half("1", "2", "a"), _half("1", "2", "b")]
    existing = {("1", "2", "a"), ("1", "2", "b"), ("2", "3", "a"), ("2", "3", "b")}
    to_upsert, to_delete = plan_segment_sync(fresh, existing_keys=existing)
    assert sorted(to_delete) == [("2", "3", "a"), ("2", "3", "b")]
