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
    QgsCredentials,
    QgsDataProvider,
    QgsDataSourceUri,
    QgsMessageLog,
    QgsProject,
    QgsProjectBadLayerHandler,
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


# ---------------------------------------------------------------------------
# Intercepteur de credentials — evite le dialogue de saisie pour notre base
# ---------------------------------------------------------------------------

class _BridgeCredentials(QgsCredentials):
    """Fournit automatiquement les credentials pour la base WYRE FTTH.

    Quand un projet contient des couches avec un authcfg d'un autre
    utilisateur, QGIS affiche un dialogue de saisie pour chaque couche.
    Ce handler intercepte ces demandes et fournit le mot de passe
    automatiquement si le realm correspond a notre serveur PG.
    Pour les autres realms, il delegue au handler original (dialogue).
    """

    def __init__(self, fallback):
        self._fallback = fallback
        self._username = DEFAULT_USER
        self._password = _DEFAULT_PW
        super().__init__()  # appelle setInstance(self) en interne

    def update_password(self, password: str):
        self._password = password

    def request(self, realm, username, password, message=""):
        QgsMessageLog.logMessage(
            f"Credentials request intercepted — realm={realm!r}",
            TAG, level=Qgis.Info,
        )
        if DEFAULT_HOST in realm:
            QgsMessageLog.logMessage(
                "Auto-providing credentials for WYRE FTTH",
                TAG, level=Qgis.Info,
            )
            # Also cache via put() so subsequent get() calls skip request()
            self.put(realm, self._username, self._password)
            return True, self._username, self._password
        # Realm inconnu → deleguer au handler QGIS par defaut (dialogue)
        if self._fallback:
            return self._fallback.request(realm, username, password, message)
        return False, username, password

    def requestMasterPassword(self, password, stored=False):
        if self._fallback:
            return self._fallback.requestMasterPassword(password, stored)
        return False, password


class _BridgeBadLayerHandler(QgsProjectBadLayerHandler):
    """Supprime le dialogue 'Traiter les couches inutilisables'.

    Les couches cassees (authcfg inconnu) seront reparees dans
    _on_project_read via _fix_layer_credentials.
    """

    def handleBadLayers(self, layers):
        pass  # Silence — on repare apres le chargement


def _precache_pg_credentials():
    """Pre-cache PG credentials pour eviter le dialogue de saisie.

    Insere dans le cache de QgsCredentials les credentials pour les
    variantes de realm les plus courantes.  Quand QGIS appelle get()
    pour une de ces realms, il trouve le cache et n'affiche pas de
    dialogue.  Le cache est consomme (take) par get(), donc on le
    re-remplit a chaque chargement de projet.
    """
    creds = QgsCredentials.instance()
    for realm in (
        f"dbname='{DEFAULT_DBNAME}' host={DEFAULT_HOST} port={DEFAULT_PORT}",
        f"dbname='{DEFAULT_DBNAME}' host={DEFAULT_HOST} port={DEFAULT_PORT} sslmode={DEFAULT_SSLMODE}",
        f"dbname='{DEFAULT_DBNAME}' host={DEFAULT_HOST}",
        DEFAULT_HOST,
    ):
        creds.put(realm, DEFAULT_USER, _DEFAULT_PW)


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

        # Appliquer l'icone Constructel sur l'entree du sous-menu
        # dans le menu Database parent (c'est le menuAction() qui porte
        # l'icone visible, pas le QMenu lui-meme).
        db_menu = self.iface.databaseMenu()
        if db_menu:
            for action in db_menu.actions():
                if action.menu() and action.menu().title() == "Constructel Bridge":
                    action.setIcon(plugin_icon)
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

        # Enregistrer les connexions WMTS / XYZ / WFS externes
        try:
            self._setup_external_services()
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"External services setup failed: {exc}", TAG, level=Qgis.Warning,
            )

        # Un seul reload de l'explorateur apres toutes les modifications settings
        try:
            self.iface.browserModel().reload()
        except Exception:
            pass

        # Intercepter les demandes de credentials QGIS pour fournir
        # automatiquement le mot de passe de notre base PG.
        # Cela evite le dialogue "Saisir les identifiants" quand un
        # projet contient des authcfg d'un autre utilisateur.
        self._orig_credentials = QgsCredentials.instance()
        self._bridge_credentials = _BridgeCredentials(self._orig_credentials)

        # Pre-cacher les credentials PG pour que QgsCredentials.get()
        # les trouve dans le cache AVANT d'appeler request().
        # Cela couvre le cas ou un projet avec authcfg inconnu est charge
        # au demarrage (projets recents, browser, etc.).
        _precache_pg_credentials()

        # Supprimer le dialogue "Traiter les couches inutilisables" —
        # les couches avec un authcfg inconnu seront reparees apres
        # le chargement dans _on_project_read.
        self._bad_layer_handler = _BridgeBadLayerHandler()
        QgsProject.instance().setBadLayerHandler(self._bad_layer_handler)

        # Ecouter le signal readProject pour reagir quand un projet est
        # charge par n'importe quel moyen (explorateur PG, fichier, etc.)
        QgsProject.instance().readProject.connect(self._on_project_read)

        # Nettoyer les authcfg des datasources AVANT la sauvegarde du projet
        # pour que le projet ecrit soit portable (pas d'authcfg user-specific).
        QgsProject.instance().writeProject.connect(self._on_write_project)

        # Auto-connexion silencieuse au demarrage: etablit uniquement la
        # connexion DB et l'enregistrement utilisateur, sans toucher au
        # projet (pas de fix credentials, hooks, etc.) pour eviter de
        # rendre le projet vide "dirty" et le dialogue "Enregistrer".
        self._auto_connect()

    def unload(self):
        """Appele par QGIS a la desactivation du plugin."""
        try:
            QgsProject.instance().readProject.disconnect(self._on_project_read)
        except TypeError:
            pass
        try:
            QgsProject.instance().writeProject.disconnect(self._on_write_project)
        except TypeError:
            pass
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
    # Reaction au chargement d'un projet (explorateur PG, fichier, etc.)
    # =====================================================================

    def _on_project_read(self, doc):
        """Appele par QgsProject.readProject apres tout chargement de projet.

        Corrige les credentials, re-hook les couches, masque les no-geom
        et applique les traductions — quel que soit le moyen de chargement
        (explorateur PostgreSQL, fichier .qgs/.qgz, menu recent, etc.).
        """
        # Toujours corriger les credentials (utilise le mot de passe par
        # defaut si pas encore connecte — suffit pour reparer les authcfg).
        try:
            self._fix_layer_credentials()
        except Exception as exc:
            self._log(f"Fix layer credentials failed: {exc}", Qgis.Warning)

        if not self._connected:
            return

        self._layer_hooks_installed = False
        try:
            self._hook_layers()
        except Exception as exc:
            self._log(f"Hook install failed: {exc}", Qgis.Warning)

        try:
            self._hide_no_geom_layers()
        except Exception as exc:
            self._log(f"Hide no-geom failed: {exc}", Qgis.Warning)

        try:
            bridge_sketcher.apply_all_translations()
        except Exception as exc:
            self._log(f"i18n apply failed: {exc}", Qgis.Warning)

    # =====================================================================
    # Nettoyage avant sauvegarde du projet
    # =====================================================================

    def _on_write_project(self, doc):
        """Appele par QgsProject.writeProject pendant la sauvegarde.

        Nettoie les datasources PG dans le DOM XML pour retirer les authcfg
        user-specific et les remplacer par des credentials en clair.
        Cela garantit qu'un projet sauvegarde par User A pourra etre
        ouvert par User B sans dialogue de credentials.
        """
        try:
            self._strip_authcfg_from_dom(doc)
        except Exception as exc:
            self._log(f"Strip authcfg from DOM failed: {exc}", Qgis.Warning)

    def _strip_authcfg_from_dom(self, doc):
        """Parcourt le DOM du projet et retire les authcfg des datasources PG."""
        import re
        password = getattr(self, "_password", None) or _DEFAULT_PW
        layers = doc.elementsByTagName("maplayer")
        cleaned = 0
        for i in range(layers.count()):
            node = layers.at(i)
            elem = node.toElement()
            provider_node = elem.firstChildElement("provider")
            if provider_node.isNull() or provider_node.text() != "postgres":
                continue
            ds_node = elem.firstChildElement("datasource")
            if ds_node.isNull():
                continue
            ds = ds_node.text()
            if "authcfg=" not in ds:
                continue
            # Retirer authcfg=xxx et injecter user/password en clair
            ds = re.sub(r"\bauthcfg=\w+", "", ds)
            # Ajouter user/password s'ils ne sont pas deja presents
            if f"user='{DEFAULT_USER}'" not in ds:
                ds += f" user='{DEFAULT_USER}'"
            if "password=" not in ds:
                ds += f" password='{password}'"
            ds = re.sub(r"\s{2,}", " ", ds).strip()
            # Remplacer le contenu du noeud
            while ds_node.hasChildNodes():
                ds_node.removeChild(ds_node.firstChild())
            ds_node.appendChild(doc.createTextNode(ds))
            cleaned += 1
        if cleaned:
            self._log(f"{cleaned} datasource(s) PG nettoyee(s) avant sauvegarde (authcfg retire)")

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
        # Mettre a jour le handler de credentials avec le mot de passe courant
        if hasattr(self, "_bridge_credentials"):
            self._bridge_credentials.update_password(password)
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
            # Even on connection failure, configure the QGIS PG browser
            # entry with password so that the explorer can still open
            # projects without prompting for credentials.
            try:
                self._setup_qgis_pg_connection(password, use_authcfg=False)
            except Exception:
                pass
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

        self.iface.browserModel().reload()

        # En mode silent (auto-connect au demarrage), ne pas toucher au
        # projet pour eviter de le rendre "dirty" et declencher le
        # dialogue "Enregistrer le projet".
        if not silent:
            self._apply_project_hooks()

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

    def _apply_project_hooks(self):
        """Applique les hooks, corrections et traductions sur le projet courant."""
        try:
            self._fix_layer_credentials()
        except Exception as exc:
            self._log(f"Fix layer credentials failed: {exc}", Qgis.Warning)

        try:
            self._check_layer_datasources()
        except Exception as exc:
            self._log(f"Layer datasource check failed: {exc}", Qgis.Warning)

        try:
            self._hook_layers()
        except Exception as exc:
            self._log(f"Hook install failed: {exc}", Qgis.Warning)

        try:
            self._hide_no_geom_layers()
        except Exception as exc:
            self._log(f"Hide no-geom failed: {exc}", Qgis.Warning)

        try:
            bridge_sketcher.apply_all_translations()
        except Exception as exc:
            self._log(f"i18n apply failed: {exc}", Qgis.Warning)

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

    def _fix_layer_credentials(self):
        """Reecrit les datasources PG pour utiliser les credentials courants.

        Quand un projet est charge depuis la base, les URIs des couches
        contiennent l'authcfg de l'utilisateur qui a sauvegarde le projet.
        Cet authcfg n'existe pas dans l'Auth Manager d'un autre utilisateur,
        ce qui rend toutes les couches invalides.

        Cette methode remplace l'authentification de chaque couche PG
        par des credentials en clair (user/password) SANS authcfg.
        Cela garantit que tout projet sauvegarde sera portable — un autre
        utilisateur pourra l'ouvrir sans rencontrer un authcfg inconnu.
        Gere aussi les couches invalides (provider=None) en utilisant
        layer.providerType() et layer.source() directement.
        """
        password = getattr(self, "_password", None) or _DEFAULT_PW
        project = QgsProject.instance()
        fixed = 0
        still_bad = 0
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            # providerType() fonctionne meme si le provider est None
            if layer.providerType() != "postgres":
                continue

            # Recuperer l'URI — depuis le provider si valide, sinon source()
            provider = layer.dataProvider()
            if provider:
                uri = QgsDataSourceUri(provider.uri().uri())
            else:
                uri = QgsDataSourceUri(layer.source())

            # Toujours utiliser des credentials en clair pour la portabilite
            old_authcfg = uri.authConfigId()
            needs_fix = bool(old_authcfg) or uri.username() != DEFAULT_USER
            if needs_fix:
                uri.setAuthConfigId("")
                uri.setUsername(DEFAULT_USER)
                uri.setPassword(password)

            if needs_fix or not layer.isValid():
                options = QgsDataProvider.ProviderOptions()
                layer.setDataSource(
                    uri.uri(False),
                    layer.name(),
                    "postgres",
                    options,
                )
                if layer.isValid():
                    fixed += 1
                else:
                    still_bad += 1

        if fixed:
            self._log(f"{fixed} couche(s) PG: credentials corrigees")
        if still_bad:
            self._log(f"{still_bad} couche(s) PG toujours invalides apres correction", Qgis.Warning)

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
            store_ok = _store_password_encrypted(password)
            auth_cfg_id = settings.value("constructel_bridge/auth_cfg_id", "")
            if store_ok and auth_cfg_id:
                settings.setValue(f"{base}/authcfg", auth_cfg_id)
                self._log("PG connection configured with authcfg (encrypted).")
            else:
                # Auth Manager not ready — clear any stale authcfg
                settings.remove(f"{base}/authcfg")
                self._log(
                    "Auth Manager unavailable, PG connection uses saved password.",
                    Qgis.Warning,
                )
        else:
            settings.remove(f"{base}/authcfg")

        # Always store password in connection so that the browser /
        # explorer can open projects even when authcfg resolution fails
        # (e.g. master-password not yet entered, stale config id).
        settings.setValue(f"{base}/password", password)
        settings.setValue(f"{base}/saveUsername", True)
        settings.setValue(f"{base}/savePassword", True)

        self._log(tr("pg.configured"))

    # =====================================================================
    # Connexions externes — WMTS / XYZ / WFS
    # =====================================================================

    # Definitions des services externes a enregistrer dans QGIS.
    # Chaque entree: (settings_base, nom, dict de cles/valeurs).
    _EXTERNAL_SERVICES = [
        # --- XYZ Tiles ---
        (
            "qgis/connections-xyz",
            "Google Streetview Coverage",
            {
                "url": (
                    "https://mts2.google.com/mapslt?"
                    "lyrs%3Dsvv%26x%3D{x}%26y%3D{y}%26z%3D{z}"
                    "%26w%3D256%26h%3D256%26hl%3Den&style%3D40,18"
                ),
                "zmin": 0,
                "zmax": 21,
                "tilePixelRatio": 0,
            },
        ),
        # --- WMTS (enregistre comme connexion WMS dans QGIS) ---
        (
            "qgis/connections-wms",
            "WMTS UrbIS Bruxelles",
            {
                "url": "https://geoservices-urbis.irisnet.be/geowebcache/service/wmts",
                "ignoreGetMapURI": False,
                "ignoreGetFeatureInfoURI": False,
                "ignoreAxisOrientation": False,
                "invertAxisOrientation": False,
                "smoothPixmapTransform": False,
                "dpiMode": 7,
            },
        ),
        (
            "qgis/connections-wms",
            "WMTS NGI CartoWeb Belgique",
            {
                "url": "https://cartoweb.wmts.ngi.be/1.0.0/WMTSCapabilities.xml",
                "ignoreGetMapURI": False,
                "ignoreGetFeatureInfoURI": False,
                "ignoreAxisOrientation": False,
                "invertAxisOrientation": False,
                "smoothPixmapTransform": False,
                "dpiMode": 7,
            },
        ),
        # --- WFS ---
        (
            "qgis/connections-wfs",
            "WFS Cadastre UrbIS Bruxelles",
            {
                "url": "https://geoservices-vector.irisnet.be/geoserver/urbisvector/wfs",
                "version": "2.0.0",
                "maxnumfeatures": "",
                "pagesize": "",
                "pagingenabled": True,
                "ignoreAxisOrientation": False,
                "invertAxisOrientation": False,
                "preferCoordinatesForWfsT11": False,
            },
        ),
    ]

    def _setup_external_services(self):
        """Enregistre les connexions WMTS / XYZ / WFS dans les settings QGIS.

        N'ecrase pas une connexion existante si l'URL est identique
        (l'utilisateur a peut-etre modifie d'autres parametres).
        """
        settings = QgsSettings()
        added = []
        for base, name, params in self._EXTERNAL_SERVICES:
            key_prefix = f"{base}/{name}"
            existing_url = settings.value(f"{key_prefix}/url", "")
            if existing_url == params.get("url", ""):
                self._log(f"Service '{name}' already configured — skipped")
                continue
            for k, v in params.items():
                settings.setValue(f"{key_prefix}/{k}", v)
            added.append(name)
            self._log(f"Service '{name}' registered ({key_prefix})")
        if added:
            settings.sync()
            self.iface.messageBar().pushSuccess(
                "Constructel Bridge",
                tr("services.registered", count=len(added)),
            )
        else:
            self._log("All external services already configured")

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
        """True si la couche vectorielle n'a pas de geometrie.

        Utilise l'URI (wkbType declare) en priorite pour eviter les faux
        positifs quand le provider PG n'a pas encore resolu la geometrie
        (race condition dans le signal layersAdded).
        """
        if not isinstance(layer, QgsVectorLayer):
            return False
        # Verifier d'abord l'URI : si un type geometrie est declare,
        # la couche est spatiale meme si isSpatial() est temporairement False
        uri = QgsDataSourceUri(layer.source())
        if uri.geometryColumn():
            return False
        return (
            layer.wkbType() == QgsWkbTypes.NoGeometry
            or layer.geometryType() == QgsWkbTypes.NullGeometry
            or not layer.isSpatial()
        )

    _REF_GROUP_NAME = "Référence"

    def _get_or_create_ref_group(self):
        """Retourne (ou cree) le groupe de reference pour couches masquees.

        Compatible avec le groupe cree par init_project.py.
        Detecte aussi les anciens groupes Listes/Autres et les fusionne.
        """
        from .i18n.layer_translations import GROUP_NAMES
        root = QgsProject.instance().layerTreeRoot()

        # 1. Chercher le groupe officiel
        ref_group = root.findGroup(self._REF_GROUP_NAME)

        # 2. Chercher les anciens groupes Listes/Autres
        tr_dict = GROUP_NAMES.get("Listes", {})
        legacy_names = set(tr_dict.values()) | {
            "Listes", "Autres", "Other", "Outros",
            "_ Référence (ne pas modifier)",
        }
        legacy_groups = []
        for child in root.children():
            if hasattr(child, "name") and child.name() in legacy_names:
                legacy_groups.append(child)

        # 3. Creer le groupe officiel si absent
        if not ref_group:
            ref_group = root.addGroup(self._REF_GROUP_NAME)

        # 4. Migrer les couches des anciens groupes vers le groupe officiel
        for old_group in legacy_groups:
            for child_node in list(old_group.children()):
                clone = child_node.clone()
                ref_group.addChildNode(clone)
                old_group.removeChildNode(child_node)
            root.removeChildNode(old_group)

        return ref_group

    def _hide_no_geom_layers(self):
        """Deplace les couches sans geometrie dans le groupe de reference.

        Les couches gardent leur layer ID original — les ValueRelation,
        relations et widgets continuent de fonctionner.  Le groupe est
        replie et decoche pour ne pas encombrer le panneau Couches.
        """
        root = QgsProject.instance().layerTreeRoot()
        group = self._get_or_create_ref_group()
        moved = 0
        for layer in QgsProject.instance().mapLayers().values():
            if not self._is_no_geom(layer):
                continue
            node = root.findLayer(layer.id())
            if node and node.parent() != group:
                clone = node.clone()
                group.addChildNode(clone)
                node.parent().removeChildNode(node)
                moved += 1
        group.setExpanded(False)
        group.setItemVisibilityChecked(False)
        if moved:
            self._log(f"{moved} couche(s) sans geometrie deplacee(s) dans '{group.name()}'")

    def _hide_layer_if_no_geom(self, layer):
        """Deplace une couche individuelle dans le groupe de reference si sans geometrie."""
        if not self._is_no_geom(layer):
            return
        root = QgsProject.instance().layerTreeRoot()
        group = self._get_or_create_ref_group()
        node = root.findLayer(layer.id())
        if node and node.parent() != group:
            clone = node.clone()
            group.addChildNode(clone)
            node.parent().removeChildNode(node)
            self._log(f"couche '{layer.name()}' deplacee dans '{group.name()}'")


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

        proj_name = selected["name"]
        schema = selected["schema"]
        project = QgsProject.instance()

        # Charger le projet en passant par _read_and_clean_project()
        # qui lit le XML depuis PG, nettoie les authcfg, et charge
        # depuis un fichier temporaire.  Cela evite le dialogue
        # "Saisir les identifiants" quand le projet contient des
        # authcfg d'un autre utilisateur.
        if self._read_and_clean_project(project, schema, proj_name):
            self._log(tr("project.loaded", name=proj_name))
            self.iface.messageBar().pushSuccess(
                "Constructel Bridge",
                tr("project.loaded", name=proj_name),
            )
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

    def _read_and_clean_project(self, project, schema: str, name: str) -> bool:
        """Lit le XML du projet depuis PG, nettoie les authcfg, et charge.

        Au lieu de ``project.read(postgresql://…)`` qui laisse QGIS
        resoudre les authcfg (et afficher un dialogue pour chaque
        authcfg inconnu), on:
          1. Lit le XML brut depuis ``{schema}.qgis_projects``
          2. Retire tous les ``authcfg=xxx`` et injecte user/password
          3. Ecrit dans un fichier temporaire
          4. Charge avec ``project.read(temp_path)``

        Retourne True si le chargement a reussi.
        """
        import re
        import tempfile

        password = getattr(self, "_password", None) or _DEFAULT_PW
        cur = self._conn.cursor()
        try:
            cur.execute(
                f"SELECT content FROM {schema}.qgis_projects WHERE name = %s",
                (name,),
            )
            row = cur.fetchone()
        except Exception as exc:
            self._log(f"Failed to read project XML from PG: {exc}", Qgis.Warning)
            return False
        if not row:
            self._log(f"Project '{name}' not found in {schema}.qgis_projects", Qgis.Warning)
            return False

        raw = row[0]
        if isinstance(raw, memoryview):
            raw = bytes(raw)
        elif isinstance(raw, str):
            # Deja du texte
            xml = raw
            raw = None

        if raw is not None:
            import io
            import zipfile
            # QGIS stocke le projet comme .qgz (archive ZIP) dans PG
            if raw[:2] == b"PK":
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    # Le .qgs est le premier (et souvent unique) fichier
                    qgs_names = [n for n in zf.namelist() if n.endswith(".qgs")]
                    entry = qgs_names[0] if qgs_names else zf.namelist()[0]
                    xml = zf.read(entry).decode("utf-8")
            else:
                # Tenter decode direct (texte brut ou autre encodage)
                for enc in ("utf-8", "latin-1"):
                    try:
                        xml = raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                else:
                    self._log("Cannot decode project content from PG", Qgis.Warning)
                    return False

        # Nettoyer les authcfg des datasources et injecter user/password
        original_xml = xml
        xml = re.sub(r"\bauthcfg=\w+", "", xml)

        def _fix_datasource(m):
            """Callback pour re.sub: nettoie une balise <datasource>."""
            prefix, ds, suffix = m.group(1), m.group(2), m.group(3)
            if DEFAULT_HOST not in ds:
                return m.group(0)
            if f"user='{DEFAULT_USER}'" not in ds:
                ds += f" user='{DEFAULT_USER}'"
            if "password=" not in ds:
                ds += f" password='{password}'"
            ds = re.sub(r"\s{2,}", " ", ds).strip()
            return prefix + ds + suffix

        xml = re.sub(
            r"(<datasource>)(.*?)(</datasource>)",
            _fix_datasource,
            xml,
            flags=re.DOTALL,
        )

        if xml != original_xml:
            self._log("Project XML cleaned: authcfg references removed")

        # Ecrire dans un fichier temporaire et charger
        tmp = tempfile.NamedTemporaryFile(
            suffix=".qgs", delete=False, mode="w", encoding="utf-8",
        )
        try:
            tmp.write(xml)
            tmp.close()
            result = project.read(tmp.name)
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

        if result:
            # Restaurer le titre et vider le chemin fichier pour que
            # QGIS affiche le nom du projet (pas le fichier temporaire).
            project.setTitle(name)
            project.setFileName("")
            project.setDirty(False)

        return result

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
