"""Bridge 2.1, tache 12 : groupes de projets metier dans l'arbre des couches
(LayerSelectionWidget, doublures fakes_widgets)."""
from __future__ import annotations

from constructel_bridge import bridge_projets as pj
from constructel_bridge.bridge_presets import LayerSelection
from constructel_bridge_tests.fakes19 import WYRE
from constructel_bridge_tests.test_bridge18_layers import pi  # noqa: F401  (fixture)
from constructel_bridge_tests.test_bridge20_selection import _checked, _greyed, sel  # noqa: F401  (fixture)

GOFIBER = pj.ProjetInfo("b3", "GOFIBER", "GoFiber", "WYRE", (
    pj.ProjetLayer("geofiber_connectors", "Connecteurs", None, "default", "geom", 10),
    pj.ProjetLayer("geofiber_points", "Points", None, "default", "geom", 20),
))
AUTRE = pj.ProjetInfo("c4", "AUTRE", "Autre", None, (pj.ProjetLayer("t", "T", None, "default", None, 0),))


def _widget(sel, operators=(WYRE,)):  # noqa: F811
    widget = sel.LayerSelectionWidget()
    widget.set_operators(operators)
    calls = []
    widget.on_change = lambda: calls.append(1)
    return widget, calls


def _captions(widget):
    return [group.text(0) for group in widget._tree.children]


def test_ticking_a_projet_checks_all_its_layers(sel):  # noqa: F811
    widget, calls = _widget(sel)
    widget.set_projets((GOFIBER,))
    assert calls == [1]
    items = [widget._items[("projet:GOFIBER", t)] for t in ("geofiber_connectors", "geofiber_points")]
    assert all(_checked(i) for i in items)
    assert widget.selection().projet == {"GOFIBER": frozenset({"geofiber_connectors", "geofiber_points"})}
    assert "GoFiber  2/2" in _captions(widget)


def test_layer_labels_and_tooltips(sel):  # noqa: F811
    widget, _calls = _widget(sel)
    widget.set_projets((GOFIBER,))
    item = widget._items[("projet:GOFIBER", "geofiber_points")]
    assert item.text(0) == "Points" and item.toolTip(0) == "projet.geofiber_points"


def test_untick_removes_group_and_keeps_other_checks(sel):  # noqa: F811
    widget, _calls = _widget(sel)
    widget.set_projets((GOFIBER, AUTRE))
    widget._items[("projet:GOFIBER", "geofiber_points")].setCheckState(0, sel.Qt.CheckState.Unchecked)
    widget.set_projets((GOFIBER,))
    assert ("projet:AUTRE", "t") not in widget._items
    assert not any(c.startswith("Autre") for c in _captions(widget))
    assert widget.selection().projet == {"GOFIBER": frozenset({"geofiber_connectors"})}


def test_loaded_projet_layer_is_grey_and_never_selected(sel):  # noqa: F811
    sel.project.add_pg("projet", "geofiber_points", "Points")
    widget, _calls = _widget(sel)
    widget.set_projets((GOFIBER,))
    item = widget._items[("projet:GOFIBER", "geofiber_points")]
    assert _greyed(item)
    item.state = sel.Qt.CheckState.Checked          # case propagee par Qt depuis le groupe
    assert widget.selection().projet == {"GOFIBER": frozenset({"geofiber_connectors"})}
    assert "GoFiber  1/1" in _captions(widget)


def test_projet_groups_sit_between_operator_and_common_groups(sel):  # noqa: F811
    widget, _calls = _widget(sel)
    widget.set_projets((GOFIBER,))
    captions = _captions(widget)
    i = captions.index("GoFiber  2/2")
    assert all("[Wyre]" in c for c in captions[:i])
    assert captions[i + 1].startswith(sel.tr("home.tile.chantier"))


def test_projet_does_not_change_tile_states(sel):  # noqa: F811
    widget, _calls = _widget(sel)
    before = widget.tile_states()
    widget.set_projets((GOFIBER,))
    assert widget.tile_states() == before


def test_operators_change_keeps_projet_checks(sel):  # noqa: F811
    widget, _calls = _widget(sel)
    widget.set_projets((GOFIBER,))
    widget.set_operators(())
    assert widget.selection().projet == {"GOFIBER": frozenset({"geofiber_connectors", "geofiber_points"})}


def test_apply_selection_restores_projet_layers(sel):  # noqa: F811
    widget, _calls = _widget(sel)
    widget.set_projets((GOFIBER,))
    widget.apply_selection(LayerSelection({}, frozenset(), {"GOFIBER": frozenset({"geofiber_points"}), "HIDDEN": frozenset({"x"})}))
    assert widget.selection().projet == {"GOFIBER": frozenset({"geofiber_points"})}


def test_set_tiles_keeps_projet_checks(sel):  # noqa: F811
    widget, _calls = _widget(sel)
    widget.set_projets((GOFIBER,))
    widget.set_tiles({"cables"})
    assert widget.selection().projet == {"GOFIBER": frozenset({"geofiber_connectors", "geofiber_points"})}


def test_projet_done_when_every_layer_is_loaded(sel):  # noqa: F811
    sel.project.add_pg("projet", "geofiber_points")
    sel.project.add_pg("projet", "geofiber_connectors")
    widget, _calls = _widget(sel)
    widget.set_projets((GOFIBER,))
    assert widget.projet_done("GOFIBER") and not widget.projet_done("AUTRE")
    assert f"GoFiber  {sel.tr('home.group_loaded')}" in _captions(widget)
    assert widget.selection().projet == {}
