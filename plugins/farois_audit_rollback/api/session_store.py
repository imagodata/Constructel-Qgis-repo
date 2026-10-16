"""Session Farois mémorisée (« Se souvenir de moi », 30 jours).

Seuls l'adresse mail et le jeton de rafraîchissement sont conservés : jamais le
mot de passe AD, jamais le jeton d'accès. Interface : load() -> (email, jeton)
ou None, save(email, jeton), clear(). L'implémentation QGIS chiffre le jeton dans
le gestionnaire d'authentification QGIS ; elle n'ouvre la base d'authentification
que si une session a été mémorisée, et n'écrit jamais de secret dans le journal.
"""

AUTHCFG_NAME = "Farois — session historique"
AUTHCFG_METHOD = "Basic"
SETTINGS_KEY = "farois_audit_rollback/session_authcfg"
LOG_TAG = "Farois"


class MemorySessionStore:
    """Magasin en mémoire (tests) : même contrat que QgisSessionStore."""

    def __init__(self):
        self._session = None

    def load(self):
        return self._session

    def save(self, email, refresh_token):
        self._session = (str(email), str(refresh_token))

    def clear(self):
        self._session = None


def _log(message):
    try:
        from qgis.core import Qgis, QgsMessageLog

        QgsMessageLog.logMessage(message, LOG_TAG, Qgis.Warning)
    except Exception:
        pass


def _outcome(answer, config):
    """QGIS récent (SIP_INOUT) renvoie (ok, config) ; les versions antérieures ok seul."""
    if isinstance(answer, tuple):
        return bool(answer[0]), answer[1] if len(answer) > 1 else config
    return bool(answer), config


def _saved_id(settings):
    return str(settings.value(SETTINGS_KEY, "") or "")


def _store(manager, email, refresh_token):
    """Enregistre une nouvelle configuration ; son identifiant, ou "" si refus."""
    from qgis.core import QgsAuthMethodConfig

    if manager.isDisabled():
        _log("Gestionnaire d'authentification QGIS désactivé : "
             "session Farois non mémorisée.")
        return ""
    config = QgsAuthMethodConfig(AUTHCFG_METHOD)
    config.setName(AUTHCFG_NAME)
    config.setConfig("username", str(email))
    config.setConfig("password", str(refresh_token))
    ok, stored = _outcome(manager.storeAuthenticationConfig(config), config)
    authcfg = str(stored.id() or "") if ok else ""
    if not authcfg:
        _log("Session Farois non mémorisée (gestionnaire d'authentification "
             "QGIS verrouillé ou refusé).")
    return authcfg


def _delete_config(manager, authcfg):
    """True si la configuration n'existe plus (supprimée, ou déjà absente).

    La suppression ne demande pas le mot de passe maître QGIS.
    """
    if manager.isDisabled():
        return False
    if authcfg not in manager.configIds():
        return True
    return bool(manager.removeAuthenticationConfig(authcfg))


class QgisSessionStore:
    """Configuration « Basic » du gestionnaire d'authentification QGIS.

    username = adresse mail, password = jeton de rafraîchissement ; l'identifiant
    de la configuration est gardé dans QgsSettings (SETTINGS_KEY). Toute erreur
    du gestionnaire (désactivé, mot de passe maître refusé…) est avalée : load()
    renvoie None, save() et clear() ne lèvent pas, un message (type d'erreur
    seulement) va au journal QGIS. Un save() en échec efface la session mémorisée
    auparavant : une ancienne identité n'est jamais reprise à la place de la nouvelle.
    """

    def load(self):
        try:
            from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

            settings = QgsSettings()
            authcfg = _saved_id(settings)
            if not authcfg:
                return None
            manager = QgsApplication.authManager()
            if manager.isDisabled():
                _log("Gestionnaire d'authentification QGIS désactivé : "
                     "session Farois mémorisée inutilisable.")
                return None
            if authcfg not in manager.configIds():
                settings.remove(SETTINGS_KEY)
                return None
            config = QgsAuthMethodConfig()
            ok, config = _outcome(manager.loadAuthenticationConfig(authcfg, config, True), config)
            if not ok:
                _log("Session Farois mémorisée illisible (mot de passe maître QGIS "
                     "non fourni ?) : connexion automatique impossible.")
                return None
            email = str(config.config("username") or "")
            refresh_token = str(config.config("password") or "")
            return (email, refresh_token) if refresh_token else None
        except Exception as exc:
            _log(f"Session Farois mémorisée indisponible ({type(exc).__name__}).")
            return None

    def save(self, email, refresh_token):
        try:
            from qgis.core import QgsApplication, QgsSettings

            manager, settings = QgsApplication.authManager(), QgsSettings()
            previous = _saved_id(settings)
        except Exception as exc:
            _log(f"Session Farois non mémorisée ({type(exc).__name__}).")
            return
        try:
            authcfg = _store(manager, email, refresh_token)
        except Exception as exc:
            _log(f"Session Farois non mémorisée ({type(exc).__name__}).")
            authcfg = ""
        try:
            if authcfg:
                settings.setValue(SETTINGS_KEY, authcfg)
                if previous and previous != authcfg:
                    _delete_config(manager, previous)
            elif previous:
                # Échec : l'identité mémorisée auparavant ne doit pas être reprise.
                settings.remove(SETTINGS_KEY)
                _delete_config(manager, previous)
        except Exception as exc:
            _log(f"Session Farois précédente non effacée ({type(exc).__name__}).")

    def clear(self):
        """Supprime la configuration, puis la clé ; la clé reste si la suppression
        échoue, pour qu'un clear() ultérieur réessaie."""
        try:
            from qgis.core import QgsApplication, QgsSettings

            settings = QgsSettings()
            authcfg = _saved_id(settings)
            if not authcfg:
                return
            if _delete_config(QgsApplication.authManager(), authcfg):
                settings.remove(SETTINGS_KEY)
            else:
                _log("Session Farois mémorisée non effacée (gestionnaire "
                     "d'authentification QGIS indisponible) : nouvel essai au prochain "
                     "effacement.")
        except Exception as exc:
            _log(f"Session Farois mémorisée non effacée ({type(exc).__name__}) : "
                 "nouvel essai au prochain effacement.")
