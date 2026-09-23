"""Unit tests for bridge_mtls.py (PR Bridge 1, 2026-09-23).

No QGIS import required. Certificate validation tests use real, small,
throwaway certs generated into a pytest tmp_path fixture — not mocks —
since openssl's own exit codes and stderr text are exactly what the
function under test parses.
"""
import os
import subprocess
from pathlib import Path

import pytest

from constructel_bridge.bridge_mtls import (
    MTLS_SETTINGS_KEYS,
    build_pgpass_line,
    build_pki_paths_authcfg_config,
    needs_mtls_migration,
    pgpass_file_path,
    upsert_pgpass_entry,
    validate_client_certificate,
)


def _run(*args):
    subprocess.run(args, check=True, capture_output=True)


@pytest.fixture
def valid_cert_bundle(tmp_path):
    """A real CA + client cert with clientAuth EKU, valid for 1 day."""
    ca_key = tmp_path / "ca.key"
    ca_crt = tmp_path / "ca.crt"
    client_key = tmp_path / "client.key"
    client_csr = tmp_path / "client.csr"
    client_crt = tmp_path / "client.crt"
    ext_file = tmp_path / "client_ext.cnf"
    ext_file.write_text("extendedKeyUsage = clientAuth\n")

    _run("openssl", "req", "-new", "-x509", "-days", "1", "-nodes",
         "-subj", "/CN=test-ca", "-keyout", str(ca_key), "-out", str(ca_crt))
    _run("openssl", "req", "-new", "-nodes", "-subj", "/CN=test_person",
         "-keyout", str(client_key), "-out", str(client_csr))
    _run("openssl", "x509", "-req", "-in", str(client_csr), "-CA", str(ca_crt),
         "-CAkey", str(ca_key), "-CAcreateserial", "-days", "1",
         "-extfile", str(ext_file), "-out", str(client_crt))
    return {"cert": str(client_crt), "key": str(client_key), "ca": str(ca_crt)}


def test_validate_client_certificate_accepts_valid_cert(valid_cert_bundle):
    result = validate_client_certificate(
        valid_cert_bundle["cert"], valid_cert_bundle["key"], valid_cert_bundle["ca"]
    )
    assert result.ok is True
    assert result.reason is None


def test_validate_client_certificate_missing_cert_file(tmp_path, valid_cert_bundle):
    result = validate_client_certificate(
        str(tmp_path / "does_not_exist.crt"), valid_cert_bundle["key"], valid_cert_bundle["ca"]
    )
    assert result.ok is False
    assert result.reason == "cert_missing"


def test_validate_client_certificate_missing_key_file(tmp_path, valid_cert_bundle):
    result = validate_client_certificate(
        valid_cert_bundle["cert"], str(tmp_path / "does_not_exist.key"), valid_cert_bundle["ca"]
    )
    assert result.ok is False
    assert result.reason == "key_missing"


def test_validate_client_certificate_wrong_ca_rejects_chain(tmp_path, valid_cert_bundle):
    # A second, unrelated CA — the client cert was NOT signed by it.
    other_ca_key = tmp_path / "other_ca.key"
    other_ca_crt = tmp_path / "other_ca.crt"
    _run("openssl", "req", "-new", "-x509", "-days", "1", "-nodes",
         "-subj", "/CN=other-ca", "-keyout", str(other_ca_key), "-out", str(other_ca_crt))
    result = validate_client_certificate(
        valid_cert_bundle["cert"], valid_cert_bundle["key"], str(other_ca_crt)
    )
    assert result.ok is False
    assert result.reason == "chain_invalid"


def test_validate_client_certificate_expired(tmp_path):
    ca_key = tmp_path / "ca.key"
    ca_crt = tmp_path / "ca.crt"
    client_key = tmp_path / "client.key"
    client_csr = tmp_path / "client.csr"
    client_crt = tmp_path / "client.crt"
    _run("openssl", "req", "-new", "-x509", "-days", "1", "-nodes",
         "-subj", "/CN=test-ca", "-keyout", str(ca_key), "-out", str(ca_crt))
    _run("openssl", "req", "-new", "-nodes", "-subj", "/CN=expired_person",
         "-keyout", str(client_key), "-out", str(client_csr))
    # -days -1: already expired at issuance.
    _run("openssl", "x509", "-req", "-in", str(client_csr), "-CA", str(ca_crt),
         "-CAkey", str(ca_key), "-CAcreateserial", "-days", "-1",
         "-out", str(client_crt))
    result = validate_client_certificate(str(client_crt), str(client_key), str(ca_crt))
    assert result.ok is False
    assert result.reason == "expired"


def test_validate_client_certificate_missing_client_auth_eku(tmp_path):
    # A cert signed by the CA but WITHOUT the clientAuth extended key
    # usage — rejected by the explicit EKU check (openssl's own verify
    # with -purpose sslclient returns OK for EKU-less certs).
    ca_key = tmp_path / "ca.key"
    ca_crt = tmp_path / "ca.crt"
    client_key = tmp_path / "client.key"
    client_csr = tmp_path / "client.csr"
    client_crt = tmp_path / "client.crt"
    _run("openssl", "req", "-new", "-x509", "-days", "1", "-nodes",
         "-subj", "/CN=test-ca", "-keyout", str(ca_key), "-out", str(ca_crt))
    _run("openssl", "req", "-new", "-nodes", "-subj", "/CN=no_eku_person",
         "-keyout", str(client_key), "-out", str(client_csr))
    # No -extfile: no extendedKeyUsage at all.
    _run("openssl", "x509", "-req", "-in", str(client_csr), "-CA", str(ca_crt),
         "-CAkey", str(ca_key), "-CAcreateserial", "-days", "1",
         "-out", str(client_crt))
    result = validate_client_certificate(str(client_crt), str(client_key), str(ca_crt))
    assert result.ok is False
    assert result.reason == "missing_client_auth_eku"


def test_build_pki_paths_authcfg_config():
    config = build_pki_paths_authcfg_config("bridge_mtls_cert", "/path/to/cert.pem", "/path/to/key.pem")
    assert config == {
        "method": "PKI-Paths",
        "name": "bridge_mtls_cert",
        "config": {"certpath": "/path/to/cert.pem", "keypath": "/path/to/key.pem"},
    }


def test_build_pgpass_line_simple():
    line = build_pgpass_line("db.example.internal", 5432, "farois_ftth", "ftth_editor", "s3cr3t")
    assert line == "db.example.internal:5432:farois_ftth:ftth_editor:s3cr3t"


def test_build_pgpass_line_escapes_colon_and_backslash():
    # Per https://www.postgresql.org/docs/current/libpq-pgpass.html :
    # ":" and "\\" in any field must be escaped with a preceding "\\".
    line = build_pgpass_line("db.example.internal", 5432, "farois_ftth", "ftth_editor", "p:a\\ss")
    assert line == "db.example.internal:5432:farois_ftth:ftth_editor:p\\:a\\\\ss"


def test_needs_migration_old_basic_authcfg_password_connection():
    settings = {"host": "db.example.internal", "sslmode": "3", "authcfg": "basic_cfg_id", "savePassword": False}
    assert needs_mtls_migration(settings, "Basic") is True


def test_needs_migration_already_migrated_pki_connection():
    settings = {"host": "db.example.internal", "sslmode": "5", "authcfg": "pki_cfg_id", "savePassword": False}
    assert needs_mtls_migration(settings, "PKI-Paths") is False


def test_needs_migration_no_authcfg_at_all():
    settings = {"host": "db.example.internal", "sslmode": "3", "authcfg": "", "savePassword": False}
    assert needs_mtls_migration(settings, "Basic") is True


# --- upsert_pgpass_entry ------------------------------------------------


def test_upsert_pgpass_entry_replaces_same_key():
    existing = "other:5432:db:u:pw\ndb.example.internal:5432:farois_ftth:ftth_editor:oldpw\nother2:5432:db:u:pw\n"
    new = "db.example.internal:5432:farois_ftth:ftth_editor:newpw"
    assert upsert_pgpass_entry(existing, new) == (
        "other:5432:db:u:pw\ndb.example.internal:5432:farois_ftth:ftth_editor:newpw\nother2:5432:db:u:pw\n"
    )


def test_upsert_pgpass_entry_appends_new_key():
    existing = "other:5432:db:u:pw\n"
    new = "db.example.internal:5432:farois_ftth:ftth_editor:s3cr3t"
    assert upsert_pgpass_entry(existing, new) == existing + new + "\n"


def test_upsert_pgpass_entry_empty_file():
    assert upsert_pgpass_entry("", "h:5432:d:u:p") == "h:5432:d:u:p\n"


def test_upsert_pgpass_entry_preserves_comments_blanks_and_malformed():
    existing = "# a comment\n\ngarbage-without-colons\nh:5432:d:u:old\n"
    assert upsert_pgpass_entry(existing, "h:5432:d:u:new") == (
        "# a comment\n\ngarbage-without-colons\nh:5432:d:u:new\n"
    )


def test_upsert_pgpass_entry_escapes_honored_in_key():
    existing = "my\\:host:5432:d:u:old\n"
    assert upsert_pgpass_entry(existing, "my\\:host:5432:d:u:new") == "my\\:host:5432:d:u:new\n"


def test_upsert_pgpass_entry_rejects_malformed_new_line():
    with pytest.raises(ValueError):
        upsert_pgpass_entry("h:5432:d:u:pw\n", "not-a-pgpass-line")


def test_upsert_pgpass_entry_rejects_embedded_line_break():
    # A newline inside new_line would inject a rogue second entry.
    with pytest.raises(ValueError):
        upsert_pgpass_entry("h:5432:d:u:pw\n", "h:5432:d:u:pw\ninjected:1:2:3:4")


# --- pgpass_file_path ---------------------------------------------------


def test_pgpass_file_path_posix(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert pgpass_file_path("posix") == tmp_path / ".pgpass"


def test_pgpass_file_path_windows(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert pgpass_file_path("nt") == tmp_path / "postgresql" / "pgpass.conf"


@pytest.mark.skipif(os.name == "nt", reason="default follows live platform; nt covered by explicit-arg test")
def test_pgpass_file_path_defaults_to_live_platform():
    assert pgpass_file_path() == Path.home() / ".pgpass"


# --- MTLS_SETTINGS_KEYS -----------------------------------------------------


def test_mtls_settings_keys():
    # Exact key strings: a typo here would silently fork the settings.
    assert MTLS_SETTINGS_KEYS == {
        "enabled": "constructel_bridge/mtls_enabled",
        "cert_path": "constructel_bridge/mtls_cert_path",
        "key_path": "constructel_bridge/mtls_key_path",
        "ca_path": "constructel_bridge/mtls_ca_path",
        "authcfg_id": "constructel_bridge/mtls_authcfg_id",
    }
