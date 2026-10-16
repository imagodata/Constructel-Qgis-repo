"""Pure-Python history model, independent of QGIS and Qt."""

from dataclasses import dataclass, field, replace
from typing import Any, Iterable

STATUS_MESSAGES = {
    "cancelable": "Modification annulable",
    "already_reverted": "Modification déjà annulée",
    "out_of_window": "Modification hors délai",
    "other_user": "Modification effectuée par un autre utilisateur",
    "concurrent": "Modification concurrente détectée",
    "admin_required": "Annulation réservée à un administrateur",
    "automatic": "Origine automatique non annulable dans cette version",
}


@dataclass(frozen=True)
class HistoryEntry:
    change_id: Any
    changed_at: Any = None
    username: str = ""
    schema_name: str = ""
    table_name: str = ""
    record_id: Any = None
    label: str = ""
    operation: str = ""
    changed_columns: tuple[str, ...] = field(default_factory=tuple)
    provenance: str = ""
    origin: str = ""
    before: Any = None
    after: Any = None
    can_undo: bool = False
    refusal_reason: str = ""
    transaction_id: Any = None
    cascade_root_id: Any = None
    cascade_count: int = 0
    in_engine: bool = False
    already_undone: bool = False
    raw: Any = None

    @classmethod
    def from_row(cls, row):
        def get(name, default=None):
            if isinstance(row, dict):
                return row.get(name, default)
            return getattr(row, name, default)

        def first(*names, default=None):
            return next(
                (get(name) for name in names if get(name) not in (None, "")), default
            )

        before = first("before_values", "before", "before_data", "old_data")
        after = first("after_values", "after", "after_data", "new_data")
        label = first("business_label", "label", "record_label")
        if not label:
            for values in (after, before):
                if isinstance(values, dict):
                    label = next(
                        (
                            values.get(name)
                            for name in (
                                "label",
                                "beon_label",
                                "code",
                                "name",
                                "nom",
                                "reference",
                            )
                            if values.get(name) not in (None, "")
                        ),
                        None,
                    )
                    if label:
                        break
        columns = get("changed_columns", ()) or ()
        if isinstance(columns, str):
            columns = tuple(x.strip() for x in columns.split(",") if x.strip())
        if not columns and isinstance(before, dict) and isinstance(after, dict):
            columns = sorted(
                key
                for key in before.keys() | after.keys()
                if before.get(key) != after.get(key)
            )
        return cls(
            change_id=get("change_id", get("id")),
            changed_at=get("changed_at", get("changed_at_utc")),
            username=str(
                first(
                    "username",
                    "actor",
                    "changed_by",
                    "author_id",
                    default="Utilisateur non identifié",
                )
            ),
            schema_name=str(get("schema_name", "") or ""),
            table_name=str(get("table_name", "") or ""),
            record_id=get("record_id"),
            label=str(label or "Libellé non renseigné"),
            operation=str(get("operation", "") or "").upper(),
            changed_columns=tuple(columns),
            provenance=str(
                first(
                    "provenance",
                    "change_source",
                    "origin",
                    default="Origine non renseignée",
                )
            ),
            origin=str(get("origin", "") or "").upper(),
            before=before,
            after=after,
            can_undo=bool(get("can_undo", get("undo_allowed", False)))
            and not bool(get("already_undone", False)),
            refusal_reason=(
                "Modification déjà annulée"
                if get("already_undone", False)
                else str(get("refusal_reason", "") or "")
            ),
            transaction_id=get("transaction_id"),
            cascade_root_id=get("cascade_root_id"),
            cascade_count=int(get("cascade_count", 0) or 0),
            in_engine=bool(get("in_engine", False)),
            already_undone=bool(get("already_undone", False)),
            raw=row,
        )

    @property
    def status_message(self):
        if self.refusal_reason:
            return self.refusal_reason
        return (
            STATUS_MESSAGES["cancelable"]
            if self.can_undo
            else "Modification non annulable"
        )

    def as_admin(self):
        """Vue d'un admin connecté à l'API Farois : refus liés à l'identité levés.

        Le moteur et l'API restent l'autorité ; seules les lignes connues du moteur
        et pas encore annulées deviennent annulables.
        """
        if self.already_undone:
            return replace(self, can_undo=False, refusal_reason="Modification déjà annulée")
        if not self.in_engine:
            return replace(
                self,
                can_undo=False,
                refusal_reason=self.refusal_reason or "Changement hors périmètre du moteur",
            )
        return replace(self, can_undo=True, refusal_reason="")


class HistoryModel:
    def __init__(self, entries: Iterable[HistoryEntry] = ()):
        self.set_entries(entries)

    def set_entries(self, entries):
        self.entries = list(entries)

    def filtered(self, user="", provenance="", column="", cancelable_only=False):
        user, provenance, column = user.lower(), provenance.lower(), column.lower()
        return [
            e
            for e in self.entries
            if (not user or user in e.username.lower())
            and (not provenance or provenance in e.provenance.lower())
            and (not column or any(column in c.lower() for c in e.changed_columns))
            and (not cancelable_only or e.can_undo)
        ]

    def preview(self, entry):
        return {
            "change_id": entry.change_id,
            "before": entry.before,
            "after": entry.after,
            "operation": entry.operation,
            "can_undo": entry.can_undo,
            "status": entry.status_message,
        }
