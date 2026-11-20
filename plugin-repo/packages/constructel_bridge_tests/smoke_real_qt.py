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
LIBRE = pj.ProjetInfo("c4", "LIBRE", "Libre", None, (pj.ProjetLayer("t", "T", None, "default", None, 0),))
PEOPLE = [EligibleUser("a.leroy", "Alice Leroy", "BE"), EligibleUser("a.lemaire", None, "ADMIN"),
          EligibleUser("b.alex", "Bernard Alex", None)]


def snapshot21(nominative=True, capabilities=FULL_CAPS):
    import dataclasses

    return dataclasses.replace(snapshot(), projets=(GOFIBER, LIBRE), capabilities=capabilities,
                               nominative=nominative, operator_code_labels=(("WYRE", "Wyre"), ("ORANGE", "Orange")),
                               counts=LoadedCounts({}, 0, 0, 2))


def search_people(prefix, exclude):
    LOG.append(("search", prefix, tuple(exclude)))
    return [p for p in PEOPLE if p.username not in exclude]


def smoke_21(dialog) -> None:
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

    STATE["snap"] = snapshot(connected=False, operators=())
    dialog.render()
    app.processEvents()

    dialog.reject()
    app.processEvents()
    print("SMOKE OK", [entry for entry in LOG if isinstance(entry, tuple)][:6])
    return 0


if __name__ == "__main__":
    sys.exit(main())
