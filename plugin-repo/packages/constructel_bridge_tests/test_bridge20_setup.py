"""Bridge 2.0, tache 10 (plan 2026-11-18, spec § 6.5 et § 8.4) : le setup n'est
plus rejoue apres une mise a jour.

- ``initGui`` n'efface plus ``onboarding_done`` au changement de version, il
  garde seulement ``plugin_version`` a jour ;
- rattrapage ponctuel (cle ``ONBOARDING_CATCHUP_KEY``) : un poste deja installe
  (``plugin_version`` anterieure) est considere comme configure ;
- un poste vierge et un nouvel utilisateur ont toujours l'assistant, ouvert
  dans la fenetre (``_on_home("checkin", start_wizard=True)``).
"""
from __future__ import annotations

from constructel_bridge_tests.test_bridge18_connect import (
    LOGIN,
    _FakeCursor,
    _initgui_ready,
    _install_psycopg2,
)

DONE = "constructel_bridge/onboarding_done"
VERSION = "constructel_bridge/plugin_version"


def _gui(bp18, monkeypatch, *, stored_version=None, done=None):
    """Plugin demarre par ``initGui`` ; retourne (plugin, iface, QgsSettings)."""
    from qgis.core import QgsSettings

    settings = QgsSettings()
    for key, value in ((VERSION, stored_version), (DONE, done)):
        if value is None:
            settings.remove(key)
        else:
            settings.setValue(key, value)
    iface = _initgui_ready(bp18, monkeypatch)
    _install_psycopg2(monkeypatch, [None], _FakeCursor())
    assert bp18._store_password_encrypted("ad-pw", "ad", username=LOGIN)
    plugin = bp18.ConstructelBridgePlugin(iface)
    plugin._get_qgis_username = lambda: "JDoe"
    plugin.initGui()
    return plugin, iface, settings


def test_catchup_key_name(bp18):
    assert bp18.ONBOARDING_CATCHUP_KEY == "constructel_bridge/onboarding_catchup_2_0"


def test_update_no_longer_clears_onboarding_done(bp18, monkeypatch):
    plugin, _iface, settings = _gui(bp18, monkeypatch, stored_version="1.9.0", done=True)
    assert settings.value(DONE, False) is True
    assert settings.value(VERSION) == "2.0.0" == bp18.PLUGIN_VERSION
    plugin.unload()


def test_catchup_marks_setup_done_once_for_existing_install(bp18, monkeypatch):
    plugin, iface, settings = _gui(bp18, monkeypatch, stored_version="1.9.0")   # 1.9 : indicateur efface
    assert settings.value(DONE, False) is True
    assert settings.value(bp18.ONBOARDING_CATCHUP_KEY, False) is True
    plugin.unload()

    # Second demarrage : plus aucun effet (l'indicateur remis a faux le reste).
    settings.remove(DONE)
    plugin2 = bp18.ConstructelBridgePlugin(iface)
    plugin2._get_qgis_username = lambda: "JDoe"
    plugin2.initGui()
    assert settings.value(DONE, False) is False
    assert settings.value(VERSION) == "2.0.0"
    plugin2.unload()


def test_fresh_install_still_gets_the_wizard(bp18, monkeypatch):
    plugin, iface, settings = _gui(bp18, monkeypatch)                 # aucune plugin_version
    assert settings.value(DONE, None) is None                         # pas de rattrapage
    assert settings.value(VERSION) == "2.0.0"
    assert settings.value(bp18.ONBOARDING_CATCHUP_KEY, False) is True    # joue une fois, sans effet
    opened = []
    plugin._on_home = lambda *a, **k: opened.append((a, k))

    iface.initializationCompleted.emit()

    assert plugin._connected is True
    assert opened == [(("checkin",), {"start_wizard": True})]
    assert not hasattr(plugin, "_run_onboarding")
    plugin.unload()


def test_catchup_survives_a_rollback_to_1_9(bp18, monkeypatch):
    # Revue finale : 2.0 -> 1.9 (qui efface onboarding_done et reecrit
    # plugin_version) -> 2.0.x : rattrapage rejoue malgre la cle deja posee.
    plugin, iface, settings = _gui(bp18, monkeypatch, stored_version="1.9.0")
    assert settings.value(DONE, False) is True
    assert settings.value(bp18.ONBOARDING_CATCHUP_KEY, False) is True
    plugin.unload()

    settings.setValue(VERSION, "1.9.0")      # la 1.9 a tourne entre-temps
    settings.remove(DONE)
    plugin2 = bp18.ConstructelBridgePlugin(iface)
    plugin2._get_qgis_username = lambda: "JDoe"
    plugin2.initGui()
    assert settings.value(DONE, False) is True
    assert settings.value(VERSION) == "2.0.0"
    opened = []
    plugin2._on_home = lambda *a, **k: opened.append((a, k))
    iface.initializationCompleted.emit()
    assert opened == []                      # pas d'assistant
    plugin2.unload()


def test_unfinished_setup_on_a_2_0_install_still_gets_the_wizard(bp18, monkeypatch):
    # Rattrapage deja joue, assistant jamais termine : il s'ouvre encore.
    from qgis.core import QgsSettings

    QgsSettings().setValue(bp18.ONBOARDING_CATCHUP_KEY, True)
    plugin, iface, settings = _gui(bp18, monkeypatch, stored_version="2.0.0")
    assert settings.value(DONE, None) is None
    opened = []
    plugin._on_home = lambda *a, **k: opened.append((a, k))

    iface.initializationCompleted.emit()

    assert opened == [(("checkin",), {"start_wizard": True})]
    plugin.unload()


def test_new_user_still_gets_the_wizard_even_if_done(bp18, monkeypatch):
    # Poste deja configure, mais compte jamais vu dans ref.users : assistant.
    plugin, iface, _settings = _gui(bp18, monkeypatch, stored_version="1.9.0", done=True)
    plugin._register_bridge_user = lambda **kw: True   # utilisateur cree a l'instant
    opened = []
    plugin._on_home = lambda *a, **k: opened.append((a, k, plugin._wizard_new_user))

    iface.initializationCompleted.emit()

    assert opened == [(("checkin",), {"start_wizard": True}, True)]
    plugin.unload()


def test_existing_user_with_setup_done_gets_no_wizard(bp18, monkeypatch):
    plugin, iface, _settings = _gui(bp18, monkeypatch, stored_version="1.9.0", done=True)
    opened = []
    plugin._on_home = lambda *a, **k: opened.append((a, k))

    iface.initializationCompleted.emit()

    assert plugin._connected is True and opened == []
    plugin.unload()
