"""Real Qt offscreen regressions; QGIS signals are replaced with Qt QObjects."""

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


def _qt_binding():
    """Binding already loaded in this process (never two Qt in one process),
    else PyQt6 (QGIS 4) when installed, else PyQt5 (QGIS 3)."""
    loaded = [name for name in ("PyQt6", "PyQt5") if name in sys.modules]
    for name in loaded or ("PyQt6", "PyQt5"):
        if importlib.util.find_spec(name) is not None:
            return importlib.import_module(name)
    pytest.skip("neither PyQt6 nor PyQt5 is installed")


@pytest.fixture
def native_qt(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    qt = _qt_binding()
    QtCore, QtGui, QtWidgets, sip = (
        importlib.import_module(f"{qt.__name__}.{name}")
        for name in ("QtCore", "QtGui", "QtWidgets", "sip")
    )
    if not hasattr(QtWidgets, "QAction"):
        # Qt6 moved QAction to QtGui; QGIS 4's qgis.PyQt.QtWidgets re-exports it.
        widgets = ModuleType("qgis.PyQt.QtWidgets")
        widgets.__dict__.update(vars(QtWidgets))
        widgets.QAction = QtGui.QAction
        QtWidgets = widgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    class Layer(QtCore.QObject):
        selectionChanged = QtCore.pyqtSignal()

        def __init__(self, kind=0):
            super().__init__()
            self.kind = kind
            self.selection = []

        def type(self):
            return self.kind

        def dataProvider(self):
            return SimpleNamespace(name=lambda: "postgres")

        def providerType(self):
            return "postgres" if self.kind == 0 else "gdal"

        def id(self):
            return "fixture-layer"

        def name(self):
            return "Fixture source"

        def selectedFeatureIds(self):
            return self.selection

        def selectedFeatureCount(self):
            return len(self.selection)

        def selectByIds(self, ids):
            self.selection = ids
            self.selectionChanged.emit()

        def triggerRepaint(self):
            pass

    class Project(QtCore.QObject):
        layersAdded = QtCore.pyqtSignal(list)
        layersRemoved = QtCore.pyqtSignal(list)
        cleared = QtCore.pyqtSignal()

        def __init__(self):
            super().__init__()
            self.layers = {}

        def mapLayers(self):
            return self.layers

        def mapLayer(self, ident):
            return self.layers.get(ident)

    class Iface(QtCore.QObject):
        currentLayerChanged = QtCore.pyqtSignal(object)

        def __init__(self):
            super().__init__()
            self.layer = None
            self.canvas = Mock()
            self.window = QtWidgets.QMainWindow()
            self.window.setCentralWidget(QtWidgets.QWidget())

        def activeLayer(self):
            return self.layer

        def mapCanvas(self):
            return self.canvas

        def setActiveLayer(self, layer):
            self.layer = layer
            self.currentLayerChanged.emit(layer)

        def mainWindow(self):
            return self.window

        def addToolBar(self, title):
            return self.window.addToolBar(title)

        def addPluginToMenu(self, menu, action):
            pass

        def removePluginMenu(self, menu, action):
            pass

        def addDockWidget(self, area, panel):
            self.window.addDockWidget(area, panel)

        def removeDockWidget(self, panel):
            self.window.removeDockWidget(panel)

    project, iface = Project(), Iface()
    core = ModuleType("qgis.core")
    core.QgsProject = SimpleNamespace(instance=lambda: project)
    core.QgsDataSourceUri = object
    for name, module in {
        "qgis": ModuleType("qgis"),
        "qgis.PyQt": qt,
        "qgis.PyQt.QtCore": QtCore,
        "qgis.PyQt.QtGui": QtGui,
        "qgis.PyQt.QtWidgets": QtWidgets,
        "qgis.PyQt.sip": sip,
        "qgis.core": core,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location(
        "plugins.farois_audit_rollback.gui._native_qt_dock",
        Path(__file__).parents[1] / "gui/dockwidget.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    panel = module.FaroisAuditDock(iface)
    iface.window.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, panel)
    yield SimpleNamespace(
        app=app,
        panel=panel,
        project=project,
        iface=iface,
        Layer=Layer,
        sip=sip,
        Qt=QtCore.Qt,
    )
    panel.dispose()
    if not sip.isdeleted(panel):
        sip.delete(panel)
    sip.delete(iface.window)


def test_native_widget_destruction_detaches_project_signals(native_qt):
    q = native_qt
    scope = q.panel._signals
    q.sip.delete(q.panel)
    assert scope.disposed and scope.connections == []
    q.project.layersRemoved.emit(["fixture"])
    q.project.layersAdded.emit([])
    q.project.cleared.emit()
    q.iface.currentLayerChanged.emit(None)
    q.app.processEvents()


def test_native_deleted_combo_ignores_late_callbacks(native_qt):
    q = native_qt
    q.sip.delete(q.panel.layer_combo)
    assert not q.panel.is_usable()
    q.project.layersRemoved.emit([])
    q.iface.currentLayerChanged.emit(None)
    assert q.panel._signals.disposed


def test_native_vector_to_raster_and_deleted_vector(native_qt):
    q = native_qt
    vector = q.Layer()
    q.project.layers[vector.id()] = vector
    q.iface.layer = vector
    q.iface.currentLayerChanged.emit(vector)
    assert q.panel._connected_selection_layer is vector
    q.sip.delete(vector)
    q.project.layers.clear()
    raster = q.Layer(kind=1)
    q.iface.layer = raster
    q.iface.currentLayerChanged.emit(raster)
    q.project.layersRemoved.emit(["fixture-layer"])
    assert q.panel._connected_selection_layer is None


def test_native_dock_can_shrink_below_old_920px_limit(native_qt):
    q = native_qt
    q.iface.window.resize(1000, 700)
    q.iface.window.show()
    q.app.processEvents()
    assert q.panel.minimumWidth() == 320
    assert q.panel.minimumSizeHint().width() <= 380
    q.iface.window.resizeDocks([q.panel], [360], q.Qt.Orientation.Horizontal)
    q.app.processEvents()
    assert q.panel.width() <= 380


def test_native_reopen_recreates_a_dock_with_deleted_children(native_qt):
    q = native_qt
    spec = importlib.util.spec_from_file_location(
        "plugins.farois_audit_rollback._native_qt_plugin",
        Path(__file__).parents[1] / "plugin.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.FaroisAuditDock = type(q.panel)
    plugin = module.FaroisAuditRollback(q.iface)
    plugin.initGui()
    plugin.dock = q.panel
    q.sip.delete(q.panel.layer_combo)
    plugin.show_dock()
    assert plugin.dock is not q.panel and plugin.dock.is_usable()
    assert q.panel._signals.disposed
    plugin.unload()
    plugin.sync_actions()  # a late queued notification during unload is harmless
    q.project.layersAdded.emit([])
    q.app.processEvents()


def setup_history_panel(q, rows):
    q.iface.layer = q.Layer()
    q.panel.repository = SimpleNamespace(
        engine_available=False,
        layer_history=Mock(return_value=rows),
        visible_history=Mock(return_value=rows),
    )
    q.panel._ensure_repository = lambda layer: None
    q.panel._history_context = lambda: (q.iface.layer, "wyre", "zone_drop", None)


def test_native_layer_history_populates_without_selection(native_qt):
    q = native_qt
    rows = [
        dict(
            change_id="fixture-change",
            table_name="zone_drop",
            actor="synthetic",
            changed_at="fixture-date",
            changed_columns=["status"],
            operation="UPDATE",
        )
    ]
    setup_history_panel(q, rows)
    q.panel.cancelable.setChecked(
        True
    )  # old filter must not hide all history without undo engine
    q.panel.load_history()
    assert q.panel.table.rowCount() == 1
    assert q.panel.table.item(0, 1).text() == "synthetic"
    assert "1 entrée(s) chargée(s), 1 affichée(s)" in q.panel.connection_label.text()
    assert not q.panel.cancelable.isChecked() and not q.panel.cancelable.isEnabled()


def _update_row():
    return dict(
        change_id="chg-1",
        table_name="zone_drop",
        actor="synthetic",
        changed_at="fixture-date",
        changed_columns=["label"],
        operation="UPDATE",
        label="L1",
        before_values={"label": "a0", "status": "TODO"},
        after_values={"label": "w1", "status": "TODO"},
    )


def test_native_before_after_column_follows_columns_with_tooltip(native_qt):
    q = native_qt
    setup_history_panel(q, [_update_row()])
    q.panel.load_history()
    headers = q.panel.HEADERS
    col = headers.index("Avant → après")
    assert col == headers.index("Colonnes") + 1
    assert q.panel.table.columnCount() == len(headers)
    item = q.panel.table.item(0, col)
    assert "label : a0 → w1" in item.text()
    assert item.toolTip() == "label : a0 → w1"
    assert q.panel.table.item(0, headers.index("Colonnes")).text() == "label"


def test_native_context_details_opens_field_table_dialog(native_qt, monkeypatch):
    from qgis.PyQt.QtCore import QEvent
    from qgis.PyQt.QtWidgets import QDialog, QMenu

    q = native_qt
    setup_history_panel(q, [_update_row()])
    q.panel.load_history()
    seen = {}

    def run_dialog(dialog):
        table = dialog.table
        seen["headers"] = [
            table.horizontalHeaderItem(i).text() for i in range(table.columnCount())
        ]
        seen["default"] = [table.item(r, 0).text() for r in range(table.rowCount())]
        seen["editable"] = bool(table.item(0, 1).flags() & q.Qt.ItemFlag.ItemIsEditable)
        dialog.show_all.setChecked(True)
        seen["all"] = [table.item(r, 0).text() for r in range(table.rowCount())]
        seen["dialog"] = dialog
        return 0

    monkeypatch.setattr(QDialog, "exec", run_dialog)
    monkeypatch.setattr(
        QMenu,
        "exec",
        lambda menu, pos: next(
            a for a in menu.actions() if a.text() == "Voir les valeurs avant/après"
        ),
    )
    position = q.panel.table.visualItemRect(q.panel.table.item(0, 0)).center()
    q.panel._history_context_menu(position)
    assert seen["headers"] == ["Champ", "Avant", "Après"]
    q.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert q.sip.isdeleted(seen["dialog"])
    assert seen["default"] == ["label"]
    assert seen["all"] == ["label", "status"]
    assert seen["editable"] is False


def test_native_filters_explain_empty_table_and_reset(native_qt):
    q = native_qt
    setup_history_panel(q, [dict(change_id="fixture-change", actor="synthetic")])
    q.panel.user.setText("does-not-match-fixture")
    q.panel.load_history()
    assert q.panel.table.rowCount() == 0
    assert "filtres masquent" in q.panel.connection_label.text()
    q.panel._reset_filters()
    assert q.panel.table.rowCount() == 1


def test_native_all_visible_mode_calls_scoped_repository(native_qt):
    q = native_qt
    setup_history_panel(q, [dict(change_id="fixture-change")])
    q.panel.history_scope.setCurrentIndex(2)
    q.panel.repository.visible_history.assert_called()
    assert q.panel.table.rowCount() == 1
    assert not q.panel.action_states()[0][0]


def test_native_empty_history_explains_scope(native_qt):
    q = native_qt
    setup_history_panel(q, [])
    q.panel.load_history()
    assert q.panel.table.rowCount() == 0
    assert "Aucun changement visible" in q.panel.connection_label.text()


def setup_navigation_panel(q, monkeypatch):
    row = dict(
        change_id="fixture-change",
        schema_name="wyre",
        table_name="zone_drop",
        record_id="00000000-0000-4000-8000-000000000020",
    )
    setup_history_panel(q, [row])
    q.project.layers[q.iface.layer.id()] = q.iface.layer
    q.panel._populate_layers()
    q.panel.table.selectRow(0)
    finder = Mock(return_value=(q.iface.layer, SimpleNamespace(id=lambda: 42)))
    monkeypatch.setitem(
        q.panel._navigate_history_object.__wrapped__.__globals__,
        "find_history_feature",
        finder,
    )
    return finder


def test_native_navigation_state_follows_selected_history_rows(native_qt, monkeypatch):
    q = native_qt
    setup_navigation_panel(q, monkeypatch)
    assert q.panel._navigation_state()[0]
    q.panel.table.clearSelection()
    q.panel.table.setCurrentCell(-1, -1)
    q.panel._update_actions()
    assert not q.panel._navigation_state()[0]


def test_native_select_object_keeps_row_and_ignores_reentrant_refresh(
    native_qt, monkeypatch
):
    q = native_qt
    finder = setup_navigation_panel(q, monkeypatch)
    q.panel.select_history_object()
    finder.assert_called_once()
    assert q.iface.layer.selectedFeatureIds() == [42]
    assert q.panel.table.currentRow() == 0
    assert "Objet sélectionné" in q.panel.navigation_label.text()
    assert not q.panel._navigation_in_progress


def test_native_identify_is_read_only_and_never_starts_editing(native_qt, monkeypatch):
    from qgis.PyQt.QtWidgets import QDialog

    q = native_qt
    setup_navigation_panel(q, monkeypatch)
    context, dialog = Mock(), QDialog(q.panel)
    dialog.setMode = Mock()
    dialog.exec = Mock()
    dialog.deleteLater = Mock()
    context_class = Mock(return_value=context)
    context_class.Mode.IdentifyMode = "fixture-identify-mode"
    gui = ModuleType("qgis.gui")
    gui.QgsAttributeEditorContext = context_class
    gui.QgsAttributeDialog = Mock(return_value=dialog)
    monkeypatch.setitem(sys.modules, "qgis.gui", gui)
    q.panel.identify_history_object()
    assert q.iface.layer.selectedFeatureIds() == [42]
    context.setAttributeFormMode.assert_called_once_with("fixture-identify-mode")
    context.setAllowCustomUi.assert_called_once_with(False)
    dialog.setMode.assert_called_once_with("fixture-identify-mode")
    dialog.exec.assert_called_once()
    dialog.deleteLater.assert_called_once()
    assert not q.panel._navigation_in_progress


def test_native_missing_object_does_not_change_selection(native_qt, monkeypatch):
    from qgis.PyQt.QtWidgets import QMessageBox

    q = native_qt
    finder = setup_navigation_panel(q, monkeypatch)
    finder.side_effect = LookupError("Objet supprimé ou hors périmètre.")
    warning = Mock()
    monkeypatch.setattr(QMessageBox, "warning", warning)
    q.panel.select_history_object()
    warning.assert_called_once()
    assert q.iface.layer.selectedFeatureIds() == []
    assert "Objet supprimé" in q.panel.navigation_label.text()
    assert q.panel.table.rowCount() == 1


def setup_batch_navigation(q, monkeypatch):
    from qgis.PyQt.QtCore import QItemSelectionModel

    finder = setup_navigation_panel(q, monkeypatch)
    first = dict(q.panel.repository.layer_history.return_value[0])
    second = dict(
        first,
        change_id="fixture-second",
        record_id="00000000-0000-4000-8000-000000000021",
    )
    q.panel.repository.layer_history.return_value = [first, second]
    q.panel.load_history()
    for row in (0, 1):
        q.panel.table.selectionModel().select(
            q.panel.table.model().index(row, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
    features = [
        SimpleNamespace(
            id=lambda ident=ident: ident,
            hasGeometry=lambda: True,
            geometry=lambda: SimpleNamespace(isEmpty=lambda: False),
        )
        for ident in (42, 43)
    ]
    q.iface.layer.isSpatial = lambda: True
    finder.side_effect = [(q.iface.layer, feature) for feature in features]
    return finder


def test_native_context_menu_preserves_multiple_rows_and_dispatches_selection(
    native_qt, monkeypatch
):
    from qgis.PyQt.QtWidgets import QMenu

    q = native_qt
    finder = setup_batch_navigation(q, monkeypatch)

    def choose(menu, position):
        assert [a.text() for a in menu.actions()][:3] == [
            "Identifier les objets",
            "Zoomer sur les objets",
            "Sélectionner les objets",
        ]
        assert len(q.panel._selected_history_entries()) == 2
        assert q.panel._context_menu_open
        previous_calls = q.panel.repository.layer_history.call_count
        q.panel._auto_refresh()
        q.panel.load_history()
        assert q.panel.repository.layer_history.call_count == previous_calls
        return menu.actions()[2]

    monkeypatch.setattr(QMenu, "exec", choose)
    position = q.panel.table.visualItemRect(q.panel.table.item(0, 0)).center()
    q.panel._history_context_menu(position)
    assert finder.call_count == 2
    assert q.iface.layer.selectedFeatureIds() == [42, 43]
    assert len(q.panel._selected_history_entries()) == 2
    assert not q.panel._context_menu_open


def test_native_right_click_unselected_row_replaces_context_selection(
    native_qt, monkeypatch
):
    from qgis.PyQt.QtWidgets import QMenu

    q = native_qt
    finder = setup_batch_navigation(q, monkeypatch)
    q.panel.table.clearSelection()
    q.panel.table.selectRow(0)
    selected = []

    def cancel(menu, position):
        selected.extend(e.change_id for e in q.panel._selected_history_entries())
        return None

    monkeypatch.setattr(QMenu, "exec", cancel)
    q.panel._history_context_menu(
        q.panel.table.visualItemRect(q.panel.table.item(1, 0)).center()
    )
    assert selected == ["fixture-second"]
    finder.assert_not_called()


def test_native_context_zoom_frames_selected_features(native_qt, monkeypatch):
    from qgis.PyQt.QtWidgets import QMenu

    q = native_qt
    setup_batch_navigation(q, monkeypatch)
    monkeypatch.setattr(QMenu, "exec", lambda menu, position: menu.actions()[1])
    q.panel._history_context_menu(
        q.panel.table.visualItemRect(q.panel.table.item(0, 0)).center()
    )
    q.iface.canvas.zoomToSelected.assert_called_once_with([q.iface.layer])
    q.iface.canvas.refresh.assert_called_once()
    assert q.iface.layer.selectedFeatureIds() == [42, 43]


def test_native_dock_has_no_push_buttons(native_qt):
    from qgis.PyQt.QtWidgets import QPushButton

    assert native_qt.panel.findChildren(QPushButton) == []


@pytest.mark.parametrize(
    "choice", ["Actualiser l’historique", "Réinitialiser les filtres"]
)
def test_native_empty_table_context_has_refresh_and_reset(
    native_qt, monkeypatch, choice
):
    from qgis.PyQt.QtCore import QPoint
    from qgis.PyQt.QtWidgets import QMenu

    q = native_qt
    refresh, reset = Mock(), Mock()
    monkeypatch.setattr(q.panel, "load_history", refresh)
    monkeypatch.setattr(q.panel, "_reset_filters", reset)

    def choose(menu, position):
        assert [a.text() for a in menu.actions()] == [
            "Actualiser l’historique",
            "Réinitialiser les filtres",
            "Se connecter à Farois…",
        ]
        return next(a for a in menu.actions() if a.text() == choice)

    monkeypatch.setattr(QMenu, "exec", choose)
    q.panel._history_context_menu(QPoint(5, 5))
    assert refresh.call_count == int(choice == "Actualiser l’historique")
    assert reset.call_count == int(choice == "Réinitialiser les filtres")


def test_native_identify_multiple_objects_shows_read_only_forms_in_sequence(
    native_qt, monkeypatch
):
    from qgis.PyQt.QtWidgets import QDialog

    q = native_qt
    setup_batch_navigation(q, monkeypatch)
    dialogs, contexts = [], []

    def make_dialog(*args):
        dialog = QDialog(q.panel)
        dialog.setMode = Mock()
        dialog.exec = Mock()
        dialog.deleteLater = Mock()
        dialogs.append(dialog)
        return dialog

    def make_context():
        context = Mock()
        contexts.append(context)
        return context

    gui = ModuleType("qgis.gui")
    gui.QgsAttributeEditorContext = Mock(side_effect=make_context)
    gui.QgsAttributeEditorContext.Mode.IdentifyMode = "fixture-identify-mode"
    gui.QgsAttributeDialog = Mock(side_effect=make_dialog)
    monkeypatch.setitem(sys.modules, "qgis.gui", gui)
    q.panel.identify_history_object()
    assert len(dialogs) == 2
    assert q.iface.layer.selectedFeatureIds() == [42, 43]
    for dialog, context in zip(dialogs, contexts):
        context.setAttributeFormMode.assert_called_once_with("fixture-identify-mode")
        dialog.setMode.assert_called_once_with("fixture-identify-mode")
        dialog.exec.assert_called_once()


def test_native_zoom_multiple_layers_passes_only_target_layers(native_qt, monkeypatch):
    q = native_qt
    finder = setup_batch_navigation(q, monkeypatch)
    source = q.iface.layer
    target = q.Layer()
    target.id = lambda: "fixture-target"
    target.isSpatial = lambda: True
    feature = SimpleNamespace(
        id=lambda: 43,
        hasGeometry=lambda: True,
        geometry=lambda: SimpleNamespace(isEmpty=lambda: False),
    )
    finder.side_effect = [(source, feature), (target, feature)]
    q.panel.zoom_history_objects()
    q.iface.canvas.zoomToSelected.assert_called_once_with([source, target])
    assert source.selectedFeatureIds() == [43] and target.selectedFeatureIds() == [43]
    q.iface.canvas.refresh.assert_called_once()


def test_native_zoom_without_geometry_does_not_change_selection(native_qt, monkeypatch):
    from qgis.PyQt.QtWidgets import QMessageBox

    q = native_qt
    finder = setup_navigation_panel(q, monkeypatch)
    q.iface.layer.isSpatial = lambda: False
    monkeypatch.setattr(QMessageBox, "warning", Mock())
    q.panel.zoom_history_objects()
    finder.assert_called_once()
    assert q.iface.layer.selectedFeatureIds() == []
    assert "géométrie" in q.panel.navigation_label.text()
    q.iface.canvas.zoomToSelected.assert_not_called()


def test_native_batch_missing_object_leaves_layer_selection_unchanged(
    native_qt, monkeypatch
):
    from qgis.PyQt.QtWidgets import QMessageBox

    q = native_qt
    finder = setup_batch_navigation(q, monkeypatch)
    finder.side_effect = [
        (q.iface.layer, SimpleNamespace(id=lambda: 42)),
        LookupError("Objet supprimé"),
    ]
    monkeypatch.setattr(QMessageBox, "warning", Mock())
    q.panel.select_history_object()
    assert q.iface.layer.selectedFeatureIds() == []
    assert len(q.panel._selected_history_entries()) == 2


def test_native_refresh_preserves_all_selected_history_rows(native_qt, monkeypatch):
    q = native_qt
    setup_batch_navigation(q, monkeypatch)
    q.panel.load_history()
    assert len(q.panel._selected_history_entries()) == 2


def test_native_context_identify_is_dispatched(native_qt, monkeypatch):
    from qgis.PyQt.QtWidgets import QMenu

    q = native_qt
    setup_navigation_panel(q, monkeypatch)
    identify = Mock()
    monkeypatch.setattr(q.panel, "identify_history_object", identify)
    monkeypatch.setattr(QMenu, "exec", lambda menu, position: menu.actions()[0])
    q.panel._history_context_menu(
        q.panel.table.visualItemRect(q.panel.table.item(0, 0)).center()
    )
    identify.assert_called_once()


def test_native_context_menu_invalid_uuid_actions_disabled(native_qt, monkeypatch):
    from qgis.PyQt.QtWidgets import QMenu

    q = native_qt
    setup_history_panel(
        q,
        [dict(change_id="fixture-change", schema_name="wyre", table_name="zone_drop")],
    )
    q.panel.load_history()
    q.panel.table.selectRow(0)

    def cancel(menu, position):
        assert all(
            not a.isEnabled() and "UUID" in a.toolTip() for a in menu.actions()[:3]
        )
        return None

    monkeypatch.setattr(QMenu, "exec", cancel)
    q.panel._history_context_menu(
        q.panel.table.visualItemRect(q.panel.table.item(0, 0)).center()
    )


def test_native_context_menu_offers_farois_login(native_qt, monkeypatch):
    q = native_qt
    from qgis.PyQt.QtCore import QPoint
    from qgis.PyQt.QtWidgets import QMenu

    seen = []

    def fake_exec(menu, *args):
        seen.extend(action.text() for action in menu.actions() if action.text())
        return None

    monkeypatch.setattr(QMenu, "exec", fake_exec)
    q.panel._history_context_menu(QPoint(0, 0))
    assert "Se connecter à Farois…" in seen


def test_native_admin_undo_actions_are_enabled_in_layer_scope(native_qt, monkeypatch):
    from qgis.PyQt.QtWidgets import QMenu

    q = native_qt
    row = dict(
        change_id="fixture-change",
        transaction_id="00000000-0000-4000-8000-000000000010",
        schema_name="wyre",
        table_name="zone_drop",
        operation="DELETE",
        in_engine=True,
    )
    setup_history_panel(q, [row])
    q.panel.repository.engine_available = True
    q.panel.api = SimpleNamespace(
        connected=True,
        is_admin=True,
        profile=SimpleNamespace(email="admin@constructel.example.be", role="ADMIN"),
    )
    assert q.panel.history_scope.currentData() == "layer"
    assert q.iface.layer.selectedFeatureIds() == []
    q.panel.load_history()
    q.panel.table.selectRow(0)
    seen = {}

    def capture(menu, position):
        seen.update({a.text(): (a.isEnabled(), a.toolTip()) for a in menu.actions()})
        return None

    monkeypatch.setattr(QMenu, "exec", capture)
    q.panel._history_context_menu(
        q.panel.table.visualItemRect(q.panel.table.item(0, 0)).center()
    )
    assert seen["Annuler la modification"][0], seen["Annuler la modification"][1]
    assert seen["Annuler la transaction"][0], seen["Annuler la transaction"][1]
    q.panel.api = None  # sans session admin : mode objet toujours exigé
    assert not q.panel.action_states()[0][0]
    assert "mode Objet sélectionné" in q.panel.action_states()[0][1]


def drive_login_dialog(monkeypatch, fill):
    """Remplace exec : relève l'état initial du dialogue puis le remplit."""
    from qgis.PyQt.QtWidgets import QCheckBox, QDialog, QLineEdit

    seen = {}

    def fake_exec(dialog):
        edits = dialog.findChildren(QLineEdit)
        password = next(e for e in edits if e.echoMode() == QLineEdit.EchoMode.Password)
        email = next(e for e in edits if e is not password)
        boxes = dialog.findChildren(QCheckBox)
        seen.update(email=email.text(), boxes=[(b.text(), b.isChecked()) for b in boxes],
                    tips=[b.toolTip() for b in boxes], password=password)
        fill(email, password, boxes)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    return seen


def test_native_login_dialog_offers_remember_me_checked_by_default(native_qt, monkeypatch):
    from plugins.farois_audit_rollback.gui.login_dialog import ask_credentials

    seen = drive_login_dialog(monkeypatch, lambda email, password, boxes: password.setText("pw"))
    result = ask_credentials(native_qt.panel, "simon@constructel.example.be")
    assert seen["email"] == "simon@constructel.example.be"
    assert seen["boxes"] == [("Se souvenir de moi (30 jours)", True)]
    assert "mot de passe maître" in seen["tips"][0]
    assert result == ("simon@constructel.example.be", "pw", True)
    assert seen["password"].text() == ""  # champ vidé dès la fermeture


def test_native_login_dialog_remember_me_can_be_declined(native_qt, monkeypatch):
    from plugins.farois_audit_rollback.gui.login_dialog import ask_credentials

    def fill(email, password, boxes):
        password.setText("pw")
        boxes[0].setChecked(False)

    seen = drive_login_dialog(monkeypatch, fill)
    assert ask_credentials(native_qt.panel, "a@constructel.example.be") == (
        "a@constructel.example.be", "pw", False)
    seen = drive_login_dialog(monkeypatch, lambda email, password, boxes: password.setText("pw"))
    assert ask_credentials(native_qt.panel, "a@constructel.example.be", remember=False)[2] is False
    assert seen["boxes"] == [("Se souvenir de moi (30 jours)", False)]


def test_native_auto_connect_reports_in_the_banner_without_any_dialog(native_qt, monkeypatch):
    from qgis.PyQt.QtWidgets import QMessageBox
    from plugins.farois_audit_rollback.api.farois_client import FaroisNotAuthenticated
    from plugins.farois_audit_rollback.api.session_store import MemorySessionStore

    for name in ("critical", "warning", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, Mock(side_effect=AssertionError(name)))
    q = native_qt
    store = MemorySessionStore()
    store.save("simon@constructel.example.be", "rt-1")
    q.panel.store = store
    q.panel.api = SimpleNamespace(
        connected=False, profile=None, last_email="",
        resume=Mock(side_effect=FaroisNotAuthenticated("Session expirée", status=401)),
    )
    q.panel.auto_connect_farois()
    assert q.panel.api_label.text() == "Farois : session expirée — reconnectez-vous (clic droit)"
    assert store.load() is None


def test_native_context_menu_shows_the_refusal_reason_in_the_disabled_undo_texts(
    native_qt, monkeypatch
):
    from qgis.PyQt.QtWidgets import QMenu

    q = native_qt
    setup_history_panel(
        q,
        [dict(change_id="fixture-change", schema_name="wyre", table_name="zone_drop")],
    )
    q.panel.load_history()
    q.panel.table.selectRow(0)
    full = q.panel.action_states()[0][1]
    seen = {}

    def capture(menu, position):
        seen["tips"] = menu.toolTipsVisible()
        seen["actions"] = [(a.text(), a.isEnabled(), a.toolTip()) for a in menu.actions()]
        return None

    monkeypatch.setattr(QMenu, "exec", capture)
    q.panel._history_context_menu(
        q.panel.table.visualItemRect(q.panel.table.item(0, 0)).center()
    )
    assert seen["tips"]
    short = full if len(full) <= 70 else full[:69] + "…"
    by_prefix = {a[0].split(" — ")[0]: a for a in seen["actions"]}
    for label in ("Annuler la modification", "Annuler la transaction"):
        text, enabled, tip = by_prefix[label]
        assert not enabled and tip == full
        assert text == f"{label} — {short}"
