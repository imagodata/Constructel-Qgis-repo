"""Bridge 2.1, tache 19 : page « Projets QGIS » (sections, badges, boutons,
modes login partage / base sans lot b / hors connexion) et cablage du plugin."""
from __future__ import annotations

import dataclasses
import importlib
import sys
import types
from types import SimpleNamespace

import pytest

from constructel_bridge import bridge_home_model as hm
from constructel_bridge import bridge_projets as pj
from constructel_bridge import bridge_qgis_store as store
from constructel_bridge.bridge_qgis_projects import OpenedQgisProject, QgisProjectRow
from constructel_bridge_tests.fakes19 import WYRE
from constructel_bridge_tests.fakes_widgets import (
    _ITEM_FLAG,
    _ROLE,
    _Button,
    _CheckBox,
    _Combo,
    _Completer,
    _Dialog,
    _Edit,
    _GroupBox,
    _Item,
    _ItemTree,
    _Label,
    _LineEdit,
    _Layout,
    _StringModel,
    _Timer,
    _W,
)
from constructel_bridge_tests.test_bridge20_home_model import snap
from constructel_bridge_tests.test_bridge20_projects import _ProjTree

MODULE = "constructel_bridge.bridge_home_projects"
FULL = pj.ProjetCapabilities(True, True, True, True, True, True, True)
GOFIBER = pj.ProjetInfo("uuid-g", "GOFIBER", "GoFiber", "WYRE", (pj.ProjetLayer("t", "T", None, "default", None, 0),))
REFS = [{"name": "Ixelles", "schema": "wyre", "description": "Réseau", "updated": ""},
        {"name": "Modèle", "schema": "public", "description": None, "updated": None},
        {"name": "Vieux projet", "schema": "projet", "description": "", "updated": ""}]


def qrow(name, **kw):
    base = dict(owner="jdoe", projet_id=None, projet_code=None, projet_label=None, share_project=False,
                published=False, owner_role="BE", version=1, updated_at=None, updated_by="jdoe", is_owner=False,
                can_edit=False, share_count=None, description=None)
    base.update(kw)
    return QgisProjectRow(name=name, **base)


ROWS = [
    qrow("Ma vue", is_owner=True, can_edit=True, share_count=0),
    qrow("Ma vue partagée", is_owner=True, can_edit=True, share_count=2, share_project=True, projet_id="uuid-g",
         projet_code="GOFIBER", projet_label="GoFiber", published=True),
    qrow("Vue de Bob", owner="b.martin", can_edit=True),
    qrow("Référence GoFiber", owner="admin", published=True, projet_id="uuid-g", projet_code="GOFIBER",
         projet_label="GoFiber", description="profondeur"),
]


class _Tree3(_ProjTree):
    def setCurrentItem(self, item):
        self.select(item)


@pytest.fixture
def page_mod(bp18, monkeypatch):
    from qgis.PyQt import QtCore, QtWidgets

    for name, fake in (("QWidget", _W), ("QLabel", _Label), ("QPushButton", _Button), ("QLineEdit", _Edit),
                       ("QTreeWidget", _Tree3), ("QTreeWidgetItem", _Item), ("QVBoxLayout", _Layout),
                       ("QHBoxLayout", _Layout), ("QDialog", _Dialog), ("QComboBox", _Combo),
                       ("QCompleter", _Completer), ("QGroupBox", _GroupBox), ("QRadioButton", _CheckBox),
                       ("QCheckBox", _CheckBox)):
        monkeypatch.setattr(QtWidgets, name, fake, raising=False)
    monkeypatch.setattr(QtCore.Qt, "ItemDataRole", _ROLE, raising=False)
    monkeypatch.setattr(QtCore.Qt, "ItemFlag", _ITEM_FLAG, raising=False)
    monkeypatch.setattr(QtCore.Qt, "TextFormat", types.SimpleNamespace(PlainText=0), raising=False)
    monkeypatch.setattr(QtCore, "QTimer", _Timer, raising=False)
    monkeypatch.setattr(QtCore, "QStringListModel", _StringModel, raising=False)
    names = (MODULE, "constructel_bridge.bridge_qgis_dialogs", "constructel_bridge.bridge_people_picker")
    for name in names:
        monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module(MODULE)
    yield module
    for name in names:
        sys.modules.pop(name, None)


class _Qgis:
    def __init__(self, log, rows=ROWS):
        self.log, self.rows = log, list(rows)
        self.opened_record = None

    def list_visible(self):
        self.log.append("list_visible")
        return list(self.rows)

    def open(self, row):
        self.log.append(("open_qgis", row.name))
        return True

    def delete(self, name):
        self.log.append(("delete", name))
        self.rows = [r for r in self.rows if r.name != name]
        return store.StoreOutcome(store.STATUS_OK)

    def opened(self):
        return self.opened_record

    def current_state(self):
        return hm.CurrentProjectState("Ixelles", 3, "jdoe")

    def __getattr__(self, name):
        return lambda *a, **k: self.log.append((name, a)) or None


def _page(page_mod, nominative=True, caps=FULL, connected=True, refs=REFS, rows=ROWS, with_qgis=True):
    log = []
    snapshot = snap(connected=connected, projets=(GOFIBER,), capabilities=caps, nominative=nominative,
                    operator_code_labels=(("WYRE", "Wyre"),), labels={"wyre": "Wyre"})
    state = hm.home_state(snapshot)
    qgis = _Qgis(log, rows) if with_qgis else None
    noop = {f.name: (lambda *a, **k: None) for f in dataclasses.fields(hm.HomeActions)}
    actions = hm.HomeActions(**{**noop, "snapshot": lambda: snapshot,
                                "list_projects": lambda: log.append("list_projects") or list(refs),
                                "open_project": lambda schema, name: log.append(("open_project", schema, name)),
                                "qgis": qgis})
    page = page_mod.ProjectsPage(actions, snapshot, state, lambda: log.append("on_open"))
    page.log, page.qgis = log, qgis
    return page


def _tree(page):
    def walk(item):
        return [item.text(0), [walk(c) for c in item.children]] if item.children else item.text(0)
    return [walk(group) for group in page._tree.children]


def _find(page, name):
    for item, entry in zip(page._entry_items, page._entries):
        if item.text(0) == name:
            return item
    raise KeyError(name)


def test_three_sections_with_counts_and_badges(page_mod):
    tr = page_mod.tr
    page = _page(page_mod)
    sections = [g.text(0) for g in page._tree.children]
    assert sections == [tr("qgis.section_mine", count=2), tr("qgis.section_shared", count=1),
                        tr("qgis.section_published", count=3)]   # mon projet publie reste dans Mes projets
    mine = page._tree.children[0].children
    assert [i.text(0) for i in mine] == ["Ma vue", "Ma vue partagée"]
    assert mine[0].text(2) == tr("qgis.badge_private")
    assert mine[1].text(1) == "GoFiber"
    assert mine[1].text(2) == " · ".join([tr("qgis.badge_shared", count=2), tr("qgis.badge_projet", projet="GoFiber"),
                                          tr("qgis.badge_published")])
    shared = page._tree.children[1].children[0]
    assert shared.text(2) == f"{tr('qgis.from_owner', owner='b.martin')} · {tr('qgis.can_edit')}"


def test_published_groups_projet_then_reference_projects(page_mod):
    tr = page_mod.tr
    page = _page(page_mod)
    published = page._tree.children[2]
    assert [g.text(0) for g in published.children] == ["GoFiber · Wyre", "Wyre", tr("home.projects_common")]
    assert [i.text(0) for i in published.children[0].children] == ["Référence GoFiber"]
    assert "Vieux projet" not in str(_tree(page))      # schema projet : vient de list_visible
    assert page.log[:2] == ["list_projects", "list_visible"]


def test_share_and_delete_only_on_my_projects(page_mod):
    page = _page(page_mod)
    assert page._share_button.isVisible() and page._delete_button.isVisible() and page._save_button.isVisible()
    page._tree.select(_find(page, "Vue de Bob"))
    assert page._open_button.enabled and not page._share_button.enabled and not page._delete_button.enabled
    page._tree.select(_find(page, "Ma vue"))
    assert page._share_button.enabled and page._delete_button.enabled
    page._tree.select(_find(page, "Ixelles"))
    assert page._open_button.enabled and not page._delete_button.enabled
    page._tree.select(page._tree.children[0])            # une section n'est pas un projet
    assert not page._open_button.enabled


def test_write_buttons_follow_capabilities(page_mod):
    caps = pj.ProjetCapabilities(True, True, True, False, False, False, False)
    page = _page(page_mod, caps=caps)
    assert not page._save_button.isVisible() and not page._share_button.isVisible() and not page._delete_button.isVisible()


def test_shared_login_never_calls_visible_and_disables_save(page_mod):
    tr = page_mod.tr
    page = _page(page_mod, nominative=False)
    assert "list_visible" not in page.log
    assert page._notice.text() == tr("qgis.nominative_required") and page._notice.isVisible()
    assert not page._save_button.enabled and page._save_button.toolTip() == tr("qgis.nominative_required")
    assert [g.text(0) for g in page._tree.children] == [tr("qgis.section_published", count=2)]
    assert [g.text(0) for g in page._tree.children[0].children] == ["Wyre", tr("home.projects_common")]
    assert not page._share_button.isVisible() and not page._delete_button.isVisible()


def test_page_without_visible_function_is_the_2_0_page(page_mod):
    tr = page_mod.tr
    caps = pj.ProjetCapabilities(registry=True, qgis_table=True)
    page = _page(page_mod, caps=caps)
    assert "list_visible" not in page.log
    assert [g.text(0) for g in page._tree.children] == ["Wyre", tr("home.projects_common"), tr("qgis.legacy_projet_group")]
    assert not page._save_button.isVisible() and not page._share_button.isVisible()
    assert not page._delete_button.isVisible() and not page._notice.isVisible()


def test_page_without_qgis_actions_is_the_2_0_page(page_mod):
    page = _page(page_mod, with_qgis=False)
    assert page._mode == page_mod.MODE_LEGACY


def test_offline_page_makes_no_query(page_mod):
    page = _page(page_mod, connected=False)
    assert page.log == [] and page._message.text() == page_mod.tr("home.projects_offline")
    assert not page._save_button.isVisible()


def test_visible_list_error_shows_the_error_message(page_mod):
    page = _page(page_mod)
    page.qgis.list_visible = lambda: None
    page._reload()
    assert page._message.text() == page_mod.tr("home.projects_error")


# -- colonnes : en-tetes traduits, noms jamais tronques (correctif 2.1.x) --------------------

def _resize_to_contents():
    from qgis.PyQt.QtWidgets import QHeaderView

    return QHeaderView.ResizeMode.ResizeToContents


def test_qgis_page_headers_name_projet_and_detail_columns(page_mod):
    tr = page_mod.tr
    page = _page(page_mod)
    tree = page._tree
    assert not tree.header_hidden and tree.column_count == 3
    assert tree.header_labels == [tr("home.projects_col_name"), tr("qgis.col_projet"), tr("qgis.col_detail")]
    # La colonne 1 porte le projet metier, la 2 le detail (partage, proprietaire et droits).
    mine = tree.children[0].children[1]
    assert mine.text(1) == "GoFiber" and tr("qgis.badge_published") in mine.text(2)
    assert tree.hidden_columns == set()


def test_name_column_fits_its_content_and_last_column_stretches(page_mod):
    page = _page(page_mod)
    header = page._tree.header()
    # Nom et projet metier a la largeur de leur contenu (recalculee par Qt a chaque
    # remplissage, recherche, depli ou repli), le detail prend le reste.
    assert header.modes == {0: _resize_to_contents(), 1: _resize_to_contents()}
    assert header.stretch_last is True
    assert header.minimum == page_mod.MIN_COLUMN_WIDTH > 0


def test_shared_login_hides_the_always_empty_projet_column(page_mod):
    tr = page_mod.tr
    page = _page(page_mod, nominative=False)
    assert page._tree.header_labels == [tr("home.projects_col_name"), tr("qgis.col_projet"), tr("qgis.col_detail")]
    assert page._tree.hidden_columns == {1}
    ref = page._tree.children[0].children[0].children[0]
    assert ref.text(0) == "Ixelles" and ref.text(1) == "" and ref.text(2) == "Réseau"


@pytest.mark.parametrize("kwargs", [dict(caps=pj.ProjetCapabilities(registry=True, qgis_table=True)),
                                    dict(with_qgis=False), dict(connected=False)])
def test_2_0_and_offline_pages_have_name_and_description_headers(page_mod, kwargs):
    tr = page_mod.tr
    page = _page(page_mod, **kwargs)
    tree = page._tree
    assert not tree.header_hidden and tree.column_count == 2
    assert tree.header_labels == [tr("home.projects_col_name"), tr("home.projects_col_description")]
    assert tree.header().modes == {0: _resize_to_contents()} and tree.header().stretch_last is True
    assert tree.hidden_columns == set()


@pytest.mark.parametrize("lang, expected", [
    ("fr", (["Nom", "Projet métier", "Détail"], ["Nom", "Description"])),
    ("en", (["Name", "Business project", "Details"], ["Name", "Description"])),
    ("pt", (["Nome", "Projeto de negócio", "Detalhe"], ["Nome", "Descrição"])),
])
def test_column_headers_are_translated(page_mod, monkeypatch, lang, expected):
    i18n = sys.modules[page_mod.tr.__module__]
    monkeypatch.setattr(i18n, "_current_lang", lang)
    assert page_mod.column_headers(page_mod.MODE_QGIS) == expected[0]
    assert page_mod.column_headers(page_mod.MODE_NOMINATIVE) == expected[0]
    assert page_mod.column_headers(page_mod.MODE_LEGACY) == expected[1]
    assert page_mod.column_headers(page_mod.MODE_OFFLINE) == expected[1]


def test_search_matches_projet_label(page_mod):
    page = _page(page_mod)
    page._search.setText("gofib")
    names = [item.text(0) for item in page._entry_items]
    assert names == ["Ma vue partagée", "Référence GoFiber"]
    page._search.setText("PROFONDEUR")                  # description
    assert [item.text(0) for item in page._entry_items] == ["Référence GoFiber"]


def test_open_closes_window_then_opens_qgis_row(page_mod):
    page = _page(page_mod)
    page._tree.select(_find(page, "Vue de Bob"))
    page._open_button.clicked.emit(False)
    assert page.log[-2:] == ["on_open", ("open_qgis", "Vue de Bob")]
    page._tree.select(_find(page, "Ixelles"))
    page._tree.itemDoubleClicked.emit(page._tree.current, 0)
    assert page.log[-2:] == ["on_open", ("open_project", "wyre", "Ixelles")]


def test_after_delete_page_reloads_and_selection_moves(page_mod):
    tr = page_mod.tr
    page = _page(page_mod)
    page._tree.select(_find(page, "Ma vue"))
    page._delete_selected(ask=lambda title, text: True)
    assert ("delete", "Ma vue") in page.log and page.log.count("list_visible") == 2
    assert page._feedback.text() == tr("delete.done")
    assert page._tree.current.text(0) == "Ma vue partagée"
    page._delete_selected(ask=lambda title, text: False)      # refus de confirmation : rien
    assert page.log.count(("delete", "Ma vue partagée")) == 0


def test_save_from_page_runs_the_flow_then_reloads_and_selects(page_mod, monkeypatch):
    qd = importlib.import_module("constructel_bridge.bridge_qgis_dialogs")   # le module que la page importera
    page = _page(page_mod)
    seen = {}

    def fake_flow(dialog_factory, conflict_factory, actions, login):
        seen["login"] = login
        page.qgis.rows.append(qrow("Nouvelle", is_owner=True, can_edit=True, share_count=0))
        page.qgis.opened_record = OpenedQgisProject("Nouvelle", 1, None, None, True, True, {})
        return store.StoreOutcome(store.STATUS_OK, value=1)

    monkeypatch.setattr(qd, "run_save_flow", fake_flow)
    page._save_button.clicked.emit(False)
    assert seen["login"] == "jdoe" and page._tree.current.text(0) == "Nouvelle"
    assert page._feedback.text() == page_mod.tr("save.done", name="Nouvelle", version=1)


def test_save_feedback_when_sharing_was_refused(page_mod):
    out = store.StoreOutcome(store.STATUS_OK, value=1, message="ineligible", count=2)
    assert page_mod.ProjectsPage.save_feedback(out, "Vue") == page_mod.tr("save.share_refused", count=2)
    out = store.StoreOutcome(store.STATUS_OK, value=1, message="denied", detail="reserve")
    assert page_mod.tr("save.share_failed", message="reserve") in page_mod.ProjectsPage.save_feedback(out, "Vue")


def test_nav_label_says_qgis_projects(bp18):
    from constructel_bridge.i18n.translations import TRANSLATIONS

    assert TRANSLATIONS["fr"]["home.nav_projects"] == "Projets QGIS"
    assert TRANSLATIONS["en"]["home.nav_projects"] == "QGIS projects"
    assert TRANSLATIONS["pt"]["home.nav_projects"] == "Projetos QGIS"
    assert TRANSLATIONS["fr"]["home.projects_title"] == "Projets QGIS"
    assert all("home.projects_projets" not in TRANSLATIONS[lang] for lang in ("fr", "en", "pt"))


# --- plugin : actions des projets QGIS ------------------------------------------------------

@pytest.fixture
def plugin(bp18, monkeypatch, tmp_path):
    from constructel_bridge_tests.test_bridge18_layers import _nominal_plugin

    p = _nominal_plugin(bp18, monkeypatch, tmp_path)
    p._conn = SimpleNamespace(cursor=lambda: (_ for _ in ()).throw(AssertionError("pas de SQL direct")), closed=False)
    p._projet_caps = FULL
    return p


def test_home_actions_carry_qgis_actions_when_connected(plugin):
    actions = plugin._home_actions()
    assert actions.qgis is not None and actions.qgis.open == plugin._open_qgis_project
    assert actions.qgis.save == plugin._save_qgis_project and actions.qgis.overwrite == plugin._overwrite_qgis_project
    plugin._connected = False
    assert plugin._home_actions().qgis is None


def test_list_qgis_projects_never_in_shared_login(plugin, monkeypatch):
    calls = []
    monkeypatch.setattr(store, "list_visible", lambda conn, log=None: calls.append(1) or [])
    assert plugin._list_qgis_projects() == [] and calls == [1]
    plugin._auth_mode = "shared"
    assert plugin._list_qgis_projects() is None and calls == [1]


def test_actions_without_connection_never_raise(plugin):
    plugin._conn = None
    assert plugin._list_qgis_projects() is None
    assert plugin._delete_qgis_project("Vue").status == store.STATUS_ERROR
    assert plugin._qgis_shares_list("Vue") is None
    assert plugin._apply_qgis_shares("Vue", None).status == store.STATUS_ERROR
    assert plugin._eligible_users(None, "ale", []) is None


def test_deleting_the_opened_project_forgets_it(plugin, monkeypatch):
    monkeypatch.setattr(store, "delete", lambda conn, name, log=None: store.StoreOutcome(store.STATUS_OK))
    plugin._opened_qgis_project = OpenedQgisProject("Vue", 2, None, None, True, True, {})
    assert plugin._delete_qgis_project("Autre").status == store.STATUS_OK
    assert plugin._opened_qgis_project is not None
    assert plugin._delete_qgis_project("Vue").status == store.STATUS_OK
    assert plugin._opened_qgis_project is None


def test_list_db_projects_skips_projet_schema_when_visible_exists(plugin):
    from constructel_bridge_tests.test_bridge19_browser_projects import _ProjectsCursor

    cursor = _ProjectsCursor()
    plugin._conn = SimpleNamespace(cursor=lambda: cursor, closed=False)
    plugin._operators = [WYRE]
    assert [p["schema"] for p in plugin._list_db_projects()] == ["wyre", "public"]
    plugin._projet_caps = pj.ProjetCapabilities(qgis_table=True)          # lot b absent : lecture seule 2.0
    assert [p["schema"] for p in plugin._list_db_projects()] == ["wyre", "public", "projet"]


def test_write_actions_refused_in_shared_login(plugin, monkeypatch):
    # Revue 2.1 (L15) : garde nominative cote plugin, pas seulement l'interface.
    calls = []
    for name in ("delete", "shares_list", "apply_share_plan", "eligible_users"):
        monkeypatch.setattr(store, name, lambda *a, _n=name, **k: calls.append(_n))
    plugin._auth_mode = "shared"
    assert plugin._delete_qgis_project("Vue").status == store.STATUS_ERROR
    assert plugin._qgis_shares_list("Vue") is None and plugin._eligible_users(None, "ale", []) is None
    assert plugin._apply_qgis_shares("Vue", object()).status == store.STATUS_ERROR
    assert calls == []
