"""Projets QGIS enregistres dans `projet.qgis_projects` (Bridge 2.1) :
sections de la page, regles de nom, cible d'un enregistrement, metadata et
plan de partage. Sans Qt ni QGIS.

Contrat Farois (lot b, mig 583) : nom unique globalement, 1 a 200 caracteres
sans caractere de controle ni espace en tete ou en fin ; logins de partage
`^[a-z0-9._-]{1,63}$`, 1 a 20 par appel ; autocompletion a partir de 3
caracteres (prefixe de 50 au plus, 50 resultats au plus cote serveur).
"""
from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

NAME_MAX = 200
ELIGIBLE_MIN_PREFIX = 3
ELIGIBLE_MAX_PREFIX = 50
ELIGIBLE_LIMIT = 20
ELIGIBLE_MAX_LIMIT = 50
MAX_SHARE_LOGINS = 20
LOGIN_RE = re.compile(r"^[a-z0-9._-]{1,63}$")

SECTION_MINE = "mine"
SECTION_SHARED = "shared"
SECTION_PUBLISHED = "published"

# Cles posees par le serveur : jamais renvoyees.
_SERVER_KEYS = ("last_modified_time", "last_modified_user")


def _sort_key(text) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


@dataclass(frozen=True)
class QgisProjectRow:
    name: str
    owner: Optional[str]
    projet_id: Optional[str]
    projet_code: Optional[str]
    projet_label: Optional[str]
    share_project: bool
    published: bool
    owner_role: Optional[str]
    version: int
    updated_at: Optional[str]
    updated_by: Optional[str]
    is_owner: bool
    can_edit: bool
    share_count: Optional[int]
    description: Optional[str]


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    return str(value)


def _int_or_none(value) -> Optional[int]:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def row_from_record(record: Sequence) -> QgisProjectRow:
    """Ligne de `fn_qgis_projects_visible()` (15 colonnes) -> QgisProjectRow."""
    (name, owner, projet_id, projet_code, projet_label, share_project, published, owner_role,
     version, updated_at, updated_by, is_owner, can_edit, share_count, description) = tuple(record)[:15]
    return QgisProjectRow(
        name=str(name),
        owner=owner,
        projet_id=None if projet_id is None else str(projet_id),
        projet_code=projet_code,
        projet_label=projet_label,
        share_project=bool(share_project),
        published=bool(published),
        owner_role=owner_role,
        version=_int_or_none(version) or 0,
        updated_at=_iso(updated_at),
        updated_by=updated_by,
        is_owner=bool(is_owner),
        can_edit=bool(can_edit),
        share_count=_int_or_none(share_count),
        description=description,
    )


def section_of(row: QgisProjectRow) -> str:
    """Une seule section par projet : Mes projets > Publies > Partages."""
    if row.is_owner:
        return SECTION_MINE
    if row.published:
        return SECTION_PUBLISHED
    return SECTION_SHARED


@dataclass(frozen=True)
class ProjectSections:
    mine: tuple
    shared: tuple
    published: tuple


def build_sections(rows: Sequence[QgisProjectRow],
                   operator_of_projet: Mapping[str, Optional[str]]) -> ProjectSections:
    ordered = sorted(rows, key=lambda r: (_sort_key(r.name), r.name))
    mine = tuple(r for r in ordered if section_of(r) == SECTION_MINE)
    shared = tuple(r for r in ordered if section_of(r) == SECTION_SHARED)
    groups: Dict[Tuple[Optional[str], Optional[str]], List[QgisProjectRow]] = {}
    for r in ordered:
        if section_of(r) != SECTION_PUBLISHED:
            continue
        op = operator_of_projet.get(r.projet_code) if r.projet_code else None
        groups.setdefault((r.projet_code, op), []).append(r)
    keys = sorted(groups, key=lambda k: (k[0] is None, k[0] or "", k[1] is None, k[1] or ""))
    published = tuple((code, op, tuple(groups[(code, op)])) for code, op in keys)
    return ProjectSections(mine, shared, published)


def name_error(name: str) -> Optional[str]:
    """None si le nom est admis, sinon "empty" | "too_long" | "control" | "spaces"."""
    if not name:
        return "empty"
    if len(name) > NAME_MAX:
        return "too_long"
    if any(unicodedata.category(c) == "Cc" for c in name):
        return "control"
    if name != name.strip(" "):
        return "spaces"
    return None


def suggest_name(name: str, login: str) -> str:
    """`<nom> (<login>)`, tronque pour tenir en NAME_MAX ; inchange s'il porte deja le suffixe."""
    suffix = f" ({login})"
    name = (name or "").strip()
    if name.endswith(suffix) and len(name) <= NAME_MAX:
        return name
    base = name[:max(0, NAME_MAX - len(suffix))].rstrip(" ")
    if not base:
        return f"({login})"[:NAME_MAX]
    return base + suffix


@dataclass(frozen=True)
class OpenedQgisProject:
    name: str
    version: int
    projet_id: Optional[str]
    projet_code: Optional[str]
    is_owner: bool
    can_edit: bool
    metadata: Mapping = field(default_factory=dict)


def save_target(name: str, opened: Optional[OpenedQgisProject]) -> Tuple[Optional[int], Optional[str]]:
    """(expected_version, projet_id verrouille) : mise a jour seulement si le
    nom est celui du projet QGIS ouvert et qu'on peut le modifier."""
    if opened is not None and opened.name == name and (opened.can_edit or opened.is_owner):
        return opened.version, opened.projet_id
    return None, None


def build_metadata(description: str, saved_by: Optional[str], saved_at: Optional[str],
                   source_file: str, previous: Optional[Mapping]) -> dict:
    meta = {k: v for k, v in dict(previous or {}).items() if k not in _SERVER_KEYS}
    meta["description"] = description or ""
    for key, value in (("saved_by", saved_by), ("saved_at", saved_at), ("source_file", source_file)):
        if value:
            meta[key] = value
        else:
            meta.pop(key, None)
    return meta


@dataclass(frozen=True)
class ShareRow:
    username: str
    display_name: Optional[str]
    unit: Optional[str]
    can_edit: bool
    operant: bool


@dataclass(frozen=True)
class EligibleUser:
    username: str
    display_name: Optional[str]
    unit: Optional[str]

    def caption(self) -> str:
        text = f"{self.display_name} ({self.username})" if self.display_name else self.username
        return f"{text} — {self.unit}" if self.unit else text


@dataclass(frozen=True)
class SharePlan:
    share_project: Optional[bool]
    unshare: tuple
    edit: tuple
    open: tuple

    def is_empty(self) -> bool:
        return self.share_project is None and not (self.unshare or self.edit or self.open)


def share_plan(current: Sequence[ShareRow], wanted: Mapping[str, bool], removed: Iterable[str],
               share_project_before: bool, share_project_after: bool) -> SharePlan:
    """Appels a faire pour passer de *current* a l'etat voulu (logins tries)."""
    rights = {r.username: bool(r.can_edit) for r in current}
    gone = {login for login in removed if login in rights}
    edit, open_ = [], []
    for login, can_edit in wanted.items():
        if login in gone:
            continue
        if login in rights and rights[login] == bool(can_edit):
            continue
        (edit if can_edit else open_).append(login)
    sp = None if bool(share_project_before) == bool(share_project_after) else bool(share_project_after)
    return SharePlan(sp, tuple(sorted(gone)), tuple(sorted(edit)), tuple(sorted(open_)))


def chunks(items: Sequence[str], size: int = MAX_SHARE_LOGINS) -> List[tuple]:
    items = list(items)
    return [tuple(items[i:i + size]) for i in range(0, len(items), size)]
