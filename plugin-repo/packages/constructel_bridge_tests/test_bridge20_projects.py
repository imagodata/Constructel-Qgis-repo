"""Bridge 2.0, tache 8 (plan 2026-11-18, spec § 7, R5, R7) : page « Projets »
(bridge_home_projects.ProjectsPage) et, cote plugin, ``_open_db_project``
(ex-partie de ``_on_load_project`` apres le choix, retire en tache 9) et le
schema transverse ``projet`` dans ``_project_schemas``.

La page tourne sur les doublures de fakes_widgets.py ; le rendu Qt reel
(arbre a deux colonnes, theme sombre) reste a la recette manuelle."""
from __future__ import annotations

import dataclasses
import importlib
import sys

import pytest

from constructel_bridge import bridge_home_model as hm
from constructel_bridge_tests.fakes_widgets import (
    _ITEM_FLAG,
    _ROLE,
    _Button,
    _Label,
    _Layout,
    _LineEdit,
    _Sig,
    _Tree,
    _W,
    _widgets,
)
from constructel_bridge_tests.test_bridge18_connect import _make_plugin  # noqa: F401
from constructel_bridge_tests.test_bridge19_browser_projects import (  # noqa: F401  (fixtures)
    _ProjectsCursor,
    _record_message_boxes,
    fake_cursor,
    plugin,
    settings,
)
from constructel_bridge_tests.fakes19 import ORANGE, WYRE

MODULE = "constructel_bridge.bridge_home_projects"
LABELS = {"wyre": "Wyre", "orange": "Orange"}

PROJECTS = [
    {"name": "Ixelles", "schema": "wyre", "description": "Réseau d'Ixelles", "updated": "2026-11-01"},
    {"name": "Uccle", "schema": "wyre", "description": "Quartier Vivier d'Oie", "updated": ""},
    {"name": "Modèle commun", "schema": "public", "description": None, "updated": None},
]


class _ProjTree(_Tree):
    """QTreeWidget : sélection courante et signaux de la page."""

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


@pytest.fixture
def mod(bp18, monkeypatch):
    """bridge_home_projects importé sur des doublures de widgets."""
    from qgis.PyQt import QtCore, QtWidgets
    import types

    for name, fake in (("QWidget", _W), ("QLabel", _Label), ("QPushButton", _Button),
                       ("QLineEdit", _LineEdit), ("QTreeWidget", _ProjTree),
                       ("QVBoxLayout", _Layout), ("QHBoxLayout", _Layout)):   # 2.1 : rangees de boutons
        monkeypatch.setattr(QtWidgets, name, fake, raising=False)
    # QTreeWidgetItem de la doublure : (parent, textes), comme _Item.
    from constructel_bridge_tests.fakes_widgets import _Item
    monkeypatch.setattr(QtWidgets, "QTreeWidgetItem", _Item, raising=False)
    monkeypatch.setattr(QtCore.Qt, "ItemDataRole", _ROLE, raising=False)
    monkeypatch.setattr(QtCore.Qt, "ItemFlag", _ITEM_FLAG, raising=False)
    monkeypatch.setattr(QtCore.Qt, "TextFormat", types.SimpleNamespace(PlainText=0), raising=False)
    monkeypatch.delitem(sys.modules, MODULE, raising=False)
    module = importlib.import_module(MODULE)
    yield module
    sys.modules.pop(MODULE, None)


class _Actions:
    """HomeActions : appels journalisés dans ``log`` (partagé avec on_open)."""

    def __init__(self, projects=PROJECTS, log=None):
        self.log = [] if log is None else log
        self.projects = projects

    def list_projects(self):
        self.log.append("list_projects")
        return self.projects

    def open_project(self, schema, name):
        self.log.append(("open_project", schema, name))
        return True


def _page(mod, actions=None, connected=True, log=None):
    """2.1 : ProjectsPage(actions, instantane, etat, on_open). Sans capacites
    du lot (b) (et sans ``actions.qgis``), la page est celle de la 2.0."""
    from constructel_bridge import bridge_home_model as hm
    from constructel_bridge_tests.test_bridge20_home_model import snap

    log = [] if log is None else log
    actions = actions or _Actions(log=log)
    snapshot = snap(connected=connected, labels=LABELS)
    page = mod.ProjectsPage(actions, snapshot, hm.home_state(snapshot), lambda: log.append("on_open"))
    page.log = log
    return page


def _groups(page):
    return {g.text(0): [c.text(0) for c in g.children] for g in page._tree.children}


def _first_project(page):
    return page._tree.children[0].children[0]


# --- groupes et recherche -------------------------------------------------------------


def test_projects_grouped_by_operator_with_search(mod):
    from constructel_bridge.i18n import tr

    page = _page(mod)
    assert _groups(page) == {"Wyre": ["Ixelles", "Uccle"], tr("home.projects_common"): ["Modèle commun"]}

    # Nom ou description, sans casse ni accents : « ixe » -> Ixelles ; « RESEAU » -> description d'Ixelles.
    for query in ("ixe", "IXE", "reseau"):
        page._search.setText(query)
        assert _groups(page) == {"Wyre": ["Ixelles"]}, query
    page._search.setText("modele")
    assert _groups(page) == {tr("home.projects_common"): ["Modèle commun"]}
    page._search.setText("vivier d'oie")           # description d'Uccle
    assert _groups(page) == {"Wyre": ["Uccle"]}
    page._search.setText("")
    assert len(page._tree.children) == 2


def test_search_without_match_shows_message_and_hides_tree(mod):
    from constructel_bridge.i18n import tr

    page = _page(mod)
    page._search.setText("zzz")
    assert page._tree.children == []
    assert page._message.text() == tr("project.none_found") and page._tree.visible is False


def test_projet_schema_group_is_labelled_projets(mod):
    # 2.1 : libelle sans ambiguite (« Projets » nu retire, spec § 5 bis).
    from constructel_bridge.i18n import tr

    projects = PROJECTS + [{"name": "Partagé", "schema": "projet", "description": "", "updated": ""}]
    page = _page(mod, _Actions(projects))
    assert _groups(page)[tr("qgis.legacy_projet_group")] == ["Partagé"]
    assert tr("qgis.legacy_projet_group") != tr("home.projects_common")


def test_group_label_falls_back_to_the_schema(mod):
    page = _page(mod, _Actions([{"name": "X", "schema": "proximus", "description": "", "updated": ""}]))
    assert _groups(page) == {"proximus": ["X"]}


def test_projects_labels_exist_in_every_language(bp18):
    from constructel_bridge.i18n.translations import TRANSLATIONS

    for key in ("home.projects_title", "home.projects_search", "home.projects_open",
                "home.projects_common", "qgis.legacy_projet_group", "home.projects_offline"):
        values = {lang: TRANSLATIONS[lang][key] for lang in ("fr", "en", "pt")}
        assert all(values.values()), key
    assert TRANSLATIONS["fr"]["qgis.legacy_projet_group"] == "Projets QGIS (schéma projet)"


# --- ouverture ------------------------------------------------------------------------


def test_open_closes_window_first_then_opens(mod):
    page = _page(mod)
    page._tree.select(_first_project(page))
    assert page._open_button.enabled is True
    page._open_button.clicked.emit(False)
    assert page.log == ["list_projects", "on_open", ("open_project", "wyre", "Ixelles")]


def test_double_click_opens_too(mod):
    page = _page(mod)
    item = _first_project(page)
    page._tree.select(item)
    page._tree.itemDoubleClicked.emit(item, 0)
    assert page.log[-2:] == ["on_open", ("open_project", "wyre", "Ixelles")]


def test_open_button_disabled_without_selection(mod):
    page = _page(mod)
    assert page._open_button.enabled is False
    page._open_button.clicked.emit(False)            # sans effet
    assert "on_open" not in page.log

    group = page._tree.children[0]                    # un groupe n'est pas un projet
    page._tree.select(group)
    assert page._open_button.enabled is False
    page._open_button.clicked.emit(False)
    assert "on_open" not in page.log

    page._tree.select(_first_project(page))
    assert page._open_button.enabled is True
    page._search.setText("uccle")                     # l'arbre est reconstruit : plus de sélection
    assert page._open_button.enabled is False


# --- hors connexion, erreur, liste vide -----------------------------------------------


def test_offline_shows_message_and_never_lists(mod):
    from constructel_bridge.i18n import tr

    class Boom(_Actions):
        def list_projects(self):
            raise AssertionError("list_projects ne doit pas etre appele hors connexion")

    page = _page(mod, Boom(), connected=False)
    assert page._message.text() == tr("home.projects_offline")
    assert page._tree.children == [] and page._open_button.enabled is False
    assert page._search.enabled is False


@pytest.mark.parametrize("answer, key", [(None, "home.projects_error"), ([], "project.none_found")])
def test_list_error_or_empty_shows_message(mod, answer, key):
    from constructel_bridge.i18n import tr

    # None : liste illisible, journalisée par le plugin qui n'affiche rien
    # (tâche 9 : un seul message, celui de la page) ; [] : aucun projet.
    page = _page(mod, _Actions(answer))
    assert page._message.text() == tr(key)
    assert page._tree.children == [] and page._open_button.enabled is False
    page._search.setText("x")                         # la recherche ne masque pas l'erreur
    assert page._message.text() == tr(key)


def test_normalize_strips_accents_and_case(mod):
    assert mod.normalize("Éléphant Ç") == "elephant c"
    assert mod.normalize(None) == ""
    assert mod.matches({"name": "Ixelles", "description": None}, "  IXE ") is True
    assert mod.matches({"name": "Uccle", "description": None}, "ixe") is False


# --- plugin : _open_db_project et schema « projet » ------------------------------------


def _stub_read(plugin, monkeypatch, ok, error="boom"):
    from types import SimpleNamespace

    calls = []
    monkeypatch.setattr(plugin, "_read_and_clean_project",
                        lambda project, schema, name: calls.append((schema, name)) or ok)
    return calls


def test_open_db_project_reports_success_and_failure(bp18, plugin, monkeypatch):
    from qgis.core import QgsMessageLog, QgsProject
    from constructel_bridge.i18n import tr

    boxes = []
    monkeypatch.setattr(bp18.QMessageBox, "critical",
                        staticmethod(lambda *a, **k: boxes.append(a[2])), raising=False)
    pushed = []
    plugin.iface.messageBar = lambda: type("Bar", (), {
        "pushSuccess": lambda self, *a, **k: pushed.append(a[1]),
        "pushMessage": lambda self, *a, **k: None})()

    calls = _stub_read(plugin, monkeypatch, True)
    QgsMessageLog._messages.clear()
    assert plugin._open_db_project("wyre", "Ixelles") is True
    assert calls == [("wyre", "Ixelles")]
    assert pushed == [tr("project.loaded", name="Ixelles")] and boxes == []
    assert any(tr("project.loaded", name="Ixelles") in m[0] for m in QgsMessageLog._messages)

    monkeypatch.setattr(QgsProject.instance(), "error", lambda: "xml invalide", raising=False)
    _stub_read(plugin, monkeypatch, False)
    QgsMessageLog._messages.clear()
    assert plugin._open_db_project("wyre", "Casse") is False
    message = tr("project.load_error", name="Casse", error="xml invalide")
    assert boxes == [message] and pushed == [tr("project.loaded", name="Ixelles")]
    assert any(message in m[0] for m in QgsMessageLog._messages)


def test_load_project_menu_now_opens_the_projects_page(bp18, plugin):
    # R5 leve en tache 9 : plus de QInputDialog ; le menu « Charger un projet »
    # ouvre la fenetre sur la page Projets (test_bridge20_home.py), qui liste
    # par _list_db_projects et ouvre par _open_db_project.
    assert not hasattr(bp18.ConstructelBridgePlugin, "_on_load_project")
    actions = plugin._home_actions()
    assert actions.list_projects == plugin._list_db_projects
    assert actions.open_project == plugin._open_db_project


def test_projet_schema_listed_only_when_it_exists(plugin, fake_cursor, monkeypatch):
    # 2.1 (tache 9) : l'existence de `projet.qgis_projects` vient des capacites
    # lues a la connexion (`_projet_caps`), plus d'une requete a chaque appel.
    from constructel_bridge.bridge_projets import NO_CAPABILITIES, ProjetCapabilities

    plugin._operators = [WYRE]
    probes = []
    real_execute = fake_cursor.execute

    def execute(sql, params=None):
        real_execute(sql, params)
        if "information_schema.schemata" in sql:
            probes.append(params[0])

    monkeypatch.setattr(fake_cursor, "execute", execute)
    plugin._projet_caps = ProjetCapabilities(qgis_table=True)
    assert plugin._project_schemas() == ("wyre", "public", "projet")
    assert [p["schema"] for p in plugin._list_db_projects()] == ["wyre", "public", "projet"]

    plugin._projet_caps = NO_CAPABILITIES
    assert plugin._project_schemas() == ("wyre", "public")
    assert [p["schema"] for p in plugin._list_db_projects()] == ["wyre", "public"]
    assert probes == []


def test_projet_schema_absent_when_database_unreadable_or_offline(plugin):
    plugin._operators = [WYRE]

    def boom():
        raise RuntimeError("connexion perdue")

    plugin._conn.cursor = boom
    assert plugin._project_schemas() == ("wyre", "public")
    plugin._conn = None
    assert plugin._project_schemas() == ("wyre", "public")


def test_read_and_clean_accepts_projet_only_when_it_exists(plugin, fake_cursor, monkeypatch):
    # 2.1 (tache 9) : liste blanche du schema `projet` = capacites de la connexion.
    from qgis.core import QgsProject
    from constructel_bridge.bridge_projets import NO_CAPABILITIES, ProjetCapabilities
    from constructel_bridge_tests.test_bridge18_layers import _XmlCursor

    plugin._operators = [WYRE]
    plugin._auth_mode = ""
    plugin._password = "shared-pw"
    cursor = _XmlCursor("<qgis></qgis>")
    queries = []
    base_execute = cursor.execute
    cursor.execute = lambda sql, *a, **k: queries.append(sql) or base_execute(sql, *a, **k)
    plugin._conn.cursor = lambda: cursor

    plugin._projet_caps = NO_CAPABILITIES
    assert plugin._read_and_clean_project(QgsProject.instance(), "projet", "x") is False
    assert queries == []
    plugin._projet_caps = ProjetCapabilities(qgis_table=True)
    # Schéma présent : accepté par la liste blanche (la lecture du XML relève de _XmlCursor).
    assert "projet" in plugin._project_schemas()
