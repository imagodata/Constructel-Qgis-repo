"""Client HTTP minimal de l'API Farois (annulation admin, spec 2026-10-15).

Stdlib uniquement (urllib). Le jeton Bearer reste en mémoire : il n'est jamais
écrit dans les paramètres QGIS ni sur disque ; le mot de passe n'est jamais conservé.
"""

import http.client
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_API_URL = "http://192.168.160.31:8080"
SETTINGS_KEY = "farois_audit_rollback/api_url"
TIMEOUT_S = 10
ADMIN_ROLES = frozenset({"ADMIN", "MANAGER"})
REASON_MAX_LENGTH = 500  # contrat API : motif de 1 à 500 caractères après strip()


class FaroisApiError(Exception):
    """Erreur de l'API Farois, avec un message utilisateur en français."""

    def __init__(self, message, status=None, detail=None):
        super().__init__(message)
        self.status, self.detail = status, detail


class FaroisApiUnavailable(FaroisApiError):
    pass


class FaroisNotAuthenticated(FaroisApiError):
    pass


class FaroisForbidden(FaroisApiError):
    pass


class FaroisConflict(FaroisApiError):
    @property
    def forceable(self):
        return isinstance(self.detail, dict) and self.detail.get("reason") == "conflict"

    @property
    def report(self):
        return self.detail.get("report") if isinstance(self.detail, dict) else None


@dataclass(frozen=True)
class FaroisProfile:
    email: str
    role: str

    @property
    def is_admin(self):
        return self.role in ADMIN_ROLES


def api_url():
    try:
        from qgis.core import QgsSettings

        value = QgsSettings().value(SETTINGS_KEY, DEFAULT_API_URL)
    except ImportError:
        value = DEFAULT_API_URL
    return str(value or DEFAULT_API_URL).rstrip("/")


def _change_had_effect(change):
    return isinstance(change, dict) and bool(
        (isinstance(change.get("reverted"), list) and change["reverted"])
        or change.get("restored") is True
        or change.get("deleted") is True
    )


def undo_had_effect(report):
    """Rapport 200 de l'API (déjà commité) : au moins un effet ?

    Modification : reverted non vide, ou restored / deleted vrai. Transaction :
    au moins un membre de changes qui remplit cette condition. Réservé au chemin
    API ; le chemin PostgreSQL garde AuditRepository._validate_result (strict,
    avant COMMIT).
    """
    if not isinstance(report, dict):
        return False
    if "changes" in report:
        changes = report["changes"]
        return isinstance(changes, list) and any(map(_change_had_effect, changes))
    return _change_had_effect(report)


def _decode(raw):
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        raise FaroisApiUnavailable(
            "Réponse inattendue de l'API Farois (pas du JSON)."
        ) from None


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Ne suit aucune redirection : le jeton Bearer ne part jamais ailleurs."""

    def _refuse(self, req, fp, code, msg, headers):
        if fp is not None:
            fp.close()
        raise FaroisApiError(
            f"Redirection refusée (HTTP {code}) pour {req.full_url} : vérifiez "
            f"l'URL de l'API Farois (paramètre {SETTINGS_KEY}).",
            status=code,
        )

    http_error_301 = http_error_302 = http_error_303 = _refuse
    http_error_307 = http_error_308 = _refuse


def default_opener():
    # API sur IP LAN : aucun proxy système (ProxyHandler vide), aucune redirection.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _RefuseRedirects())


class FaroisApiClient:
    def __init__(self, base_url, opener=None):
        self.base_url = str(base_url).rstrip("/")
        self._opener = opener or default_opener()
        self._token = None
        self.profile = None
        # Dernière adresse saisie, en mémoire seulement : pré-remplit la reconnexion.
        self.last_email = ""

    @property
    def connected(self):
        return self._token is not None and self.profile is not None

    @property
    def is_admin(self):
        return self.connected and self.profile.is_admin

    def login(self, email, password):
        self.logout()
        self.last_email = email
        try:
            data = self._request(
                "POST", "/api/v1/auth/login",
                {"email": email, "password": password}, auth=False,
            )
        except FaroisNotAuthenticated as exc:
            raise FaroisNotAuthenticated(
                "Identifiants Farois refusés.", status=exc.status, detail=exc.detail
            ) from None
        token = data.get("access_token") if isinstance(data, dict) else None
        if not token:
            raise FaroisApiError("Réponse de connexion Farois invalide.")
        self._token = token
        try:
            me = self._request("GET", "/api/v1/auth/me")
        except FaroisNotAuthenticated as exc:
            self.logout()
            raise FaroisNotAuthenticated(
                "Identifiants Farois refusés.", status=exc.status, detail=exc.detail
            ) from None
        except Exception:
            self.logout()
            raise
        self.profile = FaroisProfile(
            email=str(me.get("email") or email), role=str(me.get("role") or "")
        )
        return self.profile

    def logout(self):
        self._token = None
        self.profile = None

    def revert_change(self, change_id, mode, reason):
        return self._request(
            "POST", f"/api/v1/history/changes/{change_id}/revert",
            {"mode": mode, "reason": reason},
        )

    def revert_transaction(self, tx_id, mode, reason):
        return self._request(
            "POST", f"/api/v1/history/transactions/{tx_id}/revert",
            {"mode": mode, "reason": reason},
        )

    def _request(self, method, path, payload=None, auth=True):
        if auth and self._token is None:
            raise FaroisNotAuthenticated("Connectez-vous à Farois.", status=401)
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=body, method=method)
        request.add_header("Accept", "application/json")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        if auth:
            request.add_header("Authorization", f"Bearer {self._token}")
        try:
            with self._opener.open(request, timeout=TIMEOUT_S) as response:
                return _decode(response.read())
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc, path) from None
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            http.client.HTTPException,  # IncompleteRead, BadStatusLine… : incertain
        ) as exc:
            raise FaroisApiUnavailable(
                f"API Farois injoignable ({self.base_url})."
            ) from exc

    def _http_error(self, exc, path=""):
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = None
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, dict):
            message = detail.get("message")
        elif isinstance(detail, list):  # 422 FastAPI : liste d'erreurs de validation
            first = detail[0] if detail and isinstance(detail[0], dict) else {}
            message = str(first.get("msg") or "").removeprefix("Value error, ")
        else:
            message = detail
        message = str(message or f"Erreur de l'API Farois ({exc.code}).")
        if isinstance(detail, dict) and detail.get("engine"):
            message = f"{message} — {detail['engine']}"
        if exc.code == 401:
            self.logout()
            return FaroisNotAuthenticated(
                "Session Farois expirée : reconnectez-vous.", status=401, detail=detail
            )
        if exc.code == 403:
            return FaroisForbidden(message, status=403, detail=detail)
        if exc.code == 409:
            return FaroisConflict(message, status=409, detail=detail)
        # Seule une réponse JSON de l'API ({"detail": …}) prouve qu'elle a fait
        # ROLLBACK ; page HTML d'un proxy ou corps illisible : résultat incertain.
        api_answered = isinstance(payload, dict) and "detail" in payload
        if payload is None or (exc.code >= 500 and not api_answered):
            return FaroisApiUnavailable(message, status=exc.code, detail=detail)
        if exc.code >= 500 and path.endswith("/revert"):
            message = f"{message}\nRien n'a été annulé (erreur {exc.code} de l'API Farois)."
        return FaroisApiError(message, status=exc.code, detail=detail)
