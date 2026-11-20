"""Appels SQL du schema Farois `projet` pour le Bridge 2.1, sans Qt ni QGIS.

Tout passe par la connexion psycopg2 de la session (`self._conn`, autocommit,
login de la personne) : lectures sous RLS, ecritures par les fonctions
SECURITY DEFINER du lot (b). `p_as_user` n'est JAMAIS passe. Chaque fonction
ouvre et ferme son curseur ; une lecture en echec rend une valeur neutre
(capacites absentes, liste vide ou None), jamais une exception.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from .bridge_projets import (
    CAPABILITIES_QUERY,
    CAPABILITY_FUNCTIONS,
    NO_CAPABILITIES,
    PROJETS_QUERY,
    ProjetCapabilities,
    parse_capabilities,
    parse_projet_rows,
)
from .bridge_qgis_projects import QgisProjectRow, ShareRow, row_from_record

_LOG = logging.getLogger(__name__)

VISIBLE_QUERY = "SELECT * FROM projet.fn_qgis_projects_visible()"
OPEN_QUERY = "SELECT content, metadata, version, projet_id::text FROM projet.qgis_projects WHERE name = %s"
VERSION_QUERY = "SELECT version FROM projet.qgis_projects WHERE name = %s"
SHARES_LIST_QUERY = "SELECT * FROM projet.fn_qgis_project_shares_list(%s::text)"


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


def read_capabilities(conn) -> ProjetCapabilities:
    try:
        rows = _run(conn, CAPABILITIES_QUERY, (list(CAPABILITY_FUNCTIONS),))
    except Exception as exc:  # noqa: BLE001 - capacites absentes, sans boite
        _LOG.info("Capacites du schema projet illisibles : %s", exc)
        return NO_CAPABILITIES
    return parse_capabilities(rows)


def read_projets(conn) -> tuple:
    try:
        rows = _run(conn, PROJETS_QUERY)
    except Exception as exc:  # noqa: BLE001
        _LOG.info("Registre des projets metier illisible : %s", exc)
        return ()
    return parse_projet_rows(rows)


def list_visible(conn) -> Optional[List[QgisProjectRow]]:
    try:
        rows = _run(conn, VISIBLE_QUERY)
        return [row_from_record(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("Liste des projets QGIS illisible : %s", exc)
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


def current_version(conn, name: str) -> Optional[int]:
    try:
        row = _run(conn, VERSION_QUERY, (name,), fetch="one")
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("Version du projet QGIS %s illisible : %s", name, exc)
        return None
    if not row or row[0] is None:
        return None
    return int(row[0])


def shares_list(conn, name: str) -> Optional[List[ShareRow]]:
    try:
        rows = _run(conn, SHARES_LIST_QUERY, (name,))
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("Partages du projet QGIS %s illisibles : %s", name, exc)
        return None
    return [ShareRow(str(r[0]), r[1], r[2], bool(r[3]), bool(r[4])) for r in rows]
