"""Stub-level wiring tests for Bridge 1b (mTLS activation).

Exercises bridge_plugin.py's mTLS helpers (PKI-Paths authcfg lifecycle +
_mtls_active) against the recording qgis stub — no real QGIS, no real Auth
Manager. The stub's QSettings/auth state is shared across instances like the
real API; each test gets a virgin stub via the deferred-reimport `bp`
fixture below (same pattern as test_bridge_plugin_import.py).

The stub package lives in constructel_bridge_tests/stubs/, a SIBLING of
constructel_bridge/ (not inside PLUGIN_DIR) — never bundled into the
distributed plugin zip. Do not move this file or the stub package inside
constructel_bridge/.
"""
import base64
import importlib
import json
import stat
import subprocess
import sys
import types
from pathlib import Path

import pytest

from constructel_bridge.bridge_mtls import (
    MTLS_SETTINGS_KEYS,
    CertValidationResult,
    build_pki_paths_authcfg_config,
)

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


@pytest.fixture
def qgis_stub_path():
    if str(STUBS_DIR) not in sys.path:
        sys.path.insert(0, str(STUBS_DIR))
    yield


@pytest.fixture
def credentials_json_present():
    """Same guarantee as test_bridge_plugin_import.py: credentials.json
    exists for the test without ever touching a pre-existing real file."""
    pre_existing = CREDENTIALS_PATH.exists()
    if not pre_existing:
        CREDENTIALS_PATH.write_text(json.dumps(_FIXTURE_CREDENTIALS))
    yield
    if not pre_existing:
        CREDENTIALS_PATH.unlink()


@pytest.fixture
def bp(qgis_stub_path, credentials_json_present):
    """Fresh bridge_plugin module with stubs installed (deferred import,
    after fixtures — never at collection time). Re-importing per test also
    resets the stub's shared QSettings/auth state."""
    for mod_name in list(sys.modules):
        if mod_name == "constructel_bridge.bridge_plugin" or mod_name.startswith("qgis"):
            del sys.modules[mod_name]
    return importlib.import_module("constructel_bridge.bridge_plugin")


def _openssl(*args):
    subprocess.run(("openssl",) + args, check=True, capture_output=True)


@pytest.fixture
def _mtls_bundle(tmp_path):
    """A real CA + client cert with clientAuth EKU, valid for 1 day."""
    ca_key = tmp_path / "ca.key"
    ca_crt = tmp_path / "ca.crt"
    c_key = tmp_path / "c.key"
    c_csr = tmp_path / "c.csr"
    c_crt = tmp_path / "c.crt"
    ext = tmp_path / "ext.cnf"
    ext.write_text("extendedKeyUsage = clientAuth\n")
    _openssl("req", "-new", "-x509", "-days", "1", "-nodes",
             "-subj", "/CN=t-ca", "-keyout", str(ca_key), "-out", str(ca_crt))
    _openssl("req", "-new", "-nodes", "-subj", "/CN=t-user",
             "-keyout", str(c_key), "-out", str(c_csr))
    _openssl("x509", "-req", "-in", str(c_csr), "-CA", str(ca_crt),
             "-CAkey", str(ca_key), "-CAcreateserial", "-days", "1",
             "-extfile", str(ext), "-out", str(c_crt))
    return {"cert": str(c_crt), "key": str(c_key), "ca": str(ca_crt)}


def _set_mtls_paths(settings_cls, bundle):
    settings_cls().setValue(MTLS_SETTINGS_KEYS["cert_path"], bundle["cert"])
    settings_cls().setValue(MTLS_SETTINGS_KEYS["key_path"], bundle["key"])
    settings_cls().setValue(MTLS_SETTINGS_KEYS["ca_path"], bundle["ca"])


def _load_probe(auth_mgr):
    """Fresh probe config (mirrors production retrieval: load, no return)."""
    from qgis.core import QgsAuthMethodConfig

    return auth_mgr, QgsAuthMethodConfig()


# --- PKI-Paths authcfg lifecycle ------------------------------------------


def test_store_pki_authcfg_creates_shared_config(bp):
    from qgis.core import QgsApplication, QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["cert_path"], "/certs/u.crt")
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["key_path"], "/certs/u.key")
    cfg_id = bp._store_pki_authcfg()

    assert cfg_id
    assert QgsSettings().value(MTLS_SETTINGS_KEYS["authcfg_id"]) == cfg_id
    auth_mgr, probe = _load_probe(QgsApplication.authManager())
    auth_mgr.loadAuthenticationConfig(cfg_id, probe, True)
    # Parity with the Bridge 1 builder: store and builder must agree.
    expected = build_pki_paths_authcfg_config("constructel_bridge_mtls", "/certs/u.crt", "/certs/u.key")
    assert probe.method() == expected["method"]
    assert probe.name() == expected["name"]
    assert probe.config("certpath") == expected["config"]["certpath"]
    assert probe.config("keypath") == expected["config"]["keypath"]
    # Bug #58179 pin: certificate and key ONLY — never a password.
    assert probe.config("password", "ABSENT") == "ABSENT"


def test_store_pki_authcfg_updates_existing_without_dup(bp):
    from qgis.core import QgsApplication, QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["cert_path"], "/certs/old.crt")
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["key_path"], "/certs/old.key")
    first_id = bp._store_pki_authcfg()
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["cert_path"], "/certs/new.crt")
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["key_path"], "/certs/new.key")
    second_id = bp._store_pki_authcfg()

    assert second_id == first_id
    assert QgsApplication.authManager().configIds() == [first_id]
    auth_mgr, probe = _load_probe(QgsApplication.authManager())
    auth_mgr.loadAuthenticationConfig(first_id, probe, True)
    assert probe.config("certpath") == "/certs/new.crt"
    assert probe.config("keypath") == "/certs/new.key"


def test_store_pki_authcfg_recreates_when_config_deleted(bp):
    # Stale settings id (user deleted the config in Auth Manager UI):
    # fall through to create, no crash, settings updated, no dup.
    from qgis.core import QgsApplication, QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["cert_path"], "/certs/u.crt")
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["key_path"], "/certs/u.key")
    first_id = bp._store_pki_authcfg()
    QgsApplication.authManager().removeAuthenticationConfig(first_id)
    assert QgsApplication.authManager().configIds() == []

    second_id = bp._store_pki_authcfg()

    assert second_id and second_id != first_id
    assert QgsApplication.authManager().configIds() == [second_id]
    assert QgsSettings().value(MTLS_SETTINGS_KEYS["authcfg_id"]) == second_id


def test_store_pki_authcfg_fails_when_manager_not_ready(bp, monkeypatch):
    from qgis.core import QgsApplication, QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["cert_path"], "/certs/u.crt")
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["key_path"], "/certs/u.key")
    monkeypatch.setattr(type(QgsApplication.authManager()), "isDisabled", lambda self: True)
    assert bp._store_pki_authcfg() == ""
    assert QgsApplication.authManager().configIds() == []
    assert QgsSettings().value(MTLS_SETTINGS_KEYS["authcfg_id"], "") == ""


def test_remove_pki_authcfg_clears_manager_and_settings(bp):
    from qgis.core import QgsApplication, QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["cert_path"], "/certs/u.crt")
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["key_path"], "/certs/u.key")
    cfg_id = bp._store_pki_authcfg()
    assert cfg_id in QgsApplication.authManager().configIds()

    bp._remove_pki_authcfg()

    assert QgsApplication.authManager().configIds() == []
    assert QgsSettings().value(MTLS_SETTINGS_KEYS["authcfg_id"], "") == ""


# --- _mtls_active truth table -----------------------------------------------


def test_mtls_active_disabled(bp):
    from qgis.core import QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["enabled"], False)
    assert bp._mtls_active() == (False, "disabled")


def test_mtls_active_reads_string_bool_from_settings(bp):
    # Real QGIS persists bools as strings; the flag must honor that.
    from qgis.core import QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["enabled"], "false")
    assert bp._mtls_active() == (False, "disabled")


def test_mtls_active_not_configured(bp):
    # Flag defaults to ON with no paths set: legacy mode, not an error.
    assert bp._mtls_active() == (False, "not_configured")


def test_mtls_active_cert_missing(bp, tmp_path):
    from qgis.core import QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["cert_path"], str(tmp_path / "no.crt"))
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["key_path"], str(tmp_path / "no.key"))
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["ca_path"], str(tmp_path / "no-ca.crt"))
    assert bp._mtls_active() == (False, "cert_missing")


def test_mtls_active_chain_invalid(bp, tmp_path, _mtls_bundle):
    from qgis.core import QgsSettings

    other_ca_key = tmp_path / "other_ca.key"
    other_ca_crt = tmp_path / "other_ca.crt"
    _openssl("req", "-new", "-x509", "-days", "1", "-nodes",
             "-subj", "/CN=other", "-keyout", str(other_ca_key), "-out", str(other_ca_crt))
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["cert_path"], _mtls_bundle["cert"])
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["key_path"], _mtls_bundle["key"])
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["ca_path"], str(other_ca_crt))
    assert bp._mtls_active() == (False, "chain_invalid")


@pytest.mark.parametrize("reason", [
    "cert_missing",
    "key_missing",
    "chain_invalid",
    "expired",
    "not_yet_valid",
    "missing_client_auth_eku",
])
def test_mtls_active_forwards_all_reasons(bp, tmp_path, monkeypatch, reason):
    from qgis.core import QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["cert_path"], str(tmp_path / "c.crt"))
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["key_path"], str(tmp_path / "c.key"))
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["ca_path"], str(tmp_path / "ca.crt"))
    monkeypatch.setattr(
        bp, "validate_client_certificate",
        lambda *args: CertValidationResult(ok=False, reason=reason),
    )
    assert bp._mtls_active() == (False, reason)


def test_mtls_active_valid(bp, _mtls_bundle):
    from qgis.core import QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    assert bp._mtls_active() == (True, None)


# --- T3 helpers: fake iface / psycopg2 / layers ------------------------------
# NOTE (T4 done): key-site assertions below compare against bp.tr(...) —
# the wiring concern is that the RIGHT key is used at each site. The T4
# rendering tests at the end of this file pin that every key has a real
# non-empty text in FR/EN/PT (no raw-key echo in user-visible diagnostics).


class _FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushSuccess(self, title, message):
        self.messages.append(("success", title, message))

    def pushWarning(self, title, message):
        self.messages.append(("warning", title, message))

    def pushCritical(self, title, message):
        self.messages.append(("critical", title, message))


class _FakeIface:
    def __init__(self):
        self._bar = _FakeMessageBar()

    def mainWindow(self):
        return None

    def messageBar(self):
        return self._bar


class _FakePgError(Exception):
    pass


class _FakeCursor:
    """Serves _register_bridge_user's SELECT/UPDATE + _set_app_user."""

    def __init__(self):
        self.statements = []

    def execute(self, *args, **kwargs):
        self.statements.append(args)

    def fetchone(self):
        return ("00000000-0000-0000-0000-000000000001", "tester")

    def close(self):
        pass


class _FakeConnection:
    def __init__(self):
        self.autocommit = False
        self.closed = False

    def cursor(self):
        return _FakeCursor()


def _install_fake_psycopg2(monkeypatch, behavior="ok"):
    """Install a recording psycopg2 module. `behavior` is "ok" or an
    Exception instance that connect() raises. Returns the calls list."""
    calls = []
    module = types.ModuleType("psycopg2")
    module.Error = _FakePgError

    def fake_connect(**kwargs):
        calls.append(kwargs)
        if isinstance(behavior, Exception):
            raise behavior
        return _FakeConnection()

    module.connect = fake_connect
    monkeypatch.setitem(sys.modules, "psycopg2", module)
    return calls


def _make_fake_layer(source, valid=True, provider_type="postgres"):
    """A QgsVectorLayer test double (defined per-call: the qgis stub is
    only importable inside tests, after the stub-path fixture runs)."""
    from qgis.core import QgsDataSourceUri, QgsVectorLayer

    class _FakeProvider:
        def __init__(self, uri_str):
            self._uri = QgsDataSourceUri(uri_str)

        def name(self):
            return "postgres"

        def uri(self):
            return self._uri

    class _FakeLayer(QgsVectorLayer):
        def __init__(self, uri_str, is_valid, ptype):
            self._source = uri_str
            self._valid = is_valid
            self._ptype = ptype
            self._provider = _FakeProvider(uri_str) if is_valid else None
            self.rewritten = []

        def providerType(self):
            return self._ptype

        def dataProvider(self):
            return self._provider

        def source(self):
            return self._source

        def isValid(self):
            return self._valid

        def name(self):
            return "fake_layer"

        def setDataSource(self, uri_str, name, provider, options):
            self.rewritten.append(uri_str)
            self._source = uri_str
            self._provider = _FakeProvider(uri_str)
            self._valid = True

    return _FakeLayer(source, valid, provider_type)


def _log_messages(level=None):
    """Logged messages, optionally filtered by Qgis level."""
    from qgis.core import QgsMessageLog

    return [
        message
        for (message, _tag, lvl) in QgsMessageLog._messages
        if level is None or lvl == level
    ]


def _pg_base(bp, conn="wyre"):
    return f"PostgreSQL/connections/{bp._PG_CONNECTIONS[conn]['name']}"


def _our_source(**overrides):
    params = {
        "dbname": "test_db",
        "host": "test-host.invalid",
        "port": "5432",
        "user": "test_user",
    }
    params.update(overrides)
    return " ".join(f"{key}='{value}'" for key, value in params.items())


# --- T3: _mtls_message -------------------------------------------------------


def test_mtls_message_passes_through_known_keys(bp):
    assert (
        bp._mtls_message("pg.configured", name="wyre")
        == bp.tr("pg.configured", name="wyre")
    )


def test_mtls_message_echoes_unknown_keys(bp):
    assert bp._mtls_message("mtls.no_such_key") == "mtls.no_such_key"
    assert bp._mtls_message("mtls.no_such_key", path="/x") == "mtls.no_such_key"


# --- T3: _ensure_pgpass_entry --------------------------------------------------


def test_ensure_pgpass_entry_creates_file_with_0600(bp, tmp_path):
    target = tmp_path / "subdir" / ".pgpass"
    assert (
        bp._ensure_pgpass_entry(
            target, "db.example.com", 5433, "mydb", "u1", "p@ss:w"
        )
        is True
    )
    assert (
        target.read_text(encoding="utf-8")
        == "db.example.com:5433:mydb:u1:p@ss\\:w\n"
    )
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_ensure_pgpass_entry_preserves_other_lines(bp, tmp_path):
    target = tmp_path / ".pgpass"
    target.write_text("other:5432:odb:ou:opw\nh:1:d:u:OLD\n", encoding="utf-8")
    assert bp._ensure_pgpass_entry(target, "h", 1, "d", "u", "NEW") is True
    assert (
        target.read_text(encoding="utf-8") == "other:5432:odb:ou:opw\nh:1:d:u:NEW\n"
    )


def test_ensure_pgpass_entry_directory_returns_false(bp, tmp_path):
    assert bp._ensure_pgpass_entry(tmp_path, "h", 1, "d", "u", "pw") is False


def test_ensure_pgpass_entry_readonly_file_returns_false(bp, tmp_path):
    target = tmp_path / ".pgpass"
    target.write_text("h:1:d:u:OLD\n", encoding="utf-8")
    target.chmod(0o400)
    try:
        assert bp._ensure_pgpass_entry(target, "h", 1, "d", "u", "NEW") is False
    finally:
        target.chmod(0o600)


# --- T3: _setup_qgis_pg_connection ----------------------------------------------


def test_setup_mtls_writes_verify_full_and_pki_authcfg(
    bp, tmp_path, monkeypatch, _mtls_bundle
):
    from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    pgpass = tmp_path / ".pgpass"
    monkeypatch.setattr(bp, "pgpass_file_path", lambda *a, **k: pgpass)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())

    plugin._setup_qgis_pg_connection("s3cret", use_authcfg=True)

    base = _pg_base(bp)
    assert QgsSettings().value(f"{base}/host") == "test-host.invalid"
    assert QgsSettings().value(f"{base}/port") == "5432"
    assert QgsSettings().value(f"{base}/database") == "test_db"
    assert QgsSettings().value(f"{base}/username") == "test_user"
    assert QgsSettings().value(f"{base}/sslmode") == "5"
    cfg_id = QgsSettings().value(f"{base}/authcfg")
    assert cfg_id == QgsSettings().value(MTLS_SETTINGS_KEYS["authcfg_id"])
    assert cfg_id != ""
    assert QgsSettings().value(f"{base}/saveUsername") is True
    assert QgsSettings().value(f"{base}/savePassword") is False
    assert QgsSettings().value(f"{base}/password", None) is None
    probe = QgsAuthMethodConfig()
    QgsApplication.authManager().loadAuthenticationConfig(cfg_id, probe, True)
    assert probe.method() == "PKI-Paths"
    assert probe.config("password", "") == ""
    assert probe.config("certpath", "") == _mtls_bundle["cert"]
    assert (
        pgpass.read_text(encoding="utf-8")
        == "test-host.invalid:5432:test_db:test_user:s3cret\n"
    )


def test_setup_mtls_ignores_use_authcfg_flag(bp, tmp_path, monkeypatch, _mtls_bundle):
    from qgis.core import QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    monkeypatch.setattr(bp, "pgpass_file_path", lambda *a, **k: tmp_path / ".pgpass")
    plugin = bp.ConstructelBridgePlugin(_FakeIface())

    plugin._setup_qgis_pg_connection("s3cret", use_authcfg=False)

    base = _pg_base(bp)
    assert QgsSettings().value(f"{base}/sslmode") == "5"
    assert QgsSettings().value(f"{base}/authcfg") == QgsSettings().value(
        MTLS_SETTINGS_KEYS["authcfg_id"]
    )
    assert QgsSettings().value(bp._AUTH_CFG_ID_KEYS["wyre"], "") == ""


def test_setup_mtls_removes_legacy_basic_authcfg(bp, tmp_path, monkeypatch, _mtls_bundle):
    from qgis.core import QgsApplication, QgsSettings

    assert bp._store_password_encrypted("old", "wyre") is True
    basic_id = QgsSettings().value(bp._AUTH_CFG_ID_KEYS["wyre"], "")
    assert basic_id != ""
    _set_mtls_paths(QgsSettings, _mtls_bundle)
    monkeypatch.setattr(bp, "pgpass_file_path", lambda *a, **k: tmp_path / ".pgpass")
    plugin = bp.ConstructelBridgePlugin(_FakeIface())

    plugin._setup_qgis_pg_connection("s3cret", use_authcfg=True)

    assert basic_id not in QgsApplication.authManager().configIds()
    assert QgsSettings().value(bp._AUTH_CFG_ID_KEYS["wyre"], "") == ""
    assert QgsSettings().value(f"{_pg_base(bp)}/authcfg") != ""


def test_setup_mtls_be_connection(bp, tmp_path, monkeypatch, _mtls_bundle):
    from qgis.core import QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    monkeypatch.setattr(bp, "pgpass_file_path", lambda *a, **k: tmp_path / ".pgpass")
    monkeypatch.setitem(bp._PG_CONNECTIONS, "be", {
        "name": "be",
        "host": "test-host.invalid",
        "port": 5432,
        "dbname": "test_db",
        "user": "be_user",
        "sslmode": "require",
        "schemas": "public",
        "schema": "public",
        "public_only": True,
    })
    plugin = bp.ConstructelBridgePlugin(_FakeIface())

    plugin._setup_qgis_pg_connection("bepw", conn="be")

    base = "PostgreSQL/connections/be"
    assert QgsSettings().value(f"{base}/sslmode") == "5"
    assert QgsSettings().value(f"{base}/username") == "be_user"
    assert QgsSettings().value(f"{base}/publicOnly") is True
    assert QgsSettings().value(f"{base}/authcfg") == QgsSettings().value(
        MTLS_SETTINGS_KEYS["authcfg_id"]
    )


def test_setup_mtls_pgpass_failure_aborts_with_settings_untouched(
    bp, tmp_path, monkeypatch, _mtls_bundle
):
    from qgis.core import Qgis, QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    monkeypatch.setattr(bp, "pgpass_file_path", lambda *a, **k: tmp_path)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())

    plugin._setup_qgis_pg_connection("s3cret", use_authcfg=True)

    assert QgsSettings().value(f"{_pg_base(bp)}/host", None) is None
    expected = bp.tr("mtls.pgpass_unwritable", path=str(tmp_path))
    assert any(expected in m for m in _log_messages(level=Qgis.Critical))


def test_setup_mtls_authcfg_store_failure_aborts(bp, tmp_path, monkeypatch, _mtls_bundle):
    from qgis.core import Qgis, QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    pgpass = tmp_path / ".pgpass"
    monkeypatch.setattr(bp, "pgpass_file_path", lambda *a, **k: pgpass)
    monkeypatch.setattr(bp, "_store_pki_authcfg", lambda: "")
    plugin = bp.ConstructelBridgePlugin(_FakeIface())

    plugin._setup_qgis_pg_connection("s3cret", use_authcfg=True)

    assert QgsSettings().value(f"{_pg_base(bp)}/host", None) is None
    assert any(
        bp.tr("mtls.activation_failed") in m
        for m in _log_messages(level=Qgis.Critical)
    )
    # pgpass is written before the authcfg store is attempted (documented order)
    assert "test_user" in pgpass.read_text(encoding="utf-8")


def test_setup_configured_but_invalid_aborts_loudly(bp, tmp_path, _mtls_bundle):
    from qgis.core import Qgis, QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["cert_path"], str(tmp_path / "nope.crt"))
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["key_path"], _mtls_bundle["key"])
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["ca_path"], _mtls_bundle["ca"])
    plugin = bp.ConstructelBridgePlugin(_FakeIface())

    assert plugin._setup_qgis_pg_connection("s3cret", use_authcfg=True) is None
    assert QgsSettings().value(f"{_pg_base(bp)}/host", None) is None
    assert any(
        bp.tr("mtls.cert_missing") in m
        for m in _log_messages(level=Qgis.Critical)
    )


def test_setup_inactive_matches_legacy_snapshot(bp):
    from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["enabled"], False)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())

    plugin._setup_qgis_pg_connection("s3cret", use_authcfg=True)

    base = _pg_base(bp)
    expected = {
        "host": "test-host.invalid",
        "port": "5432",
        "database": "test_db",
        "username": "test_user",
        "sslmode": "3",
        "estimatedMetadata": True,
        "allowGeometrylessTables": False,
        "geometryColumnsOnly": True,
        "dontResolveType": False,
        "publicOnly": False,
        "projectsInDatabase": True,
        "metadataInDatabase": True,
        "schemas": "wyre,osiris",
        "schema": "wyre",
        "saveUsername": True,
        "savePassword": False,
    }
    for key, value in expected.items():
        assert QgsSettings().value(f"{base}/{key}") == value
    assert QgsSettings().value(f"{base}/password", None) is None
    basic_id = QgsSettings().value(f"{base}/authcfg")
    assert basic_id == QgsSettings().value(bp._AUTH_CFG_ID_KEYS["wyre"])
    probe = QgsAuthMethodConfig()
    QgsApplication.authManager().loadAuthenticationConfig(basic_id, probe, True)
    assert probe.method() == "Basic"


def test_setup_inactive_without_authcfg_stores_no_authcfg(bp):
    from qgis.core import QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["enabled"], False)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())

    plugin._setup_qgis_pg_connection("s3cret", use_authcfg=False)

    base = _pg_base(bp)
    assert QgsSettings().value(f"{base}/sslmode") == "3"
    assert QgsSettings().value(f"{base}/authcfg", None) is None


def test_setup_not_configured_behaves_like_legacy(bp):
    from qgis.core import QgsSettings

    plugin = bp.ConstructelBridgePlugin(_FakeIface())

    plugin._setup_qgis_pg_connection("s3cret", use_authcfg=False)

    assert QgsSettings().value(f"{_pg_base(bp)}/sslmode") == "3"
    assert all("mtls." not in m for m in _log_messages())


# --- T3: _connect ------------------------------------------------------------


def _connect_ready_plugin(bp):
    from qgis.core import QgsSettings

    QgsSettings().setValue("constructel_bridge/onboarding_done", True)
    return bp.ConstructelBridgePlugin(_FakeIface())


def test_connect_mtls_passes_ssl_kwargs(bp, tmp_path, monkeypatch, _mtls_bundle):
    from qgis.core import QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    monkeypatch.setattr(bp, "pgpass_file_path", lambda *a, **k: tmp_path / ".pgpass")
    calls = _install_fake_psycopg2(monkeypatch)
    plugin = _connect_ready_plugin(bp)

    assert plugin._connect("s3cret", silent=True) is True

    assert len(calls) == 1
    kwargs = calls[0]
    assert kwargs["sslmode"] == "verify-full"
    assert kwargs["sslcert"] == _mtls_bundle["cert"]
    assert kwargs["sslkey"] == _mtls_bundle["key"]
    assert kwargs["sslrootcert"] == _mtls_bundle["ca"]
    assert kwargs["host"] == "test-host.invalid"
    assert kwargs["password"] == "s3cret"
    assert kwargs["application_name"].startswith("constructel_bridge:")
    assert plugin._connected is True
    assert QgsSettings().value(f"{_pg_base(bp)}/sslmode") == "5"
    assert any(kind == "success" for (kind, _t, _m) in plugin.iface.messageBar().messages)


def test_connect_inactive_uses_legacy_kwargs(bp, monkeypatch):
    from qgis.core import QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["enabled"], False)
    calls = _install_fake_psycopg2(monkeypatch)
    plugin = _connect_ready_plugin(bp)

    assert plugin._connect("s3cret", silent=True) is True

    assert calls[0]["sslmode"] == bp.DEFAULT_SSLMODE
    assert "sslcert" not in calls[0]
    assert "sslkey" not in calls[0]
    assert "sslrootcert" not in calls[0]
    assert QgsSettings().value(f"{_pg_base(bp)}/sslmode") == "3"


def test_connect_configured_but_invalid_aborts_before_psycopg2(
    bp, tmp_path, monkeypatch, _mtls_bundle
):
    from qgis.core import Qgis, QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["cert_path"], str(tmp_path / "nope.crt"))
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["key_path"], _mtls_bundle["key"])
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["ca_path"], _mtls_bundle["ca"])
    calls = _install_fake_psycopg2(monkeypatch)
    plugin = _connect_ready_plugin(bp)

    assert plugin._connect("s3cret", silent=True) is False

    assert calls == []
    assert plugin._connected is False
    assert QgsSettings().value(f"{_pg_base(bp)}/host", None) is None
    assert any(
        bp.tr("mtls.cert_missing") in m
        for m in _log_messages(level=Qgis.Critical)
    )


def test_connect_mtls_server_cert_rejection_maps_diagnostic(
    bp, tmp_path, monkeypatch, _mtls_bundle
):
    from qgis.core import Qgis, QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    monkeypatch.setattr(bp, "pgpass_file_path", lambda *a, **k: tmp_path / ".pgpass")
    _install_fake_psycopg2(
        monkeypatch, _FakePgError("connection requires a valid client certificate")
    )
    plugin = _connect_ready_plugin(bp)

    assert plugin._connect("s3cret", silent=True) is False

    assert any(
        bp.tr("mtls.cert_required_by_server") in m
        for m in _log_messages(level=Qgis.Critical)
    )
    # Browser entry is still configured on failure (mirrors legacy behavior)
    assert QgsSettings().value(f"{_pg_base(bp)}/sslmode") == "5"


def test_connect_mtls_other_failure_keeps_generic_diagnostic(
    bp, tmp_path, monkeypatch, _mtls_bundle
):
    from qgis.core import Qgis, QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    monkeypatch.setattr(bp, "pgpass_file_path", lambda *a, **k: tmp_path / ".pgpass")
    _install_fake_psycopg2(
        monkeypatch, _FakePgError("password authentication failed for user 'x'")
    )
    plugin = _connect_ready_plugin(bp)

    assert plugin._connect("s3cret", silent=True) is False

    assert any("Connection failed" in m for m in _log_messages(level=Qgis.Critical))
    assert all("mtls.cert_required_by_server" not in m for m in _log_messages())


def test_connect_inactive_cert_message_stays_generic(bp, monkeypatch):
    from qgis.core import Qgis, QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["enabled"], False)
    _install_fake_psycopg2(
        monkeypatch, _FakePgError("connection requires a valid client certificate")
    )
    plugin = _connect_ready_plugin(bp)

    assert plugin._connect("s3cret", silent=True) is False

    assert any("Connection failed" in m for m in _log_messages(level=Qgis.Critical))
    assert all("mtls." not in m for m in _log_messages())


# --- T3: _fix_layer_credentials -----------------------------------------------


def test_fix_mtls_rewrites_stale_authcfg_to_pki(bp, _mtls_bundle):
    from qgis.core import QgsDataSourceUri, QgsProject, QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    pki_id = bp._store_pki_authcfg()
    assert pki_id != ""
    layer = _make_fake_layer(
        _our_source(password="oldpw", authcfg="stale-id"), valid=False
    )
    QgsProject.instance().addMapLayer(layer)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())
    plugin._password = "s3cret"

    plugin._fix_layer_credentials()

    assert len(layer.rewritten) == 1
    uri = QgsDataSourceUri(layer.source())
    assert uri.authConfigId() == pki_id
    assert uri.password() == ""
    assert uri.username() == "test_user"
    assert any("credentials corrigees" in m for m in _log_messages())


def test_fix_mtls_unknown_user_falls_back_to_default(bp, _mtls_bundle):
    from qgis.core import QgsDataSourceUri, QgsProject, QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    pki_id = bp._store_pki_authcfg()
    layer = _make_fake_layer(_our_source(user="stranger", password="x"), valid=True)
    QgsProject.instance().addMapLayer(layer)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())

    plugin._fix_layer_credentials()

    uri = QgsDataSourceUri(layer.source())
    assert uri.username() == "test_user"
    assert uri.authConfigId() == pki_id
    assert uri.password() == ""


def test_fix_mtls_skips_third_party_host(bp, _mtls_bundle):
    from qgis.core import QgsProject, QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    source = "dbname='o' host=other.example.com port=5432 user='x' password='y'"
    layer = _make_fake_layer(source, valid=False)
    QgsProject.instance().addMapLayer(layer)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())

    plugin._fix_layer_credentials()

    assert layer.rewritten == []
    assert layer.source() == source


def test_fix_mtls_cert_unavailable_skips_without_downgrade(bp, monkeypatch, _mtls_bundle):
    from qgis.core import Qgis, QgsProject, QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    monkeypatch.setattr(bp, "_store_pki_authcfg", lambda: "")
    source = _our_source(password="oldpw", authcfg="stale-id")
    layer = _make_fake_layer(source, valid=False)
    QgsProject.instance().addMapLayer(layer)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())
    plugin._password = "s3cret"

    plugin._fix_layer_credentials()

    assert layer.rewritten == []
    assert layer.source() == source
    assert any(
        bp.tr("mtls.activation_failed") in m
        for m in _log_messages(level=Qgis.Warning)
    )
    assert any("toujours invalides" in m for m in _log_messages(level=Qgis.Warning))


def test_fix_configured_but_invalid_refuses_loudly(bp, tmp_path, _mtls_bundle):
    from qgis.core import Qgis, QgsProject, QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["cert_path"], str(tmp_path / "nope.crt"))
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["key_path"], _mtls_bundle["key"])
    QgsSettings().setValue(MTLS_SETTINGS_KEYS["ca_path"], _mtls_bundle["ca"])
    source = _our_source(password="oldpw", authcfg="stale-id")
    layer = _make_fake_layer(source, valid=False)
    QgsProject.instance().addMapLayer(layer)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())
    plugin._password = "s3cret"

    plugin._fix_layer_credentials()

    assert layer.rewritten == []
    assert layer.source() == source
    assert any(
        bp.tr("mtls.cert_missing") in m
        for m in _log_messages(level=Qgis.Critical)
    )


def test_fix_mtls_already_clean_layer_untouched(bp, _mtls_bundle):
    from qgis.core import QgsProject, QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    pki_id = bp._store_pki_authcfg()
    layer = _make_fake_layer(_our_source(authcfg=pki_id), valid=True)
    QgsProject.instance().addMapLayer(layer)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())

    plugin._fix_layer_credentials()

    assert layer.rewritten == []


def test_fix_mtls_be_layer_keeps_be_user(bp, monkeypatch, _mtls_bundle):
    from qgis.core import QgsDataSourceUri, QgsProject, QgsSettings

    _set_mtls_paths(QgsSettings, _mtls_bundle)
    monkeypatch.setattr(bp, "BE_ENABLED", True)
    monkeypatch.setattr(bp, "BE_USER", "be_user")
    monkeypatch.setattr(bp, "_BE_PW", "bepw")
    pki_id = bp._store_pki_authcfg()
    layer = _make_fake_layer(
        _our_source(user="be_user", password="oldpw", authcfg="stale-id"), valid=False
    )
    QgsProject.instance().addMapLayer(layer)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())
    plugin._password = "s3cret"

    plugin._fix_layer_credentials()

    uri = QgsDataSourceUri(layer.source())
    assert uri.username() == "be_user"
    assert uri.authConfigId() == pki_id
    assert uri.password() == ""


def test_fix_inactive_keeps_legacy_plaintext_rewrite(bp):
    from qgis.core import QgsDataSourceUri, QgsProject, QgsSettings

    QgsSettings().setValue(MTLS_SETTINGS_KEYS["enabled"], False)
    layer = _make_fake_layer(
        _our_source(password="oldpw", authcfg="stale-id"), valid=False
    )
    QgsProject.instance().addMapLayer(layer)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())
    plugin._password = "s3cret"

    plugin._fix_layer_credentials()

    assert len(layer.rewritten) == 1
    uri = QgsDataSourceUri(layer.source())
    assert uri.authConfigId() == ""
    assert uri.password() == "s3cret"
    assert uri.username() == "test_user"


# --- T4: translated mtls.* diagnostics ----------------------------------------

_MTLS_KEYS = [
    "mtls.cert_missing",
    "mtls.key_missing",
    "mtls.chain_invalid",
    "mtls.expired",
    "mtls.not_yet_valid",
    "mtls.missing_client_auth_eku",
    "mtls.not_configured",
    "mtls.cert_required_by_server",
    "mtls.pgpass_unwritable",
    "mtls.activation_failed",
]


def test_mtls_keys_present_in_all_languages(qgis_stub_path):
    from constructel_bridge.i18n.translations import TRANSLATIONS

    for lang in ("fr", "en", "pt"):
        for key in _MTLS_KEYS:
            assert TRANSLATIONS[lang].get(key), f"{lang}:{key} missing or empty"


@pytest.mark.parametrize("lang", ["fr", "en", "pt"])
def test_mtls_keys_render_nonempty_in_all_languages(bp, lang):
    from constructel_bridge import i18n

    i18n.set_language(lang)
    try:
        for key in _MTLS_KEYS:
            rendered = bp._mtls_message(key, path="/probe/pgpass")
            assert rendered not in ("", key), f"{lang}:{key} not translated"
            # No unsubstituted placeholder survives (tr() swallows KeyError)
            assert "{" not in rendered and "}" not in rendered, (
                f"{lang}:{key} has a raw placeholder"
            )
        assert "/probe/pgpass" in bp._mtls_message(
            "mtls.pgpass_unwritable", path="/probe/pgpass"
        )
    finally:
        i18n.set_language("en")


def test_stub_uri_round_trip_preserves_params(bp):
    from qgis.core import QgsDataSourceUri

    source = (
        "dbname='my db' host=db.example.com port=5432 "
        "user='u1' password='p@ss w:d'"
    )
    once = QgsDataSourceUri(source).uri()
    twice = QgsDataSourceUri(once).uri()
    assert once == twice  # rebuild output is a stable fixpoint
    reparsed = QgsDataSourceUri(once)
    assert reparsed.host() == "db.example.com"
    assert reparsed.username() == "u1"
    assert reparsed.password() == "p@ss w:d"
