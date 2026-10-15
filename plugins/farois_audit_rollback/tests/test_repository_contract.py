import pytest
from plugins.farois_audit_rollback.db.audit_repository import (
    AuditRepository,
    IdentifierPolicy,
)
from plugins.farois_audit_rollback.db.errors import InvalidIdentifierError


class Cursor:
    def __init__(self, rows=()):
        self.rows, self.calls = list(rows), []
        self.description = [("change_id",)]

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return ("undo-1",)

    def close(self):
        pass


class Connection:
    def __init__(self, rows=()):
        self.cursor_obj, self.commits, self.rollbacks = Cursor(rows), 0, 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_history_is_parameterized_and_empty():
    conn = Connection()
    repo = AuditRepository(conn)
    repo.engine_available = True
    assert repo.history("wyre", "roads", 7) == []
    sql, params = conn.cursor_obj.calls[-1]
    assert "v_undo_candidates" in sql and params == ("wyre", "roads", 7)


def test_identifiers_reject_injection():
    with pytest.raises(InvalidIdentifierError):
        AuditRepository(Connection()).history(
            "wyre", "roads; DROP TABLE audit.changes", 1
        )


def test_revert_requires_reason_and_commits():
    with pytest.raises(Exception, match="motif"):
        AuditRepository(Connection()).revert_change("id", " ")
    conn = Connection()
    repo = AuditRepository(conn)
    repo.engine_available = True
    assert repo.revert_change("id", "correction") == "undo-1"
    assert conn.commits == 1


def test_policy_allowlist():
    with pytest.raises(InvalidIdentifierError):
        IdentifierPolicy(allowed_schemas={"wyre"}).validate("orange", "roads")


def test_missing_engine_reads_only_scoped_view_and_maps_rows():
    conn = Connection([("change-1",)])
    repo = AuditRepository(conn)
    repo.engine_available = False
    assert repo.history("wyre", "roads", 7) == [{"change_id": "change-1"}]
    assert "audit.v_operator_changes_scoped" in conn.cursor_obj.calls[-1][0]
    assert "audit.changes" not in conn.cursor_obj.calls[-1][0]
    with pytest.raises(Exception, match="moteur d’annulation"):
        repo.revert_transaction("id", "correction")
    assert conn.commits == 0


def test_transaction_function_is_distinct_and_parameterized():
    conn = Connection()
    repo = AuditRepository(conn)
    repo.engine_available = True
    repo.revert_transaction("tx-id", "test ' parameter")
    assert conn.cursor_obj.calls == [
        ("SELECT audit.revert_transaction(%s, %s)", ("tx-id", "test ' parameter"))
    ]


def test_postgresql_conflict_rolls_back_and_preserves_error():
    conn = Connection()

    def conflict(*args):
        raise RuntimeError("Modification concurrente détectée")

    conn.cursor_obj.execute = conflict
    repo = AuditRepository(conn)
    repo.engine_available = True
    with pytest.raises(RuntimeError, match="concurrente"):
        repo.revert_change("id", "test")
    assert conn.rollbacks == 1 and conn.commits == 0


def test_history_sql_error_is_not_misreported_as_missing_engine():
    conn = Connection()

    def error(*args):
        raise RuntimeError("permission denied for v_undo_candidates")

    conn.cursor_obj.execute = error
    repo = AuditRepository(conn)
    repo.engine_available = True
    with pytest.raises(RuntimeError, match="permission denied"):
        repo.history("wyre", "roads", 7)


def test_layer_history_does_not_require_a_selected_record():
    conn = Connection([("synthetic-change",)])
    repo = AuditRepository(conn)
    repo.engine_available = False
    assert repo.layer_history("wyre", "zone_drop") == [
        {"change_id": "synthetic-change"}
    ]
    sql, params = conn.cursor_obj.calls[-1]
    assert "record_id =" not in sql and "v_operator_changes_scoped" in sql
    assert params == ("wyre", "zone_drop", 200)


def test_all_visible_history_never_reads_unscoped_audit():
    conn = Connection([("synthetic-change",)])
    repo = AuditRepository(conn)
    repo.engine_available = False
    assert len(repo.visible_history()) == 1
    sql, params = conn.cursor_obj.calls[-1]
    assert "audit.v_operator_changes_scoped" in sql and "audit.changes" not in sql
    assert params == (200,)


@pytest.mark.parametrize(
    "limit", [0, -1, 1001, True, "200", "1; DROP TABLE audit.changes"]
)
def test_recent_history_limit_is_validated(limit):
    repo = AuditRepository(Connection())
    repo.engine_available = False
    with pytest.raises(ValueError, match="limite"):
        repo.visible_history(limit)


@pytest.mark.parametrize(
    "contract,expected",
    [("legacy_field", True), ("reason", True), ("unsupported", False)],
)
def test_detects_contract_instead_of_assuming_text_argument_is_reason(
    contract, expected
):
    conn = Connection()
    conn.cursor_obj.fetchone = lambda: (True, contract)
    repo = AuditRepository(conn)
    assert repo.refresh_capabilities() is expected
    assert repo.engine_contract == contract
    sql = conn.cursor_obj.calls[0][0]
    assert "proargnames[2]" in sql and "'jsonb'::regtype" in sql
    assert "undo_candidates(name,name,uuid,integer)" in sql


def test_legacy_history_enriches_scoped_data_and_uses_server_identity():
    conn = Connection()
    repo = AuditRepository(conn)
    repo.engine_available, repo.engine_contract = True, "legacy_field"
    repo.history("wyre", "structures", "record")
    sql, params = conn.cursor_obj.calls[-1]
    assert "audit.v_operator_changes_scoped s" in sql
    assert "LEFT JOIN audit.v_undo_candidates u ON u.change_id = s.change_id" in sql
    assert "audit.fn_undo_caller()" in sql and "audit.undo_window()" in sql
    assert (
        "sibling.transaction_id = u.transaction_id" in sql and "AS cascade_count" in sql
    )
    assert "Auteur non identifié" in sql and "caller.caller_id IS NULL" in sql
    assert "audit.changes" not in sql
    assert params == ("wyre", "structures", "record")


def test_legacy_passes_field_and_commits_only_after_inspecting_report():
    conn = Connection()
    conn.autocommit = True
    states = []
    original_execute = conn.cursor_obj.execute

    def execute(sql, params):
        states.append(conn.autocommit)
        original_execute(sql, params)

    conn.cursor_obj.execute = execute
    conn.cursor_obj.fetchone = lambda: ({"reverted": ["label"], "conflicts": []},)
    repo = AuditRepository(conn)
    repo.engine_available, repo.engine_contract = True, "legacy_field"
    result = repo.revert_change("id", "Motif obligatoire")
    assert result["reverted"] == ["label"]
    assert states == [False, False]
    assert conn.cursor_obj.calls[-1][1] == ("id", "FIELD")
    assert conn.cursor_obj.calls[0][1] == ("Motif obligatoire",)
    assert conn.commits == 1 and conn.rollbacks == 0 and conn.autocommit is True


@pytest.mark.parametrize(
    "report",
    [
        {"reverted": ["label"], "conflicts": [{"column": "status"}]},
        {"changes": [{"reverted": ["label"], "conflicts": [{"column": "status"}]}]},
        {"changes": []},
        {"reverted": [], "conflicts": []},
        {"success": False},
        None,
    ],
)
def test_partial_revert_or_empty_result_rolls_back_before_autocommit_is_restored(
    report,
):
    conn = Connection()
    conn.autocommit = True
    conn.cursor_obj.fetchone = lambda: (report,)
    repo = AuditRepository(conn)
    repo.engine_available, repo.engine_contract = True, "legacy_field"
    with pytest.raises(Exception, match="Conflit|aucune|confirmé|plus de"):
        repo.revert_change("id", "motif")
    assert conn.commits == 0 and conn.rollbacks == 1 and conn.autocommit is True


def test_cursor_creation_failure_rolls_back_and_restores_connection_mode():
    conn = Connection()
    conn.autocommit = True
    conn.cursor = lambda: (_ for _ in ()).throw(RuntimeError("cursor failed"))
    repo = AuditRepository(conn)
    repo.engine_available, repo.engine_contract = True, "legacy_field"
    with pytest.raises(RuntimeError, match="cursor failed"):
        repo.revert_change("id", "motif")
    assert conn.autocommit is True and conn.rollbacks == 1 and conn.commits == 0


@pytest.mark.parametrize(
    "report", [False, True, "success", [], {"changes": ["success"]}]
)
def test_malformed_legacy_report_never_commits(report):
    conn = Connection()
    conn.autocommit = True
    conn.cursor_obj.fetchone = lambda: (report,)
    repo = AuditRepository(conn)
    repo.engine_available, repo.engine_contract = True, "legacy_field"
    with pytest.raises(Exception, match="rapport"):
        repo.revert_change("id", "motif")
    assert conn.commits == 0 and conn.rollbacks == 1 and conn.autocommit is True


@pytest.mark.parametrize("mode", ["object", "layer", "visible"])
def test_451_reads_scoped_endpoint_with_filters_before_eligibility_checks(mode):
    conn = Connection()
    repo = AuditRepository(conn)
    repo.engine_available, repo.engine_contract = True, "reason"
    if mode == "object":
        repo.history("wyre", "structures", "record")
        expected = ("wyre", "structures", "record", 1000)
    elif mode == "layer":
        repo.layer_history("wyre", "structures")
        expected = ("wyre", "structures", 200)
    else:
        repo.visible_history()
        expected = (200,)
    sql, params = conn.cursor_obj.calls[-1]
    assert "audit.undo_candidates(" in sql and "v_undo_candidates" not in sql
    assert params == expected


def test_451_motif_argument_and_real_uuid_result_are_preserved():
    conn = Connection()
    conn.autocommit = True
    identifier = "00000000-0000-4000-8000-000000000099"
    conn.cursor_obj.fetchone = lambda: (identifier,)
    repo = AuditRepository(conn)
    repo.engine_available, repo.engine_contract = True, "reason"
    assert repo.revert_change("id", "motif") == identifier
    assert conn.cursor_obj.calls[-1][1] == ("id", "motif")
    assert conn.commits == 1 and conn.autocommit is True


def test_capability_query_checks_permissions_for_each_read_contract():
    conn = Connection()
    conn.cursor_obj.fetchone = lambda: (False, "legacy_field")
    repo = AuditRepository(conn)
    assert not repo.refresh_capabilities()
    sql = conn.cursor_obj.calls[-1][0]
    assert "has_schema_privilege(current_user, 'audit', 'USAGE')" in sql
    assert (
        "has_table_privilege(current_user, to_regclass('audit.v_undo_candidates'), 'SELECT')"
        in sql
    )
    for signature in [
        "audit.fn_undo_caller()",
        "audit.undo_window()",
        "audit.undo_candidates(name,name,uuid,integer)",
        "audit.revert_change(uuid,text)",
        "audit.revert_transaction(uuid,text)",
    ]:
        assert f"to_regprocedure('{signature}'), 'EXECUTE'" in sql
    assert repo.history("wyre", "structures", "record") == []
    assert "audit.v_operator_changes_scoped" in conn.cursor_obj.calls[-1][0]
    assert "audit.fn_undo_caller()" not in conn.cursor_obj.calls[-1][0]
    assert "audit.v_undo_candidates" not in conn.cursor_obj.calls[-1][0]


def test_legacy_view_exposes_in_engine_for_admin_eligibility():
    from plugins.farois_audit_rollback.db.audit_repository import AuditRepository

    repo = AuditRepository(connection=None)
    repo.engine_available, repo.engine_contract = True, "legacy_field"
    assert "u.change_id IS NOT NULL AS in_engine" in repo._history_view()


def test_postgresql_path_still_requires_every_transaction_member_to_have_an_effect():
    # Le chemin PostgreSQL garde sa validation stricte (avant COMMIT) ; seule l'API,
    # qui a déjà commité, se contente d'un membre effectif.
    report = {"changes": [{"reverted": ["label"], "conflicts": []},
                          {"reverted": [], "conflicts": []}]}
    conn = Connection()
    conn.autocommit = True
    conn.cursor_obj.fetchone = lambda: (report,)
    repo = AuditRepository(conn)
    repo.engine_available, repo.engine_contract = True, "legacy_field"
    with pytest.raises(Exception, match="aucune"):
        repo.revert_transaction("tx", "motif")
    assert conn.commits == 0 and conn.rollbacks == 1
