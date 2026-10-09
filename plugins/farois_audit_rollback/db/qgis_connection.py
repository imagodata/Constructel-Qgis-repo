"""Reuse a source layer's QGIS PostgreSQL credentials, including authcfg/service."""

from uuid import UUID

from .audit_repository import AuditRepository, IdentifierPolicy
from .errors import AuditRepositoryError


def selected_context(layer):
    from qgis.core import QgsDataSourceUri

    if layer is None or layer.type() != 0 or layer.providerType() != "postgres":
        raise ValueError("Choisissez une couche PostgreSQL.")
    if layer.selectedFeatureCount() != 1:
        raise ValueError("Sélectionnez exactement un objet dans la couche source.")
    uri = QgsDataSourceUri(layer.source())
    feature = next(layer.getSelectedFeatures())
    fields = layer.fields()
    indexes = list(layer.dataProvider().pkAttributeIndexes())
    if len(indexes) != 1:
        raise ValueError("La couche doit exposer une clé primaire simple.")
    key_name = fields[indexes[0]].name()
    # Farois audit identifies records by UUID, not by QGIS' numeric feature id.
    candidates = [key_name]
    if fields.indexFromName("id") >= 0 and key_name != "id":
        candidates.append("id")
    for name in candidates:
        try:
            record_id = str(UUID(str(feature[name])))
        except (ValueError, TypeError, AttributeError):
            continue
        IdentifierPolicy(allowed_tables={uri.table()}, allowed_columns={name}).validate(
            uri.schema(), uri.table(), name
        )
        return layer, uri.schema(), uri.table(), record_id
    raise ValueError(
        "Aucune clé UUID Farois n'est disponible dans les attributs sélectionnés."
    )


def layer_context(layer):
    from qgis.core import QgsDataSourceUri

    if layer is None or layer.type() != 0 or layer.providerType() != "postgres":
        raise ValueError("Choisissez une couche PostgreSQL.")
    uri = QgsDataSourceUri(layer.source())
    IdentifierPolicy(allowed_tables={uri.table()}).validate(uri.schema(), uri.table())
    return layer, uri.schema(), uri.table(), None


def repository_for_layer(layer):
    from qgis.core import QgsDataSourceUri

    try:
        import psycopg2
    except ImportError as exc:
        raise AuditRepositoryError(
            "Le Python de QGIS doit disposer de psycopg2 pour réutiliser la connexion PostgreSQL."
        ) from exc
    uri = QgsDataSourceUri(layer.source())
    # Expansion is performed only in memory by QGIS' authentication manager.
    # Never persist or log this connection string.
    tls = {}
    if hasattr(uri, "hasParam"):
        # QGIS connectionInfo excludes generic URI parameters, including explicit
        # certificate paths. Keep these when the provider source carries them.
        for key in (
            "sslcert",
            "sslkey",
            "sslrootcert",
            "sslcrl",
            "sslcrldir",
            "passfile",
        ):
            if uri.hasParam(key):
                value = uri.param(key)
                if value:
                    tls[key] = value
    connection = psycopg2.connect(uri.connectionInfo(True), connect_timeout=5, **tls)
    connection.autocommit = True
    try:
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT a.attname FROM pg_catalog.pg_attribute a "
                "JOIN pg_catalog.pg_class c ON c.oid = a.attrelid "
                "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relname = %s "
                "AND c.relkind IN ('r', 'p', 'v', 'm', 'f') "
                "AND a.attnum > 0 AND NOT a.attisdropped",
                (uri.schema(), uri.table()),
            )
            columns = {row[0] for row in cursor.fetchall()}
        finally:
            cursor.close()
        if not columns:
            raise AuditRepositoryError(
                "La table source n'est pas disponible dans cette connexion."
            )
        repository = AuditRepository(
            connection,
            IdentifierPolicy(allowed_tables={uri.table()}, allowed_columns=columns),
        )
        repository.refresh_capabilities()
        return repository
    except Exception:
        connection.close()
        raise
