"""Client HTTP de l'API Farois : jeton en mémoire, erreurs typées (spec 2026-10-15)."""

import email
import http.client
import io
import json
import sys
import urllib.error
import urllib.request
import urllib.response
from pathlib import Path
from types import ModuleType

import pytest

from plugins.farois_audit_rollback.api import farois_client as fc

ME = {"id": "u-1", "email": "simon@constructel.example.be", "role": "ADMIN"}


class Response:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Opener:
    """Rejoue des réponses dans l'ordre et garde les requêtes envoyées."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, Response):
            return answer
        return Response(answer if isinstance(answer, bytes) else json.dumps(answer).encode())


def http_error(code, payload):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return urllib.error.HTTPError("http://api", code, "err", {}, io.BytesIO(body))


def logged_in(*answers):
    opener = Opener({"access_token": "tok", "token_type": "bearer"}, ME, *answers)
    client = fc.FaroisApiClient("http://api:8080/", opener=opener)
    client.login(ME["email"], "secret")
    return client, opener


def test_login_keeps_token_in_memory_and_reads_role():
    client, opener = logged_in()
    assert client.connected and client.is_admin
    assert client.profile == fc.FaroisProfile(email=ME["email"], role="ADMIN")
    login, me = opener.requests[0][0], opener.requests[1][0]
    assert login.full_url == "http://api:8080/api/v1/auth/login"
    assert json.loads(login.data) == {"email": ME["email"], "password": "secret"}
    assert login.get_header("Authorization") is None
    assert me.get_header("Authorization") == "Bearer tok"
    assert all(timeout == fc.TIMEOUT_S for _, timeout in opener.requests)


def test_password_and_token_are_never_persisted():
    client, _ = logged_in()
    state = {k: v for k, v in vars(client).items() if k != "_opener"}
    assert "secret" not in repr(state)
    source = Path(fc.__file__).read_text(encoding="utf-8")
    assert "setValue" not in source and "QgsAuthManager" not in source


def test_revert_change_posts_mode_and_reason_with_bearer():
    client, opener = logged_in({"change_id": "c-1", "reverted": ["label"], "conflicts": []})
    assert client.revert_change("c-1", "FIELD", "motif")["reverted"] == ["label"]
    request = opener.requests[-1][0]
    assert request.full_url == "http://api:8080/api/v1/history/changes/c-1/revert"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"mode": "FIELD", "reason": "motif"}
    assert request.get_header("Authorization") == "Bearer tok"


def test_revert_transaction_path():
    client, opener = logged_in({"transaction_id": "t-1", "changes": []})
    client.revert_transaction("t-1", "FORCE", "motif")
    assert opener.requests[-1][0].full_url == "http://api:8080/api/v1/history/transactions/t-1/revert"


def test_expired_token_logs_out_and_raises_not_authenticated():
    client, _ = logged_in(http_error(401, {"detail": "Session expirée"}))
    with pytest.raises(fc.FaroisNotAuthenticated):
        client.revert_change("c-1", "FIELD", "motif")
    assert not client.connected


def test_call_without_login_never_hits_the_network():
    opener = Opener()
    client = fc.FaroisApiClient("http://api", opener=opener)
    with pytest.raises(fc.FaroisNotAuthenticated):
        client.revert_change("c-1", "FIELD", "motif")
    assert opener.requests == []


def test_unreachable_api_is_typed_and_mentions_url():
    client, _ = logged_in(urllib.error.URLError("connection refused"))
    with pytest.raises(fc.FaroisApiUnavailable, match="http://api:8080"):
        client.revert_change("c-1", "FIELD", "motif")


def test_timeout_error_is_unavailable():
    client, _ = logged_in(TimeoutError("timed out"))
    with pytest.raises(fc.FaroisApiUnavailable):
        client.revert_change("c-1", "FIELD", "motif")


def test_non_json_answer_is_unavailable_not_a_crash():
    client, _ = logged_in(b"<html>502 Bad Gateway</html>")
    with pytest.raises(fc.FaroisApiUnavailable):
        client.revert_change("c-1", "FIELD", "motif")


def test_html_error_page_is_unavailable():
    client, _ = logged_in(http_error(502, b"<html>Bad Gateway</html>"))
    with pytest.raises(fc.FaroisApiUnavailable):
        client.revert_change("c-1", "FIELD", "motif")


def test_server_error_with_foreign_json_body_stays_uncertain():
    client, _ = logged_in(http_error(502, {"message": "upstream unavailable"}))
    with pytest.raises(fc.FaroisApiUnavailable):
        client.revert_change("c-1", "FIELD", "motif")


def test_conflict_is_forceable_only_for_real_conflicts():
    report = {"conflicts": [{"column": "label"}]}
    client, _ = logged_in(
        http_error(409, {"detail": {"message": "Conflit : rien n'a été annulé.",
                                    "reason": "conflict", "report": report}}),
        http_error(409, {"detail": {"message": "Modification déjà annulée.",
                                    "reason": "already_undone", "engine": "deja annule"}}),
    )
    with pytest.raises(fc.FaroisConflict) as first:
        client.revert_change("c-1", "FIELD", "motif")
    assert first.value.forceable and first.value.report == report
    with pytest.raises(fc.FaroisConflict) as second:
        client.revert_change("c-1", "FIELD", "motif")
    assert not second.value.forceable
    assert "Modification déjà annulée." in str(second.value)


def test_forbidden_keeps_server_message():
    client, _ = logged_in(http_error(403, {"detail": "Role requis: ADMIN, MANAGER. Votre role: VIEWER"}))
    with pytest.raises(fc.FaroisForbidden, match="Votre role: VIEWER"):
        client.revert_change("c-1", "FIELD", "motif")


def test_wrong_password_is_reported_as_refused_credentials():
    opener = Opener(http_error(401, {"detail": "Identifiants invalides"}))
    client = fc.FaroisApiClient("http://api", opener=opener)
    with pytest.raises(fc.FaroisNotAuthenticated, match="Identifiants Farois refusés"):
        client.login("a@b.be", "mauvais")
    assert not client.connected


def test_viewer_profile_is_not_admin():
    opener = Opener({"access_token": "tok"}, dict(ME, role="VIEWER"))
    client = fc.FaroisApiClient("http://api", opener=opener)
    profile = client.login(ME["email"], "secret")
    assert profile.role == "VIEWER"
    assert client.connected and not client.is_admin


def test_api_url_defaults_without_qgis_settings(monkeypatch):
    monkeypatch.setitem(sys.modules, "qgis.core", ModuleType("qgis.core"))
    assert fc.api_url() == "http://192.168.160.31:8080"


class Truncated(Response):
    def read(self):
        raise http.client.IncompleteRead(b"{", 10)


class Network(urllib.request.BaseHandler):
    """Réseau factice branché sur l'opener par défaut du client (avant HTTPHandler)."""

    handler_order = 100

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def http_open(self, request):
        self.requests.append(request)
        code, body, headers = self.answers.pop(0)
        message = email.message_from_string(
            "".join(f"{key}: {value}\n" for key, value in headers.items()) + "\n"
        )
        response = urllib.response.addinfourl(
            io.BytesIO(json.dumps(body).encode()), message, request.full_url, code
        )
        response.msg = "fixture"
        return response


def test_default_opener_ignores_system_proxies(monkeypatch):
    for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
        monkeypatch.setenv(name, "http://proxy.example:3128")
    def proxies(opener):
        return [
            h.proxies for h in opener.handlers
            if isinstance(h, urllib.request.ProxyHandler) and h.proxies
        ]

    # Un opener urllib standard prendrait bien ce proxy d'environnement…
    assert proxies(urllib.request.build_opener())
    # … celui du client non (ProxyHandler({}) remplace le ProxyHandler par défaut).
    assert proxies(fc.FaroisApiClient("http://api")._opener) == []


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_redirect_is_refused_and_never_followed(code):
    network = Network(
        (200, {"access_token": "tok"}, {}),
        (200, ME, {}),
        (code, {}, {"Location": "http://elsewhere.example/api/v1/history/changes/c-1/revert"}),
    )
    client = fc.FaroisApiClient("http://api:8080")
    client._opener.add_handler(network)
    client.login(ME["email"], "secret")
    with pytest.raises(fc.FaroisApiError, match="Redirection refusée") as err:
        client.revert_change("c-1", "FIELD", "motif")
    assert not isinstance(err.value, fc.FaroisApiUnavailable)
    assert err.value.status == code
    assert len(network.requests) == 3  # rien n'a suivi la redirection
    assert all(r.host == "api:8080" for r in network.requests)


@pytest.mark.parametrize(
    "payload",
    [
        {"detail": {"message": "Délai dépassé, réessayez.", "reason": "timeout",
                    "engine": "canceling statement due to statement timeout"}},
        {"detail": "Erreur interne du serveur"},
    ],
)
@pytest.mark.parametrize("code", [500, 503])
def test_server_error_with_json_body_says_nothing_was_undone(code, payload):
    client, _ = logged_in(http_error(code, payload))
    with pytest.raises(fc.FaroisApiError) as err:
        client.revert_change("c-1", "FIELD", "motif")
    assert not isinstance(err.value, fc.FaroisApiUnavailable)
    assert "Rien n'a été annulé" in str(err.value)
    assert "incertain" not in str(err.value)
    assert err.value.status == code


@pytest.mark.parametrize(
    "failure",
    [Truncated(b""), http.client.BadStatusLine("garbage"), http.client.IncompleteRead(b"")],
)
def test_truncated_or_malformed_http_answer_is_unavailable(failure):
    client, _ = logged_in(failure)
    with pytest.raises(fc.FaroisApiUnavailable, match="http://api:8080"):
        client.revert_change("c-1", "FIELD", "motif")


def test_validation_error_list_is_shown_as_its_first_message():
    client, _ = logged_in(http_error(422, {"detail": [
        {"type": "value_error", "loc": ["body", "reason"],
         "msg": "Value error, Motif trop long (500 caractères maximum)", "input": "x"},
        {"type": "enum", "loc": ["body", "mode"], "msg": "Input should be 'FIELD'"},
    ]}))
    with pytest.raises(fc.FaroisApiError) as err:
        client.revert_change("c-1", "FIELD", "motif")
    assert str(err.value) == "Motif trop long (500 caractères maximum)"
    assert err.value.status == 422


def test_401_on_me_during_login_means_refused_credentials():
    opener = Opener({"access_token": "tok"}, http_error(401, {"detail": "Jeton invalide"}))
    client = fc.FaroisApiClient("http://api", opener=opener)
    with pytest.raises(fc.FaroisNotAuthenticated) as err:
        client.login(ME["email"], "secret")
    assert str(err.value) == "Identifiants Farois refusés."
    assert not client.connected


def test_last_email_is_remembered_in_memory_after_expiry_and_failed_login():
    client, _ = logged_in(http_error(401, {"detail": "Session expirée"}))
    with pytest.raises(fc.FaroisNotAuthenticated):
        client.revert_change("c-1", "FIELD", "motif")
    assert not client.connected and client.last_email == ME["email"]
    client._opener.answers.append(http_error(401, {"detail": "Identifiants invalides"}))
    with pytest.raises(fc.FaroisNotAuthenticated):
        client.login("autre@constructel.example.be", "mauvais")
    assert client.last_email == "autre@constructel.example.be"
    assert "mauvais" not in repr(vars(client))
