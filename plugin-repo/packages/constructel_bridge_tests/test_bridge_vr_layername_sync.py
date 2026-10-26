"""LayerName des listes de valeurs (ValueRelation) resynchronise apres renommage.

Les styles Farois designent la couche cible par son nom de table (zone_pop,
structures...). _sync_value_relation_layer_names le remplace par le nom
affiche (traduit) de la couche. Constats de revue du 2026-10-26 :
- apres un changement de langue, LayerName vaut l'ancien nom traduit
  (« POP Zones ») : il doit etre reconnu et remappe sur le nouveau nom ;
- les styles par defaut de la base sont reappliques a chaque ouverture de
  projet, Bridge ou non : LayerName revient au nom de table et doit etre
  resynchronise aussitot.
"""

import importlib
import re
import sys
from types import SimpleNamespace

import pytest

from .test_bridge1b_wiring import _FakeIface, bp, credentials_json_present, qgis_stub_path  # noqa: F401


class FakeSetup:
    def __init__(self, widget_type, config):
        self._type, self._config = widget_type, dict(config)

    def type(self):
        return self._type

    def config(self):
        return dict(self._config)


class FakeUri:
    def __init__(self, source):
        match = re.search(r'table="[^"]+"\."([^"]+)"', source)
        self._table = match.group(1) if match else ""

    def table(self):
        return self._table


class FakeLayer:
    def __init__(self, name, table=None, value_relations=()):
        self._name, self._table = name, table
        self._setups = [FakeSetup("ValueRelation", cfg) for cfg in value_relations]

    def name(self):
        return self._name

    def source(self):
        return f'dbname=x table="wyre"."{self._table}" (geom)' if self._table else "memory"

    def dataProvider(self):
        return SimpleNamespace(name=lambda: "postgres" if self._table else "memory")

    def fields(self):
        return SimpleNamespace(count=lambda: len(self._setups))

    def editorWidgetSetup(self, index):
        return self._setups[index]

    def setEditorWidgetSetup(self, index, setup):
        self._setups[index] = setup


@pytest.fixture
def sk(qgis_stub_path, monkeypatch):  # noqa: F811
    for name in list(sys.modules):
        if name.startswith(("qgis", "constructel_bridge.bridge_sketcher", "constructel_bridge.i18n")):
            monkeypatch.delitem(sys.modules, name)
    module = importlib.import_module("constructel_bridge.bridge_sketcher")
    monkeypatch.setattr(module, "QgsVectorLayer", FakeLayer)
    monkeypatch.setattr(module, "QgsDataSourceUri", FakeUri)
    monkeypatch.setattr(module, "QgsEditorWidgetSetup", FakeSetup)
    return module


def _project(*layers):
    return SimpleNamespace(
        mapLayers=lambda: {str(i): layer for i, layer in enumerate(layers)},
        mapLayersByName=lambda name: [layer for layer in layers if layer.name() == name],
    )


def _layer_name(layer):
    return layer.editorWidgetSetup(0).config()["LayerName"]


def test_sync_remaps_table_name_to_current_layer_name(sk):
    ducts = FakeLayer("Conduites", "ducts", [{"LayerName": "zone_pop", "Value": "code"}])
    sk._sync_value_relation_layer_names(_project(FakeLayer("Zones POP", "zone_pop"), ducts))
    assert _layer_name(ducts) == "Zones POP"


def test_sync_remaps_stale_translated_name_after_language_switch(sk):
    # Session ouverte en anglais (LayerName remappe sur « POP Zones »), puis
    # bascule en francais : la couche s'appelle maintenant « Zones POP ».
    ducts = FakeLayer("Conduites", "ducts", [{"LayerName": "POP Zones", "Value": "code"}])
    sk._sync_value_relation_layer_names(_project(FakeLayer("Zones POP", "zone_pop"), ducts))
    assert _layer_name(ducts) == "Zones POP"


def test_sync_leaves_unknown_layer_name_alone(sk):
    ducts = FakeLayer("Conduites", "ducts", [{"LayerName": "Ma couche", "Value": "code"}])
    sk._sync_value_relation_layer_names(_project(FakeLayer("Zones POP", "zone_pop"), ducts))
    assert _layer_name(ducts) == "Ma couche"


def test_sync_keeps_layer_name_that_already_resolves(sk):
    # Meme table chargee deux fois (copie filtree ajoutee apres) : la liste
    # pointe deja sur une couche du projet, elle ne doit pas etre detournee.
    ducts = FakeLayer("ducts", "ducts", [{"LayerName": "zone_pop", "Value": "code"}])
    project = _project(FakeLayer("zone_pop", "zone_pop"), ducts, FakeLayer("zone_pop copie", "zone_pop"))
    sk._sync_value_relation_layer_names(project)
    assert _layer_name(ducts) == "zone_pop"


def test_sync_keeps_translated_name_of_user_layer(sk):
    # Session PT : la couche Farois s'appelle « Estruturas » ; « Structures »
    # est une couche personnelle que la liste cible deja.
    ducts = FakeLayer("Condutas", "ducts", [{"LayerName": "Structures", "Value": "nomenclature"}])
    project = _project(FakeLayer("Estruturas", "structures"), FakeLayer("Structures"), ducts)
    sk._sync_value_relation_layer_names(project)
    assert _layer_name(ducts) == "Structures"


def _plugin_with_one_pg_layer(bp, monkeypatch, events):
    from qgis.core import QgsProject, QgsSettings

    QgsSettings().setValue("constructel_bridge/onboarding_done", True)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())
    uri = SimpleNamespace(schema=lambda: "wyre", table=lambda: "ducts", geometryColumn=lambda: "geom")
    layer = type("PgLayer", (bp.QgsVectorLayer,), {
        "isValid": lambda self: True,
        "providerType": lambda self: "postgres",
        "dataProvider": lambda self: SimpleNamespace(uri=lambda: uri),
        "loadNamedStyle": lambda self, path: events.append("style") or ("", True),
        "triggerRepaint": lambda self: None,
    })()
    QgsProject.instance().addMapLayer(layer)
    cursor = SimpleNamespace(execute=lambda *a: None, fetchone=lambda: ("<qgis/>",), close=lambda: None)
    plugin._conn = SimpleNamespace(cursor=lambda: cursor)
    monkeypatch.setattr(plugin, "_ensure_ref_layers", lambda: None)
    monkeypatch.setattr(
        bp.bridge_sketcher, "_sync_value_relation_layer_names", lambda project: events.append("sync")
    )
    return plugin


def test_default_styles_reload_then_resyncs_layer_names(bp, monkeypatch):  # noqa: F811
    events = []
    plugin = _plugin_with_one_pg_layer(bp, monkeypatch, events)

    plugin._apply_db_default_styles()

    # Le QML de la base remet les LayerName au nom de table : resynchroniser
    # APRES le rechargement, meme hors projet Bridge (_on_project_read
    # s'arrete avant l'i18n)
    assert events == ["style", "sync"]


def test_no_resync_without_connection(bp, monkeypatch):  # noqa: F811
    events = []
    plugin = _plugin_with_one_pg_layer(bp, monkeypatch, events)
    plugin._conn = None

    plugin._apply_db_default_styles()

    # Rien n'a ete recharge : la configuration du projet reste intacte
    assert events == []
