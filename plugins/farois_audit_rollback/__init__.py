"""Farois Audit/Rollback QGIS plugin."""


def classFactory(iface):
    from .plugin import FaroisAuditRollback

    return FaroisAuditRollback(iface)
