"""Bridge 2.1, tache 14 : neutralisation de TOUT projet ouvert depuis la base
par le Bridge (le sien compris) et projet QGIS ouvert retenu (doublures)."""
from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace

import pytest

from constructel_bridge import bridge_projets as pj
from constructel_bridge import bridge_qgis_store as store
from constructel_bridge.bridge_qgis_projects import QgisProjectRow
from constructel_bridge_tests.fakes19 import WYRE
from constructel_bridge_tests.test_bridge18_layers import _XmlCursor, _nominal_plugin, _our_source

EMBEDDED = (
    "<qgis><properties><Macros><pythonCode>import os; os.system('x')</pythonCode></Macros>"
    "<ExpressionFunctions><pythonCode>def f(): pass</pythonCode></ExpressionFunctions></properties>"
    "<projectlayers><maplayer><id>l1</id><layername>Points</layername><datasource>"
    + _our_source(password="x") +
    "</datasource><attributeactions><actionsetting type=\"1\" name=\"Py\" action=\"run()\"/></attributeactions>"
    "<editforminit>open_form</editforminit><editforminitcodesource>2</editforminitcodesource>"
    "<editforminitcode>def open_form(): pass</editforminitcode></maplayer></projectlayers></qgis>"
)


def qgz(xml):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("vue.qgs", xml)
    return buf.getvalue()


def row(name="Vue", **kw):
    base = dict(owner="jdoe", projet_id="a0b1", projet_code="GOFIBER", projet_label="GoFiber", share_project=False,
                published=False, owner_role="BE", version=4, updated_at=None, updated_by="jdoe", is_owner=True,
                can_edit=True, share_count=0, description="d")
    base.update(kw)
    return QgisProjectRow(name=name, **base)


@pytest.fixture
def plugin(bp18, monkeypatch, tmp_path):
    from qgis.PyQt.QtWidgets import QMessageBox

    p = _nominal_plugin(bp18, monkeypatch, tmp_path)
    p._operators = [WYRE]
    p._projet_caps = pj.ProjetCapabilities(True, True, True, True, True, True, True)
    p.boxes = []
    for name in ("critical", "warning", "information"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: p.boxes.append(a[2] if len(a) > 2 else a)))
    return p


def _serve_projet(plugin, monkeypatch, content=None, missing=False, version=4):
    reads = []

    def fake(conn, name):
        reads.append(name)
        if missing:
            return None
        return store.OpenRow(content if content is not None else qgz(EMBEDDED), {"description": "d"}, version, "a0b1")

    monkeypatch.setattr(store, "read_for_open", fake)
    plugin._conn = SimpleNamespace(cursor=lambda: (_ for _ in ()).throw(AssertionError("pas de SQL direct")), closed=False)
    return reads


def _bar(plugin):
    return [m[2] for m in plugin.iface.messageBar().messages]


def test_open_neutralizes_own_project_too(bp18, plugin, monkeypatch):
    from qgis.core import QgsProject

    _serve_projet(plugin, monkeypatch)
    assert plugin._open_qgis_project(row(is_owner=True)) is True
    xml = QgsProject.instance().read_xml
    for needle in ("os.system", "def f()", 'name="Py"', "open_form", "password='x'"):
        assert needle not in xml
    assert any(m == bp18.tr("project.neutralized", count=5) for m in _bar(plugin))


def test_legacy_schema_project_is_neutralized_too(bp18, plugin):
    from qgis.core import QgsProject

    plugin._conn = SimpleNamespace(cursor=lambda: _XmlCursor(EMBEDDED), closed=False)
    assert plugin._read_and_clean_project(QgsProject.instance(), "wyre", "ref") is True
    xml = QgsProject.instance().read_xml
    assert "os.system" not in xml and 'name="Py"' not in xml
    assert any(m == bp18.tr("project.neutralized", count=5) for m in _bar(plugin))


def test_clean_project_xml_is_untouched_before_authcfg_cleaning(bp18, plugin, monkeypatch):
    from qgis.core import QgsProject

    xml = "<qgis><projectlayers><maplayer><datasource>dbname='x' host=elsewhere.invalid table=\"a\".\"b\"</datasource></maplayer></projectlayers></qgis>"
    plugin._conn = SimpleNamespace(cursor=lambda: _XmlCursor(xml), closed=False)
    assert plugin._read_and_clean_project(QgsProject.instance(), "wyre", "ref") is True
    assert QgsProject.instance().read_xml == xml          # serveur tiers : rien a nettoyer, aucune reserialisation
    assert not any("neutralis" in m for m in _bar(plugin))


def test_entity_declaration_is_refused_and_never_read(bp18, plugin, monkeypatch):
    from qgis.core import QgsProject

    project = QgsProject.instance()
    project.read_xml = "avant"
    _serve_projet(plugin, monkeypatch, content=qgz('<!DOCTYPE qgis [<!ENTITY a "b">]><qgis>&a;</qgis>'))
    assert plugin._open_qgis_project(row()) is False
    assert project.read_xml == "avant"
    assert plugin.boxes == [bp18.tr("project.unsafe_refused", name="Vue")]
    assert plugin._opened_qgis_project is None


def test_opened_record_set_after_read_and_cleared_on_new_project(bp18, plugin, monkeypatch):
    from qgis.core import QgsProject

    _serve_projet(plugin, monkeypatch, version=7)
    project = QgsProject.instance()
    real_read = project.read

    def read_emitting_cleared(path):
        plugin._on_project_cleared()          # QGIS vide le projet avant de le lire
        return real_read(path)

    monkeypatch.setattr(project, "read", read_emitting_cleared)
    assert plugin._open_qgis_project(row(is_owner=False, can_edit=True)) is True
    opened = plugin._opened_qgis_project
    assert (opened.name, opened.version, opened.projet_id, opened.projet_code) == ("Vue", 7, "a0b1", "GOFIBER")
    assert opened.can_edit and not opened.is_owner and opened.metadata == {"description": "d"}
    plugin._on_project_cleared()                # Projet > Nouveau
    assert plugin._opened_qgis_project is None


def test_open_invisible_projet_row_reports_not_found(bp18, plugin, monkeypatch):
    _serve_projet(plugin, monkeypatch, missing=True)
    assert plugin._open_qgis_project(row()) is False
    assert plugin._opened_qgis_project is None and len(plugin.boxes) == 1
    assert "Vue" in plugin.boxes[0]


def test_projet_read_error_is_reported_never_raised(bp18, plugin, monkeypatch):
    def boom(conn, name):
        raise RuntimeError("permission denied for table qgis_projects")

    monkeypatch.setattr(store, "read_for_open", boom)
    assert plugin._open_qgis_project(row()) is False and len(plugin.boxes) == 1


def test_cleared_signal_is_connected_and_disconnected(bp18, monkeypatch):
    from qgis.core import QgsProject
    from constructel_bridge_tests.test_bridge18_connect import _initgui_ready, _install_psycopg2, _FakeCursor

    iface = _initgui_ready(bp18, monkeypatch)
    _install_psycopg2(monkeypatch, [None], _FakeCursor())
    plugin = bp18.ConstructelBridgePlugin(iface)
    plugin.initGui()
    assert plugin._on_project_cleared in QgsProject.instance().cleared._slots
    plugin.unload()
    assert plugin._on_project_cleared not in QgsProject.instance().cleared._slots


def test_oversized_qgs_is_never_decompressed(bp18, plugin, monkeypatch):
    # Revue 2.1 (M4) : bombe ZIP, refus avant zf.read.
    monkeypatch.setattr(bp18, "MAX_QGS_BYTES", 10)
    _serve_projet(plugin, monkeypatch)
    assert plugin._open_qgis_project(row()) is False
    assert plugin.boxes == [bp18.tr("project.unsafe_refused", name="Vue")]
