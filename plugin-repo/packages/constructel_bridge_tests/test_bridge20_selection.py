"""Bridge 2.0, tache 4 (plan 2026-11-18, spec § 6.2) : widget de selection v2.

Les tuiles (operateur / commun) et l'arbre allege de LayerSelectionWidget
tournent ici sur les doublures de fakes_widgets.py ; le rendu Qt reel
(tuile a deux lignes, arbre, theme sombre) reste a la recette manuelle.
Modele des tuiles : test_bridge20_presets.py."""
from __future__ import annotations

import importlib
import sys

import pytest

from constructel_bridge.bridge_presets import TILE_LAYERS, LayerSelection, tile_keys
from constructel_bridge_tests.fakes19 import ORANGE, WYRE, FakeRasterLayer, install_fake_project
from constructel_bridge_tests.fakes_widgets import (
    _CHECK,
    _ITEM_FLAG,
    _ROLE,
    _Button,
    _CheckBox,
    _GroupBox,
    _Item,
    _Label,
    _Layout,
    _Button,
    _ToolButton,
    _Tree,
    _W,
)
from constructel_bridge_tests.test_bridge18_layers import pi  # noqa: F401  (pi = fixture)

MODULE = "constructel_bridge.bridge_layer_selection"


@pytest.fixture
def sel(pi, monkeypatch):  # noqa: F811
    """bridge_layer_selection importe sur les doublures de widgets ; FakeProject
    branche dans bridge_project_init (``sel.project``)."""
    from qgis.PyQt import QtCore, QtWidgets

    for name, fake in (("QWidget", _W), ("QGroupBox", _GroupBox), ("QTreeWidget", _Tree),
                       ("QTreeWidgetItem", _Item), ("QLabel", _Label), ("QPushButton", _Button),
                       ("QCheckBox", _CheckBox), ("QToolButton", _ToolButton), ("QVBoxLayout", _Layout),
                       ("QHBoxLayout", _Layout)):
        monkeypatch.setattr(QtWidgets, name, fake, raising=False)
    for name, enum in (("ItemFlag", _ITEM_FLAG), ("CheckState", _CHECK), ("ItemDataRole", _ROLE)):
        monkeypatch.setattr(QtCore.Qt, name, enum, raising=False)
    monkeypatch.delitem(sys.modules, MODULE, raising=False)
    module = importlib.import_module(MODULE)
    module.project = install_fake_project(pi, monkeypatch)
    yield module
    sys.modules.pop(MODULE, None)


def _checked(item):
    return item.state == _CHECK.Checked


def _greyed(item):
    """Deja chargee (T9-c2b) : desactivee, decochee, non cochable."""
    return item.disabled and item.state == _CHECK.Unchecked and not item.flag_bits & _ITEM_FLAG.ItemIsUserCheckable


def _two(sel):
    widget = sel.LayerSelectionWidget()
    widget.set_operators((WYRE, ORANGE))
    return widget


def _tile_keys_checked(widget, schema, tile):
    return {k for k in tile_keys(tile) if (schema, k) in widget._items and _checked(widget._items[(schema, k)])}


# --- arbre ------------------------------------------------------------------------------


def test_tree_has_one_group_per_tile_and_operator(sel):
    widget = _two(sel)
    names = [sel.tr(f"home.tile.{t}") for t in ("zones", "genie_civil", "cables", "demand_points")]
    commons = [sel.tr(f"home.tile.{t}") for t in ("chantier", "osiris", "cadastre", "urbanisme")]
    expected = [f"{name}  [{label}]" for label in ("Wyre", "Orange") for name in names] + commons
    captions = [group.text(0) for group in widget._tree.children]
    assert len(captions) == len(expected)
    assert all(caption.startswith(prefix) for caption, prefix in zip(captions, expected))
    assert not any("Référence" in c or "Reference" in c for c in captions)
    assert captions[0] == f"{names[0]}  [Wyre]  0/4"


def test_short_labels_and_table_in_tooltip(sel):
    from constructel_bridge.i18n.layer_translations import LAYER_DISPLAY_NAMES

    widget = _two(sel)
    item = widget._items[("wyre", "cables")]
    assert "wyre.cables" not in item.text(0) and "(" not in item.text(0)
    assert item.text(0) == LAYER_DISPLAY_NAMES["cables"][sel.get_language()]     # libelle court, jamais schema.table
    assert item.tip == "wyre.cables"
    assert widget._items[("orange", "cables")].tip == "orange.cables"


def test_item_label_follows_the_layer_translations_then_the_catalog(sel):
    from constructel_bridge.i18n.layer_translations import LAYER_DISPLAY_NAMES

    widget = _two(sel)
    lang = sel.get_language()
    assert widget._items[("wyre", "duct_progress")].text(0) == LAYER_DISPLAY_NAMES["v_duct_progress"][lang]
    assert widget._items[(None, "interventions")].text(0) == "Interventions"      # sans traduction : label_fr du catalogue
    assert widget._items[(None, "wfs_buildings")].tip == "wfs.urbisvector:Buildings"


def test_common_layers_have_a_single_item_under_none(sel):
    widget = _two(sel)
    assert (None, "osiris_frozen") in widget._items and ("wyre", "osiris_frozen") not in widget._items
    assert not any(key in ("v_form_lists", "docs_elements") for _schema, key in widget._items)


def test_expert_layers_hidden_until_requested(sel):
    widget = _two(sel)
    assert ("wyre", "subducts") not in widget._items
    widget._chk_expert.setChecked(True)               # la case du widget pilote set_show_expert
    assert ("wyre", "subducts") in widget._items and not _checked(widget._items[("wyre", "subducts")])
    widget.toggle_tile("genie_civil")
    assert not _checked(widget._items[("wyre", "subducts")])
    assert _checked(widget._items[("wyre", "ducts")])
    widget.set_show_expert(False)
    assert ("wyre", "subducts") not in widget._items and widget._chk_expert.isChecked() is False


def test_manually_ticked_expert_layer_is_kept_while_shown_and_dropped_when_hidden(sel):
    widget = _two(sel)
    widget.set_show_expert(True)
    widget._items[("wyre", "subducts")].setCheckState(0, _CHECK.Checked)
    assert widget.selection().per_operator["wyre"] == frozenset({"subducts"})
    widget.set_show_expert(False)
    assert widget.selection().is_empty()


def test_apply_selection_with_an_expert_layer_reveals_it(sel):
    widget = _two(sel)
    chosen = LayerSelection({"wyre": {"subducts", "cables"}}, set())
    widget.apply_selection(chosen)
    assert widget._chk_expert.isChecked() and widget.selection() == chosen


# --- tuiles -----------------------------------------------------------------------------


def test_tile_toggles_layers_for_every_operator(sel):
    widget = _two(sel)
    widget.toggle_tile("zones")
    zones = {k for k in tile_keys("zones")}
    assert {key for (schema, key), item in widget._items.items() if _checked(item)} == zones
    assert sum(_checked(item) for item in widget._items.values()) == 8
    assert widget.tile_states()["zones"] == "on"
    widget.toggle_tile("zones")
    assert widget.tile_states()["zones"] == "off" and not any(_checked(i) for i in widget._items.values())


def test_tile_buttons_follow_the_state(sel):
    widget = _two(sel)
    tile = widget._tiles["zones"]
    assert tile.checkable and not tile.isChecked()
    widget._tiles["zones"].clicked.emit(False)                          # clic utilisateur
    assert tile.isChecked() and widget.tile_states()["zones"] == "on"
    widget._items[("orange", "zone_drop")].setCheckState(0, _CHECK.Unchecked)
    assert not tile.isChecked() and tile.text().splitlines()[0].startswith("◪")
    widget._tiles["zones"].clicked.emit(False)                          # partielle -> tout cocher
    assert tile.isChecked() and not tile.text().startswith("◪")


def test_tile_text_and_tooltip(sel):
    widget = _two(sel)
    head, count = widget._tiles["cables"].text().split("\n")
    assert sel.tr("home.tile.cables") in head and count == sel.tr("home.tile_layers", count=1)
    assert widget._tiles["genie_civil"].text().split("\n")[1] == sel.tr("home.tile_layers", count=4)   # sans subducts
    tip = widget._tiles["zones"].tooltip
    labels = [widget._items[("wyre", key)].text(0) for key in TILE_LAYERS["zones"]]
    assert tip == ", ".join(labels) and len(labels) == 4
    widget.set_show_expert(True)
    assert widget._tiles["genie_civil"].text().split("\n")[1] == sel.tr("home.tile_layers", count=5)


def test_manual_change_makes_tile_partial_and_calls_on_change(sel):
    widget = _two(sel)
    widget.toggle_tile("zones")
    calls = []
    widget.on_change = lambda: calls.append(1)
    widget._items[("orange", "zone_drop")].setCheckState(0, _CHECK.Unchecked)
    assert widget.tile_states()["zones"] == "partial" and calls == [1]
    widget.on_change = None
    widget._items[("orange", "zone_drop")].setCheckState(0, _CHECK.Checked)   # pas de rappel : aucune erreur
    assert widget.tile_states()["zones"] == "on"


def test_every_mutation_calls_on_change_once(sel):
    widget = _two(sel)
    calls = []
    widget.on_change = lambda: calls.append(1)
    for action in (lambda: widget.toggle_tile("cables"), lambda: widget.set_row("common", True),
                   lambda: widget.set_tiles(["zones"]), lambda: widget.apply_selection(LayerSelection({}, set())),
                   lambda: widget.set_show_expert(True), lambda: widget.set_operators((WYRE,)),
                   lambda: widget._basemap_items["osm"].setCheckState(0, _CHECK.Unchecked),
                   lambda: widget._chk_styles.setChecked(False)):
        calls.clear()
        action()
        assert calls == [1], action


def test_loaded_layers_greyed_per_schema(sel):
    sel.project.add_pg("wyre", "zone_mro")
    widget = _two(sel)
    assert _greyed(widget._items[("wyre", "zone_mro")]) and widget._items[("wyre", "zone_mro")].text(0).endswith("✔")
    assert not widget._items[("orange", "zone_mro")].disabled
    widget.toggle_tile("zones")
    assert widget.selection().per_operator["wyre"] == frozenset({"zone_pop", "zone_distribution", "zone_drop"})
    assert widget.selection().per_operator["orange"] == tile_keys("zones")
    widget._items[("wyre", "zone_mro")].setCheckState(0, _CHECK.Checked)   # Qt le propage depuis un groupe
    assert "zone_mro" not in widget.selection().per_operator["wyre"]
    assert widget.tile_states()["zones"] == "on"


def test_tile_fully_loaded_is_done_and_disabled(sel):
    for key in tile_keys("cables"):
        sel.project.add_pg("wyre", key)
    widget = sel.LayerSelectionWidget()
    widget.set_operators((WYRE,))
    assert widget.tile_states()["cables"] == "done"
    tile = widget._tiles["cables"]
    assert not tile.isEnabled() and tile.text().split("\n")[1] == sel.tr("home.tile_done")
    caption = widget._tree.children[2].text(0)
    assert caption.endswith(sel.tr("home.group_loaded")) and widget._tree.children[2].expanded is False
    widget.toggle_tile("cables")                                      # sans effet
    assert widget.selection().is_empty()


def test_loaded_common_layers_are_greyed_for_all(sel):
    sel.project.add_pg("chantier", "interventions")
    widget = _two(sel)
    assert _greyed(widget._items[(None, "interventions")])
    widget.set_row("common", True)
    assert "interventions" not in widget.selection().common and widget.tile_states()["chantier"] == "on"


def test_no_operator_disables_operator_row(sel):
    widget = sel.LayerSelectionWidget()
    widget.set_operators(())
    states = widget.tile_states()
    assert [states[t] for t in ("zones", "genie_civil", "cables", "demand_points")] == ["disabled"] * 4
    assert all(not widget._tiles[t].isEnabled() for t in ("zones", "genie_civil", "cables", "demand_points"))
    assert all(widget._tiles[t].isEnabled() for t in ("chantier", "osiris", "cadastre", "urbanisme"))
    widget.toggle_tile("zones")
    assert widget.selection().is_empty()
    widget.toggle_tile("chantier")
    assert widget.selection().per_operator == {} and "interventions" in widget.selection().common


def test_new_widget_shows_the_common_tree_before_any_operator(sel):
    widget = sel.LayerSelectionWidget()
    assert [g.text(0).split("  ")[0] for g in widget._tree.children] == [
        sel.tr(f"home.tile.{t}") for t in ("chantier", "osiris", "cadastre", "urbanisme")]


# --- selection --------------------------------------------------------------------------


def test_apply_selection_round_trip(sel):
    widget = _two(sel)
    chosen = LayerSelection({"wyre": {"zone_mro", "cables"}, "orange": {"structures"}}, {"interventions", "wfs_parcels"})
    widget.apply_selection(chosen)
    assert widget.selection() == chosen
    widget.apply_selection(LayerSelection({"orange": {"cables"}}, set()))       # remplace, n'ajoute pas
    assert widget.selection() == LayerSelection({"orange": {"cables"}}, set())


def test_apply_selection_ignores_unknown_operators_and_loaded_layers(sel):
    sel.project.add_pg("wyre", "cables")
    widget = _two(sel)
    widget.apply_selection(LayerSelection({"wyre": {"cables", "ducts"}, "proximus": {"cables"}}, set()))
    assert widget.selection() == LayerSelection({"wyre": {"ducts"}}, set())


def test_selection_never_contains_form_lists_nor_docs(sel):
    widget = _two(sel)
    widget.set_row("operator", True)
    widget.set_row("common", True)
    chosen = widget.selection()
    assert not any({"v_form_lists", "docs_elements"} & keys for keys in chosen.per_operator.values())
    assert not {"v_form_lists", "docs_elements"} & chosen.common


def test_selection_keeps_the_operator_order(sel):
    widget = sel.LayerSelectionWidget()
    widget.set_operators((ORANGE, WYRE))
    widget.toggle_tile("cables")
    assert list(widget.selection().per_operator) == ["orange", "wyre"]


def test_set_tiles_replaces_the_selection(sel):
    widget = _two(sel)
    widget.toggle_tile("cables")
    widget.set_tiles(["zones", "chantier"])
    assert widget.tile_states()["cables"] == "off" and widget.tile_states()["zones"] == "on"
    assert widget.tile_states()["chantier"] == "on"
    assert widget.selection().common == tile_keys("chantier")
    widget.set_tiles([])
    assert widget.selection().is_empty()


def test_row_all_none(sel):
    widget = _two(sel)
    widget.set_row("common", True)
    common = {t for t in ("chantier", "osiris", "cadastre", "urbanisme")}
    assert {t for t, s in widget.tile_states().items() if s == "on"} == common
    assert widget.selection().per_operator == {} and "planning_facades" not in widget.selection().common
    widget.set_row("common", False)
    assert widget.selection().is_empty()
    widget.set_row("operator", True)
    assert {t for t, s in widget.tile_states().items() if s == "on"} == {"zones", "genie_civil", "cables", "demand_points"}
    widget.set_row("operator", False)
    assert widget.selection().is_empty()


def test_row_buttons_are_wired(sel):
    widget = _two(sel)
    widget._row_buttons["common"][0].clicked.emit(False)
    assert widget.tile_states()["osiris"] == "on"
    widget._row_buttons["common"][1].clicked.emit(False)
    assert widget.tile_states()["osiris"] == "off"
    assert widget._row_buttons["operator"][0].text() == sel.tr("home.row_all")
    assert widget._row_buttons["operator"][1].text() == sel.tr("home.row_none")


def test_selection_survives_an_operator_change(sel):
    widget = _two(sel)
    widget.toggle_tile("zones")
    widget._items[("wyre", "cables")].setCheckState(0, _CHECK.Checked)
    widget.set_operators((WYRE, ORANGE, bo_proximus()))
    # la tuile « zones » cochee s'etend au nouvel operateur, le choix manuel reste
    assert _tile_keys_checked(widget, "proximus", "zones") == tile_keys("zones")
    assert _checked(widget._items[("wyre", "cables")])
    widget.set_operators((ORANGE,))
    assert widget.selection() == LayerSelection({"orange": tile_keys("zones")}, set())


def bo_proximus():
    from constructel_bridge import bridge_operators as bo

    return bo.OperatorInfo("PROXIMUS", "Proximus", "proximus")


def test_group_checkbox_checks_its_layers_and_counter_follows(sel):
    widget = _two(sel)
    group = widget._tree.children[0]
    assert group.flag_bits & _ITEM_FLAG.ItemIsUserCheckable and group.state == _CHECK.Unchecked
    group.setCheckState(0, _CHECK.Checked)
    assert _tile_keys_checked(widget, "wyre", "zones") == tile_keys("zones")
    assert group.text(0).endswith("4/4") and widget.tile_states()["zones"] == "partial"
    widget._items[("wyre", "zone_pop")].setCheckState(0, _CHECK.Unchecked)
    assert group.state == _CHECK.PartiallyChecked and group.text(0).endswith("3/4")
    group.setCheckState(0, _CHECK.Unchecked)
    assert widget.selection().is_empty() and group.text(0).endswith("0/4")


# --- fonds de plan et styles (repris de 1.9) --------------------------------------------


def test_basemaps_already_loaded_are_greyed_and_never_selected_again(sel):
    sel.project.addMapLayer(FakeRasterLayer("type=xyz", "OpenStreetMap", "wms"))
    widget = sel.LayerSelectionWidget()
    widget.set_operators((WYRE,))
    assert _greyed(widget._basemap_items["osm"]) and widget._basemap_items["osm"].tip == sel.tr("init.already_loaded")
    defaults = {bm["key"] for bm in sel.BASEMAPS if bm["default"]}
    assert widget.selected_basemaps() == defaults - {"osm"} and widget.want_basemap() is True


def test_nothing_new_to_add_means_no_basemap_wanted(sel):
    for bm in sel.BASEMAPS:
        if bm["default"]:
            sel.project.addMapLayer(FakeRasterLayer("type=xyz", bm["name"], "wms"))
    widget = sel.LayerSelectionWidget()
    widget.set_operators((WYRE,))
    assert widget.selected_basemaps() == set() and widget.want_basemap() is False


def test_loaded_basemap_is_never_selected_even_if_its_box_gets_checked(sel):
    sel.project.addMapLayer(FakeRasterLayer("type=xyz", "OpenStreetMap", "wms"))
    widget = sel.LayerSelectionWidget()
    widget._basemap_items["osm"].setCheckState(0, _CHECK.Checked)
    assert "osm" not in widget.selected_basemaps()


def test_selection_is_empty_by_default_and_styles_default_on(sel):
    widget = sel.LayerSelectionWidget()
    widget.set_operators((WYRE,))
    assert widget.selection().is_empty()                 # v_form_lists : ajoutee par le plan de chargement
    assert widget.want_styles() is True
    widget._chk_styles.setChecked(False)
    assert widget.want_styles() is False


def test_selection_module_is_gone_from_project_init(pi):  # noqa: F811
    for name in ("LayerSelectionWidget", "TEMPLATES", "_INFRA_BASE"):
        assert not hasattr(pi, name)


def test_selection_texts_in_three_languages():
    from constructel_bridge.i18n.translations import TRANSLATIONS

    tiles = ("zones", "genie_civil", "cables", "demand_points", "chantier", "osiris", "cadastre", "urbanisme")
    keys = [f"home.tile.{t}" for t in tiles] + [
        "home.tile_layers", "home.tile_done", "home.group_loaded", "home.row_operator", "home.row_common",
        "home.row_all", "home.row_none", "home.show_expert"]
    for lang in ("en", "fr", "pt"):
        assert all(TRANSLATIONS[lang][key].strip() for key in keys), lang
    fr = TRANSLATIONS["fr"]
    assert [fr[f"home.tile.{t}"] for t in tiles] == [
        "Zones", "Génie civil", "Câbles", "Points de demande", "Chantier", "OSIRIS", "Cadastre UrbIS", "Urbanisme"]
    assert fr["home.tile_layers"].format(count=3) == "3 couches" and fr["home.tile_done"] == "déjà chargé"
    assert fr["home.show_expert"] == "Afficher toutes les couches" and fr["home.row_operator"] == "Par opérateur"
    assert TRANSLATIONS["pt"]["home.tile_done"] == "já carregado"
