"""Textes des enregistrements refuses (Bridge 2.1) : dialogue « Enregistrer
le projet courant… » et disquette d'un projet QGIS en base. Sans Qt."""
from __future__ import annotations

from .bridge_project_safety import (
    FINDING_ACTION,
    FINDING_EMBEDDED_PROJECT,
    FINDING_EXPRESSION_FUNCTIONS,
    FINDING_FORM_INIT,
    FINDING_MACROS,
    FINDING_PASSWORD,
    FINDING_PYTHON_FILE,
    Finding,
)
from .bridge_qgis_store import (
    STATUS_GONE,
    STATUS_INVALID,
    STATUS_NAME_TAKEN,
    STATUS_NOMINATIVE,
    STATUS_PROJET_DENIED,
)
from .i18n import tr

# K11 : un appel tr LITTERAL par cle.
_FINDINGS = {
    FINDING_MACROS: lambda f: tr("save.finding_macros"),
    FINDING_EXPRESSION_FUNCTIONS: lambda f: tr("save.finding_expression_functions"),
    FINDING_ACTION: lambda f: tr("save.finding_action", detail=f.detail),
    FINDING_FORM_INIT: lambda f: tr("save.finding_form_init", detail=f.detail),
    FINDING_PASSWORD: lambda f: tr("save.finding_password"),
    FINDING_PYTHON_FILE: lambda f: tr("save.finding_python_file", detail=f.detail),
    FINDING_EMBEDDED_PROJECT: lambda f: tr("save.finding_embedded_project", detail=f.detail),
}


def format_finding(finding: Finding) -> str:
    """Constat du controle a l'enregistrement, lisible (« couche « Points » :
    action de type Python… »)."""
    text = _FINDINGS.get(finding.kind, lambda f: f.kind)(finding)
    if finding.layer:
        return tr("save.finding_layer", layer=finding.layer) + " " + text
    return text


def save_outcome_text(outcome) -> str:
    """Texte d'un enregistrement refuse."""
    status = outcome.status
    if status == STATUS_NAME_TAKEN:
        return tr("save.name_taken")
    if status == STATUS_GONE:
        return tr("save.gone")
    if status == "unsafe":
        lines = [tr("save.unsafe_intro")] + ["• " + format_finding(f) for f in (outcome.value or ())]
        return "\n".join(lines)
    if status == STATUS_NOMINATIVE:
        return tr("save.nominative")
    if status == STATUS_PROJET_DENIED:
        return tr("save.projet_denied")
    if status == STATUS_INVALID:
        return tr("save.invalid", message=outcome.message or "")
    if status == "too_large":
        return tr("save.too_large")
    if status == "empty":
        return tr("save.empty_project")
    return tr("save.error", message=outcome.message or "")
