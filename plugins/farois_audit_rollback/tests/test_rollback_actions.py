from dataclasses import replace

import pytest

from plugins.farois_audit_rollback.gui.history_model import HistoryEntry
from plugins.farois_audit_rollback.gui.rollback_actions import action_states

TX = "00000000-0000-4000-8000-000000000010"


def entry(**kw):
    return replace(
        HistoryEntry(change_id="change", can_undo=True, transaction_id=TX), **kw
    )


def test_explicit_change_and_transaction_choices():
    change, transaction = action_states(entry())
    assert change[0] and transaction[0]
    assert TX in transaction[1]


@pytest.mark.parametrize("tx", [None, "", 42, "42", "not-a-uuid"])
def test_no_uuid_does_not_enable_transaction(tx):
    change, transaction = action_states(entry(transaction_id=tx))
    assert change[0]
    assert not transaction[0]


@pytest.mark.parametrize(
    "extra",
    [
        dict(cascade_count=2),
        dict(cascade_root_id="root"),
        dict(provenance="CASCADE"),
        dict(provenance="import"),
        dict(provenance="AUTO"),
        dict(origin="CASCADE", provenance="MANUAL"),
        dict(origin="PIPELINE"),
        dict(origin="BULK"),
    ],
)
def test_cascades_and_imports_are_not_undone_individually(extra):
    change, transaction = action_states(entry(**extra))
    assert not change[0]
    assert transaction[0]


@pytest.mark.parametrize("args", [dict(connected=False), dict(current=False)])
def test_missing_connection_or_stale_context_disables_both(args):
    assert all(not state[0] for state in action_states(entry(), **args))


def test_server_refusal_is_preserved():
    states = action_states(
        entry(can_undo=False, refusal_reason="Modification déjà annulée")
    )
    assert all(
        not state[0] and state[1] == "Modification déjà annulée" for state in states
    )


def test_empty_history_disables_both():
    assert all(not state[0] for state in action_states(None))


def test_direct_root_with_another_pending_group_member_requires_transaction():
    root = entry(origin="DIRECT", provenance="MANUAL", cascade_count=1)
    change, transaction = action_states(root)
    assert not change[0] and transaction[0]
    assert "Annuler la transaction" in change[1]


TX_INSERT = "00000000-0000-4000-8000-0000000000b1"


def test_insert_change_points_to_transaction_undo():
    row = HistoryEntry(change_id="c", operation="INSERT", transaction_id=TX_INSERT, can_undo=True)
    (change_ok, change_reason), (tx_ok, _) = action_states(row)
    assert not change_ok
    assert "Annuler la transaction" in change_reason
    assert tx_ok


def test_disabled_action_text_truncates_the_reason_to_70_characters():
    from plugins.farois_audit_rollback.gui.rollback_actions import disabled_action_text

    assert disabled_action_text("Annuler", "Court.") == "Annuler — Court."
    assert disabled_action_text("Annuler", "") == "Annuler"
    text = disabled_action_text("Annuler", "x" * 100)
    assert text == "Annuler — " + "x" * 69 + "…"


def test_linked_change_points_to_transaction_with_short_reason():
    entry = HistoryEntry(
        change_id="c",
        operation="UPDATE",
        transaction_id="00000000-0000-4000-8000-0000000000c1",
        cascade_count=2,
        can_undo=True,
    )
    (change_ok, change_reason), (tx_ok, _) = action_states(entry)
    assert not change_ok
    assert change_reason == "Liée à d'autres changements : utilisez « Annuler la transaction »."
    assert len(change_reason) <= 70
    assert tx_ok
