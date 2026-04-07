# -*- coding: utf-8 -*-
"""
Constructel Bridge - Plugin principal.

Responsabilites:
  1. Configurer la connexion PostgreSQL wyre_ftth (role ftth_editor)
  2. Identifier l'utilisateur QGIS et l'enregistrer dans ref.users
  3. Positionner app.current_user sur chaque connexion pour tracer les editions
  4. Intercepter les commits de couche pour tagger l'utilisateur
"""

import base64
import os
from typing import Optional

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsAuthMethodConfig,
    QgsDataSourceUri,
    QgsMessageLog,
    QgsProject,
    QgsSettings,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QInputDialog,
    QMenu,
    QMessageBox,
    QToolButton,
)

from .i18n import SUPPORTED_LANGUAGES, get_language, init_language, set_language, tr
from . import bridge_sketcher

TAG = "Constructel Bridge"
AUTH_CFG_NAME = "constructel_bridge_pw"

# ---------------------------------------------------------------------------
# Credentials — loaded from credentials.json next to this file
# ---------------------------------------------------------------------------
_CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")

def _load_credentials() -> dict:
    """Load connection parameters from credentials.json."""
    import json
    with open(_CREDENTIALS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

_CREDS = _load_credentials()

DEFAULT_HOST = os.getenv("WYRE_DB_HOST", "") or _CREDS["host"]
DEFAULT_PORT = int(os.getenv("WYRE_DB_PORT", str(_CREDS["port"])))
DEFAULT_DBNAME = os.getenv("WYRE_DB_NAME", "") or _CREDS["dbname"]
DEFAULT_USER = _CREDS["user"]
_DEFAULT_PW = base64.b64decode(_CREDS["password"]).decode()
DEFAULT_SRID = _CREDS.get("srid", 31370)
DEFAULT_SSLMODE = _CREDS.get("sslmode", "require")
PG_SERVICE_NAME = _CREDS.get("service_name", "constructel_bridge")
EMAIL_DOMAIN = _CREDS.get("email_domain", "constructel.be")

LANG_LABELS = {"fr": "Francais", "en": "English", "pt": "Portugues"}


def _ensure_auth_manager_ready() -> bool:
    """Ensure the Auth Manager is initialized and master password is set.

    Prompts the user to set a master password if not yet configured.
    Returns True if Auth Manager is ready.
    """
    auth_mgr = QgsApplication.authManager()
    if not auth_mgr.isDisabled():
        if not auth_mgr.masterPasswordIsSet():
            # This will prompt the user to enter/create a master password
            return auth_mgr.setMasterPassword(True)
        return True
    return False


def _store_password_encrypted(password: str) -> bool:
    """Store the password in QGIS Auth Manager (encrypted SQLite DB).

    Returns True on success.
    """
    if not _ensure_auth_manager_ready():
        QgsMessageLog.logMessage(
            "Auth Manager not available, cannot store encrypted password.",
            TAG, level=Qgis.Warning,
        )
        return False
    auth_mgr = QgsApplication.authManager()
    # Look for an existing config with our name
    cfg_id = QgsSettings().value("constructel_bridge/auth_cfg_id", "")
    if cfg_id and cfg_id in auth_mgr.configIds():
        # Update existing config
        config = QgsAuthMethodConfig()
        auth_mgr.loadAuthenticationConfig(cfg_id, config, True)
        config.setConfig("password", password)
        ok = auth_mgr.updateAuthenticationConfig(config)
    else:
        # Create new config
        config = QgsAuthMethodConfig("Basic")
        config.setName(AUTH_CFG_NAME)
        config.setConfig("username", DEFAULT_USER)
        config.setConfig("password", password)
        ok = auth_mgr.storeAuthenticationConfig(config)
        if ok:
            QgsSettings().setValue("constructel_bridge/auth_cfg_id", config.id())
    # Remove legacy plaintext password if present
    QgsSettings().remove("constructel_bridge/password")
    return ok


def _retrieve_password_encrypted() -> str:
    """Retrieve the password from QGIS Auth Manager.

    Returns the password string, or empty string if not found.
    """
    if not _ensure_auth_manager_ready():
        return ""
    auth_mgr = QgsApplication.authManager()
    cfg_id = QgsSettings().value("constructel_bridge/auth_cfg_id", "")
    if not cfg_id or cfg_id not in auth_mgr.configIds():
        # Fallback: check legacy plaintext storage and migrate
        legacy_pw = QgsSettings().value("constructel_bridge/password", "")
        if legacy_pw:
            _store_password_encrypted(legacy_pw)
            return legacy_pw
        return ""
    config = QgsAuthMethodConfig()
    auth_mgr.loadAuthenticationConfig(cfg_id, config, True)
    return config.config("password", "")


def _remove_stored_password():
    """Remove the stored password from Auth Manager and legacy settings."""
    auth_mgr = QgsApplication.authManager()
    cfg_id = QgsSettings().value("constructel_bridge/auth_cfg_id", "")
    if cfg_id and cfg_id in auth_mgr.configIds():
        auth_mgr.removeAuthenticationConfig(cfg_id)
    QgsSettings().remove("constructel_bridge/auth_cfg_id")
    QgsSettings().remove("constructel_bridge/password")


def _get_plugin_version() -> str:
    """Read current plugin version from metadata.txt."""
    meta_path = os.path.join(os.path.dirname(__file__), "metadata.txt")
    with open(meta_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("version="):
                return line.strip().split("=", 1)[1]
    return ""


PLUGIN_VERSION = _get_plugin_version()


class ConstructelBridgePlugin:
    """Plugin QGIS — point d'entree."""

    def __init__(self, iface: QgisInterface):
        self.iface = iface
        self._actions: list[QAction] = []
        self._bridge_user: Optional[str] = None
        self._bridge_user_id: Optional[str] = None
        self._conn = None
        self._connected = False
        self._layer_hooks_installed = False

    # =====================================================================
    # QGIS Plugin lifecycle
    # =====================================================================

    def initGui(self):
        """Appele par QGIS au chargement du plugin."""
        init_language()
        # Activer les macros projet pour que openProject/saveProject/closeProject
        # s'executent automatiquement (evite le bandeau "macros desactivees")
        QgsSettings().setValue("qgis/enableMacros", "Always")

        icon_path = os.path.join(os.path.dirname(__file__), "constructel_bridge_icon.png")
        plugin_icon = QIcon(icon_path)

        # Icones QGIS theme pour chaque action
        theme = QgsApplication.getThemeIcon
        icon_connect = theme("/mActionAddPostgisLayer.svg")
        icon_status = theme("/mIconInfo.svg")
        icon_onboarding = theme("/mActionNewBookmark.svg")
        icon_load = theme("/mActionFileOpen.svg")
        icon_language = theme("/mIconAtlas.svg")

        parent = self.iface.mainWindow()

        # -- Actions ----------------------------------------------------------
        action_connect = QAction(icon_connect, tr("menu.connect"), parent)
        action_connect.triggered.connect(self._on_connect)
        self._actions.append(action_connect)

        action_status = QAction(icon_status, tr("menu.status"), parent)
        action_status.triggered.connect(self._on_status)
        self._actions.append(action_status)

        action_onboarding = QAction(icon_onboarding, tr("menu.onboarding"), parent)
        action_onboarding.triggered.connect(self._on_onboarding)
        self._actions.append(action_onboarding)

        action_load_project = QAction(icon_load, tr("menu.load_project"), parent)
        action_load_project.triggered.connect(self._on_load_project)
        self._actions.append(action_load_project)

        action_language = QAction(icon_language, tr("menu.language"), parent)
        action_language.triggered.connect(self._on_change_language)
        self._actions.append(action_language)

        # -- Menu Database (sous-menu Constructel Bridge) ---------------------
        for action in self._actions:
            self.iface.addPluginToDatabaseMenu("Constructel Bridge", action)

        # Appliquer l'icone Constructel sur le sous-menu parent
        db_menu = self.iface.databaseMenu()
        if db_menu:
            for sub in db_menu.findChildren(QMenu):
                if sub.title() == "Constructel Bridge":
                    sub.setIcon(plugin_icon)
                    break

        # -- Toolbar dropdown -------------------------------------------------
        self._toolbar_menu = QMenu(parent)
        self._toolbar_menu.addAction(action_connect)
        self._toolbar_menu.addSeparator()
        self._toolbar_menu.addAction(action_status)
        self._toolbar_menu.addAction(action_onboarding)
        self._toolbar_menu.addAction(action_load_project)
        self._toolbar_menu.addSeparator()
        self._toolbar_menu.addAction(action_language)

        self._tool_button = QToolButton(parent)
        self._tool_button.setIcon(plugin_icon)
        self._tool_button.setToolTip("Constructel Bridge")
        self._tool_button.setMenu(self._toolbar_menu)
        self._tool_button.setPopupMode(QToolButton.MenuButtonPopup)
        self._tool_button.clicked.connect(self._on_connect)

        self._toolbar_action = self.iface.addToolBarWidget(self._tool_button)

        # Detecter install/mise a jour: mettre a jour la version stockee
        settings = QgsSettings()
        stored_version = settings.value("constructel_bridge/plugin_version", "")
        if stored_version != PLUGIN_VERSION:
            settings.remove("constructel_bridge/onboarding_done")
            settings.setValue("constructel_bridge/plugin_version", PLUGIN_VERSION)
            self._log(
                f"Plugin {'installed' if not stored_version else 'updated'}: "
                f"{stored_version or '(none)'} -> {PLUGIN_VERSION}"
            )

        # Masquer les couches sans geometrie deja presentes dans le projet
        # (couvre le cas ou le projet est deja ouvert au chargement du plugin)
        try:
            self._hide_no_geom_layers()
        except Exception:
            pass

        # Auto-connexion silencieuse au demarrage si un mot de passe est
        # disponible (stocke dans Auth Manager ou mot de passe par defaut).
        # Cela evite a l'utilisateur de devoir cliquer manuellement sur
        # "Connexion base de donnees" a chaque ouverture de projet.
        self._auto_connect()

    def unload(self):
        """Appele par QGIS a la desactivation du plugin."""
        self._unhook_layers()
        if self._conn and not self._conn.closed:
            self._conn.close()
        # Retirer le bouton toolbar dropdown
        if hasattr(self, "_toolbar_action") and self._toolbar_action:
            self.iface.removeToolBarIcon(self._toolbar_action)
        # Retirer les entrees du menu Database
        for action in self._actions:
            self.iface.removePluginDatabaseMenu("Constructel Bridge", action)
        self._actions.clear()

    # =====================================================================
    # Auto-connexion
    # =====================================================================

    def _auto_connect(self):
        """Tente une connexion silencieuse au demarrage du plugin.

        Utilise le mot de passe stocke dans Auth Manager, ou a defaut
        le mot de passe par defaut du fichier credentials.json.
        En cas d'echec, aucune erreur n'est affichee — l'utilisateur
        pourra se connecter manuellement via le menu.
        """
        if self._connected:
            return
        password = _retrieve_password_encrypted() or _DEFAULT_PW
        self._connect(password, silent=True)

    # =====================================================================
    # Language
    # =====================================================================

    def _on_change_language(self):
        """Dialogue de changement de langue."""
        items = [f"{LANG_LABELS[l]} ({l})" for l in SUPPORTED_LANGUAGES]
        current_idx = list(SUPPORTED_LANGUAGES).index(get_language())
        choice, ok = QInputDialog.getItem(
            self.iface.mainWindow(),
            tr("lang.title"),
            tr("lang.prompt"),
            items,
            current_idx,
            False,
        )
        if ok and choice:
            lang_code = choice.split("(")[-1].rstrip(")")
            set_language(lang_code)
            # Refresh menu labels
            self._refresh_action_labels()
            # Appliquer les traductions sur toutes les couches
            bridge_sketcher.apply_all_translations(lang_code)
            self.iface.messageBar().pushSuccess(
                "Constructel Bridge",
                tr("lang.applied", lang=LANG_LABELS.get(lang_code, lang_code)),
            )

    def _refresh_action_labels(self):
        """Met a jour les labels des actions apres changement de langue."""
        keys = [
            "menu.connect", "menu.status", "menu.onboarding",
            "menu.load_project", "menu.language",
        ]
        for action, key in zip(self._actions, keys):
            action.setText(tr(key))

    # =====================================================================
    # Connexion
    # =====================================================================

    def _on_connect(self):
        """Action manuelle: dialogue de connexion."""
        from .bridge_dialog import ConstructelConnectDialog

        dlg = ConstructelConnectDialog(
            self.iface.mainWindow(),
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            dbname=DEFAULT_DBNAME,
            default_password=_DEFAULT_PW,
        )
        if dlg.exec_() == QDialog.Accepted:
            password = dlg.password() or _DEFAULT_PW
            if dlg.save_password():
                _store_password_encrypted(password)
            self._connect(password)

    def _connect(self, password: str, silent: bool = False):
        """Etablit la connexion et initialise l'utilisateur.

        Returns True on success, False on failure.
        When *silent* is True, no error dialog is shown (used by auto-connect).
        """
        self._password = password
        qgis_user = self._get_qgis_username()

        try:
            import psycopg2

            app_name = f"constructel_bridge:{qgis_user}"
            self._conn = psycopg2.connect(
                host=DEFAULT_HOST,
                port=DEFAULT_PORT,
                dbname=DEFAULT_DBNAME,
                user=DEFAULT_USER,
                password=password,
                application_name=app_name,
                options="-c search_path=infra",
                sslmode=DEFAULT_SSLMODE,
            )
            self._conn.autocommit = True
        except Exception as exc:
            self._log(
                f"Connection failed to {DEFAULT_HOST}:{DEFAULT_PORT}/{DEFAULT_DBNAME}: {exc}",
                Qgis.Critical,
            )
            if not silent:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Constructel Bridge",
                    tr("conn.failed", error=f"{DEFAULT_HOST}:{DEFAULT_PORT} — {exc}"),
                )
            return False

        self._connected = True
        self._log(tr("conn.established"))

        try:
            is_new_user = self._register_bridge_user()
        except Exception as exc:
            self._log(f"User registration failed: {exc}", Qgis.Warning)
            is_new_user = False

        try:
            self._setup_qgis_pg_connection(password, use_authcfg=True)
        except Exception as exc:
            self._log(f"QGIS PG config failed: {exc}", Qgis.Warning)

        try:
            self._check_layer_datasources()
        except Exception as exc:
            self._log(f"Layer datasource check failed: {exc}", Qgis.Warning)

        try:
            self._hook_layers()
        except Exception as exc:
            self._log(f"Hook install failed: {exc}", Qgis.Warning)

        # Masquer les couches sans geometrie (listes, ref)
        try:
            self._hide_no_geom_layers()
        except Exception as exc:
            self._log(f"Hide no-geom failed: {exc}", Qgis.Warning)

        # Appliquer les traductions i18n sur les couches
        try:
            bridge_sketcher.apply_all_translations()
        except Exception as exc:
            self._log(f"i18n apply failed: {exc}", Qgis.Warning)

        self.iface.messageBar().pushSuccess(
            "Constructel Bridge",
            tr("conn.connected_as", user=self._bridge_user),
        )

        try:
            onboarding_done = QgsSettings().value("constructel_bridge/onboarding_done", False)
            if not onboarding_done or is_new_user:
                self._run_onboarding(is_new_user)
        except Exception as exc:
            self._log(f"Onboarding failed: {exc}", Qgis.Warning)

        return True

    # =====================================================================
    # Identification et enregistrement utilisateur
    # =====================================================================

    def _get_qgis_username(self) -> str:
        """Recupere le nom d'utilisateur depuis les settings QGIS ou l'OS."""
        settings = QgsSettings()

        explicit = settings.value("constructel_bridge/username", "")
        if explicit:
            return explicit

        try:
            profile = QgsApplication.instance().userProfileManager().userProfile()
            if profile and profile.name() and profile.name() != "default":
                return profile.name()
        except Exception:
            pass

        import getpass
        return getpass.getuser()

    def _register_bridge_user(self) -> bool:
        """Enregistre l'utilisateur QGIS dans ref.users si absent."""
        username = self._get_qgis_username()
        self._bridge_user = username
        is_new = False

        cur = self._conn.cursor()
        try:
            cur.execute(
                "SELECT id, username FROM ref.users WHERE username = %s AND active = TRUE",
                (username,),
            )
            row = cur.fetchone()

            if row:
                self._bridge_user_id = str(row[0])
                self._log(tr("user.existing", username=username, user_id=self._bridge_user_id))
            else:
                cur.execute(
                    """
                    INSERT INTO ref.users (username, email, last_name, role)
                    VALUES (%s, %s, %s, 'OPERATOR')
                    ON CONFLICT (username) DO UPDATE
                        SET last_login = NOW(), active = TRUE
                    RETURNING id
                    """,
                    (username, f"{username}@constructel.be", username),
                )
                self._bridge_user_id = str(cur.fetchone()[0])
                self._log(tr("user.created", username=username, user_id=self._bridge_user_id))
                is_new = True

            cur.execute(
                "UPDATE ref.users SET last_login = NOW() WHERE id = %s::uuid",
                (self._bridge_user_id,),
            )
            self._set_app_user(username)

        except Exception as exc:
            self._log(tr("user.error", error=exc), Qgis.Warning)
        finally:
            cur.close()

        return is_new

    def _set_app_user(self, username: str):
        """Positionne app.current_user dans la session PostgreSQL."""
        if not self._conn or self._conn.closed:
            return
        cur = self._conn.cursor()
        try:
            cur.execute("SELECT set_config('app.current_user', %s, false)", (username,))
        except Exception as exc:
            self._log(f"set_config error: {exc}", Qgis.Warning)
        finally:
            cur.close()

    # =====================================================================
    # Configuration connexion QGIS
    # =====================================================================

    def _check_layer_datasources(self):
        """Verifie que les couches PostgreSQL ne pointent pas vers localhost."""
        bad_hosts = ("localhost", "127.0.0.1", "::1")
        project = QgsProject.instance()
        bad_layers = []
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            provider = layer.dataProvider()
            if not provider or provider.name() != "postgres":
                continue
            uri = provider.uri()
            layer_host = uri.host()
            if layer_host in bad_hosts:
                bad_layers.append(layer.name())
        if bad_layers:
            names = ", ".join(bad_layers[:5])
            if len(bad_layers) > 5:
                names += f" (+{len(bad_layers) - 5})"
            self._log(
                f"{len(bad_layers)} layer(s) pointing to localhost: {names}",
                Qgis.Warning,
            )
            self.iface.messageBar().pushWarning(
                "Constructel Bridge",
                tr(
                    "layers.bad_host",
                    count=len(bad_layers),
                    names=names,
                    host=DEFAULT_HOST,
                ),
            )

    def _setup_qgis_pg_connection(self, password: str, use_authcfg: bool = False):
        """Enregistre la connexion PostgreSQL dans les settings QGIS.

        Always writes all values to ensure consistency and fix any
        leftover misconfiguration from previous plugin versions.

        When *use_authcfg* is True, stores credentials in Auth Manager
        and references the authcfg ID instead of storing the password
        in plaintext (equivalent to "Convertir en configuration").
        """
        settings = QgsSettings()
        base = "PostgreSQL/connections/constructel_bridge"

        settings.setValue(f"{base}/host", DEFAULT_HOST)
        settings.setValue(f"{base}/port", str(DEFAULT_PORT))
        settings.setValue(f"{base}/database", DEFAULT_DBNAME)
        settings.setValue(f"{base}/username", DEFAULT_USER)
        settings.setValue(f"{base}/sslmode", "3")
        settings.setValue(f"{base}/estimatedMetadata", True)
        settings.setValue(f"{base}/allowGeometrylessTables", False)
        settings.setValue(f"{base}/geometryColumnsOnly", True)
        settings.setValue(f"{base}/dontResolveType", False)
        settings.setValue(f"{base}/publicOnly", False)
        settings.setValue(f"{base}/projectsInDatabase", True)
        settings.setValue(f"{base}/metadataInDatabase", True)
        settings.setValue(f"{base}/schemas", "infra")
        settings.setValue(f"{base}/schema", "infra")

        if use_authcfg:
            # Store credentials in Auth Manager (encrypted)
            _store_password_encrypted(password)
            auth_cfg_id = settings.value("constructel_bridge/auth_cfg_id", "")
            settings.setValue(f"{base}/authcfg", auth_cfg_id)
            # Clear plaintext credentials from connection
            settings.setValue(f"{base}/password", "")
            settings.setValue(f"{base}/savePassword", False)
            settings.setValue(f"{base}/saveUsername", False)
            self._log("PG connection configured with authcfg (encrypted).")
        else:
            # Plaintext password (initial setup before dialog validation)
            settings.remove(f"{base}/authcfg")
            settings.setValue(f"{base}/password", password)
            settings.setValue(f"{base}/saveUsername", True)
            settings.setValue(f"{base}/savePassword", True)

        self._log(tr("pg.configured"))
        self.iface.browserModel().reload()

    # =====================================================================
    # Hook sur les couches — tagging des commits
    # =====================================================================

    def _hook_layers(self):
        """Installe les hooks beforeCommitChanges sur toutes les couches vectorielles."""
        if self._layer_hooks_installed:
            return

        project = QgsProject.instance()
        for layer in project.mapLayers().values():
            if isinstance(layer, QgsVectorLayer):
                self._hook_single_layer(layer)

        project.layersAdded.connect(self._on_layers_added)
        self._layer_hooks_installed = True
        self._log(tr("hook.all_installed"))

    def _unhook_layers(self):
        if not self._layer_hooks_installed:
            return
        try:
            QgsProject.instance().layersAdded.disconnect(self._on_layers_added)
        except TypeError:
            pass
        self._layer_hooks_installed = False

    def _on_layers_added(self, layers):
        for layer in layers:
            if isinstance(layer, QgsVectorLayer):
                self._hook_single_layer(layer)
                self._hide_layer_if_no_geom(layer)
                bridge_sketcher.apply_to_layer(layer)

    def _hook_single_layer(self, layer: QgsVectorLayer):
        provider = layer.dataProvider()
        if not provider or provider.name() != "postgres":
            return
        try:
            layer.beforeCommitChanges.disconnect(self._on_before_commit)
        except TypeError:
            pass
        layer.beforeCommitChanges.connect(self._on_before_commit)
        self._log(tr("hook.installed", layer=layer.name()), Qgis.Info)

    def _on_before_commit(self):
        layer = self.iface.activeLayer()
        if not layer or not isinstance(layer, QgsVectorLayer):
            return
        if not self._bridge_user:
            return
        provider = layer.dataProvider()
        if not provider or provider.name() != "postgres":
            return

        try:
            provider.executeSql(
                f"SELECT set_config('app.current_user', '{self._bridge_user}', true)"
            )
            provider.executeSql(
                f"SET application_name = 'constructel_bridge:{self._bridge_user}'"
            )
            self._log(tr("hook.commit_tagged", user=self._bridge_user, layer=layer.name()))
        except Exception as exc:
            self._log(tr("hook.exec_error", error=exc), Qgis.Warning)

    # =====================================================================
    # Masquage des couches sans geometrie (listes / ref)
    # =====================================================================
    # Les couches sans geometrie (tables ref, vues docs) sont necessaires
    # dans le projet pour les widgets ValueRelation et les relations,
    # mais ne doivent pas encombrer le Layer Tree.
    #
    # Strategie: retirer le noeud du Layer Tree (removeChildNode) tout en
    # gardant la couche dans le projet (addMapLayer(layer, False) ne
    # re-cree pas de noeud). La couche reste accessible via
    # QgsProject.mapLayers() et les widgets continuent de fonctionner.

    @staticmethod
    def _is_no_geom(layer):
        """True si la couche vectorielle n'a pas de geometrie."""
        if not isinstance(layer, QgsVectorLayer):
            return False
        return (
            not layer.isSpatial()
            or layer.wkbType() == QgsWkbTypes.NoGeometry
            or layer.geometryType() == QgsWkbTypes.NullGeometry
        )

    def _hide_no_geom_layers(self):
        """Retire du Layer Tree les couches sans geometrie et les groupes vides.

        Les couches restent enregistrees dans QgsProject.mapLayers() donc
        les widgets ValueRelation continuent de fonctionner.
        """
        from .i18n.layer_translations import GROUP_NAMES
        root = QgsProject.instance().layerTreeRoot()
        removed = 0
        for layer in QgsProject.instance().mapLayers().values():
            if not self._is_no_geom(layer):
                continue
            node = root.findLayer(layer.id())
            if node:
                node.parent().removeChildNode(node)
                removed += 1

        # Supprimer les groupes Listes/Autres devenus vides
        tr_dict = GROUP_NAMES.get("Listes", {})
        known_names = set(tr_dict.values()) | {"Listes", "Autres", "Other", "Outros"}
        for child in list(root.children()):
            if hasattr(child, "name") and child.name() in known_names:
                if not child.children():
                    root.removeChildNode(child)

        if removed:
            self._log(f"{removed} couche(s) sans geometrie retiree(s) du Layer Tree")

    def _hide_layer_if_no_geom(self, layer):
        """Retire une couche individuelle du Layer Tree si sans geometrie."""
        if not self._is_no_geom(layer):
            return
        root = QgsProject.instance().layerTreeRoot()
        node = root.findLayer(layer.id())
        if node:
            node.parent().removeChildNode(node)
            self._log(f"couche '{layer.name()}' retiree du Layer Tree (sans geometrie)")

    # =====================================================================
    # Charger un projet depuis PostgreSQL
    # =====================================================================

    def _on_load_project(self):
        """Liste les projets QGIS stockes en base et charge celui choisi."""
        if not self._connected:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Constructel Bridge",
                tr("conn.connect_first"),
            )
            return

        # Lister les projets disponibles
        projects = self._list_db_projects()
        if projects is None:
            return  # erreur deja affichee
        if not projects:
            QMessageBox.information(
                self.iface.mainWindow(),
                tr("project.title"),
                tr("project.none_found"),
            )
            return

        # Dialogue de selection
        items = [f"{p['name']}  ({p['schema']})" for p in projects]
        choice, ok = QInputDialog.getItem(
            self.iface.mainWindow(),
            tr("project.title"),
            tr("project.select"),
            items,
            0,
            False,
        )
        if not ok or not choice:
            return

        # Retrouver le projet selectionne
        idx = items.index(choice)
        selected = projects[idx]

        # Construire l'URI PostgreSQL du projet
        # Utilise authcfg si disponible, sinon password en clair
        from urllib.parse import quote
        auth_cfg_id = QgsSettings().value("constructel_bridge/auth_cfg_id", "")
        if auth_cfg_id:
            uri = (
                f"postgresql://@{DEFAULT_HOST}:{DEFAULT_PORT}"
                f"/?dbname={quote(DEFAULT_DBNAME, safe='')}"
                f"&sslmode={DEFAULT_SSLMODE}"
                f"&schema={selected['schema']}"
                f"&project={quote(selected['name'], safe='')}"
                f"&authcfg={auth_cfg_id}"
            )
        else:
            uri = (
                f"postgresql://{quote(DEFAULT_USER, safe='')}:{quote(self._password, safe='')}"
                f"@{DEFAULT_HOST}:{DEFAULT_PORT}"
                f"/?dbname={quote(DEFAULT_DBNAME, safe='')}"
                f"&sslmode={DEFAULT_SSLMODE}"
                f"&schema={selected['schema']}"
                f"&project={quote(selected['name'], safe='')}"
            )

        proj_name = selected["name"]
        project = QgsProject.instance()
        if project.read(uri):
            self._log(tr("project.loaded", name=proj_name))
            self.iface.messageBar().pushSuccess(
                "Constructel Bridge",
                tr("project.loaded", name=proj_name),
            )
            # Re-hook les couches du projet charge + masquage + i18n
            self._layer_hooks_installed = False
            self._hook_layers()
            self._hide_no_geom_layers()
            bridge_sketcher.apply_all_translations()
        else:
            raw_error = project.error()
            if hasattr(raw_error, "summary"):
                error = raw_error.summary()
            else:
                error = str(raw_error) if raw_error else "Unknown error"
            self._log(tr("project.load_error", name=proj_name, error=error), Qgis.Critical)
            QMessageBox.critical(
                self.iface.mainWindow(),
                tr("project.title"),
                tr("project.load_error", name=proj_name, error=error),
            )

    _PROJECT_SCHEMAS = ("infra",)

    def _list_db_projects(self) -> list[dict] | None:
        """Interroge PostgreSQL pour lister les projets QGIS stockes.

        Cherche la table ``qgis_projects`` dans les schemas public et infra.
        """
        cur = self._conn.cursor()
        try:
            results: list[dict] = []
            for schema in self._PROJECT_SCHEMAS:
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = 'qgis_projects'
                    )
                    """,
                    (schema,),
                )
                if not cur.fetchone()[0]:
                    continue
                cur.execute(
                    f"""
                    SELECT name,
                           metadata->>'description' AS description,
                           metadata->>'last_modified_time' AS updated,
                           %s AS schema
                    FROM {schema}.qgis_projects
                    ORDER BY name
                    """,
                    (schema,),
                )
                columns = [desc[0] for desc in cur.description]
                results.extend(dict(zip(columns, row)) for row in cur.fetchall())

            if not results:
                QMessageBox.information(
                    self.iface.mainWindow(),
                    tr("project.title"),
                    tr("project.no_table"),
                )
                return None

            return results

        except Exception as exc:
            self._log(f"list_db_projects error: {exc}", Qgis.Warning)
            QMessageBox.warning(
                self.iface.mainWindow(),
                tr("project.title"),
                tr("project.list_error", error=exc),
            )
            return None
        finally:
            cur.close()

    # =====================================================================
    # Onboarding
    # =====================================================================

    def _run_onboarding(self, is_new_user: bool):
        from .bridge_onboarding import OnboardingWizard

        wizard = OnboardingWizard(
            parent=self.iface.mainWindow(),
            username=self._bridge_user or "",
            user_id=self._bridge_user_id or "",
            is_new_user=is_new_user,
            db_conn=self._conn,
            email_domain=EMAIL_DOMAIN,
        )
        wizard.exec_()

    def _on_onboarding(self):
        if not self._connected:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Constructel Bridge",
                tr("conn.connect_first"),
            )
            return
        self._run_onboarding(is_new_user=False)

    # =====================================================================
    # Status
    # =====================================================================

    def _on_status(self):
        if not self._connected:
            msg = tr("status.not_connected")
        else:
            msg = tr(
                "status.connected_to",
                host=DEFAULT_HOST,
                port=DEFAULT_PORT,
                dbname=DEFAULT_DBNAME,
                user=DEFAULT_USER,
                bridge_user=self._bridge_user,
                bridge_user_id=self._bridge_user_id,
                hooks=self._layer_hooks_installed,
            )
        QMessageBox.information(self.iface.mainWindow(), tr("status.title"), msg)

    # =====================================================================
    # Logging
    # =====================================================================

    def _log(self, message: str, level=Qgis.Info):
        QgsMessageLog.logMessage(message, TAG, level=level)
