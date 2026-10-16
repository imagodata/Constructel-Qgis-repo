"""Track signal connections independently of the lifetime of Qt widgets."""

from functools import wraps
from weakref import ref


class SignalScope:
    def __init__(self, is_deleted=lambda obj: False):
        self.disposed = False
        self.connections = []
        self.database = None
        self.is_deleted = is_deleted

    def connect(self, signal, slot, owner=None):
        if self.disposed:
            return
        signal.connect(slot)
        self.connections.append(
            (signal, slot, ref(owner) if owner is not None else None)
        )

    def disconnect(self, signal, slot):
        try:
            signal.disconnect(slot)
        except (TypeError, RuntimeError, AttributeError):
            pass
        self.connections = [
            (s, f, owner) for s, f, owner in self.connections if f != slot
        ]

    def replace_database(self, database):
        previous, self.database = self.database, database
        if previous is not None and previous is not database:
            previous.close()

    def dispose(self, *args):
        if self.disposed:
            return
        # Mark inactive first: a queued callback may still run after disconnect.
        self.disposed = True
        connections, self.connections = self.connections, []
        for signal, slot, owner_ref in connections:
            owner = owner_ref() if owner_ref is not None else None
            # Never touch a bound signal whose C++ sender was already freed.
            if owner_ref is not None and (owner is None or self.is_deleted(owner)):
                continue
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError, AttributeError):
                pass
        database, self.database = self.database, None
        if database is not None:
            database.close()


def live_ui(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        if not self.is_usable():
            self._signals.dispose()
            return None
        return method(self, *args, **kwargs)

    return guarded
