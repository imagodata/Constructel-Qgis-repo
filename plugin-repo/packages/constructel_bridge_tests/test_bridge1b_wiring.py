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
import subprocess
import sys
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
