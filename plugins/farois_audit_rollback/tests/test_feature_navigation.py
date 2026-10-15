"""Navigation uses only loaded QGIS layers; no database writes or raw SQL."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from plugins.farois_audit_rollback.gui.feature_navigation import (
    find_history_feature,
    matching_layers,
    navigation_target,
    resolve_history_features,
)
from plugins.farois_audit_rollback.gui.history_model import HistoryEntry

ID = "00000000-0000-4000-8000-000000000020"


def entry(**kwargs):
    return HistoryEntry(
        change_id="fixture-change",
        schema_name=kwargs.get("schema", "wyre"),
        table_name=kwargs.get("table", "roads"),
        record_id=kwargs.get("record_id", ID),
        operation=kwargs.get("operation", "UPDATE"),
    )


@pytest.fixture
def navigation(monkeypatch):
    uris = {}

    class Request:
        def setFilterExpression(self, value):
            self.expression = value
            return self

        def setLimit(self, value):
            self.limit = value
            return self

    expression = Mock(side_effect=lambda key, value: (key, value))
    core = ModuleType("qgis.core")
    core.QgsDataSourceUri = lambda source: uris[source]
    core.QgsExpression = SimpleNamespace(createFieldEqualityExpression=expression)
    core.QgsFeatureRequest = Request
    monkeypatch.setitem(sys.modules, "qgis", ModuleType("qgis"))
    monkeypatch.setitem(sys.modules, "qgis.core", core)

    class Feature(dict):
        def id(self):
            return 42

        def isValid(self):
            return True

    def layer(ident, table="roads", database="fixture", names=("fid", "id")):
        field_list = [
            SimpleNamespace(
                name=lambda name=name: name,
                typeName=lambda name=name: "integer" if name == "fid" else "uuid",
            )
            for name in names
        ]

        class Fields:
            def __getitem__(self, index):
                return field_list[index]

            def indexFromName(self, name):
                return names.index(name) if name in names else -1

        uris[ident] = SimpleNamespace(
            schema=lambda: "wyre",
            table=lambda: table,
            host=lambda: "fixture-server",
            port=lambda: "5432",
            database=lambda: database,
            service=lambda: "",
            username=lambda: "fixture-user",
            authConfigId=lambda: "fixture-auth",
        )
        return SimpleNamespace(
            id=lambda: ident,
            source=lambda: ident,
            type=lambda: 0,
            providerType=lambda: "postgres",
            fields=Fields,
            dataProvider=lambda: SimpleNamespace(pkAttributeIndexes=lambda: [0]),
            getFeatures=Mock(return_value=iter([Feature(id=ID, fid=42)])),
        )

    return SimpleNamespace(layer=layer, expression=expression, Feature=Feature)


def test_missing_active_history_row_refused():
    with pytest.raises(ValueError, match="ligne"):
        navigation_target(None)


@pytest.mark.parametrize("value", [None, 42, "not-an-uuid", "'; SELECT 1;--"])
def test_invalid_record_uuid_refused(value):
    with pytest.raises(ValueError, match="UUID"):
        navigation_target(entry(record_id=value))


def test_unvalidated_schema_and_table_refused():
    for row in (entry(schema="public"), entry(table="roads; DROP TABLE x")):
        with pytest.raises(ValueError, match="périmètre"):
            navigation_target(row)


def test_uuid_attribute_resolved_to_qgis_fid_with_bounded_expression(navigation):
    n = navigation
    layer = n.layer("source")
    result_layer, feature = find_history_feature(entry(), layer, [layer])
    assert result_layer is layer and feature.id() == 42
    n.expression.assert_called_once_with("id", ID)
    assert layer.getFeatures.call_args.args[0].limit == 2


def test_other_loaded_table_on_same_connection_can_be_resolved(navigation):
    n = navigation
    source, target = n.layer("source", table="cables"), n.layer("target")
    assert find_history_feature(entry(), source, [source, target])[0] is target
    source.getFeatures.assert_not_called()


def test_same_table_in_different_database_is_never_selected(navigation):
    n = navigation
    source = n.layer("source", table="cables")
    foreign = n.layer("foreign", database="another-fixture")
    with pytest.raises(LookupError, match="connexion"):
        find_history_feature(entry(), source, [foreign])
    foreign.getFeatures.assert_not_called()


def test_source_layer_preferred_over_duplicate_display_layer(navigation):
    n = navigation
    source, duplicate = n.layer("source"), n.layer("duplicate")
    assert find_history_feature(entry(), source, [duplicate])[0] is source
    duplicate.getFeatures.assert_not_called()


def test_ambiguous_layers_require_explicit_source(navigation):
    n = navigation
    source = n.layer("source", table="cables")
    with pytest.raises(LookupError, match="Plusieurs couches"):
        find_history_feature(entry(), source, [n.layer("a"), n.layer("b")])


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_deleted_or_filtered_feature_has_clear_refusal(navigation, operation):
    n = navigation
    source = n.layer("source")
    source.getFeatures.return_value = iter([])
    with pytest.raises(LookupError, match="supprimé, filtré ou hors périmètre"):
        find_history_feature(entry(operation=operation), source, [])


def test_deleted_layer_is_skipped_without_dereferencing(navigation):
    n = navigation
    source = n.layer("source", table="cables")
    deleted = object()
    with pytest.raises(LookupError, match="chargée"):
        find_history_feature(entry(), source, [deleted], lambda obj: obj is deleted)


def test_duplicate_uuid_in_target_refused(navigation):
    n = navigation
    source = n.layer("source")
    source.getFeatures.return_value = iter([n.Feature(id=ID), n.Feature(id=ID)])
    with pytest.raises(LookupError, match="Plusieurs objets"):
        find_history_feature(entry(), source, [])


def test_numeric_primary_key_is_not_compared_to_a_uuid(navigation):
    n = navigation
    source = n.layer("source", names=("fid",))
    with pytest.raises(ValueError, match="clé"):
        find_history_feature(entry(), source, [])
    source.getFeatures.assert_not_called()


def test_no_longer_loaded_source_refused(navigation):
    with pytest.raises(ValueError, match="plus disponible"):
        find_history_feature(entry(), None, [])


def test_batch_deduplicates_multiple_audit_rows_for_same_uuid():
    resolver = Mock(return_value=("layer", "feature"))
    assert resolve_history_features(
        [entry(), entry(operation="INSERT")], "source", [], lambda obj: False, resolver
    ) == [("layer", "feature")]
    assert resolver.call_count == 1


def test_batch_empty_selection_refused():
    with pytest.raises(ValueError, match="lignes"):
        resolve_history_features([], "source", [], lambda obj: False)


def test_batch_preflight_propagates_missing_target():
    resolver = Mock(side_effect=[("layer", "feature"), LookupError("missing")])
    second = entry(record_id="00000000-0000-4000-8000-000000000021")
    with pytest.raises(LookupError, match="missing"):
        resolve_history_features(
            [entry(), second], "source", [], lambda obj: False, resolver
        )


def test_matching_layers_lists_every_loaded_layer_of_the_table_on_the_source_connection(
    navigation,
):
    n = navigation
    source = n.layer("source", table="cables")
    twin, display = n.layer("twin"), n.layer("display")
    foreign = n.layer("foreign", database="another-fixture")
    deleted = object()
    layers = [source, twin, display, foreign, n.layer("other", table="ducts"), deleted]
    found = matching_layers("wyre", "roads", source, layers, lambda obj: obj is deleted)
    assert found == [twin, display]
    assert matching_layers("wyre", "cables", source, layers, lambda obj: obj is deleted) == [source]


def test_matching_layers_requires_a_postgresql_source(navigation):
    with pytest.raises(ValueError, match="plus disponible"):
        matching_layers("wyre", "roads", None, [])
