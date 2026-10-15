from plugins.farois_audit_rollback.gui.history_model import HistoryEntry, HistoryModel


def entry(**overrides):
    data = dict(
        change_id="1",
        username="alice",
        provenance="manual",
        operation="UPDATE",
        changed_columns=("status",),
        can_undo=True,
    )
    data.update(overrides)
    return HistoryEntry(**data)


def test_empty_history_and_filters():
    assert HistoryModel().filtered() == []
    model = HistoryModel(
        [entry(), entry(change_id="2", username="bob", can_undo=False)]
    )
    assert len(model.filtered(user="alice")) == 1
    assert len(model.filtered(cancelable_only=True)) == 1
    assert model.filtered(column="status")[0].change_id == "1"


def test_status_messages_and_preview():
    e = entry(
        can_undo=False,
        refusal_reason="Modification déjà annulée",
        before={"x": 1},
        after={"x": 2},
    )
    assert e.status_message == "Modification déjà annulée"
    assert HistoryModel([e]).preview(e)["before"] == {"x": 1}


def test_insert_delete_cascade_are_displayable():
    entries = [
        entry(operation="INSERT"),
        entry(operation="DELETE"),
        entry(provenance="cascade", can_undo=False),
    ]
    assert [e.operation for e in HistoryModel(entries).entries] == [
        "INSERT",
        "DELETE",
        "UPDATE",
    ]


def test_real_scoped_view_fields():
    row = dict(
        change_id="change",
        actor="synthetic",
        record_label="Fixture",
        before_data={"depth": 1},
        after_data={"depth": 2},
        provenance="DIRECT",
    )
    e = HistoryEntry.from_row(row)
    assert e.username == "synthetic" and e.label == "Fixture"
    assert e.before == {"depth": 1} and e.after == {"depth": 2}
    assert not e.can_undo and e.transaction_id is None


def test_empty_aliases_do_not_hide_real_audit_fields():
    entry = HistoryEntry.from_row(
        {
            "change_id": "change",
            "username": None,
            "changed_by": None,
            "actor": "db_actor",
            "business_label": "",
            "record_label": None,
            "before_data": {"label": "Ancien", "status": "PLANNED"},
            "after_data": {"label": "Nouveau", "status": "STARTED"},
            "provenance": "",
            "change_source": "QGIS",
            "changed_columns": None,
        }
    )
    assert entry.username == "db_actor" and entry.label == "Nouveau"
    assert entry.provenance == "QGIS" and entry.changed_columns == ("label", "status")
    assert entry.before["label"] == "Ancien" and entry.after["label"] == "Nouveau"


def test_already_undone_is_never_cancelable_even_if_server_flag_true():
    entry = HistoryEntry.from_row({"can_undo": True, "already_undone": True})
    assert not entry.can_undo and "déjà annulée" in entry.status_message


def test_unknown_audit_fields_are_explicit_instead_of_blank():
    entry = HistoryEntry.from_row({"change_id": "change"})
    assert entry.username == "Utilisateur non identifié"
    assert entry.label == "Libellé non renseigné"
    assert entry.provenance == "Origine non renseignée"


def test_admin_view_unlocks_engine_rows_refused_for_identity():
    row = HistoryEntry.from_row({
        "change_id": "c", "operation": "UPDATE", "in_engine": True, "already_undone": False,
        "can_undo": False, "refusal_reason": "Modification effectuée par un autre utilisateur",
    })
    admin = row.as_admin()
    assert admin.can_undo and admin.refusal_reason == ""
    assert not row.can_undo


def test_admin_view_unlocks_delete_rows_refused_as_update_only():
    row = HistoryEntry.from_row({
        "change_id": "c", "operation": "DELETE", "in_engine": True,
        "refusal_reason": "Cette version annule uniquement les modifications UPDATE",
    })
    assert row.as_admin().can_undo


def test_admin_view_keeps_already_undone_and_out_of_engine_refused():
    undone = HistoryEntry.from_row({"change_id": "c", "in_engine": True, "already_undone": True})
    assert not undone.as_admin().can_undo
    assert undone.as_admin().status_message == "Modification déjà annulée"
    outside = HistoryEntry.from_row({"change_id": "c", "in_engine": False})
    assert not outside.as_admin().can_undo
    assert outside.as_admin().status_message == "Changement hors périmètre du moteur"
