"""Characterization tests for bridge_identity.py (PR Bridge 0, 2026-09-22).

These lock in the CURRENT behavior of logic extracted from
bridge_plugin.py. No QGIS import required — run with plain `pytest`.
"""
import base64

from constructel_bridge.bridge_identity import (
    build_set_config_sql,
    decode_password,
    derive_email,
    parse_credentials_json,
    resolve_credentials_for_realm,
    resolve_username,
)


# --- resolve_username -------------------------------------------------

def test_resolve_username_prefers_explicit_setting():
    result = resolve_username("alice.override", "bob_profile", "carol_os")
    assert result == "alice.override"


def test_resolve_username_falls_back_to_profile_name():
    result = resolve_username("", "bob_profile", "carol_os")
    assert result == "bob_profile"


def test_resolve_username_ignores_default_profile_name():
    result = resolve_username("", "default", "carol_os")
    assert result == "carol_os"


def test_resolve_username_falls_back_to_os_username():
    result = resolve_username("", "", "carol_os")
    assert result == "carol_os"


# --- derive_email -------------------------------------------------------

def test_derive_email_matches_hardcoded_domain():
    assert derive_email("jdupont") == "jdupont@constructel.be"


def test_derive_email_accepts_custom_domain():
    assert derive_email("jdupont", domain="example.com") == "jdupont@example.com"


# --- parse_credentials_json ---------------------------------------------

def test_parse_credentials_json_nested_format_passthrough():
    raw = {"wyre": {"host": "h"}, "be": {"host": "h2"}}
    assert parse_credentials_json(raw) == raw


def test_parse_credentials_json_flat_format_attaches_to_wyre():
    raw = {"host": "h", "port": 5432, "dbname": "db", "user": "u", "password": "cGFzcw=="}
    result = parse_credentials_json(raw)
    assert result["wyre"] == raw
    assert result["be"] == {}


# --- decode_password ------------------------------------------------------

def test_decode_password_roundtrip():
    encoded = base64.b64encode(b"s3cr3t").decode()
    assert decode_password(encoded) == "s3cr3t"


# --- resolve_credentials_for_realm ----------------------------------------

DEFAULT_KWARGS = dict(
    be_enabled=True,
    be_host="db.example.internal",
    be_user="bureau_etudes",
    be_password="be-pw",
    default_host="db.example.internal",
    default_user="ftth_editor",
    default_password="wyre-pw",
)


def test_resolve_credentials_be_matched_by_username():
    result = resolve_credentials_for_realm(
        "dbname='farois_ftth' host=db.example.internal port=5432",
        "bureau_etudes",
        **DEFAULT_KWARGS,
    )
    assert result == ("bureau_etudes", "be-pw")


def test_resolve_credentials_be_matched_by_realm_user_clause():
    result = resolve_credentials_for_realm(
        "dbname='farois_ftth' host=db.example.internal user='bureau_etudes'",
        "someone_else",
        **DEFAULT_KWARGS,
    )
    assert result == ("bureau_etudes", "be-pw")


def test_resolve_credentials_falls_back_to_default_host():
    result = resolve_credentials_for_realm(
        "dbname='farois_ftth' host=db.example.internal port=5432",
        "someone_else",
        **DEFAULT_KWARGS,
    )
    assert result == ("ftth_editor", "wyre-pw")


def test_resolve_credentials_be_disabled_falls_back_to_default():
    kwargs = dict(DEFAULT_KWARGS, be_enabled=False)
    result = resolve_credentials_for_realm(
        "dbname='farois_ftth' host=db.example.internal user='bureau_etudes'",
        "bureau_etudes",
        **kwargs,
    )
    assert result == ("ftth_editor", "wyre-pw")


def test_resolve_credentials_unrelated_realm_returns_none():
    result = resolve_credentials_for_realm(
        "dbname='other_db' host=third-party.example.com",
        "someone",
        **DEFAULT_KWARGS,
    )
    assert result is None


def test_resolve_credentials_third_party_host_with_be_username_does_not_leak():
    # Regression guard for the credential-leak scenario documented in
    # bridge_plugin.py's _credentials_for docstring: a third-party PG
    # server where the username happens to equal be_user must NOT
    # receive the be password.
    result = resolve_credentials_for_realm(
        "dbname='other_db' host=third-party.example.com",
        "bureau_etudes",
        **DEFAULT_KWARGS,
    )
    assert result is None



def test_resolve_credentials_be_host_distinct_from_default_host_anchors_correctly():
    # be_host deliberately DIFFERENT from default_host — proves the function
    # anchors the be-branch on be_host specifically, not on default_host.
    # (Regression guard: a mutant that swaps be_host->default_host in the
    # source's first condition passes every OTHER existing test in this
    # file, because they all set be_host == default_host.)
    result = resolve_credentials_for_realm(
        "dbname='farois_ftth' host=be.example.internal user='bureau_etudes'",
        "someone_else",
        be_enabled=True,
        be_host="be.example.internal",
        be_user="bureau_etudes",
        be_password="be-pw",
        default_host="db.example.internal",
        default_user="ftth_editor",
        default_password="wyre-pw",
    )
    assert result == ("bureau_etudes", "be-pw")

# --- build_set_config_sql --------------------------------------------------

def test_build_set_config_sql_simple_username():
    set_config_sql, app_name_sql = build_set_config_sql("jdupont")
    assert set_config_sql == "SELECT set_config('app.current_user', 'jdupont', true)"
    assert app_name_sql == "SET application_name = 'constructel_bridge:jdupont'"


def test_build_set_config_sql_escapes_single_quote():
    # Characterizes the CURRENT naive escaping (doubled quote), not a fix.
    set_config_sql, app_name_sql = build_set_config_sql("o'brien")
    assert set_config_sql == "SELECT set_config('app.current_user', 'o''brien', true)"
    assert app_name_sql == "SET application_name = 'constructel_bridge:o''brien'"
