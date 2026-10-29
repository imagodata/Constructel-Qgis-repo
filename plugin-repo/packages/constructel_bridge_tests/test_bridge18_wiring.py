"""Stub-level wiring tests for Bridge 1.8 (logins PG nominatifs LDAPS,
plan 2026-10-29 volets B3-B9, C, D). No real QGIS: the qgis stub package
of constructel_bridge_tests/stubs/ is installed and bridge_plugin is
re-imported per test (shared QgsSettings / Auth Manager state reset).

credentials.json is written per test from an explicit dict so the three
deployment shapes are covered: 1.7.x (shared wyre+be passwords), 1.8
transition (shared wyre password kept for the D7 fallback, be without any
secret) and 1.8.x closure (no secret at all).
"""
import base64
import importlib
import json
import sys
import types
from pathlib import Path

import pytest

STUBS_DIR = Path(__file__).resolve().parent / "stubs"
PLUGIN_DIR = Path(__file__).resolve().parent.parent / "constructel_bridge"
CREDENTIALS_PATH = PLUGIN_DIR / "credentials.json"

HOST = "test-host.invalid"
_B64 = base64.b64encode(b"shared-pw").decode()

CREDS_17 = {
    "wyre": {"host": HOST, "port": 5432, "dbname": "test_db", "user": "ftth_editor", "password": _B64},
    "be": {"host": HOST, "port": 5432, "dbname": "test_db", "user": "bureau_etudes", "password": _B64},
}
CREDS_18 = {
    "wyre": {"host": HOST, "port": 5432, "dbname": "test_db", "user": "ftth_editor", "password": _B64},
    "be": {"host": HOST, "port": 5432, "dbname": "test_db"},
}
CREDS_18X = {
    "wyre": {"host": HOST, "port": 5432, "dbname": "test_db"},
    "be": {"host": HOST, "port": 5432, "dbname": "test_db"},
}


@pytest.fixture
def load_bp():
    """Factory: load_bp(creds) -> fresh bridge_plugin module built on *creds*.
    Never clobbers a pre-existing real credentials.json."""
    if str(STUBS_DIR) not in sys.path:
        sys.path.insert(0, str(STUBS_DIR))
    pre_existing = CREDENTIALS_PATH.read_bytes() if CREDENTIALS_PATH.exists() else None

    def _load(creds):
        CREDENTIALS_PATH.write_text(json.dumps(creds))
        for mod_name in list(sys.modules):
            if mod_name == "constructel_bridge.bridge_plugin" or mod_name.startswith("qgis"):
                del sys.modules[mod_name]
        return importlib.import_module("constructel_bridge.bridge_plugin")

    yield _load
    if pre_existing is None:
        CREDENTIALS_PATH.unlink(missing_ok=True)
    else:
        CREDENTIALS_PATH.write_bytes(pre_existing)


@pytest.fixture
def bp(load_bp):
    return load_bp(CREDS_18)


def _log_messages(level=None):
    from qgis.core import QgsMessageLog

    return [m for (m, _t, lvl) in QgsMessageLog._messages if level is None or lvl == level]


# --- B9 : credentials.json tolerant ------------------------------------------


def test_shared_fallback_available_when_wyre_password_present(load_bp):
    bp = load_bp(CREDS_18)
    assert bp.SHARED_FALLBACK_AVAILABLE is True
    assert bp._DEFAULT_PW == "shared-pw"
    assert bp.DEFAULT_USER == "ftth_editor"


def test_import_without_wyre_password_disables_fallback_without_keyerror(load_bp):
    bp = load_bp(CREDS_18X)
    assert bp.SHARED_FALLBACK_AVAILABLE is False
    assert bp._DEFAULT_PW == ""
    assert bp.DEFAULT_USER == ""


def test_wyre_sslmode_is_forced_to_verify_full(load_bp):
    creds = json.loads(json.dumps(CREDS_18))
    creds["wyre"]["sslmode"] = "require"
    bp = load_bp(creds)
    assert bp.DEFAULT_SSLMODE == "verify-full"


# --- C3 : be sans identifiant partage ----------------------------------------


def test_be_enabled_without_shared_credentials(load_bp):
    bp = load_bp(CREDS_18)
    assert bp.BE_ENABLED is True
    assert bp.BE_SHARED_AVAILABLE is False
    assert bp.BE_SSLMODE == "verify-full"


def test_be_shared_available_on_17x_credentials(load_bp):
    bp = load_bp(CREDS_17)
    assert bp.BE_ENABLED is True
    assert bp.BE_SHARED_AVAILABLE is True


def test_be_disabled_without_host(load_bp):
    creds = json.loads(json.dumps(CREDS_18))
    creds["be"] = {}
    bp = load_bp(creds)
    assert bp.BE_ENABLED is False


# --- B3 / C1 : Auth Manager username=<login> ---------------------------------


def _config(bp, cfg_id):
    from qgis.core import QgsApplication, QgsAuthMethodConfig

    cfg = QgsAuthMethodConfig()
    QgsApplication.authManager().loadAuthenticationConfig(cfg_id, cfg, True)
    return cfg


def test_store_password_with_login_writes_username_in_fixed_wyre_config(bp):
    assert bp._store_password_encrypted("ad-pw", "wyre", username="jdoe") is True
    cfg = _config(bp, "9i19s56")
    assert cfg.method() == "Basic"
    assert cfg.config("username") == "jdoe"
    assert cfg.config("password") == "ad-pw"


def test_store_password_updates_username_of_existing_config(bp):
    bp._store_password_encrypted("old", "wyre")  # 1.7.x : username = ftth_editor
    assert _config(bp, "9i19s56").config("username") == "ftth_editor"
    bp._store_password_encrypted("ad-pw", "wyre", username="jdoe")
    cfg = _config(bp, "9i19s56")
    assert cfg.config("username") == "jdoe"
    assert cfg.config("password") == "ad-pw"


def test_store_password_without_login_keeps_shared_username(bp):
    bp._store_password_encrypted("shared-pw", "wyre")
    assert _config(bp, "9i19s56").config("username") == "ftth_editor"


def test_store_be_password_with_login_uses_fixed_be_config(bp):
    assert bp._store_password_encrypted("ad-pw", "be", username="jdoe") is True
    cfg = _config(bp, "07254s7")
    assert cfg.config("username") == "jdoe"
    assert cfg.name() == bp.AUTH_CFG_NAME_BE


def test_stored_login_reads_username_of_fixed_config(bp):
    assert bp._stored_login("wyre") == ""
    bp._store_password_encrypted("ad-pw", "wyre", username="jdoe")
    assert bp._stored_login("wyre") == "jdoe"


# --- B6 : root.crt --------------------------------------------------------------


def test_ensure_root_crt_writes_both_cas_and_creates_parent(bp, tmp_path, monkeypatch):
    target = tmp_path / "postgresql" / "root.crt"
    monkeypatch.setattr(bp, "root_crt_file_path", lambda *a, **k: target)

    assert bp._ensure_root_crt() is True

    text = target.read_text(encoding="utf-8")
    assert text.count("BEGIN CERTIFICATE") == 2
    assert text.endswith("-----END CERTIFICATE-----\n")


def test_ensure_root_crt_is_idempotent_and_preserves_foreign_roots(bp, tmp_path, monkeypatch):
    target = tmp_path / "root.crt"
    foreign = "-----BEGIN CERTIFICATE-----\nMIIBforeign\n-----END CERTIFICATE-----\n"
    target.write_text("# corp roots\n" + foreign, encoding="utf-8")
    monkeypatch.setattr(bp, "root_crt_file_path", lambda *a, **k: target)

    assert bp._ensure_root_crt() is True
    first = target.read_text(encoding="utf-8")
    assert bp._ensure_root_crt() is True
    assert target.read_text(encoding="utf-8") == first
    assert first.startswith("# corp roots\n")
    assert "MIIBforeign" in first
    assert first.count("BEGIN CERTIFICATE") == 3


def test_ensure_root_crt_unwritable_logs_blocking_error(bp, tmp_path, monkeypatch):
    from qgis.core import Qgis

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    target = blocker / "root.crt"  # parent is a regular file: cannot be created
    monkeypatch.setattr(bp, "root_crt_file_path", lambda *a, **k: target)

    assert bp._ensure_root_crt() is False
    assert any(
        bp.tr("nominal.root_crt_failed", path=str(target)) in m
        for m in _log_messages(level=Qgis.MessageLevel.Critical)
    )
