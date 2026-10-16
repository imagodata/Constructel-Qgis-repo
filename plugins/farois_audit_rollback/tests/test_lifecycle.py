from types import SimpleNamespace
from unittest.mock import Mock

from plugins.farois_audit_rollback.gui.lifecycle import SignalScope, live_ui


def test_dispose_disconnects_exact_slots_and_closes_database_once():
    scope = SignalScope()
    signal, slot, db = Mock(), Mock(), Mock()
    scope.connect(signal, slot)
    scope.replace_database(db)
    scope.dispose()
    scope.dispose()
    signal.disconnect.assert_called_once_with(slot)
    db.close.assert_called_once()
    assert scope.disposed and not scope.connections


def test_deleted_signal_does_not_prevent_other_cleanup():
    scope = SignalScope()
    deleted, live, db = Mock(), Mock(), Mock()
    deleted.disconnect.side_effect = RuntimeError(
        "wrapped C/C++ object has been deleted"
    )
    scope.connect(deleted, Mock())
    scope.connect(live, Mock())
    scope.replace_database(db)
    scope.dispose()
    live.disconnect.assert_called_once()
    db.close.assert_called_once()


def test_database_replacement_releases_previous_connection():
    scope = SignalScope()
    old, new = Mock(), Mock()
    scope.replace_database(old)
    scope.replace_database(new)
    scope.dispose()
    old.close.assert_called_once()
    new.close.assert_called_once()


def test_queued_callback_does_not_touch_deleted_ui():
    ui = SimpleNamespace(is_usable=lambda: False, _signals=SignalScope())
    touch_widget = Mock(side_effect=RuntimeError("QComboBox has been deleted"))
    guarded = live_ui(lambda self: touch_widget())
    assert guarded(ui) is None
    touch_widget.assert_not_called()
    assert ui._signals.disposed


def test_dispose_does_not_call_a_signal_of_a_deleted_cpp_sender():
    class Owner:
        deleted = False

    owner = Owner()
    signal, slot = Mock(), Mock()
    signal.disconnect.side_effect = AssertionError("must not touch freed C++ sender")
    scope = SignalScope(is_deleted=lambda obj: obj.deleted)
    scope.connect(signal, slot, owner)
    owner.deleted = True
    scope.dispose()
    signal.disconnect.assert_not_called()
