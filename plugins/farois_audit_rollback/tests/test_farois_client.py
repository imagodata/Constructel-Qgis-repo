"""Client HTTP de l'API Farois : jeton en mémoire, erreurs typées (spec 2026-10-15)."""

import io
import json
import sys
import urllib.error
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
