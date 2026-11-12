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
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit, urlunsplit
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


def normalize_login(text: str) -> str:
    """Login saisi par la personne -> login PostgreSQL (revue 29/10, I5) :
    ``DOMAINE\\login`` et ``login@suffixe`` (constructelbe.corp ou autre)
    sont ramenés à ``login``, en minuscules. "" si le résultat ne peut pas
    être un login (le dialogue l'affiche au lieu de basculer en partagé)."""
    login = (text or "").strip()
    if "\\" in login:
        login = login.rsplit("\\", 1)[1]
    if "@" in login:
        login = login.split("@", 1)[0]
    return resolve_pg_login(login)


# --- probe failure classification ---------------------------------------------
#
# Revue 29/10 (I2) : seul le REFUS DU MOT DE PASSE déclenche la ressaisie ;
# tout autre échec pendant la connexion (login non actif, pg_hba, délai,
# TLS, trop de connexions, motif inconnu) mène au repli partagé quand il
# existe. Messages du serveur en anglais ou en français (lc_messages),
# relevés dans src/backend/po/fr.po (PostgreSQL 17).

AUTH_REFUSED = "auth_refused"      # bind refused: the password is wrong (re-prompt once)
LOGIN_DISABLED = "login_disabled"  # role NOLOGIN / unknown / no pg_hba line: not activated

_LOGIN_DISABLED_PATTERNS = (
    re.compile(r"is not permitted to log in"),
    re.compile(r"n'est pas autorisé à se connecter"),
    re.compile(r'role "[^"]*" does not exist'),
    re.compile(r"le rôle .{0,80}? n'existe pas"),
    re.compile(r"no pg_hba\.conf entry"),
    re.compile(r"aucune entrée dans pg_hba\.conf"),
    re.compile(r"pg_hba\.conf rejects connection"),
    re.compile(r"pg_hba\.conf rejette la connexion"),
)
_AUTH_REFUSED_PATTERNS = (
    # password = méthodes password/md5/scram ; LDAP = lignes ldap (bind AD).
    re.compile(r"\b(?:password|LDAP) authentication failed"),
    re.compile(r"authentification (?:par mot de passe|LDAP) échouée"),
)


def classify_auth_failure(exc) -> str | None:
    """AUTH_REFUSED (mot de passe refusé : ressaisie possible),
    LOGIN_DISABLED (login non actif ou non admis : pas un problème de mot de
    passe) ou None (tout le reste : délai, TLS, réseau, motif inconnu).
    L'appelant replie dans tous les cas où il ne ressaisit pas. Ne lève
    jamais.
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
    if pgcode == "28P01":  # invalid_password
        return AUTH_REFUSED
    if isinstance(pgcode, str) and pgcode.startswith("28"):
        return LOGIN_DISABLED
    return None


# --- decision after a failed probe --------------------------------------------

AUTH_MODE_NOMINAL = "nominal"
AUTH_MODE_SHARED = "shared"

NOMINAL_SETTINGS_KEYS = {
    "auth_mode": "constructel_bridge/auth_mode",
    "pg_login": "constructel_bridge/pg_login",
}

# Spec §5.7.4 / AC8 : jamais plus de 2 binds refusés par démarrage.
MAX_REFUSED_BINDS = 2


def should_reprompt(kind, memorized_mode: str, refused_binds: int, explicit: bool = False) -> bool:
    """Redemander le mot de passe (une seule fois) après *refused_binds*
    refus ? Seulement pour un mot de passe refusé, sous le plafond de binds
    refusés, et jamais d'office au démarrage d'un poste déjà en repli (une
    action explicite de la personne -- Connecter, Réessayer -- si)."""
    if kind != AUTH_REFUSED or refused_binds >= MAX_REFUSED_BINDS:
        return False
    return explicit or memorized_mode != AUTH_MODE_SHARED


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


def strip_datasource_authcfg(ds: str) -> str:
    """*ds* sans ``authcfg=`` (revue 2, I-7 : jamais nos configs vers un
    hôte tiers), tout le reste inchangé."""
    return _rewrite_datasource(ds, {"authcfg"}, [])


# --- URI de projet enregistré dans PostgreSQL (revue 2, I-8) -------------------
#
# QgsPostgresProjectStorage::encodeUri (3.28 -> master) :
# ``postgresql://<host>:<port>?authcfg=<id>&sslmode=<mode>&dbname=…&schema=…
# &project=…``. La connexion de stockage (lecture, enregistrement) en est
# déduite sans passer par QgsPathResolver : le préprocesseur ne la voit pas.


def secure_project_storage_uri(uri: str, hosts, authcfg_ids, sslmode: str = "verify-full") -> str:
    """URI ``postgresql://`` d'un projet en base, rattachée à une de nos
    configs fixes : ``sslmode`` forcé sur nos hôtes, ``authcfg`` retiré
    sur un hôte tiers. Les autres éléments de la requête sont conservés
    tels quels (encodage compris) ; toute autre URI est rendue inchangée."""
    if not (uri or "").startswith("postgresql://"):
        return uri
    parts = urlsplit(uri)
    items = parts.query.split("&") if parts.query else []

    def _key(item):
        return unquote(item.partition("=")[0])

    values = {}
    for item in items:
        values.setdefault(_key(item), unquote(item.partition("=")[2]))
    if values.get("authcfg") not in authcfg_ids:
        return uri
    if (parts.hostname or "") not in {h.lower() for h in hosts if h}:
        items = [i for i in items if _key(i) != "authcfg"]
    elif values.get("sslmode") != sslmode:
        items = [i for i in items if _key(i) != "sslmode"] + [f"sslmode={sslmode}"]
    else:
        return uri
    return urlunsplit(parts._replace(query="&".join(items)))


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
    # Mig 536 : NULL côté ECRITURE (current_gis_*_ids(true)) = tout en
    # écriture sur cette dimension, distinct d'un tableau vide (rien coché).
    write_bypass: bool = False


# current_gis_*_ids() renvoient du uuid[] : psycopg2 n'a pas de typecaster
# pour uuid[] (OID 2951) et rend alors le littéral brut « {a,b} », que l'on
# itérait caractère par caractère (1.8.0 -> 1.8.3 : périmètre illisible,
# « {} » pris pour un périmètre non vide). Le cast ::text[] est parsé
# nativement en liste ; NULL reste NULL (bypass), distinct de « {} ».
SCOPE_QUERY = (
    "SELECT public.current_gis_role(), "
    "public.current_gis_has_capability('network.read'), "
    "public.current_gis_has_capability('network.write'), "
    "public.current_gis_mro_ids(false)::text[], public.current_gis_mro_ids(true)::text[], "
    "public.current_gis_pop_ids(false)::text[], public.current_gis_pop_ids(true)::text[]"
)


def _pg_array_items(text: str) -> list[str]:
    """Éléments d'un littéral de tableau PostgreSQL à une dimension
    (``{}``, ``{a,b}``, ``{"a b",c}``), tel que psycopg2 le rend pour un
    type de tableau sans typecaster. Guillemets retirés, ``\\`` déséchappé,
    éléments NULL ignorés. Une chaîne qui n'est pas un littéral de tableau
    est un identifiant unique (jamais découpée en caractères)."""
    body = text.strip()
    if not (body.startswith("{") and body.endswith("}")):
        return [body] if body else []
    body = body[1:-1]
    items: list[str] = []
    if not body.strip():
        return items
    buf: list[str] = []
    in_quotes = was_quoted = False
    i = 0
    while i <= len(body):
        ch = body[i] if i < len(body) else ","  # virgule finale implicite
        if ch == "\\" and i + 1 < len(body):
            i += 1
            buf.append(body[i])
        elif in_quotes:
            if ch == '"':
                in_quotes = False
            else:
                buf.append(ch)
        elif ch == '"':
            if not "".join(buf).strip():
                buf = []
            in_quotes = was_quoted = True
        elif ch == ",":
            item = "".join(buf)
            if not was_quoted:
                item = item.strip()
            # Un identifiant vide n'a pas de sens : il ne doit pas rendre
            # un périmètre « non vide ».
            if item and (was_quoted or item.upper() != "NULL"):
                items.append(item)
            buf, was_quoted = [], False
        elif not (was_quoted and ch.isspace()):
            buf.append(ch)
        i += 1
    return items


def _ids(value) -> list:
    """Identifiants d'un tableau lu par psycopg2 : liste/tuple (cas normal,
    ``text[]``) ou littéral brut ``"{a,b}"`` (tableau sans typecaster).
    NULL -> [] : l'appelant teste ``is None`` sur la valeur brute AVANT
    (NULL = tout, distinct d'un tableau vide)."""
    if value is None:
        return []
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", "replace")
    if isinstance(value, str):
        return _pg_array_items(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(v) for v in value if v is not None and str(v) != ""]
    return [str(value)]


def parse_session_scope(row: Sequence) -> SessionScope:
    """Build a SessionScope from one row of SCOPE_QUERY. NULL id arrays mean
    "no restriction" (bypass_scopes of current_verified_gis_user). The NULL
    tests below are made on the RAW values, before _ids()."""
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
        write_bypass=mro_write is None or pop_write is None,
    )


def scope_kind(scope: SessionScope) -> str:
    """"all" (bypass), "scoped" (at least one MRO/POP) or "none" (no
    perimeter: network layers come back empty, by design)."""
    if scope.bypass:
        return "all"
    if scope.mro_ids or scope.pop_ids:
        return "scoped"
    return "none"


def write_scope_kind(scope: SessionScope) -> str:
    """Perimetre d'ECRITURE (migration Farois 536) : "all" (network.write et
    tableau d'ecriture NULL = tout, ADMIN/MANAGER), "scoped" (network.write
    et au moins un MRO ou une POP coche « ecriture », can_write) ou "none"
    (role sans network.write, ou aucun MRO/POP coche : toute ecriture
    reseau sera refusee). Decide sur les tableaux d'ECRITURE, jamais sur
    ceux de lecture (bypass)."""
    if not scope.network_write:
        return "none"
    if scope.write_bypass:
        return "all"
    if scope.mro_write_ids or scope.pop_write_ids:
        return "scoped"
    return "none"


def scope_labels(ids: Sequence[str], names: dict) -> list[str]:
    """Human labels for scope ids: the name when known, else the first
    block of the UUID. Sorted (case- and accent-insensitive) for a stable
    display."""
    labels = (str(names.get(i) or str(i).split("-")[0]) for i in ids)
    return sorted(labels, key=lambda label: (_sort_key(label), label))


def _sort_key(label: str) -> str:
    decomposed = unicodedata.normalize("NFKD", label.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


# Barre de messages QGIS : le nombre de zones et les premiers noms ; la
# liste complète va dans le journal (max_names=None).
SCOPE_NAMES_SHOWN = 3


def summarize_labels(labels: Sequence[str], max_names: int | None = SCOPE_NAMES_SHOWN) -> str:
    """``"A, B, C… (+7)"`` : les *max_names* premiers libellés puis le
    nombre de libellés non affichés ; tous les libellés quand ils tiennent
    ou quand *max_names* vaut None."""
    labels = list(labels)
    if max_names is None or len(labels) <= max_names:
        return ", ".join(labels)
    return f"{', '.join(labels[:max_names])}… (+{len(labels) - max_names})"


def write_scope_equals_read(scope: SessionScope) -> bool:
    """True quand les MRO/POP cochés « écriture » sont exactement ceux du
    périmètre de lecture (message : « écriture sur tout le périmètre »)."""
    return (set(scope.mro_write_ids) == set(scope.mro_ids)
            and set(scope.pop_write_ids) == set(scope.pop_ids))


def should_lock_layer(schema: str, scope: SessionScope | None) -> bool:
    """True when a layer of *schema* must be set read-only in QGIS: a
    nominative session without network.write, on the ``wyre`` schema only
    (plan D2 ; revue 29/10 I8 -- chantier.*, docs.* stay editable, spec
    D11 ; public/ref/osiris untouched). Shared mode (scope None): never."""
    if scope is None or scope.network_write:
        return False
    return schema == "wyre"


# Revue 29/10 (M7) : « hors périmètre » (RLS, trigger de périmètre) et
# « droit manquant » (GRANT) sont distingués quand le texte du serveur le
# permet (anglais ou français) ; un 42501 sans autre indice reste neutre.
SCOPE_REFUSAL_PERIMETER = "perimeter"
SCOPE_REFUSAL_RIGHT = "right"
SCOPE_REFUSAL_UNKNOWN = "unknown"

_PERIMETER_REFUSAL_RE = re.compile(
    r"row-level security|sécurité au niveau ligne|gis_scope|perimetre|périmètre",
    re.IGNORECASE,
)
_RIGHT_REFUSAL_RE = re.compile(r"permission denied|droit refusé", re.IGNORECASE)


def scope_refusal_kind(message: str) -> str | None:
    """SCOPE_REFUSAL_PERIMETER, SCOPE_REFUSAL_RIGHT, SCOPE_REFUSAL_UNKNOWN
    (42501 seul) ou None quand l'erreur de commit n'est pas un refus
    d'écriture pour raison de périmètre ou de droits."""
    text = message or ""
    if _PERIMETER_REFUSAL_RE.search(text):
        return SCOPE_REFUSAL_PERIMETER
    if _RIGHT_REFUSAL_RE.search(text):
        return SCOPE_REFUSAL_RIGHT
    if "42501" in text:
        return SCOPE_REFUSAL_UNKNOWN
    return None


def is_scope_write_refusal(message: str) -> bool:
    """True when a commit error message is the server refusing a write for
    scope/capability reasons (RLS policy, trg_enforce_gis_scope, 42501)."""
    return scope_refusal_kind(message) is not None
