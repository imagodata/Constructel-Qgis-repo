"""Unit tests for bridge_mtls.py (PR Bridge 1, 2026-09-23).

No QGIS import required. Certificate validation tests use real, small,
throwaway certs generated into a pytest tmp_path fixture — not mocks —
since openssl's own exit codes and stderr text are exactly what the
function under test parses.
"""
import subprocess

import pytest

from constructel_bridge.bridge_mtls import (
    build_pgpass_line,
    build_pki_paths_authcfg_config,
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
