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


# ---------------------------------------------------------------- Task 6 : ecritures et erreurs
# Mise a jour du contrat (Q4) : le plugin classe par le HINT code, jamais par le texte.

@pytest.mark.parametrize("code,hint,status", [
    ("FP409", "QGISP_VERSION_CONFLICT", "conflict"),
    ("42501", "QGISP_NAME_TAKEN", "name_taken"),
    ("42501", "QGISP_NOT_FOUND", "gone"),
    ("42501", "QGISP_NOT_NOMINATIVE", "nominative"),
    ("42501", "QGISP_PROJET_FORBIDDEN", "projet_denied"),
    ("42501", "QGISP_NOT_OWNER", "denied"),
    ("42501", "QGISP_ADMIN_ONLY", "denied"),
    ("42501", "QGISP_DELEGATION_DENIED", "error"),
    ("23514", "QGISP_NOT_ELIGIBLE", "ineligible"),
    ("22023", None, "invalid"),
    ("42501", "QGISP_SOMETHING_NEW", "error"),
    ("42501", None, "error"),
    (None, None, "error"),
])
def test_classify_error_by_hint(code, hint, status):
    assert store.classify_error(pg_error(code, "message quelconque", hint=hint)).status == status


def test_message_text_is_never_used_to_classify():
    # Ancien texte « deja utilise » sans HINT : erreur generique, pas name_taken.
    out = store.classify_error(pg_error("42501", "nom de projet x deja utilise"))
    assert out.status == "error" and out.message == "nom de projet x deja utilise"


def test_unknown_hint_keeps_the_message():
    out = store.classify_error(pg_error("42501", "nouveau refus", hint="QGISP_FUTURE"))
    assert out.status == "error" and out.message == "nouveau refus"


def test_invalid_shows_server_message():
    out = store.classify_error(pg_error("22023", "nom de projet QGIS invalide"))
    assert out.status == "invalid" and out.message == "nom de projet QGIS invalide"


def test_version_conflict_code_without_hint_is_still_a_conflict():
    assert store.classify_error(pg_error("FP409", "conflit")).status == "conflict"


def test_hint_read_from_diag_hint_attribute_too():
    exc = PgError("42501", "x")
    exc.diag = SimpleNamespace(message_primary="x", message_detail=None, hint="QGISP_NAME_TAKEN")
    assert store.classify_error(exc).status == "name_taken"


def test_ineligible_count_and_conflict_detail():
    out = store.classify_error(pg_error("23514", "partage refuse : 2 personne(s)", hint="QGISP_NOT_ELIGIBLE"))
    assert out.count == 2
    out = store.classify_error(pg_error("FP409", "conflit", detail="version courante 5, modifiee le 2026-11-19 par bob",
                                        hint="QGISP_VERSION_CONFLICT"))
    assert out.detail.startswith("version courante 5")


def test_plain_exception_is_a_generic_error():
    out = store.classify_error(RuntimeError("server closed the connection"))
    assert out.status == "error" and "server closed" in out.message


def test_save_create_passes_null_version_and_returns_new_version(conn):
    conn.answer(one=(1,))
    out = store.save(conn, "Vue", b"PK\x03\x04", {"description": "d"}, None, None)
    sql, params = conn.executed[-1]
    assert "fn_qgis_project_save" in sql and params[3] is None and params[4] is None
    assert params[0] == "Vue" and bytes(getattr(params[1], "adapted", params[1])) == b"PK\x03\x04" and params[2] == '{"description": "d"}'
    assert out.status == "ok" and out.value == 1


def test_save_update_and_conflict(conn):
    conn.answer(one=(5,))
    out = store.save(conn, "Vue", b"PK", {"description": "é"}, 4, "a0b1")
    sql, params = conn.executed[-1]
    assert params[3] == 4 and params[4] == "a0b1" and "é" in params[2] and out.value == 5
    conn.fail_at(2, pg_error("FP409", "conflit", detail="version courante 6", hint="QGISP_VERSION_CONFLICT"))
    out = store.save(conn, "Vue", b"PK", {}, 4, None)
    assert out.status == "conflict" and out.detail == "version courante 6"


def test_delete_true_false_denied(conn):
    conn.answer(one=(True,))
    assert store.delete(conn, "Vue").status == "ok"
    conn.answer(one=(False,))
    assert store.delete(conn, "Vue").status == "missing"
    conn.fail_at(3, pg_error("42501", "reserve", hint="QGISP_NOT_OWNER"))
    assert store.delete(conn, "Vue").status == "denied"


def test_eligible_users_needs_three_characters_and_passes_exclude(conn):
    assert store.eligible_users(conn, "GOFIBER", " ab ", []) == [] and conn.executed == []
    conn.answer(all=[("a.leroy", "Alice Leroy", "BE")])
    (user,) = store.eligible_users(conn, "GOFIBER", "ale", ["b.x"])
    sql, params = conn.executed[-1]
    assert "p_exclude" in sql and params == ("GOFIBER", "ale", ["b.x"]) and user.username == "a.leroy"
    assert "p_as_user" not in sql


def test_eligible_users_prefix_capped_and_errors_are_none(conn):
    conn.answer(all=[])
    store.eligible_users(conn, None, "x" * 80, ())
    assert conn.executed[-1][1] == (None, "x" * 50, [])
    conn.error = pg_error("42501", "inaccessible", hint="QGISP_PROJET_FORBIDDEN")
    assert store.eligible_users(conn, "GOFIBER", "ale", []) is None


def test_eligible_users_requests_the_limit_within_server_bounds(conn):
    conn.answer(all=[])
    store.eligible_users(conn, None, "ale", [])
    assert ", 20, p_exclude" in conn.executed[-1][0]


def test_apply_share_plan_order_chunks_and_stop_on_first_error(conn):
    plan = SharePlan(True, ("c",), tuple(f"u{i:02d}" for i in range(25)), ("d",))
    conn.answer_each(ok=4)                     # set_share_project, unshare, share(20), share(5) ok ; share(open) leve 23514
    conn.fail_at(5, pg_error("23514", "partage refuse : 1 personne(s)", hint="QGISP_NOT_ELIGIBLE"))
    out = store.apply_share_plan(conn, "Vue", plan)
    names = [sql.split("(")[0].split(".")[-1] for sql, _ in conn.executed]
    assert names == ["fn_qgis_project_set_share_project", "fn_qgis_project_unshare", "fn_qgis_project_share",
                     "fn_qgis_project_share", "fn_qgis_project_share"]
    assert out.status == "ineligible" and out.value == 4 and out.count == 1
    assert conn.executed[2][1] == ("Vue", [f"u{i:02d}" for i in range(20)], True)
    assert conn.executed[4][1] == ("Vue", ["d"], False)


def test_apply_share_plan_ok_counts_calls(conn):
    out = store.apply_share_plan(conn, "Vue", SharePlan(None, (), ("a",), ()))
    assert out.status == "ok" and out.value == 1 and len(conn.executed) == 1


def test_writes_never_pass_p_as_user(conn):
    store.save(conn, "Vue", b"PK", {}, None, None)
    store.delete(conn, "Vue")
    store.eligible_users(conn, None, "ale", [])
    store.apply_share_plan(conn, "Vue", SharePlan(True, ("a",), ("b",), ("c",)))
    assert all("p_as_user" not in sql for sql, _ in conn.executed)


def test_errors_reach_the_plugin_log_callback(conn):
    seen = []
    conn.error = RuntimeError("boom")
    store.read_capabilities(conn, log=seen.append)
    store.list_visible(conn, log=seen.append)
    store.save(conn, "Vue", b"PK", {}, None, None, log=seen.append)
    assert len(seen) == 3 and all("boom" in m for m in seen)


def test_ineligible_count_ignores_digits_of_the_project_name():
    # Revue 2.1 (M5) : message reel du serveur, nom du projet en tete.
    msg = "partage du projet QGIS Zone 12 POP 3 refuse : 2 personne(s) non eligible(s)"
    assert store.classify_error(pg_error("23514", msg, hint="QGISP_NOT_ELIGIBLE")).count == 2
