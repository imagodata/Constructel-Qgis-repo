"""Mise à jour de la profondeur des points déjà en base, arbitrée par la date du rapport."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    SKIP_NO_DEPTH, SKIP_OLDER, SKIP_SUPERSEDED, SKIP_UNDATED, SKIP_UP_TO_DATE,
    DepthUpdate, InterventionRecord, KnownPoint, NominatimHit,
    _build_attribute_values, address_key, build_depth_update_sql, build_known_points,
    dedupe_records, depth_update_dirty_ids, ids_to_geocode, normalize_report_date,
    plan_depth_updates, sql_text, strip_depth_fields,
)

D1 = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
D2 = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)
D3 = datetime(2026, 10, 15, 8, 0, tzinfo=timezone.utc)
TABLE = "public.geofiber_asbuilt_depth_points"


def _rec(inter, depth="60", date=D2, wo="WO-1", addr="Rue de la Gare 12", source="r.msg"):
    return InterventionRecord(
        work_order=wo, intervention=inter, address=addr, postal_code="1000",
        place="Bruxelles", depth_raw=depth, source_message=source, report_date=date,
    )


def _point(inter, measured=D1, wo="WO-1", addr="Rue de la Gare 12", cat="vert", updated=None):
    return KnownPoint(
        intervention_id=inter, work_order=wo, address_key=address_key(addr, "1000"),
        depth_category=cat, measured_at=measured, updated_at=updated,
    )


# --- date du rapport ---------------------------------------------------------
def test_date_avec_fuseau_ramenee_en_utc():
    paris = timezone(timedelta(hours=2))
    out = normalize_report_date(datetime(2026, 10, 13, 10, 0, tzinfo=paris))
    assert out == datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc)


def test_date_naive_consideree_utc():
    out = normalize_report_date(datetime(2026, 10, 13, 10, 0))
    assert out == datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc)


def test_date_texte_entete_email():
    out = normalize_report_date("Mon, 13 Oct 2026 10:00:00 +0200")
    assert out == datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc)


def test_date_absente_ou_illisible():
    assert normalize_report_date(None) is None
    assert normalize_report_date("") is None
    assert normalize_report_date("pas une date") is None


# --- dédoublonnage du lot ----------------------------------------------------
def test_dedoublonnage_le_rapport_le_plus_recent_gagne_quel_que_soit_l_ordre():
    out = dedupe_records([
        _rec("111", depth="70", date=D3, source="a.msg"),
        _rec("111", depth="40", date=D1, source="z.msg"),
    ])
    assert out[0].source_message == "a.msg"


def test_dedoublonnage_un_rapport_recent_sans_profondeur_ne_gagne_pas():
    out = dedupe_records([
        _rec("111", depth="40", date=D1, source="ancien.msg"),
        _rec("111", depth="", date=D3, source="recent.msg"),
    ])
    assert out[0].source_message == "ancien.msg"


def test_dedoublonnage_un_rapport_date_gagne_sur_un_non_date():
    out = dedupe_records([
        _rec("111", depth="40", date=D1, source="date.msg"),
        _rec("111", depth="70", date=None, source="sans_date.csv"),
    ])
    assert out[0].source_message == "date.msg"


# --- points connus en base ---------------------------------------------------
def test_points_connus_depuis_les_lignes_sql():
    rows = [("111", "WO-1", "Rue de la Gare 12", "1000", "vert", D1.timestamp(), None)]
    (point,) = build_known_points(rows)
    assert point.intervention_id == "111"
    assert point.address_key == address_key("Rue de la Gare 12", "1000")
    assert point.measured_at == D1
    assert point.updated_at is None


# --- planification -----------------------------------------------------------
def test_meme_intervention_rapport_plus_recent_mise_a_jour():
    plan = plan_depth_updates([_rec("111", date=D2)], [_point("111", measured=D1)])
    assert [(u.record.intervention, u.target_id) for u in plan.updates] == [("111", "111")]
    assert not plan.updates[0].renamed
    assert plan.new == [] and plan.skipped == []


def test_meme_intervention_rapport_plus_ancien_ignore():
    rec = _rec("111", date=D1)
    plan = plan_depth_updates([rec], [_point("111", measured=D2)])
    assert plan.updates == []
    assert plan.skipped == [(rec, SKIP_OLDER, "111")]


def test_meme_rapport_relance_deja_a_jour():
    rec = _rec("111", date=D2)
    plan = plan_depth_updates([rec], [_point("111", measured=D2)])
    assert plan.skipped == [(rec, SKIP_UP_TO_DATE, "111")]


def test_point_sans_date_de_mesure_mis_a_jour_par_tout_rapport_date():
    plan = plan_depth_updates([_rec("111", date=D1)], [_point("111", measured=None)])
    assert [u.target_id for u in plan.updates] == ["111"]


def test_rapport_sans_profondeur_n_efface_pas():
    rec = _rec("111", depth="", date=D3)
    plan = plan_depth_updates([rec], [_point("111", measured=D1)])
    assert plan.skipped == [(rec, SKIP_NO_DEPTH, "111")]


def test_rapport_sans_date_ne_modifie_pas_un_point_existant():
    rec = _rec("111", date=None)
    plan = plan_depth_updates([rec], [_point("111", measured=None)])
    assert plan.skipped == [(rec, SKIP_UNDATED, "111")]


def test_nouveau_numero_meme_work_order_et_adresse_renumerote_le_point():
    plan = plan_depth_updates([_rec("222", date=D2)], [_point("111", measured=D1)])
    (update,) = plan.updates
    assert (update.record.intervention, update.target_id, update.renamed) == ("222", "111", True)


def test_nouveau_numero_adresse_inconnue_a_geocoder():
    rec = _rec("222", addr="Rue Neuve 5")
    plan = plan_depth_updates([rec], [_point("111")])
    assert plan.new == [rec] and plan.updates == []


def test_nouveau_numero_autre_work_order_a_geocoder():
    rec = _rec("222", wo="WO-2")
    plan = plan_depth_updates([rec], [_point("111")])
    assert plan.new == [rec]


def test_deux_lignes_du_lot_visent_le_meme_point_la_plus_recente_gagne():
    ancien = _rec("111", date=D2, source="ancien.msg")
    recent = _rec("222", date=D3, source="recent.msg")
    plan = plan_depth_updates([ancien, recent], [_point("111", measured=D1)])
    assert [(u.record.intervention, u.target_id) for u in plan.updates] == [("222", "111")]
    assert plan.skipped == [(ancien, SKIP_SUPERSEDED, "111")]


def test_a_date_egale_le_meme_numero_gagne_sur_la_renumerotation():
    meme = _rec("111", date=D2)
    autre = _rec("222", date=D2)
    plan = plan_depth_updates([autre, meme], [_point("111", measured=D1)])
    assert [(u.record.intervention, u.target_id) for u in plan.updates] == [("111", "111")]
    assert plan.skipped == [(autre, SKIP_SUPERSEDED, "111")]


def test_plusieurs_points_a_la_meme_adresse_le_plus_recent_est_renumerote():
    points = [_point("100", measured=D1), _point("111", measured=D2)]
    plan = plan_depth_updates([_rec("222", date=D3)], points)
    assert [u.target_id for u in plan.updates] == ["111"]


def test_renumerotation_plus_ancienne_que_la_base_ignoree():
    rec = _rec("222", date=D1)
    plan = plan_depth_updates([rec], [_point("111", measured=D2)])
    assert plan.skipped == [(rec, SKIP_OLDER, "111")]


# --- géocodage selon le mode -------------------------------------------------
def _plan_mixte():
    return plan_depth_updates(
        [
            _rec("NEW", addr="Rue Neuve 5"),               # nouveau
            _rec("111", date=D3),                           # mise à jour même numéro
            _rec("333", date=D1, wo="WO-3"),               # même numéro, plus ancien
            _rec("444", date=D1, wo="WO-4"),               # renumérotation plus ancienne
        ],
        [
            _point("111", measured=D1),
            _point("333", measured=D2, wo="WO-3"),
            _point("400", measured=D2, wo="WO-4"),
        ],
    )


def test_mode_defaut_seuls_les_nouveaux_sont_geocodes():
    assert ids_to_geocode(_plan_mixte(), recompute=False) == {"NEW"}


def test_mode_recalculer_regeocode_seulement_les_points_a_jour():
    # 333 (rapport plus ancien que la base) garderait une adresse périmée ;
    # 444 viserait le point 400 sans le renuméroter (doublon).
    assert ids_to_geocode(_plan_mixte(), recompute=True) == {"NEW", "111"}


def test_mode_recalculer_ligne_supplantee_par_une_renumerotation_non_geocodee():
    # 111 (D2) et 222 (D3) visent le point 111 : 222 le renumérote, 111 ne doit
    # pas être re-géocodé (il serait inséré en doublon gris).
    plan = plan_depth_updates(
        [_rec("111", date=D2), _rec("222", date=D3)], [_point("111", measured=D1)]
    )
    assert ids_to_geocode(plan, recompute=True) == {"222"}


def test_mode_recalculer_rapport_a_jour_ou_sans_profondeur_regeocode():
    plan = plan_depth_updates(
        [_rec("111", date=D2), _rec("333", depth="", date=D3, wo="WO-3")],
        [_point("111", measured=D2), _point("333", measured=D1, wo="WO-3")],
    )
    assert ids_to_geocode(plan, recompute=True) == {"111", "333"}


def test_les_champs_de_profondeur_sont_retires_pour_un_point_existant():
    values = {"intervention_id": "111", "address_raw": "x", "depth_cm": 60.0,
              "depth_category": "vert", "measured_at": D2, "source_message": "r.msg"}
    assert strip_depth_fields(values) == {"intervention_id": "111", "address_raw": "x"}


def test_valeurs_inserees_portent_la_date_du_rapport():
    hit = NominatimHit(lat=50.85, lon=4.35, postcode="1000", city="Bruxelles")
    values = _build_attribute_values(_rec("111", date=D2), "q", "ok", hit)
    assert values["measured_at"] == D2


# --- écriture SQL ------------------------------------------------------------
def test_sql_text_double_les_apostrophes():
    assert sql_text("O'Brien.msg") == "'O''Brien.msg'"
    assert sql_text(None) == "NULL"


def test_sql_mise_a_jour_gardee_par_la_date():
    sql = build_depth_update_sql(DepthUpdate(_rec("111", depth="70"), "111"), TABLE)
    epoch = repr(D2.timestamp())
    assert sql.startswith(f"UPDATE {TABLE} SET ")
    assert "depth_cm = 70.0" in sql
    assert "depth_category = 'vert'" in sql
    assert f"measured_at = to_timestamp({epoch})" in sql
    assert "source_message = 'r.msg'" in sql
    assert "intervention_id = '111'," not in sql  # pas de renumérotation
    assert sql.endswith(
        f"WHERE intervention_id = '111' AND (measured_at IS NULL OR "
        f"measured_at < to_timestamp({epoch})) RETURNING intervention_id"
    )


def test_sql_renumerotation_change_l_identifiant():
    sql = build_depth_update_sql(DepthUpdate(_rec("222"), "111"), TABLE)
    assert "SET intervention_id = '222', " in sql
    assert "WHERE intervention_id = '111' " in sql


# --- segments à recalculer ---------------------------------------------------
def test_renumerotation_rend_sales_l_ancien_et_le_nouveau_numero():
    update = DepthUpdate(_rec("222"), "111", old_category="vert")
    assert depth_update_dirty_ids(update) == {"111", "222"}


def test_changement_de_categorie_rend_le_point_sale():
    update = DepthUpdate(_rec("111", depth="40"), "111", old_category="vert")
    assert depth_update_dirty_ids(update) == {"111"}


def test_meme_categorie_aucun_segment_a_recalculer():
    update = DepthUpdate(_rec("111", depth="70"), "111", old_category="vert")
    assert depth_update_dirty_ids(update) == set()


# --- durcissements (revue) ---------------------------------------------------
from geocode_asbuilt_depth import (  # noqa: E402
    dedupe_records as _dedupe, initial_dirty_ids, parse_depth_cm,
    point_values_for_upsert, ungeocoded_rows_to_records,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def test_date_tronquee_a_la_seconde():
    out = normalize_report_date(datetime(2026, 10, 13, 10, 0, 5, 123457, tzinfo=timezone.utc))
    assert out == datetime(2026, 10, 13, 10, 0, 5, tzinfo=timezone.utc)


def test_date_nulle_extract_msg_annee_4500_rejetee():
    assert normalize_report_date(datetime(4500, 8, 31, 23, 59), now=NOW) is None


def test_date_future_rejetee_et_marge_d_un_jour():
    assert normalize_report_date(NOW + timedelta(days=2), now=NOW) is None
    assert normalize_report_date(NOW + timedelta(hours=12), now=NOW) == NOW + timedelta(hours=12)


def test_date_filetime_zero_1601_rejetee():
    assert normalize_report_date(datetime(1601, 1, 1)) is None


def test_profondeur_non_finie_illisible():
    assert parse_depth_cm("nan") is None
    assert parse_depth_cm("inf") is None
    assert parse_depth_cm("1e400") is None


def test_profondeur_manquante_ne_compte_pas_comme_mesure():
    out = _dedupe([
        _rec("111", depth="60", date=D1, source="ancien.msg"),
        _rec("111", depth="0", date=D3, source="recent.msg"),
    ])
    assert out[0].source_message == "ancien.msg"
    rec = _rec("111", depth="5", date=D3)
    plan = plan_depth_updates([rec], [_point("111", measured=D1)])
    assert plan.skipped == [(rec, SKIP_NO_DEPTH, "111")]


def test_dedoublonnage_complete_les_champs_d_adresse_vides():
    ancien = _rec("111", depth="40", date=D1, source="ancien.msg")
    recent = InterventionRecord(
        work_order="", intervention="111", address="", postal_code="", place="",
        depth_raw="70", source_message="recent.msg", report_date=D3,
    )
    (out,) = _dedupe([ancien, recent])
    assert (out.depth_raw, out.source_message, out.report_date) == ("70", "recent.msg", D3)
    assert (out.work_order, out.address, out.postal_code, out.place) == (
        "WO-1", "Rue de la Gare 12", "1000", "Bruxelles")
    assert recent.address == ""  # entrée non modifiée


def test_point_sans_geometrie_jamais_cible_d_une_renumerotation():
    rows = [
        ("111", "WO-1", "Rue de la Gare 12", "1000", "vert", D1.timestamp(), None, True),
        ("222", "WO-1", "Rue de la Gare 12", "1000", "", None, None, False),
    ]
    rec = _rec("222", date=D3)
    plan = plan_depth_updates([rec], build_known_points(rows))
    assert plan.new == [rec] and plan.updates == []


def test_point_sans_geometrie_pas_vise_par_work_order_et_adresse():
    rows = [("100", "WO-1", "Rue de la Gare 12", "1000", "", None, None, False)]
    rec = _rec("222", date=D3)
    assert plan_depth_updates([rec], build_known_points(rows)).new == [rec]


def test_renumerotation_malgre_un_code_postal_different():
    point = KnownPoint(intervention_id="111", work_order="WO-1",
                       address_key=address_key("Rue de la Gare 12", "1020"), measured_at=D1)
    plan = plan_depth_updates([_rec("222", date=D3)], [point])
    assert [(u.target_id, u.renamed) for u in plan.updates] == [("111", True)]


def test_points_ex_aequo_choix_deterministe():
    points = [_point("100", measured=D1), _point("111", measured=D1)]
    first = plan_depth_updates([_rec("222", date=D3)], points).updates[0].target_id
    second = plan_depth_updates([_rec("222", date=D3)], points[::-1]).updates[0].target_id
    assert first == second == "111"


def test_epoch_avant_1970_lu():
    rows = [("111", "WO-1", "Rue X 1", "1000", "vert", -86400.0, None, True)]
    assert build_known_points(rows)[0].measured_at == datetime(1969, 12, 31, tzinfo=timezone.utc)


def test_non_geocodees_relues_avec_leur_date():
    rows = [("111", "WO-1", "Rue X 1", "1000", "B", "60", "r.msg", D2.timestamp())]
    (rec,) = ungeocoded_rows_to_records(rows)
    assert rec.report_date == D2
    (rec7,) = ungeocoded_rows_to_records([rows[0][:7]])
    assert rec7.report_date is None


def test_segments_des_points_disparus_repares_sans_recalcul():
    assert initial_dirty_ids(set(), {"1"}, {"1"}, {"1", "ancien"}, False) == {"ancien"}


_FULL = {"intervention_id": "111", "address_raw": "x", "depth_cm": 70.0,
         "depth_category": "vert", "measured_at": D3, "source_message": "r.msg"}


def test_upsert_insertion_complete_autorisee():
    assert point_values_for_upsert(_FULL, existing=False, existing_measured_at=None,
                                   measured_column=True) == _FULL


def test_upsert_jamais_d_insertion_sans_mesure():
    assert point_values_for_upsert(strip_depth_fields(_FULL), existing=False,
                                   existing_measured_at=None, measured_column=True) is None


def test_upsert_point_existant_mesure_plus_recente_ecrite():
    assert point_values_for_upsert(_FULL, existing=True, existing_measured_at=D2,
                                   measured_column=True) == _FULL


def test_upsert_point_existant_mesure_plus_ancienne_ou_non_datee_conservee():
    stripped = strip_depth_fields(_FULL)
    assert point_values_for_upsert(_FULL, True, D3, True) == stripped
    assert point_values_for_upsert(dict(_FULL, measured_at=None), True, None, True) == stripped


def test_upsert_sans_colonne_de_date_ancien_comportement():
    assert point_values_for_upsert(_FULL, True, None, measured_column=False) == _FULL


from geocode_asbuilt_depth import retained_by_target  # noqa: E402


def test_ligne_retenue_par_point_pour_le_journal():
    # Même email (date égale) : la première ligne prend le point, les autres
    # sont écartées ; le journal doit nommer la ligne retenue.
    lignes = [_rec("222", date=D2), _rec("333", date=D2), _rec("444", date=D2, depth="")]
    plan = plan_depth_updates(lignes, [_point("111", measured=D1)])
    assert retained_by_target(plan) == {"111": "222"}
    assert [r.intervention for r, reason, _t in plan.skipped if reason == SKIP_SUPERSEDED] == ["333", "444"]


def test_ligne_retenue_meme_sans_mise_a_jour():
    plan = plan_depth_updates(
        [_rec("111", date=D1), _rec("222", date=D1)], [_point("111", measured=D1)]
    )
    assert retained_by_target(plan) == {"111": "111"}
