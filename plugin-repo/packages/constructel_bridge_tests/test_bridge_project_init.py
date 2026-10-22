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
