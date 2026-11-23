"""Disquette et Ctrl+S d'un projet QGIS ouvert ou enregistre en base par le
Bridge : stockage de projet ``constructel-bridge:`` (doublures : aucun QGIS,
aucune base)."""
from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace

import pytest

from constructel_bridge import bridge_db_save as dbs
from constructel_bridge import bridge_home_model as hm
from constructel_bridge import bridge_projets as pj
from constructel_bridge import bridge_qgis_store as store
from constructel_bridge.bridge_qgis_projects import OpenedQgisProject, QgisProjectRow
from constructel_bridge_tests.fakes19 import WYRE
from constructel_bridge_tests.test_bridge18_layers import _nominal_plugin


def qgz(body="", attrs='saveUser="jdoe" saveDateTime="2026-11-23T09:00:00"'):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Vue.qgs", f'<qgis version="3.44" {attrs}><projectlayers>{body}</projectlayers></qgis>')
    return buf.getvalue()


def row(name="Vue", **kw):
    base = dict(owner="jdoe", projet_id="a0b1", projet_code="GOFIBER", projet_label="GoFiber", share_project=False,
                published=False, owner_role="BE", version=4, updated_at=None, updated_by="jdoe", is_owner=True,
                can_edit=True, share_count=0, description="d")
    base.update(kw)
    return QgisProjectRow(name=name, **base)


class Context:
    def __init__(self):
        self.messages = []

    def pushMessage(self, message, level=None):  # noqa: N802
        self.messages.append(message)


class Device:
    def __init__(self, data):
        self._data = data

    def readAll(self):  # noqa: N802
        return SimpleNamespace(data=lambda: self._data)


# --- URI ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Vue", "Vue Ixelles / lot 2", "a:b%c", "Référence GoFiber"])
def test_uri_round_trip(name):
    uri = dbs.bridge_uri(name)
    assert uri.startswith("constructel-bridge:projet/") and "/" not in uri[len("constructel-bridge:projet/"):]
    assert dbs.is_bridge_uri(uri) and dbs.name_from_uri(uri) == name


@pytest.mark.parametrize("uri", ["", None, "C:/x/p.qgz", "postgresql://h?schema=wyre&project=p",
                                 "/tmp/constructel-bridge:projet/x"])
def test_other_locations_are_not_bridge_uris(uri):
    assert not dbs.is_bridge_uri(uri) and dbs.name_from_uri(uri) is None


def test_clear_file_name_gives_a_null_path_not_an_empty_one():
    seen = []
    dbs.clear_file_name(SimpleNamespace(setFileName=seen.append))
    assert seen == [None]                 # '' = chaine vide NON nulle : QGIS ecrirait dans « »


# --- stockage -----------------------------------------------------------------------------------

def _storage(bp18, writer):
    return dbs.storage_class()(writer)


def test_storage_write_hands_the_archive_to_the_writer(bp18):
    calls = []
    storage = _storage(bp18, lambda uri, data: calls.append((uri, data)) or (True, ""))
    context = Context()
    assert storage.writeProject("constructel-bridge:projet/Vue", Device(b"PK.."), context) is True
    assert calls == [("constructel-bridge:projet/Vue", b"PK..")] and context.messages == []
    assert storage.type() == "constructel-bridge" and storage.listProjects("x") == []
    assert storage.removeProject("x") is False


def test_storage_refusal_message_goes_to_qgis_dialog(bp18):
    storage = _storage(bp18, lambda uri, data: (False, "conflit"))
    context = Context()
    assert storage.writeProject("u", Device(b"PK"), context) is False
    assert context.messages == ["conflit"]


def test_storage_writer_exception_never_reaches_qgis(bp18):
    def boom(uri, data):
        raise RuntimeError("panne")

    context = Context()
    assert _storage(bp18, boom).writeProject("u", Device(b"PK"), context) is False
    assert "panne" in context.messages[0]


def test_storage_never_reads_a_project(bp18):
    context = Context()
    assert _storage(bp18, None).readProject("constructel-bridge:projet/Vue", Device(b""), context) is False
    assert context.messages == [bp18.tr("disquette.open_via_bridge")]


def test_unloaded_storage_refuses_to_write(bp18):
    storage = _storage(bp18, lambda *a: (True, ""))
    dbs.unregister_storage(storage)
    context = Context()
    assert storage.writeProject("u", Device(b"PK"), context) is False and context.messages


def test_register_replaces_a_stale_storage_and_unregister_removes_it(bp18):
    from qgis.core import QgsApplication

    registry = QgsApplication.projectStorageRegistry()
    first = dbs.register_storage(lambda *a: (True, ""))
    second = dbs.register_storage(lambda *a: (True, ""))
    assert registry.projectStorageFromType("constructel-bridge") is second and first is not second
    dbs.unregister_storage(second)
    assert registry.projectStorageFromType("constructel-bridge") is None


def test_register_without_storage_api_returns_none(bp18, monkeypatch):
    from qgis.core import QgsApplication

    monkeypatch.delattr(QgsApplication, "projectStorageRegistry")
    logs = []
    assert dbs.register_storage(lambda *a: (True, ""), log=logs.append) is None and logs


# --- plugin -------------------------------------------------------------------------------------

@pytest.fixture
def plugin(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsProject

    p = _nominal_plugin(bp18, monkeypatch, tmp_path)
    p._operators = [WYRE]
    p._conn = SimpleNamespace(cursor=lambda: (_ for _ in ()).throw(AssertionError("pas de SQL direct")), closed=False)
    p._projet_caps = pj.ProjetCapabilities(True, True, True, True, True, True, True)
    p._db_storage = dbs.register_storage(p._save_from_storage)
    project = QgsProject.instance()
    project._layers = {"l1": SimpleNamespace(id=lambda: "l1")}
    p.calls = []
    p.save_outcome = store.StoreOutcome(store.STATUS_OK, value=5)

    def fake_save(conn, name, content, metadata, expected, projet_id, log=None):
        p.calls.append(("save", name, expected, projet_id, dict(metadata)))
        return p.save_outcome

    def fake_version(conn, name, log=None):
        p.calls.append(("version", name))
        return 9

    def fake_read(conn, name):
        return store.OpenRow(qgz(), {"description": "ma vue", "qgis_version": "3.44"}, 4, "a0b1")

    monkeypatch.setattr(store, "save", fake_save)
    monkeypatch.setattr(store, "current_version", fake_version)
    monkeypatch.setattr(store, "read_for_open", fake_read)
    monkeypatch.setattr(bp18, "write_project_archive", lambda proj, directory: qgz())
    yield p
    project._layers = {}


def _bar(plugin):
    return [m[2] for m in plugin.iface.messageBar().messages]


def _disquette(plugin, content=None):
    """Ce que fait QGIS a la disquette : QgsProject.write -> stockage."""
    from qgis.core import QgsApplication, QgsProject

    project = QgsProject.instance()
    storage = QgsApplication.projectStorageRegistry().projectStorageFromType("constructel-bridge")
    project.setDirty(False)                    # zip() a deja remis le projet « non modifie »
    context = Context()
    saved = storage.writeProject(project.fileName(), Device(content if content is not None else qgz()), context)
    return saved, context.messages


def test_opening_an_editable_projet_project_gives_it_its_db_location(plugin):
    from qgis.core import QgsProject

    assert plugin._open_qgis_project(row()) is True
    project = QgsProject.instance()
    assert project.fileName() == dbs.bridge_uri("Vue") and project.isDirty() is False
    assert project.title() == "Vue"


def test_disquette_saves_in_db_with_the_version_read_at_opening(bp18, plugin):
    from qgis.core import QgsProject

    plugin._open_qgis_project(row())
    saved, messages = _disquette(plugin)
    assert saved is True and messages == []
    (save,) = plugin.calls                     # jamais de relecture de version : pas d'ecrasement
    assert save[:4] == ("save", "Vue", 4, None)
    assert save[4]["description"] == "ma vue" and save[4]["qgis_version"] == "3.44"
    assert save[4]["saved_by"] == "jdoe" and "source_file" not in save[4]
    assert plugin._opened_qgis_project.version == 5
    assert QgsProject.instance().isDirty() is False
    assert bp18.tr("save.done", name="Vue", version=5) in _bar(plugin)
    plugin.save_outcome = store.StoreOutcome(store.STATUS_OK, value=6)
    _disquette(plugin)                         # disquette suivante : version 5
    assert plugin.calls[-1][2] == 5


def test_conflict_overwrites_nothing_and_keeps_the_work(bp18, plugin):
    from qgis.core import QgsProject

    plugin._open_qgis_project(row())
    plugin.save_outcome = store.StoreOutcome(store.STATUS_CONFLICT, detail="version courante 6")
    saved, messages = _disquette(plugin)
    assert saved is False and messages == [bp18.tr("disquette.conflict", name="Vue")]
    assert [c[0] for c in plugin.calls] == ["save"]          # aucun « Ecraser » implicite
    assert plugin._opened_qgis_project.version == 4
    assert QgsProject.instance().isDirty() is True            # la fermeture demandera encore
    assert QgsProject.instance().fileName() == dbs.bridge_uri("Vue")


def test_read_only_shared_project_gets_an_explicit_message_and_no_query(bp18, plugin):
    from qgis.core import QgsProject

    plugin._open_qgis_project(row(is_owner=False, can_edit=False))
    assert QgsProject.instance().fileName() == dbs.bridge_uri("Vue")
    saved, messages = _disquette(plugin)
    assert saved is False and messages == [bp18.tr("disquette.read_only", name="Vue")]
    assert plugin.calls == [] and QgsProject.instance().isDirty() is True


def test_shared_with_edit_right_saves(plugin):
    plugin._open_qgis_project(row(is_owner=False, can_edit=True))
    assert _disquette(plugin)[0] is True and plugin.calls[0][2] == 4


def test_project_forgotten_after_clear_is_never_written(bp18, plugin):
    plugin._open_qgis_project(row())
    plugin._on_project_cleared()               # Nouveau, ouverture d'un autre projet
    saved, messages = _disquette(plugin)
    assert saved is False and messages == [bp18.tr("disquette.detached", name="Vue")]
    assert plugin.calls == []


def test_other_name_than_the_opened_project_is_never_written(bp18, plugin):
    from qgis.core import QgsProject

    plugin._open_qgis_project(row())
    QgsProject.instance().setFileName(dbs.bridge_uri("Autre"))
    saved, messages = _disquette(plugin)
    assert saved is False and plugin.calls == []


def test_unsafe_archive_is_refused_before_any_query(bp18, plugin):
    plugin._open_qgis_project(row())
    unsafe = qgz('<maplayer><layername>Points</layername><attributeactions>'
                 '<actionsetting type="1" name="Py" action="x()"/></attributeactions></maplayer>')
    saved, messages = _disquette(plugin, unsafe)
    assert saved is False and plugin.calls == []
    assert bp18.tr("save.unsafe_intro") in messages[0] and "Points" in messages[0]


def test_lost_nominative_session_is_refused_before_any_query(bp18, plugin):
    plugin._open_qgis_project(row())
    plugin._auth_mode = "shared"
    saved, messages = _disquette(plugin)
    assert saved is False and plugin.calls == [] and bp18.tr("save.nominative") in messages[0]


def test_closed_connection_is_refused(bp18, plugin):
    plugin._open_qgis_project(row())
    plugin._conn = SimpleNamespace(closed=True)
    saved, messages = _disquette(plugin)
    assert saved is False and plugin.calls == [] and messages


def test_deleted_project_message_suggests_another_name(bp18, plugin):
    plugin._open_qgis_project(row())
    plugin.save_outcome = store.StoreOutcome(store.STATUS_GONE)
    saved, messages = _disquette(plugin)
    assert saved is False and bp18.tr("save.gone") in messages[0]


def test_operator_schema_project_keeps_native_save_as(bp18, plugin):
    from qgis.core import QgsProject
    from constructel_bridge_tests.test_bridge18_layers import _XmlCursor

    plugin._conn = SimpleNamespace(cursor=lambda: _XmlCursor("<qgis></qgis>"), closed=False)
    assert plugin._open_db_project("wyre", "ref") is True
    assert QgsProject.instance().fileName() is None      # chemin nul : « Enregistrer sous » natif


def test_without_storage_the_opened_project_keeps_native_save_as(plugin):
    from qgis.core import QgsProject

    dbs.unregister_storage(plugin._db_storage)
    plugin._db_storage = None
    plugin._open_qgis_project(row())
    assert QgsProject.instance().fileName() is None


def test_bridge_save_button_makes_the_project_a_db_project(plugin):
    from qgis.core import QgsProject

    plugin.save_outcome = store.StoreOutcome(store.STATUS_OK, value=1)
    out = plugin._save_qgis_project(hm.SaveRequest("Neuve", "desc", None, None, hm.VISIBILITY_PRIVATE, ()))
    assert out.status == store.STATUS_OK
    project = QgsProject.instance()
    assert project.fileName() == dbs.bridge_uri("Neuve") and project.isDirty() is False
    plugin.calls.clear()
    plugin.save_outcome = store.StoreOutcome(store.STATUS_OK, value=2)
    assert _disquette(plugin)[0] is True
    assert plugin.calls[0][:4] == ("save", "Neuve", 1, None)
    assert plugin.calls[0][4]["description"] == "desc"


def test_bridge_button_never_stores_the_bridge_uri_as_source_file(plugin):
    plugin._open_qgis_project(row())
    plugin._save_qgis_project(hm.SaveRequest("Vue", "d", None, None, hm.VISIBILITY_PRIVATE, ()))
    assert "source_file" not in plugin.calls[0][4]


def test_failed_bridge_button_keeps_the_previous_location(plugin):
    from qgis.core import QgsProject

    plugin._open_qgis_project(row())
    plugin.save_outcome = store.StoreOutcome(store.STATUS_CONFLICT)
    plugin._save_qgis_project(hm.SaveRequest("Autre", "d", None, None, hm.VISIBILITY_PRIVATE, ()))
    assert QgsProject.instance().fileName() == dbs.bridge_uri("Vue")


def test_deleting_the_opened_project_detaches_it(plugin, monkeypatch):
    from qgis.core import QgsProject

    plugin._open_qgis_project(row())
    QgsProject.instance().setDirty(True)
    monkeypatch.setattr(store, "delete", lambda conn, name, log=None: store.StoreOutcome(store.STATUS_OK))
    plugin._delete_qgis_project("Vue")
    project = QgsProject.instance()
    assert project.fileName() is None and project.isDirty() is True


def test_initgui_registers_the_storage_and_unload_restores_native_save(bp18, monkeypatch):
    from qgis.core import QgsApplication, QgsProject
    from constructel_bridge_tests.test_bridge18_connect import _FakeCursor, _initgui_ready, _install_psycopg2

    iface = _initgui_ready(bp18, monkeypatch)
    _install_psycopg2(monkeypatch, [None], _FakeCursor())
    plugin = bp18.ConstructelBridgePlugin(iface)
    plugin.initGui()
    registry = QgsApplication.projectStorageRegistry()
    assert registry.projectStorageFromType("constructel-bridge") is plugin._db_storage is not None
    project = QgsProject.instance()
    project.setFileName(dbs.bridge_uri("Vue"))
    project.setDirty(True)
    plugin.unload()
    assert registry.projectStorageFromType("constructel-bridge") is None and plugin._db_storage is None
    assert project.fileName() is None and project.isDirty() is True


def test_unload_leaves_a_local_project_alone(bp18, monkeypatch):
    from qgis.core import QgsProject
    from constructel_bridge_tests.test_bridge18_connect import _FakeCursor, _initgui_ready, _install_psycopg2

    iface = _initgui_ready(bp18, monkeypatch)
    _install_psycopg2(monkeypatch, [None], _FakeCursor())
    plugin = bp18.ConstructelBridgePlugin(iface)
    plugin.initGui()
    QgsProject.instance().setFileName("C:/x/p.qgz")
    plugin.unload()
    assert QgsProject.instance().fileName() == "C:/x/p.qgz"
