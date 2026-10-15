"""Headless checks of toolbar wiring and rollback dispatch using Qt/QGIS mocks."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from plugins.farois_audit_rollback.api.farois_client import (
    FaroisApiUnavailable,
    FaroisConflict,
    FaroisNotAuthenticated,
    FaroisProfile,
)
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
    panel._resolve_source_layer = lambda: panel.layer
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
        "Se connecter à Farois…",
        "Se déconnecter de Farois",
    ]
    toolbar.addAction.assert_called_once_with(plugin.action)
    assert Path(plugin.action.icon.path).name == "icon.svg"
    assert iface.addPluginToMenu.call_count == 5
    module.FaroisAuditDock = Mock()
    plugin.action.triggered.emit()
    module.FaroisAuditDock.assert_called_once_with(iface, api=plugin.api)
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


def admin_api(**overrides):
    api = SimpleNamespace(
        connected=True,
        is_admin=True,
        profile=FaroisProfile("simon@constructel.example.be", "ADMIN"),
        revert_change=Mock(return_value={"reverted": ["label"], "conflicts": []}),
        revert_transaction=Mock(return_value={"changes": [{"reverted": ["label"], "conflicts": []}]}),
        login=Mock(),
        logout=Mock(),
    )
    vars(api).update(overrides)
    return api


def test_admin_session_sends_change_undo_to_api_not_postgres(dock):
    dock.api = admin_api()
    dock.undo_selected()
    dock.api.revert_change.assert_called_once_with("change", "FIELD", "test reason")
    dock.repository.revert_change.assert_not_called()
    dock.layer.reload.assert_called_once()


def test_admin_session_restores_a_delete(dock):
    dock.api = admin_api()
    dock.model = HistoryModel(
        [HistoryEntry(change_id="change", transaction_id=TX, operation="DELETE", can_undo=True)]
    )
    dock.undo_selected()
    dock.api.revert_change.assert_called_once_with("change", "RESTORE", "test reason")


def test_admin_session_sends_transaction_undo_to_api(dock):
    dock.api = admin_api()
    dock.undo_transaction_selected()
    dock.api.revert_transaction.assert_called_once_with(TX, "FIELD", "test reason")
    dock.repository.revert_transaction.assert_not_called()


def test_conflict_offers_force_and_retries_with_force(dock, qt):
    conflict = FaroisConflict(
        "Conflit : rien n'a été annulé.", status=409,
        detail={"reason": "conflict", "report": {"conflicts": [{"column": "label"}]}},
    )
    dock.api = admin_api(revert_change=Mock(side_effect=[conflict, {"reverted": ["label"], "conflicts": []}]))
    dock.undo_selected()
    assert [c.args[1] for c in dock.api.revert_change.call_args_list] == ["FIELD", "FORCE"]
    assert "FORCE" in qt.QMessageBox.question.call_args.args[2]
    dock.layer.reload.assert_called_once()


def test_conflict_declined_does_not_force(dock, qt):
    qt.QMessageBox.question.side_effect = [qt.QMessageBox.Yes, qt.QMessageBox.No]
    conflict = FaroisConflict("Conflit.", status=409, detail={"reason": "conflict", "report": {}})
    dock.api = admin_api(revert_change=Mock(side_effect=conflict))
    dock.undo_selected()
    dock.api.revert_change.assert_called_once()
    dock.layer.reload.assert_not_called()


def test_already_undone_is_shown_without_force(dock, qt):
    dock.api = admin_api(revert_change=Mock(side_effect=FaroisConflict(
        "Modification déjà annulée.", status=409, detail={"reason": "already_undone"})))
    dock.undo_selected()
    dock.api.revert_change.assert_called_once()
    assert qt.QMessageBox.question.call_count == 1
    assert "Modification déjà annulée." in qt.QMessageBox.critical.call_args.args[2]


def test_expired_session_never_falls_back_to_postgres(dock, qt):
    dock.api = admin_api(revert_change=Mock(side_effect=FaroisNotAuthenticated(
        "Session Farois expirée : reconnectez-vous.", status=401)))
    dock._render_api_status = Mock()
    dock.undo_selected()
    dock.repository.revert_change.assert_not_called()
    dock.layer.reload.assert_not_called()
    assert "reconnectez-vous" in qt.QMessageBox.warning.call_args.args[2]


def test_viewer_login_is_not_activated(dock, qt):
    api = admin_api(connected=False, is_admin=False, profile=None,
                    login=Mock(return_value=FaroisProfile("v@constructel.example.be", "VIEWER")))
    dock.api = api
    dock.api_session_changed = Mock()
    dock.connect_farois(credentials=("v@constructel.example.be", "pw"))
    api.logout.assert_called_once()
    assert "VIEWER" in qt.QMessageBox.warning.call_args.args[2]
    dock.api_session_changed.assert_called_once()


def test_login_failure_is_reported_and_session_unchanged(dock, qt):
    api = admin_api(connected=False, is_admin=False, profile=None,
                    login=Mock(side_effect=FaroisNotAuthenticated("Identifiants Farois refusés.")))
    dock.api = api
    dock.api_session_changed = Mock()
    dock.connect_farois(credentials=("a@constructel.example.be", "mauvais"))
    assert "Identifiants Farois refusés." in qt.QMessageBox.critical.call_args.args[2]
    dock.api_session_changed.assert_not_called()


def test_entry_view_applies_admin_rules_only_with_admin_session(dock):
    entry = HistoryEntry(change_id="c", operation="UPDATE", in_engine=True, can_undo=False,
                         refusal_reason="Modification effectuée par un autre utilisateur")
    dock.api = admin_api()
    assert dock._entry_view(entry).can_undo
    dock.api = None
    assert not dock._entry_view(entry).can_undo


def test_unload_drops_the_farois_session(qt):
    module = load_module("plugins.farois_audit_rollback._tested_plugin_unload", "plugin.py")
    iface = Mock()
    iface.addToolBar.return_value = Mock()
    plugin = module.FaroisAuditRollback(iface)
    plugin.initGui()
    api = plugin.api
    api.logout = Mock()
    plugin.unload()
    api.logout.assert_called_once()
    assert plugin.api is None


def test_failed_relogin_while_connected_refreshes_session(dock, qt):
    dock.api = admin_api(login=Mock(side_effect=FaroisNotAuthenticated("Identifiants Farois refusés.")))
    dock.api_session_changed = Mock()
    dock.connect_farois(credentials=("a@constructel.example.be", "mauvais"))
    assert "Identifiants Farois refusés." in qt.QMessageBox.critical.call_args.args[2]
    dock.api_session_changed.assert_called_once()


def test_undo_redraws_session_banner_afterwards(dock):
    dock.api = admin_api()
    dock._render_api_status = Mock()
    dock.undo_selected()
    dock._render_api_status.assert_called()


def test_unavailable_api_reports_uncertain_outcome_without_fallback(dock, qt):
    dock.api = admin_api(revert_change=Mock(side_effect=FaroisApiUnavailable("API Farois injoignable (http://x).")))
    dock.undo_selected()
    dock.repository.revert_change.assert_not_called()
    dock.layer.reload.assert_not_called()
    assert "Résultat incertain" in qt.QMessageBox.warning.call_args.args[2]


def scope(value):
    return SimpleNamespace(currentData=lambda: value)


def pg_layer(ident, table="roads", database="fixture"):
    """Couche PostgreSQL factice : source = identifiant, résolu par FakeUri."""
    return SimpleNamespace(
        id=lambda: ident,
        source=lambda: f"{database}|{table}",
        type=lambda: 0,
        providerType=lambda: "postgres",
        isEditable=lambda: False,
        selectedFeatureIds=lambda: [7],
        reload=Mock(),
        selectByIds=Mock(),
        triggerRepaint=Mock(),
    )


class FakeUri:
    def __init__(self, source):
        self.db, self.name = source.split("|")

    def schema(self):
        return "wyre"

    def table(self):
        return self.name

    def database(self):
        return self.db

    host = port = service = username = authConfigId = lambda self: ""


def project_with(dock, monkeypatch, *layers):
    monkeypatch.setattr(sys.modules["qgis.core"], "QgsDataSourceUri", FakeUri, raising=False)
    monkeypatch.setitem(
        dock.action_states.__func__.__globals__,
        "QgsProject",
        SimpleNamespace(instance=lambda: SimpleNamespace(
            mapLayers=lambda: {layer.id(): layer for layer in layers})),
    )


@pytest.mark.parametrize("history_scope", ["layer", "visible"])
def test_admin_restores_a_deleted_object_from_layer_or_visible_scope(
    dock, qt, monkeypatch, history_scope
):
    # Un objet supprimé n'est plus sélectionnable : sa ligne DELETE n'apparaît
    # qu'en portée couche / tous les changements, jamais en mode objet.
    source, twin, other = pg_layer("source"), pg_layer("twin"), pg_layer("other", table="cables")
    foreign = pg_layer("foreign", database="another")
    project_with(dock, monkeypatch, source, twin, other, foreign)
    dock.layer = source
    dock._selected_context = Mock(side_effect=ValueError("Sélectionnez exactement un objet."))
    dock.api = admin_api(revert_change=Mock(return_value={"restored": True, "conflicts": []}))
    dock.history_scope = scope(history_scope)
    dock.model = HistoryModel([
        HistoryEntry(change_id="c", transaction_id=TX, operation="DELETE", in_engine=True,
                     schema_name="wyre", table_name="roads").as_admin()
    ])
    (change_ok, reason), (tx_ok, _) = dock.action_states()
    assert change_ok and tx_ok, reason
    dock.undo_selected()
    dock.api.revert_change.assert_called_once_with("c", "RESTORE", "test reason")
    dock.repository.revert_change.assert_not_called()
    dock._selected_context.assert_not_called()
    for layer in (source, twin):  # même table, même connexion
        layer.reload.assert_called_once()
        layer.triggerRepaint.assert_called_once()
        layer.selectByIds.assert_not_called()  # hors mode objet : sélection intacte
    other.reload.assert_not_called()
    foreign.reload.assert_not_called()
    assert "Annulation enregistrée" in qt.QMessageBox.information.call_args.args[2]


def test_admin_transaction_undo_from_visible_scope(dock, qt):
    dock.api = admin_api()
    dock.history_scope = scope("visible")
    dock._selected_context = Mock(side_effect=ValueError("Sélectionnez exactement un objet."))
    dock.undo_transaction_selected()
    dock.api.revert_transaction.assert_called_once_with(TX, "FIELD", "test reason")
    dock._selected_context.assert_not_called()
    dock.layer.reload.assert_called_once()  # à défaut de couche de la table : la source
    dock.layer.selectByIds.assert_not_called()


def test_admin_object_scope_keeps_the_map_selection(dock):
    dock.api = admin_api()
    dock.history_scope = scope("object")
    dock.undo_selected()
    dock.layer.reload.assert_called_once()
    dock.layer.selectByIds.assert_called_once_with([7])


@pytest.mark.parametrize("change", ["entry", "repository"])
def test_admin_undo_refused_when_history_changed_during_dialog(dock, qt, change):
    dock.api = admin_api()
    dock.history_scope = scope("layer")

    def changed(*args):
        if change == "entry":
            dock.model.set_entries([HistoryEntry(change_id="other", transaction_id=TX)])
        else:
            dock.repository = SimpleNamespace(engine_available=True)
        return "motif", True

    qt.QInputDialog.getText.side_effect = changed
    dock.undo_selected()
    dock.api.revert_change.assert_not_called()
    dock.layer.reload.assert_not_called()
    assert "historique a changé" in qt.QMessageBox.critical.call_args.args[2]


def test_admin_without_loaded_history_cannot_undo(dock):
    dock.api = admin_api()
    dock.history_scope = scope("layer")
    dock._last_context = None
    assert all(not state[0] for state in dock.action_states())


@pytest.mark.parametrize("api", [None, "viewer"])
def test_layer_scope_without_admin_session_still_requires_object_mode(dock, qt, api):
    dock.api = (
        admin_api(is_admin=False, profile=FaroisProfile("v@constructel.example.be", "VIEWER"))
        if api else None
    )
    dock.history_scope = scope("layer")
    dock.model = HistoryModel([
        HistoryEntry(change_id="c", transaction_id=TX, operation="DELETE", can_undo=True,
                     in_engine=True)
    ])
    assert all(
        not ok and "passez en mode Objet sélectionné" in reason
        for ok, reason in dock.action_states()
    )
    dock.undo_selected()
    dock.undo_transaction_selected()
    assert "passez en mode Objet sélectionné" in qt.QMessageBox.warning.call_args.args[2]
    dock.repository.revert_change.assert_not_called()
    dock.repository.revert_transaction.assert_not_called()
    dock.layer.reload.assert_not_called()


def test_admin_flow_never_falls_back_to_postgres_if_session_drops_during_dialog(dock, qt):
    dock.api = admin_api(revert_change=Mock(side_effect=FaroisNotAuthenticated(
        "Connectez-vous à Farois.", status=401)))
    dock.history_scope = scope("layer")
    dock._render_api_status = Mock()

    def logout(*args):
        dock.api.connected = dock.api.is_admin = False
        return "motif", True

    qt.QInputDialog.getText.side_effect = logout
    dock.undo_selected()
    dock.api.revert_change.assert_called_once()
    dock.repository.revert_change.assert_not_called()
    dock.layer.reload.assert_not_called()


def test_api_server_error_with_json_body_is_shown_as_nothing_undone(dock, qt):
    from plugins.farois_audit_rollback.tests.test_farois_client import http_error, logged_in

    client, _ = logged_in(http_error(503, {"detail": {
        "message": "Délai dépassé, réessayez.", "reason": "timeout",
        "engine": "canceling statement due to statement timeout"}}))
    dock.api = client
    dock.undo_selected()
    text = qt.QMessageBox.critical.call_args.args[2]
    assert "Rien n'a été annulé" in text and "incertain" not in text
    qt.QMessageBox.warning.assert_not_called()
    dock.repository.revert_change.assert_not_called()
    dock.layer.reload.assert_not_called()
