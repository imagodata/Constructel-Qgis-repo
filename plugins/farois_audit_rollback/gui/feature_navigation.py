"""Resolve an audit UUID in an already loaded, same-connection QGIS layer."""

from uuid import UUID

from ..db.audit_repository import IdentifierPolicy
from ..db.errors import InvalidIdentifierError


def navigation_target(entry):
    if entry is None:
        raise ValueError("Sélectionnez une ligne de l'historique.")
    try:
        IdentifierPolicy().validate(entry.schema_name, entry.table_name)
    except InvalidIdentifierError as exc:
        raise ValueError(
            "La table de cette entrée est hors périmètre de navigation."
        ) from exc
    try:
        record_id = str(UUID(str(entry.record_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(
            "Cette entrée ne fournit pas d'UUID d'objet exploitable."
        ) from exc
    return entry.schema_name, entry.table_name, record_id


def _connection_key(uri):
    # No authentication expansion, passwords, logs or automatic connections.
    return tuple(
        getattr(uri, name)()
        for name in ("host", "port", "database", "service", "username", "authConfigId")
    )


def matching_layers(schema, table, source_layer, layers, is_deleted=lambda obj: False):
    """Couches PostgreSQL chargées sur schema.table, avec la connexion de la source."""
    from qgis.core import QgsDataSourceUri

    if source_layer is None or is_deleted(source_layer):
        raise ValueError("La couche source n'est plus disponible.")
    if source_layer.type() != 0 or source_layer.providerType() != "postgres":
        raise ValueError("Choisissez une couche source PostgreSQL.")
    source_key = _connection_key(QgsDataSourceUri(source_layer.source()))
    candidates = []
    seen = set()
    for layer in [source_layer, *layers]:
        if layer is None or is_deleted(layer):
            continue
        if layer.type() != 0 or layer.providerType() != "postgres":
            continue
        if layer.id() in seen:
            continue
        seen.add(layer.id())
        uri = QgsDataSourceUri(layer.source())
        if (uri.schema(), uri.table()) != (schema, table):
            continue
        if _connection_key(uri) == source_key:
            candidates.append(layer)
    return candidates


def find_history_feature(entry, source_layer, layers, is_deleted=lambda obj: False):
    from qgis.core import QgsExpression, QgsFeatureRequest

    schema, table, record_id = navigation_target(entry)
    candidates = matching_layers(schema, table, source_layer, layers, is_deleted)
    if not candidates:
        raise LookupError(
            "Aucune couche PostgreSQL chargée ne correspond à la table et à la "
            "connexion de cette entrée. Chargez sa couche source."
        )
    if source_layer in candidates:
        candidates = [source_layer]
    if len(candidates) != 1:
        raise LookupError(
            "Plusieurs couches correspondent : choisissez la couche cible comme "
            "couche source du panneau."
        )
    layer = candidates[0]
    fields = layer.fields()
    names = ["id"] if fields.indexFromName("id") >= 0 else []
    indexes = list(layer.dataProvider().pkAttributeIndexes())
    if len(indexes) == 1:
        key = fields[indexes[0]].name()
        if key not in names:
            names.append(key)
    names = [
        name
        for name in names
        if fields[fields.indexFromName(name)].typeName().lower()
        in {"uuid", "text", "varchar", "character varying", "string", "qstring"}
    ]
    if not names:
        raise ValueError("La couche n'expose pas de clé d'objet utilisable.")
    policy = IdentifierPolicy(allowed_tables={table}, allowed_columns=set(names))
    for name in names:
        policy.validate(schema, table, name)
        # Expression is constructed by QGIS, never SQL or user-provided text.
        expression = QgsExpression.createFieldEqualityExpression(name, record_id)
        request = QgsFeatureRequest().setFilterExpression(expression).setLimit(2)
        features = list(layer.getFeatures(request))
        matches = []
        for feature in features:
            try:
                ident = str(UUID(str(feature[name])))
            except (ValueError, TypeError, AttributeError):
                continue
            if ident == record_id and feature.isValid():
                matches.append(feature)
        if len(matches) > 1:
            raise LookupError("Plusieurs objets portent cet UUID ; sélection refusée.")
        if matches:
            return layer, matches[0]
    raise LookupError(
        "Objet introuvable dans la couche : supprimé, filtré ou hors périmètre. "
        "Ses valeurs historiques restent consultables dans l'audit."
    )


def resolve_history_features(entries, source_layer, layers, is_deleted, resolver=None):
    """Resolve every target before changing selection, and deduplicate audit rows."""
    resolver = resolver or find_history_feature
    layers = list(layers)
    seen, targets = set(), []
    if not entries:
        raise ValueError("Sélectionnez une ou plusieurs lignes de l'historique.")
    for entry in entries:
        key = navigation_target(entry)
        if key in seen:
            continue
        seen.add(key)
        targets.append(resolver(entry, source_layer, layers, is_deleted))
    return targets
