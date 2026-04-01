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
    QgsMessageLog,
    QgsProject,
    QgsSettings,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QDialog, QInputDialog, QMessageBox

from .i18n import SUPPORTED_LANGUAGES, get_language, init_language, set_language, tr

TAG = "Constructel Bridge"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_HOST = os.getenv("WYRE_DB_HOST", "") or "192.168.160.31"
DEFAULT_PORT = int(os.getenv("WYRE_DB_PORT", "5432"))
DEFAULT_DBNAME = os.getenv("WYRE_DB_NAME", "wyre_ftth")
DEFAULT_USER = "ftth_editor"
_DEFAULT_PW = base64.b64decode("aXQ0RG9BNXV6aHZjZk9OWVVsUWNXQT09").decode()
DEFAULT_SRID = 31370
PG_SERVICE_NAME = "constructel_bridge"

LANG_LABELS = {"fr": "Francais", "en": "English", "pt": "Portugues"}


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

        icon_path = os.path.join(os.path.dirname(__file__), "constructel_bridge_icon.png")
        icon = QIcon(icon_path)

        action_connect = QAction(icon, tr("menu.connect"), self.iface.mainWindow())
        action_connect.triggered.connect(self._on_connect)
        self.iface.addToolBarIcon(action_connect)
        self.iface.addPluginToDatabaseMenu("Constructel Bridge", action_connect)
        self._actions.append(action_connect)

        action_status = QAction(tr("menu.status"), self.iface.mainWindow())
        action_status.triggered.connect(self._on_status)
        self.iface.addPluginToDatabaseMenu("Constructel Bridge", action_status)
        self._actions.append(action_status)

        action_onboarding = QAction(tr("menu.onboarding"), self.iface.mainWindow())
        action_onboarding.triggered.connect(self._on_onboarding)
        self.iface.addPluginToDatabaseMenu("Constructel Bridge", action_onboarding)
        self._actions.append(action_onboarding)

        action_load_project = QAction(tr("menu.load_project"), self.iface.mainWindow())
        action_load_project.triggered.connect(self._on_load_project)
        self.iface.addPluginToDatabaseMenu("Constructel Bridge", action_load_project)
        self._actions.append(action_load_project)

        action_language = QAction(tr("menu.language"), self.iface.mainWindow())
        action_language.triggered.connect(self._on_change_language)
        self.iface.addPluginToDatabaseMenu("Constructel Bridge", action_language)
        self._actions.append(action_language)

        # Corriger une eventuelle connexion QGIS sauvegardee avec un mauvais host
        self._fix_saved_pg_connection()

        # Auto-connect au demarrage si le password est deja en memoire
        try:
            self._try_auto_connect()
        except Exception as exc:
            self._log(f"Auto-connect failed: {exc}", Qgis.Warning)

    def unload(self):
        """Appele par QGIS a la desactivation du plugin."""
        self._unhook_layers()
        if self._conn and not self._conn.closed:
            self._conn.close()
        for action in self._actions:
            self.iface.removeToolBarIcon(action)
            self.iface.removePluginDatabaseMenu("Constructel Bridge", action)
        self._actions.clear()

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
            self.iface.messageBar().pushInfo(
                "Constructel Bridge",
                tr("lang.restart", lang=LANG_LABELS.get(lang_code, lang_code)),
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

    def _try_auto_connect(self):
        """Tente une connexion automatique uniquement si le mot de passe a ete sauvegarde."""
        stored_pw = QgsSettings().value("constructel_bridge/password", "")
        if stored_pw:
            if not self._connect(stored_pw, silent=True):
                # Mot de passe stocke invalide : on le supprime et on ouvre le dialogue
                QgsSettings().remove("constructel_bridge/password")
                self._log("Stored password invalid, cleared. Opening connection dialog.", Qgis.Warning)
                self._on_connect()

    def _on_connect(self):
        """Action manuelle: dialogue de connexion."""
        from .bridge_dialog import ConstructelConnectDialog

        dlg = ConstructelConnectDialog(
            self.iface.mainWindow(),
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            dbname=DEFAULT_DBNAME,
        )
        if dlg.exec_() == QDialog.Accepted:
            password = dlg.password() or _DEFAULT_PW
            save = dlg.save_password()
            if save:
                QgsSettings().setValue("constructel_bridge/password", password)
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
                options="-c search_path=infra,public",
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
            self._setup_qgis_pg_connection(password)
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

    def _fix_saved_pg_connection(self):
        """Corrige le host de la connexion QGIS sauvegardee si elle pointe vers localhost."""
        settings = QgsSettings()
        base = "PostgreSQL/connections/constructel_bridge"
        existing_host = settings.value(f"{base}/host", "")
        if existing_host and existing_host != DEFAULT_HOST:
            self._log(
                f"Fixing saved PG connection: {existing_host} -> {DEFAULT_HOST}",
                Qgis.Warning,
            )
            settings.setValue(f"{base}/host", DEFAULT_HOST)
            settings.setValue(f"{base}/port", str(DEFAULT_PORT))
            settings.setValue(f"{base}/database", DEFAULT_DBNAME)

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

    def _setup_qgis_pg_connection(self, password: str):
        """Enregistre la connexion PostgreSQL dans les settings QGIS si absente ou différente."""
        settings = QgsSettings()
        base = "PostgreSQL/connections/constructel_bridge"

        # Vérifie si la connexion existe déjà avec les mêmes paramètres
        existing_host = settings.value(f"{base}/host", "")
        existing_port = settings.value(f"{base}/port", "")
        existing_db = settings.value(f"{base}/database", "")
        existing_user = settings.value(f"{base}/username", "")
        existing_pw = settings.value(f"{base}/password", "")

        if (
            existing_host == DEFAULT_HOST
            and existing_port == str(DEFAULT_PORT)
            and existing_db == DEFAULT_DBNAME
            and existing_user == DEFAULT_USER
            and existing_pw == password
        ):
            self._log(tr("pg.already_configured"))
            return

        settings.setValue(f"{base}/host", DEFAULT_HOST)
        settings.setValue(f"{base}/port", str(DEFAULT_PORT))
        settings.setValue(f"{base}/database", DEFAULT_DBNAME)
        settings.setValue(f"{base}/username", DEFAULT_USER)
        settings.setValue(f"{base}/password", password)
        settings.setValue(f"{base}/saveUsername", True)
        settings.setValue(f"{base}/savePassword", True)
        settings.setValue(f"{base}/sslmode", "1")
        settings.setValue(f"{base}/estimatedMetadata", True)
        settings.setValue(f"{base}/allowGeometrylessTables", False)
        settings.setValue(f"{base}/geometryColumnsOnly", True)
        settings.setValue(f"{base}/dontResolveType", False)
        settings.setValue(f"{base}/publicOnly", False)
        settings.setValue(f"{base}/projectsInDatabase", True)
        settings.setValue(f"{base}/metadataInDatabase", True)
        settings.setValue(f"{base}/schemas", "infra")

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
        uri = (
            f"postgresql://{DEFAULT_USER}:{self._password}@{DEFAULT_HOST}:{DEFAULT_PORT}"
            f"/{DEFAULT_DBNAME}?schema={selected['schema']}&project={selected['name']}"
        )

        proj_name = selected["name"]
        project = QgsProject.instance()
        if project.read(uri):
            self._log(tr("project.loaded", name=proj_name))
            self.iface.messageBar().pushSuccess(
                "Constructel Bridge",
                tr("project.loaded", name=proj_name),
            )
            # Re-hook les couches du projet charge
            self._layer_hooks_installed = False
            self._hook_layers()
        else:
            error = project.error().summary() if project.error() else "Unknown error"
            self._log(tr("project.load_error", name=proj_name, error=error), Qgis.Critical)
            QMessageBox.critical(
                self.iface.mainWindow(),
                tr("project.title"),
                tr("project.load_error", name=proj_name, error=error),
            )

    _PROJECT_SCHEMAS = ("public", "infra")

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
