"""Bridge 2.1 — appels SQL du schema projet (bridge_qgis_store) sur un faux
curseur : lectures, ecritures et classement des erreurs par HINT code."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from constructel_bridge import bridge_projets as pj
from constructel_bridge import bridge_qgis_store as store
from constructel_bridge.bridge_qgis_projects import SharePlan


class PgError(Exception):
    def __init__(self, code, message, detail="", hint=None):
        super().__init__(message)
        self.pgcode = code
        self.diag = SimpleNamespace(message_primary=message, message_detail=detail or None, message_hint=hint)


def pg_error(code, message, detail="", hint=None):
    return PgError(code, message, detail, hint)


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.closed = False
        self._result = None

    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        n = len(self.conn.executed)
        if n in self.conn.failures:
            raise self.conn.failures[n]
        if self.conn.error is not None:
            raise self.conn.error
        self._result = self.conn.answers.pop(0) if self.conn.answers else self.conn.default

    def fetchone(self):
        res = self._result
        if isinstance(res, dict):
            return res.get("one")
        return None

    def fetchall(self):
        res = self._result
        if isinstance(res, dict):
            return list(res.get("all", []))
        return []

    def close(self):
        self.closed = True
        self.conn.closed_cursors += 1


class FakeConn:
    def __init__(self):
        self.executed = []
        self.answers = []
        self.failures = {}
        self.error = None
        self.default = {"one": (1,), "all": []}
        self.closed_cursors = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def answer(self, one=None, all=None):
        self.answers.append({"one": one, "all": all if all is not None else []})

    def answer_each(self, ok):
        for _ in range(ok):
            self.answer(one=(1,))

    def fail_at(self, n, exc):
        self.failures[n] = exc


@pytest.fixture
def conn():
    return FakeConn()


VISIBLE = ("Vue", "ad", "a0b1", "GOFIBER", "GoFiber", False, False, "BE", 2,
           dt.datetime(2026, 11, 19, 10, 0), "ad", True, True, 0, "desc")


# ---------------------------------------------------------------- Task 5 : lectures

def test_read_capabilities_passes_function_names_and_survives_errors(conn):
    conn.answer(all=[("r", "projets", True), ("r", "projet_couches", True)])
    caps = store.read_capabilities(conn)
    sql, params = conn.executed[-1]
    assert sql == pj.CAPABILITIES_QUERY and list(params) == [list(pj.CAPABILITY_FUNCTIONS)]
    assert caps.registry and not caps.qgis_projects
    conn.error = RuntimeError("boom")
    assert store.read_capabilities(conn) == pj.NO_CAPABILITIES


def test_read_projets_error_is_empty(conn):
    conn.answer(all=[("b3", "GOFIBER", "GoFiber", None, "t", "T", None, None, "geom", 1)])
    (projet,) = store.read_projets(conn)
    assert projet.code == "GOFIBER" and conn.executed[-1][0] == pj.PROJETS_QUERY
    conn.error = RuntimeError("permission denied")
    assert store.read_projets(conn) == ()


def test_list_visible_maps_records_and_none_on_error(conn):
    conn.answer(all=[VISIBLE])
    (row,) = store.list_visible(conn)
    assert row.name == "Vue" and row.is_owner and row.projet_code == "GOFIBER"
    assert conn.executed[-1][0] == store.VISIBLE_QUERY
    conn.error = RuntimeError("x")
    assert store.list_visible(conn) is None


def test_read_for_open_converts_memoryview_and_missing_row(conn):
    conn.answer(one=(memoryview(b"PK\x03\x04"), {"description": "d"}, 3, "a0b1"))
    row = store.read_for_open(conn, "Vue")
    assert row == store.OpenRow(b"PK\x03\x04", {"description": "d"}, 3, "a0b1")
    assert isinstance(row.content, bytes) and conn.executed[-1][1] == ("Vue",)
    conn.answer(one=None)
    assert store.read_for_open(conn, "Absent") is None
    conn.answer(one=(b"PK", "pas un dict", 1, None))
    assert store.read_for_open(conn, "Vue").metadata == {}


def test_current_version_none_when_invisible(conn):
    conn.answer(one=(7,))
    assert store.current_version(conn, "Vue") == 7
    conn.answer(one=None)
    assert store.current_version(conn, "Vue") is None
    conn.error = RuntimeError("x")
    assert store.current_version(conn, "Vue") is None


def test_shares_list_maps_rows_and_none_on_error(conn):
    conn.answer(all=[("a.leroy", "Alice Leroy", "BE", True, False)])
    (share,) = store.shares_list(conn, "Vue")
    assert share.username == "a.leroy" and share.can_edit and not share.operant
    conn.error = pg_error("42501", "reserve", hint="QGISP_NOT_OWNER")
    assert store.shares_list(conn, "Vue") is None


def test_every_cursor_is_closed(conn):
    store.read_capabilities(conn)
    store.list_visible(conn)
    conn.error = RuntimeError("x")
    store.read_projets(conn)
    assert conn.closed_cursors == 3


def test_no_query_passes_p_as_user(conn):
    store.read_capabilities(conn)
    store.read_projets(conn)
    store.list_visible(conn)
    conn.answer(one=None)
    store.read_for_open(conn, "Vue")
    store.current_version(conn, "Vue")
    store.shares_list(conn, "Vue")
    assert conn.executed and all("p_as_user" not in sql for sql, _ in conn.executed)
