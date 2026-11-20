"""Appels SQL du schema Farois `projet` pour le Bridge 2.1, sans Qt ni QGIS.

Tout passe par la connexion psycopg2 de la session (`self._conn`, autocommit,
login de la personne) : lectures sous RLS, ecritures par les fonctions
SECURITY DEFINER du lot (b). Le parametre de delegation (as_user) n est JAMAIS passe. Chaque fonction
ouvre et ferme son curseur ; une lecture en echec rend une valeur neutre
(capacites absentes, liste vide ou None), jamais une exception.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from .bridge_projets import (
    CAPABILITIES_QUERY,
    CAPABILITY_FUNCTIONS,
    NO_CAPABILITIES,
    PROJETS_QUERY,
    ProjetCapabilities,
    parse_capabilities,
    parse_projet_rows,
)
from .bridge_qgis_projects import (
    ELIGIBLE_LIMIT,
    ELIGIBLE_MAX_LIMIT,
    ELIGIBLE_MAX_PREFIX,
    ELIGIBLE_MIN_PREFIX,
    EligibleUser,
    QgisProjectRow,
    SharePlan,
    ShareRow,
    chunks,
    row_from_record,
)

_LOG = logging.getLogger(__name__)

VISIBLE_QUERY = "SELECT * FROM projet.fn_qgis_projects_visible()"
OPEN_QUERY = "SELECT content, metadata, version, projet_id::text FROM projet.qgis_projects WHERE name = %s"
VERSION_QUERY = "SELECT version FROM projet.qgis_projects WHERE name = %s"
SHARES_LIST_QUERY = "SELECT * FROM projet.fn_qgis_project_shares_list(%s::text)"


Log = Optional[Callable[[str], None]]


def _report(log: Log, message: str) -> None:
    """Journal Python et, si fourni, journal du plugin (QgsMessageLog)."""
    _LOG.warning(message)
    if log is not None:
        try:
            log(message)
        except Exception:  # noqa: BLE001 - le journal ne fait jamais echouer
            pass


def _run(conn, sql: str, params=None, fetch: str = "all"):
    """Execute *sql* sur un curseur ferme ensuite ; leve les erreurs."""
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
        return None
    finally:
        try:
            cur.close()
        except Exception:  # noqa: BLE001 - fermeture best effort
            pass


def read_capabilities(conn, log: Log = None) -> ProjetCapabilities:
    try:
        rows = _run(conn, CAPABILITIES_QUERY, (list(CAPABILITY_FUNCTIONS),))
    except Exception as exc:  # noqa: BLE001 - capacites absentes, sans boite
        _report(log, f"Capacites du schema projet indisponibles : {exc}")
        return NO_CAPABILITIES
    return parse_capabilities(rows)


def read_projets(conn, log: Log = None) -> tuple:
    try:
        rows = _run(conn, PROJETS_QUERY)
    except Exception as exc:  # noqa: BLE001
        _report(log, f"Registre des projets metier indisponible : {exc}")
        return ()
    return parse_projet_rows(rows)


def list_visible(conn, log: Log = None) -> Optional[List[QgisProjectRow]]:
    try:
        rows = _run(conn, VISIBLE_QUERY)
        return [row_from_record(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        _report(log, f"Liste des projets QGIS indisponible : {exc}")
        return None


@dataclass(frozen=True)
class OpenRow:
    content: bytes
    metadata: dict
    version: int
    projet_id: Optional[str]


def read_for_open(conn, name: str) -> Optional[OpenRow]:
    """Contenu d'un projet QGIS sous RLS ; None s'il est absent ou invisible.
    Les erreurs de lecture remontent a l'appelant (message d'ouverture)."""
    row = _run(conn, OPEN_QUERY, (name,), fetch="one")
    if not row:
        return None
    content, metadata, version, projet_id = row[0], row[1], row[2], row[3]
    if isinstance(content, memoryview):
        content = content.tobytes()
    elif content is not None and not isinstance(content, bytes):
        content = bytes(content)
    return OpenRow(
        content=content or b"",
        metadata=dict(metadata) if isinstance(metadata, dict) else {},
        version=int(version or 0),
        projet_id=None if projet_id is None else str(projet_id),
    )


def current_version(conn, name: str, log: Log = None) -> Optional[int]:
    try:
        row = _run(conn, VERSION_QUERY, (name,), fetch="one")
    except Exception as exc:  # noqa: BLE001
        _report(log, f"Version du projet QGIS {name} indisponible : {exc}")
        return None
    if not row or row[0] is None:
        return None
    return int(row[0])


def shares_list(conn, name: str, log: Log = None) -> Optional[List[ShareRow]]:
    try:
        rows = _run(conn, SHARES_LIST_QUERY, (name,))
    except Exception as exc:  # noqa: BLE001
        _report(log, f"Partages du projet QGIS {name} indisponibles : {exc}")
        return None
    return [ShareRow(str(r[0]), r[1], r[2], bool(r[3]), bool(r[4])) for r in rows]


# ---------------------------------------------------------------------------
# Ecritures et classement des erreurs (Task 6)
# ---------------------------------------------------------------------------
STATUS_OK = "ok"
STATUS_CONFLICT = "conflict"
STATUS_NAME_TAKEN = "name_taken"
STATUS_GONE = "gone"
STATUS_NOMINATIVE = "nominative"
STATUS_PROJET_DENIED = "projet_denied"
STATUS_DENIED = "denied"
STATUS_INVALID = "invalid"
STATUS_INELIGIBLE = "ineligible"
STATUS_MISSING = "missing"
STATUS_ERROR = "error"

# HINT codes et stables du contrat (lot b, Q4) : le plugin teste le HINT,
# jamais le texte du message. Un HINT inconnu = erreur generique (message).
# QGISP_DELEGATION_DENIED (delegation as_user renseignee) ne doit jamais arriver : le
# Bridge ne le passe pas ; il est traite comme une erreur generique.
HINT_STATUS = {
    "QGISP_VERSION_CONFLICT": STATUS_CONFLICT,
    "QGISP_NAME_TAKEN": STATUS_NAME_TAKEN,
    "QGISP_NOT_FOUND": STATUS_GONE,
    "QGISP_NOT_NOMINATIVE": STATUS_NOMINATIVE,
    "QGISP_PROJET_FORBIDDEN": STATUS_PROJET_DENIED,
    "QGISP_NOT_OWNER": STATUS_DENIED,
    "QGISP_ADMIN_ONLY": STATUS_DENIED,
    "QGISP_NOT_ELIGIBLE": STATUS_INELIGIBLE,
}

SAVE_QUERY = "SELECT projet.fn_qgis_project_save(%s::text, %s::bytea, %s::jsonb, %s::integer, %s::uuid)"
DELETE_QUERY = "SELECT projet.fn_qgis_project_delete(%s::text)"
SET_SHARE_PROJECT_QUERY = "SELECT projet.fn_qgis_project_set_share_project(%s::text, %s::boolean)"
UNSHARE_QUERY = "SELECT projet.fn_qgis_project_unshare(%s::text, %s::text[])"
SHARE_QUERY = "SELECT projet.fn_qgis_project_share(%s::text, %s::text[], %s::boolean)"
ELIGIBLE_QUERY = ("SELECT * FROM projet.fn_qgis_project_eligible_users(%s::text, %s::text, "
                  + str(min(ELIGIBLE_LIMIT, ELIGIBLE_MAX_LIMIT)) + ", p_exclude => %s::text[])")

_FIRST_INT_RE = re.compile(r"\d+")
_COUNT_RE = re.compile(r"(\d+)\s*personne")


@dataclass(frozen=True)
class StoreOutcome:
    status: str
    value: object = None
    message: str = ""
    detail: str = ""
    count: Optional[int] = None


def _diag(exc: BaseException, *names: str) -> str:
    diag = getattr(exc, "diag", None)
    for name in names:
        value = getattr(diag, name, None) if diag is not None else None
        if value:
            return str(value)
    return ""


def classify_error(exc: BaseException) -> StoreOutcome:
    code = getattr(exc, "pgcode", None)
    hint = _diag(exc, "message_hint", "hint").strip()
    message = _diag(exc, "message_primary")
    if not message:
        text = str(exc).strip()
        message = text.splitlines()[0] if text else ""
    detail = _diag(exc, "message_detail")
    status = HINT_STATUS.get(hint)
    if status is None:
        if code == "FP409":
            status = STATUS_CONFLICT
        elif code == "22023":
            status = STATUS_INVALID
        else:
            status = STATUS_ERROR
    count = None
    if status == STATUS_INELIGIBLE:
        # « partage du projet QGIS <nom> refuse : <n> personne(s)… » : le nom
        # (qui peut contenir des chiffres) precede ; on prend le DERNIER
        # nombre suivi de « personne », a defaut le dernier nombre.
        text = message or ""
        found = _COUNT_RE.findall(text) or _FIRST_INT_RE.findall(text)
        count = int(found[-1]) if found else None
    return StoreOutcome(status, message=message or "", detail=detail, count=count)


def _binary(content: bytes):
    try:
        import psycopg2  # noqa: PLC0415 - absent des tests sans base
        return psycopg2.Binary(content)
    except Exception:  # noqa: BLE001
        return bytes(content)


def save(conn, name: str, content: bytes, metadata: dict, expected_version: Optional[int],
         projet_id: Optional[str], log: Log = None) -> StoreOutcome:
    params = (name, _binary(content), json.dumps(metadata or {}, ensure_ascii=False), expected_version, projet_id)
    try:
        row = _run(conn, SAVE_QUERY, params, fetch="one")
    except Exception as exc:  # noqa: BLE001
        outcome = classify_error(exc)
        _report(log, f"Enregistrement du projet QGIS {name} refuse ({outcome.status}) : "
                     f"{outcome.message} {outcome.detail}".rstrip())
        return outcome
    version = int(row[0]) if row and row[0] is not None else None
    return StoreOutcome(STATUS_OK, value=version)


def delete(conn, name: str, log: Log = None) -> StoreOutcome:
    try:
        row = _run(conn, DELETE_QUERY, (name,), fetch="one")
    except Exception as exc:  # noqa: BLE001
        outcome = classify_error(exc)
        _report(log, f"Suppression du projet QGIS {name} refusee ({outcome.status}) : {outcome.message}")
        return outcome
    return StoreOutcome(STATUS_OK if row and row[0] else STATUS_MISSING)


def eligible_users(conn, projet_code: Optional[str], prefix: str,
                   exclude: Sequence[str], log: Log = None) -> Optional[List[EligibleUser]]:
    """Personnes eligibles au partage ; [] sans requete sous 3 caracteres,
    None si la recherche echoue."""
    cleaned = (prefix or "").strip()
    if len(cleaned) < ELIGIBLE_MIN_PREFIX:
        return []
    cleaned = cleaned[:ELIGIBLE_MAX_PREFIX]
    try:
        rows = _run(conn, ELIGIBLE_QUERY, (projet_code, cleaned, [str(x) for x in exclude or ()]))
    except Exception as exc:  # noqa: BLE001
        _report(log, f"Recherche de personnes impossible : {exc}")
        return None
    return [EligibleUser(str(r[0]), r[1], r[2]) for r in rows]


def apply_share_plan(conn, name: str, plan: SharePlan, log: Log = None) -> StoreOutcome:
    """Partage avec le projet metier, retraits, puis partages « peut
    modifier » et « peut ouvrir », par paquets de 20 ; arret a la premiere
    erreur (value = nombre d'appels reussis)."""
    calls = []
    if plan.share_project is not None:
        calls.append((SET_SHARE_PROJECT_QUERY, (name, bool(plan.share_project))))
    calls += [(UNSHARE_QUERY, (name, list(batch))) for batch in chunks(plan.unshare)]
    calls += [(SHARE_QUERY, (name, list(batch), True)) for batch in chunks(plan.edit)]
    calls += [(SHARE_QUERY, (name, list(batch), False)) for batch in chunks(plan.open)]
    done = 0
    for sql, params in calls:
        try:
            _run(conn, sql, params, fetch="one")
        except Exception as exc:  # noqa: BLE001
            outcome = classify_error(exc)
            _report(log, f"Partage du projet QGIS {name} interrompu apres {done} appel(s) "
                         f"({outcome.status}) : {outcome.message}")
            return StoreOutcome(outcome.status, value=done, message=outcome.message,
                                detail=outcome.detail, count=outcome.count)
        done += 1
    return StoreOutcome(STATUS_OK, value=done)
