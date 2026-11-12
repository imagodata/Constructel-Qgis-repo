"""Bridge 1.9 : operateurs utilisables par la session (plan 2026-11-12,
tache 1, spec § 6.2). Module pur `bridge_operators` + chargement a la
connexion (`_load_operators`) sur doublures, jamais sur une base reelle."""
import pytest

from constructel_bridge import bridge_operators as bo
from constructel_bridge_tests.test_bridge18_connect import (
    _FakeCursor,
    _PgErr,
    _logs,
    _make_plugin,
)

ROWS = [("ORANGE", "Orange", "orange", True), ("PROXIMUS", "Proximus", "proximus", False),
        ("WYRE", "Wyre", "wyre", True)]


def test_parse_operator_rows_keeps_order_and_readability():
    reg = bo.parse_operator_rows(ROWS)
    assert [o.schema for o in reg] == ["orange", "proximus", "wyre"]
    assert reg[1] == bo.OperatorInfo("PROXIMUS", "Proximus", "proximus", False)


def test_parse_operator_rows_drops_unsafe_or_missing_schema():
    assert bo.parse_operator_rows([("X", "X", 'x"; drop', True), ("Y", "Y", None, True)]) == []


@pytest.mark.parametrize("name", ["wyre", "orange_2", "_tmp", "a" * 63])
def test_is_safe_schema_accepts_plain_identifiers(name):
    assert bo.is_safe_schema(name) is True


@pytest.mark.parametrize("name", ["", None, "Wyre", "1wyre", "wy-re", "wyre\n", "a" * 64, 'x"; drop', 42])
def test_is_safe_schema_rejects_everything_else(name):
    assert bo.is_safe_schema(name) is False


@pytest.mark.parametrize("codes", [None, []])
def test_without_scope_codes_only_readable_schemas(codes):
    assert [o.schema for o in bo.usable_operators(bo.parse_operator_rows(ROWS), codes)] == ["orange", "wyre"]


def test_scope_codes_intersect_readable():
    assert [o.schema for o in bo.usable_operators(bo.parse_operator_rows(ROWS), ["WYRE", "PROXIMUS"])] == ["wyre"]


def test_preselect_last_operator_else_first():
    ops = bo.usable_operators(bo.parse_operator_rows(ROWS), None)
    assert bo.preselect_operator(ops, "wyre").schema == "wyre"
    assert bo.preselect_operator(ops, "proximus").schema == "orange"
    assert bo.preselect_operator(ops, "").schema == "orange"
    assert bo.preselect_operator([], "wyre") is None


def test_operators_query_is_guarded():
    q = bo.OPERATORS_QUERY
    assert "o.active IS TRUE" in q and "to_regnamespace(o.schema_name) IS NOT NULL" in q
    assert "has_schema_privilege(to_regnamespace(o.schema_name)::oid, 'USAGE')" in q
    assert q.rstrip().endswith("ORDER BY o.code")


# --- cote plugin : chargement a la connexion ---------------------------------


def test_connect_loads_usable_operators(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(operator_rows=ROWS, operator_codes=["WYRE"])
    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert [o.schema for o in plugin._operators] == ["wyre"]
    assert set(plugin._operator_registry) == {"orange", "proximus", "wyre"}
    assert plugin._operator_registry["wyre"] == bo.OperatorInfo("WYRE", "Wyre", "wyre", True)
    sql = cur.sql()
    assert bo.OPERATORS_QUERY in sql and bo.SCOPE_CODES_QUERY in sql


def test_scope_codes_not_executable_falls_back_to_readable(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(operator_rows=ROWS,
                      operator_codes=_PgErr("permission denied for function current_gis_operator_codes"))
    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert [o.schema for o in plugin._operators] == ["orange", "wyre"]


def test_scope_codes_null_for_admin_falls_back_to_readable(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(operator_rows=ROWS, operator_codes=None)
    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert [o.schema for o in plugin._operators] == ["orange", "wyre"]


def test_operators_query_failure_never_blocks_connection(bp18, monkeypatch, tmp_path):
    from qgis.core import Qgis

    cur = _FakeCursor(operator_rows=_PgErr("permission denied for table operateurs"))
    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert plugin._connected is True and plugin._operators == [] and plugin._operator_registry == {}
    ours = [m for m in _logs(Qgis.MessageLevel.Warning) if "Liste des operateurs indisponible" in m]
    assert ours and not any("illisible" in m for m in ours)  # mot filtre par un test 1.8.4


def test_operators_are_loaded_in_shared_mode_too(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(operator_rows=ROWS)
    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur,
                              memorized="shared", ask=("shared-pw", False))

    plugin._connect("shared-pw", silent=True)

    assert plugin._auth_mode == "shared"
    assert [o.schema for o in plugin._operators] == ["orange", "wyre"]
