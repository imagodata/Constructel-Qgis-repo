"""Smoke-import test for bridge_plugin.py, using a minimal qgis/PyQt stub
package (PR Bridge 0, 2026-09-22). This does NOT verify QGIS behavior —
only that the module imports cleanly, so future refactors (Bridge 1+)
have a fast regression signal without a real QGIS runtime.

The stub package lives in constructel_bridge_tests/stubs/, a SIBLING of
constructel_bridge/ (not inside PLUGIN_DIR) — release.py's rebuild_zip()
walks PLUGIN_DIR only, so this stub is never bundled into the distributed
plugin zip. Do not move this file or the stub package inside
constructel_bridge/.
"""
import base64
import importlib
import json
import sys
from pathlib import Path

import pytest

STUBS_DIR = Path(__file__).resolve().parent / "stubs"
PLUGIN_DIR = Path(__file__).resolve().parent.parent / "constructel_bridge"
CREDENTIALS_PATH = PLUGIN_DIR / "credentials.json"

_FIXTURE_CREDENTIALS = {
    "wyre": {
        "host": "test-host.invalid",
        "port": 5432,
        "dbname": "test_db",
        "user": "test_user",
        "password": base64.b64encode(b"test").decode(),
    }
}


@pytest.fixture
def qgis_stub_path():
    if str(STUBS_DIR) not in sys.path:
        sys.path.insert(0, str(STUBS_DIR))
    yield


@pytest.fixture
def credentials_json_present():
    """Ensures credentials.json exists next to bridge_plugin.py for the
    duration of the test, WITHOUT ever touching a pre-existing real file
    (the real deployment on the VPS has one; a fresh clone does not).
    """
    pre_existing = CREDENTIALS_PATH.exists()
    if not pre_existing:
        CREDENTIALS_PATH.write_text(json.dumps(_FIXTURE_CREDENTIALS))
    yield
    if not pre_existing:
        CREDENTIALS_PATH.unlink()


def test_bridge_plugin_module_imports_cleanly(qgis_stub_path, credentials_json_present):
    # Deferred import: must happen AFTER the fixtures have set up sys.path
    # and credentials.json, not at collection time.
    for mod_name in list(sys.modules):
        if mod_name == "constructel_bridge.bridge_plugin" or mod_name.startswith("qgis"):
            del sys.modules[mod_name]
    module = importlib.import_module("constructel_bridge.bridge_plugin")
    assert hasattr(module, "ConstructelBridgePlugin")
