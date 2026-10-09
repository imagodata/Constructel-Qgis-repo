"""QGIS source UUID and authentication integration without real connections."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from plugins.farois_audit_rollback.db.qgis_connection import (
    repository_for_layer,
    selected_context,
    layer_context,
)

ID = "00000000-0000-4000-8000-000000000020"


@pytest.fixture
def source(monkeypatch):
    uri = SimpleNamespace(
        schema=lambda: "wyre",
        table=lambda: "roads",
        connectionInfo=Mock(return_value="service=fixture"),
    )
    core = ModuleType("qgis.core")
    core.QgsDataSourceUri = lambda text: uri
    monkeypatch.setitem(sys.modules, "qgis", ModuleType("qgis"))
    monkeypatch.setitem(sys.modules, "qgis.core", core)
    names = ["fid", "id"]

    class Fields:
        def __getitem__(self, i):
            return SimpleNamespace(name=lambda: names[i])

        def indexFromName(self, name):
            return names.index(name) if name in names else -1

    feature = {"fid": 123, "id": ID}
    layer = SimpleNamespace(
        type=lambda: 0,
        providerType=lambda: "postgres",
        selectedFeatureCount=lambda: 1,
        source=lambda: "authcfg=fixture",
        dataProvider=lambda: SimpleNamespace(pkAttributeIndexes=lambda: [0]),
        getSelectedFeatures=lambda: iter([feature]),
        fields=Fields,
    )
    return layer, feature, uri


def test_uses_attribute_uuid_instead_of_numeric_qgis_fid(source):
    layer, _, _ = source
    assert selected_context(layer)[1:] == ("wyre", "roads", ID)


@pytest.mark.parametrize("count", [0, 2])
def test_zero_and_multiple_selection_refused(source, count):
    layer, _, _ = source
    layer.selectedFeatureCount = lambda: count
    with pytest.raises(ValueError, match="exactement un"):
        selected_context(layer)


def test_non_postgres_layer_refused(source):
    layer, _, _ = source
    layer.providerType = lambda: "ogr"
    with pytest.raises(ValueError, match="PostgreSQL"):
        selected_context(layer)


def test_no_uuid_refused(source):
    layer, feature, _ = source
    feature["id"] = 456
    with pytest.raises(ValueError, match="UUID"):
        selected_context(layer)


def test_connection_expands_qgis_auth_and_reads_capabilities(source, monkeypatch):
    layer, _, uri = source
    connection = Mock()
    connection.cursor.return_value.fetchall.return_value = [("id",), ("fid",)]
    connection.cursor.return_value.fetchone.return_value = (False,)
    driver = ModuleType("psycopg2")
    driver.connect = Mock(return_value=connection)
    monkeypatch.setitem(sys.modules, "psycopg2", driver)
    repo = repository_for_layer(layer)
    uri.connectionInfo.assert_called_once_with(True)
    driver.connect.assert_called_once_with("service=fixture", connect_timeout=5)
    assert repo.engine_available is False and connection.autocommit is True
    connection.close.assert_not_called()


def test_connection_error_is_preserved_without_logging_credentials(source, monkeypatch):
    layer, _, _ = source
    driver = ModuleType("psycopg2")
    driver.connect = Mock(side_effect=RuntimeError("connection refused"))
    monkeypatch.setitem(sys.modules, "psycopg2", driver)
    with pytest.raises(RuntimeError, match="connection refused"):
        repository_for_layer(layer)


def test_absent_driver_is_reported(source, monkeypatch):
    layer, _, _ = source
    monkeypatch.setitem(sys.modules, "psycopg2", None)
    with pytest.raises(RuntimeError, match="psycopg2"):
        repository_for_layer(layer)


def test_layer_history_context_works_without_object_selection(source):
    layer, _, _ = source
    layer.selectedFeatureCount = lambda: 0
    assert layer_context(layer)[1:] == ("wyre", "roads", None)


def test_explicit_certificate_parameters_are_preserved(source, monkeypatch):
    layer, _, uri = source
    tls = {
        "sslcert": "fixture-cert.pem",
        "sslkey": "fixture-key.pem",
        "sslrootcert": "fixture-ca.pem",
    }
    uri.hasParam = lambda key: key in tls
    uri.param = lambda key: tls.get(key, "")
    connection = Mock()
    connection.cursor.return_value.fetchall.return_value = [("id",)]
    connection.cursor.return_value.fetchone.return_value = (False,)
    driver = ModuleType("psycopg2")
    driver.connect = Mock(return_value=connection)
    monkeypatch.setitem(sys.modules, "psycopg2", driver)
    repository_for_layer(layer)
    driver.connect.assert_called_once_with("service=fixture", connect_timeout=5, **tls)
