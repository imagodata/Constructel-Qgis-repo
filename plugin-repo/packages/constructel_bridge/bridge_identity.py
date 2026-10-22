"""Pure identity/credential-resolution logic, extracted from
bridge_plugin.py for unit testing without a QGIS runtime (PR Bridge 0,
2026-09-22).

These functions must stay side-effect-free: no QGIS, no psycopg2, no file
I/O beyond what's passed in as plain arguments. bridge_plugin.py delegates
to them; this module has no dependency on bridge_plugin.py.
"""
from __future__ import annotations

import base64
import re


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


def fixed_authcfg_id_for_user(
    user: str,
    *,
    wyre_user: str,
    wyre_authcfg_id: str,
    be_enabled: bool,
    be_user: str,
    be_authcfg_id: str,
) -> str:
    """Return the FIXED Auth Manager config id attached to a PG user.

    The id is identical on every workstation, so a project saved with
    ``authcfg=<id>`` opens anywhere the plugin created that config (no
    plaintext password stored in the .qgz). `be` is only recognised when
    enabled. Returns "" for any other user.
    """
    if be_enabled and be_user and user == be_user:
        return be_authcfg_id
    if wyre_user and user == wyre_user:
        return wyre_authcfg_id
    return ""


def stale_config_ids(configs: dict, name: str, fixed_id: str) -> list:
    """Ids of Auth Manager configs called *name* whose id is NOT *fixed_id*.

    ``configs`` maps config id -> config name. Only configs carrying the
    plugin's own name are considered: foreign configs are never listed.
    Sorted for a deterministic cleanup order.
    """
    return sorted(cid for cid, cname in configs.items() if cname == name and cid != fixed_id)


AUDIT_EMAIL_MAX_LEN = 255
_AUDIT_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
# Any previous app.current_user option, in libpq's "-c name=value",
# "-cname=value" or "--name=value" forms.
_PGOPTIONS_APP_USER_RE = re.compile(r"(?<!\S)(?:-c\s*|--)app\.current_user=\S*")


def is_valid_audit_email(email) -> bool:
    """True if *email* may be passed verbatim in libpq PGOPTIONS.

    Whitelist only: no whitespace, quote, comma or backslash can reach the
    libpq options parser (which splits on whitespace and treats backslash
    as an escape). The address is DECLARED by the workstation: traceability
    only, never a proof of identity (spec 2026-10-15).
    """
    return (
        isinstance(email, str)
        and 0 < len(email) <= AUDIT_EMAIL_MAX_LEN
        and _AUDIT_EMAIL_RE.fullmatch(email) is not None
    )


def build_pgoptions(existing, email):
    """Return the PGOPTIONS value carrying ``app.current_user=<email>``.

    Keeps every option already set on the workstation, drops any previous
    app.current_user option so values never pile up, and appends the new
    one. An invalid or missing *email* returns *existing* unchanged
    (possibly None): an invalid address is never sent.
    """
    if not is_valid_audit_email(email):
        return existing
    kept = " ".join(_PGOPTIONS_APP_USER_RE.sub(" ", existing or "").split())
    option = f"-c app.current_user={email}"
    return f"{kept} {option}" if kept else option


def strip_app_user_option(existing):
    """Return *existing* PGOPTIONS without any app.current_user option, or
    None when nothing else remains. Used to withdraw a stale address so an
    edit is never attributed to a previous (or different) user."""
    kept = " ".join(_PGOPTIONS_APP_USER_RE.sub(" ", existing or "").split())
    return kept or None
