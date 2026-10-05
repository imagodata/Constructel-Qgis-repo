import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    InterventionRecord, address_key, build_known_keys, is_already_present,
)

ROWS = [("111", "WO-1", "Rue de la Gare 12", "1000")]


def _rec(inter, wo, addr, postal="1000"):
    return InterventionRecord(work_order=wo, intervention=inter, address=addr, postal_code=postal)


def test_address_key_ignore_casse_et_espaces():
    assert address_key("Rue de la  Gare 12", "1000") == address_key("rue de la gare 12 ", "B-1000")


def test_address_key_vide():
    assert address_key("  ") == ""


def test_meme_intervention_deja_presente():
    ids, wo = build_known_keys(ROWS)
    assert is_already_present(_rec("111", "", ""), ids, wo)


def test_meme_work_order_meme_adresse_deja_presente():
    ids, wo = build_known_keys(ROWS)
    assert is_already_present(_rec("222", "WO-1", "rue de la gare 12"), ids, wo)


def test_meme_work_order_autre_adresse_reste_a_traiter():
    ids, wo = build_known_keys(ROWS)
    assert not is_already_present(_rec("222", "WO-1", "Rue du Pont 3"), ids, wo)


def test_meme_adresse_autre_work_order_reste_a_traiter():
    ids, wo = build_known_keys(ROWS)
    assert not is_already_present(_rec("222", "WO-2", "Rue de la Gare 12"), ids, wo)


def test_base_vide_rien_de_present():
    ids, wo = build_known_keys([])
    assert not is_already_present(_rec("1", "WO-1", "Rue X 1"), ids, wo)


def test_dirty_ids_sans_recalcul_seuls_les_points_modifies_du_run():
    from geocode_asbuilt_depth import initial_dirty_ids
    assert initial_dirty_ids({"9"}, {"1", "2", "9"}, {"1", "2", "9"}, {"9"}, False) == {"9"}


def test_dirty_ids_avec_recalcul_retente_les_points_non_couverts():
    from geocode_asbuilt_depth import initial_dirty_ids
    assert initial_dirty_ids(set(), {"1", "2"}, {"1", "2"}, {"1"}, True) == {"2"}
    assert initial_dirty_ids(set(), {"1", "2"}, {"1", "2"}, {"1"}) == {"2"}
