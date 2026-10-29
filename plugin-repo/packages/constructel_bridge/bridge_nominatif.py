"""Pure logic for the nominative PostgreSQL logins (Bridge 1.8, plan
2026-10-29, spec Farois 2026-10-26 §5.7).

Side-effect-free: no qgis, no psycopg2, no file IO. bridge_plugin.py
consumes these functions; this module never imports it. Everything here is
unit-tested without a QGIS runtime (test_bridge_nominatif.py).

Server facts encoded here (verified 2026-10-29 on prod):
  * the PostgreSQL role of a person is lower(sAMAccountName), matching the
    server-side guard ``^[a-z0-9._-]{1,63}$`` (spec §5.2);
  * psycopg2.connect() failures carry ``pgcode=None``: the SQLSTATE class 28
    of the spec is only readable from the libpq message text;
  * the AD lockout threshold is 0, but the plugin still binds at most twice
    per startup (spec §5.7.4, AC8).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

# --- identity -----------------------------------------------------------------

PG_LOGIN_RE = re.compile(r"^[a-z0-9._-]{1,63}$")


def resolve_pg_login(username: str) -> str:
    """PostgreSQL login of a workstation user: ``lower(username)``.

    Returns "" when the result would not be accepted by the server-side
    provisioning guard (spaces, domain prefix, quotes, too long...): the
    caller then skips the nominative attempt instead of binding with a name
    that cannot exist.
    """
    login = (username or "").strip().lower()
    return login if PG_LOGIN_RE.fullmatch(login) else ""


# --- probe failure classification ---------------------------------------------

AUTH_REFUSED = "auth_refused"      # bind refused: the password is wrong (re-prompt once)
LOGIN_DISABLED = "login_disabled"  # role NOLOGIN / unknown / no pg_hba line: not activated

_LOGIN_DISABLED_PATTERNS = (
    re.compile(r"is not permitted to log in"),
    re.compile(r'role "[^"]*" does not exist'),
    re.compile(r"no pg_hba\.conf entry"),
)
_AUTH_REFUSED_PATTERNS = (
    re.compile(r"authentication failed"),  # password / LDAP / SCRAM authentication failed
)


def classify_auth_failure(exc) -> str | None:
    """AUTH_REFUSED, LOGIN_DISABLED, or None when *exc* is not an
    authentication failure (network, TLS, server down: no fallback, spec
    §5.7.5). Never raises.
    """
    try:
        message = str(exc)
    except Exception:  # noqa: BLE001 -- exotic exception object
        return None
    for pattern in _LOGIN_DISABLED_PATTERNS:
        if pattern.search(message):
            return LOGIN_DISABLED
    for pattern in _AUTH_REFUSED_PATTERNS:
        if pattern.search(message):
            return AUTH_REFUSED
    pgcode = getattr(exc, "pgcode", None)
    if isinstance(pgcode, str) and pgcode.startswith("28"):
        return AUTH_REFUSED
    return None


# --- decision after a failed probe --------------------------------------------

AUTH_MODE_NOMINAL = "nominal"
AUTH_MODE_SHARED = "shared"

NOMINAL_SETTINGS_KEYS = {
    "auth_mode": "constructel_bridge/auth_mode",
    "pg_login": "constructel_bridge/pg_login",
}


def decide_after_probe_failure(kind, memorized_mode: str, has_shared_password: bool,
                               reprompted: bool) -> str:
    """"reprompt" (ask the password once more), "fallback" (shared login +
    banner, D7) or "error" (current error behaviour, no fallback).

    A wrong password is re-asked ONCE, and only when the workstation is not
    already in shared mode (a workstation that fell back before gets a
    single silent probe per startup, no dialog). A disabled or unknown login
    never re-prompts: the password is not the problem.
    """
    if kind is None:
        return "error"
    if kind == AUTH_REFUSED and memorized_mode in ("", None, AUTH_MODE_NOMINAL) and not reprompted:
        return "reprompt"
    if has_shared_password:
        return "fallback"
    return "error"


# --- root.crt (libpq trusted roots) -------------------------------------------

def root_crt_file_path(os_name: str = os.name) -> Path:
    """libpq's default trusted-roots file: %APPDATA%\\postgresql\\root.crt on
    Windows, ~/.postgresql/root.crt elsewhere. Same shape as
    bridge_mtls.pgpass_file_path (os_name passed explicitly for tests)."""
    if os_name == "nt":
        return Path(os.getenv("APPDATA", "")) / "postgresql" / "root.crt"
    return Path.home() / ".postgresql" / "root.crt"


_PEM_CERT_RE = re.compile(
    r"-----BEGIN CERTIFICATE-----\s*(?P<body>.*?)\s*-----END CERTIFICATE-----",
    re.DOTALL,
)
_PEM_ANY_RE = re.compile(r"-----BEGIN ([A-Z ]+)-----")


def _normalize_body(body: str) -> str:
    return "".join(body.split())


def pem_blocks(text: str) -> list[str]:
    """Certificate blocks found in *text*, each normalized to the canonical
    layout (header, base64 body in 64-column lines, footer, no trailing
    newline). Non-certificate material is ignored."""
    blocks = []
    for match in _PEM_CERT_RE.finditer(text or ""):
        body = _normalize_body(match.group("body"))
        if not body:
            continue
        lines = [body[i:i + 64] for i in range(0, len(body), 64)]
        blocks.append("-----BEGIN CERTIFICATE-----\n" + "\n".join(lines) + "\n-----END CERTIFICATE-----")
    return blocks


def upsert_root_crt_pem(existing_text: str, blocks: Iterable[str]) -> str:
    """Append every certificate of *blocks* that is not already in
    *existing_text*, which is otherwise preserved verbatim (comments, foreign
    roots, line layout). Certificates match by base64 body, whitespace
    ignored. The result ends with exactly one newline.

    Raises ValueError for a block that is not a certificate (a private key
    must never land in root.crt) or contains no certificate at all.
    """
    present = {_normalize_body(m.group("body")) for m in _PEM_CERT_RE.finditer(existing_text or "")}
    to_add = []
    for block in blocks:
        kinds = _PEM_ANY_RE.findall(block or "")
        if not kinds or any(kind != "CERTIFICATE" for kind in kinds):
            raise ValueError("refusing to write a non-certificate PEM block into root.crt")
        parsed = pem_blocks(block)
        if not parsed:
            raise ValueError("refusing to write an empty certificate block into root.crt")
        for cert in parsed:
            key = _normalize_body(_PEM_CERT_RE.search(cert).group("body"))
            if key in present:
                continue
            present.add(key)
            to_add.append(cert)
    base = (existing_text or "").rstrip("\r\n")
    parts = ([base] if base else []) + to_add
    return "\n".join(parts) + "\n"


def embedded_ca_paths(plugin_dir) -> list[Path]:
    """The two public CA certificates shipped in the plugin package (spec
    §5.5): the Farois DB CA, then the Constructel AD root."""
    certs = Path(plugin_dir) / "certs"
    return [certs / "farois-db-ca.crt", certs / "constructelbe-ca.pem"]


# --- datasource rewriting -----------------------------------------------------

_DS_AUTHCFG_RE = re.compile(r"\bauthcfg=\S+")
_DS_USER_RE = re.compile(r"\buser=(?:'[^']*'|\S+)")
_DS_PASSWORD_RE = re.compile(r"\bpassword=(?:'[^']*'|\S+)")
_DS_SSLMODE_RE = re.compile(r"\bsslmode=\S+")


def rewrite_datasource_nominal(ds: str, login: str, authcfg_id: str) -> str:
    """A QGIS postgres datasource string carrying the nominative identity:
    ``sslmode=verify-full user='<login>' authcfg=<id>`` and never a
    password. Every other token (table, key, srid, geometry...) is kept.
    Idempotent."""
    out = _DS_AUTHCFG_RE.sub("", ds or "")
    out = _DS_USER_RE.sub("", out)
    out = _DS_PASSWORD_RE.sub("", out)
    out = _DS_SSLMODE_RE.sub("", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    return f"{out} sslmode=verify-full user='{login}' authcfg={authcfg_id}".strip()


# --- session scope (volet D) --------------------------------------------------

@dataclass(frozen=True)
class SessionScope:
    role: str | None
    network_read: bool
    network_write: bool
    bypass: bool  # ADMIN/MANAGER: the server returns NULL arrays = everything
    mro_ids: list = field(default_factory=list)
    mro_write_ids: list = field(default_factory=list)
    pop_ids: list = field(default_factory=list)
    pop_write_ids: list = field(default_factory=list)


SCOPE_QUERY = (
    "SELECT public.current_gis_role(), "
    "public.current_gis_has_capability('network.read'), "
    "public.current_gis_has_capability('network.write'), "
    "public.current_gis_mro_ids(false), public.current_gis_mro_ids(true), "
    "public.current_gis_pop_ids(false), public.current_gis_pop_ids(true)"
)


def _ids(value) -> list:
    return [str(v) for v in value] if value else []


def parse_session_scope(row: Sequence) -> SessionScope:
    """Build a SessionScope from one row of SCOPE_QUERY. NULL id arrays mean
    "no restriction" (bypass_scopes of current_verified_gis_user)."""
    role, can_read, can_write, mro_all, mro_write, pop_all, pop_write = row
    bypass = mro_all is None and pop_all is None
    return SessionScope(
        role=role,
        network_read=bool(can_read),
        network_write=bool(can_write),
        bypass=bypass,
        mro_ids=_ids(mro_all),
        mro_write_ids=_ids(mro_write),
        pop_ids=_ids(pop_all),
        pop_write_ids=_ids(pop_write),
    )


def scope_kind(scope: SessionScope) -> str:
    """"all" (bypass), "scoped" (at least one MRO/POP) or "none" (no
    perimeter: network layers come back empty, by design)."""
    if scope.bypass:
        return "all"
    if scope.mro_ids or scope.pop_ids:
        return "scoped"
    return "none"


def scope_labels(ids: Sequence[str], names: dict) -> list[str]:
    """Human labels for scope ids: the name when known, else the first
    block of the UUID. Sorted for a stable display."""
    return sorted(str(names.get(i) or str(i).split("-")[0]) for i in ids)


def should_lock_layer(schema: str, scope: SessionScope | None) -> bool:
    """True when a layer of *schema* must be set read-only in QGIS: a
    nominative session without network.write on an operator schema. Shared
    mode (scope None) and the public/ref schemas are never locked."""
    if scope is None or scope.network_write:
        return False
    return schema not in ("public", "ref", "")


_SCOPE_REFUSAL_RE = re.compile(
    r"permission denied|row-level security|42501|gis_scope|perimetre|périmètre",
    re.IGNORECASE,
)


def is_scope_write_refusal(message: str) -> bool:
    """True when a commit error message is the server refusing a write for
    scope/capability reasons (RLS policy, trg_enforce_gis_scope, 42501)."""
    return bool(_SCOPE_REFUSAL_RE.search(message or ""))
