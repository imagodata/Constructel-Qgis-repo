# -*- coding: utf-8 -*-
"""
Constructel Bridge - Plugin QGIS pour connexion WYRE FTTH et tracking utilisateur.
"""


def classFactory(iface):
    from .bridge_plugin import ConstructelBridgePlugin
    return ConstructelBridgePlugin(iface)
