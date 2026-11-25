"""Bridge 2.2 : repointage, a l'ouverture d'un projet, des couches de projet
metier deplacees par la migration Farois 596 (schema `projet` -> `data`).

Un projet QGIS enregistre avant la 596 (en base ou `.qgz` local) garde des
couches PostgreSQL ``"projet"."<table>"``. Si le registre
(`projet.projet_tables.schema_name`, lu a la connexion : ProjetLayer.schema)
place ``<table>`` dans un autre schema, la couche est repointee vers ce schema,
EN MEMOIRE : le projet n'est ecrit que si la personne l'enregistre.

- Seules les couches ``projet.<t>`` dont le registre donne un autre schema
  pour ``<t>`` (nom exact) sont touchees ; une table hors registre, une couche
  d'un autre schema, une requete SQL ou une couche non PostgreSQL ne le sont
  jamais.
- Registre illisible (pas de scope PROJET, base sans registre, hors
  connexion) : ``schemas`` vide, aucune modification.
"""
from __future__ import annotations

from typing import Iterable, List, Mapping, Optional, Tuple

from qgis.core import QgsDataProvider, QgsDataSourceUri, QgsVectorLayer

# Schema d'origine des tables de projet metier (avant la mig Farois 596).
LEGACY_SCHEMA = "projet"


def relocation_targets(layer_tables: Iterable[Tuple[str, str, str]],
                       schemas: Optional[Mapping[str, str]]) -> List[Tuple[str, str]]:
    """``(layer_id, schema, table)`` -> ``(layer_id, nouveau_schema)`` pour les
    seules couches ``projet.<t>`` dont le registre place ``<t>`` ailleurs.
    PURE ; ordre d'entree conserve."""
    schemas = schemas or {}
    targets = []
    for layer_id, schema, table in layer_tables:
        if schema != LEGACY_SCHEMA:
            continue
        target = schemas.get(table)
        if target and target != LEGACY_SCHEMA:
            targets.append((layer_id, target))
    return targets


def _layer_uri(layer):
    """``QgsDataSourceUri`` d'une couche PostgreSQL, valide ou non (couche
    invalide apres la 596 : pas de fournisseur, la source fait foi)."""
    provider = layer.dataProvider()
    if provider:
        return QgsDataSourceUri(provider.uri().uri())
    return QgsDataSourceUri(layer.source())


def relocate_project_layers(project, schemas: Optional[Mapping[str, str]]) -> int:
    """Repointe en memoire les couches de *project* vers le schema du registre
    (*schemas* : table -> schema, voir projet_layer_schemas). Retourne le
    nombre de couches repointees ; *schemas* vide : 0, rien n'est touche."""
    if not schemas:
        return 0
    layers = {}
    uris = {}
    rows = []
    for layer_id, layer in project.mapLayers().items():
        if not isinstance(layer, QgsVectorLayer) or layer.providerType() != "postgres":
            continue
        uri = _layer_uri(layer)
        layers[layer_id] = layer
        uris[layer_id] = uri
        rows.append((layer_id, uri.schema(), uri.table()))
    moved = 0
    for layer_id, schema in relocation_targets(rows, schemas):
        uri = uris[layer_id]
        uri.setSchema(schema)
        layer = layers[layer_id]
        layer.setDataSource(uri.uri(False), layer.name(), "postgres", QgsDataProvider.ProviderOptions())
        moved += 1
    return moved
