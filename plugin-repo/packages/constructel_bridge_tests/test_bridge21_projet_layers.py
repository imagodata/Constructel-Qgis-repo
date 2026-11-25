"""Bridge 2.1, tache 10 : chargement des couches declarees d'un projet metier
(bridge_project_init). Doublures fakes19, aucun QGIS ni aucune base."""
from __future__ import annotations

from constructel_bridge import bridge_projets as pj
from constructel_bridge_tests.fakes19 import FakeLayer, install_fake_project
from constructel_bridge_tests.test_bridge18_layers import pi  # noqa: F401  (fixture)
from constructel_bridge_tests.test_bridge19_reorganize import _names
from constructel_bridge_tests.test_bridge_project_init import project_init  # noqa: F401  (fixture)

GROUP = "Profondeur As-Built"
GOFIBER = pj.ProjetInfo("b3", "GOFIBER", "GoFiber", "WYRE", (
    pj.ProjetLayer("geofiber_connectors", "Connecteurs", GROUP, "default", "geom", 10),
    pj.ProjetLayer("geofiber_points", "Points", GROUP, "gofiber_points", "geom", 20),
    pj.ProjetLayer("geofiber_meta", "Métadonnées", None, "default", None, 30),
))
ALL = {"geofiber_connectors", "geofiber_points", "geofiber_meta"}


def _projet_layers(project):
    return [ly for ly in project.mapLayers().values() if project.schema_of(ly.id()) == "projet"]


def test_projet_layers_go_in_a_marked_root_group_before_common(pi, monkeypatch):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    pi.ensure_common_group(root)
    assert pi.load_projet_layers({}, "", GOFIBER, ALL, apply_styles=False) == 3
    assert _names(root) == ["GoFiber", "Commun"]
    group = root.children()[0]
    assert group.customProperty(pi.PROJET_GROUP_PROPERTY) == "GOFIBER"
    assert _names(group) == [GROUP, "Métadonnées"]
    assert _names(group.children()[0]) == ["Connecteurs", "Points"]


def test_operator_group_added_later_sits_before_the_projet_group(pi, monkeypatch):  # noqa: F811
    from constructel_bridge_tests.fakes19 import WYRE

    project = install_fake_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    pi.load_projet_layers({}, "", GOFIBER, ALL, apply_styles=False)
    pi.ensure_common_group(root)
    pi.ensure_operator_group(root, WYRE)
    assert _names(root) == ["Wyre", "GoFiber", "Commun"]


def test_projet_layers_keep_sort_order_and_labels(pi, monkeypatch):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)
    pi.load_projet_layers({}, "", GOFIBER, {"geofiber_points", "geofiber_connectors"}, apply_styles=False)
    layers = _projet_layers(project)
    assert sorted(ly.name() for ly in layers) == ["Connecteurs", "Points"]
    adds = [e[1] for e in project.events if e[0] == "add"]
    names = [project.mapLayer(i).name() for i in adds]
    assert names == ["Connecteurs", "Points"]


def test_attribute_table_without_geometry_is_loaded(pi, monkeypatch):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)
    assert pi.load_projet_layers({}, "", GOFIBER, {"geofiber_meta"}, apply_styles=False) == 1
    (layer,) = _projet_layers(project)
    assert layer.name() == "Métadonnées" and "(geom)" not in layer.source()


def test_already_loaded_projet_table_is_never_reloaded_or_restyled(pi, monkeypatch):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)
    project.add_pg("projet", "geofiber_points", "Mes points")
    styled = []
    monkeypatch.setattr(pi, "_apply_styles_from_db", lambda _p, _pw, loaded, style_names=None: styled.append(dict(style_names)) or set())
    assert pi.load_projet_layers({}, "", GOFIBER, ALL, apply_styles=True) == 2
    assert project.count_pg("projet", "geofiber_points") == 1
    assert styled == [{"projet:geofiber_connectors": "default", "projet:geofiber_meta": "default"}]
    assert pi.existing_projet_tables(project) == ALL


def test_projet_load_never_stamps_operator_nor_suffix(pi, monkeypatch):  # noqa: F811
    install_fake_project(pi, monkeypatch)
    stamps = []
    monkeypatch.setattr(pi, "stamp_project", lambda *a, **k: stamps.append(a))
    pi.load_projet_layers({}, "", GOFIBER, ALL, apply_styles=False)
    info = pi.get_bridge_info()
    assert stamps == [] and info["operators"] == [] and info["version"] == pi.WYRE_PROJECT_VERSION


def test_invalid_layer_is_logged_and_skipped(pi, monkeypatch):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)

    class Invalid(FakeLayer):
        def __init__(self, source="", name="", provider="postgres"):
            super().__init__(source, name, provider)
            self.valid = "geofiber_points" not in source

    monkeypatch.setattr(pi, "QgsVectorLayer", Invalid)
    assert pi.load_projet_layers({}, "", GOFIBER, ALL, apply_styles=False) == 2
    assert project.count_pg("projet", "geofiber_points") == 0


def test_projet_style_uses_style_name(project_init, monkeypatch):  # noqa: F811
    pi = project_init
    import sys
    from types import SimpleNamespace

    from constructel_bridge_tests.fakes19 import FakeUri
    from constructel_bridge_tests.test_bridge19_retarget import _StyleCursor

    monkeypatch.setattr(pi, "QgsDataSourceUri", FakeUri)
    cursor = _StyleCursor({("projet", "geofiber_points", "geom", "gofiber_points"): "<qgis/>"})
    executed = []
    real = cursor.execute
    cursor.execute = lambda sql, params=(): executed.append(sql) or real(sql, params)
    connection = SimpleNamespace(cursor=lambda: cursor, close=lambda: None)
    fake_pg = SimpleNamespace(connect=lambda **_kw: connection, Error=type("Error", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "psycopg2", fake_pg)
    layer = FakeLayer.pg("projet", "geofiber_points", "Points")
    styled = pi._apply_styles_from_db({}, "pw", {"projet:geofiber_points": layer},
                                      style_names={"projet:geofiber_points": "gofiber_points"})
    assert styled == {"projet:geofiber_points"}
    assert cursor.params == [("projet", "geofiber_points", "geom", "gofiber_points")]
    assert "stylename = %s" in executed[0]


def test_count_loaded_layers_counts_projet_layers(pi, monkeypatch):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)
    pi.load_projet_layers({}, "", GOFIBER, ALL, apply_styles=False)
    project.add_pg("wyre", "cables")
    counts = pi.count_loaded_layers(project, {"wyre"})
    assert counts.projet == 3 and counts.per_operator == {"wyre": 1} and counts.common == 0


def test_projet_table_named_like_an_operator_table_is_not_an_operator(pi, monkeypatch):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)
    project.add_pg("projet", "cables")
    counts = pi.count_loaded_layers(project)
    assert counts.projet == 1 and counts.per_operator == {}


def test_projet_group_is_not_moved_by_reorganize(pi, monkeypatch):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)
    chantier = pj.ProjetInfo("c", "CHANTIER_X", "Chantier", None, (pj.ProjetLayer("t", "T", None, "default", "geom", 0),))
    pi.load_projet_layers({}, "", chantier, {"t"}, apply_styles=False)
    root = project.layerTreeRoot()
    assert _names(root) == ["Chantier"] and not pi.needs_reorganization(root)


# --- Bridge 2.2 : tables de projet dans le schema du registre (Farois mig 596) ---------

DATA = pj.ProjetInfo("b3", "GOFIBER", "GoFiber", "WYRE", (
    pj.ProjetLayer("geofiber_connectors", "Connecteurs", GROUP, "default", "geom", 10, "data"),
    pj.ProjetLayer("geofiber_points", "Points", GROUP, "gofiber_points", "geom", 20, "data"),
))
DATA_SCHEMAS = {"geofiber_connectors": "data", "geofiber_points": "data"}


def test_existing_reconnait_projet_et_data(pi, monkeypatch):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)
    project.add_pg("data", "geofiber_connectors")
    project.add_pg("projet", "geofiber_points")          # ancienne source, transition
    project.add_pg("data", "autre_table")                # hors registre : ignoree
    project.add_pg("wyre", "geofiber_meta")              # autre schema : ignoree
    assert pi.existing_projet_tables(project, DATA_SCHEMAS) == {"geofiber_connectors", "geofiber_points"}
    # Sans registre : seul projet.<t> compte (comportement 2.1).
    assert pi.existing_projet_tables(project) == {"geofiber_points"}
    # Deja chargee dans projet ou data : jamais rechargee.
    assert pi.load_projet_layers({}, "", DATA, {"geofiber_connectors", "geofiber_points"}, apply_styles=False) == 0


def test_loaded_counts_data(pi, monkeypatch):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)
    project.add_pg("data", "geofiber_connectors")
    project.add_pg("projet", "geofiber_points")
    project.add_pg("data", "autre_table")
    project.add_pg("wyre", "cables")
    counts = pi.count_loaded_layers(project, {"wyre"}, DATA_SCHEMAS)
    assert counts.projet == 2 and counts.per_operator == {"wyre": 1} and counts.common == 0
    assert pi.count_loaded_layers(project, {"wyre"}).projet == 1


def test_uri_couche_dans_data(pi, monkeypatch):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)
    styled = []

    def spy(_p, _pw, loaded, style_names=None):
        styled.append({key: project.schema_of(layer.id()) for key, layer in loaded.items()})
        return set()

    monkeypatch.setattr(pi, "_apply_styles_from_db", spy)
    assert pi.load_projet_layers({}, "", DATA, {"geofiber_connectors", "geofiber_points"}, apply_styles=True) == 2
    assert project.count_pg("data", "geofiber_points") == 1 and project.count_pg("projet", "geofiber_points") == 0
    assert '"data"."geofiber_points"' in project.pg_layers("data", "geofiber_points")[0].source()
    # Style cherche dans le schema de la couche (URI data), cle projet:<t> inchangee.
    assert styled == [{"projet:geofiber_connectors": "data", "projet:geofiber_points": "data"}]
