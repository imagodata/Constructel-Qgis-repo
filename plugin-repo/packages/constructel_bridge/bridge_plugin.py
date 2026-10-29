# -*- coding: utf-8 -*-
"""
Constructel Bridge - Plugin principal.

Responsabilites:
  1. Configurer la connexion PostgreSQL farois_ftth (role ftth_editor)
  2. Identifier l'utilisateur QGIS et l'enregistrer dans ref.users
  3. Positionner app.current_user sur chaque connexion pour tracer les editions
  4. Intercepter les commits de couche pour tagger l'utilisateur
"""

import os
from typing import Optional
from xml.sax.saxutils import escape as xml_escape, unescape as xml_unescape

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsAuthCertUtils,
    QgsAuthMethodConfig,
    QgsCredentials,
    QgsDataProvider,
    QgsDataSourceUri,
    QgsMessageLog,
    QgsPathResolver,
    QgsProject,
    QgsProjectBadLayerHandler,
    QgsSettings,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgisInterface, QgsMessageBarItem
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtNetwork import QSslCertificate
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
from .bridge_identity import (
    build_pgoptions,
    decode_password,
    derive_email,
    is_valid_audit_email,
    strip_app_user_option,
)
from .bridge_mtls import (
    MTLS_SETTINGS_KEYS,
    build_pgpass_line,
    pgpass_file_path,
    upsert_pgpass_entry,
    validate_client_certificate,
)
from .bridge_nominatif import (
    AUTH_MODE_NOMINAL,
    AUTH_MODE_SHARED,
    AUTH_REFUSED,
    LOGIN_DISABLED,
    NOMINAL_SETTINGS_KEYS,
    SCOPE_QUERY,
    ca_bundle_path,
    classify_auth_failure,
    datasource_param,
    embedded_ca_paths,
    force_datasource_sslmode,
    normalize_login,
    parse_session_scope,
    resolve_pg_login,
    rewrite_datasource_identity,
    rewrite_datasource_nominal,
    scope_kind,
    SCOPE_REFUSAL_PERIMETER,
    SCOPE_REFUSAL_RIGHT,
    scope_labels,
    scope_refusal_kind,
    secure_project_storage_uri,
    should_lock_layer,
    should_reprompt,
    strip_datasource_authcfg,
)

TAG = "Constructel Bridge"
AUTH_CFG_NAME = "constructel_bridge_pw"
AUTH_CFG_NAME_BE = "constructel_bridge_be_pw"
MTLS_AUTH_CFG_NAME = "constructel_bridge_mtls"

# Adresse mail de l'utilisateur posee dans PGOPTIONS (app.current_user) pour que
# l'audit Farois enregistre l'auteur des editions QGIS. Tracabilite seulement :
# adresse DECLAREE par le poste, jamais une preuve d'identite (spec 2026-10-15).
AUDIT_EMAIL_KEY = "constructel_bridge/audit_email"
AUDIT_EMAIL_SWITCH_KEY = "constructel_bridge/audit_email_pgoptions"

# Cle de settings ou est memorise l'ID de configuration Auth Manager, par
# connexion. `wyre` CONSERVE la cle historique : la changer orphaniserait
# les configurations Auth Manager deja stockees sur les postes existants.
_AUTH_CFG_ID_KEYS = {
    "wyre": "constructel_bridge/auth_cfg_id",
    "be": "constructel_bridge/auth_cfg_id_be",
    "ad": "constructel_bridge/auth_cfg_id_ad",
}
# `ad` (Bridge 1.8) : le mot de passe AD de la personne, conserve pour la
# sonde nominative du prochain demarrage MEME quand le poste est en repli
# (9i19s56 porte alors l'identifiant partage, chemin 1.7.3 exact). Jamais
# reference par une couche ; seule la sonde psycopg2 le lit.
AUTH_CFG_NAME_AD = "constructel_bridge_ad"
_AUTH_CFG_NAMES = {
    "wyre": AUTH_CFG_NAME,
    "be": AUTH_CFG_NAME_BE,
    "ad": AUTH_CFG_NAME_AD,
}

# Identifiants Auth Manager FIXES, identiques sur tous les postes : un projet
# enregistre avec authcfg=<id> s'ouvre partout ou le plugin a cree cette
# config, sans mot de passe en clair dans le .qgz. Ce sont les ids deja
# utilises par les projets existants (poste de reference). Depuis 1.8 le
# `username` de wyre/be est le login nominatif DU poste (spec §5.7.2).
_FIXED_AUTH_CFG_IDS = {
    "wyre": "9i19s56",
    "be": "07254s7",
    "ad": "nomin18",
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
    from .bridge_identity import parse_credentials_json
    with open(_CREDENTIALS_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return parse_credentials_json(raw)

_CREDS = _load_credentials()
_WYRE_CREDS = _CREDS.get("wyre", {})
_BE_CREDS = _CREDS.get("be", {})

DEFAULT_HOST = os.getenv("WYRE_DB_HOST", "") or _WYRE_CREDS["host"]
DEFAULT_PORT = int(os.getenv("WYRE_DB_PORT", str(_WYRE_CREDS["port"])))
DEFAULT_DBNAME = os.getenv("WYRE_DB_NAME", "") or _WYRE_CREDS["dbname"]
# Bridge 1.8 : l'identifiant PARTAGE (ftth_editor) n'est plus que le repli
# D7 de la transition. `user`/`password` deviennent optionnels dans
# credentials.json : absents (cloture 1.8.x), le repli est simplement
# indisponible -- jamais un KeyError qui empecherait le plugin de charger.
DEFAULT_USER = _WYRE_CREDS.get("user", "")
_DEFAULT_PW = decode_password(_WYRE_CREDS["password"]) if _WYRE_CREDS.get("password") else ""
SHARED_FALLBACK_AVAILABLE = bool(DEFAULT_USER and _DEFAULT_PW)
DEFAULT_SRID = _WYRE_CREDS.get("srid", 31370)
# Revue 29/10 (D-TLS-2) : sslmode de l'identifiant PARTAGE (repli D7,
# secours admin) = 1.7.x a l'identique (credentials.json, defaut require).
# Seule la session NOMINATIVE, qui transporte le mot de passe AD, est en
# verify-full obligatoire (spec 2026-10-26 §5.1/§5.5) -- NOMINAL_SSLMODE.
DEFAULT_SSLMODE = _WYRE_CREDS.get("sslmode", "require")
NOMINAL_SSLMODE = "verify-full"
# Revue 29/10 (I2) : delai maximal (s) de la sonde nominative -- annuaire AD
# lent ou en panne -> repli au lieu d'un QGIS fige.
NOMINAL_CONNECT_TIMEOUT = 10
PG_SERVICE_NAME = _WYRE_CREDS.get("service_name", "constructel_bridge")
EMAIL_DOMAIN = _WYRE_CREDS.get("email_domain", "constructel.be")

# Connexion `be` (bureau d'etudes) — schema public uniquement. Depuis 1.8 :
# login nominatif LDAPS (meme compte AD que `wyre`, authcfg 07254s7) ; le
# bloc `be` de credentials.json ne porte plus que host/port/dbname. Un
# ancien bloc avec user/password (1.5 -> 1.7) reste lu : identifiant
# partage disponible pour reconnaitre les projets `be` historiques.
# Absente des credentials.json anterieurs a la v1.5.0 : toutes les
# constantes retombent alors sur des valeurs vides et BE_ENABLED est False.
BE_HOST = os.getenv("BE_DB_HOST", "") or _BE_CREDS.get("host", "")
BE_PORT = int(os.getenv("BE_DB_PORT", str(_BE_CREDS.get("port", 5432))))
BE_DBNAME = os.getenv("BE_DB_NAME", "") or _BE_CREDS.get("dbname", "")
BE_USER = _BE_CREDS.get("user", "")
_BE_PW = decode_password(_BE_CREDS["password"]) if _BE_CREDS.get("password") else ""
BE_SSLMODE = _BE_CREDS.get("sslmode", "require")  # identifiant partage be (1.7.x)

# `wyre` et `be` pointent sur le MEME host et la MEME base : dans un realm
# QgsCredentials, seul l'utilisateur les distingue (cf.
# _precache_pg_credentials). Un bloc `be` qui reutiliserait
# l'utilisateur partage de `wyre` rendrait la resolution ambigue et
# casserait l'authentification de `wyre` — on refuse alors d'activer la
# connexion.
BE_ENABLED = (
    bool(BE_HOST and BE_DBNAME)
    and not (BE_USER and BE_USER == DEFAULT_USER)
)
BE_SHARED_AVAILABLE = BE_ENABLED and bool(BE_USER and _BE_PW)

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
    if SHARED_FALLBACK_AVAILABLE:
        for realm in (
            f"dbname='{DEFAULT_DBNAME}' host={DEFAULT_HOST} port={DEFAULT_PORT}",
            f"dbname='{DEFAULT_DBNAME}' host={DEFAULT_HOST} port={DEFAULT_PORT} sslmode={DEFAULT_SSLMODE}",
            f"dbname='{DEFAULT_DBNAME}' host={DEFAULT_HOST}",
            DEFAULT_HOST,
        ):
            creds.put(realm, DEFAULT_USER, _DEFAULT_PW)

    if not BE_SHARED_AVAILABLE:
        return
    # `be` partage host + base avec `wyre` : SEULES les variantes de realm
    # qui portent user='...' sont pre-cachees. Pre-cacher une variante sans
    # utilisateur ecraserait le cache de `wyre` avec le mot de passe du
    # bureau d'etudes et casserait la connexion principale.
    for realm in (
        f"dbname='{BE_DBNAME}' host={BE_HOST} port={BE_PORT} user='{BE_USER}'",
        f"dbname='{BE_DBNAME}' host={BE_HOST} port={BE_PORT} sslmode={BE_SSLMODE} user='{BE_USER}'",
    ):
        creds.put(realm, BE_USER, _BE_PW)


def _fixed_authcfg_for_user(user: str) -> str:
    """Id d'authcfg FIXE de *user*, si cette config existe dans l'Auth Manager local.

    Retourne "" si l'utilisateur n'a pas d'id fixe, ou si la config n'existe
    pas (encore) sur ce poste : l'appelant retombe alors sur son comportement
    historique (identifiants en clair).
    """
    from .bridge_identity import fixed_authcfg_id_for_user

    cfg_id = fixed_authcfg_id_for_user(
        user,
        wyre_user=DEFAULT_USER,
        wyre_authcfg_id=_FIXED_AUTH_CFG_IDS["wyre"],
        be_enabled=BE_ENABLED,
        be_user=BE_USER,
        be_authcfg_id=_FIXED_AUTH_CFG_IDS["be"],
    )
    if not cfg_id:
        return ""
    try:
        return cfg_id if cfg_id in QgsApplication.authManager().configIds() else ""
    except Exception:
        return ""


def _check_fixed_authcfgs() -> str:
    """Controle au demarrage : les configs Auth Manager du plugin portent l'id FIXE.

    Pour wyre et be (be seulement si activee) :
      * si l'id fixe est absent mais qu'une ancienne config du plugin existe
        (id aleatoire), son mot de passe est repris dans une config a id
        fixe ;
      * les anciennes configs du plugin (meme nom, autre id) ne sont
        supprimees QU'APRES presence de l'id fixe -- jamais de perte de
        mot de passe.
    Ne provoque pas de dialogue de mot de passe maitre quand `be` est
    desactivee. Retourne un resume pour le journal ; ne leve jamais.
    """
    from .bridge_identity import stale_config_ids

    try:
        auth_mgr = QgsApplication.authManager()
        if auth_mgr.isDisabled():
            return "Auth check: Auth Manager desactive"
        if not BE_ENABLED and not auth_mgr.masterPasswordIsSet():
            return "Auth check: mot de passe maitre non defini, controle reporte"
        if not _ensure_auth_manager_ready():
            return "Auth check: Auth Manager indisponible"
        parts = []
        for conn in ("wyre", "be"):
            if conn == "be" and not BE_ENABLED:
                continue
            fixed_id = _FIXED_AUTH_CFG_IDS[conn]
            name = _AUTH_CFG_NAMES[conn]
            configs = {
                cid: cfg.name()
                for cid, cfg in auth_mgr.availableAuthMethodConfigs().items()
            }
            stale = stale_config_ids(configs, name, fixed_id)
            if fixed_id not in auth_mgr.configIds() and stale:
                old = QgsAuthMethodConfig()
                auth_mgr.loadAuthenticationConfig(stale[0], old, True)
                old_pw = old.config("password", "")
                if old_pw:
                    _store_password_encrypted(old_pw, conn)
            removed = 0
            if fixed_id in auth_mgr.configIds():
                for cid in stale:
                    if auth_mgr.removeAuthenticationConfig(cid):
                        removed += 1
                QgsSettings().setValue(_AUTH_CFG_ID_KEYS[conn], fixed_id)
                parts.append(f"{conn} ok ({fixed_id})" + (f", {removed} ancienne(s) supprimee(s)" if removed else ""))
            else:
                parts.append(f"{conn} id fixe {fixed_id} absent (cree a la connexion)")
        return "Auth check: " + " | ".join(parts)
    except Exception as exc:
        return f"Auth check en echec: {exc}"


# Revue 29/10 (M2) : un mot de passe maitre annule ou refuse n'est demande
# qu'UNE fois par sequence de connexion (4 a 5 invites avant : be, sonde,
# mot de passe AD, wyre, be). Remis a zero par chaque action explicite de
# l'utilisateur (Connecter, Reessayer mon acces nominatif).
_MASTER_PASSWORD_DECLINED = False


def _ensure_auth_manager_ready() -> bool:
    """Ensure the Auth Manager is initialized and master password is set.

    Prompts the user to set a master password if not yet configured --
    at most once until _reset_master_password_prompt() (M2).
    Returns True if Auth Manager is ready.
    """
    global _MASTER_PASSWORD_DECLINED
    auth_mgr = QgsApplication.authManager()
    if auth_mgr.isDisabled():
        return False
    if auth_mgr.masterPasswordIsSet():
        return True
    if _MASTER_PASSWORD_DECLINED:
        return False
    # This will prompt the user to enter/create a master password
    if auth_mgr.setMasterPassword(True):
        return True
    _MASTER_PASSWORD_DECLINED = True
    return False


def _reset_master_password_prompt() -> None:
    """Action explicite de l'utilisateur : l'invite du mot de passe maitre
    peut de nouveau s'afficher (une fois)."""
    global _MASTER_PASSWORD_DECLINED
    _MASTER_PASSWORD_DECLINED = False


class _LocalSetupError(Exception):
    """Echec local apres une connexion nominative reussie (config Auth
    Manager non ecrite) : la session nominative serait inutilisable par les
    couches -> repli partage (revue 29/10, M3)."""


def _stored(answer) -> bool:
    """Result of QgsAuthManager.storeAuthenticationConfig().

    QGIS (3.28 -> 4.x, SIP_INOUT) returns (ok, config): the tuple itself is
    always truthy, only its first item tells whether the write succeeded.
    """
    return bool(answer[0]) if isinstance(answer, tuple) else bool(answer)


def _store_password_encrypted(password: str, conn: str = "wyre", username: str | None = None) -> bool:
    """Store the password in QGIS Auth Manager (encrypted SQLite DB).

    *conn* est une cle de ``_PG_CONNECTIONS`` : chaque connexion a sa
    propre configuration Auth Manager et sa propre cle de settings, sinon
    `be` ecraserait celle de `wyre` (et inversement).

    *username* (Bridge 1.8) : login PostgreSQL nominatif porte par la
    config a id FIXE (9i19s56 / 07254s7) -- l'id ne change pas, seul le
    `username` varie d'un poste a l'autre : un projet `authcfg=9i19s56`
    s'ouvre partout avec les identifiants DU poste (spec §5.7.2). Absent :
    identifiant partage historique de la connexion.

    Returns True on success.
    """
    if not _ensure_auth_manager_ready():
        QgsMessageLog.logMessage(
            "Auth Manager not available, cannot store encrypted password.",
            TAG, level=Qgis.MessageLevel.Warning,
        )
        return False
    auth_mgr = QgsApplication.authManager()
    settings_key = _AUTH_CFG_ID_KEYS[conn]
    user = username or _PG_CONNECTIONS.get(conn, {}).get("user", "")
    if conn in ("wyre", "be") and user and user not in (DEFAULT_USER, BE_USER):
        # I-4 : pose AVANT l'ecriture (une ecriture a moitie faite compte).
        QgsSettings().setValue(AD_IDENTITY_KEY, True)
    # ID FIXE (identique sur tous les postes) : on vise TOUJOURS cette
    # config. L'ancienne config a id aleatoire d'un poste deja installe
    # n'est pas supprimee (orpheline, inoffensive).
    fixed_id = _FIXED_AUTH_CFG_IDS.get(conn, "")
    if fixed_id:
        cfg_id = fixed_id
    else:
        cfg_id = QgsSettings().value(settings_key, "")
    if cfg_id and cfg_id in auth_mgr.configIds():
        # Update existing config
        config = QgsAuthMethodConfig()
        auth_mgr.loadAuthenticationConfig(cfg_id, config, True)
        config.setConfig("username", user)
        config.setConfig("password", password)
        ok = auth_mgr.updateAuthenticationConfig(config)
        if ok:
            QgsSettings().setValue(settings_key, cfg_id)
    else:
        # Create new config
        config = QgsAuthMethodConfig("Basic")
        if fixed_id:
            config.setId(fixed_id)
        config.setName(_AUTH_CFG_NAMES[conn])
        config.setConfig("username", user)
        config.setConfig("password", password)
        ok = _stored(auth_mgr.storeAuthenticationConfig(config))
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


# Revue 2 (I-4) : « 9i19s56 / 07254s7 peuvent porter l'identite AD (login +
# mot de passe Windows) ». Pose AVANT toute ecriture nominative de ces
# configs, leve SEULEMENT quand plus aucune ne la porte (reecriture
# partagee reussie, ou config retiree). Lu sans mot de passe maitre ni
# connexion : il ne depend ni de _auth_mode ni d'une lecture de config.
AD_IDENTITY_KEY = "constructel_bridge/ad_identity_in_layer_configs"


def _ad_identity_flag() -> bool:
    value = QgsSettings().value(AD_IDENTITY_KEY, None)
    if value is None:
        # Poste passe par une version de travail sans drapeau : le mode
        # memorise dit ce que la derniere session a laisse dans 9i19s56.
        return (QgsSettings().value(NOMINAL_SETTINGS_KEYS["auth_mode"], "") or "") == AUTH_MODE_NOMINAL
    return str(value).lower() in ("true", "1")


def _refresh_ad_identity_flag() -> bool:
    """Leve le drapeau si chaque config fixe est absente ou porte
    l'identifiant partage ; le maintient sinon (dont config illisible :
    mot de passe maitre indisponible). Retourne l'etat du drapeau."""
    try:
        ids = QgsApplication.authManager().configIds()
        for conn, shared_user in (("wyre", DEFAULT_USER), ("be", BE_USER)):
            if _FIXED_AUTH_CFG_IDS[conn] not in ids:
                continue
            login = _stored_login(conn)
            if not login or login != shared_user:
                return _ad_identity_flag()
        QgsSettings().setValue(AD_IDENTITY_KEY, False)
        return False
    except Exception:  # noqa: BLE001 -- lecture best-effort : drapeau maintenu
        return _ad_identity_flag()


def _retrieve_password_encrypted(conn: str = "wyre") -> str:
    """Retrieve the password from QGIS Auth Manager.

    Returns the password string, or empty string if not found.
    """
    if not _ensure_auth_manager_ready():
        return ""
    auth_mgr = QgsApplication.authManager()
    fixed_id = _FIXED_AUTH_CFG_IDS.get(conn, "")
    if fixed_id and fixed_id in auth_mgr.configIds():
        cfg_id = fixed_id
    else:
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


def _stored_login(conn: str = "wyre") -> str:
    """Login PostgreSQL porte par la config Auth Manager a id FIXE de *conn*
    ("" si absente ou Auth Manager indisponible). Sert a distinguer un
    mot de passe nominatif deja saisi d'un mot de passe partage herite de
    1.7.x (username=ftth_editor) : ne jamais sonder un login avec le mot de
    passe d'un autre."""
    try:
        if not _ensure_auth_manager_ready():
            return ""
        auth_mgr = QgsApplication.authManager()
        fixed_id = _FIXED_AUTH_CFG_IDS.get(conn, "")
        if not fixed_id or fixed_id not in auth_mgr.configIds():
            return ""
        config = QgsAuthMethodConfig()
        auth_mgr.loadAuthenticationConfig(fixed_id, config, True)
        return config.config("username", "") or ""
    except Exception:  # noqa: BLE001 -- lecture best-effort
        return ""


def _ensure_qgis_trusted_cas() -> bool:
    """Importe les CA embarquees (CA Farois DB + racine AD Constructel) dans
    la base d'authentification QGIS, avec la politique « Trusted ».

    Revue 29/10 (D-TLS-1) : pour une couche authcfg (methode Basic) en
    sslmode verify-*, QGIS REMPLACE tout sslrootcert= par un fichier
    temporaire contenant QgsAuthManager.trustedCaCerts() (magasin systeme +
    CA de la base d'authentification ; QgsAuthBasicMethod::
    updateDataSourceUriItems, 3.28 -> 4.x). Un root.crt sur le poste n'y
    sert donc a rien : sans cet import, toute couche nominative echouerait
    (« certificate verify failed ») alors que la sonde psycopg2 reussit.

    Idempotent (certificat deja present et deja « Trusted » : rien n'est
    ecrit). Ni storeCertAuthority ni storeCertTrustPolicy n'exigent le mot
    de passe maitre (verifie dans le source QGIS 3.28 et master). Echec ->
    False + journal Critical : le nominatif est alors impossible, l'appelant
    passe en repli partage (jamais de poste bloque)."""
    try:
        auth_mgr = QgsApplication.authManager()
        if auth_mgr.isDisabled():
            raise RuntimeError("Auth Manager desactive")
        trusted = QgsAuthCertUtils.CertTrustPolicy.Trusted
        changed = False
        for path in embedded_ca_paths(os.path.dirname(__file__)):
            with open(path, "rb") as f:
                certs = QSslCertificate.fromData(f.read())
            if len(certs) != 1 or certs[0].isNull():
                raise ValueError(f"{path.name} : un certificat attendu, {len(certs)} lu(s)")
            cert = certs[0]
            # certAuthority(id) plutot que existsCertAuthority() : ce dernier
            # interroge une colonne inexistante en 3.28 (toujours False).
            if auth_mgr.certAuthority(QgsAuthCertUtils.shaHexForCert(cert)).isNull():
                if not auth_mgr.storeCertAuthority(cert):
                    raise RuntimeError(f"storeCertAuthority a echoue ({path.name})")
                changed = True
            if auth_mgr.certTrustPolicy(cert) != trusted:
                if not auth_mgr.storeCertTrustPolicy(cert, trusted):
                    raise RuntimeError(f"storeCertTrustPolicy a echoue ({path.name})")
                changed = True
        if changed:
            # trustedCaCerts() lit les caches CA et politiques : sans
            # reconstruction, l'import ne vaudrait qu'au prochain demarrage.
            auth_mgr.rebuildCaCertsCache()
            auth_mgr.rebuildCertTrustCache()
            auth_mgr.rebuildTrustedCaCertsCache()
        return True
    except Exception as exc:  # noqa: BLE001 -- jamais d'exception vers la connexion
        QgsMessageLog.logMessage(
            f"{tr('nominal.ca_import_failed')} ({exc})",
            TAG, level=Qgis.MessageLevel.Critical,
        )
        return False


def _remove_stored_password(conn: str = "wyre"):
    """Remove the stored password from Auth Manager and legacy settings."""
    auth_mgr = QgsApplication.authManager()
    settings_key = _AUTH_CFG_ID_KEYS[conn]
    cfg_id = QgsSettings().value(settings_key, "")
    if cfg_id and cfg_id in auth_mgr.configIds():
        auth_mgr.removeAuthenticationConfig(cfg_id)
    fixed_id = _FIXED_AUTH_CFG_IDS.get(conn, "")
    if fixed_id and fixed_id != cfg_id and fixed_id in auth_mgr.configIds():
        auth_mgr.removeAuthenticationConfig(fixed_id)
    QgsSettings().remove(settings_key)
    QgsSettings().remove("constructel_bridge/password")


def _store_pki_authcfg() -> str:
    """Create or update the ONE shared PKI-Paths auth config for mTLS.

    Cert/key paths come from the mTLS settings (single source of truth).
    The config carries certificate and key ONLY, never a password (QGIS
    bug #58179). Mirrors _store_password_encrypted's structure exactly:
    readiness guard, configIds() membership check, load + update vs create
    (never both — a failed update must not orphan a duplicate).

    Returns the config id, or "" when the manager is unavailable or the
    write fails (callers abort loudly).
    """
    if not _ensure_auth_manager_ready():
        QgsMessageLog.logMessage(
            "Auth Manager not available, cannot store PKI-Paths config.",
            TAG, level=Qgis.MessageLevel.Warning,
        )
        return ""
    auth_mgr = QgsApplication.authManager()
    settings_key = MTLS_SETTINGS_KEYS["authcfg_id"]
    cert_path = QgsSettings().value(MTLS_SETTINGS_KEYS["cert_path"], "")
    key_path = QgsSettings().value(MTLS_SETTINGS_KEYS["key_path"], "")
    cfg_id = QgsSettings().value(settings_key, "")
    if cfg_id and cfg_id in auth_mgr.configIds():
        # Update existing config
        config = QgsAuthMethodConfig()
        auth_mgr.loadAuthenticationConfig(cfg_id, config, True)
        config.setConfig("certpath", cert_path)
        config.setConfig("keypath", key_path)
        if auth_mgr.updateAuthenticationConfig(config):
            return cfg_id
        return ""
    # Create new config
    config = QgsAuthMethodConfig("PKI-Paths")
    config.setName(MTLS_AUTH_CFG_NAME)
    config.setConfig("certpath", cert_path)
    config.setConfig("keypath", key_path)
    if _stored(auth_mgr.storeAuthenticationConfig(config)):
        QgsSettings().setValue(settings_key, config.id())
        return config.id()
    return ""


def _remove_pki_authcfg() -> None:
    """Remove the shared PKI-Paths auth config and its settings id."""
    auth_mgr = QgsApplication.authManager()
    cfg_id = QgsSettings().value(MTLS_SETTINGS_KEYS["authcfg_id"], "")
    if cfg_id and cfg_id in auth_mgr.configIds():
        auth_mgr.removeAuthenticationConfig(cfg_id)
    QgsSettings().remove(MTLS_SETTINGS_KEYS["authcfg_id"])


def _mtls_message(key: str, **kwargs) -> str:
    """Translate an mtls.* diagnostic key for the operator.

    T3 wires the diagnostics; T4 provides the real translated texts. Until
    then an unknown key must degrade to the key itself — never raise inside
    the connect flow. Returns the key unchanged when `tr()` raises, returns
    a non-string, or returns an empty string.
    """
    try:
        text = tr(key, **kwargs)
    except Exception:
        return key
    if not isinstance(text, str) or not text:
        return key
    return text


def _ensure_pgpass_entry(pgpass_path, host: str, port: int, dbname: str,
                         user: str, password: str) -> bool:
    """Write our password line into the libpq pgpass file.

    Creates the file (and missing parent directories, e.g. %APPDATA%
    postgresql/ on first use) when absent, preserves every other line via
    upsert_pgpass_entry(), and enforces 0o600 — libpq silently IGNORES a
    group/other-readable pgpass on POSIX, so a lax file would degrade to
    password prompts without a word.

    Returns False when the file cannot be read, written, or chmod'ed
    (callers abort loudly with the mtls.pgpass_unwritable diagnostic).
    os.chmod(0o600) is also harmless on Windows (no write bit removed, so
    no read-only flag is set); libpq ignores permissions there anyway.
    """
    new_line = build_pgpass_line(host, port, dbname, user, password)
    parent = os.path.dirname(os.path.abspath(str(pgpass_path)))
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError:
        return False
    try:
        with open(pgpass_path, "r", encoding="utf-8") as f:
            existing = f.read()
    except FileNotFoundError:
        existing = ""
    except OSError:
        return False
    try:
        text = upsert_pgpass_entry(existing, new_line)
    except ValueError:
        return False
    try:
        with open(pgpass_path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(pgpass_path, 0o600)
    except OSError:
        return False
    return True


def _mtls_active() -> tuple[bool, str | None]:
    """Whether mTLS is engaged for GIS connections.

    (True, None) iff the kill-switch is on AND all three cert paths are
    configured AND the certificate validates. (False, reason) otherwise:
    "disabled" (flag off), "not_configured" (flag on, paths missing), or a
    CertValidationResult reason (configured but invalid — callers must abort
    loudly, never fall back to legacy silently).
    """
    if not QgsSettings().value(MTLS_SETTINGS_KEYS["enabled"], True, type=bool):
        return (False, "disabled")
    cert = QgsSettings().value(MTLS_SETTINGS_KEYS["cert_path"], "")
    key = QgsSettings().value(MTLS_SETTINGS_KEYS["key_path"], "")
    ca = QgsSettings().value(MTLS_SETTINGS_KEYS["ca_path"], "")
    if not cert or not key or not ca:
        return (False, "not_configured")
    result = validate_client_certificate(cert, key, ca)
    if not result.ok:
        return (False, result.reason)
    return (True, None)


_SSL_MODE_ENUMS = {
    "disable": "SslDisable",
    "allow": "SslAllow",
    "prefer": "SslPrefer",
    "require": "SslRequire",
    "verify-ca": "SslVerifyCa",
    "verify-full": "SslVerifyFull",
}


def _ssl_mode_enum(mode: str):
    """QgsDataSourceUri.SslMode correspondant a un sslmode libpq."""
    return getattr(QgsDataSourceUri.SslMode, _SSL_MODE_ENUMS.get(mode, "SslPrefer"))


# Revue 2 (I-1/I-2) : marqueur du verrou D2 pose par le plugin, porte par la
# couche elle-meme. Une lecture seule sans ce marqueur appartient a la
# personne (ou a un style) et n'est jamais levee par le plugin.
SCOPE_LOCK_PROPERTY = "constructel_bridge/scope_lock"


def _has_scope_lock(layer) -> bool:
    return bool(layer.customProperty(SCOPE_LOCK_PROPERTY, ""))


def _get_plugin_version() -> str:
    """Read current plugin version from metadata.txt."""
    meta_path = os.path.join(os.path.dirname(__file__), "metadata.txt")
    with open(meta_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("version="):
                return line.strip().split("=", 1)[1]
    return ""


PLUGIN_VERSION = _get_plugin_version()


def _clear_audit_identity(forget_email: bool = True):
    """Retire app.current_user de PGOPTIONS et oublie l'adresse en cache.

    *forget_email* False (session nominative, revue 29/10 M9) : l'adresse
    memorisee est conservee -- le plugin Historique (farois_audit_rollback)
    la lit pour pre-remplir sa connexion ; seul le GUC declaratif disparait.
    """
    cleaned = strip_app_user_option(os.environ.get("PGOPTIONS"))
    if cleaned is None:
        os.environ.pop("PGOPTIONS", None)
    else:
        os.environ["PGOPTIONS"] = cleaned
    if forget_email:
        QgsSettings().remove(AUDIT_EMAIL_KEY)


def _apply_audit_identity(email, log) -> bool:
    """Pose PGOPTIONS pour que toute NOUVELLE connexion libpq du processus
    QGIS (fournisseur PostgreSQL compris) porte app.current_user=<email>.

    Les connexions deja ouvertes ne sont pas modifiees (pool QGIS). Ne bloque
    jamais et ne leve jamais : interrupteur a faux -> rien n'est touche ;
    adresse absente ou invalide -> l'adresse precedente est retiree (pas
    d'attribution a un autre utilisateur) ; la fonction renvoie False.
    """
    try:
        if not QgsSettings().value(AUDIT_EMAIL_SWITCH_KEY, True, type=bool):
            log("Adresse d'audit desactivee (constructel_bridge/audit_email_pgoptions = false)", Qgis.MessageLevel.Info)
            return False
        if not is_valid_audit_email(email):
            _clear_audit_identity()
            log(f"Adresse d'audit absente ou invalide ({email!r}) : editions QGIS non attribuees", Qgis.MessageLevel.Warning)
            return False
        os.environ["PGOPTIONS"] = build_pgoptions(os.environ.get("PGOPTIONS"), email)
        QgsSettings().setValue(AUDIT_EMAIL_KEY, email)
        log(f"Adresse d'audit posee pour les nouvelles connexions PostgreSQL : {email}", Qgis.MessageLevel.Info)
        return True
    except Exception as exc:  # noqa: BLE001 -- ne jamais empecher initGui/_connect
        log(f"Adresse d'audit non posee (erreur inattendue) : {exc}", Qgis.MessageLevel.Warning)
        return False


def _apply_cached_audit_identity(log) -> bool:
    """Au demarrage, avant tout chargement de couche : reutilise l'adresse
    memorisee lors de la derniere connexion Bridge reussie. Ne leve jamais."""
    try:
        cached = QgsSettings().value(AUDIT_EMAIL_KEY, "")
    except Exception as exc:  # noqa: BLE001 -- ne jamais empecher initGui
        log(f"Adresse d'audit en cache illisible : {exc}", Qgis.MessageLevel.Warning)
        return False
    if not cached:
        return False
    return _apply_audit_identity(cached, log)


class ConstructelBridgePlugin:
    """Plugin QGIS — point d'entree."""

    def __init__(self, iface: QgisInterface):
        self.iface = iface
        self._actions: list[QAction] = []
        self._bridge_user: Optional[str] = None
        self._bridge_user_id: Optional[str] = None
        self._bridge_user_email: Optional[str] = None
        self._conn = None
        self._connected = False
        self._layer_hooks_installed = False
        # Bridge 1.8 : mode d'authentification de la session courante
        # ("nominal" | "shared"), login PostgreSQL nominatif, perimetre.
        self._auth_mode = ""
        self._pg_login = ""
        self._scope = None
        self._scope_names = ({}, {})
        self._last_connect_error = None
        # Revue 29/10 (I6) : _password = mot de passe PARTAGE seulement (lu
        # par les chemins 1.7.x) ; le mot de passe AD de la session
        # nominative n'est lu que par _init_conn_params (styles).
        self._password = None
        self._ad_password = None
        # Revue 29/10 (I13/I9) : connexion de demarrage differee ; dialogues,
        # assistant d'accueil et bandeau seulement une fois l'interface prete.
        self._startup_state = "idle"  # "idle" | "pending" | "done" | "cancelled"
        self._ui_ready = False
        self._pending_prompt = None  # None | "first" | "reprompt"
        self._pending_login = ""
        self._pending_onboarding = None
        self._banner = None  # (motif, login) du bandeau de repli D7
        self._banner_item = None
        self._action_retry = None
        # Revue 29/10 (M6) : slots raiseError par id de couche. Le verrou
        # D2, lui, est marque SUR la couche (SCOPE_LOCK_PROPERTY).
        self._layer_error_slots = {}

    # =====================================================================
    # QGIS Plugin lifecycle
    # =====================================================================

    def initGui(self):
        """Appele par QGIS au chargement du plugin."""
        # Avant tout chargement de couche (projet ouvert au demarrage compris) :
        # les connexions PostgreSQL ouvertes ensuite porteront l'adresse d'audit.
        _apply_cached_audit_identity(self._log)
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

        # Bridge 1.8 : nouvelle sonde nominative a la demande (poste en repli
        # D7 active entre-temps par un admin, mot de passe Windows change).
        action_retry = QAction(theme("/mActionRefresh.svg"), tr("menu.retry_nominal"), parent)
        action_retry.triggered.connect(self._on_retry_nominal)
        self._actions.append(action_retry)
        self._action_retry = action_retry

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
        self._toolbar_menu.addAction(action_retry)
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
        self._tool_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
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
                f"External services setup failed: {exc}", TAG, level=Qgis.MessageLevel.Warning,
            )

        # Pre-provisionner la dependance pip `extract-msg` utilisee par le
        # script Processing de geocodage .msg (diffuse via Resource Sharing).
        # Best-effort: ne doit jamais interrompre le chargement du plugin.
        try:
            self._ensure_extract_msg_available()
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"extract-msg pre-provisioning failed: {exc}", TAG, level=Qgis.MessageLevel.Warning,
            )

        # Revue 29/10 (M13) : le pre-cache QgsCredentials de l'identifiant
        # partage n'est plus pose ici mais a l'ouverture d'une session
        # PARTAGEE (_connect) : en nominatif, une couche sans authcfg ne doit
        # pas se connecter silencieusement en ftth_editor.
        #
        # Revue 29/10 (I13) : le controle des configs Auth Manager et la
        # connexion `be` partagee sont faits par la phase silencieuse du
        # demarrage (_startup_silent), plus dans initGui.

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

        # Revue 29/10 (M8) : toute couche ajoutee au projet courant (Bridge
        # ou non, navigateur compris) suit le perimetre de la session.
        QgsProject.instance().layersAdded.connect(self._on_layers_added_scope)

        # D-TLS-2 : les projets 1.7.x et ceux enregistres en mode partage
        # portent sslmode=require avec authcfg=9i19s56. Quand cette config
        # porte le mot de passe AD, QGIS ouvrirait leurs couches en require
        # (serveur non verifie) AVANT _fix_layer_credentials : le
        # preprocesseur force verify-full a la lecture, avant toute connexion.
        self._path_preprocessor_id = QgsPathResolver.setPathPreprocessor(
            self._nominal_source_preprocessor
        )
        # Revue 2 (I-8) : URI postgresql:// des projets recents (sans reseau).
        try:
            self._secure_recent_projects()
        except Exception as exc:  # noqa: BLE001 -- jamais bloquant
            self._log(f"Projets recents non securises : {exc}", Qgis.MessageLevel.Warning)

        # Auto-connexion silencieuse au demarrage: etablit uniquement la
        # connexion DB et l'enregistrement utilisateur, sans toucher au
        # projet (pas de fix credentials, hooks, etc.) pour eviter de
        # rendre le projet vide "dirty" et le dialogue "Enregistrer".
        # Revue 29/10 (I13) : differee, jamais dans initGui.
        self._schedule_startup_connection()

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
        try:
            QgsProject.instance().layersAdded.disconnect(self._on_layers_added_scope)
        except TypeError:
            pass
        # I8 : deconnexion -> plus aucun verrou pose par le plugin.
        self._release_scope_locks()
        if getattr(self, "_path_preprocessor_id", None):
            QgsPathResolver.removePathPreprocessor(self._path_preprocessor_id)
            self._path_preprocessor_id = None
        self._cancel_startup_connection()
        self._remove_banner()
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
        # Filet de securite (I13) : la phase silencieuse du demarrage a
        # normalement deja tourne a layerLoaded(0, n), avant les couches.
        if self._startup_state == "pending":
            self._startup_silent()
        try:
            self._secure_current_project_uri()
        except Exception as exc:  # noqa: BLE001 -- jamais bloquant
            self._log(f"URI du projet non securisee : {exc}", Qgis.MessageLevel.Warning)
        # Toujours corriger les credentials (utilise le mot de passe par
        # defaut si pas encore connecte — suffit pour reparer les authcfg).
        try:
            self._fix_layer_credentials()
        except Exception as exc:
            self._log(f"Fix layer credentials failed: {exc}", Qgis.MessageLevel.Warning)

        # Volet D2 : lecture seule selon le perimetre, projet Bridge ou non
        # (toute couche de nos serveurs est concernee).
        try:
            self._apply_scope_to_layers()
        except Exception as exc:
            self._log(f"Scope lock failed: {exc}", Qgis.MessageLevel.Warning)

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
            self._log(f"Hook install failed: {exc}", Qgis.MessageLevel.Warning)

        try:
            from .bridge_project_init import ensure_relations
            ensure_relations()
        except Exception as exc:
            self._log(f"Relations recreate failed: {exc}", Qgis.MessageLevel.Warning)

        try:
            bridge_sketcher.apply_all_translations()
        except Exception as exc:
            self._log(f"i18n apply failed: {exc}", Qgis.MessageLevel.Warning)

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
            self._log(f"Strip authcfg from DOM failed: {exc}", Qgis.MessageLevel.Warning)
        try:
            self._strip_scope_locks_from_dom(doc)
        except Exception as exc:
            self._log(f"Strip read-only locks from DOM failed: {exc}", Qgis.MessageLevel.Warning)

    def _strip_scope_locks_from_dom(self, doc):
        """Revue 29/10 (I8) : la lecture seule posee par le plugin depend de
        la session du poste, elle ne doit pas etre ecrite dans le projet
        (readOnly="1" sur <maplayer>, relu tel quel par QGIS). Seules les
        couches portant notre marqueur sont touchees (revue 2, I-1) : une
        lecture seule posee par la personne est ecrite telle quelle. Le
        marqueur, lui, reste dans le projet : a la reouverture, la couche
        est reverrouillee ou liberee selon la session."""
        project = QgsProject.instance()
        layers = doc.elementsByTagName("maplayer")
        for i in range(layers.count()):
            elem = layers.at(i).toElement()
            layer = project.mapLayer(elem.firstChildElement("id").text())
            if layer is not None and _has_scope_lock(layer):
                elem.setAttribute("readOnly", "0")

    def _strip_authcfg_from_dom(self, doc):
        """Parcourt le DOM du projet et retire les authcfg des datasources PG.

        Miroir cote ECRITURE de _fix_layer_credentials (cote lecture) :
        meme raisonnement known_identities (preserver l'identite be plutot
        que tout basculer vers wyre) et meme garde d'hote (ne jamais
        injecter nos identifiants dans la datasource d'un serveur tiers).
        Corrige au passage un bug de l'ancienne version : le test
        `f"user='{DEFAULT_USER}'" not in ds` ne detectait pas un user=
        EXISTANT different (ex. bureau_etudes), ce qui ajoutait un second
        attribut user= en double dans la datasource au lieu de remplacer
        le premier.
        """
        password = getattr(self, "_password", None) or _DEFAULT_PW
        known_identities = {DEFAULT_USER: (DEFAULT_USER, password)}
        if BE_ENABLED and BE_USER and _BE_PW:
            known_identities[BE_USER] = (BE_USER, _BE_PW)
        nominal = self._auth_mode == AUTH_MODE_NOMINAL and bool(self._pg_login)
        wyre_fixed = _FIXED_AUTH_CFG_IDS["wyre"]
        be_fixed = _FIXED_AUTH_CFG_IDS["be"]
        known_hosts = {h for h in (DEFAULT_HOST, BE_HOST) if h}

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
            if nominal:
                # Session nominative : TOUTE datasource de nos serveurs est
                # ecrite user='<login>' authcfg=<id fixe> sslmode=verify-full,
                # mot de passe en clair compris (spec §5.7.7).
                if datasource_param(ds, "host") not in known_hosts:
                    continue
                is_be = BE_ENABLED and (
                    datasource_param(ds, "authcfg") == be_fixed
                    or (bool(BE_USER) and datasource_param(ds, "user") == BE_USER)
                )
                new_ds = rewrite_datasource_nominal(ds, self._pg_login, be_fixed if is_be else wyre_fixed)
                if new_ds == ds:
                    continue
                while ds_node.hasChildNodes():
                    ds_node.removeChild(ds_node.firstChild())
                ds_node.appendChild(doc.createTextNode(new_ds))
                cleaned += 1
                continue
            if datasource_param(ds, "authcfg") is None:
                continue
            # Ne jamais injecter nos identifiants dans la datasource d'un
            # serveur PG tiers : comparaison EXACTE de l'hote (revue 2, M7 ;
            # une sous-chaine matchait un autre hote ou le texte du filtre).
            if datasource_param(ds, "host") not in known_hosts:
                continue

            # Determiner l'identite a preserver depuis le user='...'
            # existant AVANT de le retirer -- repli sur wyre si absent ou
            # inconnu (meme comportement que _fix_layer_credentials).
            current_user = datasource_param(ds, "user")
            target_user, target_password = known_identities.get(
                current_user, (DEFAULT_USER, password)
            )

            # Remplacer authcfg/user/password existants par l'identite
            # cible, AVANT table= : les ajouter en fin de chaine les
            # versait dans le filtre sql= (revue 29/10, I12 -- faute deja
            # presente en 1.7.x).
            fixed_cfg = _fixed_authcfg_for_user(target_user)
            if fixed_cfg:
                # ID FIXE identique sur tous les postes : projet portable,
                # sans mot de passe en clair.
                ds = rewrite_datasource_identity(ds, target_user, authcfg=fixed_cfg)
            else:
                ds = rewrite_datasource_identity(ds, target_user, password=target_password)
            # Remplacer le contenu du noeud
            while ds_node.hasChildNodes():
                ds_node.removeChild(ds_node.firstChild())
            ds_node.appendChild(doc.createTextNode(ds))
            cleaned += 1
        if cleaned:
            self._log(f"{cleaned} datasource(s) PG nettoyee(s) avant sauvegarde (authcfg retire)")

    # =====================================================================
    # verify-full des couches qui recoivent le mot de passe AD (D-TLS-2)
    # =====================================================================

    def _ad_password_in_layer_configs(self) -> bool:
        """True quand 9i19s56/07254s7 portent (ou peuvent porter) le mot de
        passe AD : drapeau persistant AD_IDENTITY_KEY (revue 2, I-4 : vrai
        aussi en repli partage tant que ces configs n'ont pas ete
        reecrites, ex. mot de passe maitre refuse), ou session nominative."""
        return _ad_identity_flag() or (self._connected and self._auth_mode == AUTH_MODE_NOMINAL)

    def _nominal_source_preprocessor(self, source):
        """Preprocesseur QgsPathResolver (appele par QGIS pour chaque chemin
        et chaque datasource lus dans un projet, avant creation des couches),
        pour les datasources rattachees a NOS configs fixes 9i19s56/07254s7 :
        - hote tiers (comparaison exacte) : authcfg retire -- nos
          identifiants ne partent jamais ailleurs (revue 2, I-7) ;
        - nos hotes : verify-full tant que ces configs portent le mot de
          passe AD.
        Rien d'autre n'est touche ; ne leve jamais (QGIS 3.28 remplacerait
        la source par une chaine vide)."""
        try:
            if "authcfg=" not in source:
                return source
            authcfg = datasource_param(source, "authcfg")
            if authcfg not in (_FIXED_AUTH_CFG_IDS["wyre"], _FIXED_AUTH_CFG_IDS["be"]):
                return source
            host = datasource_param(source, "host")
            if host not in {h for h in (DEFAULT_HOST, BE_HOST) if h}:
                self._log(
                    f"authcfg {authcfg} retire d'une datasource vers un hote tiers ({host or 'sans hote'})",
                    Qgis.MessageLevel.Warning,
                )
                return strip_datasource_authcfg(source)
            if datasource_param(source, "sslmode") == NOMINAL_SSLMODE:
                return source
            if not self._ad_password_in_layer_configs():
                return source
            return force_datasource_sslmode(source, NOMINAL_SSLMODE)
        except Exception:  # noqa: BLE001 -- voir docstring
            return source

    def _secure_open_layers(self):
        """Couches DEJA chargees (plugin active ou recharge -- Plugin
        Reloader -- avec un projet ouvert, revue 2 I-5) : meme traitement
        que le preprocesseur, applique par setDataSource. Ne fait rien pour
        une couche deja conforme."""
        for layer in QgsProject.instance().mapLayers().values():
            if not isinstance(layer, QgsVectorLayer) or layer.providerType() != "postgres":
                continue
            source = layer.source()
            secured = self._nominal_source_preprocessor(source)
            if secured == source:
                continue
            try:
                layer.setDataSource(secured, layer.name(), "postgres", QgsDataProvider.ProviderOptions())
            except Exception as exc:  # noqa: BLE001 -- couche exotique, jamais bloquant
                self._log(f"Securisation de {layer.name()} impossible : {exc}", Qgis.MessageLevel.Warning)

    def _secure_storage_uri(self, uri: str) -> str:
        return secure_project_storage_uri(
            uri, (DEFAULT_HOST, BE_HOST), (_FIXED_AUTH_CFG_IDS["wyre"], _FIXED_AUTH_CFG_IDS["be"]),
            NOMINAL_SSLMODE,
        )

    def _secure_recent_projects(self):
        """Revue 2 (I-8) : les projets enregistres dans PostgreSQL sont
        rouverts depuis « Projets recents » par leur URI postgresql://
        (authcfg + sslmode, QgsPostgresProjectStorage), sans
        preprocesseur. Tant que 9i19s56/07254s7 portent le mot de passe AD,
        ces URI sont reecrites en verify-full (sans reseau). QGIS garde la
        liste lue au demarrage en memoire : effet complet au demarrage
        suivant ; _on_project_read couvre le projet ouvert entre-temps."""
        if not self._ad_password_in_layer_configs():
            return
        settings = QgsSettings()
        settings.beginGroup("UI/recentProjects")
        groups = settings.childGroups()
        settings.endGroup()
        secured = 0
        for group in groups:
            key = f"UI/recentProjects/{group}/path"
            path = settings.value(key, "") or ""
            new_path = self._secure_storage_uri(path)
            if new_path != path:
                settings.setValue(key, new_path)
                secured += 1
        if secured:
            self._log(f"{secured} projet(s) recent(s) en base rattache(s) a verify-full")

    def _secure_current_project_uri(self):
        """Projet ouvert depuis PostgreSQL par une URI en require : les
        enregistrements suivants (et l'entree des projets recents) partent
        en verify-full. Ne rend pas le projet modifie."""
        project = QgsProject.instance()
        uri = project.fileName() or ""
        if not uri.startswith("postgresql://") or not self._ad_password_in_layer_configs():
            return
        secured = self._secure_storage_uri(uri)
        if secured == uri:
            return
        dirty = project.isDirty()
        project.setFileName(secured)
        project.setDirty(dirty)
        self._log("Projet en base : URI de stockage rattachee a verify-full")

    # =====================================================================
    # Auto-connexion
    # =====================================================================

    def _schedule_startup_connection(self):
        """Programme la connexion de demarrage (revue 29/10, I13) : rien de
        modal ni de reseau dans initGui, masque par l'ecran de demarrage.

        Phase silencieuse (_startup_silent : sonde avec le mot de passe AD
        memorise, sinon repli partage ; jamais de dialogue) au plus tard a
        initializationCompleted, mais AVANT tout projet ouvert au lancement :
        main.cpp ouvre le projet de la ligne de commande et QgisApp le
        dernier projet (fileOpenAfterLaunch, connecte avant les plugins)
        AVANT nos slots de initializationCompleted ; QgsProject emet
        layerLoaded(0, n) avant de creer la premiere couche -> la sonde passe
        avant toute connexion de couche. Phase interactive (dialogue,
        assistant d'accueil, bandeau) a initializationCompleted.
        """
        self._startup_state = "pending"
        QgsProject.instance().layerLoaded.connect(self._on_layer_loaded)
        main_window = self.iface.mainWindow()
        if main_window is not None and main_window.isVisible():
            # Plugin active apres le demarrage de QGIS : interface prete.
            QTimer.singleShot(0, self._on_initialization_completed)
        else:
            self.iface.initializationCompleted.connect(self._on_initialization_completed)

    def _cancel_startup_connection(self):
        """unload : plus aucun rappel de demarrage en attente."""
        try:
            QgsProject.instance().layerLoaded.disconnect(self._on_layer_loaded)
        except (TypeError, RuntimeError):
            pass
        try:
            self.iface.initializationCompleted.disconnect(self._on_initialization_completed)
        except (TypeError, RuntimeError, AttributeError):
            pass
        self._startup_state = "cancelled"

    def _on_layer_loaded(self, index, _count):
        if index == 0 and self._startup_state == "pending":
            self._startup_silent()

    def _on_initialization_completed(self):
        if self._startup_state == "cancelled":
            return  # plugin decharge avant le rappel (QTimer.singleShot)
        try:
            self.iface.initializationCompleted.disconnect(self._on_initialization_completed)
        except (TypeError, RuntimeError, AttributeError):
            pass
        self._startup_silent()
        self._startup_interactive()

    def _startup_silent(self):
        """Phase silencieuse du demarrage, une seule fois : controle des
        configs Auth Manager, `be` partagee historique, puis connexion
        (_auto_connect). Aucun dialogue de connexion."""
        if self._startup_state != "pending":
            return
        self._startup_state = "done"
        try:
            QgsProject.instance().layerLoaded.disconnect(self._on_layer_loaded)
        except (TypeError, RuntimeError):
            pass
        # Configs Auth Manager a id fixe (wyre/be) : nettoie les anciennes
        # configs a id aleatoire en reprenant leur mot de passe.
        self._log(_check_fixed_authcfgs())
        # `be` nominative (meme compte AD) est configuree apres la sonde
        # reussie, dans _connect. Seul l'identifiant partage `be` historique
        # (credentials 1.5 -> 1.7) l'est ici, independamment de `wyre`.
        if BE_SHARED_AVAILABLE:
            try:
                self._setup_qgis_pg_connection(_BE_PW, use_authcfg=True, conn="be")
            except Exception as exc:
                QgsMessageLog.logMessage(
                    f"BE connection setup failed: {exc}", TAG, level=Qgis.MessageLevel.Warning,
                )
        elif not BE_ENABLED:
            QgsMessageLog.logMessage(
                "Connexion 'be' non configuree "
                "(bloc absent ou invalide dans credentials.json)",
                TAG, level=Qgis.MessageLevel.Info,
            )
        self._auto_connect()

    def _startup_interactive(self):
        """Phase interactive : l'interface est prete. Dialogue differe
        (premier demarrage, ressaisie apres refus), bandeau, assistant."""
        self._ui_ready = True
        prompt, self._pending_prompt = self._pending_prompt, None
        if prompt:
            # Le dialogue est la seule interaction de demarrage ; apres une
            # saisie, un echec est affiche (revue 29/10, M12).
            self._connect_nominal_or_fallback(
                silent=False, login=self._pending_login or None, reprompt=prompt == "reprompt",
            )
        self._show_banner()
        self._update_mode_indicator()
        if self._pending_onboarding is not None:
            is_new_user, self._pending_onboarding = self._pending_onboarding, None
            try:
                self._run_onboarding(is_new_user)
            except Exception as exc:
                self._log(f"Onboarding failed: {exc}", Qgis.MessageLevel.Warning)

    def _auto_connect(self):
        """Tente une connexion silencieuse au demarrage du plugin.

        Bridge 1.8 : sonde nominative unique (login AD de la personne, mot
        de passe memorise dans l'Auth Manager), puis repli D7 sur
        l'identifiant partage si le login n'est pas actif. Jamais de
        dialogue ici : un dialogue necessaire est differe a la phase
        interactive (_startup_interactive).
        """
        if self._connected:
            return
        self._connect_nominal_or_fallback(silent=True, interactive=False)

    def _nominal_login(self) -> str:
        """Login PostgreSQL nominatif du poste : lower(nom d'utilisateur
        QGIS/OS), "" s'il ne peut pas etre un login (spec §5.1/§5.7.1)."""
        return resolve_pg_login(self._get_qgis_username())

    def _startup_login(self) -> str:
        """Login a sonder : celui saisi ou valide lors d'une connexion
        precedente (revue 29/10, I4 -- compte AD different du nom Windows),
        sinon celui deduit du poste."""
        memorized = normalize_login(QgsSettings().value(NOMINAL_SETTINGS_KEYS["pg_login"], "") or "")
        return memorized or self._nominal_login()

    def _ask_password(self, login: str, reprompt: bool = False):
        """Dialogue de connexion : login (pre-rempli, modifiable, normalise
        et valide par le dialogue) + mot de passe AD. Retourne (login,
        password) ou None si annule."""
        from .bridge_dialog import ConstructelConnectDialog

        dlg = ConstructelConnectDialog(
            self.iface.mainWindow(),
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            dbname=DEFAULT_DBNAME,
            login=login,
            message=tr("dialog.reprompt", login=login) if reprompt else "",
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return (dlg.login(), dlg.password())

    def _stored_ad_password(self, login: str) -> str:
        """Mot de passe AD memorise pour *login* ("" sinon) : jamais celui
        d'un autre login."""
        return _retrieve_password_encrypted("ad") if login and _stored_login("ad") == login else ""

    def _remember_ad_password(self, login: str, password: str):
        """Memorise le mot de passe AD de *login* pour la sonde du prochain
        demarrage -- seulement quand il n'a pas ete refuse (revue 29/10, I10)."""
        _store_password_encrypted(password, "ad", username=login)
        QgsSettings().setValue(NOMINAL_SETTINGS_KEYS["pg_login"], login)

    def _forget_refused_password(self, login: str, password: str):
        """Un mot de passe refuse n'est plus jamais rejoue (revue 29/10, I10) :
        ni par la sonde du demarrage suivant (nomin18), ni par les couches ou
        le navigateur (9i19s56/07254s7). Seules les configs qui portent
        exactement ce login ET ce mot de passe sont retirees."""
        auth_mgr = QgsApplication.authManager()
        for conn in ("ad", "wyre", "be"):
            try:
                if _stored_login(conn) == login and _retrieve_password_encrypted(conn) == password:
                    auth_mgr.removeAuthenticationConfig(_FIXED_AUTH_CFG_IDS[conn])
                    self._log(f"Mot de passe refuse retire de la config {_FIXED_AUTH_CFG_IDS[conn]} ({conn})")
            except Exception as exc:  # noqa: BLE001 -- best-effort, jamais bloquant
                self._log(f"Retrait du mot de passe refuse ({conn}) impossible : {exc}", Qgis.MessageLevel.Warning)
        _refresh_ad_identity_flag()

    def _connect_nominal_or_fallback(self, silent: bool = False, login: Optional[str] = None,
                                     password: Optional[str] = None, interactive: bool = True,
                                     explicit: bool = False, reprompt: bool = False) -> bool:
        """Sonde nominative UNIQUE puis repli D7 (spec §5.7.4-5, AC8 ; revue
        29/10 I2/I4/I5/I10/M1/M2/M3/M11/M12).

        1. login (memorise, sinon deduit du poste) ; ``ftth_editor`` saisi =
           secours admin D5 -> session partagee explicite, apres CHAQUE
           dialogue ;
        2. prerequis locaux : Auth Manager utilisable (une seule invite du
           mot de passe maitre) et CA importees dans QGIS (D-TLS-1) ; sinon
           repli partage ;
        3. mot de passe AD memorise pour ce login, sinon dialogue -- differe
           a la phase interactive au demarrage (*interactive* False), jamais
           propose d'office a un poste deja en repli sans mot de passe ;
        4. UNE connexion psycopg2 (verify-full, connect_timeout) ; sur echec :
           - mot de passe refuse : UNE ressaisie si permise
             (should_reprompt), sinon repli ; mot de passe oublie ;
           - login non actif (NOLOGIN, inconnu, pg_hba) : repli direct, mot
             de passe conserve (pas un refus de mot de passe) ;
           - toute autre erreur (delai, TLS, serveur, motif inconnu) : repli,
             mode memorise inchange.
        Jamais plus de 2 binds refuses par demarrage. *explicit* (Connecter,
        Reessayer) : la ressaisie est permise meme en repli, et un echec
        conserve la session ouverte au lieu de la remplacer. *reprompt* :
        ressaisie differee d'un refus deja compte (phase silencieuse).
        """
        memorized = QgsSettings().value(NOMINAL_SETTINGS_KEYS["auth_mode"], "") or ""
        if login is None:
            login = self._startup_login()
        if DEFAULT_USER and login == DEFAULT_USER:
            # Identifiant de secours saisi explicitement (admin, D5) : chemin partage.
            return self._connect_shared(silent, password=password, explicit=True)
        if not login and not interactive:
            self._log(tr("nominal.login_unusable", user=self._get_qgis_username()), Qgis.MessageLevel.Warning)
            if memorized == AUTH_MODE_SHARED:
                return self._fallback(silent, "no_password", login, explicit)
            self._pending_prompt, self._pending_login = "first", ""
            return self._fallback(silent, None, login, explicit)
        if not _ensure_auth_manager_ready():
            # M2/M3 : sans Auth Manager, 9i19s56 ne porterait pas l'identite
            # nominative des couches -> nominatif impossible.
            self._log("Acces nominatif impossible : Auth Manager indisponible "
                      "(mot de passe maitre non saisi ou gestionnaire desactive)", Qgis.MessageLevel.Warning)
            return self._fallback(silent, "local_setup", login, explicit)
        if not _ensure_qgis_trusted_cas():
            # D-TLS-1 : sans la CA dans QGIS, aucune couche nominative ne
            # passerait verify-full -> nominatif impossible, repli partage.
            return self._fallback(silent, "local_setup", login, explicit)
        refused = 1 if reprompt else 0
        if password is None and not reprompt:
            password = self._stored_ad_password(login)
        if not password:
            if not interactive:
                if memorized == AUTH_MODE_SHARED:
                    # Poste en repli sans mot de passe memorise (refuse et
                    # oublie) : pas de dialogue d'office a chaque demarrage.
                    return self._fallback(silent, "no_password", login, explicit)
                self._pending_prompt, self._pending_login = "first", login
                return self._fallback(silent, None, login, explicit)
            answer = self._ask_password(login, reprompt=reprompt)
            if not answer:
                # I9 : annuler ne fige pas le poste en repli -- mode memorise
                # inchange, nouvelle demande au demarrage suivant.
                return self._fallback(silent, AUTH_REFUSED if reprompt else "no_password", login, explicit,
                                      cancelled=True)
            login, password = answer
            if DEFAULT_USER and login == DEFAULT_USER:
                return self._connect_shared(silent, password=password, explicit=True)
            QgsSettings().setValue(NOMINAL_SETTINGS_KEYS["pg_login"], login)
        while True:
            if self._connect(password, silent=True, login=login, project_hooks=not silent):
                self._remember_ad_password(login, password)
                QgsSettings().setValue(NOMINAL_SETTINGS_KEYS["auth_mode"], AUTH_MODE_NOMINAL)
                self._set_banner(None)
                return True
            error = self._last_connect_error
            if isinstance(error, _LocalSetupError):
                kind = "local_setup"
            else:
                kind = classify_auth_failure(error) or "unavailable"
            self._log(
                f"Acces nominatif ({login}) non obtenu [{kind}] -- {error}",
                Qgis.MessageLevel.Warning,
            )
            if kind == AUTH_REFUSED:
                refused += 1
                self._forget_refused_password(login, password)
                if should_reprompt(kind, memorized, refused, explicit=explicit):
                    if not interactive:
                        self._pending_prompt, self._pending_login = "reprompt", login
                        return self._fallback(silent, AUTH_REFUSED, login, explicit)
                    answer = self._ask_password(login, reprompt=True)
                    if not answer:
                        return self._fallback(silent, AUTH_REFUSED, login, explicit, cancelled=True)
                    login, password = answer
                    if DEFAULT_USER and login == DEFAULT_USER:
                        return self._connect_shared(silent, password=password, explicit=True)
                    QgsSettings().setValue(NOMINAL_SETTINGS_KEYS["pg_login"], login)
                    continue
                QgsSettings().setValue(NOMINAL_SETTINGS_KEYS["auth_mode"], AUTH_MODE_SHARED)
            elif kind == LOGIN_DISABLED:
                # Pas un refus de mot de passe (NOLOGIN : le bind AD a
                # reussi ; pg_hba/role inconnu : aucun bind) : conserve pour
                # que la sonde du prochain demarrage bascule seule une fois
                # l'acces active (AC8).
                self._remember_ad_password(login, password)
                QgsSettings().setValue(NOMINAL_SETTINGS_KEYS["auth_mode"], AUTH_MODE_SHARED)
            return self._fallback(silent, kind, login, explicit)

    def _fallback(self, silent: bool, kind, login: str, explicit: bool = False,
                  cancelled: bool = False) -> bool:
        """Issue d'un acces nominatif non obtenu. Action explicite avec une
        session ouverte : la session est conservee (M1) et l'echec affiche
        (rien si la personne a annule le dialogue). Session partagee deja
        ouverte (phase silencieuse) : bandeau seul. Sinon : connexion
        partagee (repli D7) + bandeau."""
        if explicit and self._connected:
            if cancelled:
                return False
            if self._auth_mode == AUTH_MODE_SHARED:
                self._set_banner(kind, login)
            if kind and not silent:
                QMessageBox.warning(
                    self.iface.mainWindow(), "Constructel Bridge",
                    tr("nominal.retry_failed", reason=self._reason_text(kind, login)),
                )
            return False
        if self._connected and self._auth_mode == AUTH_MODE_SHARED:
            self._set_banner(kind, login)
            return True
        return self._connect_shared(silent, banner=kind, login=login)

    def _connect_shared(self, silent: bool, banner=None, login: str = "",
                        password: Optional[str] = None, explicit: bool = False) -> bool:
        """Connexion avec l'identifiant partage (chemin 1.7.x) + bandeau
        persistant D7 (sauf secours admin *explicit*). Sans identifiant
        partage (cloture 1.8.x) : erreur claire, jamais de KeyError."""
        if not SHARED_FALLBACK_AVAILABLE:
            error = f"{DEFAULT_HOST}:{DEFAULT_PORT} — {self._last_connect_error or '-'}"
            message = tr(
                "nominal.no_fallback",
                reason=self._reason_text(banner or "unavailable", login or self._nominal_login()),
                error=error,
            )
            self._log(message, Qgis.MessageLevel.Critical)
            if not silent:
                QMessageBox.critical(self.iface.mainWindow(), "Constructel Bridge", message)
            return False
        if password is None:
            # Mot de passe partage memorise (1.7.x, eventuellement tourne)
            # seulement si la config fixe porte bien l'identifiant partage.
            stored = _retrieve_password_encrypted("wyre") if _stored_login("wyre") in ("", DEFAULT_USER) else ""
            password = stored or _DEFAULT_PW
        ok = self._connect(password, silent=silent)
        if ok:
            self._set_banner(None if explicit else banner, login)
        return ok

    def _on_retry_nominal(self):
        """Action « Reessayer mon acces nominatif » : nouvelle sonde (mot de
        passe memorise, sinon dialogue, une ressaisie permise) ; succes ->
        bascule nominative immediate, sans redemarrage ni reinstallation.
        Echec -> la session en cours est conservee (M1)."""
        _reset_master_password_prompt()
        ok = self._connect_nominal_or_fallback(silent=False, explicit=True)
        if ok and self._auth_mode == AUTH_MODE_NOMINAL:
            self.iface.messageBar().pushSuccess(
                "Constructel Bridge", tr("nominal.retry_ok", login=self._pg_login),
            )

    # =====================================================================
    # Bandeau de repli D7 et indicateur de mode (revue 29/10, I9/I14)
    # =====================================================================

    _REASON_KEYS = {
        LOGIN_DISABLED: "nominal.reason_login_disabled",
        AUTH_REFUSED: "nominal.reason_auth_refused",
        "unavailable": "nominal.reason_unavailable",
        "local_setup": "nominal.reason_local_setup",
        "no_password": "nominal.reason_no_password",
    }

    def _reason_text(self, kind, login: str = "") -> str:
        return tr(self._REASON_KEYS.get(kind, "nominal.reason_unavailable"), login=login or "-")

    def _set_banner(self, kind, login: str = ""):
        """Bandeau persistant du repli D7 (None = aucun) : journalise tout de
        suite, affiche des que l'interface est prete."""
        self._banner = (kind, login) if kind else None
        if self._banner:
            self._log(tr("nominal.banner", reason=self._reason_text(kind, login)), Qgis.MessageLevel.Warning)
        if self._ui_ready:
            self._show_banner()
        self._update_mode_indicator()

    def _remove_banner(self):
        if self._banner_item is None:
            return
        try:
            self.iface.messageBar().popWidget(self._banner_item)
        except (RuntimeError, AttributeError):
            pass  # deja ferme par l'utilisateur (objet C++ detruit)
        self._banner_item = None

    def _show_banner(self):
        """Message SANS expiration (duree 0) dans la barre de messages ;
        remplace le precedent, retire quand la session redevient nominative."""
        self._remove_banner()
        if self._banner is None or not (self._connected and self._auth_mode == AUTH_MODE_SHARED):
            return
        kind, login = self._banner
        item = QgsMessageBarItem(
            "Constructel Bridge", tr("nominal.banner", reason=self._reason_text(kind, login)),
            Qgis.MessageLevel.Warning, 0,
        )
        self.iface.messageBar().pushItem(item)
        self._banner_item = item

    def _update_mode_indicator(self):
        """Indication permanente dans le menu du plugin : libelle de l'action
        « Reessayer mon acces nominatif » quand la session est partagee."""
        if self._action_retry is None:
            return
        shared = self._connected and self._auth_mode == AUTH_MODE_SHARED
        self._action_retry.setText(tr("menu.retry_nominal_shared" if shared else "menu.retry_nominal"))

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
            "menu.connect", "menu.retry_nominal", "menu.status", "menu.onboarding",
            "menu.load_project", "menu.init_project", "menu.language",
        ]
        for action, key in zip(self._actions, keys):
            action.setText(tr(key))
        self._update_mode_indicator()

    # =====================================================================
    # Connexion
    # =====================================================================

    def _on_connect(self):
        """Action manuelle : dialogue de connexion (login nominatif pre-rempli
        et modifiable + mot de passe AD). Meme machine d'etat que le
        demarrage (revue 29/10, M11) : mot de passe refuse -> UNE ressaisie
        avec message ; echec -> la session en cours est conservee (M1)."""
        _reset_master_password_prompt()
        answer = self._ask_password(self._pg_login or self._startup_login())
        if not answer:
            return
        login, password = answer
        self._connect_nominal_or_fallback(silent=False, login=login, password=password, explicit=True)

    def _connect(self, password: str, silent: bool = False, login: Optional[str] = None,
                 project_hooks: Optional[bool] = None):
        """Etablit la connexion et initialise l'utilisateur.

        Returns True on success, False on failure.
        When *silent* is True, no error dialog is shown (used by auto-connect).
        *project_hooks* (defaut : not silent) : corrections du projet courant
        apres succes.

        *login* (Bridge 1.8) : login PostgreSQL nominatif ; None = identifiant
        partage (chemin 1.7.x, repli D7). En nominatif : verify-full avec les
        CA du paquet et connect_timeout, configs Auth Manager ecrites et
        verifiees AVANT de declarer la session (M3), SELECT seul sur
        ref.users, plus d'app.current_user (le serveur connait l'auteur),
        perimetre lu et affiche. Sur echec, l'exception est conservee dans
        self._last_connect_error pour l'orchestrateur
        (_connect_nominal_or_fallback) ; le dialogue d'erreur est laisse a
        l'appelant en nominatif. La connexion en cours n'est fermee qu'apres
        le succes de la nouvelle (revue 29/10, M1).

        When mTLS is active, connects with verify-full + client certificate
        (paths from the mTLS settings). When mTLS is configured but
        invalid, aborts loudly before attempting any connection.
        """
        nominal = bool(login)
        user = login if nominal else DEFAULT_USER
        if not nominal:
            # Revue 29/10 (I6) : seul le mot de passe PARTAGE est expose aux
            # chemins 1.7.x (_fix_layer_credentials, projets, v_form_lists).
            self._password = password
        self._last_connect_error = None
        qgis_user = self._get_qgis_username()

        mtls_active, mtls_reason = _mtls_active()
        if not mtls_active and mtls_reason not in ("disabled", "not_configured"):
            # Configured but invalid (expired cert, missing key, ...): fail
            # closed BEFORE attempting any connection. A doomed legacy
            # attempt would only produce a misleading "wrong password"
            # trail once the server enforces client certs.
            self._log(_mtls_message(f"mtls.{mtls_reason}"), Qgis.MessageLevel.Critical)
            if not silent:
                QMessageBox.critical(
                    self.iface.mainWindow(),
                    "Constructel Bridge",
                    _mtls_message(f"mtls.{mtls_reason}"),
                )
            return False
        ssl_kwargs = {}
        if mtls_active:
            # verify-full against our CA + client cert auth; the password
            # still travels (SCRAM + clientcert), the cert is the 2nd factor.
            ssl_kwargs = {
                "sslmode": "verify-full",
                "sslcert": QgsSettings().value(MTLS_SETTINGS_KEYS["cert_path"], ""),
                "sslkey": QgsSettings().value(MTLS_SETTINGS_KEYS["key_path"], ""),
                "sslrootcert": QgsSettings().value(MTLS_SETTINGS_KEYS["ca_path"], ""),
            }
        elif nominal:
            # Session nominative (mot de passe AD) : verify-full obligatoire,
            # CA lues en place dans le paquet du plugin (D-TLS-1, rien
            # d'ecrit sur le poste). Partage : kwargs 1.7.x (D-TLS-2).
            ssl_kwargs = {
                "sslmode": NOMINAL_SSLMODE,
                "sslrootcert": str(ca_bundle_path(os.path.dirname(__file__))),
            }
        if nominal:
            # Revue 29/10 (I2) : AD lent ou en panne -> echec borne puis
            # repli, au lieu de geler QGIS jusqu'a authentication_timeout.
            ssl_kwargs["connect_timeout"] = NOMINAL_CONNECT_TIMEOUT

        try:
            import psycopg2

            app_name = f"constructel_bridge:{qgis_user}"
            ssl_mode = ssl_kwargs.pop("sslmode", DEFAULT_SSLMODE)
            new_conn = psycopg2.connect(
                host=DEFAULT_HOST,
                port=DEFAULT_PORT,
                dbname=DEFAULT_DBNAME,
                user=user,
                password=password,
                application_name=app_name,
                options="-c search_path=wyre,public",
                sslmode=ssl_mode,
                **ssl_kwargs,
            )
            new_conn.autocommit = True
        except (psycopg2.Error, OSError) as exc:
            self._last_connect_error = exc
            if mtls_active and "connection requires a valid client certificate" in str(exc):
                # Exact server-side verdict (pg_hba clientcert rejection):
                # our certificate was refused — not a password problem.
                # Still configure the browser entry (mirrors the generic
                # failure path below).
                try:
                    self._setup_qgis_pg_connection(password, use_authcfg=False)
                except Exception:
                    pass
                self._log(_mtls_message("mtls.cert_required_by_server"), Qgis.MessageLevel.Critical)
                if not silent:
                    QMessageBox.critical(
                        self.iface.mainWindow(),
                        "Constructel Bridge",
                        _mtls_message("mtls.cert_required_by_server"),
                    )
                return False
            self._log(
                f"Connection failed to {DEFAULT_HOST}:{DEFAULT_PORT}/{DEFAULT_DBNAME} ({user}): {exc}",
                Qgis.MessageLevel.Critical,
            )
            if nominal:
                # L'orchestrateur decide (ressaisie, repli, erreur) : ne pas
                # ecrire d'entree navigateur nominative sans mot de passe.
                return False
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

        if nominal:
            # M3 : la session nominative n'existe que si 9i19s56 porte bien
            # l'identite du poste -- sinon les couches pointeraient vers une
            # config absente ou perimee alors que le plugin se dirait connecte.
            try:
                self._setup_qgis_pg_connection(password, use_authcfg=True, login=login)
            except Exception as exc:
                self._log(f"QGIS PG config failed: {exc}", Qgis.MessageLevel.Warning)
            if not mtls_active and _stored_login("wyre") != login:
                new_conn.close()
                self._last_connect_error = _LocalSetupError(
                    f"config Auth Manager {_FIXED_AUTH_CFG_IDS['wyre']} non ecrite pour {login}"
                )
                return False

        old_conn = self._conn
        self._conn = new_conn
        if old_conn is not None and old_conn is not new_conn and not getattr(old_conn, "closed", True):
            try:
                old_conn.close()
            except Exception:  # noqa: BLE001 -- ancienne connexion deja morte
                pass

        self._connected = True
        self._auth_mode = AUTH_MODE_NOMINAL if nominal else AUTH_MODE_SHARED
        self._pg_login = login or ""
        self._ad_password = password if nominal else None
        self._scope = None
        self._scope_names = ({}, {})
        if nominal:
            self._log(tr("conn.established_nominal", login=login))
            # Le serveur connait l'auteur (session_user) : l'adresse
            # declaree n'est plus posee (spec §5.7.6, AC9) ; l'adresse
            # memorisee reste pour le plugin Historique (revue 29/10, M9).
            _clear_audit_identity(forget_email=False)
        else:
            self._log(tr("conn.established"))
            # M13 : pre-cache QgsCredentials de l'identifiant partage
            # seulement en session partagee.
            _precache_pg_credentials()

        try:
            is_new_user = self._register_bridge_user(select_only=nominal, login=login)
        except Exception as exc:
            self._log(f"User registration failed: {exc}", Qgis.MessageLevel.Warning)
            is_new_user = False

        if nominal:
            self._read_session_scope()
        else:
            try:
                self._setup_qgis_pg_connection(password, use_authcfg=True)
            except Exception as exc:
                self._log(f"QGIS PG config failed: {exc}", Qgis.MessageLevel.Warning)

        try:
            self._setup_be_connection(password, login)
        except Exception as exc:
            self._log(f"BE connection setup failed: {exc}", Qgis.MessageLevel.Warning)

        # En mode silent (auto-connect au demarrage), ne pas toucher au
        # projet pour eviter de le rendre "dirty" et declencher le
        # dialogue "Enregistrer le projet".
        if not nominal:
            # I-4 : drapeau leve seulement si 9i19s56/07254s7 ne portent
            # plus l'identite AD (reecriture partagee reussie / retrait).
            _refresh_ad_identity_flag()
        # I-5 / I-7 : couches deja ouvertes (plugin active ou recharge avec
        # un projet ouvert) : verify-full si nos configs portent le mot de
        # passe AD, jamais nos configs vers un hote tiers.
        try:
            self._secure_open_layers()
            if nominal:
                self._secure_recent_projects()
        except Exception as exc:  # noqa: BLE001 -- jamais bloquant
            self._log(f"Securisation des couches ouvertes impossible : {exc}", Qgis.MessageLevel.Warning)

        if project_hooks is None:
            project_hooks = not silent
        if project_hooks:
            self._apply_project_hooks()
        # I8 : le verrou suit la session (pose en nominatif sans
        # network.write, leve en partage ou avec le droit d'ecriture).
        try:
            self._apply_scope_to_layers()
        except Exception as exc:  # noqa: BLE001 -- jamais bloquant
            self._log(f"Scope lock failed: {exc}", Qgis.MessageLevel.Warning)

        if nominal:
            self.iface.messageBar().pushSuccess(
                "Constructel Bridge",
                tr("conn.connected_nominal", login=login, scope=self._scope_text()),
            )
        else:
            self.iface.messageBar().pushSuccess(
                "Constructel Bridge",
                tr("conn.connected_as", user=self._bridge_user),
            )
        self._update_mode_indicator()

        try:
            onboarding_done = QgsSettings().value("constructel_bridge/onboarding_done", False)
            if not onboarding_done or is_new_user:
                if self._ui_ready:
                    self._run_onboarding(is_new_user)
                else:
                    # I13 : pas d'assistant modal sous l'ecran de demarrage.
                    self._pending_onboarding = bool(is_new_user or self._pending_onboarding)
        except Exception as exc:
            self._log(f"Onboarding failed: {exc}", Qgis.MessageLevel.Warning)

        return True

    def _apply_project_hooks(self):
        """Applique les hooks, corrections et traductions sur le projet courant."""
        try:
            self._fix_layer_credentials()
        except Exception as exc:
            self._log(f"Fix layer credentials failed: {exc}", Qgis.MessageLevel.Warning)

        try:
            self._check_layer_datasources()
        except Exception as exc:
            self._log(f"Layer datasource check failed: {exc}", Qgis.MessageLevel.Warning)

        try:
            self._hook_layers()
        except Exception as exc:
            self._log(f"Hook install failed: {exc}", Qgis.MessageLevel.Warning)

        try:
            bridge_sketcher.apply_all_translations()
        except Exception as exc:
            self._log(f"i18n apply failed: {exc}", Qgis.MessageLevel.Warning)

        try:
            self._apply_scope_to_layers()
        except Exception as exc:
            self._log(f"Scope lock failed: {exc}", Qgis.MessageLevel.Warning)

    # =====================================================================
    # Identification et enregistrement utilisateur
    # =====================================================================

    def _get_qgis_username(self) -> str:
        """Recupere le nom d'utilisateur depuis les settings QGIS ou l'OS."""
        from .bridge_identity import resolve_username

        settings = QgsSettings()
        explicit = settings.value("constructel_bridge/username", "")

        profile_name = ""
        try:
            profile = QgsApplication.instance().userProfileManager().userProfile()
            if profile:
                profile_name = profile.name() or ""
        except Exception:
            pass

        # NOTE (PR Bridge 0): both the QGIS profile-manager lookup and
        # getpass.getuser() are now evaluated eagerly, even when `explicit`
        # alone would already decide the result. Previously the profile
        # lookup ran only when `explicit` was falsy, and getpass.getuser()
        # only when both prior checks failed. Neither call has side effects
        # (the profile lookup is a read-only getter, already wrapped in
        # try/except in the original code too) and resolve_username()
        # short-circuits on `explicit_setting` before consulting either
        # value, so the return value is unaffected. Accepted as a
        # deliberate, low-risk deviation to make the decision logic a pure,
        # testable function — not a silent behavior change.
        import getpass
        return resolve_username(explicit, profile_name, getpass.getuser())

    def _register_bridge_user(self, select_only: bool = False, login: Optional[str] = None) -> bool:
        """Enregistre l'utilisateur QGIS dans ref.users si absent.

        *select_only* (session nominative, Bridge 1.8) : lecture seule --
        l'utilisateur existe par ldap_sync, ni INSERT ni UPDATE (spec
        §5.7.8 ; la mig 502 les refuserait), ni adresse d'audit declaree.
        La recherche porte sur le login PostgreSQL de la session (*login*,
        = lower(username) cote serveur), pas sur le nom du poste (revue
        29/10, M10). Un login hors ref.users (bureau d'etudes) est
        simplement journalise.
        """
        username = login if (select_only and login) else self._get_qgis_username()
        self._bridge_user = username
        is_new = False

        cur = self._conn.cursor()
        try:
            if select_only:
                cur.execute(
                    "SELECT id, username, email FROM ref.users "
                    "WHERE lower(username) = %s AND active = TRUE",
                    (username.lower(),),
                )
            else:
                cur.execute(
                    "SELECT id, username, email FROM ref.users WHERE username = %s AND active = TRUE",
                    (username,),
                )
            row = cur.fetchone()

            if row:
                self._bridge_user_id = str(row[0])
                self._bridge_user_email = row[2]
                if select_only:
                    self._bridge_user = row[1] or username
                self._log(tr("user.existing", username=username, user_id=self._bridge_user_id))
            elif select_only:
                self._log(
                    f"Utilisateur {username} absent de ref.users "
                    "(login nominatif hors ref.users, ex. bureau d'etudes)"
                )
            else:
                cur.execute(
                    """
                    INSERT INTO ref.users (username, email, last_name, role)
                    VALUES (%s, %s, %s, 'OPERATOR')
                    ON CONFLICT (username) DO UPDATE
                        SET last_login = NOW(), active = TRUE
                    RETURNING id, email
                    """,
                    (username, derive_email(username), username),
                )
                new_row = cur.fetchone()
                self._bridge_user_id = str(new_row[0])
                self._bridge_user_email = new_row[1]
                self._log(tr("user.created", username=username, user_id=self._bridge_user_id))
                is_new = True

            if select_only:
                return False

            cur.execute(
                "UPDATE ref.users SET last_login = NOW() WHERE id = %s::uuid",
                (self._bridge_user_id,),
            )
            # Avant _setup_qgis_pg_connection / chargement du projet (cf. _connect).
            _apply_audit_identity(self._bridge_user_email, self._log)
            self._set_app_user(self._bridge_user_email or username)

        except Exception as exc:
            self._log(tr("user.error", error=exc), Qgis.MessageLevel.Warning)
        finally:
            cur.close()

        return is_new

    def _read_session_scope(self):
        """Lit le perimetre de la session nominative : role, capacites
        network.read/write, MRO/POP (lecture et ecriture) -- SELECT seul,
        jamais bloquant (volet D1). Un login sans EXECUTE sur ces fonctions
        (bureau d'etudes) laisse le perimetre inconnu."""
        self._scope = None
        self._scope_names = ({}, {})
        if not self._conn or self._conn.closed:
            return
        cur = self._conn.cursor()
        try:
            cur.execute(SCOPE_QUERY)
            scope = parse_session_scope(cur.fetchone())
            self._scope = scope
            mro_names, pop_names = {}, {}
            try:
                if scope.mro_ids:
                    cur.execute(
                        "SELECT id::text, name FROM wyre.zone_mro WHERE id = ANY(%s::uuid[])",
                        (scope.mro_ids,),
                    )
                    mro_names = {str(i): n for (i, n) in cur.fetchall()}
                if scope.pop_ids:
                    cur.execute(
                        "SELECT id::text, code FROM wyre.zone_pop WHERE id = ANY(%s::uuid[])",
                        (scope.pop_ids,),
                    )
                    pop_names = {str(i): c for (i, c) in cur.fetchall()}
            except Exception as exc:  # noqa: BLE001 -- noms = confort d'affichage
                self._log(f"Noms des zones du perimetre illisibles : {exc}", Qgis.MessageLevel.Warning)
            self._scope_names = (mro_names, pop_names)
            self._log(
                f"Perimetre de session : role={scope.role} read={scope.network_read} "
                f"write={scope.network_write} -- {self._scope_text()}"
            )
        except Exception as exc:  # noqa: BLE001 -- ne jamais bloquer la connexion
            self._log(f"Perimetre de session illisible : {exc}", Qgis.MessageLevel.Warning)
        finally:
            cur.close()

    def _scope_text(self) -> str:
        """Perimetre de la session, pour les messages (volet D3)."""
        if self._auth_mode != AUTH_MODE_NOMINAL:
            return tr("nominal.mode_shared", user=DEFAULT_USER)
        scope = self._scope
        if scope is None:
            return tr("scope.unknown")
        kind = scope_kind(scope)
        if kind == "all":
            text = tr("scope.all")
        elif kind == "none":
            text = tr("scope.none")
        else:
            mro_names, pop_names = self._scope_names
            text = tr(
                "scope.scoped",
                mro=", ".join(scope_labels(scope.mro_ids, mro_names)) or "-",
                pop=", ".join(scope_labels(scope.pop_ids, pop_names)) or "-",
            )
        if not scope.network_write:
            text = f"{text} / {tr('scope.readonly')}"
        return text

    def _setup_be_connection(self, password: str, login: Optional[str]):
        """Connexion `be` (bureau d'etudes, schema public) : nominative avec
        le MEME compte AD (authcfg 07254s7, username=<login>) ; en repli
        partage, l'identifiant `be` historique s'il est encore livre."""
        if not BE_ENABLED:
            QgsMessageLog.logMessage(
                "Connexion 'be' non configuree "
                "(bloc absent ou invalide dans credentials.json)",
                TAG, level=Qgis.MessageLevel.Info,
            )
            return
        if login:
            self._setup_qgis_pg_connection(password, use_authcfg=True, conn="be", login=login)
        elif BE_SHARED_AVAILABLE:
            self._setup_qgis_pg_connection(_BE_PW, use_authcfg=True, conn="be")
        else:
            self._log("Connexion 'be' : aucun identifiant disponible en mode partage (login nominatif requis)")
            self._neutralize_nominal_be()

    def _neutralize_nominal_be(self):
        """Repli partage sans identifiant `be` : 07254s7 ne doit plus porter
        le login + mot de passe AD d'une session nominative precedente, que
        les couches `be` et le navigateur rejoueraient (binds refuses si le
        mot de passe a change ; revue 29/10, I10). La config est retiree et
        l'entree navigateur `be` n'y fait plus reference."""
        fixed_id = _FIXED_AUTH_CFG_IDS["be"]
        try:
            auth_mgr = QgsApplication.authManager()
            if fixed_id not in auth_mgr.configIds():
                return
            login = _stored_login("be")
            # Revue 2 (I-4) : config illisible (mot de passe maitre refuse)
            # mais drapeau pose -> elle peut porter l'identite AD : retiree
            # (le retrait n'exige pas le mot de passe maitre).
            if (login and login == BE_USER) or (not login and not _ad_identity_flag()):
                return
            auth_mgr.removeAuthenticationConfig(fixed_id)
            QgsSettings().remove(f"PostgreSQL/connections/{_PG_CONNECTIONS['be']['name']}/authcfg")
            self._log(f"Connexion 'be' : config nominative {fixed_id} retiree (session partagee)")
        except Exception as exc:  # noqa: BLE001 -- jamais bloquant
            self._log(f"Connexion 'be' : neutralisation impossible : {exc}", Qgis.MessageLevel.Warning)

    def _set_app_user(self, username: str):
        """Positionne app.current_user dans la session PostgreSQL (mode
        partage seulement : en nominatif le serveur connait l'auteur)."""
        if self._auth_mode == AUTH_MODE_NOMINAL:
            return
        if not self._conn or self._conn.closed:
            return
        cur = self._conn.cursor()
        try:
            cur.execute("SELECT set_config('app.current_user', %s, false)", (username,))
        except Exception as exc:
            self._log(f"set_config error: {exc}", Qgis.MessageLevel.Warning)
        finally:
            cur.close()

    def _refresh_audit_identity(self):
        """Relit l'adresse dans ref.users (l'assistant d'accueil peut la
        modifier) et la repose pour les connexions suivantes."""
        if not self._conn or self._conn.closed or not self._bridge_user_id:
            return
        cur = self._conn.cursor()
        try:
            cur.execute("SELECT email FROM ref.users WHERE id = %s::uuid", (self._bridge_user_id,))
            row = cur.fetchone()
        except Exception as exc:
            self._log(f"Relecture de l'adresse d'audit impossible : {exc}", Qgis.MessageLevel.Warning)
            return
        finally:
            cur.close()
        email = row[0] if row else None
        if email and email != self._bridge_user_email:
            self._bridge_user_email = email
            _apply_audit_identity(email, self._log)
            self._set_app_user(email)

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

        Quand mTLS est actif, les couches sont reecrites vers l'authcfg
        PKI-Paths partagee (username conserve, SANS mot de passe) au lieu
        de credentials en clair. Si mTLS est actif mais le certificat
        indisponible, ou configure mais invalide, les couches concernees
        sont IGNOREES (comptees still_bad, warning) — jamais downgradees
        vers du plaintext (R4).
        """
        password = getattr(self, "_password", None) or _DEFAULT_PW
        # Deux identites plugin sont legitimes ici : wyre (DEFAULT_USER,
        # historique) et be (BE_USER, bureau d'etudes, si active). Sans
        # cette distinction, toute couche `be` (username=bureau_etudes)
        # etait auparavant reecrite de force vers wyre a chaque ouverture
        # de projet -- cassant le cloisonnement schema public de `be` et
        # embarquant le mot de passe wyre en clair dans le .qgz d'un
        # utilisateur externe (bureau d'etudes). Hisse hors de la boucle :
        # invariant, pas la peine de le reconstruire par couche.
        known_identities = {DEFAULT_USER: (DEFAULT_USER, password)}
        if BE_ENABLED and BE_USER and _BE_PW:
            known_identities[BE_USER] = (BE_USER, _BE_PW)
        # Bridge 1.8 : session nominative = identite DU poste (login + config
        # fixe), jamais de mot de passe, verify-full ; une couche `be`
        # (identifiant partage historique ou authcfg be) reste sur la
        # config be, tout le reste va sur la config wyre (spec §5.7.2/7).
        nominal = self._auth_mode == AUTH_MODE_NOMINAL and bool(self._pg_login)
        ad_identity = self._ad_password_in_layer_configs()
        wyre_fixed = _FIXED_AUTH_CFG_IDS["wyre"]
        be_fixed = _FIXED_AUTH_CFG_IDS["be"]

        # Reachable without _connect (project-load hook), so the
        # configured-but-invalid state must refuse HERE too — never
        # downgrade a layer to a plaintext password while mTLS is
        # configured but broken (R4).
        mtls_active, mtls_reason = _mtls_active()
        mtls_invalid = not mtls_active and mtls_reason not in ("disabled", "not_configured")
        pki_cfg_id = ""
        if mtls_active:
            pki_cfg_id = _store_pki_authcfg()
            if not pki_cfg_id:
                self._log(_mtls_message("mtls.activation_failed"), Qgis.MessageLevel.Warning)
        if mtls_invalid:
            self._log(_mtls_message(f"mtls.{mtls_reason}"), Qgis.MessageLevel.Critical)

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
                # Revue 2 (I-7) : jamais nos configs fixes (identite AD ou
                # partagee) vers un serveur tiers.
                if uri.authConfigId() in (wyre_fixed, be_fixed):
                    self._log(
                        f"Couche {layer.name()} : authcfg {uri.authConfigId()} retire "
                        f"(hote tiers {uri.host() or 'sans hote'})",
                        Qgis.MessageLevel.Warning,
                    )
                    uri.setAuthConfigId("")
                    layer.setDataSource(uri.uri(False), layer.name(), "postgres",
                                        QgsDataProvider.ProviderOptions())
                continue

            old_authcfg = uri.authConfigId()
            current_user = uri.username()
            force_verify_full = nominal
            if mtls_active or mtls_invalid:
                if not pki_cfg_id:
                    # Active but cert unavailable (or configured but
                    # invalid): SKIP, never downgrade to a plaintext
                    # password. Counted as still_bad so the operator
                    # sees the warning tally.
                    still_bad += 1
                    continue
                target_user = current_user if current_user in known_identities else DEFAULT_USER
                if old_authcfg != pki_cfg_id or uri.password() or current_user != target_user:
                    uri.setAuthConfigId(pki_cfg_id)
                    uri.setUsername(target_user)
                    uri.setPassword("")
                    needs_fix = True
                else:
                    needs_fix = False
            elif nominal:
                is_be = BE_ENABLED and (
                    old_authcfg == be_fixed or (bool(BE_USER) and current_user == BE_USER)
                )
                target_cfg = be_fixed if is_be else wyre_fixed
                needs_fix = (
                    old_authcfg != target_cfg
                    or current_user != self._pg_login
                    or bool(uri.password())
                    or datasource_param(uri.uri(False), "sslmode") != "verify-full"
                )
                if needs_fix:
                    uri.setAuthConfigId(target_cfg)
                    uri.setUsername(self._pg_login)
                    uri.setPassword("")
            elif ad_identity and old_authcfg in (wyre_fixed, be_fixed):
                # Revue 2 (I-4) : repli partage alors que 9i19s56/07254s7
                # portent encore l'identite AD (non reecrites, ex. mot de
                # passe maitre refuse) -> couche gardee, mais en verify-full.
                force_verify_full = True
                needs_fix = datasource_param(uri.uri(False), "sslmode") != NOMINAL_SSLMODE
            else:
                # Mode partage : un login nominatif d'un collegue (projet
                # enregistre ailleurs) est une identite inconnue -> wyre,
                # via la config fixe si elle existe (jamais de mot de passe
                # partage en clair pour un simple user= etranger) -- sauf
                # si cette config porte l'identite AD (I-4).
                target_user = current_user if current_user in known_identities else DEFAULT_USER
                fixed_cfg = "" if ad_identity else _fixed_authcfg_for_user(target_user)
                if fixed_cfg:
                    # Identite connue avec authcfg a ID FIXE present sur ce
                    # poste : on y rattache la couche, sans mot de passe en
                    # clair dans la datasource.
                    needs_fix = (
                        old_authcfg != fixed_cfg or bool(uri.password()) or current_user != target_user
                    )
                    if needs_fix:
                        uri.setAuthConfigId(fixed_cfg)
                        uri.setUsername(target_user)
                        uri.setPassword("")
                else:
                    needs_fix = bool(old_authcfg) or current_user not in known_identities
                    if needs_fix:
                        target_user, target_password = known_identities.get(
                            current_user, (DEFAULT_USER, password)
                        )
                        uri.setAuthConfigId("")
                        uri.setUsername(target_user)
                        uri.setPassword(target_password)

            if needs_fix or not layer.isValid():
                source = uri.uri(False)
                if force_verify_full and not (mtls_active or mtls_invalid):
                    # verify-full par reecriture du texte : setSslMode()
                    # n'existe pas en 3.28 et setParam("sslmode") y
                    # doublait le jeton au lieu de le remplacer.
                    source = force_datasource_sslmode(source, "verify-full")
                options = QgsDataProvider.ProviderOptions()
                layer.setDataSource(
                    source,
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
            self._log(f"{still_bad} couche(s) PG toujours invalides apres correction", Qgis.MessageLevel.Warning)

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
                    self._log(f"Style query error for {schema}.{table}: {_style_err}", Qgis.MessageLevel.Warning)
                    continue
                # Ecrire le QML dans un fichier temporaire et l'appliquer
                import tempfile
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".qml", delete=False, mode="w", encoding="utf-8"
                )
                was_read_only = layer.isReadOnly()
                try:
                    tmp.write(row[0])
                    tmp.close()
                    result = layer.loadNamedStyle(tmp.name)
                finally:
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass
                if not was_read_only and layer.isReadOnly():
                    # Revue 2 (I-2) : readOnly="1" d'un style par defaut
                    # (enregistre depuis une couche verrouillee) n'est pas
                    # une regle de style ; le verrou D2 est l'affaire du
                    # perimetre de la session.
                    layer.setReadOnly(False)
                    self._log(f"Style par defaut de {schema}.{table} : readOnly=1 ignore", Qgis.MessageLevel.Warning)
                if isinstance(result, tuple):
                    ok = result[1] if isinstance(result[0], str) else result[0]
                else:
                    ok = bool(result)
                if ok:
                    layer.triggerRepaint()
                    applied += 1
            cur.close()
        except Exception as exc:
            self._log(f"Style loading error: {exc}", Qgis.MessageLevel.Warning)
        if applied:
            self._log(f"{applied} couche(s): styles par defaut appliques")

        # Charger les couches de reference cachees requises par les ValueRelation
        self._ensure_ref_layers()

        # Le QML de la base designe la couche cible des ValueRelation par son nom
        # de table : remapper aussitot sur les noms affiches, y compris hors
        # projet Bridge (_on_project_read s'arrete alors avant l'i18n).
        try:
            bridge_sketcher._sync_value_relation_layer_names(project)
        except Exception as exc:
            self._log(f"ValueRelation LayerName sync failed: {exc}", Qgis.MessageLevel.Warning)
        # ... et leur LayerSource (user='ftth_editor' fige dans les QML)
        # vers l'identite nominative du poste (Bridge 1.8, B9).
        self._rewrite_value_relation_sources()

    def _rewrite_value_relation_sources(self):
        """Session nominative seulement : LayerSource des listes de valeurs
        rattache au login du poste (jamais bloquant)."""
        if self._auth_mode != AUTH_MODE_NOMINAL or not self._pg_login:
            return
        try:
            patched = bridge_sketcher.rewrite_value_relation_sources(
                QgsProject.instance(), self._pg_login, _FIXED_AUTH_CFG_IDS["wyre"],
                (DEFAULT_HOST, BE_HOST),
            )
            if patched:
                self._log(f"{patched} LayerSource(s) de listes de valeurs rattache(s) au login nominatif")
        except Exception as exc:  # noqa: BLE001 -- confort, jamais bloquant
            self._log(f"ValueRelation LayerSource rewrite failed: {exc}", Qgis.MessageLevel.Warning)

    def _init_conn_params(self):
        """(conn_params, password) pour l'initialisation de projet et les
        styles : session nominative = login + config fixe + verify-full
        (aucun mot de passe dans les couches, CA du paquet pour la
        connexion psycopg2 des styles) ; partage = chemin 1.7.x exact."""
        password = getattr(self, "_password", None) or _DEFAULT_PW
        params = {
            "host": DEFAULT_HOST,
            "port": DEFAULT_PORT,
            "dbname": DEFAULT_DBNAME,
            "user": DEFAULT_USER,
            "sslmode": DEFAULT_SSLMODE,
        }
        if self._auth_mode == AUTH_MODE_NOMINAL and self._pg_login:
            params["user"] = self._pg_login
            params["authcfg"] = _FIXED_AUTH_CFG_IDS["wyre"]
            params["sslmode"] = NOMINAL_SSLMODE
            params["sslrootcert"] = str(ca_bundle_path(os.path.dirname(__file__)))
            # I6 : seul lecteur du mot de passe AD (connexion psycopg2 des
            # styles) ; jamais ecrit dans une couche (authcfg).
            password = self._ad_password or ""
        return params, password

    def _ensure_ref_layers(self):
        """Charge ref.v_form_lists comme couche cachee pour les ValueRelation.

        Les formulaires QGIS utilisent des ValueRelation qui referencent
        ref.v_form_lists. Cette couche doit exister dans le projet pour
        que les listes deroulantes fonctionnent.

        Revue 29/10 (I7) : inerte en 1.7.x (TypeError), cette injection
        touchait TOUT projet ouvert. Desormais : projet Bridge dont une liste
        de valeurs depend de v_form_lists seulement, et toujours via une
        config Auth Manager a id fixe -- jamais de mot de passe en clair.
        """
        project = QgsProject.instance()
        try:
            from .bridge_project_init import is_bridge_project

            if not is_bridge_project() or not bridge_sketcher.value_relations_use_form_lists(project):
                return
        except Exception as exc:  # noqa: BLE001 -- confort, jamais bloquant
            self._log(f"v_form_lists : projet non analysable ({exc})", Qgis.MessageLevel.Warning)
            return
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
        uri = QgsDataSourceUri()
        if self._auth_mode == AUTH_MODE_NOMINAL and self._pg_login:
            # Session nominative : login + config fixe, aucun mot de passe.
            uri.setConnection(
                DEFAULT_HOST, str(DEFAULT_PORT), DEFAULT_DBNAME,
                self._pg_login, "", QgsDataSourceUri.SslMode.SslVerifyFull,
                _FIXED_AUTH_CFG_IDS["wyre"],
            )
        else:
            # Session partagee : config fixe 9i19s56 (identifiant partage),
            # sslmode 1.7.x ; sans elle, pas de couche plutot qu'un mot de
            # passe en clair dans le projet.
            fixed_cfg = "" if self._ad_password_in_layer_configs() else _fixed_authcfg_for_user(DEFAULT_USER)
            if not fixed_cfg:
                self._log("v_form_lists non chargee : config Auth Manager partagee absente ou non partagee")
                return
            uri.setConnection(
                DEFAULT_HOST, str(DEFAULT_PORT), DEFAULT_DBNAME,
                DEFAULT_USER, "", _ssl_mode_enum(DEFAULT_SSLMODE), fixed_cfg,
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
                Qgis.MessageLevel.Warning,
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

    def _setup_qgis_pg_connection_mtls(self, conn: str, password: str):
        """PKI-Paths variant of _setup_qgis_pg_connection (mTLS active).

        sslmode "5" (verify-full), shared PKI authcfg, username saved, NO
        password value anywhere — the password travels via .pgpass for
        libpq-based consumers. Any legacy Basic authcfg for this
        connection is removed (idempotent). Aborts loudly (log + return,
        settings untouched) when the pgpass write or the PKI config store
        fails. The legacy `use_authcfg` flag is ignored: PKI replaces
        Basic unconditionally while mTLS is active.
        """
        params = _PG_CONNECTIONS[conn]
        settings = QgsSettings()
        base = f"PostgreSQL/connections/{params['name']}"

        if not _ensure_pgpass_entry(
            pgpass_file_path(), params["host"], params["port"],
            params["dbname"], params["user"], password,
        ):
            self._log(
                _mtls_message("mtls.pgpass_unwritable", path=str(pgpass_file_path())),
                Qgis.MessageLevel.Critical,
            )
            return
        cfg_id = _store_pki_authcfg()
        if not cfg_id:
            self._log(_mtls_message("mtls.activation_failed"), Qgis.MessageLevel.Critical)
            return

        settings.setValue(f"{base}/host", params["host"])
        settings.setValue(f"{base}/port", str(params["port"]))
        settings.setValue(f"{base}/database", params["dbname"])
        settings.setValue(f"{base}/username", params["user"])
        settings.setValue(f"{base}/sslmode", "5")
        settings.setValue(f"{base}/estimatedMetadata", True)
        settings.setValue(f"{base}/allowGeometrylessTables", False)
        settings.setValue(f"{base}/geometryColumnsOnly", True)
        settings.setValue(f"{base}/dontResolveType", False)
        settings.setValue(f"{base}/publicOnly", params.get("public_only", False))
        settings.setValue(f"{base}/projectsInDatabase", True)
        settings.setValue(f"{base}/metadataInDatabase", True)
        settings.setValue(f"{base}/schemas", params["schemas"])
        settings.setValue(f"{base}/schema", params["schema"])
        settings.setValue(f"{base}/authcfg", cfg_id)
        settings.setValue(f"{base}/saveUsername", True)
        settings.setValue(f"{base}/savePassword", False)
        settings.remove(f"{base}/password")

        # Legacy Basic authcfg must not linger next to the PKI config.
        _remove_stored_password(conn)

        # Renommage v1.5.0 : retirer l'entree historique "constructel_bridge".
        settings.remove(_LEGACY_PG_CONNECTION)

        self._log(tr("pg.configured", name=params["name"]))

    def _setup_qgis_pg_connection(self, password: str, use_authcfg: bool = False,
                                  conn: str = "wyre", login: Optional[str] = None):
        """Enregistre une connexion PostgreSQL dans les settings QGIS.

        Always writes all values to ensure consistency and fix any
        leftover misconfiguration from previous plugin versions.

        *conn* est une cle de ``_PG_CONNECTIONS`` ("wyre" ou "be") : elle
        determine le nom affiche, les parametres serveur et les schemas
        exposes.  Le defaut "wyre" preserve le comportement des appelants
        historiques (_connect).

        *login* (Bridge 1.8) : login nominatif porte par l'entree et par la
        config Auth Manager a id fixe, en verify-full ("5") ; None =
        identifiant partage, en require ("3") comme 1.7.x (D-TLS-2).

        When *use_authcfg* is True, stores credentials in Auth Manager
        and references the authcfg ID instead of storing the password
        in plaintext (equivalent to "Convertir en configuration").

        When mTLS is active, delegates to _setup_qgis_pg_connection_mtls
        (PKI-Paths + verify-full; `use_authcfg` ignored). When mTLS is
        configured but invalid, aborts loudly without writing anything.
        """
        params = _PG_CONNECTIONS[conn]
        mtls_active, mtls_reason = _mtls_active()
        if mtls_active:
            self._setup_qgis_pg_connection_mtls(conn, password)
            return
        if mtls_reason not in ("disabled", "not_configured"):
            # Configured but invalid: fail closed, LOUDLY. Never fall back
            # to legacy silently (R4) — an expired cert + silent Basic
            # fallback would leave the operator unprotected post-enforcement.
            self._log(_mtls_message(f"mtls.{mtls_reason}"), Qgis.MessageLevel.Critical)
            return
        settings = QgsSettings()
        base = f"PostgreSQL/connections/{params['name']}"
        user = login or params["user"]

        settings.setValue(f"{base}/host", params["host"])
        settings.setValue(f"{base}/port", str(params["port"]))
        settings.setValue(f"{base}/database", params["dbname"])
        settings.setValue(f"{base}/username", user)
        settings.setValue(f"{base}/sslmode", "5" if login else "3")
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
            store_ok = _store_password_encrypted(password, conn, username=login)
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
                    "has no saved password.",
                    Qgis.MessageLevel.Warning,
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

    # QGIS >= 3.30 ne lit plus que connections/ows|xyz/items/... : au
    # demarrage, QGIS Desktop y recopie les cles qgis/connections-* puis
    # (3.36+) les supprime. On ecrit donc directement, et seulement, les cles
    # actuelles (memes noms que cette migration) : ecrire les anciennes ferait
    # re-enregistrer les services a chaque demarrage. Les parametres absents
    # gardent la valeur par defaut de QGIS.
    _CURRENT_CONNECTION_ROOTS = {
        "qgis/connections-xyz": "connections/xyz/items",
        "qgis/connections-wms": "connections/ows/items/wms/connections/items",
        "qgis/connections-wfs": "connections/ows/items/wfs/connections/items",
    }
    _CURRENT_CONNECTION_KEYS = {
        "url": "url",
        "version": "version",
        "zmin": "zmin",
        "zmax": "zmax",
        "dpiMode": "dpi-mode",
        "pagingenabled": "paging-enabled",
    }

    def _service_settings(self, base, name, params):
        """(prefixe, valeurs) du service sous les cles lues par le QGIS courant."""
        root = self._CURRENT_CONNECTION_ROOTS.get(base)
        if Qgis.QGIS_VERSION_INT < 33000 or root is None:
            return f"{base}/{name}", dict(params)
        values = {
            self._CURRENT_CONNECTION_KEYS[k]: v
            for k, v in params.items()
            if k in self._CURRENT_CONNECTION_KEYS
        }
        if "paging-enabled" in values and Qgis.QGIS_VERSION_INT >= 33600:
            # Depuis QGIS 3.36 : chaine default|enabled|disabled (booleen avant).
            values["paging-enabled"] = "enabled" if values["paging-enabled"] else "disabled"
        return f"{root}/{name}", values

    def _setup_external_services(self):
        """Enregistre les connexions WMTS / XYZ / WFS dans les settings QGIS.

        N'ecrase pas une connexion existante si l'URL est identique
        (l'utilisateur a peut-etre modifie d'autres parametres).
        """
        settings = QgsSettings()
        added = []
        for base, name, params in self._EXTERNAL_SERVICES:
            key_prefix, values = self._service_settings(base, name, params)
            if settings.value(f"{key_prefix}/url", "") == params.get("url", ""):
                self._log(f"Service '{name}' already configured — skipped")
                continue
            for k, v in values.items():
                settings.setValue(f"{key_prefix}/{k}", v)
            added.append(name)
            self._log(f"Service '{name}' registered ({key_prefix})")
        if added:
            settings.sync()
            self.iface.reloadConnections()
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
                    level=Qgis.MessageLevel.Warning,
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
                    level=Qgis.MessageLevel.Warning,
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
                    level=Qgis.MessageLevel.Warning,
                )
        except Exception as exc:
            self._log(
                f"Pre-provisionnement de 'extract-msg' ignore ({exc})",
                level=Qgis.MessageLevel.Warning,
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

        # Un seul branchement, meme apres plusieurs lectures de projet.
        try:
            project.layersAdded.disconnect(self._on_layers_added)
        except TypeError:
            pass
        project.layersAdded.connect(self._on_layers_added)
        self._layer_hooks_installed = True
        self._log(tr("hook.all_installed"))

    def _unhook_layers(self):
        # M6 : slots raiseError retires au dechargement du plugin.
        for layer, slot in self._layer_error_slots.values():
            try:
                layer.raiseError.disconnect(slot)
            except (TypeError, RuntimeError, AttributeError):
                pass  # couche supprimee entre-temps
        self._layer_error_slots = {}
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

    def _on_layers_added_scope(self, layers):
        """Volet D2 / M8 : les couches ajoutees apres la connexion suivent le
        perimetre de la session (lecture seule sans network.write), projet
        Bridge ou non."""
        try:
            self._apply_scope_to_layers(layers)
        except Exception as exc:  # noqa: BLE001 -- jamais bloquant
            self._log(f"Scope lock on added layers failed: {exc}", Qgis.MessageLevel.Warning)

    def _hook_single_layer(self, layer: QgsVectorLayer):
        provider = layer.dataProvider()
        if not provider or provider.name() != "postgres":
            return
        try:
            layer.beforeCommitChanges.disconnect(self._on_before_commit)
        except TypeError:
            pass
        layer.beforeCommitChanges.connect(self._on_before_commit)
        # Volet D2 : un refus serveur (42501, RLS, trg_enforce_gis_scope) sur
        # un commit est traduit en message clair. Un seul slot par couche.
        self._connect_layer_error(layer)
        self._log(tr("hook.installed", layer=layer.name()), Qgis.MessageLevel.Info)

    def _connect_layer_error(self, layer):
        signal = getattr(layer, "raiseError", None)
        if signal is None:
            return
        # M6 : indexe sur layer.id() (id(objet) peut etre reutilise par
        # Python) ; la couche est gardee pour deconnecter a l'unload.
        layer_id = layer.id()
        previous = self._layer_error_slots.pop(layer_id, None)
        if previous is not None:
            try:
                previous[0].raiseError.disconnect(previous[1])
            except (TypeError, RuntimeError):
                pass

        def _slot(message, _layer=layer):
            self._on_layer_error(_layer, message)

        try:
            signal.connect(_slot)
        except Exception:  # noqa: BLE001 -- signal absent sur cette version de QGIS
            return
        self._layer_error_slots[layer_id] = (layer, _slot)

    def _on_layer_error(self, layer, message):
        """Message clair quand le serveur refuse une ecriture pour raison de
        perimetre ou de capacite (session nominative seulement : en repli,
        ftth_editor voit et ecrit tout, D6)."""
        if self._auth_mode != AUTH_MODE_NOMINAL:
            return
        kind = scope_refusal_kind(str(message))
        if kind is None:
            return
        key = {
            SCOPE_REFUSAL_PERIMETER: "scope.write_refused_perimeter",
            SCOPE_REFUSAL_RIGHT: "scope.write_refused_right",
        }.get(kind, "scope.write_refused")
        text = tr(key, layer=layer.name())
        self._log(f"{text} -- {message}", Qgis.MessageLevel.Warning)
        self.iface.messageBar().pushWarning("Constructel Bridge", text)

    def _apply_scope_to_layers(self, layers=None) -> int:
        """Volet D2 : sans capacite network.write, les couches du schema
        `wyre` de nos serveurs passent en lecture seule dans QGIS, avec
        message. La barriere reelle reste le serveur (RLS + trigger).

        Revue 29/10 (I8) et revue 2 (I-1/I-2) : le verrou est marque SUR la
        couche (propriete personnalisee SCOPE_LOCK_PROPERTY : relue avec le
        projet, recopiee par clone, copier-coller et .qlr) et suit la
        session. Couche marquee : reverrouillee si la session l'exige (projet
        rouvert, couche dupliquee), sinon liberee et demarquee. Couche non
        marquee deja en lecture seule : posee par la personne, jamais
        touchee. setReadOnly() refuse (couche en cours d'edition) : signale.
        Retourne le nombre de couches verrouillees par cet appel."""
        scope = self._scope if (self._connected and self._auth_mode == AUTH_MODE_NOMINAL) else None
        known_hosts = {h for h in (DEFAULT_HOST, BE_HOST) if h}
        if layers is None:
            layers = QgsProject.instance().mapLayers().values()
        locked, unlocked, busy = 0, 0, []
        for layer in layers:
            if not isinstance(layer, QgsVectorLayer) or layer.providerType() != "postgres":
                continue
            uri = QgsDataSourceUri(layer.source())
            try:
                ours = _has_scope_lock(layer)
                if uri.host() in known_hosts and should_lock_layer(uri.schema(), scope):
                    if layer.isReadOnly():
                        continue  # deja verrouillee (par nous, ou par la personne)
                    if layer.setReadOnly(True):
                        layer.setCustomProperty(SCOPE_LOCK_PROPERTY, "1")
                        locked += 1
                    else:
                        busy.append(layer.name())
                elif ours:
                    layer.setReadOnly(False)
                    layer.removeCustomProperty(SCOPE_LOCK_PROPERTY)
                    unlocked += 1
            except Exception as exc:  # noqa: BLE001 -- couche exotique
                self._log(f"Read-only lock failed on {layer.name()}: {exc}", Qgis.MessageLevel.Warning)
        if locked:
            text = tr("scope.layers_locked", count=locked)
            self._log(text, Qgis.MessageLevel.Warning)
            self.iface.messageBar().pushWarning("Constructel Bridge", text)
        if busy:
            text = tr("scope.layers_lock_busy", names=", ".join(busy))
            self._log(text, Qgis.MessageLevel.Warning)
            self.iface.messageBar().pushWarning("Constructel Bridge", text)
        if unlocked:
            self._log(f"{unlocked} couche(s) reseau rendue(s) a l'edition (perimetre de session)")
        return locked

    def _release_scope_locks(self):
        """Leve tous les verrous poses par le plugin (dechargement)."""
        for layer in QgsProject.instance().mapLayers().values():
            try:
                if _has_scope_lock(layer):
                    layer.setReadOnly(False)
                    layer.removeCustomProperty(SCOPE_LOCK_PROPERTY)
            except Exception:  # noqa: BLE001 -- couche deja detruite
                pass

    def _on_before_commit(self):
        layer = self.iface.activeLayer()
        if not layer or not isinstance(layer, QgsVectorLayer):
            return
        if not self._bridge_user:
            return
        provider = layer.dataProvider()
        if not provider or provider.name() != "postgres":
            return

        # QgsVectorDataProvider n'a pas d'executeSql (QGIS 3.28 -> 4.x) : sans
        # connexion Bridge ouverte, rien a tenter. L'auteur des modifications
        # est porte par PGOPTIONS (app.current_user, cf. _apply_audit_identity).
        if not self._conn or self._conn.closed:
            return
        try:
            cur = self._conn.cursor()
            try:
                if self._auth_mode != AUTH_MODE_NOMINAL:
                    # Session nominative : l'auteur est session_user, le GUC
                    # declaratif est ignore par le serveur (spec §5.3).
                    cur.execute(
                        "SELECT set_config('app.current_user', %s, true)",
                        (self._bridge_user_email or self._bridge_user,),
                    )
                cur.execute("SET application_name = %s", (f"constructel_bridge:{self._bridge_user}",))
            finally:
                cur.close()
            self._log(tr("hook.commit_tagged", user=self._bridge_user, layer=layer.name()))
        except (Exception, ) as exc:
            self._log(tr("hook.exec_error", error=exc), Qgis.MessageLevel.Warning)  # noqa: broad-except — provider API may raise various types

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
            layer.wkbType() == QgsWkbTypes.Type.NoGeometry
            or layer.geometryType() == QgsWkbTypes.GeometryType.NullGeometry
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
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected = dlg.selected_layers()
        if not selected - {"v_form_lists"}:
            return  # rien selectionne

        try:
            conn_params, password = self._init_conn_params()

            count = init_project(
                conn_params, password, selected,
                add_basemap=dlg.want_basemap(),
                apply_styles=dlg.want_styles(),
                selected_basemaps=dlg.selected_basemaps(),
            )

            # Appliquer les traductions i18n
            from . import bridge_sketcher
            bridge_sketcher.apply_all_translations()
            self._rewrite_value_relation_sources()

            # Installer les hooks d'edition
            self._hook_layers()
            self._apply_scope_to_layers()

            self.iface.messageBar().pushMessage(
                "Constructel Bridge",
                tr("init.success", count=count),
                level=Qgis.MessageLevel.Success,
                duration=5,
            )
        except Exception as exc:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Constructel Bridge",
                tr("init.error", error=str(exc)),
            )
            import traceback
            self._log(traceback.format_exc(), Qgis.MessageLevel.Critical)

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
            self._log(tr("project.load_error", name=proj_name, error=error), Qgis.MessageLevel.Critical)
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

        password = getattr(self, "_password", None) or _DEFAULT_PW
        # Validate schema against whitelist to prevent SQL injection
        if schema not in self._PROJECT_SCHEMAS:
            self._log(f"Rejected invalid schema: {schema!r}", Qgis.MessageLevel.Warning)
            return False
        cur = self._conn.cursor()
        try:
            cur.execute(
                f"SELECT content FROM {schema}.qgis_projects WHERE name = %s",
                (name,),
            )
            row = cur.fetchone()
        except Exception as exc:
            self._log(f"Failed to read project XML from PG: {exc}", Qgis.MessageLevel.Warning)
            return False
        if not row:
            self._log(f"Project '{name}' not found in {schema}.qgis_projects", Qgis.MessageLevel.Warning)
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
                    self._log("Cannot decode project content from PG", Qgis.MessageLevel.Warning)
                    return False

        # Nettoyer les authcfg des datasources et injecter user/password.
        # Meme logique known_identities que _fix_layer_credentials /
        # _strip_authcfg_from_dom (hotfix 2026-07-30, cf. leurs
        # docstrings) : preserver l'identite be existante plutot que de
        # tout basculer vers wyre, et ne jamais toucher un serveur tiers.
        original_xml = xml
        known_identities = {DEFAULT_USER: (DEFAULT_USER, password)}
        if BE_ENABLED and BE_USER and _BE_PW:
            known_identities[BE_USER] = (BE_USER, _BE_PW)
        known_hosts = {h for h in (DEFAULT_HOST, BE_HOST) if h}
        nominal = self._auth_mode == AUTH_MODE_NOMINAL and bool(self._pg_login)
        wyre_fixed = _FIXED_AUTH_CFG_IDS["wyre"]
        be_fixed = _FIXED_AUTH_CFG_IDS["be"]

        def _fix_datasource(m):
            """Callback pour re.sub: nettoie une balise <datasource>."""
            prefix, raw, suffix = m.group(1), m.group(2), m.group(3)
            # Texte XML : entites decodees avant analyse, re-encodees apres
            # (un filtre sql= peut contenir < > & ou des guillemets).
            ds = xml_unescape(raw, {"&quot;": '"', "&apos;": "'"})
            if datasource_param(ds, "host") not in known_hosts:  # M7 : exact
                return m.group(0)
            if nominal:
                # Session nominative : identite du poste via la config
                # fixe (presente : la sonde l'a ecrite), aucun mot de passe.
                is_be = BE_ENABLED and (
                    datasource_param(ds, "authcfg") == be_fixed
                    or (bool(BE_USER) and datasource_param(ds, "user") == BE_USER)
                )
                new_ds = rewrite_datasource_nominal(
                    ds, self._pg_login, be_fixed if is_be else wyre_fixed,
                )
            else:
                # Regression round 3 corrigee : le strip global d'authcfg sur
                # tout le XML a ete retire au profit d'un traitement par
                # datasource. Identite cible injectee AVANT table= : en fin
                # de chaine elle tombait dans le filtre sql= (revue 29/10,
                # I12 -- faute deja presente en 1.7.x).
                current_user = datasource_param(ds, "user")
                target_user, target_password = known_identities.get(
                    current_user, (DEFAULT_USER, password)
                )
                new_ds = rewrite_datasource_identity(ds, target_user, password=target_password)
            if new_ds == ds:
                return m.group(0)
            return prefix + xml_escape(new_ds) + suffix

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
            self._log(f"list_db_projects error: {exc}", Qgis.MessageLevel.Warning)
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
            # Session nominative : plus d'UPDATE ref.users par le plugin
            # (spec §5.7.8, trigger 502) -- le profil se gere dans Farois.
            db_conn=None if self._auth_mode == AUTH_MODE_NOMINAL else self._conn,
            email_domain=EMAIL_DOMAIN,
        )
        wizard.exec()
        self._refresh_audit_identity()

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
            nominal = self._auth_mode == AUTH_MODE_NOMINAL
            msg = tr(
                "status.connected_to",
                host=DEFAULT_HOST,
                port=DEFAULT_PORT,
                dbname=DEFAULT_DBNAME,
                user=self._pg_login if nominal else DEFAULT_USER,
                bridge_user=self._bridge_user,
                bridge_user_id=self._bridge_user_id,
                hooks=self._layer_hooks_installed,
            )
            mode = (
                tr("nominal.mode_nominal", login=self._pg_login) if nominal
                else tr("nominal.mode_shared", user=DEFAULT_USER)
            )
            msg = f"{msg}\n{mode}\n{self._scope_text()}"
        QMessageBox.information(self.iface.mainWindow(), tr("status.title"), msg)

    # =====================================================================
    # Logging
    # =====================================================================

    def _log(self, message: str, level=Qgis.MessageLevel.Info):
        QgsMessageLog.logMessage(message, TAG, level=level)
