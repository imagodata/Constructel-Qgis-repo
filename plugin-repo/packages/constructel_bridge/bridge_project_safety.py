"""Code embarque d'un projet QGIS : controle a l'enregistrement et
neutralisation a l'ouverture (Bridge 2.1), sans Qt ni QGIS.

Regles portees a l'identique de farois/qgis/project_store.py (scan_qgs,
_action_finding, inspect_archive, _parse_qgs) ; les constats sont des
`Finding` (type, couche, detail) et non des phrases : le texte affiche est
formate par l'interface (une cle de traduction par type, K11).

Familles controlees (Qgis::EmbeddedScriptType) : macros du projet, fonctions
d'expression Python, actions de couche qui executent du code, code
d'initialisation de formulaire ; plus les fichiers .py de l'archive et les
mots de passe en clair des sources de donnees.
"""
from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional

FINDING_MACROS = "macros"
FINDING_EXPRESSION_FUNCTIONS = "expression_functions"
FINDING_ACTION = "action"
FINDING_FORM_INIT = "form_init"
FINDING_PASSWORD = "password"
FINDING_PYTHON_FILE = "python_file"

# Qgis::AttributeActionType : 0 Generic, 1 GenericPython, 2 Mac, 3 Windows,
# 4 Unix, 5 OpenUrl, 6 SubmitUrlEncoded, 7 SubmitUrlMultipart. Seules les
# actions URL sont admises.
ALLOWED_ACTION_TYPES = frozenset({5, 6, 7})
MAX_CONTENT_BYTES = 256 * 1024 * 1024

# Qgis::AttributeFormPythonInitCodeSource : 0 NoSource, 1 File, 2 Dialog,
# 3 Environment.
_FORM_INIT_NO_SOURCE = {"", "0"}
_MAX_QGS_BYTES = 512 * 1024 * 1024
_PASSWORD_RE = re.compile(r"\bpassword\s*=\s*('(?:[^'\\]|\\.)+'|[^\s'][^\s]*)", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    kind: str
    layer: str = ""
    detail: str = ""


class ProjectFileError(ValueError):
    """Contenu illisible : pas une archive .qgz, XML invalide ou entite XML."""


@dataclass(frozen=True)
class ArchiveReport:
    qgs_name: str
    saved_at: Optional[str]
    saved_by: Optional[str]
    findings: tuple


def _parse_qgs(data, entry: str = "projet") -> ET.Element:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    # Aucune entite XML dans un .qgs : toute declaration est refusee en amont
    # (expansion d'entites) ; le DOCTYPE externe standard de QGIS est admis.
    if b"<!ENTITY" in raw:
        raise ProjectFileError(f"{entry} : declaration d'entite XML refusee")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ProjectFileError(f"{entry} : XML invalide ({exc})") from exc
    if root.tag != "qgis":
        raise ProjectFileError(f"{entry} : racine <{root.tag}> au lieu de <qgis>")
    return root


def _text(el: Optional[ET.Element]) -> str:
    return (el.text or "").strip() if el is not None else ""


def _layer_label(maplayer: ET.Element) -> str:
    return _text(maplayer.find("layername")) or _text(maplayer.find("id")) or "?"


def _macro_elements(root: ET.Element) -> List[ET.Element]:
    return root.findall("properties/Macros/pythonCode") + root.findall(".//projectMacros")


def _expression_elements(root: ET.Element) -> List[ET.Element]:
    return root.findall("properties/ExpressionFunctions/pythonCode")


def _action_refused(action: ET.Element) -> Optional[str]:
    """Detail de l'action si elle execute du code, sinon None."""
    if not (action.get("action") or "").strip():
        return None  # commande vide : rien a executer (meme regle que QGIS)
    raw = (action.get("type") or "").strip()
    name = action.get("name") or action.get("shortTitle") or "?"
    try:
        action_type = int(raw)
    except ValueError:
        return f"{name} (type={raw or '?'})"
    if action_type in ALLOWED_ACTION_TYPES:
        return None
    return f"{name} (type={action_type})"


def _form_init_refused(maplayer: ET.Element) -> Optional[str]:
    init_fn = _text(maplayer.find("editforminit"))
    source = _text(maplayer.find("editforminitcodesource"))
    init_code = _text(maplayer.find("editforminitcode"))
    init_file = _text(maplayer.find("editforminitfilepath"))
    if source not in _FORM_INIT_NO_SOURCE and (init_fn or init_code or init_file):
        return init_fn or "?"
    return None


def scan_qgs(root: ET.Element) -> List[Finding]:
    """Ce qui bloque l'enregistrement d'un document .qgs (liste vide = OK)."""
    findings: List[Finding] = []
    if any(_text(el) for el in _macro_elements(root)):
        findings.append(Finding(FINDING_MACROS))
    if any(_text(el) for el in _expression_elements(root)):
        findings.append(Finding(FINDING_EXPRESSION_FUNCTIONS))

    seen_actions = set()
    for maplayer in root.iter("maplayer"):
        label = _layer_label(maplayer)
        for action in maplayer.iter("actionsetting"):
            seen_actions.add(id(action))
            detail = _action_refused(action)
            if detail:
                findings.append(Finding(FINDING_ACTION, label, detail))
        init_fn = _form_init_refused(maplayer)
        if init_fn:
            findings.append(Finding(FINDING_FORM_INIT, label, init_fn))
        if _PASSWORD_RE.search(_text(maplayer.find("datasource"))):
            findings.append(Finding(FINDING_PASSWORD, label))

    for action in root.iter("actionsetting"):
        if id(action) not in seen_actions:
            detail = _action_refused(action)
            if detail:
                findings.append(Finding(FINDING_ACTION, "", detail))
    return findings


def inspect_qgz(content: bytes) -> ArchiveReport:
    """Lit une archive .qgz en memoire et liste ce qui bloque son enregistrement."""
    if not content or not bytes(content[:2]) == b"PK":
        raise ProjectFileError("archive .qgz (ZIP) attendue")
    try:
        zf = zipfile.ZipFile(io.BytesIO(bytes(content)))
    except zipfile.BadZipFile as exc:
        raise ProjectFileError(f"archive ZIP invalide ({exc})") from exc

    with zf:
        names = zf.namelist()
        qgs_entries = [n for n in names if n.lower().endswith(".qgs")]
        if not qgs_entries:
            raise ProjectFileError("aucun fichier .qgs dans l'archive")
        findings: List[Finding] = [Finding(FINDING_PYTHON_FILE, "", n)
                                   for n in names if n.lower().endswith(".py")]
        first = None
        for entry in qgs_entries:
            if zf.getinfo(entry).file_size > _MAX_QGS_BYTES:
                raise ProjectFileError(f"{entry} : trop volumineux une fois decompresse")
            try:
                data = zf.read(entry)
            except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
                raise ProjectFileError(f"lecture de {entry} impossible ({exc})") from exc
            root = _parse_qgs(data, entry)
            findings.extend(scan_qgs(root))
            if first is None:
                first = (entry, root)

    entry, root = first
    return ArchiveReport(
        qgs_name=entry,
        saved_at=root.get("saveDateTime") or None,
        saved_by=root.get("saveUserFull") or root.get("saveUser") or None,
        findings=tuple(findings),
    )


# ---------------------------------------------------------------------------
# Neutralisation a l'ouverture (spec 2.1 § 7.5) : appliquee a TOUT projet
# ouvert depuis la base par le Bridge, le sien compris.
# ---------------------------------------------------------------------------
_XML_HEADER = ('<?xml version="1.0" encoding="UTF-8"?>\n'
               "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n")
_URI_PASSWORD_RE = re.compile(r"&password=[^&]*", re.IGNORECASE)
_LEADING_URI_PASSWORD_RE = re.compile(r"^password=[^&\s]*&", re.IGNORECASE)
_LIBPQ_PASSWORD_RE = re.compile(r"\bpassword\s*=\s*(?:'(?:[^'\\]|\\.)*'|[^\s']\S*)(?=\s|$)", re.IGNORECASE)


@dataclass(frozen=True)
class NeutralizeResult:
    xml: str
    removed: tuple


def strip_datasource_password(datasource: str) -> str:
    """Retire un mot de passe en clair d'une source (libpq ou URI)."""
    if not datasource or "password" not in datasource.lower():
        return datasource
    out = _URI_PASSWORD_RE.sub("", datasource)
    out = _LEADING_URI_PASSWORD_RE.sub("", out)
    out = _LIBPQ_PASSWORD_RE.sub("", out)
    if out == datasource:
        return datasource
    return re.sub(r" {2,}", " ", out).strip()


def _clear(el: Optional[ET.Element]) -> None:
    if el is not None:
        el.text = ""


def neutralize_qgs_xml(xml: str) -> NeutralizeResult:
    """Vide macros, fonctions d'expression, actions non URL, code de
    formulaire et mots de passe en clair. Rien trouve : *xml* rendu tel quel
    (meme objet). Leve ProjectFileError sur entite XML ou XML illisible."""
    root = _parse_qgs(xml)
    removed: List[Finding] = []

    macros = [el for el in _macro_elements(root) if _text(el)]
    if macros:
        removed.append(Finding(FINDING_MACROS))
        for el in macros:
            _clear(el)
    expressions = [el for el in _expression_elements(root) if _text(el)]
    if expressions:
        removed.append(Finding(FINDING_EXPRESSION_FUNCTIONS))
        for el in expressions:
            _clear(el)

    parents = {id(child): parent for parent in root.iter() for child in parent}
    layer_of = {}
    for maplayer in root.iter("maplayer"):
        label = _layer_label(maplayer)
        for el in maplayer.iter():
            layer_of[id(el)] = label

    for action in list(root.iter("actionsetting")):
        detail = _action_refused(action)
        if detail:
            removed.append(Finding(FINDING_ACTION, layer_of.get(id(action), ""), detail))
            parent = parents.get(id(action))
            if parent is not None:
                parent.remove(action)

    password_layers = set()
    for maplayer in root.iter("maplayer"):
        label = _layer_label(maplayer)
        init_fn = _form_init_refused(maplayer)
        if init_fn:
            removed.append(Finding(FINDING_FORM_INIT, label, init_fn))
            source = maplayer.find("editforminitcodesource")
            if source is not None:
                source.text = "0"
            for tag in ("editforminit", "editforminitcode", "editforminitfilepath"):
                _clear(maplayer.find(tag))
        ds = maplayer.find("datasource")
        if ds is not None and ds.text:
            cleaned = strip_datasource_password(ds.text)
            if cleaned != ds.text:
                ds.text = cleaned
                password_layers.add(id(ds))
                removed.append(Finding(FINDING_PASSWORD, label))

    # Autres emplacements d'une source : <datasource> hors couche (mises en
    # page, couches embarquees) et attribut source de l'arbre des couches.
    other_password = False
    for el in root.iter():
        if el.tag == "datasource" and id(el) not in password_layers and el.text:
            cleaned = strip_datasource_password(el.text)
            if cleaned != el.text:
                el.text = cleaned
                other_password = True
        source_attr = el.get("source")
        if source_attr:
            cleaned = strip_datasource_password(source_attr)
            if cleaned != source_attr:
                el.set("source", cleaned)
                other_password = True
    if other_password and not password_layers:
        removed.append(Finding(FINDING_PASSWORD))

    if not removed:
        return NeutralizeResult(xml, ())
    return NeutralizeResult(_XML_HEADER + ET.tostring(root, encoding="unicode"), tuple(removed))
