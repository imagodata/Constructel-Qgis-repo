import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import InterventionRecord, dedupe_records


def _rec(intervention, address="Rue X 1", depth="60", source="a.msg", **kw):
    return InterventionRecord(
        work_order=kw.get("work_order", "W1"), intervention=intervention,
        address=address, postal_code=kw.get("postal_code", "1000"),
        place=kw.get("place", "Bruxelles"), depth_raw=depth, source_message=source,
    )


def test_une_seule_ligne_par_intervention():
    out = dedupe_records([_rec("12345678"), _rec("12345678"), _rec("12345679")])
    assert [r.intervention for r in out] == ["12345678", "12345679"]


def test_a_completude_egale_la_derniere_occurrence_gagne():
    out = dedupe_records([
        _rec("12345678", depth="40", source="2026-01.msg"),
        _rec("12345678", depth="60", source="2026-02.msg"),
    ])
    assert len(out) == 1 and out[0].source_message == "2026-02.msg"


def test_la_ligne_la_plus_complete_gagne_meme_si_plus_ancienne():
    out = dedupe_records([
        _rec("12345678", depth="60", source="ancien.msg"),
        _rec("12345678", depth="", address="", source="recent.msg"),
    ])
    assert out[0].source_message == "ancien.msg"


def test_ordre_de_sortie_suit_la_premiere_apparition_et_ids_vides_ecartes():
    out = dedupe_records([
        _rec("22222222"), _rec(""), _rec("11111111"), _rec("22222222", source="b.msg"),
    ])
    assert [r.intervention for r in out] == ["22222222", "11111111"]
    assert out[0].source_message == "b.msg"


def test_cle_insensible_aux_espaces():
    out = dedupe_records([_rec("12345678"), _rec(" 12345678 ", source="b.msg")])
    assert len(out) == 1
