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

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

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


# --- CA du serveur (verify-full) ---------------------------------------------
#
# Revue 29/10 (D-TLS-1) : plus de root.crt sur le poste. QGIS remplace tout
# sslrootcert= d'une couche authcfg en verify-* par un fichier temporaire de
# ses CA de confiance (QgsAuthBasicMethod::updateDataSourceUriItems) : les CA
# sont donc importées dans la base d'authentification QGIS
# (bridge_plugin._ensure_qgis_trusted_cas) ; la connexion psycopg2 du
# plugin, elle, lit le bundle en lecture seule dans le paquet.

_PEM_CERT_RE = re.compile(
    r"-----BEGIN CERTIFICATE-----\s*(?P<body>.*?)\s*-----END CERTIFICATE-----",
    re.DOTALL,
)


def pem_blocks(text: str) -> list[str]:
    """Certificate blocks found in *text*, each normalized to the canonical
    layout (header, base64 body in 64-column lines, footer, no trailing
    newline). Non-certificate material is ignored."""
    blocks = []
    for match in _PEM_CERT_RE.finditer(text or ""):
        body = "".join(match.group("body").split())
        if not body:
            continue
        lines = [body[i:i + 64] for i in range(0, len(body), 64)]
        blocks.append("-----BEGIN CERTIFICATE-----\n" + "\n".join(lines) + "\n-----END CERTIFICATE-----")
    return blocks


def embedded_ca_paths(plugin_dir) -> list[Path]:
    """The two public CA certificates shipped in the plugin package (spec
    §5.5): the Farois DB CA, then the Constructel AD root."""
    certs = Path(plugin_dir) / "certs"
    return [certs / "farois-db-ca.crt", certs / "constructelbe-ca.pem"]


def ca_bundle_path(plugin_dir) -> Path:
    """Bundle PEM des deux CA (même ordre), passé en ``sslrootcert`` à la
    connexion psycopg2 nominative : lu en place dans le paquet, aucune
    écriture sur le poste."""
    return Path(plugin_dir) / "certs" / "root-ca-bundle.pem"


# --- datasource rewriting -----------------------------------------------------
#
# Revue 29/10 (I12/M5) : une datasource postgres se termine souvent par
# ``table="s"."t" (geom) sql=<filtre>`` et QgsDataSourceUri lit TOUT ce qui
# suit ``sql=`` comme filtre. Ajouter des jetons en fin de chaîne corrompait
# donc le filtre (et l'authcfg était perdu) ; des regex naïves rataient
# aussi les valeurs à apostrophe échappée (``password='pa\'ss word'``). Le
# découpage ci-dessous suit exactement QgsDataSourceUri::QgsDataSourceUri /
# getValue (QGIS 3.28 -> 4.x) et ne touche jamais au texte après ``sql=``.

_IDENTITY_KEYS = frozenset({"user", "password", "authcfg"})


def _ds_skip_blanks(text: str, i: int) -> int:
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def _ds_read_value(text: str, i: int) -> tuple[str, int]:
    """Valeur commençant en *i* (règles de QgsDataSourceUri::getValue) :
    (valeur déséchappée, position juste après la valeur, blancs exclus)."""
    n = len(text)
    out = []
    if i < n and text[i] in ("'", '"'):
        delim = text[i]
        i += 1
        while True:
            if i >= n:
                break  # chaîne non terminée : QGIS s'arrête aussi
            if text[i] == "\\":
                i += 1
                if i >= n:
                    continue
                if text[i] not in (delim, "\\"):
                    i -= 1
            elif text[i] == delim:
                i += 1
                break
            out.append(text[i])
            i += 1
    else:
        while i < n and not text[i].isspace():
            if text[i] == "\\":
                i += 1
                if i >= n:
                    break
                if text[i] not in ("\\", "'"):
                    i -= 1
            out.append(text[i])
            i += 1
    return "".join(out), i


def parse_datasource(ds: str) -> tuple[list, int | None]:
    """Paramètres d'une datasource postgres QGIS, dans l'ordre :
    ``[(clé, valeur déséchappée, début, fin)]`` où ``ds[début:fin]`` est le
    jeton brut (``table=`` englobe ``."table"`` et ``(geom)``), et la
    position du ``sql=`` final (None s'il n'y en a pas)."""
    text = ds or ""
    n = len(text)
    params = []
    i = 0
    while i < n:
        i = _ds_skip_blanks(text, i)
        if i >= n:
            break
        if text[i] == "=":
            i += 1
            continue
        start = i
        while i < n and text[i] != "=" and not text[i].isspace():
            i += 1
        name = text[start:i]
        i = _ds_skip_blanks(text, i)
        if i >= n or text[i] != "=":
            continue  # mot sans « = » : ignoré, comme QGIS
        i += 1
        if name == "sql":
            return params, start
        value, end = _ds_read_value(text, i)
        if name == "table":
            j = _ds_skip_blanks(text, end)
            if j < n and text[j] == ".":
                table, end = _ds_read_value(text, j + 1)
                value = f"{value}.{table}"
            j = _ds_skip_blanks(text, end)
            if j < n and text[j] == "(":
                j += 1
                while j < n and text[j] != ")":
                    if text[j] == "\\":
                        j += 1
                    j += 1
                end = min(j + 1, n)
        params.append((name, value, start, end))
        i = end
    return params, None


def datasource_param(ds: str, name: str) -> str | None:
    """Valeur (déséchappée) du premier paramètre *name* avant ``sql=``,
    None s'il est absent."""
    for key, value, _start, _end in parse_datasource(ds)[0]:
        if key == name:
            return value
    return None


def _ds_quote(value: str) -> str:
    # Même échappement que QgsDataSourceUri::escape.
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _rewrite_datasource(ds: str, drop, tokens) -> str:
    """Retire les paramètres *drop* et insère *tokens* juste avant
    ``table=`` (sinon avant ``sql=``, sinon en fin). Les autres jetons sont
    conservés tels quels, le filtre ``sql=`` à l'octet près."""
    text = ds or ""
    params, sql_start = parse_datasource(text)
    kept = [(name, text[start:end]) for (name, _value, start, end) in params if name not in drop]
    names = [name for name, _raw in kept]
    pos = names.index("table") if "table" in names else len(kept)
    parts = [raw for _n, raw in kept[:pos]] + list(tokens) + [raw for _n, raw in kept[pos:]]
    out = " ".join(parts)
    if sql_start is not None:
        out = f"{out} {text[sql_start:]}" if out else text[sql_start:]
    return out


def rewrite_datasource_identity(ds: str, user: str, *, password: str = "",
                                authcfg: str = "", sslmode: str = "") -> str:
    """Identité d'une datasource postgres : ``user``/``password``/``authcfg``
    existants retirés puis remplacés (et ``sslmode`` quand il est fourni ;
    sinon celui de la datasource est conservé). Idempotent."""
    tokens = [f"user={_ds_quote(user)}"] if user else []
    if password:
        tokens.append(f"password={_ds_quote(password)}")
    if sslmode:
        tokens.append(f"sslmode={sslmode}")
    if authcfg:
        tokens.append(f"authcfg={authcfg}")
    drop = _IDENTITY_KEYS | ({"sslmode"} if sslmode else set())
    return _rewrite_datasource(ds, drop, tokens)


def rewrite_datasource_nominal(ds: str, login: str, authcfg_id: str) -> str:
    """A QGIS postgres datasource string carrying the nominative identity:
    ``user='<login>' sslmode=verify-full authcfg=<id>`` and never a
    password. Every other token (table, key, srid, geometry, sql filter) is
    kept. Idempotent."""
    return rewrite_datasource_identity(ds, login, authcfg=authcfg_id, sslmode="verify-full")


def force_datasource_sslmode(ds: str, sslmode: str) -> str:
    """*ds* avec ``sslmode=<sslmode>``, tout le reste inchangé."""
    return _rewrite_datasource(ds, {"sslmode"}, [f"sslmode={sslmode}"])


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
