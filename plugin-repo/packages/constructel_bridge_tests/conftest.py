"""Shared pytest fixtures for constructel_bridge_tests.

Adds plugin-repo/packages/ to sys.path so `from constructel_bridge import
...` works from a plain `pytest` invocation, with no QGIS installation
required for the pure-logic tests (bridge_identity.py has zero
qgis/psycopg2 imports).

Bridge 1.8 fixtures (`load_bp18`, `bp18`): a fresh bridge_plugin module
imported on top of the qgis stub package, built on an explicit
credentials.json dict (three deployment shapes: 1.7.x shared passwords,
1.8 transition, 1.8.x closure without any secret).
"""
import base64
import importlib
import json
import sys
from pathlib import Path

import pytest

PACKAGES_DIR = Path(__file__).resolve().parent.parent
if str(PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGES_DIR))

STUBS_DIR = Path(__file__).resolve().parent / "stubs"
PLUGIN_DIR = PACKAGES_DIR / "constructel_bridge"
CREDENTIALS_PATH = PLUGIN_DIR / "credentials.json"

HOST18 = "test-host.invalid"
_B64 = base64.b64encode(b"shared-pw").decode()
_B64_BE = base64.b64encode(b"be-shared-pw").decode()

CREDS_17 = {
    "wyre": {"host": HOST18, "port": 5432, "dbname": "test_db", "user": "ftth_editor", "password": _B64},
    "be": {"host": HOST18, "port": 5432, "dbname": "test_db", "user": "bureau_etudes", "password": _B64_BE},
}
CREDS_18 = {
    "wyre": {"host": HOST18, "port": 5432, "dbname": "test_db", "user": "ftth_editor", "password": _B64},
    "be": {"host": HOST18, "port": 5432, "dbname": "test_db"},
}
CREDS_18X = {
    "wyre": {"host": HOST18, "port": 5432, "dbname": "test_db"},
    "be": {"host": HOST18, "port": 5432, "dbname": "test_db"},
}


@pytest.fixture
def load_bp18(monkeypatch):
    """Factory: load_bp18(creds) -> fresh bridge_plugin module built on
    *creds*. Never clobbers a pre-existing real credentials.json. PGOPTIONS
    is restored after the test even when the code writes os.environ."""
    if str(STUBS_DIR) not in sys.path:
        sys.path.insert(0, str(STUBS_DIR))
    pre_existing = CREDENTIALS_PATH.read_bytes() if CREDENTIALS_PATH.exists() else None
    monkeypatch.setenv("PGOPTIONS", "placeholder")
    monkeypatch.delenv("PGOPTIONS")

    def _load(creds):
        CREDENTIALS_PATH.write_text(json.dumps(creds))
        for mod_name in list(sys.modules):
            if mod_name == "constructel_bridge.bridge_plugin" or mod_name.startswith("qgis"):
                del sys.modules[mod_name]
        return importlib.import_module("constructel_bridge.bridge_plugin")

    yield _load
    if pre_existing is None:
        CREDENTIALS_PATH.unlink(missing_ok=True)
    else:
        CREDENTIALS_PATH.write_bytes(pre_existing)


@pytest.fixture
def bp18(load_bp18):
    return load_bp18(CREDS_18)
