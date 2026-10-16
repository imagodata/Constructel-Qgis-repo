"""Dockable QGIS UI with selectable source layer and automatic refresh."""

import json

try:
    from qgis.PyQt.QtWidgets import (
        QDockWidget,
        QWidget,
        QVBoxLayout,
        QHBoxLayout,
        QLineEdit,
        QCheckBox,
        QTableWidget,
        QTableWidgetItem,
        QMessageBox,
        QInputDialog,
        QComboBox,
        QLabel,
        QGroupBox,
        QGridLayout,
        QSizePolicy,
        QMenu,
    )
    from qgis.PyQt.QtCore import QTimer, Qt, pyqtSignal, QSize, QItemSelectionModel
    from qgis.PyQt import sip
    from qgis.core import QgsProject

    QGIS_AVAILABLE = True
except ImportError:
    QGIS_AVAILABLE = False
from .history_model import HistoryModel, HistoryEntry
from .rollback_actions import action_states, transaction_uuid
from .login_dialog import ask_credentials
from .change_details import columns_label, summary_text, show_change_details
from ..api.farois_client import (
    REASON_MAX_LENGTH,
    FaroisApiUnavailable,
    FaroisConflict,
    FaroisNotAuthenticated,
    undo_had_effect,
)
from ..db.qgis_connection import repository_for_layer, selected_context, layer_context
from .lifecycle import SignalScope, live_ui
from .feature_navigation import (
    find_history_feature,
    matching_layers,
    navigation_target,
    resolve_history_features,
)

if QGIS_AVAILABLE:

    class FaroisAuditDock(QDockWidget):
        actionsChanged = pyqtSignal()
        HEADERS = [
            "Date",
            "Utilisateur",
            "Table",
            "Identifiant",
            "Libellé",
            "Opération",
            "Colonnes",
            "Avant → après",
            "Provenance",
            "Statut",
            "Transaction",
        ]

        def __init__(self, iface, parent=None, api=None):
            super().__init__(
                "Farois — Historique et rollback", parent or iface.mainWindow()
            )
            self.iface, self.repository, self.model = iface, None, HistoryModel()
            self.api = api
            self._signals = SignalScope(sip.isdeleted)
            self.destroyed.connect(self._signals.dispose)
            self._source_layer = None
            self._last_context = None
            self._loading = False
            self._undo_in_progress = False
            self._navigation_in_progress = False
            self._context_menu_open = False
            self._repository_key = None
            root = QWidget()
            main = QVBoxLayout(root)
            self.api_label = QLabel()
            self.api_label.setWordWrap(True)
            main.addWidget(self.api_label)
            source_box = QGroupBox("Objet source")
            source_layout = QVBoxLayout(source_box)
            source_row = QHBoxLayout()
            source_row.addWidget(QLabel("Couche :"))
            self.layer_combo = QComboBox()
            self.layer_combo.setMinimumWidth(0)
            self.layer_combo.setMinimumContentsLength(12)
            self.layer_combo.setSizeAdjustPolicy(
                QComboBox.AdjustToMinimumContentsLengthWithIcon
            )
            self.layer_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.layer_combo.currentIndexChanged.connect(self._on_layer_choice)
            source_row.addWidget(self.layer_combo, 1)
            self.context_label = QLabel("Aucune sélection")
            self.context_label.setWordWrap(True)
            source_layout.addLayout(source_row)
            self.history_scope = QComboBox()
            self.history_scope.addItem("Couche source — récent", "layer")
            self.history_scope.addItem("Objet sélectionné", "object")
            self.history_scope.addItem("Tous les changements visibles", "visible")
            self.history_scope.setMinimumContentsLength(12)
            self.history_scope.setSizeAdjustPolicy(
                QComboBox.AdjustToMinimumContentsLengthWithIcon
            )
            source_layout.addWidget(self.history_scope)
            source_layout.addWidget(self.context_label)
            main.addWidget(source_box)

            filter_box = QGroupBox("Filtres d'historique")
            filters = QGridLayout(filter_box)
            self.user, self.provenance, self.column = (
                QLineEdit(),
                QLineEdit(),
                QLineEdit(),
            )
            self.user.setPlaceholderText("Utilisateur")
            self.provenance.setPlaceholderText("Provenance")
            self.column.setPlaceholderText("Colonne")
            self.cancelable = QCheckBox("Annulables uniquement")
            for index, widget in enumerate(
                (self.user, self.provenance, self.column, self.cancelable)
            ):
                filters.addWidget(widget, index // 2, index % 2)
            main.addWidget(filter_box)
            self.table = QTableWidget(0, len(self.HEADERS))
            self.table.setHorizontalHeaderLabels(self.HEADERS)
            self.table.setSelectionBehavior(QTableWidget.SelectRows)
            self.table.setAlternatingRowColors(True)
            self.table.setMinimumWidth(0)
            self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.table.setSelectionMode(QTableWidget.ExtendedSelection)
            self.table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.table.customContextMenuRequested.connect(self._history_context_menu)
            self.table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.table.itemSelectionChanged.connect(self._update_actions)
            self.table.cellDoubleClicked.connect(self.identify_history_object)
            main.addWidget(self.table, 1)

            self.navigation_label = QLabel(
                "Clic droit sur l’historique : identifier, zoomer, sélectionner."
            )
            self.navigation_label.setWordWrap(True)
            main.addWidget(self.navigation_label)
            self.auto_refresh = QCheckBox("Actualisation automatique")
            self.auto_refresh.setChecked(True)
            main.addWidget(self.auto_refresh)
            self.connection_label = QLabel(
                "Connexion : en attente de la couche source."
            )
            self.connection_label.setWordWrap(True)
            main.addWidget(self.connection_label)
            self.setWidget(root)
            self.setMinimumWidth(320)

            self.history_scope.currentIndexChanged.connect(self._history_scope_changed)
            for edit in (self.user, self.provenance, self.column):
                edit.editingFinished.connect(self._filters_changed)
            self.cancelable.stateChanged.connect(self._filters_changed)

            self.refresh_timer = QTimer(self)
            self.refresh_timer.setInterval(5000)
            self._signals.connect(
                self.refresh_timer.timeout, self._auto_refresh, self.refresh_timer
            )
            self.refresh_timer.start()
            self._connect_project_signals()
            self._populate_layers()
            self._update_actions()
            self._render_api_status()

        def sizeHint(self):
            return QSize(460, 600)

        def is_usable(self):
            if self._signals.disposed or sip.isdeleted(self):
                return False
            return all(
                not sip.isdeleted(widget)
                for widget in (
                    self.layer_combo,
                    self.table,
                    self.context_label,
                    self.connection_label,
                    self.history_scope,
                    self.navigation_label,
                )
            )

        def _connect_project_signals(self):
            self._signals.connect(
                self.iface.currentLayerChanged,
                self._on_active_layer_changed,
                self.iface,
            )
            project = QgsProject.instance()
            self._signals.connect(
                project.layersAdded, self._project_layers_changed, project
            )
            self._signals.connect(
                project.layersRemoved, self._project_layers_changed, project
            )
            self._signals.connect(
                project.cleared, self._project_layers_changed, project
            )

        @live_ui
        def _project_layers_changed(self, *args):
            self._populate_layers()

        @live_ui
        def _populate_layers(self):
            current_id = self.layer_combo.currentData()
            self.layer_combo.blockSignals(True)
            self.layer_combo.clear()
            self.layer_combo.addItem("Couche active", None)
            for layer in QgsProject.instance().mapLayers().values():
                if sip.isdeleted(layer):
                    continue
                if (
                    layer.type() == 0
                    and layer.dataProvider().name().lower() == "postgres"
                ):
                    self.layer_combo.addItem(layer.name(), layer.id())
            index = self.layer_combo.findData(current_id)
            self.layer_combo.setCurrentIndex(index if index >= 0 else 0)
            self.layer_combo.blockSignals(False)
            self._resolve_source_layer()
            self.refresh_context(auto=True)

        @live_ui
        def _resolve_source_layer(self):
            chosen_id = self.layer_combo.currentData()
            self._source_layer = (
                QgsProject.instance().mapLayer(chosen_id)
                if chosen_id
                else self.iface.activeLayer()
            )
            if self._source_layer is not None and sip.isdeleted(self._source_layer):
                self._source_layer = None
            return self._source_layer

        @live_ui
        def _on_layer_choice(self, index):
            self._resolve_source_layer()
            self.refresh_context(auto=True)

        @live_ui
        def _on_active_layer_changed(self, layer):
            if self.layer_combo.currentIndex() == 0:
                self._source_layer = layer
                self.refresh_context(auto=True)

        @live_ui
        def _on_selection_changed(self, *args):
            self.refresh_context(auto=True)

        @live_ui
        def refresh_context(self, auto=False):
            if self._navigation_in_progress or self._context_menu_open:
                return
            layer = self._resolve_source_layer()
            self._wire_selection_signal(layer)
            if layer is None:
                self.context_label.setText("Aucune couche source sélectionnée.")
                self._clear_history()
                return
            if layer.type() != 0 or layer.dataProvider().name().lower() != "postgres":
                self.context_label.setText("Choisissez une couche PostgreSQL.")
                self._clear_history()
                return
            selected = layer.selectedFeatureIds()
            mode = self.history_scope.currentData()
            if mode == "object" and len(selected) != 1:
                self._clear_history()
                self.connection_label.setText(
                    "Mode objet : sélectionnez exactement un objet, ou choisissez un historique de couche."
                )
            provider = layer.dataProvider().name()
            self.context_label.setText(
                f"Couche : {layer.name()} — fournisseur : {provider} — "
                f"sélection : {len(selected)} objet(s)"
            )
            if auto and (mode != "object" or len(selected) == 1):
                self.load_history(silent=True)
            self._update_actions()

        def _selected_context(self):
            return selected_context(self._resolve_source_layer())

        def _history_context(self):
            layer = self._resolve_source_layer()
            mode = self.history_scope.currentData()
            if mode == "object":
                return selected_context(layer)
            if mode == "layer":
                return layer_context(layer)
            if layer is None or layer.type() != 0 or layer.providerType() != "postgres":
                raise ValueError("Choisissez une couche PostgreSQL pour sa connexion.")
            return layer, None, None, None

        @live_ui
        def _history_scope_changed(self, *args):
            self._clear_history()
            self.refresh_context(auto=True)

        @live_ui
        def _reset_filters(self, *args):
            for edit in (self.user, self.provenance, self.column):
                edit.clear()
            self.cancelable.blockSignals(True)
            self.cancelable.setChecked(False)
            self.cancelable.blockSignals(False)
            self._clear_history()
            self.load_history()

        def _ensure_repository(self, layer):
            key = (layer.id(), hash(layer.source()))
            if self.repository is not None and self._repository_key == key:
                return
            if self.repository is not None:
                self._signals.replace_database(None)
            self.repository = None
            self._repository_key = None
            self.repository = repository_for_layer(layer)
            self._signals.replace_database(self.repository)
            self._repository_key = key

        @live_ui
        def _auto_refresh(self):
            if (
                self.isVisible()
                and self.auto_refresh.isChecked()
                and not self._undo_in_progress
                and not self._navigation_in_progress
            ):
                self.refresh_context(auto=True)

        @live_ui
        def _filters_changed(self, *args):
            self._clear_history()
            self.load_history()

        @live_ui
        def load_history(self, *args, silent=False):
            if (
                self._undo_in_progress
                or self._navigation_in_progress
                or self._context_menu_open
            ):
                return
            if self._loading:
                return
            self._loading = True
            try:
                layer, schema, table, record_id = self._history_context()
                self._ensure_repository(layer)
                mode = self.history_scope.currentData()
                if mode == "object":
                    rows = self.repository.history(schema, table, record_id)
                    self.context_label.setText(
                        f"Objet : {schema}.{table} — UUID : {record_id}"
                    )
                elif mode == "layer":
                    rows = self.repository.layer_history(schema, table)
                    self.context_label.setText(
                        f"Couche : {schema}.{table} — 200 derniers changements visibles"
                    )
                else:
                    rows = self.repository.visible_history()
                    self.context_label.setText(
                        "Tous les changements autorisés par PostgreSQL — 200 derniers"
                    )
                if not self.repository.engine_available:
                    self.cancelable.blockSignals(True)
                    self.cancelable.setChecked(False)
                    self.cancelable.blockSignals(False)
                self.cancelable.setEnabled(bool(self.repository.engine_available))
                self.cancelable.setToolTip(
                    "Ce filtre nécessite le moteur d’annulation."
                )
                selected_ids = [e.change_id for e in self._selected_history_entries()]
                same_context = self._last_context == (layer.id(), record_id)
                self.model.set_entries(
                    self._entry_view(HistoryEntry.from_row(row)) for row in rows
                )
                self._last_context = (layer.id(), record_id)
                self._render(selected_ids if same_context else None)
                shown = len(self._filtered_entries())
                summary = f"{len(rows)} entrée(s) chargée(s), {shown} affichée(s). "
                if not rows:
                    summary += "Aucun changement visible pour ce périmètre. Essayez « Tous les changements visibles ». "
                elif not shown:
                    summary += (
                        "Les filtres masquent toutes les entrées ; réinitialisez-les. "
                    )
                self.connection_label.setText(
                    "Connexion PostgreSQL de la couche : OK. "
                    + summary
                    + (
                        (
                            "Moteur d'annulation FIELD disponible ; auteur et identité vérifiés par PostgreSQL."
                            if getattr(self.repository, "engine_contract", None)
                            == "legacy_field"
                            else "Moteur d'annulation disponible."
                        )
                        if self.repository.engine_available
                        else "Le moteur d’annulation Farois est indisponible pour cette connexion (installation, contrat ou droits PostgreSQL)."
                    )
                )
            except Exception as exc:
                self._clear_history()
                self.connection_label.setText(f"Lecture impossible : {exc}")
                if not silent:
                    QMessageBox.critical(self, "Farois", str(exc))
            finally:
                self._loading = False
                self._update_actions()

        @live_ui
        def _render(self, selected_id=None):
            entries = self._filtered_entries()
            selected_ids = (
                {str(value) for value in selected_id}
                if isinstance(selected_id, (list, tuple, set))
                else {str(selected_id)}
                if selected_id is not None
                else set()
            )
            self.table.blockSignals(True)
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            self.table.setRowCount(len(entries))
            for r, e in enumerate(entries):
                values = [
                    e.changed_at,
                    e.username,
                    e.table_name,
                    e.record_id,
                    e.label,
                    e.operation,
                    columns_label(e),
                    summary_text(e),
                    e.provenance,
                    e.status_message,
                    e.transaction_id,
                ]
                for c, value in enumerate(values):
                    item = QTableWidgetItem(str(value or ""))
                    if not e.can_undo:
                        item.setForeground(Qt.gray)
                    item.setToolTip(
                        json.dumps(
                            {
                                "Utilisateur": e.username,
                                "Libellé": e.label,
                                "Provenance": e.provenance,
                                "Colonnes": e.changed_columns,
                                "Avant": e.before,
                                "Après": e.after,
                                "Annulation": e.status_message,
                            },
                            ensure_ascii=False,
                            indent=2,
                            default=str,
                        )
                    )
                    if c == self.HEADERS.index("Avant → après"):
                        full = summary_text(e, full=True)
                        if full:
                            item.setToolTip(full)
                    self.table.setItem(r, c, item)
                if str(e.change_id) in selected_ids:
                    index = self.table.model().index(r, 0)
                    self.table.selectionModel().select(
                        index, QItemSelectionModel.Select | QItemSelectionModel.Rows
                    )
                    self.table.selectionModel().setCurrentIndex(
                        index, QItemSelectionModel.NoUpdate
                    )
            self.table.blockSignals(False)
            self.table.resizeColumnsToContents()
            self._update_actions()

        @live_ui
        def _clear_history(self):
            self._last_context = None
            self.model.set_entries([])
            self.table.setRowCount(0)
            self._update_actions()

        def action_states(self):
            if not self.is_usable():
                return (False, "Panneau fermé."), (False, "Panneau fermé.")
            if len(self._selected_history_entries()) > 1:
                reason = "Sélectionnez une seule modification pour une annulation."
                return (False, reason), (False, reason)
            if self._admin_api():
                # L'API annule par change_id : ni mode objet ni sélection carte
                # (un objet supprimé n'est plus sélectionnable). « Courant » =
                # historique chargé.
                current = self._last_context is not None
            else:
                scope = getattr(self, "history_scope", None)
                if scope is not None and scope.currentData() != "object":
                    reason = "Pour annuler, passez en mode Objet sélectionné et sélectionnez cet objet."
                    return (False, reason), (False, reason)
                try:
                    layer, _, _, record_id = self._selected_context()
                    current = self._last_context == (layer.id(), record_id)
                except (ValueError, RuntimeError, AttributeError):
                    current = False
            if self.repository is not None and not self.repository.engine_available:
                reason = "Le moteur d’annulation Farois est indisponible pour cette connexion (installation, contrat ou droits PostgreSQL)."
                return (False, reason), (False, reason)
            project = QgsProject.instance() if hasattr(QgsProject, "instance") else None
            if project is not None and any(
                item.providerType() == "postgres" and item.isEditable()
                for item in project.mapLayers().values()
                if hasattr(item, "providerType") and hasattr(item, "isEditable")
            ):
                reason = (
                    "Enregistrez ou abandonnez les éditions PostgreSQL avant d'annuler."
                )
                return (False, reason), (False, reason)
            return action_states(
                self._entry_for_current_row(),
                connected=self.repository is not None,
                current=current and not self._undo_in_progress,
            )

        @live_ui
        def _update_actions(self):
            self.actionsChanged.emit()

        def _navigation_state(self):
            try:
                entries = self._selected_history_entries()
                if not entries:
                    raise ValueError(
                        "Sélectionnez une ou plusieurs lignes de l’historique."
                    )
                for entry in entries:
                    navigation_target(entry)
                return (
                    not self._navigation_in_progress and not self._undo_in_progress,
                    "Retrouver les objets dans les couches PostgreSQL chargées de la même connexion.",
                )
            except ValueError as exc:
                return False, str(exc)

        @live_ui
        def _history_context_menu(self, position):
            item = self.table.itemAt(position)
            selected_rows = {
                i.row() for i in self.table.selectionModel().selectedRows()
            }
            if item is not None and item.row() not in selected_rows:
                self.table.clearSelection()
                self.table.setCurrentCell(item.row(), item.column())
                self.table.selectRow(item.row())
            menu = QMenu(self)
            identify = zoom = select = edit = details = undo = transaction = None
            if item is not None:
                identify = menu.addAction("Identifier les objets")
                zoom = menu.addAction("Zoomer sur les objets")
                select = menu.addAction("Sélectionner les objets")
                edit = menu.addAction("Modifier l'objet")
                edit.setEnabled(
                    len(self._selected_history_entries()) == 1
                    and self._navigation_state()[0]
                )
                edit.setToolTip(
                    "Ouvrir les attributs actuels en édition QGIS ; enregistrer ensuite les modifications dans QGIS."
                )
                details = menu.addAction("Voir les valeurs avant/après")
                details.setEnabled(len(self._selected_history_entries()) == 1)
                enabled, reason = self._navigation_state()
                for action in (identify, zoom, select):
                    action.setEnabled(enabled)
                    action.setToolTip(reason)
                menu.addSeparator()
                undo = menu.addAction("Annuler la modification")
                transaction = menu.addAction("Annuler la transaction")
                for action, (enabled, reason) in zip(
                    (undo, transaction), self.action_states()
                ):
                    action.setEnabled(enabled)
                    action.setToolTip(reason)
                menu.addSeparator()
            refresh = menu.addAction("Actualiser l’historique")
            reset = menu.addAction("Réinitialiser les filtres")
            api = getattr(self, "api", None)
            farois = menu.addAction(
                "Se déconnecter de Farois"
                if api is not None and api.connected
                else "Se connecter à Farois…"
            )
            idle = not self._navigation_in_progress and not self._undo_in_progress
            refresh.setEnabled(idle)
            reset.setEnabled(idle)
            farois.setEnabled(idle and api is not None)
            self._context_menu_open = True
            try:
                chosen = menu.exec_(self.table.viewport().mapToGlobal(position))
            finally:
                self._context_menu_open = False
                if not sip.isdeleted(menu):
                    menu.deleteLater()
            if self.is_usable() and chosen is not None and chosen.isEnabled():
                if chosen is identify:
                    self.identify_history_object()
                elif chosen is edit:
                    self.edit_history_object()
                elif chosen is details:
                    entry = self._entry_for_current_row()
                    if entry is not None:
                        show_change_details(entry, self)
                elif chosen is zoom:
                    self.zoom_history_objects()
                elif chosen is select:
                    self.select_history_object()
                elif chosen is undo:
                    self.undo_selected()
                elif chosen is transaction:
                    self.undo_transaction_selected()
                elif chosen is refresh:
                    self.load_history()
                elif chosen is reset:
                    self._reset_filters()
                elif chosen is farois:
                    if api.connected:
                        self.disconnect_farois()
                    else:
                        self.connect_farois()

        @live_ui
        def select_history_object(self, *args):
            self._navigate_history_object(identify=False)

        @live_ui
        def identify_history_object(self, *args):
            self._navigate_history_object(identify=True)

        @live_ui
        def edit_history_object(self, *args):
            if len(self._selected_history_entries()) != 1:
                QMessageBox.warning(
                    self, "Farois", "Sélectionnez un seul objet à modifier."
                )
                return
            self._navigate_history_object(identify=True, edit=True)

        @live_ui
        def zoom_history_objects(self, *args):
            self._navigate_history_object(identify=False, zoom=True)

        @live_ui
        def _navigate_history_object(self, identify, zoom=False, edit=False):
            if self._navigation_in_progress or self._undo_in_progress:
                return
            entries = self._selected_history_entries()
            self._navigation_in_progress = True
            navigated = False
            try:
                targets = resolve_history_features(
                    entries,
                    self._resolve_source_layer(),
                    QgsProject.instance().mapLayers().values(),
                    sip.isdeleted,
                    resolver=find_history_feature,
                )
                if zoom and any(
                    not layer.isSpatial()
                    or not feature.hasGeometry()
                    or feature.geometry().isEmpty()
                    for layer, feature in targets
                ):
                    raise ValueError(
                        "Zoom impossible : un objet n'a pas de géométrie utilisable."
                    )
                self._update_actions()
                groups = {}
                for layer, feature in targets:
                    groups.setdefault(layer.id(), (layer, []))[1].append(feature.id())
                for layer, ids in groups.values():
                    layer.selectByIds(ids)
                    layer.triggerRepaint()
                layer = targets[0][0]
                index = self.layer_combo.findData(layer.id())
                if index >= 0:
                    self.layer_combo.blockSignals(True)
                    self.layer_combo.setCurrentIndex(index)
                    self.layer_combo.blockSignals(False)
                self.iface.setActiveLayer(layer)
                navigated = True
                self.navigation_label.setText(
                    f"Objet sélectionné : {len(targets)} objet(s) dans {len(groups)} couche(s)."
                )
                if zoom:
                    canvas = self.iface.mapCanvas()
                    canvas.zoomToSelected([group[0] for group in groups.values()])
                    canvas.refresh()
                if identify:
                    from qgis.gui import QgsAttributeDialog, QgsAttributeEditorContext

                    for number, (layer, feature) in enumerate(targets, 1):
                        if not self.is_usable() or sip.isdeleted(layer):
                            break
                        if edit and not layer.isEditable() and not layer.startEditing():
                            raise ValueError(
                                "Cette couche ne permet pas l'édition avec la connexion actuelle."
                            )
                        context = QgsAttributeEditorContext()
                        form_mode = (
                            QgsAttributeEditorContext.SingleEditMode
                            if edit
                            else QgsAttributeEditorContext.IdentifyMode
                        )
                        context.setAttributeFormMode(form_mode)
                        context.setAllowCustomUi(False)
                        dialog = QgsAttributeDialog(
                            layer, feature, False, self, True, context
                        )
                        try:
                            dialog.setMode(form_mode)
                            dialog.setWindowTitle(
                                "Farois — Modifier l'objet (enregistrer ensuite dans QGIS)"
                                if edit
                                else f"Farois — Identifier {number}/{len(targets)} (lecture seule)"
                            )
                            dialog.exec_()
                        finally:
                            if not sip.isdeleted(dialog):
                                dialog.deleteLater()
            except Exception as exc:
                if self.is_usable():
                    self.navigation_label.setText(str(exc))
                    QMessageBox.warning(
                        self, "Farois — Objet de l’historique", str(exc)
                    )
            finally:
                self._navigation_in_progress = False
                if self.is_usable():
                    if navigated:
                        self.refresh_context(auto=True)
                        self._render([entry.change_id for entry in entries])
                    self._update_actions()

        def _entry_for_current_row(self):
            row = self.table.currentRow()
            entries = self._filtered_entries()
            if hasattr(self.table, "selectionModel") and row not in {
                i.row() for i in self.table.selectionModel().selectedRows()
            }:
                return None
            return entries[row] if 0 <= row < len(entries) else None

        def _selected_history_entries(self):
            if not hasattr(self.table, "selectionModel"):
                entry = self._entry_for_current_row()
                return [entry] if entry is not None else []
            entries = self._filtered_entries()
            rows = sorted(i.row() for i in self.table.selectionModel().selectedRows())
            return [entries[row] for row in rows if 0 <= row < len(entries)]

        def _filtered_entries(self):
            return self.model.filtered(
                user=self.user.text(),
                provenance=self.provenance.text(),
                column=self.column.text(),
                cancelable_only=self.cancelable.isChecked(),
            )

        def undo_selected(self):
            self._request_undo(transaction=False)

        def undo_transaction_selected(self):
            self._request_undo(transaction=True)

        @live_ui
        def _request_undo(self, transaction):
            entry = self._entry_for_current_row()
            enabled, refusal = self.action_states()[int(transaction)]
            if not enabled:
                QMessageBox.warning(self, "Farois", refusal)
                return
            admin = self._admin_api()
            if not admin:
                layer, _, _, record_id = self._selected_context()
                context = (layer.id(), record_id)
                selected_ids = layer.selectedFeatureIds()
            repository = self.repository
            target_id = transaction_uuid(entry) if transaction else entry.change_id
            self._undo_in_progress = True
            self._update_actions()
            try:
                if transaction:
                    title = "Confirmer l'annulation de la transaction"
                    message = (
                        f"Transaction : {target_id}\n"
                        "Toutes les modifications de cette transaction sont concernées, "
                        "y compris celles des autres objets et les cascades éventuelles.\n"
                        "Le périmètre complet n'est pas prévisualisé par ce panneau. "
                        "PostgreSQL vérifiera les droits et les conflits. Continuer ?"
                    )
                else:
                    title = "Confirmer l'annulation de la modification"
                    preview = json.dumps(
                        {"Avant": entry.before, "Après": entry.after},
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    )
                    message = f"Modification : {target_id}\n{preview}\nContinuer ?"
                if (
                    QMessageBox.question(
                        self,
                        title,
                        message,
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No,
                    )
                    != QMessageBox.Yes
                ):
                    return
                reason, ok = QInputDialog.getText(self, "Motif obligatoire", "Motif :")
                if not self.is_usable() or not ok or not reason.strip():
                    return
                if admin:
                    if self.repository is not repository or not any(
                        item.change_id == entry.change_id for item in self.model.entries
                    ):
                        raise ValueError(
                            "L'historique a changé pendant la confirmation. Actualisez l'historique."
                        )
                else:
                    current_layer, _, _, current_id = self._selected_context()
                    if (
                        current_layer.id(),
                        current_id,
                    ) != context or self.repository is not repository:
                        raise ValueError(
                            "La couche source ou la sélection a changé. Actualisez l'historique."
                        )
                project = (
                    QgsProject.instance() if hasattr(QgsProject, "instance") else None
                )
                if project is not None and any(
                    item.providerType() == "postgres" and item.isEditable()
                    for item in project.mapLayers().values()
                    if hasattr(item, "providerType") and hasattr(item, "isEditable")
                ):
                    raise ValueError(
                        "Enregistrez ou abandonnez les éditions PostgreSQL avant d'annuler."
                    )
                if admin:
                    undo_id = self._undo_via_api(entry, transaction, target_id, reason)
                    if undo_id is None:
                        return
                elif transaction:
                    undo_id = repository.revert_transaction(target_id, reason)
                else:
                    undo_id = repository.revert_change(target_id, reason)
                if isinstance(undo_id, dict) and (
                    undo_id.get("success") is False or undo_id.get("conflicts")
                ):
                    QMessageBox.warning(
                        self,
                        "Farois — Refus / conflits",
                        json.dumps(undo_id, ensure_ascii=False, default=str),
                    )
                    return
                if admin:
                    self._reload_entry_layers(entry)
                else:
                    layer.reload()
                    layer.selectByIds(selected_ids)
                    layer.triggerRepaint()
                result_label = (
                    json.dumps(undo_id, ensure_ascii=False, indent=2, default=str)
                    if isinstance(undo_id, dict)
                    else str(undo_id)
                )
                QMessageBox.information(
                    self, "Farois", f"Annulation enregistrée : {result_label}"
                )
            except Exception as exc:
                if self.is_usable():
                    QMessageBox.critical(self, "Farois", str(exc))
            finally:
                self._undo_in_progress = False
                self._render_api_status()
                self.load_history(silent=True)
                self._update_actions()

        def _wire_selection_signal(self, layer):
            # Raster layers do not expose selectionChanged; never retain them here.
            if layer is not None and (sip.isdeleted(layer) or layer.type() != 0):
                layer = None
            previous = getattr(self, "_connected_selection_layer", None)
            if previous is layer:
                return
            if previous is not None and not sip.isdeleted(previous):
                try:
                    self._signals.disconnect(
                        previous.selectionChanged, self._on_selection_changed
                    )
                except (TypeError, RuntimeError, AttributeError):
                    pass
            self._connected_selection_layer = layer
            if layer is not None:
                self._signals.connect(
                    layer.selectionChanged, self._on_selection_changed, layer
                )

        def _admin_api(self):
            api = getattr(self, "api", None)
            return api is not None and api.is_admin

        def _entry_view(self, entry):
            return entry.as_admin() if self._admin_api() else entry

        def _render_api_status(self):
            label = getattr(self, "api_label", None)
            if label is None or sip.isdeleted(label):
                return
            api = getattr(self, "api", None)
            if api is not None and api.connected:
                label.setText(f"Farois : {api.profile.email} ({api.profile.role})")
            else:
                label.setText(
                    "Farois : non connecté — annulations soumises aux droits PostgreSQL."
                )

        def connect_farois(self, credentials=None):
            api = getattr(self, "api", None)
            if api is None:
                return
            if credentials is None:
                credentials = ask_credentials(
                    self, api.last_email or (api.profile.email if api.profile else "")
                )
            if not credentials:
                return
            was_connected = api.connected
            try:
                profile = api.login(*credentials)
            except Exception as exc:
                QMessageBox.critical(self, "Farois", str(exc))
                if was_connected:
                    self.api_session_changed()
                return
            if not profile.is_admin:
                api.logout()
                QMessageBox.warning(
                    self,
                    "Farois",
                    f"Le compte {profile.email} a le rôle {profile.role} : "
                    "l'annulation via l'API est réservée aux rôles ADMIN et MANAGER.",
                )
            self.api_session_changed()

        def disconnect_farois(self):
            api = getattr(self, "api", None)
            if api is not None:
                api.logout()
            self.api_session_changed()

        def api_session_changed(self):
            self._render_api_status()
            self.load_history(silent=True)

        def _undo_via_api(self, entry, transaction, target_id, reason):
            """Envoie l'annulation à l'API ; None si rien n'a été annulé (déjà signalé)."""
            if len(reason.strip()) > REASON_MAX_LENGTH:
                QMessageBox.warning(
                    self,
                    "Farois",
                    f"Motif trop long ({len(reason.strip())} caractères, "
                    f"{REASON_MAX_LENGTH} au maximum) : rien n'a été envoyé.",
                )
                return None
            api = self.api
            send = api.revert_transaction if transaction else api.revert_change
            mode = "RESTORE" if not transaction and entry.operation == "DELETE" else "FIELD"
            try:
                result = send(target_id, mode, reason)
            except FaroisApiUnavailable as exc:
                self._warn_uncertain(exc)
                return None
            except FaroisNotAuthenticated:
                self._render_api_status()
                QMessageBox.warning(
                    self,
                    "Farois",
                    "Session Farois expirée : reconnectez-vous puis relancez l'annulation. "
                    "Rien n'a été annulé.",
                )
                return None
            except FaroisConflict as conflict:
                if mode == "RESTORE" or not conflict.forceable:
                    raise
                if not self._confirm_force(conflict, transaction):
                    return None
                try:
                    result = send(target_id, "FORCE", reason)
                except FaroisApiUnavailable as exc:
                    self._warn_uncertain(exc)
                    return None
            if not undo_had_effect(result):
                # 200 sans aucun effet (changes vide, rien de restauré/annulé).
                QMessageBox.warning(
                    self,
                    "Farois",
                    "Rien n'a été annulé : l'API Farois n'a rapporté aucun effet "
                    "(modification déjà annulée ou sans changement).",
                )
                return None
            return result

        def _reload_entry_layers(self, entry):
            """Recharge les couches de la table annulée (connexion de la source).

            À défaut, la couche source. La sélection n'est rétablie qu'en mode
            objet ; ailleurs elle n'est pas touchée.
            """
            source = self._resolve_source_layer()
            project = QgsProject.instance() if hasattr(QgsProject, "instance") else None
            layers = []
            if entry.schema_name and entry.table_name and project is not None:
                try:
                    layers = matching_layers(
                        entry.schema_name,
                        entry.table_name,
                        source,
                        list(project.mapLayers().values()),
                        sip.isdeleted,
                    )
                except ValueError:
                    layers = []
            if not layers and source is not None and not sip.isdeleted(source):
                layers = [source]
            scope = getattr(self, "history_scope", None)
            keep_selection = scope is not None and scope.currentData() == "object"
            for layer in layers:
                selected_ids = layer.selectedFeatureIds() if keep_selection else None
                layer.reload()
                if keep_selection:
                    layer.selectByIds(selected_ids)
                layer.triggerRepaint()

        def _warn_uncertain(self, exc):
            QMessageBox.warning(
                self,
                "Farois",
                f"{exc}\nRésultat incertain : si la requête a atteint le serveur, "
                "l'annulation a pu être enregistrée. Actualisez l'historique avant "
                "de relancer (une annulation déjà faite sera refusée).",
            )

        def _confirm_force(self, conflict, transaction=False):
            report = conflict.report if isinstance(conflict.report, dict) else {}
            # Modification : ses conflits ; transaction : rapport du membre en conflit.
            shown = report.get("conflicts") or report.get("changes")
            if shown:
                details = json.dumps(shown, ensure_ascii=False, indent=2, default=str)
            else:
                detail = conflict.detail if isinstance(conflict.detail, dict) else {}
                engine = str(detail.get("engine") or "")
                details = engine if engine not in str(conflict) else ""
            consequence = "Les valeurs actuelles en conflit seront écrasées."
            if transaction:
                consequence += (
                    " Les objets créés par cette transaction seront supprimés même "
                    "s'ils ont été modifiés ou référencés depuis ; des suppressions "
                    "en cascade sont possibles."
                )
            text = "\n".join(part for part in (str(conflict), details) if part)
            return (
                QMessageBox.question(
                    self,
                    "Farois — Conflit",
                    f"{text}\n\nForcer l'annulation (FORCE) ? {consequence}",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                == QMessageBox.Yes
            )

        def dispose(self):
            self._signals.dispose()
            timer = getattr(self, "refresh_timer", None)
            if timer is not None and not sip.isdeleted(timer):
                timer.stop()
            self.repository = None
            self._source_layer = None
            self._connected_selection_layer = None

else:

    class FaroisAuditDock:
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "Les bindings QGIS sont nécessaires pour afficher le panneau."
            )
