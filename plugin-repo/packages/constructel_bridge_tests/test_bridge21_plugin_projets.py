"""Bridge 2.1, tache 9 : capacites du schema `projet` et projets metier lus a
la connexion (doublures, jamais de base reelle)."""
from __future__ import annotations

import pytest

from constructel_bridge import bridge_projets as pj
from constructel_bridge_tests.test_bridge18_connect import _FakeCursor, _PgErr, _logs, _make_plugin
from constructel_bridge_tests.test_bridge18_layers import pi  # noqa: F401  (fixture)
from constructel_bridge_tests.test_bridge19_browser_projects import (  # noqa: F401  (fixtures)
    fake_cursor,
    plugin,
    settings,
)


def _snapshot(plugin_):
    """home_snapshot sans le Check-in (extensions, Resource Sharing)."""
    plugin_._home_plugin_summary = lambda: None
    plugin_._home_checkin_state = lambda _summary: None
    return plugin_.home_snapshot()

ALL_CAPS = ([("r", "projets", True), ("r", "projet_couches", True), ("r", "projet_tables", True), ("r", "qgis_projects", True)]
            + [("f", n, True) for n in pj.CAPABILITY_FUNCTIONS])
GOFIBER_ROWS = [("b3", "GOFIBER", "GoFiber", "WYRE", "geofiber_points", "Points", None, None, "geom", 1)]


class _ProjetCursor(_FakeCursor):
    """_FakeCursor 1.8/1.9 + capacites (CAPABILITIES_QUERY) et registre
    (PROJETS_QUERY) ; une Exception en *caps* ou *projets* est levee."""

    def __init__(self, caps=ALL_CAPS, projets=GOFIBER_ROWS, **kw):
        super().__init__(**kw)
        self.caps = caps
        self.projets = projets

    def execute(self, sql, params=None):
        if sql == pj.CAPABILITIES_QUERY:
            self.executed.append((sql, params))
            self._one, self._all = None, []
            if isinstance(self.caps, Exception):
                raise self.caps
            self._all = list(self.caps)
            return
        if sql == pj.PROJETS_QUERY:
            self.executed.append((sql, params))
            self._one, self._all = None, []
            if isinstance(self.projets, Exception):
                raise self.projets
            self._all = list(self.projets)
            return
        super().execute(sql, params)


def _connected(bp18, monkeypatch, tmp_path, **kw):
    cur = _ProjetCursor(**kw)
    plugin_, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")
    plugin_._auto_connect()
    assert plugin_._connected
    return plugin_, cur


def test_connect_reads_capabilities_then_projets(bp18, monkeypatch, tmp_path):
    from constructel_bridge import bridge_operators as bo

    plugin_, cur = _connected(bp18, monkeypatch, tmp_path)
    sql = cur.sql()
    i_ops, i_caps, i_projets = sql.index(bo.OPERATORS_QUERY), sql.index(pj.CAPABILITIES_QUERY), sql.index(pj.PROJETS_QUERY)
    assert i_ops < i_caps < i_projets
    assert plugin_._projet_caps.qgis_projects and [p.code for p in plugin_._projets] == ["GOFIBER"]
    assert any("Projets metier visibles : GOFIBER" in m for m in _logs())


def test_capabilities_absent_schema_hides_everything(bp18, monkeypatch, tmp_path, pi):
    shown = []
    from qgis.PyQt.QtWidgets import QMessageBox

    for name in ("critical", "warning", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: shown.append(a)))
    plugin_, cur = _connected(bp18, monkeypatch, tmp_path, caps=[])
    assert pj.PROJETS_QUERY not in cur.sql()
    assert plugin_._projet_caps == pj.NO_CAPABILITIES and plugin_._projets == ()
    snapshot = _snapshot(plugin_)
    assert snapshot.projets == () and not snapshot.capabilities.registry and shown == []
    assert any("Projets metier visibles : aucun" in m for m in _logs())


def test_registry_error_is_logged_never_raised(bp18, monkeypatch, tmp_path):
    plugin_, _cur = _connected(bp18, monkeypatch, tmp_path, projets=_PgErr("permission denied for table projets"))
    assert plugin_._connected and plugin_._projets == () and plugin_._projet_caps.registry
    assert any("permission denied for table projets" in m for m in _logs())


def test_capabilities_error_is_logged_never_raised(bp18, monkeypatch, tmp_path):
    plugin_, cur = _connected(bp18, monkeypatch, tmp_path, caps=_PgErr("canceling statement"))
    assert plugin_._connected and plugin_._projet_caps == pj.NO_CAPABILITIES
    assert pj.PROJETS_QUERY not in cur.sql()


def test_snapshot_carries_projets_capabilities_and_nominative(bp18, monkeypatch, tmp_path, pi):
    plugin_, _cur = _connected(bp18, monkeypatch, tmp_path)
    snapshot = _snapshot(plugin_)
    assert [p.code for p in snapshot.projets] == ["GOFIBER"] and snapshot.capabilities.save
    assert snapshot.nominative is True and snapshot.opened_qgis_project is None
    assert ("WYRE", "Wyre") in snapshot.operator_code_labels


def test_snapshot_offline_has_no_projets_and_no_capabilities(plugin, pi):  # noqa: F811
    plugin._projet_caps = pj.ProjetCapabilities(True, True, True)
    plugin._projets = (pj.ProjetInfo("b3", "GOFIBER", "GoFiber", None, ()),)
    plugin._connected = False
    snapshot = _snapshot(plugin)
    assert snapshot.projets == () and snapshot.capabilities == pj.NO_CAPABILITIES and snapshot.nominative is False


def test_shared_session_is_not_nominative(plugin, pi):  # noqa: F811
    plugin._auth_mode = "shared"
    plugin._pg_login = ""
    assert _snapshot(plugin).nominative is False


def test_projet_schema_exists_reads_no_database(plugin):
    def boom():
        raise AssertionError("aucune requete attendue")

    plugin._conn.cursor = boom
    assert plugin._projet_schema_exists() is False
    plugin._projet_caps = pj.ProjetCapabilities(qgis_table=True)
    assert plugin._projet_schema_exists() is True


def test_disconnect_forgets_projets(bp18, plugin, monkeypatch):
    monkeypatch.setattr(bp18, "unregister_expressions", lambda: None)
    plugin._projet_caps = pj.ProjetCapabilities(True, True, True)
    plugin._projets = (pj.ProjetInfo("b3", "GOFIBER", "GoFiber", None, ()),)
    plugin._conn.close = lambda: None
    plugin.unload()
    assert plugin._projet_caps == pj.NO_CAPABILITIES and plugin._projets == ()
