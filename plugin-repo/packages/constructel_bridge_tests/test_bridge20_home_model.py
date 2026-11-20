"""Bridge 2.0, tache 3 (accueil v2, spec § 6.2, § 6.4, § 6.6) : modele de
l'ecran sans Qt (``bridge_home_model``) -- perimetre multiple, couches
communes seules, pastille du Check-in. Les tests de forme (champs, absence
d'import Qt) restent ici ; ceux du rendu sont en tache 5."""
from __future__ import annotations

import ast
from dataclasses import dataclass, fields
from pathlib import Path

import pytest

from constructel_bridge import bridge_diagnostic as bd
from constructel_bridge import bridge_home_model as hm
from constructel_bridge.bridge_presets import LayerSelection, UserPreset
from constructel_bridge_tests.fakes19 import ORANGE, WYRE

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "constructel_bridge"
PROXIMUS_SCHEMA = "proximus"


@dataclass(frozen=True)
class Counts:
    """Meme forme que bridge_project_init.LoadedCounts (module Qt : importe
    seulement sous la fixture pi ; test_loaded_counts_shape les garde alignes)."""
    per_operator: dict
    common: int
    basemaps: int
    projet: int = 0      # 2.1 : couches de projets metier


def last(*schemas):
    return UserPreset("", tuple(schemas), LayerSelection({}, frozenset()))


def snap(**kw):
    base = dict(connected=True, header="jdoe · 10 MRO", operators=(WYRE, ORANGE), counts=Counts({}, 0, 0),
                labels={"wyre": "Wyre", "orange": "Orange"}, last_selection=None, project_suffix=None,
                last_suffix=False, plugin_summary=bd.PluginSummary(5, 6, 1), plugin_version="2.0.0",
                project_operators=(), login="jdoe")
    return hm.HomeSnapshot(**{**base, **kw})


# --- home_state ------------------------------------------------------------------------


def test_offline_disables_loading_and_projects():
    s = hm.home_state(snap(connected=False, header="", operators=(WYRE,), last_selection=last("wyre")))
    assert s.load_enabled is False and s.message_key == "home.connect_to_see"
    assert s.operators == () and s.preselected == () and s.saved_project_enabled is False
    assert s.loaded_marks == frozenset()


def test_connected_without_operator_allows_common_only():
    s = hm.home_state(snap(operators=()))
    assert s.load_enabled is True and s.message_key == "home.common_only"
    assert s.operators == () and s.preselected == () and s.saved_project_enabled is True


def test_first_open_preselects_first_operator():
    s = hm.home_state(snap())
    assert s.preselected == ("wyre",) and s.message_key == "" and s.operators == (WYRE, ORANGE)
    assert s.load_enabled is True and s.saved_project_enabled is True


def test_last_selection_preselects_its_usable_operators():
    s = hm.home_state(snap(last_selection=last("orange", PROXIMUS_SCHEMA)))
    assert s.preselected == ("orange",)
    assert hm.home_state(snap(last_selection=last())).preselected == ()   # commun seul : choix voulu


def test_preselection_follows_usable_order_not_stored_order():
    assert hm.home_state(snap(last_selection=last("orange", "wyre"))).preselected == ("wyre", "orange")


def test_last_selection_with_no_usable_operator_falls_back_to_first():
    assert hm.home_state(snap(last_selection=last(PROXIMUS_SCHEMA))).preselected == ("wyre",)


def test_preselection_never_leaves_usable_scope():   # Task 1 parked : per_operator hors schemas
    stored = UserPreset("", ("wyre", PROXIMUS_SCHEMA),
                        LayerSelection({"wyre": {"cables"}, PROXIMUS_SCHEMA: {"cables"}}, frozenset()))
    assert hm.home_state(snap(operators=(WYRE,), last_selection=stored)).preselected == ("wyre",)


def test_add_mode_is_gone():
    assert not hasattr(hm.HomeState, "mode") and "mode" not in {f.name for f in fields(hm.HomeState)}


def test_common_layers_alone_have_no_summary_or_mark():
    s = hm.home_state(snap(counts=Counts({}, 7, 0)))
    assert s.summary == () and s.loaded_marks == frozenset()


def test_every_loaded_operator_is_marked_and_summarized_in_load_order():
    s = hm.home_state(snap(counts=Counts({"orange": 9, "wyre": 14}, 2, 3)))
    assert s.loaded_marks == frozenset({"wyre", "orange"})
    assert s.summary == (("Orange", 9), ("Wyre", 14))


def test_operator_outside_scopes_is_summarized_not_selectable():   # K14
    s = hm.home_state(snap(operators=(WYRE,), counts=Counts({"orange": 9}, 0, 0)))
    assert s.operators == (WYRE,) and s.preselected == ("wyre",)
    assert s.summary == (("Orange", 9),) and s.loaded_marks == frozenset()


def test_summary_label_of_an_unknown_schema_is_capitalized():
    s = hm.home_state(snap(labels={}, counts=Counts({PROXIMUS_SCHEMA: 2}, 0, 0)))
    assert s.summary == (("Proximus", 2),)


def test_state_carries_the_checkin_badge():
    checkin = hm.CheckinState(bd.PluginSummary(5, 6, 1), True, False)
    assert hm.home_state(snap(checkin=checkin)).checkin_badge == 3
    assert hm.home_state(snap()).checkin_badge == 0


# --- toggle_operator / select_none -----------------------------------------------------


def test_toggle_operator_keeps_order_and_none_is_empty():
    assert hm.toggle_operator(("orange",), "wyre", ("wyre", "orange")) == ("wyre", "orange")
    assert hm.toggle_operator(("wyre", "orange"), "wyre", ("wyre", "orange")) == ("orange",)
    assert hm.toggle_operator(("orange",), "orange", ("wyre", "orange")) == ()
    assert hm.select_none() == ()


def test_toggle_operator_ignores_a_schema_outside_the_order():
    assert hm.toggle_operator(("wyre",), PROXIMUS_SCHEMA, ("wyre", "orange")) == ("wyre",)


# --- suffix_state ----------------------------------------------------------------------


def test_suffix_forced_with_two_selected():
    assert hm.suffix_state([], ["wyre", "orange"], None, False) == (True, False)
    assert hm.suffix_state([], [], None, True) == (True, True)   # sans operateur : etat stable


def test_suffix_follows_project_then_workstation_choice():
    assert hm.suffix_state([], ["wyre"], None, False) == (False, True)
    assert hm.suffix_state([], ["wyre"], None, True) == (True, True)
    assert hm.suffix_state(["wyre"], ["wyre"], False, True) == (False, True)
    assert hm.suffix_state(["wyre"], ["wyre"], True, False) == (True, True)
    assert hm.suffix_state(("wyre", "wyre"), ["wyre"], None, False) == (False, True)   # doublons : un seul schema


def test_suffix_forced_by_loaded_plus_selected():
    assert hm.suffix_state(["wyre"], ["orange"], False, False) == (True, False)
    assert hm.suffix_state(["wyre", "orange"], ["wyre"], False, False) == (True, False)


# --- checkin_badge ---------------------------------------------------------------------


def test_checkin_badge():
    assert hm.checkin_badge(hm.CheckinState(bd.PluginSummary(5, 6, 1), True, False)) == 3
    assert hm.checkin_badge(None) == 0
    assert hm.checkin_badge(hm.CheckinState(bd.PluginSummary(6, 6, 0), True, True)) == 0


def test_checkin_badge_ignores_absent_extensions():
    assert hm.checkin_badge(hm.CheckinState(bd.PluginSummary(5, 6, 1), None, None)) == 2
    assert hm.checkin_badge(hm.CheckinState(None, False, None)) == 1
    assert hm.checkin_badge(hm.CheckinState(None, None, None)) == 0


# --- messages --------------------------------------------------------------------------


def test_message_keys_and_no_19_alias_left():
    assert (hm.MESSAGE_CONNECT, hm.MESSAGE_COMMON_ONLY) == ("home.connect_to_see", "home.common_only")
    # R2 leve en tache 9 : l'ecran 1.9 est reecrit, ses symboles disparaissent.
    for name in ("SELECTOR_NONE", "SELECTOR_LABEL", "SELECTOR_BUTTONS", "MODE_INIT", "MODE_ADD",
                 "MESSAGE_NO_OPERATOR"):
        assert not hasattr(hm, name), name


def test_suffix_state_takes_a_sequence_of_schemas_only():
    # Plus de cale 1.9 (un schema seul en texte) : l'appelant passe une sequence.
    import inspect
    assert "isinstance" not in inspect.getsource(hm.suffix_state)


# --- forme -----------------------------------------------------------------------------


def test_snapshot_fields():
    names = [f.name for f in fields(hm.HomeSnapshot)]
    assert "last_schema" not in names
    assert names[:12] == ["connected", "header", "operators", "counts", "labels", "last_selection",
                          "project_suffix", "last_suffix", "plugin_summary", "plugin_version",
                          "project_operators", "user_presets"]
    assert names[12:15] == ["checkin", "login", "email"]   # tache 9 : profil du Check-in
    # 2.1 : champs ajoutes en fin, avec defauts (constructeur 2.0 inchange)
    assert names[15:] == ["projets", "capabilities", "nominative", "opened_qgis_project", "operator_code_labels"]


def test_snapshot_login_and_email_default_to_empty():
    snapshot = hm.HomeSnapshot(connected=False, header="", operators=(), counts=Counts({}, 0, 0), labels={},
                               last_selection=None, project_suffix=None, last_suffix=False)
    assert (snapshot.login, snapshot.email) == ("", "")


def test_home_actions_fields():
    assert [f.name for f in fields(hm.HomeActions)] == [
        "snapshot", "connect", "load", "list_projects", "open_project", "diagnostic_inputs",
        "diagnostic_action", "configure_sharing", "make_wizard", "set_language", "save_presets",
        "qgis"]   # 2.1 : facultatif, defaut None


def test_home_state_fields():
    assert [f.name for f in fields(hm.HomeState)] == [
        "load_enabled", "message_key", "operators", "preselected", "loaded_marks", "summary",
        "saved_project_enabled", "checkin_badge",
        "projet_groups", "preselected_projets", "qgis_reason"]   # 2.1 : defauts en fin


def test_home_model_has_no_qt_import():
    tree = ast.parse((PLUGIN_DIR / "bridge_home_model.py").read_text(encoding="utf-8"))
    guarded = {id(n) for block in tree.body if isinstance(block, ast.If) and getattr(block.test, "id", "") == "TYPE_CHECKING"
               for n in ast.walk(block)}
    modules = {(n.module or "") if isinstance(n, ast.ImportFrom) else a.name
               for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) and id(n) not in guarded
               for a in n.names}
    # 2.1 : bridge_projets est lui-meme sans Qt (test_bridge21_projets).
    assert modules == {"__future__", "dataclasses", "typing", "bridge_projets"}


@pytest.mark.parametrize("key", ["home.common_only"])
def test_common_only_text_in_three_languages(key):
    import importlib.util
    spec = importlib.util.spec_from_file_location("bridge20_translations", PLUGIN_DIR / "i18n" / "translations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for lang in ("fr", "en", "pt"):
        assert module.TRANSLATIONS[lang][key].strip()
