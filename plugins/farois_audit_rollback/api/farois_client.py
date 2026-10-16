"""Client HTTP minimal de l'API Farois (annulation admin, spec 2026-10-15).

Stdlib uniquement (urllib). Le jeton d'accès (Bearer) reste en mémoire. Le jeton
de rafraîchissement (cookie refresh_token du login, 30 jours) aussi, et n'est
confié au magasin de session (session_store) que si l'utilisateur demande « Se
souvenir de moi ». Le mot de passe AD n'est jamais conservé ni transmis au
magasin. Aucun cookie jar : l'en-tête Cookie n'est posé à la main que pour
/auth/refresh, jamais à côté d'un Authorization: Bearer.
"""

import http.client
import http.cookies
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_API_URL = "http://192.168.160.31:8080"
SETTINGS_KEY = "farois_audit_rollback/api_url"
TIMEOUT_S = 10
# Connexion automatique (non interactive) : resume + /me n'attendent pas plus.
RESUME_TIMEOUT_S = 5
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


def _cookie(headers, name):
    """Valeur du cookie `name` dans les en-têtes Set-Cookie (suppressions ignorées)."""
    found = None
    for header in (headers.get_all("Set-Cookie") if headers is not None else None) or ():
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(header)
        except http.cookies.CookieError:
            continue
        morsel = jar.get(name)
        if morsel is not None and morsel.value and morsel["max-age"] != "0":
            found = morsel.value
    return found


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
    def __init__(self, base_url, opener=None, store=None, resume_timeout=RESUME_TIMEOUT_S):
        self.base_url = str(base_url).rstrip("/")
        self._opener = opener or default_opener()
        self.resume_timeout = resume_timeout
        self._store = store  # magasin de session (« Se souvenir de moi ») ou None
        self._token = None
        self._refresh_token = None
        self.profile = None
        # Dernière adresse saisie, en mémoire seulement : pré-remplit la reconnexion.
        self.last_email = ""

    @property
    def connected(self):
        return self._token is not None and self.profile is not None

    @property
    def is_admin(self):
        return self.connected and self.profile.is_admin

    def login(self, email, password, remember=False):
        self.logout()
        self.last_email = email
        try:
            data, headers = self._send(
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
        self._refresh_token = _cookie(headers, "refresh_token")
        try:
            self._load_profile(email)
        except FaroisNotAuthenticated as exc:
            raise FaroisNotAuthenticated(
                "Identifiants Farois refusés.", status=exc.status, detail=exc.detail
            ) from None
        if self._store is not None:
            if remember and self._refresh_token:
                self._store.save(email, self._refresh_token)
            else:
                self._store.clear()
        return self.profile

    def resume(self, refresh_token):
        """Reprend une session mémorisée : /auth/refresh (cookie seul) puis /me.

        Non interactif : délai court (resume_timeout) pour ces deux requêtes.
        """
        self.forget()
        self._token = self._refresh(refresh_token, timeout=self.resume_timeout)
        self._refresh_token = refresh_token
        self._load_profile("", timeout=self.resume_timeout)
        self.last_email = self.profile.email or self.last_email
        return self.profile

    def logout(self):
        """Révoque la session côté serveur (erreurs ignorées), puis l'oublie."""
        if self._token is not None:
            try:
                self._request("POST", "/api/v1/auth/logout")
            except Exception:
                pass
        self.forget()

    def forget(self):
        """Oublie jetons et profil sans rien révoquer (déchargement du plugin)."""
        self._token = None
        self._refresh_token = None
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

    def _load_profile(self, fallback_email, timeout=TIMEOUT_S):
        try:
            me, _ = self._send("GET", "/api/v1/auth/me", timeout=timeout)
        except Exception:
            self.forget()
            raise
        me = me if isinstance(me, dict) else {}
        self.profile = FaroisProfile(
            email=str(me.get("email") or fallback_email), role=str(me.get("role") or "")
        )

    def _refresh(self, refresh_token, timeout=TIMEOUT_S):
        """Nouveau jeton d'accès : cookie refresh_token seul, sans Authorization."""
        token = str(refresh_token or "")
        if not token or any(char in token for char in ";,\r\n \t\""):
            raise FaroisNotAuthenticated("Session Farois mémorisée invalide.", status=401)
        _, headers = self._send(
            "POST", "/api/v1/auth/refresh", auth=False,
            cookie=f"refresh_token={token}", timeout=timeout,
        )
        access_token = _cookie(headers, "access_token")
        if not access_token:
            raise FaroisApiError("Réponse de renouvellement Farois invalide.")
        return access_token

    def _request(self, method, path, payload=None, auth=True):
        if auth and self._token is None:
            raise FaroisNotAuthenticated("Connectez-vous à Farois.", status=401)
        try:
            return self._send(method, path, payload, auth)[0]
        except FaroisNotAuthenticated:
            if not (auth and self._renew_access_token()):
                self.forget()
                raise
        # Une requête refusée en 401 n'a pas été exécutée : UNE seule relance.
        try:
            return self._send(method, path, payload, auth)[0]
        except FaroisNotAuthenticated:
            self.forget()
            raise

    def _renew_access_token(self):
        """Rafraîchissement silencieux, une seule tentative ; False si impossible."""
        if self._refresh_token is None:
            return False
        try:
            self._token = self._refresh(self._refresh_token)
        except FaroisApiError:
            return False
        return True

    def _send(self, method, path, payload=None, auth=True, cookie=None, timeout=TIMEOUT_S):
        """Une requête, sans relance : (corps JSON décodé, en-têtes de réponse)."""
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=body, method=method)
        request.add_header("Accept", "application/json")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        if auth:
            request.add_header("Authorization", f"Bearer {self._token}")
        if cookie is not None:
            request.add_header("Cookie", cookie)
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return _decode(response.read()), getattr(response, "headers", None)
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
        if exc.code == 401:  # session oubliée par _request (après un éventuel refresh)
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
