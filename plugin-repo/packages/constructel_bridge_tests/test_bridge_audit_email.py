"""Stub-level tests: Bridge sets PGOPTIONS so that every NEW libpq
connection of the QGIS process carries app.current_user=<email>
(spec 2026-10-15-bridge-audit-email-design.md). No real QGIS.

Same fixture pattern as test_bridge1b_wiring.py: the stub package lives in
constructel_bridge_tests/stubs/ and each test re-imports bridge_plugin so
the stub's shared QgsSettings store starts empty.
"""
import base64
import importlib
import inspect
import json
import os
import sys
import types
from pathlib import Path

import pytest

STUBS_DIR = Path(__file__).resolve().parent / "stubs"
PLUGIN_DIR = Path(__file__).resolve().parent.parent / "constructel_bridge"
CREDENTIALS_PATH = PLUGIN_DIR / "credentials.json"
_FIXTURE_CREDENTIALS = {
    "wyre": {
        "host": "test-host.invalid",
        "port": 5432,
        "dbname": "test_db",
        "user": "test_user",
        "password": base64.b64encode(b"test").decode(),
    }
}
EMAIL = "simonducourneau@constructel.be"


@pytest.fixture
def bp(monkeypatch):
    if str(STUBS_DIR) not in sys.path:
        sys.path.insert(0, str(STUBS_DIR))
    pre_existing = CREDENTIALS_PATH.exists()
    if not pre_existing:
        CREDENTIALS_PATH.write_text(json.dumps(_FIXTURE_CREDENTIALS))
    # setenv puis delenv : monkeypatch mémorise l'état initial et le restaure à
    # la fin du test, même si le code testé écrit os.environ directement.
    monkeypatch.setenv("PGOPTIONS", "placeholder")
    monkeypatch.delenv("PGOPTIONS")
    for mod_name in list(sys.modules):
        if mod_name == "constructel_bridge.bridge_plugin" or mod_name.startswith("qgis"):
            del sys.modules[mod_name]
    module = importlib.import_module("constructel_bridge.bridge_plugin")
    yield module
    if not pre_existing:
        CREDENTIALS_PATH.unlink()


class _Log:
    def __init__(self):
        self.records = []

    def __call__(self, message, level=0):
        self.records.append((message, level))


class _FakeCursor:
    """Answers the queries of _register_bridge_user / _refresh_audit_identity."""

    def __init__(self, existing_row, inserted_row=None, refreshed_email=None):
        self.existing_row = existing_row
        self.inserted_row = inserted_row
        self.refreshed_email = refreshed_email
        self.executed = []
        self._next = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "FROM ref.users WHERE username" in sql:
            self._next = self.existing_row
        elif "INSERT INTO ref.users" in sql:
            self._next = self.inserted_row
        elif "SELECT email FROM ref.users WHERE id" in sql:
            self._next = (self.refreshed_email,)
        else:
            self._next = None

    def fetchone(self):
        return self._next

    def close(self):
        pass


class _FakeConn:
    closed = False

    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def _fake_plugin(bp, cursor, username="SimonDucourneau"):
    plugin = types.SimpleNamespace(
        _conn=_FakeConn(cursor), _bridge_user=None, _bridge_user_id=None,
        _bridge_user_email=None, _log=_Log(),
    )
    plugin._get_qgis_username = lambda: username
    plugin._set_app_user = lambda value: plugin.__dict__.setdefault("app_user_set", value)
    return plugin


# --- _apply_audit_identity ---------------------------------------------

def test_apply_sets_pgoptions_and_caches_email(bp):
    from qgis.core import QgsSettings
    log = _Log()
    assert bp._apply_audit_identity(EMAIL, log) is True
    assert os.environ["PGOPTIONS"] == f"-c app.current_user={EMAIL}"
    assert QgsSettings().value(bp.AUDIT_EMAIL_KEY) == EMAIL


def test_apply_preserves_workstation_pgoptions(bp, monkeypatch):
    monkeypatch.setenv("PGOPTIONS", "-c search_path=wyre")
    assert bp._apply_audit_identity(EMAIL, _Log()) is True
    assert os.environ["PGOPTIONS"] == f"-c search_path=wyre -c app.current_user={EMAIL}"


@pytest.mark.parametrize("bad", [None, "", "pas une adresse", "a b@constructel.be"])
def test_apply_invalid_email_sets_nothing_and_warns(bp, bad):
    from qgis.core import Qgis, QgsSettings
    log = _Log()
    assert bp._apply_audit_identity(bad, log) is False
    assert "PGOPTIONS" not in os.environ
    assert QgsSettings().value(bp.AUDIT_EMAIL_KEY) is None
    assert any(level == Qgis.MessageLevel.Warning for _, level in log.records)


@pytest.mark.parametrize("off", [False, "false"])
def test_switch_off_is_respected_bool_or_string(bp, off):
    from qgis.core import QgsSettings
    QgsSettings().setValue(bp.AUDIT_EMAIL_SWITCH_KEY, off)
    assert bp._apply_audit_identity(EMAIL, _Log()) is False
    assert "PGOPTIONS" not in os.environ


def test_cached_identity_applied_at_startup(bp):
    from qgis.core import QgsSettings
    assert bp._apply_cached_audit_identity(_Log()) is False  # rien en cache
    QgsSettings().setValue(bp.AUDIT_EMAIL_KEY, EMAIL)
    assert bp._apply_cached_audit_identity(_Log()) is True
    assert os.environ["PGOPTIONS"] == f"-c app.current_user={EMAIL}"


def test_initgui_applies_cache_before_anything_else(bp):
    src = inspect.getsource(bp.ConstructelBridgePlugin.initGui)
    first_call = src.index("_apply_cached_audit_identity(")
    assert first_call < src.index("init_language(")
    # Revue 29/10 (I13) : la connexion est differee, l'adresse posee avant.
    assert first_call < src.index("self._schedule_startup_connection(")


# --- _register_bridge_user ---------------------------------------------

def test_register_existing_user_applies_email(bp):
    cur = _FakeCursor(existing_row=("11111111-1111-1111-1111-111111111111", "SimonDucourneau", EMAIL))
    plugin = _fake_plugin(bp, cur)
    bp.ConstructelBridgePlugin._register_bridge_user(plugin)
    assert plugin._bridge_user_email == EMAIL
    assert os.environ["PGOPTIONS"] == f"-c app.current_user={EMAIL}"
    assert plugin.app_user_set == EMAIL


def test_register_new_user_applies_returned_email(bp):
    cur = _FakeCursor(existing_row=None,
                      inserted_row=("22222222-2222-2222-2222-222222222222", "newbie@constructel.be"))
    plugin = _fake_plugin(bp, cur, username="newbie")
    bp.ConstructelBridgePlugin._register_bridge_user(plugin)
    assert plugin._bridge_user_email == "newbie@constructel.be"
    assert os.environ["PGOPTIONS"] == "-c app.current_user=newbie@constructel.be"
    assert any("RETURNING id, email" in sql for sql, _ in cur.executed)


def test_register_user_without_email_does_not_block(bp):
    cur = _FakeCursor(existing_row=("33333333-3333-3333-3333-333333333333", "noemail", None))
    plugin = _fake_plugin(bp, cur, username="noemail")
    bp.ConstructelBridgePlugin._register_bridge_user(plugin)
    assert "PGOPTIONS" not in os.environ
    assert plugin.app_user_set == "noemail"  # repli historique : nom d'utilisateur
    assert plugin._bridge_user_id == "33333333-3333-3333-3333-333333333333"


# --- _refresh_audit_identity (après l'assistant d'accueil) ---------------

def test_refresh_after_onboarding_applies_new_email(bp):
    cur = _FakeCursor(existing_row=None, refreshed_email="nouvelle.adresse@constructel.be")
    plugin = _fake_plugin(bp, cur)
    plugin._bridge_user_id = "11111111-1111-1111-1111-111111111111"
    plugin._bridge_user_email = EMAIL
    bp.ConstructelBridgePlugin._refresh_audit_identity(plugin)
    assert plugin._bridge_user_email == "nouvelle.adresse@constructel.be"
    assert os.environ["PGOPTIONS"] == "-c app.current_user=nouvelle.adresse@constructel.be"


def test_run_onboarding_refreshes_identity_after_wizard(bp):
    src = inspect.getsource(bp.ConstructelBridgePlugin._run_onboarding)
    assert src.index("wizard.exec()") < src.index("self._refresh_audit_identity()")


# --- _on_before_commit --------------------------------------------------

def test_before_commit_tags_bridge_connection_with_email(bp):
    src = inspect.getsource(bp.ConstructelBridgePlugin._on_before_commit)
    assert "self._bridge_user_email or self._bridge_user" in src


# --- Revue finale #2 : une adresse refusée retire l'ancienne ---------------

def test_invalid_email_removes_stale_cached_address(bp, monkeypatch):
    from qgis.core import QgsSettings
    QgsSettings().setValue(bp.AUDIT_EMAIL_KEY, "ancien@constructel.be")
    monkeypatch.setenv("PGOPTIONS", "-c search_path=wyre -c app.current_user=ancien@constructel.be")
    assert bp._apply_audit_identity("hélènedupré@constructel.be", _Log()) is False
    assert os.environ["PGOPTIONS"] == "-c search_path=wyre"
    assert QgsSettings().value(bp.AUDIT_EMAIL_KEY) is None


def test_register_with_invalid_email_does_not_keep_cached_address(bp):
    from qgis.core import QgsSettings
    QgsSettings().setValue(bp.AUDIT_EMAIL_KEY, EMAIL)
    assert bp._apply_cached_audit_identity(_Log()) is True  # posée au démarrage
    cur = _FakeCursor(existing_row=("44444444-4444-4444-4444-444444444444", "autre", "pas une adresse"))
    plugin = _fake_plugin(bp, cur, username="autre")
    bp.ConstructelBridgePlugin._register_bridge_user(plugin)
    assert "PGOPTIONS" not in os.environ
    assert QgsSettings().value(bp.AUDIT_EMAIL_KEY) is None


# --- Revue finale #12 : jamais d'exception vers initGui / _connect ---------

class _ExplodingSettings:
    def value(self, *args, **kwargs):
        raise TypeError("unable to convert a QVariant")

    def setValue(self, *args, **kwargs):
        raise TypeError("unable to convert a QVariant")

    def remove(self, *args, **kwargs):
        raise TypeError("unable to convert a QVariant")


def test_apply_never_raises(bp, monkeypatch):
    from qgis.core import Qgis
    monkeypatch.setattr(bp, "QgsSettings", _ExplodingSettings)
    log = _Log()
    assert bp._apply_audit_identity(EMAIL, log) is False
    assert bp._apply_cached_audit_identity(log) is False
    assert any(level == Qgis.MessageLevel.Warning for _, level in log.records)
