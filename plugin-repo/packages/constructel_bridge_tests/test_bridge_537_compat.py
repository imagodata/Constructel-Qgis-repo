"""Compatibilite avec les migrations Farois 536 / 538 (03/11/2026) et le lot 537.

536 : un login nominatif n'ecrit que si son role a network.write ET que la
case « ecriture » (can_write) est cochee sur le MRO ou la POP de la ligne ;
sinon 42501 « Edition refusee: aucun droit d'ecriture sur le perimetre
MRO/POP de wyre.<table> » (ou UPDATE silencieux a 0 ligne via RLS).
538 : plus de TEMPORARY, layer_styles / qgis_projects / map_themes en lecture
seule pour bureau_etudes, administration ESB fermee aux logins.
537 (a venir) : ftth_editor perd les schemas operateurs ; sql/bridge_grants.sql
devient faux.
"""
import importlib.util
import re
from pathlib import Path

import pytest

from constructel_bridge import bridge_nominatif as bn
from constructel_bridge_tests.test_bridge18_scope import (
    DESIGNER,
    VIEWER,
    _layer,
    _plugin,
    _src,
)

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "constructel_bridge"

ADMIN = ("ADMIN", True, True, None, None, None, None)
DESIGNER_NO_WRITE_SCOPE = ("DESIGNER", True, True, ["m1"], [], ["p1"], [])
DESIGNER_POP_WRITE = ("DESIGNER", True, True, ["m1"], [], ["p1", "p2"], ["p2"])
NO_PERIMETER = ("DESIGNER", True, True, [], [], [], [])
# Revue : NULL (tout) et tableau vide (rien) ne se confondent pas, et
# l'ecriture se decide sur les tableaux d'ECRITURE, pas sur la lecture.
READ_ALL_WRITE_NONE = ("X", True, True, None, [], None, [])
MRO_WRITE_ALL = ("X", True, True, ["m1"], None, ["p1"], [])

MSG_536 = (
    "ERROR:  Edition refusee: aucun droit d'ecriture sur le perimetre MRO/POP "
    "de wyre.cables"
)


def _translations():
    spec = importlib.util.spec_from_file_location(
        "bridge537_translations", PLUGIN_DIR / "i18n" / "translations.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TRANSLATIONS


# --- 536 : perimetre d'ecriture ------------------------------------------------


@pytest.mark.parametrize("row, expected", [
    (ADMIN, "all"),
    (DESIGNER, "scoped"),
    (DESIGNER_POP_WRITE, "scoped"),
    (DESIGNER_NO_WRITE_SCOPE, "none"),
    (VIEWER, "none"),
    (NO_PERIMETER, "none"),
    (READ_ALL_WRITE_NONE, "none"),
    (MRO_WRITE_ALL, "all"),
])
def test_write_scope_kind(row, expected):
    assert bn.write_scope_kind(bn.parse_session_scope(row)) == expected


def test_refus_536_traduit_en_message_perimetre(bp18, monkeypatch):
    plugin = _plugin(bp18, monkeypatch, DESIGNER)
    layer = _layer(_src("wyre", "cables"), "Cables")

    plugin._hook_single_layer(layer)
    layer.raiseError.emit(MSG_536)

    assert plugin.iface.messageBar().warnings() == [
        bp18.tr("scope.write_refused_perimeter", layer="Cables")
    ]


def test_message_perimetre_explique_quoi_demander():
    fr = _translations()["fr"]["scope.write_refused_perimeter"]
    assert fr.startswith("Écriture non autorisée sur ce périmètre")
    assert "cocher « écriture » sur votre MRO/POP" in fr
    assert "Farois, Admin › Utilisateurs › Périmètre" in fr
    hint = _translations()["fr"]["scope.write_none"]
    assert "cocher « écriture » sur votre MRO/POP" in hint
    assert "Farois, Admin › Utilisateurs › Périmètre" in hint


def test_avertissement_sans_mro_pop_en_ecriture(bp18, monkeypatch):
    plugin = _plugin(bp18, monkeypatch, DESIGNER_NO_WRITE_SCOPE)

    assert plugin._warn_if_no_write_perimeter() is True

    # Persistant (pushMessage, duration=0) : pas recouvert par le succes.
    assert plugin.iface.messageBar().messages == [
        ("message", "Constructel Bridge", bp18.tr("scope.write_none"))
    ]


def test_avertissement_lecture_tout_mais_ecriture_vide(bp18, monkeypatch):
    plugin = _plugin(bp18, monkeypatch, READ_ALL_WRITE_NONE)

    assert plugin._warn_if_no_write_perimeter() is True


@pytest.mark.parametrize("row, mode", [
    (DESIGNER, bn.AUTH_MODE_NOMINAL),        # MRO coche en ecriture
    (ADMIN, bn.AUTH_MODE_NOMINAL),           # tout le reseau
    (VIEWER, bn.AUTH_MODE_NOMINAL),          # deja signale par le verrou
    (DESIGNER_NO_WRITE_SCOPE, bn.AUTH_MODE_SHARED),  # mode partage
    (NO_PERIMETER, bn.AUTH_MODE_NOMINAL),    # rien a cocher (scope.none)
    (MRO_WRITE_ALL, bn.AUTH_MODE_NOMINAL),   # NULL = tout en ecriture
])
def test_pas_d_avertissement_hors_du_cas_sans_perimetre(bp18, monkeypatch, row, mode):
    plugin = _plugin(bp18, monkeypatch, row, mode=mode)

    assert plugin._warn_if_no_write_perimeter() is False

    assert plugin.iface.messageBar().messages == []


def test_texte_de_session_montre_le_perimetre_d_ecriture(bp18, monkeypatch):
    plugin = _plugin(bp18, monkeypatch, DESIGNER_NO_WRITE_SCOPE)
    assert bp18.tr("scope.write_none_short") in plugin._scope_text()

    plugin = _plugin(bp18, monkeypatch, DESIGNER_POP_WRITE)
    plugin._scope_names = ({"m1": "MRO-1"}, {"p1": "POP-1", "p2": "POP-2"})
    text = plugin._scope_text()
    # 1.8.4 : la dimension d'ecriture vide (MRO) est omise, plus de « [-] ».
    assert text.endswith(" / " + bp18.tr(
        "scope.write_scoped", dims=bp18.tr("scope.pop", count=1, names="POP-2")))
    assert "[" not in text

    plugin = _plugin(bp18, monkeypatch, ADMIN)
    assert plugin._scope_text() == bp18.tr("scope.all")

    plugin = _plugin(bp18, monkeypatch, NO_PERIMETER)
    text = plugin._scope_text()
    assert text.startswith(bp18.tr("scope.none"))
    assert bp18.tr("scope.write_none_short") not in text


# --- 538 : rien de ferme n'est utilise ----------------------------------------


def _plugin_code() -> str:
    parts = []
    for path in sorted(PLUGIN_DIR.rglob("*.py")):
        if "i18n" in path.parts or path.name == "release.py":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.lstrip().startswith("#"):
                parts.append(line)
    return "\n".join(parts)


@pytest.mark.parametrize("pattern", [
    r"\bCREATE\s+(GLOBAL\s+|LOCAL\s+)?TEMP(ORARY)?\b",
    r"\bpg_temp\b",
    r"\besb\.",
    r"\bINTO\s+(TEMP|TEMPORARY)\b",
    # Toute forme qualifiee : public., "public"., {schema}., wyre.
    r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+[^\s;]*?(layer_styles|qgis_projects|map_themes)\b",
    r"saveStyleToDatabase",
])
def test_aucun_usage_ferme_par_la_538(pattern):
    assert not re.search(pattern, _plugin_code(), re.IGNORECASE), pattern


# --- 537 : grants de reference obsoletes ---------------------------------------


def test_bridge_grants_marque_obsolete_et_inactif():
    text = (PLUGIN_DIR / "sql" / "bridge_grants.sql").read_text(encoding="utf-8")
    assert "OBSOLÈTE" in text
    active = [
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("--")
    ]
    assert not [line for line in active if re.match(r"\s*(GRANT|REVOKE)\b", line, re.IGNORECASE)]
