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
from plugins.farois_audit_rollback.gui.dockwidget import AUTO_REASON
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
    widgets.QInputDialog = SimpleNamespace(getText=Mock(return_value=("x", True)))
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
    panel.bar = Mock()
    panel.iface = SimpleNamespace(messageBar=lambda: panel.bar)
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
    dock.repository.revert_transaction.assert_called_once_with(TX, AUTO_REASON)
    dock.repository.revert_change.assert_not_called()
    dock.layer.selectByIds.assert_called_once_with([7])
    assert TX[:8] in qt.QMessageBox.question.call_args.args[2]


def test_unit_button_does_not_silently_undo_transaction(dock):
    dock.undo_selected()
    dock.repository.revert_change.assert_called_once_with("change", AUTO_REASON)
    dock.repository.revert_transaction.assert_not_called()


def test_cancel_confirmation_does_not_call_database(dock, qt):
    qt.QMessageBox.question.return_value = qt.QMessageBox.No
    dock.undo_transaction_selected()
    dock.repository.revert_transaction.assert_not_called()
    assert not dock._undo_in_progress


def test_changed_selection_during_dialog_does_not_call_database(dock, qt):
    def changed(*args):
        dock._selected_context = lambda: (dock.layer, "wyre", "roads", "other-record")
        return qt.QMessageBox.Yes

    qt.QMessageBox.question.side_effect = changed
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
    assert Path(plugin.action.icon.path).is_file()
    assert iface.addPluginToMenu.call_count == 5
    module.FaroisAuditDock = Mock()
    plugin.action.triggered.emit()
    module.FaroisAuditDock.assert_called_once_with(
        iface, api=plugin.api, store=plugin.store
    )
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


def admin_api(**overrides):
    api = SimpleNamespace(
        connected=True,
        is_admin=True,
        profile=FaroisProfile("simon@constructel.example.be", "ADMIN"),
        revert_change=Mock(return_value={"reverted": ["label"], "conflicts": []}),
        revert_transaction=Mock(return_value={"changes": [{"reverted": ["label"], "conflicts": []}]}),
        login=Mock(),
        logout=Mock(),
        resume=Mock(),
        forget=Mock(),
        last_email="",
    )
    vars(api).update(overrides)
    return api


def test_admin_session_sends_change_undo_to_api_not_postgres(dock):
    dock.api = admin_api()
    dock.undo_selected()
    dock.api.revert_change.assert_called_once_with("change", "FIELD", AUTO_REASON)
    dock.repository.revert_change.assert_not_called()
    dock.layer.reload.assert_called_once()


def test_admin_session_restores_a_delete(dock):
    dock.api = admin_api()
    dock.model = HistoryModel(
        [HistoryEntry(change_id="change", transaction_id=TX, operation="DELETE", can_undo=True)]
    )
    dock.undo_selected()
    dock.api.revert_change.assert_called_once_with("change", "RESTORE", AUTO_REASON)


def test_admin_session_sends_transaction_undo_to_api(dock):
    dock.api = admin_api()
    dock.undo_transaction_selected()
    dock.api.revert_transaction.assert_called_once_with(TX, "FIELD", AUTO_REASON)
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
    assert qt.QMessageBox.question.call_count == 2
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
    api.logout, api.forget = Mock(), Mock()
    plugin.unload()
    # Oublie sans révoquer : /auth/logout tuerait la session mémorisée à chaque
    # fermeture de QGIS (et bloquerait la fermeture si l'API est injoignable).
    api.forget.assert_called_once()
    api.logout.assert_not_called()
    assert plugin.api is None and plugin.store is None


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
    dock.api.revert_change.assert_called_once_with("c", "RESTORE", AUTO_REASON)
    dock.repository.revert_change.assert_not_called()
    dock._selected_context.assert_not_called()
    for layer in (source, twin):  # même table, même connexion
        layer.reload.assert_called_once()
        layer.triggerRepaint.assert_called_once()
        layer.selectByIds.assert_not_called()  # hors mode objet : sélection intacte
    other.reload.assert_not_called()
    foreign.reload.assert_not_called()
    dock.bar.pushSuccess.assert_called_once()


def test_admin_transaction_undo_from_visible_scope(dock, qt):
    dock.api = admin_api()
    dock.history_scope = scope("visible")
    dock._selected_context = Mock(side_effect=ValueError("Sélectionnez exactement un objet."))
    dock.undo_transaction_selected()
    dock.api.revert_transaction.assert_called_once_with(TX, "FIELD", AUTO_REASON)
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
        return qt.QMessageBox.Yes

    qt.QMessageBox.question.side_effect = changed
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
        return qt.QMessageBox.Yes

    qt.QMessageBox.question.side_effect = logout
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


def tx_conflict(report=True, engine="revert_transaction : conflit, transaction non annulee : {...}"):
    member = {"change_id": "member-1", "operation": "INSERT", "conflicts": [
        {"column": "*", "detail": "lignes referencees par : wyre.cables"}]}
    detail = {"message": "Conflit : la transaction n'a pas été annulée.",
              "reason": "conflict", "engine": engine}
    if report:
        detail["report"] = {"transaction_id": TX, "mode": "FIELD", "changes": [member]}
    return FaroisConflict("Conflit : la transaction n'a pas été annulée.", status=409, detail=detail)


def test_transaction_conflict_dialog_warns_about_cascades_and_shows_the_report(dock, qt):
    dock.api = admin_api(revert_transaction=Mock(side_effect=[
        tx_conflict(), {"transaction_id": TX, "mode": "FORCE",
                        "changes": [{"deleted": True, "conflicts": []}]}]))
    dock.undo_transaction_selected()
    text = qt.QMessageBox.question.call_args.args[2]
    assert "Les objets créés par cette transaction seront supprimés même s'ils ont été " \
        "modifiés ou référencés depuis ; des suppressions en cascade sont possibles." in text
    assert "member-1" in text and "lignes referencees par : wyre.cables" in text
    assert "{}" not in text
    assert [c.args[1] for c in dock.api.revert_transaction.call_args_list] == ["FIELD", "FORCE"]
    dock.layer.reload.assert_called_once()


def test_transaction_conflict_without_report_shows_the_engine_message(dock, qt):
    qt.QMessageBox.question.side_effect = [qt.QMessageBox.Yes, qt.QMessageBox.No]
    dock.api = admin_api(revert_transaction=Mock(side_effect=tx_conflict(
        report=False, engine="revert_transaction : conflit, rapport illisible")))
    dock.undo_transaction_selected()
    text = qt.QMessageBox.question.call_args.args[2]
    assert "revert_transaction : conflit, rapport illisible" in text and "{}" not in text
    dock.api.revert_transaction.assert_called_once()  # refus : FORCE jamais envoyé
    assert qt.QMessageBox.question.call_count == 2
    dock.layer.reload.assert_not_called()


def test_change_conflict_dialog_keeps_the_overwrite_warning_only(dock, qt):
    conflict = FaroisConflict("Conflit : rien n'a été annulé.", status=409, detail={
        "reason": "conflict", "report": {"conflicts": [{"column": "label", "current": "B"}]}})
    dock.api = admin_api(revert_change=Mock(side_effect=[conflict, {"reverted": ["label"]}]))
    dock.undo_selected()
    text = qt.QMessageBox.question.call_args.args[2]
    assert "Les valeurs actuelles en conflit seront écrasées." in text
    assert "cascade" not in text and '"label"' in text


@pytest.mark.parametrize(
    "transaction, result",
    [
        (True, {"transaction_id": TX, "mode": "FIELD", "changes": []}),
        (False, {"change_id": "change", "reverted": [], "conflicts": [],
                 "restored": False, "deleted": False}),
        (False, {}),
    ],
)
def test_api_success_that_undid_nothing_is_not_reported_as_done(dock, qt, transaction, result):
    dock.api = admin_api(revert_change=Mock(return_value=result),
                         revert_transaction=Mock(return_value=result))
    (dock.undo_transaction_selected if transaction else dock.undo_selected)()
    assert "Rien n'a été annulé" in dock.bar.pushWarning.call_args.args[1]
    qt.QMessageBox.information.assert_not_called()
    dock.layer.reload.assert_not_called()


def test_reason_over_500_characters_is_refused_before_sending(dock, qt, monkeypatch):
    dock.api = admin_api()
    glb = dock.undo_selected.__func__.__globals__
    monkeypatch.setitem(glb, "AUTO_REASON", "x" * 501)
    dock.undo_selected()
    dock.api.revert_change.assert_not_called()
    assert "500" in qt.QMessageBox.warning.call_args.args[2]
    dock.layer.reload.assert_not_called()
    monkeypatch.setitem(glb, "AUTO_REASON", "  " + "x" * 500 + "  ")
    dock.undo_selected()
    dock.api.revert_change.assert_called_once()


def test_reconnection_dialog_is_prefilled_with_the_last_email_after_expiry(dock, qt, monkeypatch):
    from plugins.farois_audit_rollback.tests.test_farois_client import ME, http_error, logged_in

    client, _ = logged_in(http_error(401, {"detail": "Session expirée"}))
    dock.api = client
    dock._render_api_status = Mock()
    dock.undo_selected()
    assert not client.connected
    asked = Mock(return_value=None)
    monkeypatch.setitem(dock.connect_farois.__func__.__globals__, "ask_credentials", asked)
    dock.connect_farois()
    asked.assert_called_once_with(dock, ME["email"])


NO_EFFECT = {"reverted": [], "conflicts": [], "restored": False, "deleted": False}


def test_api_transaction_with_one_effective_member_is_a_success(dock, qt):
    result = {"transaction_id": TX, "mode": "FIELD", "changes": [
        {"change_id": "a", "reverted": ["label"], "conflicts": [], "restored": False,
         "deleted": False},
        dict(NO_EFFECT, change_id="b"),
    ]}
    dock.api = admin_api(revert_transaction=Mock(return_value=result))
    dock.undo_transaction_selected()
    dock.bar.pushSuccess.assert_called_once()
    qt.QMessageBox.warning.assert_not_called()
    dock.layer.reload.assert_called_once()


def test_api_transaction_whose_members_all_had_no_effect_undid_nothing(dock, qt):
    result = {"transaction_id": TX, "mode": "FIELD",
              "changes": [dict(NO_EFFECT, change_id="a"), dict(NO_EFFECT, change_id="b")]}
    dock.api = admin_api(revert_transaction=Mock(return_value=result))
    dock.undo_transaction_selected()
    assert "Rien n'a été annulé" in dock.bar.pushWarning.call_args.args[1]
    qt.QMessageBox.information.assert_not_called()
    dock.layer.reload.assert_not_called()


# ── Connexion automatique (session mémorisée) et « Se souvenir de moi » ──

EMAIL = "simon@constructel.example.be"
EXPIRED = "Farois : session expirée — reconnectez-vous (clic droit)"
UNREACHABLE = "Farois : API injoignable — connexion automatique impossible"


class Label:
    def __init__(self):
        self.value = ""

    def setText(self, text):
        self.value = text

    def text(self):
        return self.value


@pytest.fixture
def auto_dock(dock, qt, monkeypatch):
    """Panneau avec bandeau, session mémorisée et interdiction de tout dialogue."""
    from plugins.farois_audit_rollback.api.session_store import MemorySessionStore

    dock.api_label = Label()
    dock.store = MemorySessionStore()
    dock.store.save(EMAIL, "rt-1")
    monkeypatch.setitem(
        dock.connect_farois.__func__.__globals__,
        "ask_credentials",
        Mock(side_effect=AssertionError("aucun dialogue en connexion automatique")),
    )
    yield dock
    for name in ("warning", "critical", "information", "question"):
        getattr(qt.QMessageBox, name).assert_not_called()


def logged_out_api(resume_role=None, **overrides):
    api = admin_api(connected=False, is_admin=False, profile=None, **overrides)

    def resume(token):
        api.profile = FaroisProfile(EMAIL, resume_role)
        api.connected, api.is_admin = True, api.profile.is_admin
        return api.profile

    def logout():
        api.connected = api.is_admin = False
        api.profile = None

    if resume_role is not None:
        api.resume = Mock(side_effect=resume)
    api.logout = Mock(side_effect=logout)  # comme le vrai client : session oubliée
    return api


def test_auto_connect_resumes_a_remembered_admin_session_silently(auto_dock):
    auto_dock.api = logged_out_api("ADMIN")
    auto_dock.auto_connect_farois()
    auto_dock.api.resume.assert_called_once_with("rt-1")
    assert auto_dock.api_label.text() == f"Farois : {EMAIL} (ADMIN)"
    auto_dock.load_history.assert_called_once_with(silent=True)
    assert auto_dock.store.load() == (EMAIL, "rt-1")


def test_auto_connect_expired_session_clears_the_store_and_says_so(auto_dock):
    auto_dock.api = logged_out_api(resume=Mock(side_effect=FaroisNotAuthenticated(
        "Session Farois expirée : reconnectez-vous.", status=401)))
    auto_dock.auto_connect_farois()
    assert auto_dock.store.load() is None
    assert auto_dock.api_label.text() == EXPIRED
    assert auto_dock.api.last_email == EMAIL  # pré-remplira la reconnexion
    auto_dock.load_history.assert_not_called()


def test_auto_connect_unreachable_api_keeps_the_remembered_token(auto_dock):
    auto_dock.api = logged_out_api(resume=Mock(side_effect=FaroisApiUnavailable(
        "API Farois injoignable (http://x).")))
    auto_dock.auto_connect_farois()
    assert auto_dock.store.load() == (EMAIL, "rt-1")
    assert auto_dock.api_label.text() == UNREACHABLE


def test_auto_connect_other_api_error_keeps_the_token_and_explains(auto_dock):
    from plugins.farois_audit_rollback.api.farois_client import FaroisApiError

    auto_dock.api = logged_out_api(resume=Mock(side_effect=FaroisApiError(
        "Réponse de renouvellement Farois invalide.")))
    auto_dock.auto_connect_farois()
    assert auto_dock.store.load() == (EMAIL, "rt-1")
    assert "connexion automatique impossible" in auto_dock.api_label.text()
    assert "Réponse de renouvellement Farois invalide." in auto_dock.api_label.text()


def test_auto_connect_non_admin_account_is_dropped(auto_dock):
    auto_dock.api = logged_out_api("VIEWER")
    auto_dock.auto_connect_farois()
    assert auto_dock.store.load() is None
    auto_dock.api.logout.assert_called_once()
    assert "VIEWER" in auto_dock.api_label.text()
    assert "ADMIN et MANAGER" in auto_dock.api_label.text()


def test_auto_connect_needs_a_remembered_session_and_a_logged_out_client(auto_dock):
    auto_dock.api = logged_out_api("ADMIN")
    auto_dock.store.clear()
    auto_dock.auto_connect_farois()
    auto_dock.api.resume.assert_not_called()
    auto_dock.store.save(EMAIL, "rt-1")
    auto_dock.api = admin_api()  # déjà connecté
    auto_dock.auto_connect_farois()
    auto_dock.api.resume.assert_not_called()
    auto_dock.store = None
    auto_dock.api = logged_out_api("ADMIN")
    auto_dock.auto_connect_farois()  # sans magasin : rien
    auto_dock.api.resume.assert_not_called()


def test_connection_dialog_is_prefilled_from_constructel_bridge(dock, monkeypatch):
    settings = {"constructel_bridge/audit_email": "bridge@constructel.example.be"}

    class Settings:
        def value(self, key, default=None):
            return settings.get(key, default)

    monkeypatch.setattr(sys.modules["qgis.core"], "QgsSettings", Settings, raising=False)
    dock.api = logged_out_api()
    asked = Mock(return_value=None)
    monkeypatch.setitem(dock.connect_farois.__func__.__globals__, "ask_credentials", asked)
    dock.connect_farois()
    asked.assert_called_once_with(dock, "bridge@constructel.example.be")
    dock.api.last_email = "saisie@constructel.example.be"  # la dernière saisie prime
    dock.connect_farois()
    assert asked.call_args.args == (dock, "saisie@constructel.example.be")


@pytest.mark.parametrize("remember", [True, False])
def test_remember_me_choice_decides_what_is_stored(dock, qt, remember):
    from plugins.farois_audit_rollback.api.farois_client import FaroisApiClient
    from plugins.farois_audit_rollback.api.session_store import MemorySessionStore
    from plugins.farois_audit_rollback.tests.test_farois_client import (
        ME, REFRESH, Opener, login_response,
    )

    store = MemorySessionStore()
    dock.store = store
    dock.api = FaroisApiClient("http://api:8080", opener=Opener(login_response(), ME), store=store)
    dock.connect_farois(credentials=(ME["email"], "secret", remember))
    assert dock.api.is_admin
    assert store.load() == ((ME["email"], REFRESH) if remember else None)
    assert "secret" not in repr(vars(store))
    qt.QMessageBox.critical.assert_not_called()


def test_manual_non_admin_login_is_not_remembered(dock, qt):
    from plugins.farois_audit_rollback.api.farois_client import FaroisApiClient
    from plugins.farois_audit_rollback.api.session_store import MemorySessionStore
    from plugins.farois_audit_rollback.tests.test_farois_client import (
        ME, Opener, login_response,
    )

    store = MemorySessionStore()
    opener = Opener(login_response(), dict(ME, role="VIEWER"), {"detail": "ok"})
    dock.store = store
    dock.api = FaroisApiClient("http://api:8080", opener=opener, store=store)
    dock.connect_farois(credentials=(ME["email"], "secret", True))
    assert store.load() is None and not dock.api.connected
    assert opener.requests[-1][0].full_url.endswith("/api/v1/auth/logout")
    assert "VIEWER" in qt.QMessageBox.warning.call_args.args[2]


def test_disconnect_revokes_and_forgets_the_remembered_session(auto_dock):
    auto_dock.api = admin_api()
    auto_dock.disconnect_farois()
    auto_dock.api.logout.assert_called_once()
    assert auto_dock.store.load() is None
    auto_dock.load_history.assert_called_once_with(silent=True)


def test_explicit_login_replaces_the_auto_connect_banner(auto_dock):
    auto_dock.api = logged_out_api(resume=Mock(side_effect=FaroisApiUnavailable("down")))
    auto_dock.auto_connect_farois()
    assert auto_dock.api_label.text() == UNREACHABLE
    auto_dock.api = admin_api()
    auto_dock.connect_farois(credentials=(EMAIL, "pw", True))
    assert auto_dock.api_label.text() == f"Farois : {EMAIL} (ADMIN)"
    auto_dock.api = logged_out_api()
    auto_dock.disconnect_farois()
    assert "non connecté" in auto_dock.api_label.text()


def started_plugin(name):
    module = load_module(f"plugins.farois_audit_rollback.{name}", "plugin.py")
    iface = Mock()
    iface.addToolBar.return_value = Mock()
    plugin = module.FaroisAuditRollback(iface)
    plugin.initGui()
    module.FaroisAuditDock = Mock(side_effect=lambda *args, **kwargs: Mock())
    return module, plugin


def test_plugin_wires_one_qgis_store_into_client_and_dock(qt):
    from plugins.farois_audit_rollback.api.session_store import QgisSessionStore

    module, plugin = started_plugin("_tested_plugin_store")
    assert isinstance(plugin.store, QgisSessionStore)
    assert plugin.api._store is plugin.store
    assert plugin.dock is None  # initGui : ni panneau, ni réseau, ni magasin lu
    plugin.show_dock()
    module.FaroisAuditDock.assert_called_once_with(
        plugin.iface, api=plugin.api, store=plugin.store
    )


def test_auto_connect_runs_once_on_first_dock_opening(qt):
    module, plugin = started_plugin("_tested_plugin_auto_once")
    plugin.show_dock()
    first = plugin.dock
    first.auto_connect_farois.assert_called_once()
    plugin.show_dock()
    first.auto_connect_farois.assert_called_once()
    first.is_usable.return_value = False  # panneau détruit : recréé, sans relance
    plugin.show_dock()
    assert plugin.dock is not first
    plugin.dock.auto_connect_farois.assert_not_called()


def test_menu_connect_lets_the_dock_try_the_kept_token_once(qt):
    module, plugin = started_plugin("_tested_plugin_menu_connect")
    dock = Mock()
    module.FaroisAuditDock = Mock(return_value=dock)
    plugin.connect_farois()  # première ouverture par le menu
    dock.connect_farois.assert_called_once_with()  # reprise puis, si besoin, dialogue
    dock.auto_connect_farois.assert_not_called()  # pas de double tentative réseau


@pytest.mark.parametrize("kept", ["unreachable", "failed"])
def test_kept_token_rearms_the_automatic_attempt_for_the_next_opening(qt, kept):
    module, plugin = started_plugin(f"_tested_plugin_rearm_{kept}")
    dock = Mock()
    dock.auto_connect_farois.side_effect = [kept, "connected"]
    module.FaroisAuditDock = Mock(return_value=dock)
    plugin.show_dock()
    plugin.show_dock()  # nouvel essai : l'API répond cette fois
    plugin.show_dock()
    assert dock.auto_connect_farois.call_count == 2


@pytest.mark.parametrize("final", ["expired", "not_admin", None])
def test_definitive_outcomes_do_not_rearm_the_automatic_attempt(qt, final):
    module, plugin = started_plugin(f"_tested_plugin_no_rearm_{final}")
    dock = Mock()
    dock.auto_connect_farois.return_value = final
    module.FaroisAuditDock = Mock(return_value=dock)
    plugin.show_dock()
    plugin.show_dock()
    dock.auto_connect_farois.assert_called_once()


def test_menu_disconnect_clears_the_store_and_cancels_auto_connect(qt):
    module, plugin = started_plugin("_tested_plugin_menu_disconnect")
    plugin.api = SimpleNamespace(connected=True, logout=Mock(), forget=Mock())
    plugin.store = Mock()
    plugin.disconnect_farois()  # panneau jamais ouvert
    plugin.api.logout.assert_called_once()
    plugin.store.clear.assert_called_once()
    plugin.show_dock()
    plugin.dock.auto_connect_farois.assert_not_called()
    plugin.dock.is_usable.return_value = True
    plugin.disconnect_farois()  # panneau ouvert : il gère lui-même la déconnexion
    plugin.dock.disconnect_farois.assert_called_once()


@pytest.mark.parametrize(
    "failure, outcome",
    [
        (FaroisNotAuthenticated("Session Farois expirée : reconnectez-vous.", status=401), "expired"),
        (FaroisApiUnavailable("API Farois injoignable (http://x)."), "unreachable"),
        (RuntimeError("inattendu"), "failed"),
    ],
)
def test_auto_connect_reports_its_outcome(auto_dock, failure, outcome):
    auto_dock.api = logged_out_api(resume=Mock(side_effect=failure))
    assert auto_dock.auto_connect_farois() == outcome


def test_auto_connect_reports_success_non_admin_and_nothing_to_do(auto_dock):
    auto_dock.api = logged_out_api("ADMIN")
    assert auto_dock.auto_connect_farois() == "connected"
    assert auto_dock.auto_connect_farois() is None  # déjà connecté
    auto_dock.api = logged_out_api("VIEWER")
    assert auto_dock.auto_connect_farois() == "not_admin"
    assert auto_dock.auto_connect_farois() is None  # magasin vidé


def test_manual_connect_reuses_the_kept_token_without_asking(auto_dock):
    auto_dock.api = logged_out_api("ADMIN")
    auto_dock.connect_farois()  # ask_credentials interdit par la fixture
    auto_dock.api.resume.assert_called_once_with("rt-1")
    assert auto_dock.api.connected
    assert auto_dock.api_label.text() == f"Farois : {EMAIL} (ADMIN)"


@pytest.mark.parametrize(
    "failure, kept",
    [
        (FaroisNotAuthenticated("Session Farois expirée : reconnectez-vous.", status=401), False),
        (FaroisApiUnavailable("API Farois injoignable (http://x)."), True),
    ],
)
def test_manual_connect_asks_for_the_password_only_if_the_kept_token_fails(
    auto_dock, monkeypatch, failure, kept
):
    asked = Mock(return_value=None)
    monkeypatch.setitem(auto_dock.connect_farois.__func__.__globals__, "ask_credentials", asked)
    auto_dock.api = logged_out_api(resume=Mock(side_effect=failure))
    auto_dock.connect_farois()
    auto_dock.api.resume.assert_called_once_with("rt-1")
    asked.assert_called_once_with(auto_dock, EMAIL)
    assert auto_dock.store.load() == ((EMAIL, "rt-1") if kept else None)
    auto_dock.api.login.assert_not_called()  # dialogue annulé


def test_manual_connect_while_connected_asks_without_resuming(auto_dock, monkeypatch):
    asked = Mock(return_value=None)
    monkeypatch.setitem(auto_dock.connect_farois.__func__.__globals__, "ask_credentials", asked)
    auto_dock.api = admin_api()  # changement de compte
    auto_dock.connect_farois()
    auto_dock.api.resume.assert_not_called()
    asked.assert_called_once()


def editing(layer, name, modified=True):
    layer.name = lambda: name
    layer.isEditable = lambda: True
    layer.isModified = lambda: modified
    return layer


def roads_entry():
    return HistoryEntry(change_id="change", transaction_id=TX, can_undo=True,
                        schema_name="wyre", table_name="roads")


def test_modified_edit_buffer_of_the_entry_table_refuses_undo_with_layer_name(dock, qt, monkeypatch):
    source = pg_layer("source")
    twin = editing(pg_layer("twin"), "Routes éditées")
    project_with(dock, monkeypatch, source, twin)
    dock.layer = source
    dock._last_context = ("source", "uuid-record")
    dock.model = HistoryModel([roads_entry()])
    for state in dock.action_states():
        assert not state[0]
        assert state[1] == "Enregistrez ou annulez d'abord les modifications de la couche « Routes éditées »."
    dock.undo_selected()
    dock.repository.revert_change.assert_not_called()
    assert "Routes éditées" in qt.QMessageBox.warning.call_args.args[2]


def test_edit_buffer_of_another_table_or_without_changes_does_not_block(dock, monkeypatch):
    source = pg_layer("source")
    other = editing(pg_layer("cables", table="cables"), "Câbles")
    idle = editing(pg_layer("idle"), "Routes", modified=False)
    project_with(dock, monkeypatch, source, other, idle)
    dock.layer = source
    dock._last_context = ("source", "uuid-record")
    dock.model = HistoryModel([roads_entry()])
    assert all(state[0] for state in dock.action_states())


def test_edit_buffer_appearing_during_confirmation_blocks_the_call(dock, qt, monkeypatch):
    source = pg_layer("source")
    twin = pg_layer("twin")
    project_with(dock, monkeypatch, source, twin)
    dock.layer = source
    dock._last_context = ("source", "uuid-record")
    dock.model = HistoryModel([roads_entry()])

    def edit_meanwhile(*args):
        editing(twin, "Routes")
        return qt.QMessageBox.Yes

    qt.QMessageBox.question.side_effect = edit_meanwhile
    dock.undo_selected()
    dock.repository.revert_change.assert_not_called()
    qt.QMessageBox.critical.assert_called_once()
    assert "Routes" in qt.QMessageBox.critical.call_args.args[2]


def test_undo_never_asks_for_a_reason(dock, qt):
    dock.undo_selected()
    dock.undo_transaction_selected()
    qt.QInputDialog.getText.assert_not_called()
    assert AUTO_REASON == "Annulation depuis QGIS (plugin historique)"


@pytest.mark.parametrize("transaction", [False, True])
def test_confirmation_is_short_and_shows_no_values(dock, qt, transaction):
    dock.model = HistoryModel([HistoryEntry(
        change_id="change", transaction_id=TX, can_undo=True,
        before={"nom": "avant-secret"}, after={"nom": "apres-secret"})])
    (dock.undo_transaction_selected if transaction else dock.undo_selected)()
    message = qt.QMessageBox.question.call_args.args[2]
    for forbidden in ("Avant", "Après", "secret", "{"):
        assert forbidden not in message
    assert message.startswith("Annuler ")
    if transaction:
        assert "toute la transaction" in message and TX[:8] in message
    assert qt.QMessageBox.question.call_args.args[4] == qt.QMessageBox.No


def test_success_goes_to_the_message_bar_not_a_dialog(dock, qt):
    dock.undo_selected()
    dock.bar.pushSuccess.assert_called_once_with("Farois", "Annulation enregistrée.")
    qt.QMessageBox.information.assert_not_called()


def test_success_without_message_bar_shows_nothing(dock, qt):
    dock.iface = SimpleNamespace()
    dock.undo_selected()
    qt.QMessageBox.information.assert_not_called()
    qt.QMessageBox.critical.assert_not_called()


def test_nothing_undone_is_a_message_bar_warning(dock, qt):
    dock.api = admin_api(revert_change=Mock(return_value={}))
    dock.undo_selected()
    assert "Rien n'a été annulé" in dock.bar.pushWarning.call_args.args[1]
    dock.bar.pushSuccess.assert_not_called()


def test_postgres_path_receives_the_automatic_reason(dock):
    dock.undo_selected()
    dock.repository.revert_change.assert_called_once_with("change", AUTO_REASON)
