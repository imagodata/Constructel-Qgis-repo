"""Bridge 2.2, tache 8 : a l'ouverture d'un projet, une couche PostgreSQL
``projet.<t>`` dont le registre place ``<t>`` dans un autre schema (``data``
apres la mig Farois 596) est repointee vers ce schema, en memoire. Doublures :
stub qgis.core, aucune base ni QGIS."""
from __future__ import annotations

import importlib
import sys

import pytest


@pytest.fixture
def br(bp18, monkeypatch):
    """bridge_relocate importe sur le stub qgis.core charge par bp18."""
    monkeypatch.delitem(sys.modules, "constructel_bridge.bridge_relocate", raising=False)
    return importlib.import_module("constructel_bridge.bridge_relocate")


SCHEMAS = {
    "geofiber_asbuilt_depth_points": "data",
    "geofiber_asbuilt_depth_segments": "data",
    "geofiber_meta": "projet",                 # registre avant la 596 : rien a faire
}


# --- relocation_targets (pure) -------------------------------------------------------


def test_cible_seulement_projet_vers_data(br):
    layers = [
        ("l1", "projet", "geofiber_asbuilt_depth_points"),
        ("l2", "data", "geofiber_asbuilt_depth_segments"),     # deja dans data
        ("l3", "projet", "geofiber_meta"),                     # registre : projet
    ]
    assert br.relocation_targets(layers, SCHEMAS) == [("l1", "data")]


def test_autre_schema_intouche(br):
    layers = [
        ("l1", "wyre", "geofiber_asbuilt_depth_points"),       # copie dans un schema operateur
        ("l2", "public", "geofiber_asbuilt_depth_points"),
        ("l3", "", "geofiber_asbuilt_depth_points"),           # requete SQL, sans schema
        ("l4", "projet", "qgis_projects"),                     # table hors registre
    ]
    assert br.relocation_targets(layers, SCHEMAS) == []


def test_registre_vide_rien(br):
    layers = [("l1", "projet", "geofiber_asbuilt_depth_points")]
    assert br.relocation_targets(layers, {}) == []
    assert br.relocation_targets(layers, None) == []


def test_nom_prolonge_intouche(br):
    layers = [
        ("l1", "projet", "geofiber_asbuilt_depth_points_old"),
        ("l2", "projet", "geofiber_asbuilt_depth_point"),
        ("l3", "projet", "GEOFIBER_ASBUILT_DEPTH_POINTS"),
    ]
    assert br.relocation_targets(layers, SCHEMAS) == []


# --- relocate_project_layers (stub qgis.core) ----------------------------------------


def _layer_class(br):
    class _Layer(br.QgsVectorLayer):
        def __init__(self, source, name, provider="postgres"):
            super().__init__(source, name, provider)
            self._layer_id = name
            self.calls = []

        def providerType(self):
            return self._provider_type

        def dataProvider(self):
            return None                # couche invalide apres la 596 : source() fait foi

        def setDataSource(self, source, name, provider, *args):
            self.calls.append((source, name, provider))
            self._source = source

    return _Layer


class _Project:
    def __init__(self, layers):
        self._layers = {ly.id(): ly for ly in layers}

    def mapLayers(self):
        return dict(self._layers)


def _pg(br, schema, table, name):
    return _layer_class(br)(f"dbname='farois_ftth' host=db.example port=5432 user='u' key='id' "
                  f"table=\"{schema}\".\"{table}\"", name)


def test_relocate_repointe_en_memoire_et_compte(br):
    moved = _pg(br, "projet", "geofiber_asbuilt_depth_points", "Points")
    other = _pg(br, "projet", "geofiber_asbuilt_depth_points_old", "Ancien")
    done = _pg(br, "data", "geofiber_asbuilt_depth_segments", "Segments")
    wfs = _layer_class(br)("typename='projet:geofiber_asbuilt_depth_points'", "Wfs", provider="WFS")
    project = _Project([moved, other, done, wfs])
    assert br.relocate_project_layers(project, SCHEMAS) == 1
    ((source, name, provider),) = moved.calls
    assert '"data"."geofiber_asbuilt_depth_points"' in source and "host=db.example" in source
    assert (name, provider) == ("Points", "postgres")
    assert other.calls == [] and done.calls == [] and wfs.calls == []


def test_relocate_registre_illisible_aucune_modification(br):
    moved = _pg(br, "projet", "geofiber_asbuilt_depth_points", "Points")
    assert br.relocate_project_layers(_Project([moved]), {}) == 0
    assert moved.calls == []


# --- branchement dans le plugin --------------------------------------------------------


def test_plugin_repointe_apres_les_credentials(bp18, monkeypatch):
    import inspect
    from types import SimpleNamespace

    from constructel_bridge import bridge_projets as pj

    bp = bp18
    src = inspect.getsource(bp.ConstructelBridgePlugin._on_project_read)
    assert src.index("self._fix_layer_credentials()") < src.index("self._relocate_projet_layers()")
    hooks = inspect.getsource(bp.ConstructelBridgePlugin._apply_project_hooks)
    assert hooks.index("self._fix_layer_credentials()") < hooks.index("self._relocate_projet_layers()")

    calls, logs = [], []
    monkeypatch.setattr(bp, "relocate_project_layers", lambda project, schemas: calls.append(dict(schemas)) or 2)
    data = pj.ProjetInfo("b3", "GOFIBER", "GoFiber", "WYRE", (
        pj.ProjetLayer("geofiber_asbuilt_depth_points", "Points", None, "default", "geom", 1, "data"),))
    plugin = SimpleNamespace(_projets=(data,), _log=lambda msg, *a: logs.append(msg))
    assert bp.ConstructelBridgePlugin._relocate_projet_layers(plugin) == 2
    assert calls == [{"geofiber_asbuilt_depth_points": "data"}] and any("data" in m for m in logs)


def test_plugin_sans_registre_ne_touche_a_rien(bp18, monkeypatch):
    from types import SimpleNamespace

    bp = bp18
    calls = []
    monkeypatch.setattr(bp, "relocate_project_layers", lambda project, schemas: calls.append(schemas) or 0)
    plugin = SimpleNamespace(_projets=(), _log=lambda *a: None)
    assert bp.ConstructelBridgePlugin._relocate_projet_layers(plugin) == 0
    assert calls == []
