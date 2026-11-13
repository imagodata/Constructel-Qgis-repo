"""Bridge 1.8.4 — périmètre de session lisible à la connexion (log réel du
12/11 : « périmètre MRO [, , , …(40 vides)…, ,, …, f, f, {, }] / POP [{, }] »).

Cause : current_gis_*_ids() renvoient du uuid[] ; psycopg2 n'a pas de
typecaster pour uuid[] (OID 2951) et rend le littéral « {a,b} », que _ids()
itérait caractère par caractère jusqu'en 1.8.3. Conséquences : 40 libellés
vides (les tirets) + 9 virgules pour 10 MRO, et « {} » (aucune POP) pris
pour un périmètre NON vide -- scope_kind/write_scope_kind « scoped » au lieu
de « none », avertissement « aucun MRO/POP coché » jamais affiché, requête
des noms en échec (« Noms des zones du perimetre illisibles »).

Correctif : ::text[] dans SCOPE_QUERY (parsé nativement, NULL reste NULL) et
_ids() défensif (liste ou littéral brut). Message : noms, dimension vide
omise, troncature à 3 noms « … (+N) » (liste complète au journal), « écriture
sur tout le périmètre » quand l'écriture égale la lecture.
"""
import re
import sys
import uuid

import pytest

from constructel_bridge import bridge_nominatif as bn
from constructel_bridge_tests.test_bridge18_connect import (
    LOGIN,
    _FakeCursor,
    _PgErr,
    _logs,
    _make_plugin,
)
from constructel_bridge_tests.test_bridge18_scope import _plugin

# 10 MRO à premiers blocs distincts (repli d'affichage sans nom).
MRO_IDS = [str(uuid.UUID(f"{i:08x}-1111-4111-8111-{i:012x}")) for i in range(1, 11)]
MRO_NAMES = ["Anderlecht", "Etterbeek", "Ixelles", "Jette", "Koekelberg",
             "Molenbeek", "Saint-Gilles", "Schaerbeek", "Uccle", "Woluwe"]
NAMES = dict(zip(MRO_IDS, MRO_NAMES))


def _pg_literal(ids):
    """Ce que psycopg2 rend pour un uuid[] (sans typecaster)."""
    return "{" + ",".join(ids) + "}"


LIT10 = _pg_literal(MRO_IDS)
# Le cas réel : 10 MRO en lecture, les mêmes en écriture, aucune POP.
REAL_ROW_RAW = ("DESIGNER", True, True, LIT10, _pg_literal(reversed(MRO_IDS)), "{}", "{}")
REAL_ROW_TEXT = ("DESIGNER", True, True, list(MRO_IDS), list(MRO_IDS), [], [])
EMPTY_ROW_RAW = ("DESIGNER", True, True, "{}", "{}", "{}", "{}")


def _fr(monkeypatch):
    monkeypatch.setattr(sys.modules["constructel_bridge.i18n"], "_current_lang", "fr")


# --- _ids : liste, littéral brut, NULL ---------------------------------------


def test_ids_null_reste_vide():
    assert bn._ids(None) == []


@pytest.mark.parametrize("raw", ["{}", " {} ", "{ }"])
def test_ids_litteral_vide_donne_liste_vide(raw):
    assert bn._ids(raw) == []


def test_ids_litteral_uuid_donne_les_uuid_et_pas_des_caracteres():
    assert bn._ids(_pg_literal(MRO_IDS[:2])) == MRO_IDS[:2]
    assert bn._ids(LIT10) == MRO_IDS


def test_ids_litteral_guillemets_echappements_et_null():
    assert bn._ids('{"a b","c\\"d",NULL,e,"NULL",""}') == ["a b", 'c"d', "e", "NULL"]


def test_ids_liste_tuple_et_uuid():
    assert bn._ids(["a", "b"]) == ["a", "b"]
    assert bn._ids(("a",)) == ["a"]
    assert bn._ids([]) == []
    assert bn._ids([uuid.UUID(MRO_IDS[0]), None]) == [MRO_IDS[0]]


def test_ids_chaine_simple_est_un_seul_identifiant():
    assert bn._ids(MRO_IDS[0]) == [MRO_IDS[0]]


def test_scope_query_caste_les_quatre_tableaux_en_text():
    casted = re.findall(r"current_gis_(?:mro|pop)_ids\((?:true|false)\)::text\[\]", bn.SCOPE_QUERY)
    assert len(casted) == 4
    assert not re.findall(r"_ids\((?:true|false)\)(?!::text\[\])", bn.SCOPE_QUERY)


# --- classification sur les littéraux bruts -----------------------------------


@pytest.mark.parametrize("row, kind, write_kind", [
    (EMPTY_ROW_RAW, "none", "none"),
    (REAL_ROW_RAW, "scoped", "scoped"),
    (("DESIGNER", True, True, _pg_literal(MRO_IDS[:1]), "{}", "{}", "{}"), "scoped", "none"),
    (("VIEWER", True, False, LIT10, "{}", "{}", "{}"), "scoped", "none"),
])
def test_scope_kind_sur_litteraux_bruts(row, kind, write_kind):
    scope = bn.parse_session_scope(row)
    assert bn.scope_kind(scope) == kind
    assert bn.write_scope_kind(scope) == write_kind


def test_litteral_brut_parse_comme_le_text_array():
    raw, text = bn.parse_session_scope(REAL_ROW_RAW), bn.parse_session_scope(REAL_ROW_TEXT)
    assert raw.mro_ids == text.mro_ids == MRO_IDS
    assert raw.pop_ids == text.pop_ids == []
    assert sorted(raw.mro_write_ids) == sorted(text.mro_write_ids)


def test_null_reste_bypass_et_differe_du_tableau_vide():
    admin = bn.parse_session_scope(("ADMIN", True, True, None, None, None, None))
    assert admin.bypass is True and bn.scope_kind(admin) == "all"
    assert bn.write_scope_kind(admin) == "all"

    write_all = bn.parse_session_scope(("X", True, True, "{}", None, "{}", "{}"))
    assert write_all.bypass is False
    assert write_all.write_bypass is True
    assert bn.scope_kind(write_all) == "none"


def test_avertissement_sans_ecriture_se_declenche_sur_litteraux_bruts(bp18, monkeypatch):
    # 1.8.3 : « {} » en écriture était pris pour un MRO coché -> jamais affiché.
    plugin = _plugin(bp18, monkeypatch, ("DESIGNER", True, True, _pg_literal(MRO_IDS[:1]), "{}", "{}", "{}"))
    assert plugin._warn_if_no_write_perimeter() is True

    plugin = _plugin(bp18, monkeypatch, EMPTY_ROW_RAW)  # rien à cocher (scope.none)
    assert plugin._warn_if_no_write_perimeter() is False


# --- helpers de formatage ------------------------------------------------------


@pytest.mark.parametrize("labels, max_names, expected", [
    ([], 3, ""),
    (["A", "B", "C"], 3, "A, B, C"),
    (["A", "B", "C", "D"], 3, "A, B, C… (+1)"),
    (MRO_NAMES, 3, "Anderlecht, Etterbeek, Ixelles… (+7)"),
    (MRO_NAMES, None, ", ".join(MRO_NAMES)),
])
def test_summarize_labels(labels, max_names, expected):
    assert bn.summarize_labels(labels, max_names) == expected


def test_scope_labels_tri_insensible_a_la_casse_et_aux_accents():
    names = {"a": "uccle", "b": "Anderlecht", "c": "Évere", "d": "Zaventem"}
    assert bn.scope_labels(["a", "b", "c", "d"], names) == ["Anderlecht", "Évere", "uccle", "Zaventem"]


def test_write_scope_equals_read_ignore_l_ordre():
    assert bn.write_scope_equals_read(bn.parse_session_scope(REAL_ROW_RAW)) is True
    pop_write = bn.parse_session_scope(("DESIGNER", True, True, ["m1"], [], ["p1", "p2"], ["p2"]))
    assert bn.write_scope_equals_read(pop_write) is False


# --- texte de session ----------------------------------------------------------


def _scoped(bp, monkeypatch, row, mro_names=None, pop_names=None):
    plugin = _plugin(bp, monkeypatch, row)
    plugin._scope_names = (mro_names or {}, pop_names or {})
    return plugin


def test_cas_reel_10_mro_sans_pop_ecriture_identique(bp18, monkeypatch):
    plugin = _scoped(bp18, monkeypatch, REAL_ROW_RAW, NAMES)
    expected = (bp18.tr("scope.mro", count=10, names="Anderlecht, Etterbeek, Ixelles… (+7)")
                + " / " + bp18.tr("scope.write_all"))
    assert plugin._scope_text() == expected
    full = plugin._scope_text(max_names=None)
    assert all(name in full for name in MRO_NAMES) and "(+" not in full


def test_cas_reel_message_francais(bp18, monkeypatch):
    plugin = _scoped(bp18, monkeypatch, REAL_ROW_RAW, NAMES)
    _fr(monkeypatch)
    assert bp18.tr("conn.connected_nominal", login="christopherroland", scope=plugin._scope_text()) == (
        "Connecté en tant que christopherroland - 10 MRO : Anderlecht, Etterbeek, Ixelles… (+7)"
        " / écriture sur tout le périmètre"
    )


def test_compte_sans_perimetre(bp18, monkeypatch):
    plugin = _scoped(bp18, monkeypatch, EMPTY_ROW_RAW)
    assert plugin._scope_text() == bp18.tr("scope.none")
    plugin = _scoped(bp18, monkeypatch, ("VIEWER", True, False, "{}", "{}", "{}", "{}"))
    assert plugin._scope_text() == bp18.tr("scope.none") + " / " + bp18.tr("scope.readonly")


def test_dimension_vide_omise(bp18, monkeypatch):
    plugin = _scoped(bp18, monkeypatch, ("DESIGNER", True, True, [], [], ["p1", "p2"], ["p2", "p1"]),
                     pop_names={"p1": "POP_01", "p2": "POP_02"})
    text = plugin._scope_text()
    assert text == bp18.tr("scope.pop", count=2, names="POP_01, POP_02") + " / " + bp18.tr("scope.write_all")
    assert "MRO" not in text and "[" not in text


def test_ecriture_partielle_listee_sur_ses_seules_dimensions(bp18, monkeypatch):
    plugin = _scoped(bp18, monkeypatch, ("DESIGNER", True, True, ["m1"], ["m1"], ["p1"], []),
                     {"m1": "Jette"}, {"p1": "POP_01"})
    sep = bp18.tr("scope.sep")
    mro = bp18.tr("scope.mro", count=1, names="Jette")
    pop = bp18.tr("scope.pop", count=1, names="POP_01")
    assert plugin._scope_text() == f"{mro}{sep}{pop} / " + bp18.tr("scope.write_scoped", dims=mro)


def test_ecriture_partielle_tronquee(bp18, monkeypatch):
    plugin = _scoped(bp18, monkeypatch, ("DESIGNER", True, True, MRO_IDS, MRO_IDS[:5], [], []), NAMES)
    assert plugin._scope_text().endswith(" / " + bp18.tr(
        "scope.write_scoped",
        dims=bp18.tr("scope.mro", count=5, names="Anderlecht, Etterbeek, Ixelles… (+2)")))


def test_ecriture_null_sur_perimetre_lu(bp18, monkeypatch):
    plugin = _scoped(bp18, monkeypatch, ("X", True, True, ["m1"], None, ["p1"], []))
    assert plugin._scope_text().endswith(" / " + bp18.tr("scope.write_all"))


def test_noms_inconnus_repli_sur_le_premier_bloc(bp18, monkeypatch):
    plugin = _scoped(bp18, monkeypatch, ("VIEWER", True, False, MRO_IDS[:2], [], [], []))
    assert plugin._scope_text() == (
        bp18.tr("scope.mro", count=2, names="00000001, 00000002") + " / " + bp18.tr("scope.readonly"))


# --- de bout en bout : connexion avec le littéral brut de psycopg2 ------------


class _StrictCursor(_FakeCursor):
    """La requête des noms échoue comme le serveur si elle reçoit autre chose
    qu'une liste d'UUID (1.8.3 : les caractères du littéral)."""

    def execute(self, sql, params=None):
        if 'FROM "wyre".zone_mro' in sql or 'FROM "wyre".zone_pop' in sql:
            for value in params[0]:
                try:
                    uuid.UUID(str(value))
                except ValueError:
                    self.executed.append((sql, params))
                    raise _PgErr(f'invalid input syntax for type uuid: "{value}"')
        super().execute(sql, params)


@pytest.mark.parametrize("row", [REAL_ROW_RAW, REAL_ROW_TEXT])
def test_connexion_cas_reel_noms_resolus_et_liste_complete_au_journal(bp18, monkeypatch, tmp_path, row):
    from qgis.core import Qgis

    cur = _StrictCursor(scope_row=row, mro_names=[(i, NAMES[i]) for i in MRO_IDS])
    plugin, _calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert not [m for m in _logs(Qgis.MessageLevel.Warning) if "illisible" in m]
    name_queries = [p for (s, p) in cur.executed if 'FROM "wyre".zone_mro' in s]
    assert name_queries == [(MRO_IDS,)]
    assert not [s for (s, _p) in cur.executed if 'FROM "wyre".zone_pop' in s]
    success = [m for (k, _t, m) in plugin.iface.messageBar().messages if k == "success"]
    assert success == [bp18.tr(
        "conn.connected_nominal", login=LOGIN,
        scope=bp18.tr("scope.mro", count=10, names="Anderlecht, Etterbeek, Ixelles… (+7)")
        + " / " + bp18.tr("scope.write_all"),
    )]
    session = [m for m in _logs() if m.startswith("Perimetre de session")]
    assert len(session) == 1 and all(name in session[0] for name in MRO_NAMES)


def test_connexion_compte_sans_perimetre(bp18, monkeypatch, tmp_path):
    cur = _StrictCursor(scope_row=EMPTY_ROW_RAW)
    plugin, _calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert bn.scope_kind(plugin._scope) == "none"
    assert not [s for (s, _p) in cur.executed if "wyre.zone_" in s]
    success = [m for (k, _t, m) in plugin.iface.messageBar().messages if k == "success"]
    assert success == [bp18.tr("conn.connected_nominal", login=LOGIN, scope=bp18.tr("scope.none"))]
