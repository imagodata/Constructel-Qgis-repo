"""Registre des projets metier (schema Farois `projet`) et capacites de la
base pour le Bridge 2.1, sans Qt ni QGIS.

- Capacites : une seule requete sur pg_catalog (lisible par tous, jamais
  d'erreur de droit) dit quelles tables du schema `projet` sont lisibles et
  quelles fonctions du lot (b) sont executables par la session. Elles pilotent
  l'affichage : une capacite absente masque la fonctionnalite, sans erreur.
- Registre : projets metier actifs ayant au moins une couche declaree, lus
  sous RLS ; `operateur_code` par `to_jsonb(p)` (colonne absente d'une base
  du lot (a) anterieure : NULL sans erreur). Le Bridge ne lit ni
  `lecture_qfield` ni les comptes partages.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

PROJET_SCHEMA = "projet"

_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


@dataclass(frozen=True)
class ProjetLayer:
    table: str
    label: str
    layer_group: Optional[str]
    style_name: str
    geom_column: Optional[str]
    sort_order: int


@dataclass(frozen=True)
class ProjetInfo:
    id: str
    code: str
    label: str
    operateur_code: Optional[str]
    layers: tuple


@dataclass(frozen=True)
class ProjetCapabilities:
    registry: bool = False
    qgis_table: bool = False
    visible: bool = False
    save: bool = False
    delete: bool = False
    share: bool = False
    share_project: bool = False

    @property
    def qgis_projects(self) -> bool:
        return self.qgis_table and self.visible


NO_CAPABILITIES = ProjetCapabilities()

CAPABILITY_FUNCTIONS = (
    "fn_qgis_projects_visible",
    "fn_qgis_project_save",
    "fn_qgis_project_delete",
    "fn_qgis_project_share",
    "fn_qgis_project_unshare",
    "fn_qgis_project_set_share_project",
    "fn_qgis_project_eligible_users",
    "fn_qgis_project_shares_list",
)

_REGISTRY_TABLES = ("projets", "projet_couches", "qgis_projects")

CAPABILITIES_QUERY = (
    "SELECT 'r' AS kind, c.relname::text AS name, "
    "(pg_catalog.has_schema_privilege(n.oid, 'USAGE') "
    "AND pg_catalog.has_table_privilege(c.oid, 'SELECT')) AS allowed "
    "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'projet' AND c.relkind IN ('r', 'p', 'v') "
    "AND c.relname IN ('projets', 'projet_couches', 'qgis_projects') "
    "UNION ALL "
    "SELECT 'f', p.proname::text, "
    "bool_or(pg_catalog.has_schema_privilege(n.oid, 'USAGE') "
    "AND pg_catalog.has_function_privilege(p.oid, 'EXECUTE')) "
    "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
    "WHERE n.nspname = 'projet' AND p.proname = ANY(%s) "
    "GROUP BY p.proname"
)

PROJETS_QUERY = (
    "SELECT p.id::text, p.code, p.label, to_jsonb(p) ->> 'operateur_code', "
    "c.table_name, c.label, c.layer_group, c.style_name, c.geom_column, c.sort_order "
    "FROM projet.projets p JOIN projet.projet_couches c ON c.projet_id = p.id "
    "WHERE p.active ORDER BY p.code, c.sort_order, c.label"
)


def sort_key(text) -> str:
    """Cle de tri insensible a la casse et aux accents."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def is_identifier(name) -> bool:
    return isinstance(name, str) and _IDENTIFIER_RE.fullmatch(name) is not None


def parse_capabilities(rows: Iterable[tuple]) -> ProjetCapabilities:
    tables = set()
    functions = set()
    for row in rows or ():
        try:
            kind, name, allowed = row[0], row[1], row[2]
        except (TypeError, IndexError):
            continue
        if not allowed:
            continue
        if kind == "r":
            tables.add(name)
        elif kind == "f":
            functions.add(name)
    qgis_table = "qgis_projects" in tables
    visible = "fn_qgis_projects_visible" in functions
    usable = qgis_table and visible
    return ProjetCapabilities(
        registry="projets" in tables and "projet_couches" in tables,
        qgis_table=qgis_table,
        visible=visible,
        save=usable and "fn_qgis_project_save" in functions,
        delete=usable and "fn_qgis_project_delete" in functions,
        share=usable and all(f in functions for f in (
            "fn_qgis_project_share", "fn_qgis_project_unshare",
            "fn_qgis_project_eligible_users", "fn_qgis_project_shares_list")),
        share_project=usable and "fn_qgis_project_set_share_project" in functions,
    )


def parse_projet_rows(rows: Iterable[tuple]) -> Tuple[ProjetInfo, ...]:
    """Lignes de PROJETS_QUERY -> projets metier (ordre de la requete).

    Une couche dont la table ou la colonne de geometrie n'est pas un
    identifiant simple est ecartee ; un projet sans couche restante aussi."""
    heads: Dict[str, Tuple[str, str, str, Optional[str]]] = {}
    layers: Dict[str, List[ProjetLayer]] = {}
    order: List[str] = []
    for row in rows or ():
        try:
            (pid, code, label, operateur, table, layer_label, group, style, geom, sort_order) = row[:10]
        except (TypeError, ValueError):
            continue
        if not code:
            continue
        key = str(pid)
        if key not in heads:
            heads[key] = (key, str(code), str(label or code), operateur or None)
            layers[key] = []
            order.append(key)
        if not is_identifier(table):
            continue
        if geom is not None and not is_identifier(geom):
            continue
        try:
            rank = int(sort_order or 0)
        except (TypeError, ValueError):
            rank = 0
        layers[key].append(ProjetLayer(
            table=table,
            label=str(layer_label or table),
            layer_group=group or None,
            style_name=style or "default",
            geom_column=geom or None,
            sort_order=rank,
        ))
    result = []
    for key in order:
        kept = sorted(layers[key], key=lambda l: (l.sort_order, sort_key(l.label)))
        if not kept:
            continue
        pid, code, label, operateur = heads[key]
        result.append(ProjetInfo(pid, code, label, operateur, tuple(kept)))
    return tuple(result)


def group_projets(projets: Sequence[ProjetInfo], usable_codes: Sequence[str],
                  operator_labels: Mapping[str, str]) -> List[Tuple[Optional[str], tuple]]:
    """(operateur_code ou None, projets tries par libelle) ; operateurs
    utilisables d'abord dans leur ordre, puis les autres par libelle, puis
    les projets sans operateur."""
    by_op: Dict[Optional[str], List[ProjetInfo]] = {}
    for projet in projets:
        by_op.setdefault(projet.operateur_code or None, []).append(projet)
    usable = [c for c in usable_codes if c in by_op]
    others = sorted((c for c in by_op if c is not None and c not in usable),
                    key=lambda c: (sort_key(operator_labels.get(c, c)), c))
    ordered: List[Optional[str]] = list(dict.fromkeys(usable)) + others
    if None in by_op:
        ordered.append(None)
    return [(code, tuple(sorted(by_op[code], key=lambda p: (sort_key(p.label), p.code)))) for code in ordered]
