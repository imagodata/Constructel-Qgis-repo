"""Fumee Qt reel (2.0.1, versions 2.0.2) : la fenetre d'accueil construite avec de VRAIS
widgets PyQt5 (rendu hors ecran), sur les stubs qgis.core habituels.

Les tests pytest tournent sur des doublures de widgets ; elles ne voient pas
les differences de types de Qt reel (ex. QTreeWidgetItem non hachable, cause
du plantage de la 2.0.0). Ce script parcourt les quatre pages et les gestes
principaux. Lancement manuel (non collecte par pytest) :

    QT_QPA_PLATFORM=offscreen python3 plugin-repo/packages/constructel_bridge_tests/smoke_real_qt.py

Sortie : « SMOKE OK » ou la trace de l'erreur.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "stubs"))
sys.path.insert(0, str(HERE.parent))

import qgis  # noqa: E402  (stub)
import qgis.PyQt  # noqa: E402,F401
from PyQt5 import QtCore, QtGui, QtNetwork, QtWidgets, QtXml  # noqa: E402

# Les modules du plugin importent qgis.PyQt.* : on les branche sur PyQt5.
for name, module in (("QtCore", QtCore), ("QtGui", QtGui), ("QtWidgets", QtWidgets),
                     ("QtNetwork", QtNetwork), ("QtXml", QtXml)):
    sys.modules[f"qgis.PyQt.{name}"] = module
    setattr(qgis.PyQt, name, module)

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

# Imports qgis.* non couverts par les stubs : classes nommees vides (meme
# recette que la fixture pi), sauf QgsTask, rendu inerte pour le Diagnostic.
import ast  # noqa: E402
import importlib  # noqa: E402
from types import ModuleType  # noqa: E402

import qgis.core as _core  # noqa: E402


class _InertTask:
    @staticmethod
    def fromFunction(*_args, **_kwargs):
        return _InertTask()


if not hasattr(_core, "QgsTask"):
    _core.QgsTask = _InertTask
_manager = type("_TaskManager", (), {"addTask": lambda self, task: None})()
if not hasattr(_core.QgsApplication, "taskManager"):
    _core.QgsApplication.taskManager = staticmethod(lambda: _manager)
for _path in (HERE.parent / "constructel_bridge").glob("*.py"):
    for _node in ast.walk(ast.parse(_path.read_text(encoding="utf-8"))):
        if not (isinstance(_node, ast.ImportFrom) and (_node.module or "").startswith("qgis")):
            continue
        if _node.module.startswith("qgis.PyQt"):
            continue
        try:
            _module = importlib.import_module(_node.module)
        except ImportError:
            _module = ModuleType(_node.module)
            sys.modules[_node.module] = _module
        for _alias in _node.names:
            if not hasattr(_module, _alias.name):
                setattr(_module, _alias.name, type(_alias.name, (), {}))

_utils = sys.modules["qgis.utils"]
for _name in ("available_plugins", "active_plugins"):
    if not hasattr(_utils, _name):
        setattr(_utils, _name, [])

from constructel_bridge import bridge_home_model as hm  # noqa: E402
from constructel_bridge import bridge_presets as bp  # noqa: E402
from constructel_bridge.bridge_diagnostic import PluginSummary  # noqa: E402
from constructel_bridge.bridge_operators import OperatorInfo  # noqa: E402
from constructel_bridge.bridge_project_init import LoadedCounts  # noqa: E402
from constructel_bridge import bridge_projets as pj  # noqa: E402
from constructel_bridge.bridge_qgis_projects import EligibleUser  # noqa: E402

WYRE = OperatorInfo("WYRE", "Wyre", "wyre")
ORANGE = OperatorInfo("ORANGE", "Orange", "orange")
LOG: list = []


def snapshot(connected=True, operators=(WYRE, ORANGE)):
    return hm.HomeSnapshot(
        connected=connected, header="a.leroy · 10 MRO" if connected else "", operators=operators,
        counts=LoadedCounts({}, 0, 0), labels={"wyre": "Wyre", "orange": "Orange"},
        project_suffix=None, last_suffix=False, plugin_summary=PluginSummary(5, 6, 1),
        plugin_version="2.0.2", project_operators=(), last_selection=None, user_presets=(),
        checkin=hm.CheckinState(PluginSummary(5, 6, 1), True, False),
        login="a.leroy" if connected else "", email="a.leroy@example.invalid" if connected else "",
    )


STATE = {"snap": snapshot()}

# --- Bridge 2.1 -------------------------------------------------------------------------------
FULL_CAPS = pj.ProjetCapabilities(True, True, True, True, True, True, True)
GOFIBER = pj.ProjetInfo("b3f1", "GOFIBER", "GoFiber", "WYRE", (
    pj.ProjetLayer("geofiber_asbuilt_depth_connectors", "Connecteurs", "Profondeur As-Built", "default", "geom", 10),
    pj.ProjetLayer("geofiber_asbuilt_depth_points", "Points", "Profondeur As-Built", "default", "geom", 20),
    pj.ProjetLayer("geofiber_meta", "Métadonnées", None, "default", None, 30),
))
MINE = None  # pose plus bas (QgisProjectRow)
LIBRE = pj.ProjetInfo("c4", "LIBRE", "Libre", None, (pj.ProjetLayer("t", "T", None, "default", None, 0),))
PEOPLE = [EligibleUser("a.leroy", "Alice Leroy", "BE"), EligibleUser("a.lemaire", None, "ADMIN"),
          EligibleUser("b.alex", "Bernard Alex", None)]


def snapshot21(nominative=True, capabilities=FULL_CAPS):
    import dataclasses

    return dataclasses.replace(snapshot(), projets=(GOFIBER, LIBRE), capabilities=capabilities,
                               nominative=nominative, operator_code_labels=(("WYRE", "Wyre"), ("ORANGE", "Orange")),
                               counts=LoadedCounts({}, 0, 0, 2))


def _mine_row():
    from constructel_bridge.bridge_qgis_projects import QgisProjectRow

    return QgisProjectRow("Vue Ixelles", "a.leroy", "b3f1", "GOFIBER", "GoFiber", False, False, "BE", 3,
                          "2026-11-19T10:00:00", "a.leroy", True, True, 2, "ma vue")


def qgis_actions(rows=None):
    from constructel_bridge.bridge_qgis_projects import QgisProjectRow, ShareRow
    from constructel_bridge import bridge_qgis_store as qs

    shared = QgisProjectRow("Vue de Bob", "b.martin", None, None, None, False, False, "ADMIN", 1,
                            None, "b.martin", False, True, None, "")
    published = QgisProjectRow("Référence GoFiber", "admin", "b3f1", "GOFIBER", "GoFiber", True, True, "ADMIN", 9,
                               None, "admin", False, False, None, "publiée")
    rows = [MINE, shared, published] if rows is None else rows
    ok = qs.StoreOutcome(qs.STATUS_OK, value=1)
    return hm.QgisProjectActions(
        list_visible=lambda: LOG.append("list_visible") or list(rows),
        open=lambda row: LOG.append(("open_qgis", row.name)) or True,
        save=lambda request: ok,
        overwrite=lambda request: ok,
        delete=lambda name: LOG.append(("delete", name)) or ok,
        shares_list=lambda name: [ShareRow("b.martin", "Bob Martin", "ADMIN", True, True),
                                  ShareRow("c.vieux", None, None, False, False)],
        apply_shares=lambda name, plan: LOG.append(("apply_shares", name)) or ok,
        eligible_users=lambda code, prefix, exclude: search_people(prefix, exclude),
        current_state=lambda: hm.CurrentProjectState("Ixelles", 4, "a.leroy"),
    )


def search_people(prefix, exclude):
    LOG.append(("search", prefix, tuple(exclude)))
    return [p for p in PEOPLE if p.username not in exclude]


def smoke_21(dialog) -> None:
    """Scenario de la Task 21 du plan 2.1 : chaque nouvel ecran construit,
    affiche hors ecran, pilote puis ferme, sans exec() ; les boites
    QMessageBox repondent tout de suite (Yes / Ok)."""
    global MINE
    MINE = _mine_row()
    box = QtWidgets.QMessageBox
    for name in ("question", "information", "warning", "critical"):
        answer = box.StandardButton.Yes if name == "question" else box.StandardButton.Ok
        setattr(box, name, staticmethod(lambda *a, _answer=answer, **k: _answer))
    """Ecrans 2.1 (Task 21) : rangee Projets metier, selecteur de personnes."""
    from constructel_bridge.bridge_people_picker import PeoplePicker

    # 1. Page Charger : GoFiber avec « Aucun », puis avec Wyre et Orange.
    STATE["snap"] = snapshot21()
    dialog.render()
    dialog.show_page("load")
    app.processEvents()
    load = dialog._pages["load"]
    load._none_button.click()
    load._projet_buttons["GOFIBER"].click()
    app.processEvents()
    tree = load._selection._tree
    captions = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert any(c.startswith("GoFiber") for c in captions), captions
    load._operator_buttons["wyre"].click()
    load._operator_buttons["orange"].click()
    load._projet_buttons["LIBRE"].click()
    app.processEvents()
    assert set(load._selection.selection().projet) == {"GOFIBER", "LIBRE"}
    load._load_button.click()            # load factice rend 0
    app.processEvents()

    # Selecteur de personnes (enregistrer / partager).
    picker = PeoplePicker(search_people, None, excluded=("x.deja",))
    picker.show()
    picker.input.setText("ale")
    picker.timer.timeout.emit()
    app.processEvents()
    assert picker._model.stringList(), "modele du completer vide"
    picker.choose(PEOPLE[0])
    picker.choose(PEOPLE[1])
    app.processEvents()
    combo = picker.list.itemWidget(picker.list.topLevelItem(0), 1)
    combo.setCurrentIndex(1)
    assert picker.chosen() == (("a.leroy", True), ("a.lemaire", False)), picker.chosen()
    picker.list.itemWidget(picker.list.topLevelItem(1), 2).click()
    app.processEvents()
    assert picker.chosen() == (("a.leroy", True),)
    picker.close()

    # 3. Dialogue « Enregistrer le projet courant… ».
    from constructel_bridge import bridge_qgis_dialogs as qd
    from constructel_bridge import bridge_qgis_store as qs
    from constructel_bridge.bridge_project_safety import Finding

    state = hm.CurrentProjectState("Ixelles", 4, "a.leroy")
    save = qd.SaveDialog((GOFIBER, LIBRE), None, state, FULL_CAPS,
                         lambda code, prefix, exclude: search_people(prefix, exclude), None)
    save.show()
    app.processEvents()
    assert save.objectName() == "bridgeHome"
    width, height = save.width(), save.height()
    assert width <= 640 and height <= 560, (width, height)
    save.name_edit.setText("Vue Ixelles / GoFiber")
    save.projet_combo.setCurrentIndex(1)
    save.people_radio.setChecked(True)
    app.processEvents()
    save.picker.input.setText("ale")
    save.picker.timer.timeout.emit()
    save.picker.choose(PEOPLE[0])
    save.picker.choose(PEOPLE[2])
    save.picker.list.itemWidget(save.picker.list.topLevelItem(1), 1).setCurrentIndex(1)
    request = save.request()
    assert request.visibility == hm.VISIBILITY_PEOPLE and request.projet_code == "GOFIBER", request
    assert request.people == (("a.leroy", False), ("b.alex", True)), request.people
    save.show_outcome(qs.StoreOutcome(qs.STATUS_NAME_TAKEN), "a.leroy")
    save.show_outcome(qs.StoreOutcome("unsafe", value=(Finding("macros"), Finding("action", "Points", "Py (type=1)"))),
                      "a.leroy")
    app.processEvents()
    save.reject()

    # 4. Dialogue de conflit (creation puis mise a jour) : chacun des trois boutons.
    for creating in (True, False):
        for button in ("rename_button", "overwrite_button", "cancel_button"):
            conflict = qd.ConflictDialog("Vue", creating, "version courante 5, modifiee le 2026-11-19 par bob")
            conflict.show()
            app.processEvents()
            assert conflict.cancel_button.isDefault()
            getattr(conflict, button).click()
            app.processEvents()
            LOG.append(("conflict", creating, conflict.choice()))

    # 5. Dialogue « Partager… » sur un de mes projets, avec une ligne inoperante.
    from constructel_bridge.bridge_qgis_projects import ShareRow

    share_actions = qgis_actions()
    share = qd.ShareDialog(MINE, share_actions, FULL_CAPS, None)
    share.show()
    app.processEvents()
    assert share.objectName() == "bridgeHome" and share.who.topLevelItemCount() == 2
    assert share.width() <= 640 and share.height() <= 560, (share.width(), share.height())
    assert share.who.topLevelItem(1).font(0).italic()          # ligne inoperante
    share.who.itemWidget(share.who.topLevelItem(0), 1).setCurrentIndex(0)
    share.who.itemWidget(share.who.topLevelItem(1), 2).click()
    share.projet_box.setChecked(True)
    share.picker.choose(PEOPLE[0])
    plan = share.plan()
    assert plan.share_project is True and plan.unshare == ("c.vieux",), plan
    share.apply()
    app.processEvents()

    # 6. Confirmation de suppression (reponse factice, puis QMessageBox.question remplacee).
    assert qd.confirm_delete(None, "Vue", ask=lambda title, text: LOG.append(("ask", title)) or True)
    assert qd.confirm_delete(None, "Vue")

    # 2. Page Projets QGIS 2.1 : trois sections, selection de « mien », recherche.
    from constructel_bridge.bridge_home import HomeDialog
    import dataclasses

    STATE["snap"] = snapshot21()
    home = HomeDialog(dataclasses.replace(actions(), qgis=qgis_actions()), None)
    home.resize(1100, 700)
    home.show()
    home.show_page("projects")
    app.processEvents()
    page = home._pages["projects"]
    assert page._mode == "qgis", page._mode
    assert page._tree.topLevelItemCount() == 3
    assert_names_fit(page._tree, 3)
    mine_section = page._tree.topLevelItem(0)
    page._tree.setCurrentItem(mine_section.child(0))
    app.processEvents()
    assert page._share_button.isEnabled() and page._delete_button.isEnabled()
    page._search.setText("gofib")
    app.processEvents()
    assert_names_fit(page._tree, 3)
    page._search.setText("")
    app.processEvents()
    assert_names_fit(page._tree, 3)
    page._delete_selected(ask=lambda title, text: True) if page._selected_own_row() else None
    app.processEvents()

    # 7. Login partage puis base sans capacites : rendu et page Projets.
    for snap21 in (snapshot21(nominative=False), snapshot21(capabilities=pj.NO_CAPABILITIES)):
        STATE["snap"] = snap21
        home.render()
        home.show_page("projects")
        app.processEvents()
        LOG.append(("mode", home._pages["projects"]._mode))
        tree = home._pages["projects"]._tree
        assert_names_fit(tree, 3 if home._pages["projects"]._mode == "nominative" else 2)

    # 8. Changement de langue EN puis PT, page Projets affichee.
    STATE["snap"] = snapshot21()
    home.render()
    home.show_page("projects")
    for code in ("en", "pt"):
        home._lang_buttons[code].click()
        app.processEvents()
    home.reject()
    app.processEvents()


def assert_names_fit(tree, columns: int) -> None:
    """En-tetes visibles et colonne 0 assez large pour chaque nom affiche
    (sections, groupes, projets) : aucun nom tronque."""
    assert not tree.isHeaderHidden() and tree.columnCount() == columns, (tree.isHeaderHidden(), tree.columnCount())
    labels = [tree.headerItem().text(c) for c in range(columns)]
    assert all(labels), labels
    metrics = tree.fontMetrics()
    iterator = QtWidgets.QTreeWidgetItemIterator(tree)
    while iterator.value() is not None:
        item = iterator.value()
        depth, parent = 1, item.parent()
        while parent is not None:
            depth, parent = depth + 1, parent.parent()
        visible = all(p.isExpanded() for p in _ancestors(item))
        need = metrics.horizontalAdvance(item.text(0)) + depth * tree.indentation()
        if visible:
            assert tree.columnWidth(0) >= need, (item.text(0), tree.columnWidth(0), need)
        iterator += 1
    LOG.append(("columns", labels, tree.columnWidth(0)))


def _ancestors(item):
    parent = item.parent()
    while parent is not None:
        yield parent
        parent = parent.parent()


def actions():
    return hm.HomeActions(
        snapshot=lambda: STATE["snap"],
        connect=lambda: LOG.append("connect"),
        load=lambda *a: LOG.append(("load", len(a))) or 0,
        list_projects=lambda: [{"name": "Ixelles", "schema": "wyre", "description": "essai", "updated": ""},
                               {"name": "Gofiber", "schema": "projet", "description": "", "updated": ""}],
        open_project=lambda schema, name: LOG.append(("open", schema, name)) or True,
        diagnostic_inputs=lambda: ("connecte (essai)", [], {"host": "127.0.0.1", "port": 9, "cafile": "",
                                                           "installed_version": "2.0.2"}),
        diagnostic_action=lambda check: [],
        configure_sharing=lambda kind: LOG.append(("configure", kind)) or "ok",
        make_wizard=lambda parent: QtWidgets.QWizard(parent),
        set_language=lambda code: LOG.append(("lang", code)),
        save_presets=lambda presets: LOG.append(("presets", len(presets))),
    )


def smoke_211_projet_only() -> None:
    """2.1.1 : login « projet seul » (aucun operateur, scope PROJET, groupe
    ftth_reader_communs) : GoFiber coche avec la tuile OSIRIS ; la couche des
    zones gelees est servie par la vue osiris.v_frozen_zones_communs, puis
    reconnue « deja chargee » (grisee) par le vrai arbre Qt."""
    import dataclasses

    from _pytest.monkeypatch import MonkeyPatch

    from constructel_bridge import bridge_project_init as bpi
    from constructel_bridge.bridge_home import HomeDialog
    from constructel_bridge_tests.fakes19 import install_fake_project

    patch = MonkeyPatch()
    try:
        project = install_fake_project(bpi, patch)
        fallback = frozenset({"osiris_frozen"})          # decision de connexion : table illisible, vue lisible
        loads = []

        def load(operators, selection, basemaps, styles, suffix):
            count = 0
            for schema, keys in selection.load_plan() or [(None, frozenset(bp.ALWAYS_KEYS))]:
                count += bpi.init_project({}, "", set(keys), add_basemap=False, apply_styles=False,
                                          operator=None, fallback_keys=fallback)
            for code, tables in selection.projet.items():
                count += bpi.load_projet_layers({}, "", GOFIBER, tables, False)
            loads.append((tuple(operators), count))
            return count

        STATE["snap"] = dataclasses.replace(snapshot21(), operators=(), header="ext.user · projet GOFIBER",
                                            counts=LoadedCounts({}, 0, 0))
        home = HomeDialog(dataclasses.replace(actions(), load=load, qgis=qgis_actions()), None)
        home.show()
        home.show_page("load")
        app.processEvents()
        page = home._pages["load"]
        assert page._operator_buttons == {} and page._none_button.isChecked()
        page._projet_buttons["GOFIBER"].click()
        page._selection.toggle_tile("osiris")
        app.processEvents()
        assert ("osiris_frozen" in page._selection.selection().common), page._selection.selection()
        page._load_button.click()
        app.processEvents()
        assert loads and loads[0][0] == () and loads[0][1] >= 1, loads
        assert project.count_pg("osiris", "v_frozen_zones_communs") == 1, "zones gelees non servies par la vue"
        assert project.count_pg("osiris", "frozen_zones") == 0
        # Fenetre rouverte : la couche chargee depuis la vue est grisee (T9-c2b).
        home = HomeDialog(dataclasses.replace(actions(), load=load, qgis=qgis_actions()), None)
        home.show()
        home.show_page("load")
        app.processEvents()
        item = home._pages["load"]._selection._items[(None, "osiris_frozen")]
        assert item.isDisabled() and item.checkState(0) == QtCore.Qt.CheckState.Unchecked
        assert "osiris_frozen" not in home._pages["load"]._selection.selection().common
        home.reject()
        app.processEvents()
        LOG.append(("projet_only", loads[0][1]))
    finally:
        patch.undo()


def smoke_disquette() -> None:
    """Disquette d'un projet en base : writeProject du stockage avec un VRAI
    QIODevice (QBuffer) et un vrai QByteArray (conversion en octets) ; la base
    QgsProjectStorage reste une doublure (pas de QGIS ici)."""
    import io
    import zipfile

    from constructel_bridge import bridge_db_save as dbs

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Vue.qgs", "<qgis/>")
    archive = buf.getvalue()
    device = QtCore.QBuffer()
    device.setData(QtCore.QByteArray(archive))
    assert device.open(QtCore.QIODevice.OpenModeFlag.ReadOnly)
    received = []

    class _Context:
        def __init__(self):
            self.messages = []

        def pushMessage(self, message, level=None):  # noqa: N802
            self.messages.append(message)

    storage = dbs.storage_class()(lambda uri, data: received.append((uri, data)) or (True, ""))
    uri = dbs.bridge_uri("Vue Ixelles / lot 2")
    assert storage.writeProject(uri, device, _Context()) is True
    assert received == [(uri, archive)] and isinstance(received[0][1], bytes)
    refused = dbs.storage_class()(lambda uri, data: (False, "conflit"))
    device.seek(0)
    context = _Context()
    assert refused.writeProject(uri, device, context) is False and context.messages == ["conflit"]
    LOG.append(("disquette", len(archive)))


def main() -> int:
    from constructel_bridge.bridge_home import HomeDialog

    dialog = HomeDialog(actions(), None)
    dialog.show()
    app.processEvents()

    load = dialog._pages["load"]
    # Perimetre : Orange en plus, puis « Aucun », puis Wyre a nouveau.
    load._operator_buttons["orange"].click()
    load._none_button.click()
    load._operator_buttons["wyre"].click()
    selection = load._selection
    for tile in bp.OPERATOR_TILES + bp.COMMON_TILES:
        selection.toggle_tile(tile)
    selection.set_show_expert(True)
    selection.set_row("common", False)
    for item in list(selection._items.values())[:3]:
        item.setCheckState(0, QtCore.Qt.CheckState.Checked)
    assert isinstance(selection.selection(), bp.LayerSelection)
    load._load_button.click()            # load rend 0 : la fenetre se redessine
    app.processEvents()

    for page in ("projects", "checkin", "diagnostic", "load"):
        dialog.show_page(page)
        app.processEvents()

    projects = dialog._pages["projects"]
    projects._search.setText("ixe")
    app.processEvents()

    dialog._lang_buttons["en"].click()   # changement de langue : redessin complet
    app.processEvents()

    smoke_21(dialog)
    smoke_211_projet_only()
    smoke_disquette()

    STATE["snap"] = snapshot(connected=False, operators=())
    dialog.render()
    app.processEvents()

    dialog.reject()
    app.processEvents()
    print("SMOKE OK", [entry for entry in LOG if isinstance(entry, tuple)][:6],
          [entry for entry in LOG if isinstance(entry, tuple) and entry[0] in ("mode", "projet_only", "disquette")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
