"""Bridge 2.0, tache 9 (plan 2026-11-18, spec § 6.1, § 6.5, § 7, § 8.3) :
fenetre a barre laterale (bridge_home.HomeDialog) et son cablage dans le
plugin (``_on_home``, ``_home_actions``, ``home_snapshot``, menus, ouverture
au premier setup).

La fenetre tourne sur les doublures de fakes_widgets.py avec les vraies pages
(Charger, Projets, Check-in, Diagnostic) ; seules la QgsTask du Diagnostic et
l'etat des partages (bridge_onboarding) sont factices. Le rendu Qt reel
(largeur de la barre, theme sombre, 1366x768) reste a la recette manuelle
(tache 10). Les pages elles-memes : test_bridge20_load_page.py,
test_bridge20_checkin.py, test_bridge20_projects.py, test_bridge19_diagnostic.py.

Ce fichier reprend aussi les regles des tests 1.9 de HomeDialog
(test_bridge19_home.py, « reecrit en Task 9 ») encore valables."""
from __future__ import annotations

import dataclasses
import importlib
import re
import sys
import types
from pathlib import Path

import pytest

from constructel_bridge import bridge_diagnostic as bd
from constructel_bridge import bridge_home_model as hm
from constructel_bridge import bridge_operators as bo
from constructel_bridge.bridge_presets import (
    LAST_SELECTION_KEY,
    LAST_SELECTION_NAME,
    USER_PRESETS_KEY,
    LayerSelection,
    UserPreset,
    presets_to_json,
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
    _LineEdit,
    _ListWidget,
    _Menu,
    _Sig,
    _Stack,
    _ToolButton,
    _Tree,
    _W,
    _texts,
)
from constructel_bridge_tests.test_bridge18_connect import _initgui_ready, _make_plugin
from constructel_bridge_tests.test_bridge18_layers import (  # noqa: F401  (pi = fixture)
    LOGIN,
    _FakeIface,
    _nominal_plugin,
    pi,
)
from constructel_bridge_tests.test_bridge19_checkin import onb  # noqa: F401  (fixture)
from constructel_bridge_tests.test_bridge20_home_model import Counts, snap

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "constructel_bridge"
MODULES = ("bridge_home", "bridge_home_load", "bridge_home_checkin", "bridge_home_projects",
           "bridge_diagnostic_dialog", "bridge_layer_selection")
PROJECTS = [{"name": "Ixelles", "schema": "wyre", "description": "", "updated": ""}]


class _Task:
    """QgsTask.fromFunction : la sonde reseau du Diagnostic ne tourne jamais."""

    @staticmethod
    def fromFunction(description, function, *args, on_finished=None, **kwargs):
        task = _Task()
        task.description, task.on_finished = description, on_finished
        return task


class _ProjTree(_Tree):
    """QTreeWidget de la page Projets : selection courante et signaux."""

    def __init__(self, *args):
        super().__init__(*args)
        self.current = None
        self.currentItemChanged = _Sig()
        self.itemDoubleClicked = _Sig()

    def select(self, item):
        previous, self.current = self.current, item
        self.currentItemChanged.emit(item, previous)

    def currentItem(self):
        return self.current

    def clear(self):
        super().clear()
        self.current = None


class _InputDialog:
    @staticmethod
    def getText(*_args, **_kwargs):
        return "", False


class _Wizard(_Dialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.finished = _Sig()

    def setWindowFlags(self, flags):
        pass


@pytest.fixture
def home(pi, monkeypatch):  # noqa: F811
    """bridge_home et ses pages importes sur les doublures de widgets ; partages
    (bridge_onboarding) configures ; ``home.tasks`` = sondes du Diagnostic."""
    from qgis import core
    from qgis.core import QgsSettings
    from qgis.PyQt import QtCore, QtWidgets

    tasks = []
    monkeypatch.setattr(core, "QgsTask", _Task, raising=False)
    monkeypatch.setattr(core.QgsApplication, "taskManager",
                        staticmethod(lambda: types.SimpleNamespace(addTask=tasks.append)), raising=False)
    for name, fake in (("QWidget", _W), ("QFrame", _W), ("QDialog", _Dialog), ("QGroupBox", _GroupBox), ("QLabel", _Label),
                       ("QPushButton", _Button), ("QCheckBox", _CheckBox), ("QToolButton", _ToolButton),
                       ("QMenu", _Menu), ("QInputDialog", _InputDialog), ("QLineEdit", _LineEdit),
                       ("QTreeWidget", _ProjTree), ("QTreeWidgetItem", _Item), ("QListWidget", _ListWidget),
                       ("QStackedWidget", _Stack), ("QVBoxLayout", _Layout), ("QHBoxLayout", _Layout),
                       ("QGridLayout", _Layout)):
        monkeypatch.setattr(QtWidgets, name, fake, raising=False)
    for name, enum in (("ItemFlag", _ITEM_FLAG), ("CheckState", _CHECK), ("ItemDataRole", _ROLE),
                       ("TextFormat", types.SimpleNamespace(PlainText=0)),
                       ("WindowType", types.SimpleNamespace(Widget=0))):
        monkeypatch.setattr(QtCore.Qt, name, enum, raising=False)
    monkeypatch.setattr(QgsSettings, "_store", {})
    onboarding = types.ModuleType("constructel_bridge.bridge_onboarding")
    onboarding.resource_sharing_configured = lambda settings=None: True
    onboarding.filtermate_configured = lambda: True
    monkeypatch.setitem(sys.modules, "constructel_bridge.bridge_onboarding", onboarding)
    for name in MODULES:
        monkeypatch.delitem(sys.modules, f"constructel_bridge.{name}", raising=False)
    module = importlib.import_module("constructel_bridge.bridge_home")
    module.project = install_fake_project(pi, monkeypatch)
    module.tasks = tasks
    module.settings = QgsSettings
    yield module
    for name in MODULES:
        sys.modules.pop(f"constructel_bridge.{name}", None)


def _open(home, snapshot=None, load_result=3, projects=PROJECTS, wizard=None, **kwargs):
    """HomeDialog sur des actions journalisees (``dialog.log``) ; le test peut
    ajouter un instantane a ``dialog.snapshots`` avant un redessin."""
    log, snapshots, holder = [], [snapshot if snapshot is not None else snap()], {}

    def open_project(schema, name):
        log.append(("open_project", schema, name, holder["dialog"].closed))
        return True

    def make_wizard(parent):
        log.append(("make_wizard", parent))
        return wizard

    actions = hm.HomeActions(
        snapshot=lambda: log.append("snapshot") or snapshots[-1],
        connect=lambda: log.append("connect"),
        load=lambda *args: log.append(("load",) + args) or load_result,
        list_projects=lambda: log.append("list_projects") or projects,
        open_project=open_project,
        diagnostic_inputs=lambda: log.append("diagnostic_inputs") or (
            "Non connecte.", [bd.Check("identity", "ok", "diag.identity_ok", {"login": "jdoe"})],
            {"host": "h", "port": 1, "cafile": "", "installed_version": "2.0.0"}),
        diagnostic_action=lambda check: log.append(("diagnostic_action", check)) or [],
        configure_sharing=lambda kind: log.append(("configure_sharing", kind)) or "",
        make_wizard=make_wizard,
        set_language=lambda code: log.append(("set_language", code)),
        save_presets=lambda presets: log.append(("save_presets", list(presets))),
    )
    dialog = home.HomeDialog(actions, None, **kwargs)
    holder["dialog"] = dialog
    dialog.log, dialog.snapshots = log, snapshots
    return dialog


def _nav(home):
    return [home.tr("home.nav_load"), home.tr("home.nav_projects"), home.tr("home.nav_checkin"),
            home.tr("home.nav_diagnostic")]


def _current(dialog):
    return dialog._stack.currentWidget()


def _finish_probe(home, task):
    task.on_finished(None, [bd.version_check("2.0.0", "2.0.0"), bd.server_check("h", 1, "ok", "")])


OFFLINE = dict(connected=False, header="", operators=(), login="")


# --- forme de la fenetre --------------------------------------------------------------------


def test_window_title_size_and_pages(home):
    dialog = _open(home)
    assert home.HomeDialog.PAGES == ("load", "projects", "checkin", "diagnostic")
    assert dialog.title == "Constructel Bridge"
    assert dialog.minimum_size == (980, 640) and dialog.size == (1100, 720)


def test_dialog_keeps_its_actions(home):
    dialog = _open(home)
    assert dialog.actions.snapshot() is dialog.snapshots[-1]
    assert dialog.log.count("snapshot") == 2      # une lecture a l'ouverture, une par le test


def test_sidebar_has_four_pages_and_opens_on_requested_page(home):
    dialog = _open(home, page="diagnostic")
    assert dialog._sidebar.rows == _nav(home)
    assert dialog._sidebar.currentRow() == 3
    panel = dialog._pages["diagnostic"]
    assert isinstance(panel, home.DiagnosticPanel) and _current(dialog) is panel
    assert set(dialog._pages) == {"diagnostic"}       # les autres pages attendent d'etre affichees


@pytest.mark.parametrize("page", ["load", False, "inconnue"])
def test_window_opens_on_load_by_default(home, page):
    dialog = _open(home, page=page)
    assert dialog._sidebar.currentRow() == 0 and isinstance(_current(dialog), home.LoadPage)


def test_sidebar_click_shows_the_page(home):
    dialog = _open(home)
    dialog._sidebar.setCurrentRow(2)
    assert isinstance(_current(dialog), home.CheckinPage) and dialog._current == "checkin"
    dialog.show_page("projects")
    assert isinstance(_current(dialog), home.ProjectsPage) and dialog._sidebar.currentRow() == 1


def test_checkin_badge_in_sidebar(home):   # K3 : resume des extensions sur l'accueil
    checkin = hm.CheckinState(bd.PluginSummary(5, 6, 1), True, True)   # 1 a mettre a jour + 1 absente
    dialog = _open(home, snap(checkin=checkin))
    assert dialog._sidebar.rows[2] == f"{home.tr('home.nav_checkin')}  ⚠ 2"
    assert dialog._sidebar.rows[2].endswith("⚠ 2")


@pytest.mark.parametrize("checkin", [None, hm.CheckinState(bd.PluginSummary(6, 6, 0), True, None),
                                     hm.CheckinState(None, None, None)])
def test_checkin_without_anything_to_do_has_no_badge(home, checkin):
    dialog = _open(home, snap(checkin=checkin))
    assert dialog._sidebar.rows[2] == home.tr("home.nav_checkin")


def test_footer_shows_the_plugin_version(home):   # K3 : version visible sur l'accueil
    dialog = _open(home, snap(plugin_version="2.0.0"))
    assert any("2.0.0" in text for text in _texts(dialog._footer))


def test_pages_are_built_lazily(home):
    dialog = _open(home)
    assert set(dialog._pages) == {"load"} and "list_projects" not in dialog.log
    assert "diagnostic_inputs" not in dialog.log and home.tasks == []
    load = dialog._pages["load"]

    dialog.show_page("projects")
    assert dialog.log.count("list_projects") == 1
    dialog.show_page("load")
    dialog.show_page("projects")
    assert dialog._pages["load"] is load and dialog.log.count("list_projects") == 1   # construites une fois


def test_home_module_has_no_hard_coded_background_color():
    src = (PLUGIN_DIR / "bridge_home.py").read_text(encoding="utf-8")
    assert not re.search(r"background", src, re.IGNORECASE)
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", src)


def test_home_modules_use_literal_keys_only():
    src = (PLUGIN_DIR / "bridge_home.py").read_text(encoding="utf-8")
    assert not re.search(r"\btr\(\s*f[\"']", src) and not re.search(r"\btr\(\s*[a-z_]", src)


def test_navigation_texts_in_three_languages():
    from constructel_bridge.i18n.translations import TRANSLATIONS

    for lang in ("fr", "en", "pt"):
        for key in ("home.nav_load", "home.nav_projects", "home.nav_checkin", "home.nav_diagnostic",
                    "home.projects_error"):
            assert TRANSLATIONS[lang][key].strip(), (lang, key)
    assert TRANSLATIONS["fr"]["home.nav_load"] == "Charger les couches"
    assert TRANSLATIONS["fr"]["home.nav_projects"] == "Projet enregistré"


# --- bas de barre : connexion et langue ------------------------------------------------------


def test_offline_footer_offers_connect_and_connect_rerenders(home):
    dialog = _open(home, snap(**OFFLINE))
    assert home.tr("home.not_connected") in _texts(dialog._footer)
    assert dialog._connect_button.text() == home.tr("home.connect")
    old = dialog._pages["load"]
    assert old._load_button.enabled is False

    dialog.snapshots.append(snap())
    dialog._connect_button.clicked.emit(False)

    assert dialog.log[-2:] == ["connect", "snapshot"]
    assert dialog.closed is False and old.deleted and dialog._pages["load"] is not old
    assert dialog._current == "load" and dialog._connect_button is None
    assert "jdoe · 10 MRO" in _texts(dialog._footer)
    page = dialog._pages["load"]
    assert page._load_button.enabled is True
    assert {s for s, b in page._operator_buttons.items() if b.checked} == {"wyre"}   # premier usage (R11)


def test_offline_window_touches_no_database(home):
    # 1.9 : hors connexion, ni choix d'operateur, ni chargement, ni projet
    # enregistre ; Check-in et Diagnostic restent utilisables.
    dialog = _open(home, snap(**OFFLINE))
    load = dialog._pages["load"]
    assert load._operator_buttons == {} and load._load_button.enabled is False
    assert load._message_label.text() == home.tr("home.connect_to_see")
    dialog.show_page("projects")
    assert "list_projects" not in dialog.log
    assert dialog._pages["projects"]._message.text() == home.tr("home.projects_offline")
    dialog.show_page("checkin")
    assert home.tr("home.checkin_profile_offline") in _texts(dialog._pages["checkin"])
    dialog.show_page("diagnostic")
    assert len(home.tasks) == 1 and "connect" not in dialog.log


def test_language_buttons_mark_the_current_language(home):
    from constructel_bridge.i18n import get_language

    dialog = _open(home)
    assert list(dialog._lang_buttons) == ["fr", "en", "pt"]
    assert [b.text() for b in dialog._lang_buttons.values()] == ["FR", "EN", "PT"]
    assert {code for code, b in dialog._lang_buttons.items() if b.checked} == {get_language()}


def test_language_change_keeps_page_and_selection(home):
    dialog = _open(home)
    page = dialog._pages["load"]
    page._operator_buttons["orange"].clicked.emit(False)
    page._operator_buttons["wyre"].clicked.emit(False)
    page._selection.set_tiles(("zones",))
    choice = page.current_choice()
    assert choice == UserPreset("", ("orange",), LayerSelection({"orange": tile_keys("zones")}, frozenset()))

    dialog._lang_buttons["en"].clicked.emit(False)

    assert dialog.log[-2:] == [("set_language", "en"), "snapshot"]
    assert dialog._current == "load" and dialog._pages["load"] is not page and page.deleted
    assert dialog._pages["load"].current_choice() == choice
    assert dialog.closed is False


def test_selection_survives_any_redraw_even_without_operator(home):
    dialog = _open(home)
    page = dialog._pages["load"]
    page._none_button.clicked.emit(False)
    page._selection.set_tiles(("osiris",))
    choice = page.current_choice()
    dialog.render()
    dialog.render()
    assert dialog._pages["load"].current_choice() == choice == UserPreset(
        "", (), LayerSelection({}, tile_keys("osiris")))


def test_offline_choice_is_not_imposed_after_connecting(home):
    # Hors connexion, la page Charger est inerte : son choix vide ne remplace
    # pas le dernier choix du poste une fois connecte.
    last = UserPreset(LAST_SELECTION_NAME, ("orange",), LayerSelection({"orange": tile_keys("cables")}, frozenset()))
    dialog = _open(home, snap(**OFFLINE, last_selection=last))
    dialog.snapshots.append(snap(last_selection=last))
    dialog._connect_button.clicked.emit(False)
    assert dialog._pages["load"].current_choice() == UserPreset("", ("orange",), last.selection)


def test_language_change_on_another_page_stays_there(home):
    dialog = _open(home, page="diagnostic")
    panel = dialog._pages["diagnostic"]
    dialog._lang_buttons["pt"].clicked.emit(False)
    assert dialog._current == "diagnostic" and dialog._pages["diagnostic"] is not panel
    assert panel._closed is True and len(home.tasks) == 2
    assert dialog._sidebar.currentRow() == 3


# --- Charger ------------------------------------------------------------------------------


def test_load_success_closes_window(home):
    dialog = _open(home)
    dialog._pages["load"]._load_button.clicked.emit(False)
    loads = [entry for entry in dialog.log if isinstance(entry, tuple) and entry[0] == "load"]
    assert len(loads) == 1 and loads[0][1] == (WYRE,)
    assert dialog.closed is True and dialog.log.count("snapshot") == 1   # pas de redessin


def test_load_nothing_rerenders(home):   # T9-c1b
    dialog = _open(home, load_result=0)
    old = dialog._pages["load"]
    old._selection.set_tiles(("cables",))
    choice = old.current_choice()
    dialog.snapshots.append(snap(counts=Counts({"wyre": 2}, 0, 1)))   # ex. reorganisation 1.8, fond deja la

    old._load_button.clicked.emit(False)

    page = dialog._pages["load"]
    assert dialog.closed is False and old.deleted and page is not old and dialog._current == "load"
    assert page._summary_label.text() == " · ".join([
        home.tr("home.loaded_operator", operator="Wyre", count=2), home.tr("home.loaded_basemaps_one")])
    assert page.current_choice() == choice


def test_suffix_is_remembered_only_when_the_person_changed_an_editable_box(home):
    # 1.9 (T9-c3) repris sur la fenetre : case non touchee -> rien ;
    # case changee puis chargement reussi -> memorisee ; chargement sans
    # effet -> jamais memorisee.
    key = bo.SUFFIX_SETTINGS_KEY
    dialog = _open(home, snap(operators=(WYRE,)))
    dialog._pages["load"]._load_button.clicked.emit(False)
    assert home.settings().value(key, None) is None

    nothing = _open(home, snap(operators=(WYRE,)), load_result=0)
    nothing._pages["load"]._suffix_box.setChecked(True)
    nothing._pages["load"]._load_button.clicked.emit(False)
    assert home.settings().value(key, None) is None and nothing.closed is False

    changed = _open(home, snap(operators=(WYRE,)))
    changed._pages["load"]._suffix_box.setChecked(True)
    changed._pages["load"]._load_button.clicked.emit(False)
    assert home.settings().value(key, None) is True and changed.closed is True


def test_forced_or_project_suffix_is_never_remembered(home):
    two = _open(home, snap(counts=Counts({"wyre": 14}, 0, 0),
                           last_selection=UserPreset(LAST_SELECTION_NAME, ("orange",), LayerSelection({}, frozenset()))))
    two._pages["load"]._load_button.clicked.emit(False)
    from_project = _open(home, snap(operators=(WYRE,), counts=Counts({"wyre": 3}, 0, 0), project_suffix=True))
    from_project._pages["load"]._load_button.clicked.emit(False)
    assert [e[-1] for e in two.log + from_project.log if isinstance(e, tuple) and e[0] == "load"] == [True, True]
    assert home.settings().value(bo.SUFFIX_SETTINGS_KEY, None) is None


def test_suffix_follows_project_operators_without_layers(home):
    # 1.9 : un operateur inscrit au projet sans couche compte pour le suffixe.
    dialog = _open(home, snap(operators=(WYRE,), project_operators=("orange",), project_suffix=False))
    box = dialog._pages["load"]._suffix_box
    assert (box.checked, box.enabled) == (True, False)


def test_operator_outside_scopes_never_gets_a_button(home):   # K14
    dialog = _open(home, snap(operators=(WYRE,), counts=Counts({"orange": 9}, 0, 0)))
    page = dialog._pages["load"]
    assert set(page._operator_buttons) == {"wyre"}
    assert page._summary_label.text() == home.tr("home.loaded_operator", operator="Orange", count=9)


# --- Projets ------------------------------------------------------------------------------


def test_saved_project_closes_the_window_before_opening(home):   # D11
    dialog = _open(home, page="projects")
    page = dialog._pages["projects"]
    page._tree.select(page._tree.children[0].children[0])
    page._open_button.clicked.emit(False)
    assert dialog.log[-1] == ("open_project", "wyre", "Ixelles", True)


def test_unreadable_project_list_shows_one_message_in_the_page(home):
    # list_projects() -> None : le plugin n'affiche rien (journal) ; la page
    # le dit, une seule fois, sans boite.
    dialog = _open(home, page="projects", projects=None)
    page = dialog._pages["projects"]
    assert page._message.text() == home.tr("home.projects_error")
    assert page._open_button.enabled is False


def test_empty_project_list_says_none_found(home):
    page = _open(home, page="projects", projects=[])._pages["projects"]
    assert page._message.text() == home.tr("project.none_found")


# --- Check-in -----------------------------------------------------------------------------


def test_checkin_change_refreshes_the_badge_without_rebuilding_the_page(home):
    # 1.9 : apres un check-in l'ecran reste ouvert et se met a jour.
    dialog = _open(home, snap(checkin=hm.CheckinState(bd.PluginSummary(5, 6, 0), True, True)), page="checkin")
    page = dialog._pages["checkin"]
    assert dialog._sidebar.rows[2].endswith("⚠ 1")
    dialog.snapshots.append(snap(checkin=hm.CheckinState(bd.PluginSummary(6, 6, 0), True, True)))

    page.on_change()

    assert dialog._sidebar.rows[2] == home.tr("home.nav_checkin")
    assert dialog._pages["checkin"] is page and not page.deleted and dialog.closed is False
    assert dialog._sidebar.currentRow() == 2


def test_checkin_page_gets_the_login_and_email_of_the_snapshot(home):
    dialog = _open(home, snap(login="s.ducournau", email="s.ducournau@constructel.be"), page="checkin")
    texts = " ".join(_texts(dialog._pages["checkin"]))
    assert "s.ducournau" in texts and "s.ducournau@constructel.be" in texts


def test_first_setup_starts_the_wizard_in_the_checkin_page_once(home):
    wizard = _Wizard()
    dialog = _open(home, page="checkin", start_wizard=True, wizard=wizard)
    page = dialog._pages["checkin"]
    assert dialog.log.count(("make_wizard", page)) == 1 and page._wizard is wizard
    wizard.finished.emit(1)
    dialog.render()
    assert [e for e in dialog.log if isinstance(e, tuple) and e[0] == "make_wizard"] == [("make_wizard", page)]


def test_first_setup_triggered_by_the_connect_button_switches_this_window(home):
    # « Se connecter » dans la fenetre declenche le premier setup : le plugin
    # demande le Check-in avec l'assistant (request_page), applique au redessin
    # qui suit la connexion ; jamais une seconde fenetre.
    wizard = _Wizard()
    dialog = _open(home, snap(**OFFLINE), wizard=wizard)
    dialog.actions = dataclasses.replace(
        dialog.actions, connect=lambda: dialog.request_page("checkin", start_wizard=True))
    dialog.snapshots.append(snap())

    dialog._connect_button.clicked.emit(False)

    page = dialog._pages["checkin"]
    assert dialog._current == "checkin" and _current(dialog) is page and page._wizard is wizard
    assert dialog._sidebar.currentRow() == 2
    dialog.render()                                     # redessin suivant : pas de second assistant
    assert [e for e in dialog.log if isinstance(e, tuple) and e[0] == "make_wizard"] == [("make_wizard", page)]


def _hosted_wizard(home, **kwargs):
    wizard = _Wizard()
    dialog = _open(home, snap(**kwargs), page="checkin", start_wizard=True, wizard=wizard)
    return dialog, dialog._pages["checkin"], wizard


def _lock_buttons(dialog):
    return list(dialog._lang_buttons.values()) + ([dialog._connect_button] if dialog._connect_button else [])


def test_hosted_wizard_disables_language_and_connect(home):   # R13 (a1)
    dialog, _page, _wizard = _hosted_wizard(home, **OFFLINE)
    assert dialog._connect_button is not None
    assert all(b.enabled is False for b in _lock_buttons(dialog))
    dialog._lang_buttons["en"].clicked.emit(False)          # meme si le clic passait : ignore
    assert ("set_language", "en") not in dialog.log


def test_wizard_started_from_the_page_disables_language_too(home):   # R13 (a1)
    wizard = _Wizard()
    dialog = _open(home, page="checkin", wizard=wizard)
    assert all(b.enabled for b in _lock_buttons(dialog))
    dialog._pages["checkin"]._wizard_button.clicked.emit(False)
    assert dialog._pages["checkin"]._wizard is wizard
    assert all(b.enabled is False for b in _lock_buttons(dialog))


def test_render_keeps_the_checkin_page_hosting_a_wizard(home):   # R13 (a2)
    dialog, page, wizard = _hosted_wizard(home)
    dialog.show_page("load")
    load = dialog._pages["load"]
    dialog.render()
    assert dialog._pages["checkin"] is page and page._wizard is wizard
    assert not page.deleted and not wizard.deleted and load.deleted
    assert dialog._current == "load" and isinstance(_current(dialog), home.LoadPage)
    dialog.show_page("checkin")
    assert _current(dialog) is page


def test_load_adding_nothing_keeps_the_hosted_wizard(home):   # R13 (a2), chemin _on_load_done(False)
    dialog, page, wizard = _hosted_wizard(home)
    dialog.actions = dataclasses.replace(dialog.actions, load=lambda *a: 0)
    dialog.show_page("load")
    old_load = dialog._pages["load"]
    old_load._load_button.clicked.emit(False)
    assert dialog.closed is False and old_load.deleted and dialog._pages["load"] is not old_load
    assert dialog._pages["checkin"] is page and page._wizard is wizard and not wizard.deleted


def test_buttons_are_enabled_again_when_the_wizard_finishes(home):   # R13 (a1)
    dialog, page, wizard = _hosted_wizard(home, **OFFLINE)
    wizard.finished.emit(1)
    assert page._wizard is None
    assert all(b.enabled for b in _lock_buttons(dialog))
    dialog._lang_buttons["en"].clicked.emit(False)
    assert ("set_language", "en") in dialog.log
    assert dialog._pages["checkin"] is not page               # sans assistant, la page se redessine


def test_request_is_applied_even_if_connect_raises(home):
    dialog = _open(home, snap(**OFFLINE))

    def failing():
        dialog.request_page("checkin")
        raise RuntimeError("connexion impossible")

    dialog.actions = dataclasses.replace(dialog.actions, connect=failing)
    with pytest.raises(RuntimeError):
        dialog._connect_button.clicked.emit(False)
    assert dialog._requested is None and dialog._current == "checkin"


def test_checkin_opened_from_the_menu_does_not_start_the_wizard(home):
    dialog = _open(home, page="checkin", wizard=_Wizard())
    assert not any(isinstance(e, tuple) and e[0] == "make_wizard" for e in dialog.log)


# --- Diagnostic : fin propre de la sonde -----------------------------------------------------


@pytest.mark.parametrize("close", ["reject", "accept", "exec"])
def test_closing_window_closes_diagnostic_panel(home, close):
    # 1.9 (resultat tardif) : la fenetre fermee, de quelque facon que ce
    # soit, le resultat de la sonde ne touche plus les lignes du panneau.
    dialog = _open(home, page="diagnostic")
    panel = dialog._pages["diagnostic"]
    rows = panel._rows
    getattr(dialog, close)()
    assert panel._closed is True
    _finish_probe(home, home.tasks[0])
    assert panel._rows is rows and not rows.deleted


def test_leaving_the_diagnostic_page_closes_its_panel_and_coming_back_restarts_it(home):
    dialog = _open(home, page="diagnostic")
    panel = dialog._pages["diagnostic"]
    dialog.show_page("load")
    assert panel._closed is True
    _finish_probe(home, home.tasks[0])                  # ignore : panneau ferme
    dialog.show_page("diagnostic")
    assert dialog._pages["diagnostic"] is panel and panel._closed is False and len(home.tasks) == 2
    _finish_probe(home, home.tasks[1])
    assert _current(dialog) is panel


def test_render_closes_the_diagnostic_panel_it_replaces(home):
    dialog = _open(home, page="load")
    dialog.show_page("diagnostic")
    panel = dialog._pages["diagnostic"]
    dialog.show_page("load")
    dialog.show_page("diagnostic")                      # rouvert : sonde relancee
    dialog.render()
    assert panel._closed is True and dialog._pages["diagnostic"] is not panel and panel.deleted


def test_dialog_without_diagnostic_page_closes_quietly(home):
    dialog = _open(home)
    dialog.reject()
    assert dialog.closed is True and home.tasks == []


# =====================================================================================
# Cote plugin
# =====================================================================================


class _RecordingHome:
    """HomeDialog du plugin : arguments recus, exec et destruction journalises."""
    created: list = []

    def __init__(self, actions, parent=None, page="load", start_wizard=False):
        self.actions, self.parent, self.page, self.start_wizard = actions, parent, page, start_wizard
        self.events = []
        _RecordingHome.created.append(self)

    def exec(self):
        self.events.append("exec")
        return 0

    def deleteLater(self):
        self.events.append("deleteLater")


@pytest.fixture
def homes(monkeypatch):
    monkeypatch.setattr(_RecordingHome, "created", [])
    fake = types.ModuleType("constructel_bridge.bridge_home")
    fake.HomeDialog = _RecordingHome
    monkeypatch.setitem(sys.modules, "constructel_bridge.bridge_home", fake)
    return _RecordingHome


def _menu_plugin(bp18, monkeypatch):
    iface = _initgui_ready(bp18, monkeypatch)
    plugin = bp18.ConstructelBridgePlugin(iface)
    plugin.initGui()
    opened = []
    monkeypatch.setattr(plugin, "_on_home", lambda *a, **k: opened.append((a, k)))
    return plugin, opened


def _action(bp18, plugin, key):
    return next(a for a in plugin._actions if a.text() == bp18.tr(key))


@pytest.mark.parametrize("key, page", [("menu.onboarding", "checkin"), ("menu.status", "diagnostic"),
                                       ("menu.load_project", "projects"), ("menu.language", "load"),
                                       ("menu.init_project", "load")])
def test_menu_entries_open_home_on_their_page(bp18, monkeypatch, key, page):
    plugin, opened = _menu_plugin(bp18, monkeypatch)
    _action(bp18, plugin, key).triggered.emit(False)    # Qt passe « checked »
    assert opened == [((page,), {})]


def test_toolbar_click_opens_home_on_load(bp18, monkeypatch):   # O1, D15
    plugin, opened = _menu_plugin(bp18, monkeypatch)
    plugin._tool_button.clicked.emit(False)
    assert opened == [(("load",), {})]


def test_separate_dialogs_are_gone(bp18):
    cls = bp18.ConstructelBridgePlugin
    for name in ("_on_load_project", "_on_diagnostic", "_on_onboarding", "_run_onboarding",
                 "_on_change_language", "_on_init_project"):
        assert not hasattr(cls, name), name


def test_on_home_passes_page_and_wizard_and_deletes_the_window(bp18, pi, homes, monkeypatch):  # noqa: F811
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._connected = False
    plugin._on_home("checkin", start_wizard=True)
    plugin._on_home()
    assert [(h.page, h.start_wizard) for h in homes.created] == [("checkin", True), ("load", False)]
    assert [h.events for h in homes.created] == [["exec", "deleteLater"]] * 2   # M5
    assert homes.created[0].parent is plugin.iface.mainWindow()


def test_installer_session_lives_as_long_as_the_window(bp18, pi, homes, monkeypatch):  # noqa: F811
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    seen = []
    monkeypatch.setattr(_RecordingHome, "exec", lambda self: seen.append(plugin._diagnostic_session) or 0)
    plugin._diagnostic_session = object()   # reliquat : jamais repris par la fenetre suivante
    plugin._on_home("diagnostic")
    assert seen == [None] and plugin._diagnostic_session is None


def test_first_setup_opens_home_on_checkin_with_wizard(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsSettings

    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw")
    QgsSettings().remove("constructel_bridge/onboarding_done")
    opened = []
    monkeypatch.setattr(plugin, "_on_home",
                        lambda *a, **k: opened.append((a, k, plugin._wizard_new_user)))

    plugin._auto_connect()                  # sous l'ecran de demarrage : differe (I13)
    assert opened == []
    plugin._startup_interactive()

    assert opened == [(("checkin",), {"start_wizard": True}, False)]


def test_first_setup_once_the_ui_is_ready_opens_home_once(bp18, monkeypatch, tmp_path):   # I-3
    from qgis.core import QgsSettings

    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw")
    QgsSettings().remove("constructel_bridge/onboarding_done")
    opened = []
    monkeypatch.setattr(plugin, "_on_home", lambda *a, **k: opened.append((a, k)))
    plugin._ui_ready = True

    plugin._auto_connect()
    plugin._startup_interactive()           # deja ouvert : jamais deux fois

    assert opened == [(("checkin",), {"start_wizard": True})]


def test_first_setup_while_the_window_is_open_switches_it_instead_of_opening_another(bp18, monkeypatch):
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    requests = []
    plugin._home_dialog = types.SimpleNamespace(request_page=lambda *a, **k: requests.append((a, k)))
    monkeypatch.setattr(plugin, "_on_home", lambda *a, **k: pytest.fail("seconde fenetre"))

    plugin._open_first_setup(True)

    assert requests == [(("checkin",), {"start_wizard": True})] and plugin._wizard_new_user is True


def test_on_home_while_a_window_is_open_shows_the_page_in_it(bp18, homes, monkeypatch):
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    shown = []
    plugin._home_dialog = types.SimpleNamespace(show_page=shown.append)
    plugin._on_home("projects")
    assert shown == ["projects"] and homes.created == []


def test_open_window_is_known_only_while_it_runs(bp18, pi, homes, monkeypatch):  # noqa: F811
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._connected = False
    seen = []
    monkeypatch.setattr(_RecordingHome, "exec", lambda self: seen.append(plugin._home_dialog is self) or 0)
    plugin._on_home()
    assert seen == [True] and plugin._home_dialog is None


def test_first_setup_is_not_replayed_once_done(bp18, monkeypatch, tmp_path):
    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw")
    opened = []
    monkeypatch.setattr(plugin, "_on_home", lambda *a, **k: opened.append((a, k)))
    plugin._auto_connect()
    plugin._startup_interactive()
    assert opened == []


def test_home_actions_are_wired(bp18, monkeypatch):
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    a = plugin._home_actions()
    assert a.snapshot == plugin.home_snapshot and a.load == plugin._load_selection
    assert a.connect == plugin._on_connect and a.save_presets == plugin._save_user_presets
    assert a.list_projects == plugin._list_db_projects and a.open_project == plugin._open_db_project
    assert a.diagnostic_action == plugin._run_diagnostic_action
    assert a.make_wizard == plugin._make_onboarding_wizard and a.set_language == plugin._set_language
    assert a.configure_sharing == plugin._configure_sharing and a.diagnostic_inputs == plugin._diagnostic_inputs


def test_diagnostic_inputs_need_no_connection(bp18, monkeypatch):
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._connected = False
    checks = [bd.Check("identity", "ok", "diag.identity_ok", {"login": "jdoe"})]
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: checks)
    status, local, network = plugin._home_actions().diagnostic_inputs()
    assert status == bp18.tr("status.not_connected") and local == checks
    assert network == {"host": bp18.DEFAULT_HOST, "port": bp18.DEFAULT_PORT,
                       "cafile": str(bp18.ca_bundle_path(PLUGIN_DIR)), "installed_version": bp18.PLUGIN_VERSION}


def test_diagnostic_inputs_survive_unreadable_plugin_lists(bp18, monkeypatch):
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._connected = False

    def boom():
        raise RuntimeError("qgis.utils indisponible")

    monkeypatch.setattr(plugin, "_diagnostic_local_checks", boom)
    assert plugin._diagnostic_inputs()[1] == []


def test_configure_sharing_dispatches_by_kind(bp18, monkeypatch):
    calls = []
    fake = types.ModuleType("constructel_bridge.bridge_onboarding")
    fake.configure_resource_sharing = lambda settings=None: calls.append("rs") or "rs fait"
    fake.configure_filtermate_sharing = lambda log=None: calls.append(("fm", log)) or "fm fait"
    monkeypatch.setitem(sys.modules, "constructel_bridge.bridge_onboarding", fake)
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    assert plugin._configure_sharing("resource_sharing") == "rs fait"
    assert plugin._configure_sharing("filtermate") == "fm fait"
    assert calls == ["rs", ("fm", plugin._log)]
    assert plugin._configure_sharing("inconnu") == "" and len(calls) == 2


def test_set_language_applies_without_asking(bp18, monkeypatch):
    from constructel_bridge.i18n import get_language

    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    applied, refreshed = [], []
    monkeypatch.setattr(bp18.bridge_sketcher, "apply_all_translations", lambda *a, **k: applied.append(a))
    monkeypatch.setattr(plugin, "_refresh_action_labels", lambda: refreshed.append(1))
    assert not hasattr(bp18, "QInputDialog")           # plus aucune question posee par le plugin
    previous = get_language()
    try:
        plugin._set_language("pt")
        assert get_language() == "pt" and applied == [("pt",)] and refreshed == [1]
        plugin._set_language("xx")                     # inconnue : rien
        assert get_language() == "pt" and len(applied) == 1
    finally:
        bp18.set_language(previous)


def test_home_snapshot_reads_last_selection_presets_and_checkin(bp18, pi, onb, monkeypatch, tmp_path):  # noqa: F811
    from qgis.core import QgsSettings

    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    plugin._operators = [WYRE, ORANGE]
    plugin._bridge_user_email = "jdoe@constructel.be"
    checks = [bd.Check("plugin", "warning", "diag.plugin_update", {"name": "B"}, "update", "b")]
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: checks)
    monkeypatch.setattr(onb, "resource_sharing_configured", lambda settings=None: False)
    monkeypatch.setattr(onb, "filtermate_configured", lambda: None)
    stored = UserPreset(LAST_SELECTION_NAME, ("orange",), LayerSelection({"orange": {"cables"}}, frozenset()))
    mine = UserPreset("Mon jeu", ("wyre",), LayerSelection({"wyre": {"zone_pop"}}, frozenset()))
    QgsSettings().setValue(LAST_SELECTION_KEY, presets_to_json([stored]))
    QgsSettings().setValue(USER_PRESETS_KEY, presets_to_json([mine]))

    snapshot = plugin.home_snapshot()

    assert snapshot.last_selection == stored and snapshot.user_presets == (mine,)
    summary = bd.PluginSummary(1, 1, 1)
    assert snapshot.plugin_summary == summary
    assert snapshot.checkin == hm.CheckinState(summary, False, None)
    assert hm.home_state(snapshot).checkin_badge == 2
    assert (snapshot.login, snapshot.email) == (LOGIN, "jdoe@constructel.be")


def test_home_snapshot_offline_has_no_login_nor_email(bp18, pi, onb, monkeypatch):  # noqa: F811
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._connected = False
    plugin._bridge_user, plugin._bridge_user_email = "ancien", "ancien@constructel.be"   # session precedente
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: [])
    snapshot = plugin.home_snapshot()
    assert (snapshot.login, snapshot.email, snapshot.header) == ("", "", "")


def test_home_snapshot_survives_an_unreadable_sharing_state(bp18, pi, onb, monkeypatch, tmp_path):  # noqa: F811
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: [])

    def boom(*_a, **_k):
        raise OSError("config FilterMate illisible")

    monkeypatch.setattr(onb, "filtermate_configured", boom)
    snapshot = plugin.home_snapshot()
    assert snapshot.checkin == hm.CheckinState(bd.PluginSummary(0, 0, 0), None, None)


def test_load_selection_warns_when_the_first_operator_is_unknown(bp18, pi, monkeypatch, tmp_path):  # noqa: F811
    from qgis.core import QgsMessageLog

    from constructel_bridge_tests.test_bridge18_layers import _shared_plugin

    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)
    monkeypatch.setattr(pi, "init_project", lambda *a, **k: 0)
    reorganized = []
    monkeypatch.setattr(plugin, "_reorganize_legacy_project", lambda op, suffix: reorganized.append(op) or suffix)
    QgsMessageLog._messages.clear()

    plugin._load_selection((ORANGE,), LayerSelection({"wyre": {"cables"}}, frozenset()), set(), False)

    assert reorganized == []
    assert any("wyre" in m[0] and "1.8" in m[0] for m in QgsMessageLog._messages)


# --- Revue finale ----------------------------------------------------------------------------


def test_home_snapshot_falls_back_on_the_1_9_last_operator(bp18, pi, onb, monkeypatch, tmp_path):  # noqa: F811
    # Revue finale : poste venu de la 1.9, ni LAST_SELECTION_KEY ni
    # LAST_OPERATORS_KEY : la preselection suit LAST_OPERATOR_KEY.
    from qgis.core import QgsSettings

    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    plugin._operators = [WYRE, ORANGE]
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: [])
    QgsSettings().setValue(bo.LAST_OPERATOR_KEY, "orange")

    snapshot = plugin.home_snapshot()

    assert snapshot.last_selection == UserPreset("", ("orange",), LayerSelection({}, frozenset()))
    assert hm.home_state(snapshot).preselected == ("orange",)
    # La cle 2.0 prime sur celle de la 1.9.
    QgsSettings().setValue(bo.LAST_OPERATORS_KEY, "wyre")
    assert plugin.home_snapshot().last_selection.schemas == ("wyre",)


def test_diagnostic_action_survives_unreadable_local_checks(bp18, monkeypatch):
    # Revue finale : une exception des verifications locales apres l'action
    # ne sort jamais du slot Qt (pas de boite d'erreur Python) : avertissement
    # journalise, dernieres verifications connues rendues.
    from qgis.core import QgsMessageLog

    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._connected = False
    checks = [bd.Check("identity", "ok", "diag.identity_ok", {"login": "jdoe"})]
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: checks)
    assert plugin._diagnostic_inputs()[1] == checks

    def boom():
        raise RuntimeError("qgis.utils indisponible")

    monkeypatch.setattr(plugin, "_diagnostic_local_checks", boom)
    QgsMessageLog._messages.clear()
    manager = bd.Check("plugin", "ok", "diag.plugin_ok", {"name": "A"})     # sans action : relecture seule
    assert plugin._run_diagnostic_action(manager) == checks
    assert any("qgis.utils indisponible" in m[0] for m in QgsMessageLog._messages)
    # Sans verifications connues : liste vide.
    fresh = bp18.ConstructelBridgePlugin(_FakeIface())
    monkeypatch.setattr(fresh, "_diagnostic_local_checks", boom)
    assert fresh._run_diagnostic_action(manager) == []


def _push_buttons(dialog):
    return dialog.findChildren(_Button)


def test_enter_presses_no_sidebar_nor_page_button(home):
    # Revue finale (Important) : dans un QDialog tout QPushButton est
    # autoDefault, Entree dans la recherche ou l'arbre cliquait « FR » ou
    # « Se connecter ». Aucun bouton autoDefault, apres chaque redessin et
    # chaque construction de page ; « Charger » par defaut sur sa page.
    dialog = _open(home, snap(**OFFLINE))
    footer = [dialog._connect_button, *dialog._lang_buttons.values()]
    load = dialog._pages["load"]
    assert all(b in _push_buttons(dialog) for b in footer + [load._load_button])
    assert not any(b.autoDefault() for b in _push_buttons(dialog))
    assert [b for b in _push_buttons(dialog) if b.isDefault()] == [load._load_button]

    dialog.snapshots.append(snap())
    dialog._connect_button.clicked.emit(False)                 # redessin
    buttons = _push_buttons(dialog)
    page = dialog._pages["load"]
    assert page._operator_buttons and all(b in buttons for b in page._operator_buttons.values())
    assert not any(b.autoDefault() for b in buttons)
    assert [b for b in buttons if b.isDefault()] == [page._load_button]

    for name in ("projects", "checkin", "diagnostic"):         # pages construites a leur affichage
        dialog.show_page(name)
        assert dialog._pages[name] in dialog._stack.pages
        assert not any(b.autoDefault() for b in _push_buttons(dialog))
        assert not any(b.isDefault() for b in _push_buttons(dialog))    # « Charger » cache : pas par defaut
    assert dialog._pages["projects"]._open_button in _push_buttons(dialog)
    dialog.show_page("load")
    assert [b for b in _push_buttons(dialog) if b.isDefault()] == [page._load_button]


def test_checkin_redraw_keeps_buttons_off_auto_default(home):
    dialog = _open(home, snap(checkin=hm.CheckinState(bd.PluginSummary(5, 6, 0), False, True)), page="checkin")
    page = dialog._pages["checkin"]
    page.on_change()                                          # apres une action : barre relue
    assert not any(b.autoDefault() for b in _push_buttons(dialog))


class _Geometry:
    def __init__(self, width, height):
        self._size = (width, height)

    def width(self):
        return self._size[0]

    def height(self):
        return self._size[1]


def _screen(monkeypatch, width, height):
    from qgis.PyQt import QtGui

    screen = types.SimpleNamespace(availableGeometry=lambda: _Geometry(width, height))
    monkeypatch.setattr(QtGui, "QGuiApplication",
                        types.SimpleNamespace(primaryScreen=staticmethod(lambda: screen)), raising=False)


def test_window_fits_a_1366x768_laptop(home, monkeypatch):
    # Anti-objectif § 4 : 1366x768, barre des taches de 40 px.
    _screen(monkeypatch, 1366, 728)
    dialog = _open(home)
    width, height = dialog.size
    assert width == 1100 and height <= 728 - 30                 # place pour la barre de titre
    assert dialog.minimum_size == (980, 640)


def test_window_keeps_its_sizes_on_a_large_screen(home, monkeypatch):
    _screen(monkeypatch, 1920, 1040)
    dialog = _open(home)
    assert dialog.size == (1100, 720) and dialog.minimum_size == (980, 640)


def test_window_and_minimum_shrink_on_a_small_screen(home, monkeypatch):
    _screen(monkeypatch, 1024, 600)
    dialog = _open(home)
    width, height = dialog.size
    assert width < 1024 and height < 600
    assert dialog.minimum_size == (980, height)                # jamais plus grand que l'ecran
    assert width >= 980


def test_window_survives_an_unreadable_screen(home, monkeypatch):
    from qgis.PyQt import QtGui

    def boom():
        raise RuntimeError("pas d'ecran")

    monkeypatch.setattr(QtGui, "QGuiApplication",
                        types.SimpleNamespace(primaryScreen=staticmethod(boom)), raising=False)
    dialog = _open(home)
    assert dialog.size == (1100, 720) and dialog.minimum_size == (980, 640)


def test_diagnostic_action_refreshes_the_checkin_badge(home):
    # Revue finale : une installation depuis le Diagnostic eteint la pastille
    # du Check-in sans attendre un redessin.
    dialog = _open(home, snap(checkin=hm.CheckinState(bd.PluginSummary(5, 6, 0), True, True)), page="diagnostic")
    panel = dialog._pages["diagnostic"]
    assert dialog._sidebar.rows[2].endswith("⚠ 1")
    dialog.snapshots.append(snap(checkin=hm.CheckinState(bd.PluginSummary(6, 6, 0), True, True)))

    panel._run_action(bd.Check("plugin", "warning", "diag.plugin_missing", {"name": "C"}, "install", "c"))

    assert any(isinstance(e, tuple) and e[0] == "diagnostic_action" for e in dialog.log)
    assert dialog._sidebar.rows[2] == home.tr("home.nav_checkin")
    assert dialog._pages["diagnostic"] is panel and panel._closed is False and dialog._sidebar.currentRow() == 3


def test_redraw_keeps_basemaps_styles_and_suffix(home):
    # Ledger T9 : les options de la page Charger survivent a render(), comme
    # current_choice().
    dialog = _open(home, snap(operators=(WYRE,), last_suffix=False))
    page = dialog._pages["load"]
    page._selection.set_basemaps(set())
    page._selection.set_want_styles(False)
    page._suffix_box.setChecked(True)
    page._suffix_box.clicked.emit(True)
    options = page.current_options()

    dialog._lang_buttons["en"].clicked.emit(False)

    again = dialog._pages["load"]
    assert again is not page and again.current_options() == options
    assert again._suffix_box.checked is True and again._selection.want_styles() is False
    assert again._selection.selected_basemaps() == set()
