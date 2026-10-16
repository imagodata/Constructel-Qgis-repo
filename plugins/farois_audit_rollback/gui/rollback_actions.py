"""Presentation of rollback choices; PostgreSQL remains the authority."""

from uuid import UUID


def transaction_uuid(entry):
    if entry is None or entry.transaction_id is None:
        return None
    try:
        return str(UUID(str(entry.transaction_id)))
    except (ValueError, TypeError, AttributeError):
        return None


def action_states(entry, connected=True, current=True):
    reason = None
    if not connected:
        reason = "Connexion PostgreSQL du panneau non configurée."
    elif not current:
        reason = "Actualisez l'historique de l'objet source sélectionné."
    elif entry is None:
        reason = "Sélectionnez une modification dans l'historique."
    elif not entry.can_undo:
        reason = entry.status_message
    if reason:
        return (False, reason), (False, reason)
    linked = bool(
        entry.cascade_root_id
        or entry.cascade_count
        or entry.origin.upper() in {"CASCADE", "PIPELINE", "BULK"}
        or entry.provenance.lower() in {"cascade", "import", "auto", "pipeline", "bulk"}
    )
    change_blocked = None
    if linked:
        change_blocked = "Liée à d'autres changements : utilisez « Annuler la transaction »."
    elif entry.operation == "INSERT":
        change_blocked = "Une création s'annule via « Annuler la transaction »."
    change = (
        change_blocked is None and bool(entry.change_id),
        change_blocked
        or "Annuler uniquement la modification sélectionnée, après confirmation.",
    )
    tx = transaction_uuid(entry)
    transaction = (
        bool(tx),
        f"Demander l'annulation de la transaction {tx}. PostgreSQL vérifiera tous les droits."
        if tx
        else "UUID de transaction absent ou incompatible avec le moteur Farois.",
    )
    return change, transaction


def disabled_action_text(label, reason, limit=70):
    """Texte de menu d'une action désactivée : la raison, tronquée, visible.

    Le menu clic droit n'affiche pas toujours les infobulles ; l'infobulle
    garde la raison complète.
    """
    reason = " ".join(str(reason or "").split())
    if not reason:
        return label
    if len(reason) > limit:
        reason = reason[: limit - 1] + "…"
    return f"{label} — {reason}"
