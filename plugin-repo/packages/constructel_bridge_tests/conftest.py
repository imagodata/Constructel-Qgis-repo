"""Shared pytest fixtures for constructel_bridge_tests.

Adds plugin-repo/packages/ to sys.path so `from constructel_bridge import
...` works from a plain `pytest` invocation, with no QGIS installation
required for the pure-logic tests (bridge_identity.py has zero
qgis/psycopg2 imports).
"""
import sys
from pathlib import Path

PACKAGES_DIR = Path(__file__).resolve().parent.parent
if str(PACKAGES_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGES_DIR))
