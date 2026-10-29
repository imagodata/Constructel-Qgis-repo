"""Stub-level wiring tests for Bridge 1.8 (logins PG nominatifs LDAPS,
plan 2026-10-29 volets B3-B9, C, D). No real QGIS: the qgis stub package
of constructel_bridge_tests/stubs/ is installed and bridge_plugin is
re-imported per test (shared QgsSettings / Auth Manager state reset).

credentials.json is written per test from an explicit dict so the three
deployment shapes are covered: 1.7.x (shared wyre+be passwords), 1.8
transition (shared wyre password kept for the D7 fallback, be without any
secret) and 1.8.x closure (no secret at all).
"""
import json

import pytest

from constructel_bridge_tests.conftest import CREDS_17, CREDS_18, CREDS_18X


@pytest.fixture
def load_bp(load_bp18):
    return load_bp18


@pytest.fixture
def bp(bp18):
    return bp18


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


def test_shared_sslmode_is_17x_and_nominal_is_verify_full(load_bp):
    # Revue 29/10 (D-TLS-2) : identifiant partage = sslmode de
    # credentials.json, require par defaut, comme 1.7.x.
    bp = load_bp(CREDS_18)
    assert bp.DEFAULT_SSLMODE == "require"
    assert bp.NOMINAL_SSLMODE == "verify-full"
    creds = json.loads(json.dumps(CREDS_18))
    creds["wyre"]["sslmode"] = "prefer"
    assert load_bp(creds).DEFAULT_SSLMODE == "prefer"


# --- C3 : be sans identifiant partage ----------------------------------------


def test_be_enabled_without_shared_credentials(load_bp):
    bp = load_bp(CREDS_18)
    assert bp.BE_ENABLED is True
    assert bp.BE_SHARED_AVAILABLE is False
    assert bp.BE_SSLMODE == "require"  # identifiant partage be historique (1.7.x)


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
