"""Client HTTP minimal de l'API Farois (annulation admin, spec 2026-10-15).

Stdlib uniquement (urllib). Le jeton Bearer reste en mémoire : il n'est jamais
écrit dans les paramètres QGIS ni sur disque ; le mot de passe n'est jamais conservé.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_API_URL = "http://192.168.160.31:8080"
SETTINGS_KEY = "farois_audit_rollback/api_url"
TIMEOUT_S = 10
ADMIN_ROLES = frozenset({"ADMIN", "MANAGER"})


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


def _decode(raw):
    try:
        return json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, ValueError):
        raise FaroisApiUnavailable(
            "Réponse inattendue de l'API Farois (pas du JSON)."
        ) from None


class FaroisApiClient:
    def __init__(self, base_url, opener=None):
        self.base_url = str(base_url).rstrip("/")
        self._opener = opener or urllib.request.build_opener()
        self._token = None
        self.profile = None

    @property
    def connected(self):
        return self._token is not None and self.profile is not None

    @property
    def is_admin(self):
        return self.connected and self.profile.is_admin

    def login(self, email, password):
        self.logout()
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
            raise self._http_error(exc) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FaroisApiUnavailable(
                f"API Farois injoignable ({self.base_url})."
            ) from exc

    def _http_error(self, exc):
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = None
        detail = payload.get("detail") if isinstance(payload, dict) else None
        message = detail.get("message") if isinstance(detail, dict) else detail
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
        if exc.code >= 500 or payload is None:
            return FaroisApiUnavailable(message, status=exc.code, detail=detail)
        return FaroisApiError(message, status=exc.code, detail=detail)
