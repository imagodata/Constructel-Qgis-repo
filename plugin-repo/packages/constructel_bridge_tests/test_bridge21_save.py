"""Bridge 2.1, tache 15 : archive du projet courant et enregistrement en
projet QGIS cote plugin (doublures : aucun QGIS, aucune base)."""
from __future__ import annotations

import io
import os
import zipfile
from types import SimpleNamespace

import pytest

from constructel_bridge import bridge_home_model as hm
from constructel_bridge import bridge_projets as pj
from constructel_bridge import bridge_qgis_store as store
from constructel_bridge.bridge_project_archive import write_project_archive
from constructel_bridge.bridge_qgis_projects import OpenedQgisProject, SharePlan
from constructel_bridge_tests.test_bridge18_layers import _nominal_plugin

ABSOLUTE = "absolute"


def qgz(body="", attrs='saveUser="jdoe" saveDateTime="2026-11-20T09:00:00"'):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bridge_save.qgs", f'<qgis version="3.34" {attrs}><projectlayers>{body}</projectlayers></qgis>')
    return buf.getvalue()


class SaveProject:
    """QgsProject reduit a ce que lit et restaure write_project_archive."""

    def __init__(self, file_name="C:/x/p.qgz", storage="relative", dirty=True, fail=False, api=True):
        self._file, self._storage, self._dirty, self.fail = file_name, storage, dirty, fail
        self.entries = {}
        self.written = []
        if not api:
            self.filePathStorage = None

    def fileName(self):
        return self._file

    def setFileName(self, name):
        self._file = name
        self._dirty = True              # comme QGIS : changer de chemin rend le projet modifie

    def isDirty(self):
        return self._dirty

    def setDirty(self, dirty):
        self._dirty = dirty

    def filePathStorage(self):
        return self._storage

    def setFilePathStorage(self, value):
        self._storage = value

    def readBoolEntry(self, scope, key, default=False):
        return self.entries.get((scope, key), default), (scope, key) in self.entries

    def writeEntry(self, scope, key, value):
        self.entries[(scope, key)] = value
        return True

    def write(self, path):
        self.written.append((path, self._storage, dict(self.entries)))
        self._file = path
        if self.fail:
            return False
        with open(path, "wb") as handle:
            handle.write(qgz())
        return True

    def error(self):
        return "disque plein"


@pytest.fixture(autouse=True)
def absolute(monkeypatch):
    from constructel_bridge import bridge_project_archive as pa

    monkeypatch.setattr(pa, "_absolute_type", lambda: ABSOLUTE)


def test_write_archive_restores_file_name_storage_and_dirty_flag(tmp_path):
    project = SaveProject()
    content = write_project_archive(project, str(tmp_path))
    assert content.startswith(b"PK")
    assert project.written[0][1] == ABSOLUTE                    # ecrit en chemins absolus
    assert (project.fileName(), project.filePathStorage(), project.isDirty()) == ("C:/x/p.qgz", "relative", True)
    assert os.listdir(tmp_path) == []                            # temporaire supprime


def test_write_archive_restores_clean_flag_too(tmp_path):
    project = SaveProject(file_name="", dirty=False)
    write_project_archive(project, str(tmp_path))
    # Sans emplacement : chemin NUL (None), jamais "" -- avec une chaine vide
    # non nulle, la disquette de QGIS tenterait d'ecrire dans « ».
    assert (project.fileName(), project.isDirty()) == (None, False)


def test_write_archive_restores_even_when_write_fails(tmp_path):
    project = SaveProject(fail=True)
    with pytest.raises(OSError):
        write_project_archive(project, str(tmp_path))
    assert (project.fileName(), project.filePathStorage(), project.isDirty()) == ("C:/x/p.qgz", "relative", True)


def test_write_archive_without_storage_api_uses_the_paths_entry(tmp_path):
    project = SaveProject(api=False)
    project.entries[("Paths", "/Absolute")] = False
    write_project_archive(project, str(tmp_path))
    assert project.written[0][2][("Paths", "/Absolute")] is True
    assert project.entries[("Paths", "/Absolute")] is False


# --- plugin -----------------------------------------------------------------------------------

def req(name="Vue", visibility=hm.VISIBILITY_PRIVATE, people=(), projet_id=None, projet_code=None, description="d"):
    return hm.SaveRequest(name, description, projet_id, projet_code, visibility, tuple(people))


@pytest.fixture
def plugin(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsProject

    p = _nominal_plugin(bp18, monkeypatch, tmp_path)
    p._conn = SimpleNamespace(cursor=lambda: (_ for _ in ()).throw(AssertionError("pas de SQL direct")), closed=False)
    p._projet_caps = pj.ProjetCapabilities(True, True, True, True, True, True, True)
    project = QgsProject.instance()
    project._layers = {"l1": SimpleNamespace(id=lambda: "l1")}
    project.setTitle("")
    p.calls = []
    p.archive = qgz()
    monkeypatch.setattr(bp18, "write_project_archive", lambda proj, directory: p.archive)

    def fake_save(conn, name, content, metadata, expected, projet_id, log=None):
        p.calls.append(("save", name, expected, projet_id, dict(metadata)))
        return p.save_outcome

    def fake_share(conn, name, plan, log=None):
        p.calls.append(("share", name, plan))
        return p.share_outcome

    def fake_version(conn, name, log=None):
        p.calls.append(("version", name))
        return p.version

    p.save_outcome = store.StoreOutcome(store.STATUS_OK, value=1)
    p.share_outcome = store.StoreOutcome(store.STATUS_OK, value=1)
    p.version = 7
    monkeypatch.setattr(store, "save", fake_save)
    monkeypatch.setattr(store, "apply_share_plan", fake_share)
    monkeypatch.setattr(store, "current_version", fake_version)
    yield p
    project._layers = {}


def test_save_refused_without_nominative_login_makes_no_query(plugin):
    plugin._auth_mode = "shared"
    assert plugin._save_qgis_project(req()).status == store.STATUS_NOMINATIVE
    assert plugin._overwrite_qgis_project(req()).status == store.STATUS_NOMINATIVE
    assert plugin.calls == []


def test_empty_project_is_refused(plugin):
    from qgis.core import QgsProject

    QgsProject.instance()._layers = {}
    assert plugin._save_qgis_project(req()).status == "empty" and plugin.calls == []


def test_unsafe_project_is_refused_before_any_query(plugin):
    plugin.archive = qgz(
        '<maplayer><layername>Points</layername><attributeactions>'
        '<actionsetting type="1" name="Py" action="x()"/></attributeactions></maplayer>')
    out = plugin._save_qgis_project(req())
    assert out.status == "unsafe" and [f.kind for f in out.value] == ["action"]
    assert plugin.calls == []


def test_too_large_archive_is_refused(plugin, monkeypatch, bp18):
    monkeypatch.setattr(bp18, "MAX_CONTENT_BYTES", 10)
    assert plugin._save_qgis_project(req()).status == "too_large" and plugin.calls == []


def test_archive_write_failure_is_an_error(plugin, monkeypatch, bp18):
    def fail(_project, _directory):
        raise OSError("disque plein")

    monkeypatch.setattr(bp18, "write_project_archive", fail)
    out = plugin._save_qgis_project(req())
    assert out.status == store.STATUS_ERROR and "disque plein" in out.message and plugin.calls == []


def test_save_update_passes_opened_version_and_locked_projet(plugin):
    from qgis.core import QgsProject

    plugin._opened_qgis_project = OpenedQgisProject("Vue", 4, "uuid-g", "GOFIBER", False, True,
                                                    {"qgis_version": "3.34", "last_modified_user": "x"})
    plugin.save_outcome = store.StoreOutcome(store.STATUS_OK, value=5)
    out = plugin._save_qgis_project(req(projet_id=None, visibility=hm.VISIBILITY_PEOPLE, people=(("a.b", True),)))
    assert out.status == store.STATUS_OK and out.value == 5
    (save,) = plugin.calls                               # mise a jour : aucune visibilite appliquee
    # Revue 2.1 (L7) : rattachement fixe en base, jamais renvoye en mise a jour.
    assert save[:4] == ("save", "Vue", 4, None)
    assert save[4] == {"qgis_version": "3.34", "description": "d", "saved_by": "jdoe", "saved_at": "2026-11-20T09:00:00"}
    opened = plugin._opened_qgis_project
    assert opened.version == 5 and not opened.is_owner and opened.projet_id == "uuid-g"
    project = QgsProject.instance()
    assert project.title() == "Vue" and project.dirty is False


def test_save_create_applies_people_visibility_after_version_1(plugin):
    out = plugin._save_qgis_project(req(projet_id="uuid-g", projet_code="GOFIBER", visibility=hm.VISIBILITY_PEOPLE,
                                        people=(("b.x", False), ("a.y", True))))
    assert out.status == store.STATUS_OK and out.value == 1 and out.message == ""
    assert plugin.calls[0][:4] == ("save", "Vue", None, "uuid-g")
    assert plugin.calls[1] == ("share", "Vue", SharePlan(None, (), ("a.y",), ("b.x",)))
    opened = plugin._opened_qgis_project
    assert opened.is_owner and opened.can_edit and opened.version == 1 and opened.projet_code == "GOFIBER"


def test_save_create_projet_visibility_sets_share_project(plugin):
    plugin._save_qgis_project(req(projet_id="uuid-g", projet_code="GOFIBER", visibility=hm.VISIBILITY_PROJET))
    assert plugin.calls[1] == ("share", "Vue", SharePlan(True, (), (), ()))


def test_save_create_private_shares_nothing(plugin):
    plugin._save_qgis_project(req())
    assert [c[0] for c in plugin.calls] == ["save"]


def test_share_refusal_after_create_keeps_the_save(plugin):
    plugin.share_outcome = store.StoreOutcome(store.STATUS_INELIGIBLE, value=0, count=1)
    out = plugin._save_qgis_project(req(visibility=hm.VISIBILITY_PEOPLE, people=(("a.y", False),)))
    assert out.status == store.STATUS_OK and out.value == 1 and out.message == "ineligible" and out.count == 1
    assert plugin._opened_qgis_project is not None


def test_save_conflict_is_returned_and_nothing_changes(plugin):
    plugin.save_outcome = store.StoreOutcome(store.STATUS_CONFLICT, detail="version courante 5")
    out = plugin._save_qgis_project(req())
    assert out.status == store.STATUS_CONFLICT and plugin._opened_qgis_project is None


def test_overwrite_rereads_version_and_reports_deletion(plugin):
    plugin.save_outcome = store.StoreOutcome(store.STATUS_OK, value=8)
    out = plugin._overwrite_qgis_project(req(projet_id="uuid-g"))
    assert out.status == store.STATUS_OK and out.value == 8
    assert plugin.calls[0] == ("version", "Vue") and plugin.calls[1][:4] == ("save", "Vue", 7, None)
    plugin.calls.clear()
    plugin.version = None
    assert plugin._overwrite_qgis_project(req()).status == store.STATUS_GONE
    assert plugin.calls == [("version", "Vue")]


def test_overwrite_never_applies_visibility(plugin):
    plugin.save_outcome = store.StoreOutcome(store.STATUS_OK, value=1)
    plugin._overwrite_qgis_project(req(visibility=hm.VISIBILITY_PEOPLE, people=(("a.y", True),)))
    assert [c[0] for c in plugin.calls] == ["version", "save"]


def test_current_project_state(plugin):
    from qgis.core import QgsProject

    QgsProject.instance().setTitle("Ixelles")
    state = plugin._current_project_state()
    assert state.title == "Ixelles" and state.layer_count == 1 and state.login == plugin._pg_login


def test_update_never_resends_the_attachment_even_if_the_dialog_carries_one(plugin):
    plugin._opened_qgis_project = OpenedQgisProject("Vue", 4, "uuid-g", "GOFIBER", True, True, {})
    plugin.save_outcome = store.StoreOutcome(store.STATUS_OK, value=5)
    plugin._save_qgis_project(req(projet_id="uuid-g"))
    assert plugin.calls[0][3] is None
