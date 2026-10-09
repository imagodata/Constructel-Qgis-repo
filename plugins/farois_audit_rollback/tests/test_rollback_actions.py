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
    assert "transactionnel" in change[1]
