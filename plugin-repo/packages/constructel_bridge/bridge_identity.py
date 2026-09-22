"""Pure identity/credential-resolution logic, extracted from
bridge_plugin.py for unit testing without a QGIS runtime (PR Bridge 0,
2026-09-22).

These functions must stay side-effect-free: no QGIS, no psycopg2, no file
I/O beyond what's passed in as plain arguments. bridge_plugin.py delegates
to them; this module has no dependency on bridge_plugin.py.
"""
from __future__ import annotations

import base64


def resolve_username(explicit_setting: str, profile_name: str, os_username: str) -> str:
    """Reproduces the resolution order of _get_qgis_username():
    1. explicit QgsSettings override, if non-empty
    2. QGIS profile name, if set and not "default"
    3. OS username (getpass.getuser())
    """
    if explicit_setting:
        return explicit_setting
    if profile_name and profile_name != "default":
        return profile_name
    return os_username


def derive_email(username: str, domain: str = "constructel.be") -> str:
    """Reproduces the email construction in _register_bridge_user():
    f"{username}@constructel.be" hardcoded — domain kept as a parameter
    here for testability, default matches the hardcoded value exactly.
    
    IMPORTANT: The hardcoded default="constructel.be" is deliberate and preserves
    the original pre-refactor behavior. bridge_plugin.py has a configurable
    EMAIL_DOMAIN that bridge_onboarding.py already uses; wiring EMAIL_DOMAIN into
    this function would be a user-visible behavior change (different emails written
    to ref.users for deployments with email_domain configured) and requires an
    explicit design decision, not a drive-by refactor.
    """
    return f"{username}@{domain}"


def parse_credentials_json(raw: dict) -> dict:
    """Reproduces the flat-vs-nested normalization in _load_credentials().

    Pre-1.5.0 deployments have a FLAT object (host/port/... at the root).
    Since 1.5.0, credentials.json has named blocks {"wyre": {...}, "be":
    {...}}. A flat object is attached to "wyre"; "be" stays empty rather
    than raising a KeyError at import time (which would prevent the whole
    plugin from loading, wyre included).
    """
    if "host" in raw:
        return {"wyre": raw, "be": {}}
    return raw


def decode_password(b64_password: str) -> str:
    """Reproduces the base64 decode used for both wyre and be passwords."""
    return base64.b64decode(b64_password).decode()


def resolve_credentials_for_realm(
    realm: str,
    username: str,
    *,
    be_enabled: bool,
    be_host: str,
    be_user: str,
    be_password: str,
    default_host: str,
    default_user: str,
    default_password: str,
) -> tuple[str, str] | None:
    """Reproduces _BridgeCredentials._credentials_for() exactly.

    `be` is tested FIRST (more specific): only recognized if the BE user
    appears explicitly in the realm string (QGIS embeds `user='...'` when
    the connection remembers its username) or as the `username` argument.
    Anchored on be_host (not default_host): a request toward a
    THIRD-PARTY PG server where username happens to equal be_user must
    NOT receive the be password — anchoring on be_host prevents that
    credential leak. Falls back to (default_user, default_password) if
    default_host is in realm. Returns None if the realm doesn't concern
    us at all.
    """
    if be_enabled and be_host in realm and (f"user='{be_user}'" in realm or username == be_user):
        return be_user, be_password
    if default_host in realm:
        return default_user, default_password
    return None


def build_set_config_sql(username: str) -> tuple[str, str]:
    """Reproduces the manual-escaping fallback branch of
    _on_before_commit() used when provider.executeSql() (no parameterized
    API) is the only option. Returns (set_config_sql, application_name_sql).

    KNOWN LIMITATION, characterized not fixed by PR Bridge 0: this is a
    naive doubled-quote escape (`.replace("'", "''")`), not a real SQL
    literal encoder. It does not handle backslashes specially and assumes
    standard_conforming_strings=on (PostgreSQL default since 9.1). Do not
    extend this pattern to new call sites; the parameterized cursor path
    (used whenever self._conn is available) remains the safe default.
    """
    safe_user = username.replace("'", "''")
    set_config_sql = f"SELECT set_config('app.current_user', '{safe_user}', true)"
    application_name_sql = f"SET application_name = 'constructel_bridge:{safe_user}'"
    return set_config_sql, application_name_sql
