"""QGIS plugin lifecycle: one toolbar entry opening the history dock."""

import os

from .gui.dockwidget import FaroisAuditDock

ICON_PATH = os.path.join(os.path.dirname(__file__), "icon.svg")


class FaroisAuditRollback:
    def __init__(self, iface):
        self.iface, self.dock, self.toolbar = iface, None, None
        self.actions = []
        self._unloading = False

    def initGui(self):
        from qgis.PyQt.QtWidgets import QAction
        from qgis.PyQt.QtGui import QIcon

        self._unloading = False

        self.toolbar = self.iface.addToolBar("Farois — Historique et rollback")
        self.toolbar.setObjectName("FaroisAuditRollbackToolbar")
        self.action = QAction("Historique Farois", self.iface.mainWindow())
        self.action.setIcon(QIcon(ICON_PATH))
        self.change_action = QAction("Annuler la modification", self.iface.mainWindow())
        self.transaction_action = QAction(
            "Annuler la transaction", self.iface.mainWindow()
        )
        self.action.triggered.connect(self.show_dock)
        self.change_action.triggered.connect(self.undo_change)
        self.transaction_action.triggered.connect(self.undo_transaction)
        self.actions = [self.action, self.change_action, self.transaction_action]
        self.toolbar.addAction(self.action)
        for action in self.actions:
            self.iface.addPluginToMenu("&Farois", action)
        self.sync_actions()

    def show_dock(self):
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt import sip

        if self._unloading:
            return

        if self.dock is not None and not self.dock.is_usable():
            old, self.dock = self.dock, None
            old.dispose()
            if not sip.isdeleted(old):
                self.iface.removeDockWidget(old)
                old.deleteLater()
        if self.dock is None:
            self.dock = FaroisAuditDock(self.iface)
            self.dock.actionsChanged.connect(self.sync_actions)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.show()
        self.dock.raise_()
        self.dock.refresh_context()

    def sync_actions(self):
        from qgis.PyQt import sip

        if self._unloading:
            return
        states = (
            self.dock.action_states()
            if self.dock is not None and self.dock.is_usable()
            else (
                (False, "Ouvrez l'historique et sélectionnez une modification."),
                (False, "Ouvrez l'historique et sélectionnez une transaction."),
            )
        )
        for action, (enabled, reason) in zip(
            (self.change_action, self.transaction_action), states
        ):
            if sip.isdeleted(action):
                continue
            action.setEnabled(enabled)
            action.setToolTip(reason)

    def undo_change(self):
        if self.dock is not None and self.dock.is_usable():
            self.dock.undo_selected()

    def undo_transaction(self):
        if self.dock is not None and self.dock.is_usable():
            self.dock.undo_transaction_selected()

    def unload(self):
        from qgis.PyQt import sip

        self._unloading = True

        if self.dock:
            self.dock.dispose()
            if not sip.isdeleted(self.dock):
                self.iface.removeDockWidget(self.dock)
                self.dock.deleteLater()
            self.dock = None
        for action in self.actions:
            if not sip.isdeleted(action):
                self.iface.removePluginMenu("&Farois", action)
                action.deleteLater()
        if self.toolbar:
            if not sip.isdeleted(self.toolbar):
                self.iface.mainWindow().removeToolBar(self.toolbar)
                self.toolbar.deleteLater()
            self.toolbar = None
        self.actions = []
