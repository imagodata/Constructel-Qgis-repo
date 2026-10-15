"""Headless checks of toolbar wiring and rollback dispatch using Qt/QGIS mocks."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from plugins.farois_audit_rollback.gui.history_model import HistoryEntry, HistoryModel

TX = "00000000-0000-4000-8000-000000000010"


class Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self):
        for slot in self.slots:
            slot()


class Action:
    def __init__(self, text, parent):
        self.text, self.triggered, self.enabled = text, Signal(), True

    def setEnabled(self, enabled):
        self.enabled = enabled

    def setToolTip(self, text):
        self.tooltip = text

    def setIcon(self, icon):
        self.icon = icon

    def deleteLater(self):
        pass


class Icon:
    def __init__(self, path):
        self.path = path


@pytest.fixture
def qt(monkeypatch):
    widgets = ModuleType("qgis.PyQt.QtWidgets")
    for name in (
        "QDockWidget",
        "QWidget",
        "QVBoxLayout",
        "QHBoxLayout",
        "QPushButton",
        "QLineEdit",
        "QCheckBox",
        "QTableWidget",
        "QTableWidgetItem",
        "QComboBox",
        "QLabel",
        "QGroupBox",
        "QGridLayout",
        "QSizePolicy",
        "QMenu",
    ):
        setattr(widgets, name, object)
    widgets.QAction = Action
    widgets.QMessageBox = SimpleNamespace(
        Yes=1,
        No=2,
        question=Mock(return_value=1),
        warning=Mock(),
        critical=Mock(),
        information=Mock(),
    )
    widgets.QInputDialog = SimpleNamespace(
        getText=Mock(return_value=("test reason", True))
    )
    core = ModuleType("qgis.PyQt.QtCore")
    core.Qt = SimpleNamespace(ToolButtonTextOnly=0, RightDockWidgetArea=2, gray=3)
    core.QTimer = object
    core.QItemSelectionModel = object
    core.pyqtSignal = Signal
    core.QSize = lambda w, h: (w, h)
    gui = ModuleType("qgis.PyQt.QtGui")
    gui.QIcon = Icon
    sip_module = ModuleType("qgis.PyQt.sip")
    sip_module.isdeleted = lambda obj: getattr(obj, "_deleted", False) is True
    qgis_core = ModuleType("qgis.core")
    qgis_core.QgsProject = object
    for name, module in {
        "qgis": ModuleType("qgis"),
        "qgis.PyQt": ModuleType("qgis.PyQt"),
        "qgis.PyQt.QtWidgets": widgets,
        "qgis.PyQt.QtCore": core,
        "qgis.PyQt.QtGui": gui,
        "qgis.PyQt.sip": sip_module,
        "qgis.core": qgis_core,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return widgets


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parents[1] / filename
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def dock(qt):
    module = load_module(
        "plugins.farois_audit_rollback.gui._tested_dock", "gui/dockwidget.py"
    )
    panel = module.FaroisAuditDock.__new__(module.FaroisAuditDock)
    from plugins.farois_audit_rollback.gui.lifecycle import SignalScope

    panel._signals = SignalScope()
    panel.is_usable = lambda: not panel._signals.disposed
    panel.repository = SimpleNamespace(
        engine_available=True,
        revert_change=Mock(return_value="undo"),
        revert_transaction=Mock(return_value="undo"),
    )
    panel.model = HistoryModel(
        [HistoryEntry(change_id="change", transaction_id=TX, can_undo=True)]
    )
    panel.table = SimpleNamespace(currentRow=lambda: 0)
    panel.user = panel.provenance = panel.column = SimpleNamespace(text=lambda: "")
    panel.cancelable = SimpleNamespace(isChecked=lambda: False)
    panel.layer = SimpleNamespace(
        id=lambda: "layer",
        selectedFeatureIds=lambda: [7],
        reload=Mock(),
        selectByIds=Mock(),
        triggerRepaint=Mock(),
    )
    panel._selected_context = lambda: (panel.layer, "wyre", "roads", "uuid-record")
    panel._last_context = ("layer", "uuid-record")
    panel._undo_in_progress = False
    panel._update_actions = Mock()
    panel.load_history = Mock()
    return panel


def test_transaction_button_dispatches_only_transaction(dock, qt):
    dock.undo_transaction_selected()
    dock.repository.revert_transaction.assert_called_once_with(TX, "test reason")
    dock.repository.revert_change.assert_not_called()
    dock.layer.selectByIds.assert_called_once_with([7])
    assert TX in qt.QMessageBox.question.call_args.args[2]


def test_unit_button_does_not_silently_undo_transaction(dock):
    dock.undo_selected()
    dock.repository.revert_change.assert_called_once_with("change", "test reason")
    dock.repository.revert_transaction.assert_not_called()


def test_cancel_confirmation_does_not_call_database(dock, qt):
    qt.QMessageBox.question.return_value = qt.QMessageBox.No
    dock.undo_transaction_selected()
    dock.repository.revert_transaction.assert_not_called()
    assert not dock._undo_in_progress


def test_changed_selection_during_dialog_does_not_call_database(dock, qt):
    def changed(*args):
        dock._selected_context = lambda: (dock.layer, "wyre", "roads", "other-record")
        return "test", True

    qt.QInputDialog.getText.side_effect = changed
    dock.undo_transaction_selected()
    dock.repository.revert_transaction.assert_not_called()
    qt.QMessageBox.critical.assert_called_once()


def test_missing_engine_disables_actions_but_keeps_history(dock):
    dock.repository.engine_available = False
    assert all(not state[0] and "moteur" in state[1] for state in dock.action_states())
    assert len(dock.model.entries) == 1


def test_multiple_history_rows_never_trigger_batch_rollback(dock):
    dock._selected_history_entries = lambda: [dock.model.entries[0]] * 2
    assert all(
        not state[0] and "une seule" in state[1] for state in dock.action_states()
    )
    dock.repository.revert_change.assert_not_called()


def test_postgresql_error_is_shown(dock, qt):
    dock.repository.revert_transaction.side_effect = RuntimeError("concurrent conflict")
    dock.undo_transaction_selected()
    assert "concurrent conflict" in qt.QMessageBox.critical.call_args.args[2]
    dock.layer.reload.assert_not_called()


def test_toolbar_has_one_history_entry_and_menu_keeps_undo_actions(qt, monkeypatch):
    module = load_module("plugins.farois_audit_rollback._tested_plugin", "plugin.py")
    toolbar = Mock()
    iface = Mock()
    iface.addToolBar.return_value = toolbar
    plugin = module.FaroisAuditRollback(iface)
    plugin.initGui()
    assert [a.text for a in plugin.actions] == [
        "Historique Farois",
        "Annuler la modification",
        "Annuler la transaction",
    ]
    toolbar.addAction.assert_called_once_with(plugin.action)
    assert Path(plugin.action.icon.path).name == "icon.svg"
    assert Path(plugin.action.icon.path).is_file()
    assert iface.addPluginToMenu.call_count == 3
    module.FaroisAuditDock = Mock()
    plugin.action.triggered.emit()
    iface.addDockWidget.assert_called_once()
    assert not plugin.transaction_action.enabled
    plugin.dock = SimpleNamespace(
        is_usable=lambda: True,
        action_states=lambda: ((True, "change"), (True, "tx")),
        undo_selected=Mock(),
        undo_transaction_selected=Mock(),
    )
    plugin.sync_actions()
    plugin.transaction_action.triggered.emit()
    plugin.dock.undo_transaction_selected.assert_called_once()
    plugin.dock.undo_selected.assert_not_called()


def test_raster_selection_signal_is_never_accessed(dock):
    raster = SimpleNamespace(type=lambda: 1)
    dock._connected_selection_layer = raster  # recover an invalid prior reference too
    dock._wire_selection_signal(raster)
    assert dock._connected_selection_layer is None


def test_deleted_previous_vector_is_not_dereferenced(dock):
    class DeletedLayer:
        _deleted = True

        @property
        def selectionChanged(self):
            raise RuntimeError(
                "wrapped C/C++ object of type QgsVectorLayer has been deleted"
            )

    dock._connected_selection_layer = DeletedLayer()
    dock._wire_selection_signal(None)
    assert dock._connected_selection_layer is None


def test_disposed_panel_ignores_queued_project_and_timer_events(dock):
    dock._signals.dispose()
    # These must return before touching any uninitialized/deleted Qt widget.
    dock._populate_layers()
    dock._project_layers_changed([])
    dock._on_active_layer_changed(None)
    dock._auto_refresh()
    dock.refresh_context(auto=True)


def test_plugin_modules_remain_importable_without_qgis_bindings(monkeypatch):
    monkeypatch.setitem(sys.modules, "qgis", None)
    monkeypatch.setitem(sys.modules, "qgis.PyQt.QtWidgets", None)
    module = load_module(
        "plugins.farois_audit_rollback.gui._tested_without_qgis", "gui/dockwidget.py"
    )
    assert not module.QGIS_AVAILABLE
    with pytest.raises(RuntimeError, match="bindings QGIS"):
        module.FaroisAuditDock(object())


@pytest.mark.parametrize("editable", [True, False])
def test_modify_current_object_uses_qgis_form_and_respects_editability(
    dock, qt, monkeypatch, editable
):
    layer = dock.layer
    layer.isEditable = lambda: False
    layer.startEditing = Mock(return_value=editable)
    layer.isSpatial = lambda: True
    feature = SimpleNamespace(id=lambda: 7)
    dock._navigation_in_progress = False
    dock._resolve_source_layer = lambda: layer
    dock.layer_combo = SimpleNamespace(findData=lambda _: -1)
    dock.iface = SimpleNamespace(setActiveLayer=Mock())
    dock.navigation_label = SimpleNamespace(setText=Mock())
    dock.refresh_context = Mock()
    dock._render = Mock()
    globals_ = dock._navigate_history_object.__func__.__wrapped__.__globals__
    monkeypatch.setitem(
        globals_, "resolve_history_features", lambda *args, **kwargs: [(layer, feature)]
    )
    monkeypatch.setitem(
        globals_,
        "QgsProject",
        SimpleNamespace(
            instance=lambda: SimpleNamespace(mapLayers=lambda: {"layer": layer})
        ),
    )

    class Context:
        IdentifyMode = 1
        SingleEditMode = 2
        setAttributeFormMode = Mock()
        setAllowCustomUi = Mock()

    dialog = Mock()
    gui = ModuleType("qgis.gui")
    gui.QgsAttributeEditorContext = Context
    gui.QgsAttributeDialog = Mock(return_value=dialog)
    monkeypatch.setitem(sys.modules, "qgis.gui", gui)
    dock.edit_history_object()
    layer.startEditing.assert_called_once()
    if editable:
        gui.QgsAttributeDialog.assert_called_once()
        dialog.setMode.assert_called_once_with(Context.SingleEditMode)
        dialog.exec_.assert_called_once()
        layer.reload.assert_not_called()  # The QGIS edit buffer is not saved by the plugin.
    else:
        gui.QgsAttributeDialog.assert_not_called()
        assert "ne permet pas l'édition" in qt.QMessageBox.warning.call_args.args[2]
    assert not dock._navigation_in_progress


def test_open_postgresql_edit_buffer_disables_undo(dock, monkeypatch):
    layer = SimpleNamespace(providerType=lambda: "postgres", isEditable=lambda: True)
    monkeypatch.setitem(
        dock.action_states.__func__.__globals__,
        "QgsProject",
        SimpleNamespace(
            instance=lambda: SimpleNamespace(mapLayers=lambda: {"layer": layer})
        ),
    )
    assert all(
        not state[0] and "éditions PostgreSQL" in state[1]
        for state in dock.action_states()
    )
