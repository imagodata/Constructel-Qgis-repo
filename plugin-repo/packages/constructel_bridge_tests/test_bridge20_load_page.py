"""Bridge 2.0, tache 5 (plan 2026-11-18, spec § 6.2, § 6.3, § 7) : page
« Charger les couches » (bridge_home_load.LoadPage).

La page tourne ici sur les doublures de fakes_widgets.py, avec le vrai
LayerSelectionWidget ; le rendu Qt reel (menu deroulant, ligne repliable,
theme sombre) reste a la recette manuelle. Modele de l'ecran :
test_bridge20_home_model.py ; widget : test_bridge20_selection.py."""
from __future__ import annotations

import dataclasses
import importlib
import sys

import pytest

from constructel_bridge import bridge_home_model as hm
from constructel_bridge.bridge_presets import (
    LAST_SELECTION_KEY,
    LAST_SELECTION_NAME,
    LayerSelection,
    UserPreset,
    presets_from_json,
    tile_keys,
)
from constructel_bridge_tests.fakes19 import ORANGE, WYRE, install_fake_project
from constructel_bridge_tests.fakes_widgets import (
    _CHECK,
    _ITEM_FLAG,
    _ROLE,
    _Button,
    _CheckBox,
    _Dialog,
    _GroupBox,
    _Item,
    _Label,
    _Layout,
    _Menu,
    _ToolButton,
    _Tree,
    _W,
    _texts,
    _widgets,
)
from constructel_bridge_tests.test_bridge18_layers import pi  # noqa: F401  (pi = fixture)
from constructel_bridge_tests.test_bridge20_home_model import Counts, snap

MODULE = "constructel_bridge.bridge_home_load"
MODULES = ("bridge_home", "bridge_home_load", "bridge_layer_selection")
FIRST_USE_TILES = ("zones", "genie_civil", "cables", "demand_points")


class _InputDialog:
    """QInputDialog : getText rend ce que le test a prepare."""
    answer = ("", False)
    asked = []

    @staticmethod
    def getText(*args, **kwargs):
        _InputDialog.asked.append(args)
        return _InputDialog.answer


@pytest.fixture
def load(pi, monkeypatch):  # noqa: F811
    """bridge_home_load (et le vrai widget de selection) importes sur les
    doublures de widgets ; FakeProject branche dans bridge_project_init."""
    from qgis.core import QgsSettings
    from qgis.PyQt import QtCore, QtWidgets

    for name, fake in (("QWidget", _W), ("QFrame", _W), ("QGridLayout", _Layout), ("QDialog", _Dialog),
                       ("QGroupBox", _GroupBox), ("QTreeWidget", _Tree),
                       ("QTreeWidgetItem", _Item), ("QLabel", _Label), ("QPushButton", _Button),
                       ("QCheckBox", _CheckBox), ("QToolButton", _ToolButton), ("QMenu", _Menu),
                       ("QInputDialog", _InputDialog), ("QVBoxLayout", _Layout), ("QHBoxLayout", _Layout)):
        monkeypatch.setattr(QtWidgets, name, fake, raising=False)
    for name, enum in (("ItemFlag", _ITEM_FLAG), ("CheckState", _CHECK), ("ItemDataRole", _ROLE)):
        monkeypatch.setattr(QtCore.Qt, name, enum, raising=False)
    monkeypatch.setattr(QgsSettings, "_store", {})
    monkeypatch.setattr(_InputDialog, "answer", ("", False))
    monkeypatch.setattr(_InputDialog, "asked", [])
    for name in MODULES:
        monkeypatch.delitem(sys.modules, f"constructel_bridge.{name}", raising=False)
    module = importlib.import_module(MODULE)
    module.project = install_fake_project(pi, monkeypatch)
    module.settings = QgsSettings
    yield module
    for name in MODULES:
        sys.modules.pop(f"constructel_bridge.{name}", None)


def _last(schemas=(), per_operator=None, common=()):
    return UserPreset(LAST_SELECTION_NAME, tuple(schemas),
                      LayerSelection(per_operator or {}, frozenset(common)))


def _open(load, load_result=3, **snapshot_kw):
    """LoadPage sur des actions journalisees : ``page.log`` (load, save_presets),
    ``page.done`` (valeurs passees a on_done). Sans ``last_selection`` fourni :
    un dernier choix vide et nomme (rien de coche, ni premiere utilisation)."""
    snapshot_kw.setdefault("last_selection", _last(("wyre",)))
    snapshot = snap(**snapshot_kw)
    state = hm.home_state(snapshot)
    log, done = [], []
    noop = {f.name: (lambda *a, **k: None) for f in dataclasses.fields(hm.HomeActions)}
    actions = hm.HomeActions(**{**noop,
                                "snapshot": lambda: snapshot,
                                "load": lambda *args: log.append(("load",) + args) or load_result,
                                "save_presets": lambda presets: log.append(("save_presets", list(presets)))})
    page = load.LoadPage(snapshot, state, actions, done.append)
    page.log, page.done = log, done
    return page


def _checked_buttons(page):
    return {schema for schema, button in page._operator_buttons.items() if button.checked}


def _loads(page):
    return [entry for entry in page.log if entry[0] == "load"]


def _stored(load):
    return load.settings().value(LAST_SELECTION_KEY, "")


# --- perimetre ----------------------------------------------------------------------------


def test_perimeter_is_multi_and_none_is_exclusive(load):
    page = _open(load, last_selection=None)
    assert set(page._operator_buttons) == {"wyre", "orange"} and _checked_buttons(page) == {"wyre"}
    assert page._none_button.text() == load.tr("home.none_operator") and page._none_button.checked is False

    page._operator_buttons["orange"].clicked.emit(False)
    assert _checked_buttons(page) == {"wyre", "orange"} and page._none_button.checked is False
    assert page._selection._operators == (WYRE, ORANGE)
    assert page._suffix_box.visible is True

    page._none_button.clicked.emit(False)
    assert _checked_buttons(page) == set() and page._none_button.checked is True
    assert page._selection._operators == () and page._suffix_box.visible is False
    page._none_button.clicked.emit(False)                          # deja sur Aucun : reste sur Aucun
    assert page._none_button.checked is True


def test_unchecking_last_operator_switches_to_none(load):
    page = _open(load)
    page._operator_buttons["wyre"].clicked.emit(False)
    assert _checked_buttons(page) == set() and page._none_button.checked is True
    assert page._selection._operators == ()
    page._operator_buttons["orange"].clicked.emit(False)           # un operateur : Aucun se decoche
    assert _checked_buttons(page) == {"orange"} and page._none_button.checked is False
    assert page._selection._operators == (ORANGE,)


def test_loaded_operator_is_marked_in_its_button(load):
    page = _open(load, counts=Counts({"wyre": 14}, 0, 0))
    assert page._operator_buttons["wyre"].text() == "Wyre ✓" and page._operator_buttons["orange"].text() == "Orange"


def test_load_button_reads_charger_and_never_names_an_operator(load):
    page = _open(load)
    assert page._load_button.text() == load.tr("home.btn_load")
    assert "Wyre" not in page._load_button.text()
    page._operator_buttons["orange"].clicked.emit(False)
    assert page._load_button.text() == load.tr("home.btn_load")


def test_already_in_the_project_row_uses_the_19_summary_text(load):
    page = _open(load, counts=Counts({"wyre": 14}, 2, 3))
    assert page._summary_label.text() == load.summary_text(page._snapshot, page._state)
    assert page._summary_label.text() == (f"{load.tr('home.loaded_operator', operator='Wyre', count=14)} · "
                                          f"{load.tr('home.loaded_common', count=2)} · "
                                          f"{load.tr('home.loaded_basemaps', count=3)}")
    assert _open(load)._summary_label is None


# --- chargement ---------------------------------------------------------------------------


def test_load_calls_action_with_operators_and_selection(load):
    page = _open(load)
    page._operator_buttons["orange"].clicked.emit(False)
    page._selection.toggle_tile("zones")
    page._load_button.clicked.emit(False)

    (_, operators, selection, basemaps, styles, suffix), = _loads(page)
    assert operators == (WYRE, ORANGE)
    assert selection.layer_count() == 8
    assert selection.per_operator == {"wyre": tile_keys("zones"), "orange": tile_keys("zones")}
    assert basemaps == page._selection.selected_basemaps() and styles is True
    assert suffix is True                                          # deux operateurs : impose (§ 6.4)
    assert page.done == [True]
    stored = presets_from_json(_stored(load))
    assert stored == [UserPreset(LAST_SELECTION_NAME, ("wyre", "orange"), selection)]


def test_load_passes_basemaps_and_styles_choices(load):
    page = _open(load)
    page._selection._basemap_items["osm"].setCheckState(0, _CHECK.Unchecked)
    page._selection._chk_styles.setChecked(False)
    page._load_button.clicked.emit(False)
    (_, _operators, _selection, basemaps, styles, _suffix), = _loads(page)
    assert "osm" not in basemaps and styles is False


def test_load_without_operator_sends_no_suffix(load):
    page = _open(load)
    page._none_button.clicked.emit(False)
    page._selection.toggle_tile("osiris")
    page._load_button.clicked.emit(False)
    (_, operators, selection, _basemaps, _styles, suffix), = _loads(page)
    assert operators == () and suffix is None and selection.common == tile_keys("osiris")
    assert presets_from_json(_stored(load)) == [UserPreset(LAST_SELECTION_NAME, (), selection)]


def test_nothing_added_keeps_window_open(load):
    page = _open(load, load_result=0)
    page._selection.toggle_tile("zones")
    page._suffix_box.setChecked(True)                               # choix change : jamais memorise sans chargement
    page._load_button.clicked.emit(False)
    assert len(_loads(page)) == 1 and page.done == [False]
    assert _stored(load) == "" and load.settings().value(load.SUFFIX_SETTINGS_KEY, None) is None


def test_suffix_is_remembered_only_when_the_person_changed_an_editable_box(load):
    page = _open(load, last_suffix=False)
    assert page._suffix_box.checked is False and page._suffix_box.enabled is True
    page._load_button.clicked.emit(False)                           # inchange : rien de memorise
    assert load.settings().value(load.SUFFIX_SETTINGS_KEY, None) is None

    page = _open(load, last_suffix=False)
    page._suffix_box.setChecked(True)
    page._load_button.clicked.emit(False)
    assert load.settings().value(load.SUFFIX_SETTINGS_KEY, None) is True
    assert _loads(page)[0][-1] is True


def test_imposed_or_project_suffix_is_never_remembered(load):
    two = _open(load)
    two._operator_buttons["orange"].clicked.emit(False)
    assert two._suffix_box.checked is True and two._suffix_box.enabled is False
    two._load_button.clicked.emit(False)
    from_project = _open(load, project_suffix=True)
    assert from_project._suffix_box.checked is True and from_project._suffix_box.enabled is True
    from_project._load_button.clicked.emit(False)
    assert load.settings().value(load.SUFFIX_SETTINGS_KEY, None) is None


def test_counts_of_one_are_singular_in_summaries(load):
    """2.0.2 : « 1 couche », « 1 fond de plan », « ✓ Wyre · 1 couche »,
    « 1 couche commune » ; pluriel sinon (0 compris)."""
    from constructel_bridge.i18n.translations import TRANSLATIONS

    fr = TRANSLATIONS["fr"]
    assert (fr["home.loaded_operator_one"].format(operator="Wyre"), fr["home.loaded_common_one"],
            fr["home.loaded_basemaps_one"]) == ("✓ Wyre · 1 couche", "1 couche commune", "1 fond de plan")
    assert load.load_summary_text(1, 1) == f"{load.tr('home.tile_layer_one')} · {load.tr('home.loaded_basemaps_one')}"
    assert load.load_summary_text(1, 3) == f"{load.tr('home.tile_layer_one')} · {load.tr('home.loaded_basemaps', count=3)}"
    assert load.load_summary_text(4, 1) == f"{load.tr('home.tile_layers', count=4)} · {load.tr('home.loaded_basemaps_one')}"
    assert load.load_summary_text(0, 2) == load.tr("home.load_summary", layers=0, basemaps=2)
    page = _open(load, counts=Counts({"wyre": 1}, 1, 1))
    assert page._summary_label.text() == (f"{load.tr('home.loaded_operator_one', operator='Wyre')} · "
                                          f"{load.tr('home.loaded_common_one')} · "
                                          f"{load.tr('home.loaded_basemaps_one')}")
    page._selection.apply_selection(LayerSelection({}, frozenset()))
    page._selection._items[(None, "interventions")].setCheckState(0, _CHECK.Checked)   # une seule couche
    basemaps = len(page._selection.selected_basemaps())
    assert page._count_label.text() == load.load_summary_text(1, basemaps)
    assert page._count_label.text().startswith(load.tr("home.tile_layer_one") + " · ")


def test_loaded_operators_force_the_suffix_for_a_second_one(load):
    page = _open(load, counts=Counts({"wyre": 14}, 0, 0), last_selection=_last(("orange",)))
    assert _checked_buttons(page) == {"orange"}
    assert page._suffix_box.checked is True and page._suffix_box.enabled is False


# --- ouverture : dernier choix et premiere utilisation -------------------------------------------


def test_last_selection_is_restored_on_open(load):
    last = _last(("orange", "proximus"), {"orange": tile_keys("zones"), "proximus": tile_keys("cables")},
                 tile_keys("osiris"))
    page = _open(load, last_selection=last)
    assert _checked_buttons(page) == {"orange"} and page._selection._operators == (ORANGE,)
    states = page._selection.tile_states()
    assert states["zones"] == "on" and states["osiris"] == "on"
    assert states["cables"] == "off" and states["chantier"] == "off"
    assert page.current_choice() == UserPreset("", ("orange",), LayerSelection(
        {"orange": tile_keys("zones")}, tile_keys("osiris")))


def test_last_selection_of_an_operator_never_leaks_into_another(load):
    last = _last(("orange",), {"orange": tile_keys("zones"), "wyre": tile_keys("cables")})
    page = _open(load, last_selection=last)
    assert page._selection.selection().per_operator == {"orange": tile_keys("zones")}


def test_first_use_ticks_the_four_operator_tiles(load):
    for last in (None, UserPreset("", ("orange",), LayerSelection({}, frozenset()))):   # 2e : repli LAST_OPERATORS
        page = _open(load, last_selection=last)
        states = page._selection.tile_states()
        assert all(states[tile] == "on" for tile in FIRST_USE_TILES)
        assert all(states[tile] == "off" for tile in ("chantier", "osiris", "cadastre", "urbanisme"))
    assert _checked_buttons(page) == {"orange"}                     # le repli suit toujours ses operateurs


def test_first_use_without_operator_ticks_nothing(load):
    page = _open(load, last_selection=None, operators=())
    assert page._none_button.checked is True and page._selection.selection().is_empty()
    assert page._operator_buttons == {}


def test_last_choice_without_operator_stays_in_none(load):
    page = _open(load, last_selection=_last((), common=tile_keys("cadastre")))
    assert page._none_button.checked is True
    assert page._selection.selection() == LayerSelection({}, tile_keys("cadastre"))


# --- presets ------------------------------------------------------------------------------


def _menu_texts(page):
    return [action.text for action in page._presets_menu.actions]


def test_presets_menu_lists_user_presets_then_the_save_entry_and_never_the_last_choice(load):
    mine = UserPreset("Réseau", ("wyre",), LayerSelection({"wyre": tile_keys("cables")}, frozenset()))
    page = _open(load, user_presets=(mine, _last(("wyre",))))
    assert page._presets_button.menu is page._presets_menu
    assert _menu_texts(page) == ["Réseau", load.tr("home.save_preset")]
    assert page._presets_button.text().startswith(load.tr("home.my_presets"))


def test_save_preset_appends_and_saves(load, monkeypatch):
    old = UserPreset("Ancien", ("wyre",), LayerSelection({}, tile_keys("osiris")))
    page = _open(load, user_presets=(old,))
    page._selection.toggle_tile("cables")
    monkeypatch.setattr(_InputDialog, "answer", ("  Mon preset ", True))
    page._presets_menu.actions[-1].triggered.emit(False)

    (_, saved), = [entry for entry in page.log if entry[0] == "save_presets"]
    assert saved[0] == old
    assert saved[1] == UserPreset("Mon preset", ("wyre",), LayerSelection({"wyre": tile_keys("cables")}, frozenset()))
    assert len(saved) == 2
    assert _menu_texts(page) == ["Ancien", "Mon preset", load.tr("home.save_preset")]


def test_saving_under_an_existing_name_replaces_it(load, monkeypatch):
    old = UserPreset("Réseau", ("wyre",), LayerSelection({"wyre": tile_keys("zones")}, frozenset()))
    other = UserPreset("Autre", (), LayerSelection({}, frozenset()))
    page = _open(load, user_presets=(old, other))
    page._selection.toggle_tile("cables")
    monkeypatch.setattr(_InputDialog, "answer", ("Réseau", True))
    page._presets_menu.actions[-1].triggered.emit(False)
    (_, saved), = [entry for entry in page.log if entry[0] == "save_presets"]
    assert [p.name for p in saved] == ["Réseau", "Autre"]
    assert saved[0].selection.per_operator == {"wyre": tile_keys("cables")}
    assert _menu_texts(page).count("Réseau") == 1


@pytest.mark.parametrize("answer", [("", True), ("   ", True), ("Mon preset", False), (LAST_SELECTION_NAME, True)])
def test_save_preset_ignores_empty_cancelled_and_reserved_names(load, monkeypatch, answer):
    page = _open(load)
    monkeypatch.setattr(_InputDialog, "answer", answer)
    page._presets_menu.actions[-1].triggered.emit(False)
    assert [entry for entry in page.log if entry[0] == "save_presets"] == []
    assert _menu_texts(page) == [load.tr("home.save_preset")]
    assert _InputDialog.asked and load.tr("home.save_preset_prompt") in _InputDialog.asked[0]


def test_choosing_a_preset_applies_it(load):
    mine = UserPreset("Mixte", ("wyre", "proximus"),
                      LayerSelection({"wyre": tile_keys("cables"), "proximus": tile_keys("cables")},
                                     tile_keys("cadastre")))
    page = _open(load, user_presets=(mine,), last_selection=_last(("orange",), {"orange": tile_keys("zones")}))
    assert _checked_buttons(page) == {"orange"}
    page._presets_menu.actions[0].triggered.emit(False)

    assert _checked_buttons(page) == {"wyre"} and page._none_button.checked is False   # proximus : inutilisable
    assert page._selection._operators == (WYRE,)
    assert page._selection.selection() == LayerSelection({"wyre": tile_keys("cables")}, tile_keys("cadastre"))


def test_choosing_a_preset_without_operator_switches_to_none(load):
    mine = UserPreset("Communes", (), LayerSelection({}, tile_keys("osiris")))
    page = _open(load, user_presets=(mine,))
    page._presets_menu.actions[0].triggered.emit(False)
    assert _checked_buttons(page) == set() and page._none_button.checked is True
    assert page._selection.selection() == LayerSelection({}, tile_keys("osiris"))


def test_current_choice_is_a_nameless_preset_of_the_page(load):
    page = _open(load)
    page._selection.toggle_tile("zones")
    choice = page.current_choice()
    assert choice.name == "" and choice.schemas == ("wyre",)
    assert choice.selection == LayerSelection({"wyre": tile_keys("zones")}, frozenset())


# --- etat hors connexion, options, resume -----------------------------------------------------


def test_offline_page_disables_everything_but_shows_message(load):
    page = _open(load, connected=False, header="", operators=())
    assert page._load_button.enabled is False
    assert page._message_label.text() == load.tr("home.connect_to_see")
    assert page._none_button.enabled is False and page._presets_button.enabled is False
    assert page._selection.enabled is False and page._operator_buttons == {}


def test_common_only_message_and_loading_stay_enabled(load):
    page = _open(load, operators=(), last_selection=None)
    assert page._message_label.text() == load.tr("home.common_only")
    assert page._load_button.enabled is True and page._none_button.enabled is True
    assert _open(load)._message_label is None


def test_options_row_is_folded_and_holds_basemaps_styles_and_suffix(load):
    page = _open(load)
    assert page._options_toggle.text().endswith(load.tr("home.options")) and page._options_body.visible is False
    inside = _widgets(page._options_body)
    assert page._selection._basemap_tree in inside and page._selection._chk_styles in inside
    assert page._suffix_box in inside
    assert page._selection._basemap_tree not in _widgets(page._selection)       # re-parente dans la page
    page._options_toggle.setChecked(True)
    assert page._options_body.visible is True
    page._options_toggle.setChecked(False)
    assert page._options_body.visible is False


def test_only_the_suffix_hides_without_operator(load):
    page = _open(load)
    page._none_button.clicked.emit(False)
    assert page._suffix_box.visible is False
    inside = _widgets(page._options_body)
    assert page._selection._basemap_tree in inside and page._selection._chk_styles in inside
    assert page._selection.want_basemap() is True and page._selection.want_styles() is True
    page._operator_buttons["wyre"].clicked.emit(False)
    assert page._suffix_box.visible is True


def test_summary_counts_what_will_be_added(load):
    page = _open(load, last_selection=_last(("wyre",)))
    basemaps = len(page._selection.selected_basemaps())
    assert page._count_label.text() == load.tr("home.load_summary", layers=0, basemaps=basemaps)
    page._selection.toggle_tile("zones")
    zones = len(tile_keys("zones"))
    assert page._count_label.text() == load.tr("home.load_summary", layers=zones, basemaps=basemaps)
    page._operator_buttons["orange"].clicked.emit(False)
    assert page._count_label.text() == load.tr("home.load_summary", layers=2 * zones, basemaps=basemaps)
    page._selection.toggle_tile("osiris")
    assert page._count_label.text() == load.tr(
        "home.load_summary", layers=2 * zones + len(tile_keys("osiris")), basemaps=basemaps)
    page._selection._basemap_items["osm"].setCheckState(0, _CHECK.Unchecked)
    assert page._count_label.text() == load.tr(
        "home.load_summary", layers=2 * zones + len(tile_keys("osiris")), basemaps=basemaps - 1)



def test_steps_are_numbered_and_titled_and_the_expert_toggle_sits_on_the_layers_header(load):
    page = _open(load)
    texts = [t for t in _texts(page) if t]
    order = [texts.index(t) for t in ("1", load.tr("home.step_perimeter"), "2", load.tr("home.step_presets"),
                                      "3", load.tr("home.step_layers"))]
    assert order == sorted(order)
    for key in ("home.step_perimeter", "home.step_presets", "home.step_layers"):
        assert not any(ch.isdigit() for ch in load.tr(key))             # le numero n'est jamais dans la traduction
    # « Afficher toutes les couches » : meme ligne que l'en-tete de l'etape 3, avant l'arbre
    selection_layout = page._selection.layout
    header = next(item for item in selection_layout.items
                  if isinstance(item, _Layout) and page._selection._chk_expert in item.items)
    assert [w.text() for w in header.items if isinstance(w, _Label)] == ["3", load.tr("home.step_layers"),
                                                                       load.tr("home.show_expert")]
    assert selection_layout.items.index(header) < selection_layout.items.index(page._selection._tree)


# --- revue finale -----------------------------------------------------------------------------


def _click_box(box, checked):
    """Geste de la personne : la case change, puis ``clicked`` (jamais emis
    par setChecked)."""
    box.setChecked(checked)
    box.clicked.emit(checked)


def test_manual_suffix_choice_survives_a_perimeter_change_while_editable(load):
    # Ledger T5 : une case modifiable cochee ou decochee a la main n'est plus
    # recalculee a chaque changement de perimetre.
    page = _open(load, last_suffix=False)
    assert page._suffix_box.checked is False and page._suffix_box.enabled is True
    _click_box(page._suffix_box, True)
    page._none_button.clicked.emit(False)                            # case masquee, choix garde
    page._operator_buttons["orange"].clicked.emit(False)             # un seul operateur : modifiable
    assert page._suffix_box.checked is True and page._suffix_box.enabled is True
    page._load_button.clicked.emit(False)
    assert _loads(page)[0][-1] is True
    assert load.settings().value(load.SUFFIX_SETTINGS_KEY, None) is True      # change par la personne

    unticked = _open(load, last_suffix=True)
    assert unticked._suffix_box.checked is True
    _click_box(unticked._suffix_box, False)
    unticked._none_button.clicked.emit(False)
    unticked._operator_buttons["wyre"].clicked.emit(False)
    assert unticked._suffix_box.checked is False


def test_imposed_suffix_drops_the_manual_choice(load):
    page = _open(load, last_suffix=False)
    _click_box(page._suffix_box, False)
    page._operator_buttons["orange"].clicked.emit(False)            # deux operateurs : impose
    assert page._suffix_box.checked is True and page._suffix_box.enabled is False
    page._operator_buttons["orange"].clicked.emit(False)            # de nouveau modifiable : valeur proposee
    assert page._suffix_box.checked is False and page._suffix_box.enabled is True
    page = _open(load, last_suffix=False)
    _click_box(page._suffix_box, True)
    page._operator_buttons["orange"].clicked.emit(False)
    page._operator_buttons["orange"].clicked.emit(False)
    assert page._suffix_box.checked is False                         # le choix manuel ne survit pas a l'impose


def test_load_button_is_the_page_default_button(load):
    page = _open(load)
    assert page.default_button() is page._load_button


def test_page_options_round_trip(load):
    page = _open(load, last_suffix=False)
    page._selection.set_basemaps(set())
    page._selection.set_want_styles(False)
    _click_box(page._suffix_box, True)
    options = page.current_options()
    assert options == {"basemaps": set(), "styles": False, "suffix": True}
    snapshot = snap(last_selection=_last(("wyre",)), last_suffix=False)
    noop = {f.name: (lambda *a, **k: None) for f in dataclasses.fields(hm.HomeActions)}
    again = load.LoadPage(snapshot, hm.home_state(snapshot), hm.HomeActions(**noop), lambda _loaded: None,
                          options=options)
    assert again.current_options() == options
    assert again._suffix_box.checked is True and again._selection.want_styles() is False
    assert again._selection.selected_basemaps() == set()
