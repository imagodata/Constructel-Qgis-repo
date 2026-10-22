import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    InterventionRecord, input_folder_error, merge_retry_records,
    ungeocoded_rows_to_records,
)


def test_rows_to_records_mappe_les_colonnes():
    recs = ungeocoded_rows_to_records(
        [("111", "WO-1", "Rue de la Gare 12", "1000", "Bruxelles", "80 cm", "a.msg")]
    )
    assert recs == [InterventionRecord(
        work_order="WO-1", intervention="111", address="Rue de la Gare 12",
        postal_code="1000", place="Bruxelles", depth_raw="80 cm", source_message="a.msg",
    )]


def test_rows_to_records_ignore_sans_intervention_ou_adresse_et_none():
    rows = [
        ("", "WO", "Rue X 1", "1000", "B", "", ""),
        ("222", "WO", "  ", "1000", "B", "", ""),
        ("333", None, "Rue Y 2", None, None, None, None),
    ]
    recs = ungeocoded_rows_to_records(rows)
    assert [r.intervention for r in recs] == ["333"]
    assert recs[0].work_order == "" and recs[0].postal_code == ""


def test_merge_garde_la_version_fraiche_et_ajoute_les_autres():
    fresh = InterventionRecord(intervention="111", address="Rue corrigee 1")
    old = InterventionRecord(intervention="111", address="Rue fausse 1")
    other = InterventionRecord(intervention="222", address="Rue Z 3")
    merged, n = merge_retry_records([fresh], [old, other])
    assert n == 1
    assert [r.address for r in merged] == ["Rue corrigee 1", "Rue Z 3"]


def test_merge_sans_relance_ne_change_rien():
    base = [InterventionRecord(intervention="1", address="A")]
    merged, n = merge_retry_records(base, [])
    assert n == 0 and merged == base


def test_dossier_requis_hors_mode_seul():
    assert input_folder_error("", False)
    assert input_folder_error(None, False)
    assert input_folder_error("   ", False)


def test_dossier_facultatif_en_mode_seul_ou_renseigne():
    assert input_folder_error("", True) is None
    assert input_folder_error("/data/rapports", False) is None
