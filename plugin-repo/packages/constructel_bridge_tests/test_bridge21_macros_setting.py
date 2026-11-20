"""Bridge 2.1, tache 20 (decision de Simon du 20/11) : le Bridge n'impose plus
``qgis/enableMacros = Always`` ; il ramene UNE fois une valeur ``Always`` a
``Ask`` (QGIS demande avant d'executer les macros d'un projet) et ne touche
jamais un autre choix."""
from __future__ import annotations

import pytest

from constructel_bridge_tests.test_bridge18_connect import _FakeCursor, _initgui_ready, _install_psycopg2

MACROS = "qgis/enableMacros"


@pytest.fixture
def settings(bp18):
    from qgis.core import QgsSettings

    QgsSettings._store.clear()
    yield QgsSettings()
    QgsSettings._store.clear()


def _start(bp18, monkeypatch):
    iface = _initgui_ready(bp18, monkeypatch)
    _install_psycopg2(monkeypatch, [None], _FakeCursor())
    plugin = bp18.ConstructelBridgePlugin(iface)
    plugin.initGui()
    plugin.unload()
    return plugin


def test_always_is_reset_once_to_ask(bp18, monkeypatch, settings):
    settings.setValue(MACROS, "Always")
    _start(bp18, monkeypatch)
    assert settings.value(MACROS) == "Ask"
    assert settings.value(bp18.MACROS_RESET_KEY) in (True, "true")


@pytest.mark.parametrize("choice", ["Never", "Ask", "SessionOnly", "NotForThisSession"])
def test_user_choice_other_than_always_is_kept(bp18, monkeypatch, settings, choice):
    settings.setValue(MACROS, choice)
    _start(bp18, monkeypatch)
    assert settings.value(MACROS) == choice
    assert settings.value(bp18.MACROS_RESET_KEY) in (True, "true")


def test_unset_value_is_never_written(bp18, monkeypatch, settings):
    _start(bp18, monkeypatch)
    assert settings.value(MACROS) is None


def test_reset_runs_only_once(bp18, monkeypatch, settings):
    settings.setValue(MACROS, "Always")
    _start(bp18, monkeypatch)
    settings.setValue(MACROS, "Always")          # la personne choisit « Toujours » ensuite
    _start(bp18, monkeypatch)
    assert settings.value(MACROS) == "Always"


def test_initgui_never_forces_always_anymore(bp18):
    import inspect

    assert '"Always")' not in inspect.getsource(bp18.ConstructelBridgePlugin.initGui)
