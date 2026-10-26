"""bridge_project_init : styles base (importNamedStyle) et URI des couches.

bridge_project_init est chargé avec les stubs partagés, complétés par des
classes nommées pour ses imports qgis.* que les stubs ne couvrent pas.
Aucun QGIS ni aucune base requis.
"""
import ast
import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

STUBS_DIR = Path(__file__).resolve().parent / "stubs"
MODULE = Path(__file__).resolve().parents[1] / "constructel_bridge" / "bridge_project_init.py"


@pytest.fixture
def project_init(monkeypatch):
    monkeypatch.syspath_prepend(str(STUBS_DIR))
    for name in list(sys.modules):
        if name == "constructel_bridge.bridge_project_init" or name.startswith(
            ("qgis", "constructel_bridge.i18n")
        ):
            monkeypatch.delitem(sys.modules, name)
    for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("qgis")):
            continue
        try:
            module = importlib.import_module(node.module)
        except ImportError:
            module = ModuleType(node.module)
            monkeypatch.setitem(sys.modules, node.module, module)
        for alias in node.names:
            if not hasattr(module, alias.name):
                monkeypatch.setattr(module, alias.name, type(alias.name, (), {}), raising=False)
    module = importlib.import_module("constructel_bridge.bridge_project_init")
    monkeypatch.setattr(
        module,
        "QgsDataSourceUri",
        lambda _uri: SimpleNamespace(
            schema=lambda: "wyre", table=lambda: "cables", geometryColumn=lambda: "geom"
        ),
    )
    monkeypatch.setattr(module, "QDomDocument", lambda: SimpleNamespace(setContent=lambda _xml: True))
    psycopg2 = ModuleType("psycopg2")
    psycopg2.Error = type("Error", (Exception,), {})
    cursor = SimpleNamespace(
        execute=lambda *_args: None, fetchone=lambda: ("<qgis/>",), close=lambda: None
    )
    psycopg2.connect = lambda **_kwargs: SimpleNamespace(cursor=lambda: cursor, close=lambda: None)
    monkeypatch.setitem(sys.modules, "psycopg2", psycopg2)
    return module


def _layer(import_result):
    uri = SimpleNamespace(uri=lambda: 'table="wyre"."cables" (geom)')
    return SimpleNamespace(
        dataProvider=lambda: SimpleNamespace(uri=lambda: uri),
        importNamedStyle=Mock(return_value=import_result),
        triggerRepaint=Mock(),
    )


def test_db_style_applied_is_reported_as_styled(project_init):
    # QGIS renvoie (True, "") en cas de succès.
    layer = _layer((True, ""))
    assert project_init._apply_styles_from_db({}, "pw", {"cables": layer}) == {"cables"}
    layer.triggerRepaint.assert_called_once()


def test_db_style_refused_falls_back_to_embedded_qml(project_init):
    # QGIS renvoie (False, message) en cas d'échec : la couche doit rester
    # candidate au style QML embarqué.
    layer = _layer((False, "Root <qgis> element could not be found"))
    assert project_init._apply_styles_from_db({}, "pw", {"cables": layer}) == set()
    layer.triggerRepaint.assert_not_called()


class _UriWithoutSetSslMode:
    """QgsDataSourceUri de QGIS < 3.42 : setSslMode n'existe pas, le mode SSL
    passe par le 6e argument de setConnection."""

    class SslMode:
        SslPrefer = "prefer"
        SslRequire = "require"

    def __init__(self):
        self.connection = None

    def setConnection(self, *args):
        self.connection = args

    def setDataSource(self, *_args):
        pass

    def setParam(self, *_args):
        pass


@pytest.mark.parametrize(
    "sslmode, expected",
    [("require", "require"), ("prefer", "prefer"), ("", "prefer"), (None, "prefer"),
     ("verify-full", "prefer")],
)
def test_build_uri_sets_sslmode_without_setSslMode(project_init, monkeypatch, sslmode, expected):
    monkeypatch.setattr(project_init, "QgsDataSourceUri", _UriWithoutSetSslMode)
    uri = project_init._build_uri(
        {"host": "h", "port": 5432, "dbname": "db", "user": "u", "sslmode": sslmode},
        "pw", "wyre", "cables", "geom", "id",
    )
    assert uri.connection == ("h", "5432", "db", "u", "pw", expected)


# --- Catalogue : cohérence des clés (couche trench_segments, migration Farois 475)


def test_catalog_keys_wired_consistently(project_init):
    keys = [entry[0] for entry in project_init.LAYER_CATALOG]
    assert len(keys) == len(set(keys))
    styles_dir = MODULE.parent / "styles"
    for key, qml in project_init.EMBEDDED_STYLES.items():
        assert key in keys, key
        assert (styles_dir / qml).is_file(), qml
    rel_names = [rel[3] for rel in project_init.RELATION_DEFS]
    assert len(rel_names) == len(set(rel_names))
    for parent, child, _fk, name in project_init.RELATION_DEFS:
        assert parent in keys and child in keys, name


def test_trench_segments_layer_in_catalog(project_init):
    entry = next(e for e in project_init.LAYER_CATALOG if e[0] == "trench_segments")
    # Aligné sur farois/qgis/_impl_init_project.py (groupe, table, géométrie, clé)
    assert entry[1:6] == ("Infrastructure", "wyre", "trench_segments", "geom", "id")
    assert project_init.EMBEDDED_STYLES["trench_segments"] == "trench_segments.qml"
    assert ("zone_pop", "trench_segments", "zone_pop_id", "trench_segments_to_pop") in (
        project_init.RELATION_DEFS
    )
    # Couche de suivi du génie civil : décochée sauf profils chantier et complet
    profiles = {k for k, t in project_init.TEMPLATES.items() if "trench_segments" in t["layers"]}
    assert profiles == {"infra_chantier", "complet"}


def test_trench_segments_fr_aliases_match_embedded_qml(project_init):
    import xml.etree.ElementTree as ET

    from constructel_bridge.i18n import layer_translations

    qml = ET.parse(MODULE.parent / "styles" / "trench_segments.qml").getroot()
    qml_aliases = {a.get("field"): a.get("name") for a in qml.iter("alias")}
    aliases = layer_translations.FIELD_ALIASES["trench_segments"]
    # Le sketcher remplace les alias du style : en FR, ce sont ceux du QML Farois.
    assert {field: tr["fr"] for field, tr in aliases.items()} == qml_aliases
    assert all(set(tr) == {"fr", "en", "pt"} for tr in aliases.values())
    assert set(layer_translations.LAYER_DISPLAY_NAMES["trench_segments"]) == {"fr", "en", "pt"}


def _trench_qml():
    import xml.etree.ElementTree as ET

    return ET.parse(MODULE.parent / "styles" / "trench_segments.qml").getroot()


def test_trench_segments_form_containers_translated(project_init):
    from constructel_bridge.i18n import layer_translations

    # Onglets et groupes calqués sur ducts.qml : le sketcher les traduit tous
    names = {c.get("name") for c in _trench_qml().iter("attributeEditorContainer")}
    lookup = {
        **layer_translations._FORM_COMMON,
        **layer_translations.FORM_CONTAINERS_PER_LAYER.get("trench_segments", {}),
    }
    assert names and names <= set(lookup)
    assert all(set(lookup[name]) == {"fr", "en", "pt"} for name in names)


def test_trench_segments_status_list_follows_language(project_init):
    from constructel_bridge.i18n import layer_translations

    status = next(
        f for f in _trench_qml().iter("field")
        if f.get("name") == "status" and f.find("editWidget") is not None
    )
    options = {o.get("name"): o.get("value") for o in status.iter("Option")}
    # Liste ref.v_form_lists : le sketcher bascule label_fr / label_en / label_pt
    assert status.find("editWidget").get("type") == "ValueRelation"
    assert options["LayerName"] in layer_translations.VALUE_RELATION_COLUMNS
    assert options["FilterExpression"] == "\"category\" = 'status_trench_segments'"


def test_trench_segments_value_relations_resolvable(project_init):
    import re

    tables = {entry[3] for entry in project_init.LAYER_CATALOG} | {"v_form_lists"}
    for field in _trench_qml().find("fieldConfiguration").findall("field"):
        widget = field.find("editWidget")
        if widget.get("type") != "ValueRelation":
            continue
        options = {o.get("name"): o.get("value") for o in widget.iter("Option")}
        # Nom de table : _sync_value_relation_layer_names le remappe sur le nom traduit
        assert options["LayerName"] in tables, field.get("name")
        # Un champ, pas une expression : QGIS n'évalue pas Value (affichage vide)
        assert re.fullmatch(r"[a-z_]+", options["Value"]), field.get("name")
