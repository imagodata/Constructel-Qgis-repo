"""QGIS plugin lifecycle: one toolbar entry opening the history dock."""

import os

from .gui.dockwidget import AUTO_CONNECT_RETRY, FaroisAuditDock

ICON_PATH = os.path.join(os.path.dirname(__file__), "icon.svg")


class FaroisAuditRollback:
    def __init__(self, iface):
        self.iface, self.dock, self.toolbar = iface, None, None
        self.api = self.store = None
        # Connexion automatique : une seule tentative, à la première ouverture du
        # panneau (jamais dans initGui : le démarrage de QGIS n'attend pas l'API).
        self._auto_connect_pending = False
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
        from .api.farois_client import FaroisApiClient, api_url
        from .api.session_store import QgisSessionStore

        # Aucun accès réseau ni au gestionnaire d'authentification ici.
        self.store = QgisSessionStore()
        self.api = FaroisApiClient(api_url(), store=self.store)
        self._auto_connect_pending = True
        self.connect_action = QAction("Se connecter à Farois…", self.iface.mainWindow())
        self.disconnect_action = QAction(
            "Se déconnecter de Farois", self.iface.mainWindow()
        )
        self.connect_action.triggered.connect(self.connect_farois)
        self.disconnect_action.triggered.connect(self.disconnect_farois)
        self.action.triggered.connect(self.show_dock)
        self.change_action.triggered.connect(self.undo_change)
        self.transaction_action.triggered.connect(self.undo_transaction)
        self.actions = [
            self.action,
            self.change_action,
            self.transaction_action,
            self.connect_action,
            self.disconnect_action,
        ]
        self.toolbar.addAction(self.action)
        for action in self.actions:
            self.iface.addPluginToMenu("&Farois", action)
        self.sync_actions()

    def show_dock(self):
        if not self._open_dock():
            return
        if self._auto_connect_pending:
            self._auto_connect_pending = False
            # API injoignable (jeton gardé) : nouvel essai à la prochaine ouverture.
            if self.dock.auto_connect_farois() in AUTO_CONNECT_RETRY:
                self._auto_connect_pending = True

    def _open_dock(self):
        """Crée ou réaffiche le panneau ; False pendant le déchargement."""
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt import sip

        if self._unloading:
            return False

        if self.dock is not None and not self.dock.is_usable():
            old, self.dock = self.dock, None
            old.dispose()
            if not sip.isdeleted(old):
                self.iface.removeDockWidget(old)
                old.deleteLater()
        if self.dock is None:
            self.dock = FaroisAuditDock(self.iface, api=self.api, store=self.store)
            self.dock.actionsChanged.connect(self.sync_actions)
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.show()
        self.dock.raise_()
        self.dock.refresh_context()
        return True

    def connect_farois(self):
        # Pas de tentative automatique ici : connect_farois() du panneau reprend
        # d'abord la session mémorisée, puis demande le mot de passe si besoin.
        if self._open_dock() and self.dock.is_usable():
            self.dock.connect_farois()

    def disconnect_farois(self):
        self._auto_connect_pending = False
        if self.dock is not None and self.dock.is_usable():
            self.dock.disconnect_farois()
            return
        if self.api is not None:
            self.api.logout()
        if self.store is not None:
            self.store.clear()

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
        self._auto_connect_pending = False
        if self.api is not None:
            # Oublie sans révoquer : la session mémorisée doit survivre à la
            # fermeture de QGIS, qui ne doit pas non plus attendre l'API.
            self.api.forget()
            self.api = None
        self.store = None

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
