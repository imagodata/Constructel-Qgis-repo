# -*- coding: utf-8 -*-
"""
Constructel Bridge - Plugin principal.

Responsabilites:
  1. Configurer la connexion PostgreSQL farois_ftth (auth LDAP individuelle)
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
from .bridge_expressions import register_expressions, unregister_expressions

TAG = "Constructel Bridge"
AUTH_CFG_NAME = "constructel_bridge_pw"
AUTH_CFG_NAME_BE = "constructel_bridge_be_pw"

# Cle de settings ou est memorise l'ID de configuration Auth Manager, par
# connexion. `wyre` CONSERVE la cle historique : la changer orphaniserait
# les configurations Auth Manager deja stockees sur les postes existants.
_AUTH_CFG_ID_KEYS = {
    "wyre": "constructel_bridge/auth_cfg_id",
    "be": "constructel_bridge/auth_cfg_id_be",
}
_AUTH_CFG_NAMES = {
    "wyre": AUTH_CFG_NAME,
    "be": AUTH_CFG_NAME_BE,
}

# ---------------------------------------------------------------------------
# Credentials — loaded from credentials.json next to this file
# ---------------------------------------------------------------------------
_CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")

def _load_credentials() -> dict:
    """Load connection parameters from credentials.json.

    Format attendu depuis la v1.5.0 : un objet par connexion,
    {"wyre": {...}, "be": {...}}. Les deploiements anterieurs ont un objet
    PLAT (host/port/... a la racine) : on le rattache alors a "wyre" et on
    laisse "be" vide, plutot que de lever une KeyError a l'import du module
    — ce qui empecherait le plugin de se charger DU TOUT, `wyre` compris.
    """
    import json
    with open(_CREDENTIALS_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if "host" in raw:
        return {"wyre": raw, "be": {}}
    return raw

_CREDS = _load_credentials()
_WYRE_CREDS = _CREDS.get("wyre", {})
_BE_CREDS = _CREDS.get("be", {})


def _resolve_os_username() -> str:
    """Determine l'identifiant OS/QGIS de la personne courante.

    Attendu = sAMAccountName AD sur un poste joint au domaine (chantier
    "Authentification LDAP wyre") -- a valider empiriquement (cf. Task 10,
    verification QGIS n1). Utilisee a la fois pour DEFAULT_USER (identite
    de connexion PG "wyre") et pour l'enregistrement dans ref.users.

    Ne doit JAMAIS lever : appelee au chargement du MODULE (DEFAULT_USER =
    _resolve_os_username()), une exception ici ferait echouer l'import du
    plugin en entier -- exactement le mode d'echec que _load_credentials()
    est deja concue pour eviter.
    """
    try:
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
    except Exception:
        try:
            import getpass
            return getpass.getuser()
        except Exception:
            return ""


DEFAULT_HOST = os.getenv("WYRE_DB_HOST", "") or _WYRE_CREDS["host"]
DEFAULT_PORT = int(os.getenv("WYRE_DB_PORT", str(_WYRE_CREDS["port"])))
DEFAULT_DBNAME = os.getenv("WYRE_DB_NAME", "") or _WYRE_CREDS["dbname"]
DEFAULT_USER = _resolve_os_username()
DEFAULT_SRID = _WYRE_CREDS.get("srid", 31370)
DEFAULT_SSLMODE = _WYRE_CREDS.get("sslmode", "require")
PG_SERVICE_NAME = _WYRE_CREDS.get("service_name", "constructel_bridge")
EMAIL_DOMAIN = _WYRE_CREDS.get("email_domain", "constructel.be")

# Connexion `be` (bureau d'etudes) — schema public uniquement, identifiant
# PostgreSQL PARTAGE (pas de compte par personne). Absente des
# credentials.json anterieurs a la v1.5.0 : toutes les constantes retombent
# alors sur des valeurs vides et BE_ENABLED est False.
BE_HOST = os.getenv("BE_DB_HOST", "") or _BE_CREDS.get("host", "")
BE_PORT = int(os.getenv("BE_DB_PORT", str(_BE_CREDS.get("port", 5432))))
BE_DBNAME = os.getenv("BE_DB_NAME", "") or _BE_CREDS.get("dbname", "")
BE_USER = _BE_CREDS.get("user", "")
_BE_PW = (
    base64.b64decode(_BE_CREDS["password"]).decode()
    if _BE_CREDS.get("password") else ""
)
BE_SSLMODE = _BE_CREDS.get("sslmode", "require")

# `wyre` et `be` pointent sur le MEME host et la MEME base : dans un realm
# QgsCredentials, seul l'utilisateur les distingue (cf.
# _BridgeCredentials._credentials_for). Un bloc `be` qui reutiliserait
# l'utilisateur de `wyre` rendrait la resolution ambigue et casserait
# l'authentification de `wyre` — on refuse alors d'activer la connexion.
BE_ENABLED = (
    bool(BE_HOST and BE_DBNAME and BE_USER and _BE_PW)
    and BE_USER != DEFAULT_USER
)

# Connexions PostgreSQL enregistrees dans les settings QGIS (panneau
# Parcourir / Gestionnaire de sources de donnees).
#   name    : nom affiche = cle sous PostgreSQL/connections/<name>
#   schemas : valeur du champ "Restreindre aux schemas"
#   schema  : schema par defaut
_PG_CONNECTIONS = {
    "wyre": {
        "name": "wyre",
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "dbname": DEFAULT_DBNAME,
        "user": DEFAULT_USER,
        "sslmode": DEFAULT_SSLMODE,
        "schemas": "wyre,osiris",
        "schema": "wyre",
        # Restriction multi-schema (wyre+osiris) : la case "Seulement le
        # schema 'public'" du dialogue QGIS ne s'applique qu'a UN schema,
        # donc hors de propos ici.
        "public_only": False,
    },
    "be": {
        "name": "be",
        "host": BE_HOST,
        "port": BE_PORT,
        "dbname": BE_DBNAME,
        "user": BE_USER,
        "sslmode": BE_SSLMODE,
        "schemas": "public",
        "schema": "public",
        # `be` ne doit exposer QUE le schema public. Contrairement a `wyre`
        # (2 schemas), c'est un cas a un seul schema : en plus de la cle
        # `schemas` (liste de restriction), QGIS a une case a cocher
        # dediee "Seulement le schema 'public'" (cle de settings
        # `publicOnly`) -- l'activer specifiquement pour `be`.
        "public_only": True,
    },
}

# Nom de la connexion QGIS avant la v1.5.0. Retire des settings a chaque
# enregistrement : sans ca, le navigateur QGIS afficherait a la fois
# l'ancienne entree et la nouvelle apres mise a jour du plugin.
_LEGACY_PG_CONNECTION = "PostgreSQL/connections/constructel_bridge"

LANG_LABELS = {"fr": "Francais", "en": "English", "pt": "Portugues"}


# ---------------------------------------------------------------------------
# Echappement de valeurs pour datasource PG (user='...' password='...')
# ---------------------------------------------------------------------------

# Chaine entre quotes simples, consciente des caracteres echappes (\x) --
# notamment le \' que QgsDataSourceUri::escape() genere pour une
# apostrophe litterale dans un mot de passe. Un [^']* naif s'arrete sur ce
# \' et laisse le reste de la valeur (jusqu'a la VRAIE quote fermante)
# dans la chaine -- fragment de secret qui fuite dans le projet sauvegarde.
_QUOTED = r"'(?:[^'\\]|\\.)*'"


def _escape_pg_uri_value(value: str) -> str:
    """Echappe une valeur avant de l'inserer entre quotes simples dans une
    datasource PG, comme QgsDataSourceUri::escape() le fait en interne.

    Ordre important : les backslashes sont doubles EN PREMIER, puis les
    quotes simples sont echappees. Inverser l'ordre echapperait aussi le
    backslash que l'on vient d'ajouter pour la quote, produisant une
    sequence incorrecte.
    """
    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace("'", "\\'")
    return escaped


# ---------------------------------------------------------------------------
# Intercepteur de credentials — evite le dialogue de saisie pour notre base
# ---------------------------------------------------------------------------

class _BridgeCredentials(QgsCredentials):
    """Fournit automatiquement les credentials pour nos connexions PG.

    Quand un projet contient des couches avec un authcfg d'un autre
    utilisateur, QGIS affiche un dialogue de saisie pour chaque couche.
    Ce handler intercepte ces demandes et fournit le mot de passe
    automatiquement si le realm correspond a notre serveur PG.
    Pour les autres realms, il delegue au handler original (dialogue).

    `wyre` et `be` pointent sur le MEME host et la MEME base : le realm
    seul ne les distingue pas, la discrimination se fait sur le nom
    d'utilisateur (cf. _credentials_for).
    """

    def __init__(self, fallback, plugin):
        self._fallback = fallback
        self._plugin = plugin
        super().__init__()  # appelle setInstance(self) en interne

    def _credentials_for(self, realm, username):
        """Resout le couple (utilisateur, mot de passe) pour un realm.

        Seul `be` est fourni automatiquement (mot de passe partage,
        issu de credentials.json). `wyre` n'a plus de mot de passe
        connu a l'avance (auth LDAP individuelle) : toute demande pour
        son realm est deleguee au dialogue QGIS natif via `request()`.

        Retourne None si le realm ne nous concerne pas (ou concerne
        `wyre`, qui doit toujours passer par le dialogue natif).

        Le repli sur simple correspondance de *username* est ANCRE sur
        BE_HOST : ce handler reste le singleton QgsCredentials actif pour
        toute la session QGIS, donc sans cet ancrage une demande vers un
        serveur PG TIERS ou le username serait egalement `bureau_etudes`
        recevrait par erreur le mot de passe `be` -- fuite de credentials
        vers un serveur externe.
        """
        if BE_ENABLED and BE_HOST in realm and (f"user='{BE_USER}'" in realm or username == BE_USER):
            return BE_USER, _BE_PW
        return None

    def request(self, realm, username, password, message=""):
        QgsMessageLog.logMessage(
            f"Credentials request intercepted — realm={realm!r}",
            TAG, level=Qgis.Info,
        )
        creds = self._credentials_for(realm, username)
        if creds is not None:
            user, pwd = creds
            QgsMessageLog.logMessage(
                f"Auto-providing credentials for {user}",
                TAG, level=Qgis.Info,
            )
            # Also cache via put() so subsequent get() calls skip request()
            self.put(realm, user, pwd)
            return True, user, pwd
        # Realm inconnu (ou wyre, qui n'a plus de reponse automatique) ->
        # deleguer au handler QGIS par defaut (dialogue natif).
        if self._fallback:
            ok, user, pwd = self._fallback.request(realm, username, password, message)
            if ok and DEFAULT_HOST in realm:
                # La personne vient de saisir SON mot de passe AD dans le
                # dialogue natif QGIS. On le met en cache RAM (jamais sur
                # disque, meurt avec le process) pour eviter une seconde
                # invite dans la meme session, et on declenche le flux de
                # connexion habituel du plugin (hooks de commit,
                # enregistrement ref.users) s'il n'est pas deja actif --
                # sans cela, une personne qui ouvre un projet et tape son
                # mot de passe au dialogue natif reste "deconnectee" cote
                # plugin (pas d'attribution d'edition).
                self.put(realm, user, pwd)
                if not self._plugin._connected:
                    self._plugin._connect(pwd, silent=True)
            return ok, user, pwd
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
    """Pre-cache les credentials PG de `be` (bureau d'etudes).

    `wyre` n'a plus de mot de passe par defaut (authentification LDAP,
    saisie a chaque session) : rien a pre-cacher pour cette connexion,
    QGIS doit demander le mot de passe nativement.
    """
    if not BE_ENABLED:
        return
    creds = QgsCredentials.instance()
    # `be` partage host + base avec `wyre` : SEULES les variantes de realm
    # qui portent user='...' sont pre-cachees. Pre-cacher une variante sans
    # utilisateur pourrait faire servir le mot de passe `be` a une demande
    # de connexion `wyre` qui matcherait le meme realm generique.
    for realm in (
        f"dbname='{BE_DBNAME}' host={BE_HOST} port={BE_PORT} user='{BE_USER}'",
        f"dbname='{BE_DBNAME}' host={BE_HOST} port={BE_PORT} sslmode={BE_SSLMODE} user='{BE_USER}'",
    ):
        creds.put(realm, BE_USER, _BE_PW)


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


def _store_password_encrypted(password: str, conn: str = "wyre") -> bool:
    """Store the password in QGIS Auth Manager (encrypted SQLite DB).

    *conn* est une cle de ``_PG_CONNECTIONS`` : chaque connexion a sa
    propre configuration Auth Manager et sa propre cle de settings, sinon
    `be` ecraserait celle de `wyre` (et inversement).

    Returns True on success.
    """
    if not _ensure_auth_manager_ready():
        QgsMessageLog.logMessage(
            "Auth Manager not available, cannot store encrypted password.",
            TAG, level=Qgis.Warning,
        )
        return False
    auth_mgr = QgsApplication.authManager()
    settings_key = _AUTH_CFG_ID_KEYS[conn]
    # Look for an existing config with our name
    cfg_id = QgsSettings().value(settings_key, "")
    if cfg_id and cfg_id in auth_mgr.configIds():
        # Update existing config
        config = QgsAuthMethodConfig()
        auth_mgr.loadAuthenticationConfig(cfg_id, config, True)
        config.setConfig("password", password)
        ok = auth_mgr.updateAuthenticationConfig(config)
    else:
        # Create new config
        config = QgsAuthMethodConfig("Basic")
        config.setName(_AUTH_CFG_NAMES[conn])
        config.setConfig("username", _PG_CONNECTIONS[conn]["user"])
        config.setConfig("password", password)
        ok = auth_mgr.storeAuthenticationConfig(config)
        if ok:
            QgsSettings().setValue(settings_key, config.id())
    # Remove legacy plaintext password if present -- ONLY for `wyre` and
    # only on success: this key is the pre-Auth-Manager migration source
    # read by _retrieve_password_encrypted("wyre"). Since `be`'s own setup
    # now runs (with authcfg=True) before wyre's auto-connect in initGui,
    # an unconditional removal here would destroy that legacy value before
    # wyre had a chance to migrate it, on a be-triggered call that has
    # nothing to do with wyre's password.
    if conn == "wyre" and ok:
        QgsSettings().remove("constructel_bridge/password")
    return ok


def _retrieve_password_encrypted(conn: str = "wyre") -> str:
    """Retrieve the password from QGIS Auth Manager.

    Returns the password string, or empty string if not found.
    """
    if not _ensure_auth_manager_ready():
        return ""
    auth_mgr = QgsApplication.authManager()
    cfg_id = QgsSettings().value(_AUTH_CFG_ID_KEYS[conn], "")
    if not cfg_id or cfg_id not in auth_mgr.configIds():
        # Fallback: check legacy plaintext storage and migrate.
        # RESERVE a `wyre` : la cle historique constructel_bridge/password
        # ne contient que le mot de passe de la connexion d'origine ; la
        # renvoyer pour `be` fournirait un mot de passe faux.
        if conn == "wyre":
            legacy_pw = QgsSettings().value("constructel_bridge/password", "")
            if legacy_pw:
                _store_password_encrypted(legacy_pw, conn)
                return legacy_pw
        return ""
    config = QgsAuthMethodConfig()
    auth_mgr.loadAuthenticationConfig(cfg_id, config, True)
    return config.config("password", "")


def _remove_stored_password(conn: str = "wyre"):
    """Remove the stored password from Auth Manager and legacy settings."""
    auth_mgr = QgsApplication.authManager()
    settings_key = _AUTH_CFG_ID_KEYS[conn]
    cfg_id = QgsSettings().value(settings_key, "")
    if cfg_id and cfg_id in auth_mgr.configIds():
        auth_mgr.removeAuthenticationConfig(cfg_id)
    QgsSettings().remove(settings_key)
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
        register_expressions()
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

        icon_init = theme("/mActionNewMap.svg")
        action_init_project = QAction(icon_init, tr("menu.init_project"), parent)
        action_init_project.triggered.connect(self._on_init_project)
        self._actions.append(action_init_project)

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
        self._toolbar_menu.addAction(action_init_project)
        self._toolbar_menu.addSeparator()
        self._toolbar_menu.addAction(action_language)

        self._tool_button = QToolButton(parent)
        self._tool_button.setIcon(plugin_icon)
        self._tool_button.setToolTip("Constructel Bridge")
        self._tool_button.setMenu(self._toolbar_menu)
        self._tool_button.setPopupMode(QToolButton.MenuButtonPopup)
        self._tool_button.clicked.connect(self._on_init_project)

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

        # Enregistrer les connexions WMTS / XYZ / WFS externes
        try:
            self._setup_external_services()
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"External services setup failed: {exc}", TAG, level=Qgis.Warning,
            )

        # Pre-provisionner la dependance pip `extract-msg` utilisee par le
        # script Processing de geocodage .msg (diffuse via Resource Sharing).
        # Best-effort: ne doit jamais interrompre le chargement du plugin.
        try:
            self._ensure_extract_msg_available()
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"extract-msg pre-provisioning failed: {exc}", TAG, level=Qgis.Warning,
            )

        # Intercepter les demandes de credentials QGIS pour fournir
        # automatiquement le mot de passe de notre base PG.
        # Cela evite le dialogue "Saisir les identifiants" quand un
        # projet contient des authcfg d'un autre utilisateur.
        self._orig_credentials = QgsCredentials.instance()
        self._bridge_credentials = _BridgeCredentials(self._orig_credentials, self)

        # Pre-cacher les credentials PG pour que QgsCredentials.get()
        # les trouve dans le cache AVANT d'appeler request().
        # Cela couvre le cas ou un projet avec authcfg inconnu est charge
        # au demarrage (projets recents, browser, etc.).
        _precache_pg_credentials()

        # Enregistrer la connexion `be` (bureau d'etudes, schema public),
        # AVEC authcfg : sans reference authcfg stockee, le bouton "Tester
        # la connexion" et le parcours du navigateur QGIS pour `be`
        # n'utilisent PAS le meme chemin que le chargement de couche et ne
        # beneficient donc pas de l'interception _BridgeCredentials —
        # l'utilisateur se retrouve avec une invite de mot de passe
        # bloquante (constate en test reel).
        #
        # Ce bloc s'execute AVANT self._auto_connect() (plus bas dans
        # initGui) : c'est donc `be`, pas `wyre`, qui declenche en premier
        # _ensure_auth_manager_ready() a chaque demarrage du plugin. Sur un
        # poste ou le mot de passe maitre QGIS est deja configure (le cas
        # normal des que `wyre` a reussi une connexion authcfg au moins une
        # fois), setMasterPassword(True) ne re-affiche PAS de dialogue :
        # aucune regression. Cas limite assume : premiere installation +
        # base injoignable des le premier demarrage -> `be` (contrairement
        # a l'auto-connexion `wyre`, qui reste use_authcfg=False sur son
        # propre chemin d'echec) peut alors declencher la creation du mot
        # de passe maitre plus tot que necessaire. Juge acceptable : rare,
        # et l'utilisateur devra de toute facon configurer ce mot de passe
        # maitre des que `wyre` se connectera avec succes.
        #
        # `be` n'a toujours pas besoin du flux _connect complet (psycopg2,
        # ref.users, onboarding) : c'est une connexion de consultation.
        if BE_ENABLED:
            try:
                self._setup_qgis_pg_connection(_BE_PW, use_authcfg=True, conn="be")
            except Exception as exc:
                QgsMessageLog.logMessage(
                    f"BE connection setup failed: {exc}", TAG, level=Qgis.Warning,
                )
        else:
            # BE_ENABLED peut etre False pour 2 raisons distinctes depuis
            # que DEFAULT_USER est une identite par personne (et non plus
            # une constante fixe) : bloc be absent/invalide, OU collision
            # DEFAULT_USER == BE_USER (ex. poste partage dont le compte OS
            # s'appelle "bureau_etudes") -- dans ce dernier cas, activer
            # `be` rendrait _credentials_for ambigu (un realm wyre avec
            # username == BE_USER recevrait a tort le mot de passe be).
            reason = (
                "l'identite AD/OS courante coincide avec le compte partage "
                "bureau_etudes -- resolution de credentials ambigue, be "
                "reste desactivee par securite"
                if BE_USER and BE_USER == DEFAULT_USER
                else "bloc absent ou invalide dans credentials.json"
            )
            QgsMessageLog.logMessage(
                f"Connexion 'be' non configuree ({reason})",
                TAG, level=Qgis.Info,
            )

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
        # Enveloppe (comme le bloc be juste au-dessus) : _auto_connect()
        # fait des ecritures Auth Manager / QgsSettings et pourrait lever
        # -- sans ce try/except, une exception ici interromprait initGui
        # a mi-chemin (hooks projet deja connectes = plugin a moitie
        # initialise).
        try:
            self._auto_connect()
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Auto-connect failed: {exc}", TAG, level=Qgis.Warning,
            )

    def unload(self):
        """Appele par QGIS a la desactivation du plugin."""
        unregister_expressions()
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

        Corrige les credentials, re-hook les couches et applique les
        traductions i18n — sans toucher a la structure du layer tree.
        Ne s'active que sur les projets inities par le plugin (bridge_operator).
        """
        # Toujours corriger les credentials (utilise le mot de passe par
        # defaut si pas encore connecte — suffit pour reparer les authcfg).
        try:
            self._fix_layer_credentials()
        except Exception as exc:
            self._log(f"Fix layer credentials failed: {exc}", Qgis.Warning)

        if not self._connected:
            return

        # Ne traiter que les projets Bridge (eviter d'interferer avec
        # des projets QGIS generiques qui ne sont pas geres par le plugin)
        from .bridge_project_init import is_bridge_project, get_bridge_info
        if not is_bridge_project():
            self._log("Projet non-Bridge detecte — hooks/relations/i18n ignores")
            return

        info = get_bridge_info()
        self._log(
            f"Projet Bridge detecte — operator={info['operator']!r} "
            f"version={info['version']!r} plugin={info['plugin']!r}"
        )

        self._layer_hooks_installed = False
        try:
            self._hook_layers()
        except Exception as exc:
            self._log(f"Hook install failed: {exc}", Qgis.Warning)

        try:
            from .bridge_project_init import ensure_relations
            ensure_relations()
        except Exception as exc:
            self._log(f"Relations recreate failed: {exc}", Qgis.Warning)

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
        user-specific et normaliser user=/password= (wyre : toujours mot
        de passe vide ; be : son mot de passe partage inchange). Portable
        au sens ou l'authcfg (propre au poste de qui a sauvegarde) ne
        bloque plus l'ouverture chez quelqu'un d'autre -- mais depuis le
        passage en auth LDAP, ouvrir une couche wyre declenche desormais
        TOUJOURS le dialogue natif de saisie du mot de passe, quel que
        soit qui a sauvegarde le projet (comportement voulu, pas une
        regression : "portable" ne veut plus dire "sans dialogue" pour wyre).
        """
        try:
            self._strip_authcfg_from_dom(doc)
        except Exception as exc:
            self._log(f"Strip authcfg from DOM failed: {exc}", Qgis.Warning)

    def _strip_authcfg_from_dom(self, doc):
        """Parcourt le DOM du projet, retire les authcfg des datasources PG
        et normalise le mot de passe wyre a "" -- meme en l'absence de
        tout authcfg.

        Miroir cote ECRITURE de _fix_layer_credentials (cote lecture) :
        meme raisonnement known_identities (preserver l'identite be plutot
        que tout basculer vers wyre) et meme garde d'hote (ne jamais
        injecter nos identifiants dans la datasource d'un serveur tiers).
        Corrige au passage un bug de l'ancienne version : le test
        `f"user='{DEFAULT_USER}'" not in ds` ne detectait pas un user=
        EXISTANT different (ex. bureau_etudes), ce qui ajoutait un second
        attribut user= en double dans la datasource au lieu de remplacer
        le premier.

        IMPORTANT (fix round 2, cf. C1) : le traitement d'une datasource
        n'est PLUS conditionne a la presence d'un authcfg=. Une couche
        construite directement avec un QgsDataSourceUri portant le vrai
        mot de passe de session (ex. _ensure_ref_layers, _on_init_project)
        n'a jamais eu d'authcfg -- un gate `"authcfg=" in ds` la laissait
        passer intacte, vrai mot de passe AD inclus, dans le projet
        sauvegarde/round-trip PG. TOUTE datasource postgres pointant sur
        nos hotes (wyre/be) est donc retraitee inconditionnellement ; la
        presence d'un authcfg ne fait plus que determiner s'il y a
        quelque chose a retirer en plus du user/password (le re.sub sur
        authcfg= est un no-op quand il est deja absent).
        """
        import re
        known_identities = {DEFAULT_USER: (DEFAULT_USER, "")}
        if BE_ENABLED:
            known_identities[BE_USER] = (BE_USER, _BE_PW)

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
            # Ne jamais injecter nos identifiants dans la datasource d'un
            # serveur PG tiers. Filtre les hotes vides (BE_HOST == "" quand
            # `be` est desactivee) AVANT le test : "" est toujours une
            # sous-chaine de n'importe quel `ds` en Python, donc un hote
            # vide dans le tuple annulerait silencieusement cette garde.
            if not any(h and h in ds for h in (DEFAULT_HOST, BE_HOST)):
                continue

            # Determiner l'identite a preserver depuis le user='...'
            # existant AVANT de le retirer -- repli sur wyre si absent ou
            # inconnu (meme comportement que _fix_layer_credentials).
            user_match = re.search(r"user='([^']*)'", ds)
            current_user = user_match.group(1) if user_match else None
            target_user, target_password = known_identities.get(
                current_user, (DEFAULT_USER, "")
            )

            # Retirer authcfg=xxx (s'il existe -- no-op sinon) ainsi que
            # tout user=/password= existant, puis reinjecter l'identite
            # cible en clair -- evite toute duplication d'attribut. Execute
            # pour TOUTE datasource matchant nos hotes, authcfg present ou
            # non (cf. docstring -- ne plus se fier a "authcfg=" in ds).
            #
            # CRITIQUE : user=/password= sont retires avec _QUOTED (chaine
            # entre quotes consciente des caracteres echappes), PAS un
            # naif [^']* -- celui-ci s'arrete au premier \' (que
            # QgsDataSourceUri::escape() genere pour une apostrophe
            # litterale dans un mot de passe, ex. abc'def -> abc\'def) et
            # laisse le reste de la valeur (" def'") dans la datasource --
            # fragment de mot de passe qui fuite dans le projet sauvegarde
            # / round-trip PG. target_user/target_password sont eux-memes
            # echappes avant reinjection (_escape_pg_uri_value) au cas ou
            # une identite AD contiendrait une apostrophe ou un backslash
            # (sAMAccountName les autorise en theorie, contrairement a un
            # certain nombre d'autres caracteres).
            ds = re.sub(r"\bauthcfg=\w+", "", ds)
            ds = re.sub(r"\buser=" + _QUOTED, "", ds)
            ds = re.sub(r"\bpassword=" + _QUOTED, "", ds)
            ds += (
                f" user='{_escape_pg_uri_value(target_user)}'"
                f" password='{_escape_pg_uri_value(target_password)}'"
            )
            ds = re.sub(r"\s{2,}", " ", ds).strip()
            # Remplacer le contenu du noeud
            while ds_node.hasChildNodes():
                ds_node.removeChild(ds_node.firstChild())
            ds_node.appendChild(doc.createTextNode(ds))
            cleaned += 1
        if cleaned:
            self._log(f"{cleaned} datasource(s) PG normalisee(s) avant sauvegarde (authcfg/mot de passe)")

    # =====================================================================
    # Auto-connexion
    # =====================================================================

    def _auto_connect(self):
        """Purge tout mot de passe wyre precedemment memorise (legacy
        pre-LDAP) au lieu de l'utiliser.

        Depuis le passage en auth LDAP, `wyre` ne doit plus JAMAIS se
        connecter silencieusement -- meme si un mot de passe est reste
        stocke dans Auth Manager depuis une session anterieure a ce
        chantier (la case "memoriser" existait avant et etait cochee par
        defaut). Le reutiliser romprait "saisie a chaque session" et,
        avant le fix C1, aurait pu faire fuiter ce mot de passe stocke
        via known_identities. La personne doit cliquer Connecter
        (menu / bouton), qui ouvre le dialogue de saisie natif.
        """
        if self._connected:
            return
        _remove_stored_password("wyre")
        QgsSettings().remove("PostgreSQL/connections/wyre/authcfg")
        self._log(
            "Auto-connexion 'wyre' desactivee (auth LDAP) — tout mot de "
            "passe memorise precedemment a ete purge, connexion manuelle "
            "requise.",
            Qgis.Info,
        )

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
            "menu.load_project", "menu.init_project", "menu.language",
        ]
        for action, key in zip(self._actions, keys):
            action.setText(tr(key))

    # =====================================================================
    # Connexion
    # =====================================================================

    def _on_connect(self):
        """Action manuelle: dialogue de connexion (mot de passe AD, jamais memorise)."""
        from .bridge_dialog import ConstructelConnectDialog

        dlg = ConstructelConnectDialog(
            self.iface.mainWindow(),
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            dbname=DEFAULT_DBNAME,
            user=DEFAULT_USER,
        )
        if dlg.exec_() == QDialog.Accepted:
            self._connect(dlg.password())

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
                options="-c search_path=wyre,public",
                sslmode=DEFAULT_SSLMODE,
            )
            self._conn.autocommit = True
        except (psycopg2.Error, OSError) as exc:
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
            # Ne jamais laisser un mot de passe errone/perime dans
            # self._password apres un echec de connexion.
            self._password = None
            return False

        self._connected = True
        self._log(tr("conn.established"))

        try:
            is_new_user = self._register_bridge_user()
        except Exception as exc:
            self._log(f"User registration failed: {exc}", Qgis.Warning)
            is_new_user = False

        try:
            self._setup_qgis_pg_connection(password, use_authcfg=False)
        except Exception as exc:
            self._log(f"QGIS PG config failed: {exc}", Qgis.Warning)

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
            bridge_sketcher.apply_all_translations()
        except Exception as exc:
            self._log(f"i18n apply failed: {exc}", Qgis.Warning)

    # =====================================================================
    # Identification et enregistrement utilisateur
    # =====================================================================

    def _get_qgis_username(self) -> str:
        """Identite QGIS de la personne courante -- TOUJOURS DEFAULT_USER.

        DEFAULT_USER est resolu UNE SEULE FOIS a l'import du module (cf.
        _resolve_os_username()). Rappeler _resolve_os_username() ici
        pourrait renvoyer une valeur differente si l'environnement a
        change depuis (ex. reglage constructel_bridge/username modifie en
        cours de session) -- ce qui ferait diverger l'identite utilisee
        pour AUTHENTIFIER la connexion PG (DEFAULT_USER, fixee) de celle
        utilisee pour ATTRIBUER les editions (ref.users, app.current_user).
        Les deux doivent toujours designer la meme personne.
        """
        return DEFAULT_USER

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
        Cela garantit que tout projet sauvegarde ne bloque plus sur un
        authcfg inconnu chez un autre utilisateur -- mais "portable" ne
        veut PAS dire "sans dialogue" pour wyre : son mot de passe est
        toujours normalise a "" (jamais le vrai mot de passe AD de
        session), donc ouvrir une couche wyre continue de declencher le
        dialogue natif de saisie -- par design (auth LDAP individuelle).
        Gere aussi les couches invalides (provider=None) en utilisant
        layer.providerType() et layer.source() directement.
        """
        # Deux identites plugin sont legitimes ici : wyre (DEFAULT_USER,
        # historique) et be (BE_USER, bureau d'etudes, si active). Sans
        # cette distinction, toute couche `be` (username=bureau_etudes)
        # etait auparavant reecrite de force vers wyre a chaque ouverture
        # de projet -- cassant le cloisonnement schema public de `be` et
        # embarquant le mot de passe wyre en clair dans le .qgz d'un
        # utilisateur externe (bureau d'etudes). Hisse hors de la boucle :
        # invariant, pas la peine de le reconstruire par couche.
        #
        # Le mot de passe wyre associe est TOUJOURS "" (jamais le vrai mot
        # de passe AD de la session) : ces identites sont ecrites dans des
        # projets partages (.qgz ou {schema}.qgis_projects), jamais un lieu
        # de stockage prive -- cf. incident de securite qui a motive ce
        # chantier. Une couche wyre normalisee vaut "user=... password=''",
        # ce qui fait retomber QGIS sur le dialogue natif au chargement.
        known_identities = {DEFAULT_USER: (DEFAULT_USER, "")}
        if BE_ENABLED:
            known_identities[BE_USER] = (BE_USER, _BE_PW)

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

            # Ne jamais injecter nos identifiants dans la datasource d'un
            # serveur PG TIERS -- seules les couches pointant sur notre
            # propre serveur (wyre/be, meme host aujourd'hui) sont
            # concernees par cette normalisation de portabilite.
            # Meme precaution que _strip_authcfg_from_dom : ne comparer
            # qu'aux hotes REELLEMENT configures, sinon une couche sans
            # hote explicite (ex. connexion par service=...) matcherait
            # a tort un BE_HOST vide (be desactivee).
            known_hosts = {h for h in (DEFAULT_HOST, BE_HOST) if h}
            if uri.host() not in known_hosts:
                continue

            old_authcfg = uri.authConfigId()
            current_user = uri.username()
            target_user, target_password = known_identities.get(
                current_user, (DEFAULT_USER, "")
            )
            # IMPORTANT (fix round 2, cf. C1) : needs_fix ne se limite plus
            # a "authcfg present ou identite inconnue". Une couche
            # construite directement avec un QgsDataSourceUri portant deja
            # le bon user='...' MAIS un vrai mot de passe (ex.
            # _ensure_ref_layers, _on_init_project) "semblait" deja
            # correcte sous l'ancien test -- son mot de passe reel restait
            # alors tel quel en memoire. On compare desormais aussi le mot
            # de passe courant a la cible attendue.
            needs_fix = (
                bool(old_authcfg)
                or current_user != target_user
                or uri.password() != target_password
            )
            if needs_fix:
                uri.setAuthConfigId("")
                uri.setUsername(target_user)
                uri.setPassword(target_password)

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

        # Appliquer les styles par defaut depuis public.layer_styles
        self._apply_db_default_styles()

    def _apply_db_default_styles(self):
        """Charge les styles QML par defaut depuis public.layer_styles.

        Pour chaque couche PG valide du projet, verifie si un style par
        defaut existe dans la base et l'applique s'il n'est pas deja charge.
        """
        conn = self._conn
        if not conn:
            return
        project = QgsProject.instance()
        applied = 0
        try:
            cur = conn.cursor()
            for layer in project.mapLayers().values():
                if not isinstance(layer, QgsVectorLayer) or not layer.isValid():
                    continue
                if layer.providerType() != "postgres":
                    continue
                provider = layer.dataProvider()
                if not provider:
                    continue
                uri = provider.uri()
                schema = uri.schema()
                table = uri.table()
                geom_col = uri.geometryColumn() or ""
                if not schema or not table:
                    continue
                try:
                    cur.execute(
                        'SELECT styleqml::text FROM public.layer_styles '
                        "WHERE f_table_schema = %s AND f_table_name = %s "
                        'AND f_geometry_column = %s AND useasdefault = true '
                        "AND stylename = 'default' LIMIT 1",
                        (schema, table, geom_col),
                    )
                    row = cur.fetchone()
                    if not row or not row[0]:
                        continue
                except (Exception, ) as _style_err:
                    self._log(f"Style query error for {schema}.{table}: {_style_err}", Qgis.Warning)
                    continue
                # Ecrire le QML dans un fichier temporaire et l'appliquer
                import tempfile
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".qml", delete=False, mode="w", encoding="utf-8"
                )
                try:
                    tmp.write(row[0])
                    tmp.close()
                    result = layer.loadNamedStyle(tmp.name)
                finally:
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass
                if isinstance(result, tuple):
                    ok = result[1] if isinstance(result[0], str) else result[0]
                else:
                    ok = bool(result)
                if ok:
                    layer.triggerRepaint()
                    applied += 1
            cur.close()
        except Exception as exc:
            self._log(f"Style loading error: {exc}", Qgis.Warning)
        if applied:
            self._log(f"{applied} couche(s): styles par defaut appliques")

        # Charger les couches de reference cachees requises par les ValueRelation
        self._ensure_ref_layers()

    def _ensure_ref_layers(self):
        """Charge ref.v_form_lists comme couche cachee pour les ValueRelation.

        Les formulaires QGIS utilisent des ValueRelation qui referencent
        ref.v_form_lists. Cette couche doit exister dans le projet pour
        que les listes deroulantes fonctionnent.
        """
        project = QgsProject.instance()
        # Verifier si v_form_lists est deja chargee
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            provider = layer.dataProvider()
            if not provider or provider.name() != "postgres":
                continue
            uri = provider.uri()
            if uri.schema() == "ref" and uri.table() == "v_form_lists":
                return  # Deja chargee

        # Charger la couche cachee
        password = getattr(self, "_password", None) or ""
        uri = QgsDataSourceUri()
        uri.setConnection(
            DEFAULT_HOST, str(DEFAULT_PORT), DEFAULT_DBNAME,
            DEFAULT_USER, password, DEFAULT_SSLMODE,
        )
        uri.setDataSource("ref", "v_form_lists", None, "", "rid")
        layer = QgsVectorLayer(uri.uri(False), "v_form_lists", "postgres")
        if layer.isValid():
            # addMapLayer(layer, False) = ne pas afficher dans la legende
            project.addMapLayer(layer, False)
            self._log("ref.v_form_lists chargee (couche cachee pour formulaires)")

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

    def _setup_qgis_pg_connection(self, password: str, use_authcfg: bool = False,
                                  conn: str = "wyre"):
        """Enregistre une connexion PostgreSQL dans les settings QGIS.

        Always writes all values to ensure consistency and fix any
        leftover misconfiguration from previous plugin versions.

        *conn* est une cle de ``_PG_CONNECTIONS`` ("wyre" ou "be") : elle
        determine le nom affiche, les parametres serveur et les schemas
        exposes.  Le defaut "wyre" preserve le comportement des appelants
        historiques (_connect).

        When *use_authcfg* is True, stores credentials in Auth Manager
        and references the authcfg ID instead of storing the password
        in plaintext (equivalent to "Convertir en configuration").
        """
        params = _PG_CONNECTIONS[conn]
        settings = QgsSettings()
        base = f"PostgreSQL/connections/{params['name']}"

        settings.setValue(f"{base}/host", params["host"])
        settings.setValue(f"{base}/port", str(params["port"]))
        settings.setValue(f"{base}/database", params["dbname"])
        settings.setValue(f"{base}/username", params["user"])
        settings.setValue(f"{base}/sslmode", "3")
        settings.setValue(f"{base}/estimatedMetadata", True)
        settings.setValue(f"{base}/allowGeometrylessTables", False)
        settings.setValue(f"{base}/geometryColumnsOnly", True)
        settings.setValue(f"{base}/dontResolveType", False)
        settings.setValue(f"{base}/publicOnly", params.get("public_only", False))
        settings.setValue(f"{base}/projectsInDatabase", True)
        settings.setValue(f"{base}/metadataInDatabase", True)
        settings.setValue(f"{base}/schemas", params["schemas"])
        settings.setValue(f"{base}/schema", params["schema"])

        if use_authcfg:
            # Store credentials in Auth Manager (encrypted)
            store_ok = _store_password_encrypted(password, conn)
            auth_cfg_id = settings.value(_AUTH_CFG_ID_KEYS[conn], "")
            if store_ok and auth_cfg_id:
                settings.setValue(f"{base}/authcfg", auth_cfg_id)
                self._log(
                    f"PG connection '{params['name']}' configured with authcfg (encrypted)."
                )
            else:
                # Auth Manager not ready — clear any stale authcfg
                settings.remove(f"{base}/authcfg")
                self._log(
                    f"Auth Manager unavailable, PG connection '{params['name']}' "
                    "uses saved password.",
                    Qgis.Warning,
                )
        else:
            settings.remove(f"{base}/authcfg")

        # Only store username; password is handled by Auth Manager (encrypted).
        # Storing plaintext password in QgsSettings is a security risk.
        settings.setValue(f"{base}/saveUsername", True)
        settings.setValue(f"{base}/savePassword", False)
        settings.remove(f"{base}/password")

        # Renommage v1.5.0 : retirer l'entree historique "constructel_bridge".
        settings.remove(_LEGACY_PG_CONNECTION)

        self._log(tr("pg.configured", name=params["name"]))

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

    @staticmethod
    def _resolve_python_executable():
        """Resout le chemin du VRAI interpreteur Python embarque par QGIS.

        Sur QGIS Windows, sys.executable pointe vers qgis-bin.exe (l'appli hote
        qui embarque Python), PAS vers un python.exe autonome. Le passer tel
        quel a pip via subprocess fait interpreter par QGIS les arguments
        "-m", "pip", ... comme des sources de donnees a ouvrir
        ("Invalid Data Source"). On resout donc l'interpreteur reel:

          - Windows: python3.exe / python.exe dans sys.exec_prefix puis
            sys.prefix (ex. C:/Program Files/QGIS 3.34/apps/Python312/).
          - Linux/Mac: sys.executable est generalement deja un interpreteur
            valide; repli sur <prefix>/bin/python3 puis shutil.which().

        Retourne un chemin verifie via os.path.isfile, ou None si aucun
        interpreteur valide n'est trouve (l'appelant s'abstient alors de pip).
        """
        import sys
        import shutil

        candidates = []
        if sys.platform.startswith("win"):
            for base in (sys.exec_prefix, sys.prefix):
                if not base:
                    continue
                candidates.append(os.path.join(base, "python3.exe"))
                candidates.append(os.path.join(base, "python.exe"))
        else:
            exe = sys.executable
            if exe and os.path.basename(exe).lower().startswith("python"):
                candidates.append(exe)
            for base in (sys.exec_prefix, sys.prefix):
                if not base:
                    continue
                candidates.append(os.path.join(base, "bin", "python3"))
                candidates.append(os.path.join(base, "bin", "python"))
            for name in ("python3", "python"):
                found = shutil.which(name)
                if found:
                    candidates.append(found)

        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate
        return None

    def _ensure_extract_msg_available(self):
        """Pre-provisionne la dependance pip `extract-msg` (best-effort).

        Utilisee par le script Processing de geocodage As-Built (.msg),
        diffuse separement via QGIS Resource Sharing. Cette methode tente
        une installation pip silencieuse au demarrage du plugin pour que
        la dependance soit deja presente le jour ou l'utilisateur installe
        ce script.

        Contrat: cette methode ne doit JAMAIS laisser remonter d'exception.
        """
        try:
            try:
                import extract_msg  # noqa: F401
                self._log("Dependance 'extract-msg' deja disponible")
                return
            except ImportError:
                pass

            self._log("Dependance 'extract-msg' absente — tentative d'installation pip…")
            import subprocess

            python_exe = self._resolve_python_executable()
            if not python_exe:
                self._log(
                    "Interpreteur Python introuvable: installation automatique de "
                    "'extract-msg' ignoree. Installation manuelle requise: "
                    "python -m pip install extract-msg",
                    level=Qgis.Warning,
                )
                return

            result = subprocess.run(
                [python_exe, "-m", "pip", "install", "extract-msg"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self._log(
                    "Echec de l'installation pip de 'extract-msg' "
                    f"(code {result.returncode}): {(result.stderr or '').strip()[:500]}",
                    level=Qgis.Warning,
                )
                return

            import importlib
            importlib.invalidate_caches()
            try:
                import extract_msg  # noqa: F401
                self._log("Dependance 'extract-msg' installee avec succes")
            except ImportError:
                self._log(
                    "pip a reussi mais 'extract-msg' reste introuvable — "
                    "un redemarrage de QGIS peut etre necessaire",
                    level=Qgis.Warning,
                )
        except Exception as exc:
            self._log(
                f"Pre-provisionnement de 'extract-msg' ignore ({exc})",
                level=Qgis.Warning,
            )

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
            # Use the plugin's own psycopg2 connection for parameterized queries
            # to avoid SQL injection via provider.executeSql() f-strings.
            if self._conn and not self._conn.closed:
                cur = self._conn.cursor()
                try:
                    cur.execute("SELECT set_config('app.current_user', %s, true)", (self._bridge_user,))
                    cur.execute("SET application_name = %s", (f"constructel_bridge:{self._bridge_user}",))
                finally:
                    cur.close()
            else:
                # Fallback: escape value for provider.executeSql() (no parameterized API)
                safe_user = self._bridge_user.replace("'", "''")
                provider.executeSql(
                    f"SELECT set_config('app.current_user', '{safe_user}', true)"
                )
                provider.executeSql(
                    f"SET application_name = 'constructel_bridge:{safe_user}'"
                )
            self._log(tr("hook.commit_tagged", user=self._bridge_user, layer=layer.name()))
        except (Exception, ) as exc:
            self._log(tr("hook.exec_error", error=exc), Qgis.Warning)  # noqa: broad-except — provider API may raise various types

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
    # Initialiser un projet vierge avec toutes les couches WYRE
    # =====================================================================

    def _on_init_project(self):
        """Ouvre le dialog de selection et initialise le projet WYRE."""
        if not self._connected:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Constructel Bridge",
                tr("conn.connect_first"),
            )
            return

        from .bridge_project_init import InitProjectDialog, init_project

        dlg = InitProjectDialog(self.iface.mainWindow())
        if dlg.exec_() != dlg.Accepted:
            return

        selected = dlg.selected_layers()
        if not selected - {"v_form_lists"}:
            return  # rien selectionne

        try:
            conn_params = {
                "host": DEFAULT_HOST,
                "port": DEFAULT_PORT,
                "dbname": DEFAULT_DBNAME,
                "user": DEFAULT_USER,
                "sslmode": DEFAULT_SSLMODE,
            }
            password = getattr(self, "_password", None) or ""

            count = init_project(
                conn_params, password, selected,
                add_basemap=dlg.want_basemap(),
                apply_styles=dlg.want_styles(),
                selected_basemaps=dlg.selected_basemaps(),
            )

            # Appliquer les traductions i18n
            from . import bridge_sketcher
            bridge_sketcher.apply_all_translations()

            # Installer les hooks d'edition
            self._hook_layers()

            self.iface.messageBar().pushMessage(
                "Constructel Bridge",
                tr("init.success", count=count),
                level=Qgis.Success,
                duration=5,
            )
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Constructel Bridge",
                tr("init.error", error=str(exc)),
            )
            import traceback
            self._log(traceback.format_exc(), Qgis.Critical)

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

    _PROJECT_SCHEMAS = ("wyre", "public")

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

        # Validate schema against whitelist to prevent SQL injection
        if schema not in self._PROJECT_SCHEMAS:
            self._log(f"Rejected invalid schema: {schema!r}", Qgis.Warning)
            return False
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

        # Nettoyer les authcfg des datasources et injecter user/password.
        # Meme logique known_identities que _fix_layer_credentials /
        # _strip_authcfg_from_dom (hotfix 2026-07-30, cf. leurs
        # docstrings) : preserver l'identite be existante plutot que de
        # tout basculer vers wyre, et ne jamais toucher un serveur tiers.
        original_xml = xml
        # wyre associe toujours "" (jamais le vrai mot de passe AD de la
        # session) : ce XML est round-trip via {schema}.qgis_projects,
        # une table PARTAGEE entre utilisateurs -- cf. C1 / incident de
        # securite qui a motive ce chantier.
        known_identities = {DEFAULT_USER: (DEFAULT_USER, "")}
        if BE_ENABLED:
            known_identities[BE_USER] = (BE_USER, _BE_PW)
        known_hosts = tuple(h for h in (DEFAULT_HOST, BE_HOST) if h)

        def _fix_datasource(m):
            """Callback pour re.sub: nettoie une balise <datasource>."""
            prefix, ds, suffix = m.group(1), m.group(2), m.group(3)
            if not any(h in ds for h in known_hosts):
                return m.group(0)
            # Regression round 3 corrigee : le strip global d'authcfg sur
            # tout le XML a ete retire au profit d'un traitement par
            # datasource, mais le re.sub sur `ds` avait ete oublie -- plus
            # aucun authcfg n'etait retire pour NOS datasources, cassant
            # l'objectif meme de cette fonction (cf. docstring).
            ds = re.sub(r"\bauthcfg=\w+", "", ds)
            user_match = re.search(r"\buser='([^']*)'", ds)
            current_user = user_match.group(1) if user_match else None
            target_user, target_password = known_identities.get(
                current_user, (DEFAULT_USER, "")
            )
            # CRITIQUE : meme fix que _strip_authcfg_from_dom -- _QUOTED
            # au lieu de [^']* pour ne pas laisser un fragment de mot de
            # passe (apres un \' echappe par QGIS) dans le XML round-trip
            # via {schema}.qgis_projects. target_user/target_password
            # echappes avant reinjection (_escape_pg_uri_value).
            ds = re.sub(r"\buser=" + _QUOTED, "", ds)
            ds = re.sub(r"\bpassword=" + _QUOTED, "", ds)
            ds += (
                f" user='{_escape_pg_uri_value(target_user)}'"
                f" password='{_escape_pg_uri_value(target_password)}'"
            )
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

        Cherche la table ``qgis_projects`` dans les schemas public et wyre.
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
