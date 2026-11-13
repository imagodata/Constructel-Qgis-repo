"""Bridge 1.9, tache 9 (spec § 6.1, § 6.2, § 6.4, § 6.6 ; decisions K2, K3,
K14, D11, D12, D15) : ecran d'accueil (solution B) avec la selection actuelle
dans la grande tuile.

  * logique sans Qt (``bridge_home_model``) testee a fond ;
  * ``count_loaded_layers`` / ``_detect_existing_basemaps`` sur le FakeProject
    de fakes19 ;
  * ``LayerSelectionWidget`` (ex-InitProjectDialog) et ``HomeDialog`` tournent
    ici sur des doublures de widgets : le rendu Qt reel (arbre a trois etats,
    mise en page, couleurs) reste a la recette manuelle (tache 10) ;
  * cote plugin, l'ecran est remplace par un enregistreur ; hors connexion,
    des doublures qui echouent si on les touche prouvent que rien ne tente la
    base."""
from __future__ import annotations

import ast
import importlib
import re
import sys
import types
from dataclasses import dataclass, fields
from pathlib import Path

import pytest

from constructel_bridge import bridge_diagnostic as bd
from constructel_bridge import bridge_home_model as hm
from constructel_bridge import bridge_operators as bo
from constructel_bridge_tests.fakes19 import ORANGE, WYRE, FakeLayer, FakeRasterLayer, install_fake_project
from constructel_bridge_tests.test_bridge18_connect import _initgui_ready
from constructel_bridge_tests.test_bridge18_layers import (  # noqa: F401  (pi = fixture)
    LOGIN,
    _FakeIface,
    _nominal_plugin,
    _shared_plugin,
    pi,
)
from constructel_bridge_tests.test_bridge19_checkin import onb  # noqa: F401  (fixture)

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "constructel_bridge"
PROXIMUS = bo.OperatorInfo("PROXIMUS", "Proximus", "proximus")


@dataclass(frozen=True)
class Counts:
    """Meme forme que bridge_project_init.LoadedCounts (module Qt : importe
    seulement sous la fixture pi ; test_loaded_counts_shape les garde alignes)."""
    per_operator: dict
    common: int
    basemaps: int


def snap(**kw):
    base = dict(connected=True, header="jdoe · 10 MRO", operators=(WYRE, ORANGE), counts=Counts({}, 0, 0),
                labels={"wyre": "Wyre", "orange": "Orange"}, last_schema="", project_suffix=None, last_suffix=False,
                plugin_summary=bd.PluginSummary(5, 6, 1), plugin_version="1.9.0", project_operators=())
    return hm.HomeSnapshot(**{**base, **kw})


# --- modele : home_state ----------------------------------------------------------------


def test_offline_state():
    s = hm.home_state(snap(connected=False, header="", operators=()))
    assert (s.selector, s.load_enabled, s.message_key, s.saved_project_enabled) == ("none", False, "home.connect_to_see", False)
    assert s.preselected is None


def test_offline_never_offers_a_stale_operator_list():
    s = hm.home_state(snap(connected=False, header=""))
    assert (s.selector, s.load_enabled, s.preselected, s.loaded_marks) == ("none", False, None, frozenset())


def test_no_operator_state():
    s = hm.home_state(snap(operators=()))
    assert (s.selector, s.load_enabled, s.message_key) == ("none", False, "home.no_operator")
    assert s.saved_project_enabled is True and s.preselected is None


def test_one_operator_is_a_label_two_are_buttons():
    one = hm.home_state(snap(operators=(WYRE,)))
    assert (one.selector, one.load_enabled, one.message_key, one.preselected) == ("label", True, "", WYRE)
    assert hm.home_state(snap()).selector == "buttons"


def test_preselection_and_add_mode():
    s = hm.home_state(snap(last_schema="wyre", counts=Counts({"wyre": 14}, 0, 3)))
    assert s.preselected == WYRE and s.mode == "add"
    assert s.loaded_marks == frozenset({"wyre"}) and s.summary == (("Wyre", 14),)
    assert hm.home_state(snap()).mode == "init"


def test_preselection_falls_back_to_first_operator():
    assert hm.home_state(snap(last_schema="proximus")).preselected == WYRE
    assert hm.home_state(snap(operators=(ORANGE, WYRE), last_schema="wyre")).preselected == WYRE


def test_common_layers_alone_switch_to_add_mode():
    s = hm.home_state(snap(counts=Counts({}, 7, 0)))
    assert s.mode == "add" and s.summary == () and s.loaded_marks == frozenset()


def test_every_loaded_operator_is_marked_and_summarized_in_load_order():
    s = hm.home_state(snap(counts=Counts({"orange": 9, "wyre": 14}, 2, 3)))
    assert s.loaded_marks == frozenset({"wyre", "orange"})
    assert s.summary == (("Orange", 9), ("Wyre", 14))


def test_operator_outside_scopes_is_summarized_not_selectable():   # Review Focus 4, K14
    s = hm.home_state(snap(operators=(WYRE,), counts=Counts({"orange": 9}, 0, 0)))
    assert s.selector == "label" and s.preselected == WYRE
    assert s.summary == (("Orange", 9),) and s.loaded_marks == frozenset()


def test_summary_label_of_an_unknown_schema_is_capitalized():
    s = hm.home_state(snap(labels={}, counts=Counts({"proximus": 2}, 0, 0)))
    assert s.summary == (("Proximus", 2),)


# --- modele : suffix_state -------------------------------------------------------------


def test_suffix_state():
    assert hm.suffix_state([], "wyre", None, False) == (False, True)
    assert hm.suffix_state([], "wyre", None, True) == (True, True)
    assert hm.suffix_state(["wyre"], "wyre", False, True) == (False, True)
    assert hm.suffix_state(["wyre"], "orange", False, False) == (True, False)


def test_suffix_state_project_choice_wins_over_workstation_default():
    assert hm.suffix_state(["wyre"], "wyre", True, False) == (True, True)
    assert hm.suffix_state(("wyre", "wyre"), "wyre", None, False) == (False, True)   # doublons : un seul schema
    assert hm.suffix_state(["wyre", "orange"], "wyre", False, False) == (True, False)


# --- modele : actions -------------------------------------------------------------------


def test_home_actions_fields():
    assert [f.name for f in fields(hm.HomeActions)] == [
        "snapshot", "connect", "load", "open_saved_project", "checkin", "diagnostic", "change_language"]


def test_home_model_has_no_qt_import():
    tree = ast.parse((PLUGIN_DIR / "bridge_home_model.py").read_text(encoding="utf-8"))
    guarded = {id(n) for block in tree.body if isinstance(block, ast.If) and getattr(block.test, "id", "") == "TYPE_CHECKING"
               for n in ast.walk(block)}
    modules = {(n.module or "") if isinstance(n, ast.ImportFrom) else a.name
               for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) and id(n) not in guarded
               for a in n.names}
    assert modules == {"__future__", "dataclasses", "typing", "bridge_operators"}


# --- bridge_project_init : couches et fonds deja charges --------------------------------


def test_loaded_counts_shape(pi):
    assert [f.name for f in fields(pi.LoadedCounts)] == [f.name for f in fields(Counts)]


def test_count_loaded_layers_ignores_layers_outside_the_tree(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    project.add_pg("wyre", "cables")
    project.addMapLayer(FakeLayer.pg("wyre", "zone_pop"), False)   # couche fantome d'un QML : sans noeud
    project.addMapLayer(FakeRasterLayer("type=xyz", "OpenStreetMap", "wms"))
    assert pi.count_loaded_layers(project) == pi.LoadedCounts({"wyre": 1}, 0, 1)


def test_count_loaded_layers_counts_common_layers_and_known_schemas(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    mine = project.layerTreeRoot().addGroup("Mes couches")
    for schema, table in (("orange", "cables"), ("orange", "zone_pop"), ("wyre", "ducts"), ("public", "cables"),
                          ("chantier", "interventions"), ("ref", "v_form_lists"),
                          ("docs", "v_element_documents_list")):
        project.add_pg(schema, table, group=mine)
    wfs = FakeLayer("typename='urbisvector:Buildings' url='https://geoservices-vector.irisnet.be'", "Batiments", "WFS")
    project.addMapLayer(wfs)
    counts = pi.count_loaded_layers(project)
    assert list(counts.per_operator.items()) == [("orange", 2), ("wyre", 1), ("public", 1)]   # ordre de l'arbre
    assert (counts.common, counts.basemaps) == (2, 0)   # v_form_lists et Documents : techniques
    known = pi.count_loaded_layers(project, known={"wyre", "orange"})
    assert known.per_operator == {"orange": 2, "wyre": 1} and known.common == 2


def test_count_loaded_layers_counts_each_basemap_once(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    for name in ("OpenStreetMap", "OpenStreetMap", "UrbIS FR", "Ma photo"):
        project.addMapLayer(FakeRasterLayer("type=xyz", name, "wms"))
    assert pi.count_loaded_layers(project).basemaps == 2


def test_detect_existing_basemaps(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    project.addMapLayer(FakeRasterLayer("type=xyz", "OpenStreetMap", "wms"))
    project.add_pg("wyre", "cables")
    assert pi._detect_existing_basemaps() == {"osm"}


def test_detected_basemaps_are_exactly_those_add_basemaps_skips(pi, monkeypatch):
    # D12 : meme regle de nom que _add_basemaps (couches du projet, arbre ou non).
    project = install_fake_project(pi, monkeypatch)
    project.addMapLayer(FakeRasterLayer("type=xyz", "UrbIS FR", "wms"), False)
    assert pi._detect_existing_basemaps() == {"urbis_fr"}
    pi._add_basemaps(project.layerTreeRoot(), {"urbis_fr", "osm"})
    names = [ly.name() for ly in project.mapLayers().values()]
    assert names.count("UrbIS FR") == 1 and names.count("OpenStreetMap") == 1


# --- doublures de widgets (LayerSelectionWidget, HomeDialog) ------------------------------


class _Sig:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class _W:
    """QWidget factice : etat lisible ; les setters non modelises sont sans effet."""

    def __init__(self, *args, **kwargs):
        self.layout = None
        self.enabled = True
        self.hidden = False
        self.deleted = False
        self.tooltip = ""

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def isEnabled(self):
        return self.enabled

    def setToolTip(self, text):
        self.tooltip = text

    def hide(self):
        self.hidden = True

    def deleteLater(self):
        self.deleted = True

    def __getattr__(self, name):
        if name.startswith("set"):
            return lambda *a, **k: None
        raise AttributeError(name)


class _Label(_W):
    def __init__(self, text="", *args):
        super().__init__(*args)
        self._text = text

    def text(self):
        return self._text

    def setText(self, text):
        self._text = text


class _Button(_Label):
    def __init__(self, text="", *args):
        super().__init__(text, *args)
        self.clicked = _Sig()
        self.checkable = False
        self.checked = False

    def setCheckable(self, checkable):
        self.checkable = bool(checkable)

    def setChecked(self, checked):
        self.checked = bool(checked)

    def isChecked(self):
        return self.checked


class _CheckBox(_Button):
    pass


class _GroupBox(_W):
    def __init__(self, title="", *args):
        super().__init__(*args)
        self.title = title


class _Dialog(_W):
    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self.closed = False

    def accept(self):
        self.closed = True

    def reject(self):
        self.closed = True


class _Layout:
    def __init__(self, parent=None):
        self.items = []
        if parent is not None:
            parent.layout = self

    def addWidget(self, widget, *_args):
        self.items.append(widget)

    def addLayout(self, layout, *_args):
        self.items.append(layout)

    def replaceWidget(self, old, new, *_args):
        self.items[self.items.index(old)] = new

    def __getattr__(self, name):
        if name.startswith(("set", "add")):
            return lambda *a, **k: None
        raise AttributeError(name)


def _widgets(root):
    """Widgets du sous-arbre de *root* (layouts parcourus), dans l'ordre."""
    found = []

    def walk(node):
        if isinstance(node, _Layout):
            for item in node.items:
                walk(item)
            return
        found.append(node)
        if getattr(node, "layout", None) is not None:
            walk(node.layout)

    walk(root)
    return found


def _texts(root):
    return [w.text() for w in _widgets(root) if isinstance(w, _Label)]


# --- LayerSelectionWidget (ex-InitProjectDialog) -----------------------------------------


class _Item:
    def __init__(self, parent, texts):
        self._text = texts[0]
        self.children = []
        self.flag_bits = 0
        self.state = None
        self.disabled = False
        self.value = None
        self.tip = ""
        self.expanded = False
        parent.children.append(self)

    def flags(self):
        return self.flag_bits

    def setFlags(self, flags):
        self.flag_bits = flags

    def setCheckState(self, _column, state):
        self.state = state

    def checkState(self, _column):
        return self.state

    def setToolTip(self, _column, text):
        self.tip = text

    def setDisabled(self, disabled):
        self.disabled = bool(disabled)

    def setData(self, _column, _role, value):
        self.value = value

    def data(self, _column, _role):
        return self.value

    def setExpanded(self, expanded):
        self.expanded = bool(expanded)

    def text(self, _column):
        return self._text


class _Tree(_W):
    def __init__(self, *args):
        super().__init__(*args)
        self.children = []

    def clear(self):
        self.children = []


class _Combo(_W):
    def __init__(self, *args):
        super().__init__(*args)
        self.entries = []
        self.index = -1
        self.currentIndexChanged = _Sig()

    def addItem(self, text, data=None):
        self.entries.append((text, data))
        if self.index < 0:
            self.index = 0

    def setCurrentIndex(self, index):
        if index != self.index:
            self.index = index
            self.currentIndexChanged.emit(index)

    def currentData(self):
        return self.entries[self.index][1]


_ITEM_FLAG = types.SimpleNamespace(ItemIsUserCheckable=0x10, ItemIsAutoTristate=0x40)
_CHECK = types.SimpleNamespace(Unchecked=0, PartiallyChecked=1, Checked=2)
_ROLE = types.SimpleNamespace(UserRole=0x100)


@pytest.fixture
def sel(pi, monkeypatch):
    """bridge_project_init reimporte sur les doublures d'arbre, de liste et de
    widgets ; FakeProject branche (``sel.project``)."""
    from qgis.PyQt import QtCore, QtWidgets

    for name, fake in (("QWidget", _W), ("QGroupBox", _GroupBox), ("QComboBox", _Combo), ("QTreeWidget", _Tree),
                       ("QTreeWidgetItem", _Item), ("QLabel", _Label), ("QPushButton", _Button),
                       ("QCheckBox", _CheckBox), ("QVBoxLayout", _Layout), ("QHBoxLayout", _Layout)):
        monkeypatch.setattr(QtWidgets, name, fake, raising=False)
    for name, enum in (("ItemFlag", _ITEM_FLAG), ("CheckState", _CHECK), ("ItemDataRole", _ROLE)):
        monkeypatch.setattr(QtCore.Qt, name, enum, raising=False)
    monkeypatch.delitem(sys.modules, "constructel_bridge.bridge_project_init", raising=False)
    module = importlib.import_module("constructel_bridge.bridge_project_init")
    module.project = install_fake_project(module, monkeypatch)
    return module


def _checked(item):
    return item.state == _CHECK.Checked


def _greyed(item):
    return item.disabled and _checked(item) and not item.flag_bits & _ITEM_FLAG.ItemIsUserCheckable


def test_selection_greys_operator_layers_of_that_operator_only(sel):
    sel.project.add_pg("wyre", "cables")
    sel.project.add_pg("chantier", "interventions")
    widget = sel.LayerSelectionWidget()
    widget.set_operator("orange", "Orange")
    assert not widget._items["cables"].disabled and "(orange.cables)" in widget._items["cables"].text(0)
    assert _greyed(widget._items["interventions"])
    assert widget._items["interventions"].tip == sel.tr("init.already_loaded")
    assert widget._items["interventions"].text(0).endswith("✔")
    widget.set_operator("wyre", "Wyre")
    assert _greyed(widget._items["cables"]) and "(wyre.cables)" in widget._items["cables"].text(0)
    assert _greyed(widget._items["interventions"])


def test_basemaps_already_loaded_are_greyed_and_never_selected_again(sel):
    sel.project.addMapLayer(FakeRasterLayer("type=xyz", "OpenStreetMap", "wms"))
    widget = sel.LayerSelectionWidget()
    widget.set_operator("wyre", "Wyre")
    assert _greyed(widget._basemap_items["osm"]) and widget._basemap_items["osm"].tip == sel.tr("init.already_loaded")
    defaults = {bm["key"] for bm in sel.BASEMAPS if bm["default"]}
    assert widget.selected_basemaps() == defaults - {"osm"} and widget.want_basemap() is True


def test_nothing_new_to_add_means_no_basemap_wanted(sel):
    for bm in sel.BASEMAPS:
        if bm["default"]:
            sel.project.addMapLayer(FakeRasterLayer("type=xyz", bm["name"], "wms"))
    widget = sel.LayerSelectionWidget()
    widget.set_operator("wyre", "Wyre")
    assert widget.selected_basemaps() == set() and widget.want_basemap() is False


def test_group_captions_carry_operator_badge_and_common_tag(sel):
    widget = sel.LayerSelectionWidget()
    widget.set_operator("orange", "Orange")
    captions = [group.text(0) for group in widget._tree.children]
    assert captions == [
        f"{sel.GROUP_NAMES['Demand Points'][sel.get_language()]}  [Orange]",
        f"{sel.GROUP_NAMES['Infrastructure'][sel.get_language()]}  [Orange]",
        f"{sel.GROUP_NAMES['Zones'][sel.get_language()]}  [Orange]",
        f"Chantier  ({sel.tr('home.common_tag')})",
        f"OSIRIS  ({sel.tr('home.common_tag')})",
        f"Cadastre UrbIS  ({sel.tr('home.common_tag')})",
        f"Urbanisme  ({sel.tr('home.common_tag')})",
        "Référence",
    ]


def test_template_combo_keeps_manual_selection_and_descriptions(sel):
    widget = sel.LayerSelectionWidget()
    widget.set_operator("wyre", "Wyre")
    assert widget._combo.entries == [(sel.tr("init.custom_select"), "custom")] + [
        (tmpl["label"], key) for key, tmpl in sel.TEMPLATES.items()]
    assert widget._combo.currentData() == "infra"
    assert widget._desc_label.text() == sel.TEMPLATES["infra"]["description"]
    assert {k for k, item in widget._items.items() if _checked(item)} == sel.TEMPLATES["infra"]["layers"] & set(widget._items)
    widget._combo.setCurrentIndex(0)
    assert widget._desc_label.text() == sel.tr("init.custom_desc")


def test_template_is_reapplied_when_the_operator_changes(sel):
    sel.project.add_pg("orange", "cables")
    widget = sel.LayerSelectionWidget()
    widget.set_operator("wyre", "Wyre")
    widget._items["subducts"].setCheckState(0, _CHECK.Checked)   # hors modele, oublie au changement
    widget.set_operator("orange", "Orange")
    checked = {k for k, item in widget._items.items() if _checked(item)}
    assert checked == (sel.TEMPLATES["infra"]["layers"] & set(widget._items)) | {"cables"}
    assert _greyed(widget._items["cables"])


def test_manual_selection_survives_an_operator_change(sel):
    sel.project.add_pg("orange", "zone_mro")
    widget = sel.LayerSelectionWidget()
    widget.set_operator("wyre", "Wyre")
    widget._btn_none.clicked.emit(False)
    for key in ("subducts", "incidents"):
        widget._items[key].setCheckState(0, _CHECK.Checked)
    assert widget._combo.currentData() == "custom"
    widget.set_operator("orange", "Orange")
    assert {k for k, item in widget._items.items() if _checked(item)} == {"subducts", "incidents", "zone_mro"}


def test_select_all_and_none_leave_loaded_layers_checked(sel):
    sel.project.add_pg("chantier", "interventions")
    widget = sel.LayerSelectionWidget()
    widget.set_operator("wyre", "Wyre")
    widget._btn_none.clicked.emit(False)
    assert {k for k, item in widget._items.items() if _checked(item)} == {"interventions"}
    assert widget._combo.currentData() == "custom"
    widget._btn_all.clicked.emit(False)
    assert all(_checked(item) for item in widget._items.values())
    assert widget.selected_layers() == set(widget._items)


def test_selected_layers_always_include_form_lists_and_styles_default_on(sel):
    widget = sel.LayerSelectionWidget()
    widget.set_operator("wyre", "Wyre")
    widget._btn_none.clicked.emit(False)
    assert widget.selected_layers() == {"v_form_lists"}
    assert widget.want_styles() is True
    widget._chk_styles.setChecked(False)
    assert widget.want_styles() is False


def test_init_project_dialog_is_gone(pi):
    assert not hasattr(pi, "InitProjectDialog")


# --- HomeDialog -------------------------------------------------------------------------


class _FakeSelection(_W):
    """LayerSelectionWidget factice : operateurs recus, selection imposee."""
    layers = frozenset({"cables", "v_form_lists"})
    basemaps = frozenset({"osm"})
    basemap_wanted = True
    styles = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self.operators = []

    def set_operator(self, schema, label):
        self.operators.append((schema, label))

    def selected_layers(self):
        return set(self.layers)

    def selected_basemaps(self):
        return set(self.basemaps)

    def want_basemap(self):
        return self.basemap_wanted

    def want_styles(self):
        return self.styles


@pytest.fixture
def home(pi, monkeypatch):
    """bridge_home importe sur les doublures de widgets ; LayerSelectionWidget
    remplace par _FakeSelection."""
    from qgis.PyQt import QtWidgets

    for name, fake in (("QDialog", _Dialog), ("QWidget", _W), ("QLabel", _Label), ("QPushButton", _Button),
                       ("QCheckBox", _CheckBox), ("QGroupBox", _GroupBox), ("QVBoxLayout", _Layout),
                       ("QHBoxLayout", _Layout)):
        monkeypatch.setattr(QtWidgets, name, fake, raising=False)
    monkeypatch.delitem(sys.modules, "constructel_bridge.bridge_home", raising=False)
    module = importlib.import_module("constructel_bridge.bridge_home")
    monkeypatch.setattr(module, "LayerSelectionWidget", _FakeSelection)
    yield module
    sys.modules.pop("constructel_bridge.bridge_home", None)


def _open(home, snapshot, load_result=3):
    """HomeDialog sur des actions journalisees (``dialog.log``) ; le test peut
    changer ``dialog.snapshots[-1]`` avant un redessin."""
    log, snapshots, holder = [], [snapshot], {}
    actions = hm.HomeActions(
        snapshot=lambda: log.append("snapshot") or snapshots[-1],
        connect=lambda: log.append("connect"),
        load=lambda *args: log.append(("load",) + args) or load_result,
        open_saved_project=lambda: log.append(("open_saved_project", holder["dialog"].closed)),
        checkin=lambda: log.append("checkin"),
        diagnostic=lambda: log.append("diagnostic"),
        change_language=lambda: log.append("change_language"),
    )
    dialog = home.HomeDialog(actions, None)
    holder["dialog"] = dialog
    dialog.log, dialog.snapshots = log, snapshots
    return dialog


def test_dialog_keeps_its_actions(home):
    dialog = _open(home, snap())
    assert dialog.actions.snapshot() is dialog.snapshots[-1]
    assert dialog.log == ["snapshot", "snapshot"]


def test_offline_screen_disables_operator_choice_loading_and_saved_project(home):
    dialog = _open(home, snap(connected=False, header="", operators=()))
    assert dialog._operator_buttons == {} and dialog._selection is None and dialog._suffix_box is None
    assert dialog._load_button.enabled is False
    assert dialog._message_label.text() == home.tr("home.connect_to_see")
    assert dialog._tiles["project"].enabled is False
    assert all(dialog._tiles[name].enabled for name in ("checkin", "diagnostic", "language"))
    assert (dialog._status_dot.text(), dialog._header_label.text()) == ("●", home.tr("home.not_connected"))
    assert dialog._connect_button.text() == home.tr("home.connect")


def test_connect_button_connects_and_redraws(home):
    dialog = _open(home, snap(connected=False, header="", operators=()))
    old = dialog._body
    dialog.snapshots.append(snap())
    dialog._connect_button.clicked.emit(False)
    assert dialog.log[-2:] == ["connect", "snapshot"]
    assert old.deleted and old.hidden and dialog._body is not old and dialog.closed is False
    assert set(dialog._operator_buttons) == {"wyre", "orange"} and dialog._connect_button is None
    assert (dialog._status_dot.text(), dialog._header_label.text()) == ("●", "jdoe · 10 MRO")


def test_no_operator_message_and_saved_project_still_available(home):
    dialog = _open(home, snap(operators=()))
    assert dialog._message_label.text() == home.tr("home.no_operator")
    assert dialog._load_button.enabled is False and dialog._selection is None
    assert dialog._tiles["project"].enabled is True


def test_single_operator_is_shown_as_text_without_selector(home):
    dialog = _open(home, snap(operators=(WYRE,)))
    assert dialog._operator_buttons == {} and dialog._operator_label.text() == "Wyre"
    assert dialog._selection.operators == [("wyre", "Wyre")]
    assert dialog._load_button.enabled is True
    assert dialog._load_button.text() == home.tr("home.btn_init", operator="Wyre")
    assert dialog._message_label is None


def test_two_operators_buttons_marks_and_switch(home):
    dialog = _open(home, snap(last_schema="orange", counts=Counts({"wyre": 14}, 0, 3)))
    buttons = dialog._operator_buttons
    assert {s: b.text() for s, b in buttons.items()} == {"wyre": "Wyre ✓", "orange": "Orange"}
    assert (buttons["orange"].checked, buttons["wyre"].checked) == (True, False)
    assert all(b.checkable for b in buttons.values())
    assert dialog._load_button.text() == home.tr("home.btn_add", operator="Orange")
    assert (dialog._suffix_box.checked, dialog._suffix_box.enabled) == (True, False)   # Wyre charge + Orange
    assert dialog._summary_label.text() == " · ".join([
        home.tr("home.loaded_operator", operator="Wyre", count=14), home.tr("home.loaded_basemaps", count=3)])

    buttons["wyre"].clicked.emit(True)

    assert (buttons["orange"].checked, buttons["wyre"].checked) == (False, True)
    assert dialog._selection.operators == [("orange", "Orange"), ("wyre", "Wyre")]
    assert (dialog._suffix_box.checked, dialog._suffix_box.enabled) == (False, True)
    assert dialog._load_button.text() == home.tr("home.btn_add", operator="Wyre")


def test_suffix_follows_project_operators_without_layers(home):
    dialog = _open(home, snap(project_operators=("orange",), project_suffix=False))
    assert dialog._selection.operators == [("wyre", "Wyre")]
    assert (dialog._suffix_box.checked, dialog._suffix_box.enabled) == (True, False)


def test_operator_outside_scopes_never_gets_a_button(home):   # K14
    dialog = _open(home, snap(operators=(WYRE, PROXIMUS), counts=Counts({"orange": 9}, 0, 0)))
    assert set(dialog._operator_buttons) == {"wyre", "proximus"}
    assert dialog._summary_label.text() == home.tr("home.loaded_operator", operator="Orange", count=9)
    assert not any("Orange" in text for b in dialog._operator_buttons.values() for text in [b.text()])


def test_common_layers_alone_are_summarized(home):
    dialog = _open(home, snap(counts=Counts({}, 7, 0)))
    assert dialog._summary_label.text() == home.tr("home.loaded_common", count=7)
    assert dialog._load_button.text() == home.tr("home.btn_add", operator="Wyre")


def test_nothing_loaded_shows_no_summary(home):
    dialog = _open(home, snap())
    assert dialog._summary_label is None and home.tr("home.loaded_title") not in _texts(dialog._body)


def test_load_passes_the_selection_and_closes_on_success(home):
    from qgis.core import QgsSettings

    dialog = _open(home, snap())
    dialog._load_button.clicked.emit(False)
    assert dialog.log[-1] == ("load", WYRE, {"cables", "v_form_lists"}, {"osm"}, False, False)
    assert dialog.closed is True
    assert QgsSettings().value(bo.SUFFIX_SETTINGS_KEY) is False   # case modifiable : memorisee


def test_load_without_any_layer_added_keeps_the_screen_open(home):
    dialog = _open(home, snap(), load_result=0)
    dialog._load_button.clicked.emit(False)
    assert dialog.log[-1][0] == "load" and dialog.closed is False


def test_unwanted_basemaps_are_not_passed(home, monkeypatch):
    monkeypatch.setattr(_FakeSelection, "basemap_wanted", False)
    dialog = _open(home, snap())
    dialog._load_button.clicked.emit(False)
    assert dialog.log[-1][3] == set()


def test_ticked_suffix_is_passed_and_remembered(home):
    from qgis.core import QgsSettings

    dialog = _open(home, snap(operators=(WYRE,)))
    dialog._suffix_box.setChecked(True)
    dialog._load_button.clicked.emit(False)
    assert dialog.log[-1][-1] is True and QgsSettings().value(bo.SUFFIX_SETTINGS_KEY) is True


def test_forced_suffix_is_passed_but_never_remembered(home):
    from qgis.core import QgsSettings

    dialog = _open(home, snap(last_schema="orange", counts=Counts({"wyre": 14}, 0, 0)))
    dialog._load_button.clicked.emit(False)
    assert dialog.log[-1][1] == ORANGE and dialog.log[-1][-1] is True
    assert QgsSettings().value(bo.SUFFIX_SETTINGS_KEY) is None


def test_saved_project_closes_the_screen_before_loading(home):
    dialog = _open(home, snap())
    dialog._tiles["project"].clicked.emit(False)
    assert dialog.log[-1] == ("open_saved_project", True)


@pytest.mark.parametrize("tile, action", [("checkin", "checkin"), ("diagnostic", "diagnostic"),
                                          ("language", "change_language")])
def test_tool_tiles_keep_the_screen_open_and_redraw(home, tile, action):
    dialog = _open(home, snap(connected=False, header="", operators=()))
    old = dialog._body
    dialog._tiles[tile].clicked.emit(False)
    assert dialog.log[-2:] == [action, "snapshot"]
    assert dialog.closed is False and old.deleted and dialog._body is not old


def test_selected_operator_survives_a_redraw(home):
    dialog = _open(home, snap())
    dialog._operator_buttons["orange"].clicked.emit(True)
    dialog._tiles["checkin"].clicked.emit(False)
    assert dialog._operator_buttons["orange"].checked and not dialog._operator_buttons["wyre"].checked
    assert dialog._selection.operators == [("orange", "Orange")]


def test_tiles_show_plugin_summary_and_version(home):   # K3
    dialog = _open(home, snap(plugin_summary=bd.PluginSummary(5, 6, 1), plugin_version="1.9.0"))
    checkin = home.tr("home.tile_checkin_sub", active=5, total=6)
    updates = home.tr("home.tile_checkin_updates", count=1)
    assert dialog._tiles["checkin"].text() == f"{home.tr('home.tile_checkin')}\n{checkin} · {updates}"
    assert dialog._tiles["diagnostic"].text() == (
        f"{home.tr('home.tile_diagnostic')}\n{home.tr('home.tile_diagnostic_sub', version='1.9.0')}")
    assert dialog._tiles["project"].text() == f"{home.tr('home.tile_project')}\n{home.tr('home.tile_project_sub')}"
    assert dialog._tiles["language"].text() == f"{home.tr('home.tile_language')}\n{home.tr('home.tile_language_sub')}"


def test_checkin_tile_without_known_update_or_summary(home):
    dialog = _open(home, snap(plugin_summary=bd.PluginSummary(6, 6, 0)))
    assert dialog._tiles["checkin"].text() == (
        f"{home.tr('home.tile_checkin')}\n{home.tr('home.tile_checkin_sub', active=6, total=6)}")
    dialog = _open(home, snap(plugin_summary=None))
    assert dialog._tiles["checkin"].text() == home.tr("home.tile_checkin")


def test_home_modules_use_literal_keys_only():
    for name in ("bridge_home.py", "bridge_home_model.py"):
        src = (PLUGIN_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"\btr\(\s*f[\"']", src) and not re.search(r"\btr\(\s*[a-z_]", src), name


def test_home_texts_in_three_languages():
    from constructel_bridge.i18n.translations import TRANSLATIONS

    fr = TRANSLATIONS["fr"]
    assert fr["menu.init_project"] == "Accueil · charger les couches"
    assert TRANSLATIONS["en"]["menu.init_project"] == "Home · load layers"
    assert TRANSLATIONS["pt"]["menu.init_project"] == "Início · carregar camadas"
    assert fr["home.connect_to_see"] == "Connecte-toi pour voir les opérateurs auxquels tu as accès"
    assert fr["home.suffix_checkbox"] == "Ajouter le nom de l'opérateur aux couches"
    assert fr["home.btn_init"].format(operator="Wyre") == "Initialiser · Wyre"
    assert fr["home.btn_add"].format(operator="Orange") == "Ajouter les couches · Orange"
    # D11 : le resume ne nomme pas le modele.
    assert " · ".join([fr["home.loaded_operator"].format(operator="Wyre", count=14),
                       fr["home.loaded_basemaps"].format(count=3)]) == "✓ Wyre · 14 couches · 3 fonds de plan"
    assert fr["home.tile_checkin_sub"].format(active=5, total=6) + " · " + fr["home.tile_checkin_updates"].format(
        count=1) == "extensions 5/6 · 1 à mettre à jour"


# --- cote plugin ------------------------------------------------------------------------


class _RecordingHome:
    def __init__(self, actions, parent=None):
        self.actions = actions
        self.parent = parent
        self.executed = 0
        self.script = []
        self.loads = []

    def exec(self):
        self.executed += 1
        for step in self.script:
            step(self)
        return 0


@pytest.fixture
def homes(monkeypatch):
    """Ecran d'accueil remplace par un enregistreur ; ``homes.script`` = gestes
    de l'utilisateur joues pendant exec()."""
    created, script = [], []

    class Home(_RecordingHome):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.script = list(script)
            created.append(self)

    fake = types.ModuleType("constructel_bridge.bridge_home")
    fake.HomeDialog = Home
    monkeypatch.setitem(sys.modules, "constructel_bridge.bridge_home", fake)
    return types.SimpleNamespace(created=created, script=script)


def click_load(selected=frozenset({"cables", "v_form_lists"}), basemaps=frozenset({"osm"})):
    """Geste : garder l'operateur preselectionne et cliquer le bouton
    principal, s'il est actif (meme regle que HomeDialog)."""
    def step(dialog):
        state = hm.home_state(dialog.actions.snapshot())
        if state.load_enabled:
            dialog.loads.append(dialog.actions.load(state.preselected, set(selected), set(basemaps), False, False))
    return step


def test_home_opens_offline(bp18, pi, homes, monkeypatch):            # O1
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._connected = False
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: [])
    plugin._on_home()
    assert len(homes.created) == 1 and homes.created[0].executed == 1
    assert homes.created[0].actions.snapshot().connected is False


def test_home_offline_never_touches_the_database(bp18, pi, onb, homes, monkeypatch):  # noqa: F811
    class _NoDb:
        def __getattr__(self, name):
            raise AssertionError(f"base sollicitee hors connexion : {name}")

    def _connect(*_args, **_kwargs):
        raise AssertionError("psycopg2.connect hors connexion")

    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(connect=_connect, Error=Exception))
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._connected = False
    plugin._conn = _NoDb()
    plugin._operators = [WYRE]   # liste d'une session precedente : jamais montree
    homes.script.append(click_load())

    plugin._on_home()

    snapshot = homes.created[0].actions.snapshot()
    state = hm.home_state(snapshot)
    assert (snapshot.connected, snapshot.header, snapshot.operators) == (False, "", ())
    assert (state.selector, state.load_enabled, state.message_key, state.saved_project_enabled) == (
        "none", False, "home.connect_to_see", False)
    assert homes.created[0].loads == []
    assert snapshot.plugin_summary == bd.plugin_summary(plugin._diagnostic_local_checks())


def test_home_snapshot_connected(bp18, pi, monkeypatch, tmp_path):
    from qgis.core import QgsSettings

    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    plugin._operators = [WYRE]
    plugin._operator_registry = {"wyre": WYRE, "orange": ORANGE}
    checks = [bd.Check("plugin", "ok", "diag.plugin_ok", {"name": "A"}),
              bd.Check("plugin", "warning", "diag.plugin_update", {"name": "B"}, "update", "b"),
              bd.Check("plugin", "warning", "diag.plugin_missing", {"name": "C"}, "install", "c"),
              bd.Check("identity", "ok", "diag.identity_ok", {"login": LOGIN})]
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: checks)
    QgsSettings().setValue(bo.LAST_OPERATOR_KEY, "orange")
    QgsSettings().setValue(bo.SUFFIX_SETTINGS_KEY, "true")   # QGIS relit un booleen en texte

    snapshot = plugin.home_snapshot()

    assert snapshot.operators == (WYRE,) and snapshot.header.startswith(LOGIN + " · ")
    assert snapshot.header == f"{LOGIN} · {plugin._scope_text()}"
    assert snapshot.labels == {"wyre": "Wyre", "orange": "Orange"}
    assert (snapshot.last_schema, snapshot.last_suffix, snapshot.project_suffix) == ("orange", True, None)
    assert snapshot.plugin_summary == bd.PluginSummary(2, 3, 1)
    assert snapshot.plugin_version == bp18.PLUGIN_VERSION
    assert snapshot.counts == pi.LoadedCounts({}, 0, 0) and snapshot.project_operators == ()


def test_home_snapshot_reads_the_project(bp18, pi, monkeypatch, tmp_path):
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    plugin._operators = [WYRE]
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: [])
    project = install_fake_project(pi, monkeypatch)
    monkeypatch.setattr(bp18, "QgsProject", pi.QgsProject)
    for schema in ("wyre", "orange", "public"):
        project.add_pg(schema, "cables")
    project.writeEntry("bridge", "operator", "wyre")
    project.writeEntry("bridge", "operator_labels", bo.format_operator_labels({"wyre": "Wyre (projet)"}))
    project.writeEntry("bridge", "operator_suffix", "0")

    snapshot = plugin.home_snapshot()

    # Schemas operateur connus seulement (registre, identite, wyre) : jamais « Public ».
    assert snapshot.counts.per_operator == {"wyre": 1}
    assert snapshot.project_operators == ("wyre",) and snapshot.project_suffix is False
    assert snapshot.labels == {"wyre": "Wyre"}   # registre / operateurs utilisables avant le projet
    plugin._operator_registry = {"wyre": WYRE, "orange": ORANGE}
    assert plugin.home_snapshot().counts.per_operator == {"wyre": 1, "orange": 1}   # K14 : hors scopes resume


def test_home_snapshot_with_unreadable_operator_list_offers_wyre(bp18, pi, monkeypatch, tmp_path):
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    plugin._operators_unavailable = True
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: [])
    snapshot = plugin.home_snapshot()
    assert snapshot.operators == (bo.FALLBACK_OPERATOR,) and snapshot.labels["wyre"] == "Wyre"
    assert hm.home_state(snapshot).preselected == bo.FALLBACK_OPERATOR


def test_home_snapshot_survives_unreadable_plugin_lists(bp18, pi, monkeypatch, tmp_path):
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)

    def boom():
        raise RuntimeError("qgis.utils indisponible")

    monkeypatch.setattr(plugin, "_diagnostic_local_checks", boom)
    assert plugin.home_snapshot().plugin_summary is None


def test_home_actions_are_wired(bp18, monkeypatch):
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    a = plugin._home_actions()
    assert a.snapshot == plugin.home_snapshot and a.load == plugin._load_operator_layers
    assert a.connect == plugin._on_connect and a.checkin == plugin._on_onboarding
    assert a.diagnostic == plugin._on_diagnostic and a.change_language == plugin._on_change_language
    assert a.open_saved_project == plugin._on_load_project


def test_toolbar_click_and_init_menu_open_home(bp18, monkeypatch):    # D15
    iface = _initgui_ready(bp18, monkeypatch)
    plugin = bp18.ConstructelBridgePlugin(iface)
    plugin.initGui()
    assert plugin._tool_button.clicked._slots == [plugin._on_home]
    init = next(a for a in plugin._actions if a.text() == bp18.tr("menu.init_project"))
    assert init.triggered._slots == [plugin._on_home]
    status = next(a for a in plugin._actions if a.text() == bp18.tr("menu.status"))
    assert status.triggered._slots == [plugin._on_diagnostic]
    assert not hasattr(bp18.ConstructelBridgePlugin, "_on_init_project")


def test_load_operator_layers_ignores_an_empty_selection(bp18, pi, monkeypatch, tmp_path):   # K2
    from qgis.core import QgsSettings

    calls = []
    monkeypatch.setattr(pi, "init_project", lambda *a, **k: calls.append(k) or 3)
    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)
    assert plugin._load_operator_layers(WYRE, {"v_form_lists"}, {"osm"}, True) == 0
    assert plugin._load_operator_layers(WYRE, set(), set(), True, suffix=True) == 0
    assert calls == [] and QgsSettings().value(bo.LAST_OPERATOR_KEY) is None
