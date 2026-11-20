"""Bridge 2.1, tache 13 : rangee « Projets metier » de l'etape Perimetre
(bridge_home_load.LoadPage, doublures fakes_widgets + vrai widget de selection)."""
from __future__ import annotations

import dataclasses

from constructel_bridge import bridge_home_model as hm
from constructel_bridge import bridge_projets as pj
from constructel_bridge.bridge_presets import LAST_SELECTION_NAME, LayerSelection, UserPreset
from constructel_bridge_tests.fakes19 import ORANGE, WYRE
from constructel_bridge_tests.test_bridge18_layers import pi  # noqa: F401  (fixture)
from constructel_bridge_tests.test_bridge20_home_model import Counts, snap
from constructel_bridge_tests.test_bridge20_load_page import _checked_buttons, _loads, load  # noqa: F401  (fixture)

FULL = pj.ProjetCapabilities(True, True, True, True, True, True, True)
GOFIBER = pj.ProjetInfo("b3", "GOFIBER", "GoFiber", "WYRE", (
    pj.ProjetLayer("geofiber_connectors", "Connecteurs", None, "default", "geom", 10),
    pj.ProjetLayer("geofiber_points", "Points", None, "default", "geom", 20),
))
ORFEO = pj.ProjetInfo("o", "ORFEO", "Orfeo", "ORANGE", (pj.ProjetLayer("t", "T", None, "default", None, 0),))
LIBRE = pj.ProjetInfo("l", "LIBRE", "Libre", None, (pj.ProjetLayer("u", "U", None, "default", None, 0),))
LABELS = (("WYRE", "Wyre"), ("ORANGE", "Orange"))


def _last(schemas=(), projets=None):
    return UserPreset(LAST_SELECTION_NAME, tuple(schemas), LayerSelection({}, frozenset(), projets or {}))


def _open(load, **kw):  # noqa: F811
    kw.setdefault("last_selection", _last(("wyre",)))
    kw.setdefault("projets", (GOFIBER, ORFEO, LIBRE))
    kw.setdefault("capabilities", FULL)
    kw.setdefault("operator_code_labels", LABELS)
    snapshot = snap(**kw)
    state = hm.home_state(snapshot)
    log, done = [], []
    noop = {f.name: (lambda *a, **k: None) for f in dataclasses.fields(hm.HomeActions)}
    actions = hm.HomeActions(**{**noop, "snapshot": lambda: snapshot,
                                "load": lambda *args: log.append(("load",) + args) or 3,
                                "save_presets": lambda presets: log.append(("save_presets", list(presets)))})
    page = load.LoadPage(snapshot, state, actions, done.append)
    page.log, page.done = log, done
    return page


def _row_texts(page):
    row = page._projets_row
    return [w.text() for w in row.findChildren(object) if hasattr(w, "text")] if row is not None else []


def test_projets_row_hidden_without_projets(load):  # noqa: F811
    assert _open(load, projets=())._projets_row is None
    assert _open(load, capabilities=pj.NO_CAPABILITIES)._projets_row is None
    assert _open(load, connected=False, operators=())._projets_row is None


def test_projets_grouped_under_operator_labels_in_state_order(load):  # noqa: F811
    page = _open(load, operators=(ORANGE, WYRE))
    assert list(page._projet_buttons) == ["ORFEO", "GOFIBER", "LIBRE"]
    texts = _row_texts(page)
    assert texts.index("Orange") < texts.index("Orfeo") < texts.index("Wyre") < texts.index("GoFiber")
    assert texts.index(load.tr("home.projets_no_operator")) < texts.index("Libre")
    assert page._projet_buttons["GOFIBER"].toolTip() == load.tr("home.projet_tooltip", operator="Wyre", count=2)
    assert page._projet_buttons["LIBRE"].toolTip() == load.tr("home.projet_tooltip_none", count=1)


def test_ticking_projet_with_none_operator_loads_it(load):  # noqa: F811
    page = _open(load)
    page._none_button.clicked.emit()
    page._projet_buttons["GOFIBER"].clicked.emit()
    page._load_button.clicked.emit()
    (entry,) = _loads(page)
    operators, selection = entry[1], entry[2]
    assert operators == () and selection.projet == {"GOFIBER": frozenset({"geofiber_connectors", "geofiber_points"})}
    assert page.current_choice().selection.projet == selection.projet


def test_unticking_projet_removes_its_layers(load):  # noqa: F811
    page = _open(load)
    page._projet_buttons["GOFIBER"].clicked.emit()
    page._projet_buttons["GOFIBER"].clicked.emit()
    assert page._selection.selection().projet == {} and not page._projet_buttons["GOFIBER"].checked


def test_projet_with_two_operators_keeps_suffix_rule_unchanged(load):  # noqa: F811
    page = _open(load)
    page._operator_buttons["orange"].clicked.emit()
    assert _checked_buttons(page) == {"wyre", "orange"}
    page._projet_buttons["GOFIBER"].clicked.emit()
    assert page._suffix_box.isChecked() and not page._suffix_box.isEnabled()
    page._operator_buttons["orange"].clicked.emit()
    assert page._suffix_box.isEnabled()


def test_last_choice_rechecks_visible_projets_only(load):  # noqa: F811
    last = _last(("wyre",), {"GOFIBER": frozenset({"geofiber_points"}), "DISPARU": frozenset({"x"})})
    page = _open(load, last_selection=last)
    assert page.chosen_projets() == ("GOFIBER",) and page._projet_buttons["GOFIBER"].checked
    assert page._selection.selection().projet == {"GOFIBER": frozenset({"geofiber_points"})}


def test_preset_rechecks_its_projets(load):  # noqa: F811
    preset = UserPreset("Mon jeu", (), LayerSelection({}, frozenset(), {"ORFEO": frozenset({"t"}), "OLD": frozenset({"z"})}))
    page = _open(load, user_presets=(preset,))
    page._choose_preset(preset)
    assert page.chosen_projets() == ("ORFEO",)
    assert page._selection.selection().projet == {"ORFEO": frozenset({"t"})}


def test_projet_fully_loaded_shows_check_mark(load):  # noqa: F811
    load.project.add_pg("projet", "geofiber_points")
    load.project.add_pg("projet", "geofiber_connectors")
    page = _open(load)
    assert page._projet_buttons["GOFIBER"].text() == "GoFiber ✓"
    assert page._projet_buttons["ORFEO"].text() == "Orfeo"


def test_summary_mentions_projet_layers(load):  # noqa: F811
    snapshot = snap(counts=Counts({}, 0, 0, 3))
    assert load.tr("home.loaded_projets", count=3) in load.summary_text(snapshot, hm.home_state(snapshot))
    snapshot = snap(counts=Counts({}, 0, 0, 1))
    assert load.summary_text(snapshot, hm.home_state(snapshot)) == load.tr("home.loaded_projets_one")


def test_count_label_counts_projet_layers(load):  # noqa: F811
    page = _open(load)
    page._none_button.clicked.emit()
    page._projet_buttons["GOFIBER"].clicked.emit()
    assert page._count_label.text().startswith("2 ")
