"""Certificate validation and connection-config builders for mTLS
(PR Bridge 1, 2026-09-23).

Side-effect-free except for shelling out to `openssl` (read-only
inspection, never writes/generates keys here — key generation is a
Farois/Constructel runbook responsibility, not this plugin's). No qgis
import: bridge_plugin.py consumes these functions, this module does not
depend on it or on QGIS being importable.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CertValidationResult:
    ok: bool
    reason: str | None  # None when ok=True; one of the named reasons below otherwise


def validate_client_certificate(cert_path: str, key_path: str, ca_path: str) -> CertValidationResult:
    """Validates a client certificate is usable for mTLS: present, chains
    to the given CA, not expired/not-yet-valid, and carries the clientAuth
    extended key usage. Does not check the key matches the cert (libpq
    itself will refuse to connect if they don't — this is a pre-flight UX
    check, not the security boundary).
    """
    if not Path(cert_path).is_file():
        return CertValidationResult(ok=False, reason="cert_missing")
    if not Path(key_path).is_file():
        return CertValidationResult(ok=False, reason="key_missing")

    # `verify -purpose sslclient` checks chain validity and time validity;
    # its stderr distinguishes the failure modes by message, since it
    # returns a single non-zero exit either way. NOTE: it does NOT reject
    # certs with no extendedKeyUsage at all (OpenSSL 3.0.2 returns "OK"
    # for those — verified empirically on this host), so the clientAuth
    # requirement is enforced explicitly below instead.
    verify = subprocess.run(
        ["openssl", "verify", "-purpose", "sslclient", "-CAfile", ca_path, cert_path],
        capture_output=True, text=True,
    )
    if verify.returncode != 0:
        if "unable to get local issuer certificate" in verify.stderr or "certificate signature failure" in verify.stderr:
            return CertValidationResult(ok=False, reason="chain_invalid")
        if "certificate has expired" in verify.stderr:
            return CertValidationResult(ok=False, reason="expired")
        if "certificate is not yet valid" in verify.stderr:
            return CertValidationResult(ok=False, reason="not_yet_valid")
        if "unhandled critical extension" in verify.stderr or "unsupported certificate purpose" in verify.stderr:
            return CertValidationResult(ok=False, reason="missing_client_auth_eku")
        return CertValidationResult(ok=False, reason="chain_invalid")

    # Explicit clientAuth EKU enforcement: `verify` above accepts certs
    # with no EKU at all (RFC 5280: absent EKU = valid for all purposes —
    # confirmed live on this host's OpenSSL 3.0.2), so require clientAuth
    # in the cert's own Extended Key Usage section. Scoped to that section
    # only (`-ext`), so a coincidental usage string elsewhere in the cert
    # (e.g. the subject CN) cannot false-pass.
    eku = subprocess.run(
        ["openssl", "x509", "-in", cert_path, "-noout", "-ext", "extendedKeyUsage"],
        capture_output=True, text=True,
    )
    if "TLS Web Client Authentication" not in eku.stdout:
        return CertValidationResult(ok=False, reason="missing_client_auth_eku")

    return CertValidationResult(ok=True, reason=None)


def build_pki_paths_authcfg_config(name: str, cert_path: str, key_path: str) -> dict:
    """Shape of a QGIS QgsAuthMethodConfig("PKI-Paths") — certificate and
    key ONLY, never a password (see Global Constraints: bug #58179 means
    the password must never travel through an authcfg on a cert-bearing
    connection). bridge_plugin.py turns this dict into a real
    QgsAuthMethodConfig via .setConfig() calls, mirroring
    _store_password_encrypted()'s existing pattern for the "Basic" method.
    """
    return {
        "method": "PKI-Paths",
        "name": name,
        "config": {"certpath": cert_path, "keypath": key_path},
    }


def build_pgpass_line(host: str, port: int, dbname: str, username: str, password: str) -> str:
    """Builds one line of a libpq .pgpass file. Escapes ':' and '\\' in
    every field per https://www.postgresql.org/docs/current/libpq-pgpass.html
    — the password field is where this matters in practice, but all
    fields are escaped for correctness.
    """
    def esc(field: str) -> str:
        return str(field).replace("\\", "\\\\").replace(":", "\\:")

    return f"{esc(host)}:{esc(port)}:{esc(dbname)}:{esc(username)}:{esc(password)}"


def needs_mtls_migration(connection_settings: dict, authcfg_method: str | None) -> bool:
    """True if an existing QGIS PG connection needs migrating to the
    cert+.pgpass pattern: no authcfg at all, or an authcfg whose method
    is "Basic" (the pre-Bridge-1 pattern). False if it already has a
    "PKI-Paths" authcfg (already migrated). An unknown or None method
    also returns True (fail-safe: re-migration is idempotent).
    """
    authcfg = connection_settings.get("authcfg", "")
    if not authcfg:
        return True
    return authcfg_method != "PKI-Paths"
