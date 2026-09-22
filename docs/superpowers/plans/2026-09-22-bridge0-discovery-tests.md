# Constructel Bridge — PR Bridge 0 (discovery/tests) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the pure identity/credential-resolution logic currently inline in `bridge_plugin.py` into a standalone, QGIS-free module with a full characterization test suite, plus a minimal `qgis`/`PyQt` stub so the plugin module itself can be smoke-imported under plain `pytest` — with zero change to plugin behavior.

**Architecture:** `bridge_plugin.py` (2072 lines, one monolithic class `ConstructelBridgePlugin` plus two small helper classes) mixes pure logic (username resolution order, credential-file parsing, realm→credentials matching, SQL-fragment construction) with QGIS-coupled side effects (QSettings, Auth Manager, psycopg2, Qt signals) in the same methods. This PR extracts the pure parts into `bridge_identity.py` (new file, zero `qgis`/`psycopg2` imports) and has `bridge_plugin.py` delegate to them. A new sibling test package `constructel_bridge_tests/` (deliberately **outside** `constructel_bridge/`, so `release.py`'s zip packaging never picks it up) hosts the test suite and a minimal `qgis` stub used only for a smoke-import test.

**Tech Stack:** Python 3.10+ (server runs 3.10.12), `pytest`, stdlib only for the extracted module (`base64`).

**Spec:** `docs/superpowers/specs/2026-09-22-constructel-bridge-mtls-design.md` — read its "État réel du terrain" section first: it documents that the backend prerequisites for Bridge 1-3 (mTLS, RLS, MRO/POP scopes) do not exist yet and that this work is currently paused pending coordination with Marco. **This does not block Bridge 0**, which is a pure testability refactor independent of the backend.

## Global Constraints

- Zero user-visible behavior change (explicit mandate for PR Bridge 0 — "aucun changement utilisateur"). Every extracted function must reproduce its source's exact current output, including known warts (e.g. the naive SQL-quote escaping in `build_set_config_sql` — characterized, not fixed).
- No real secret in any committed test/fixture file — only placeholder values (`test`, `s3cr3t`, `wyre-pw`, `be-pw`, `test-host.invalid`).
- The `qgis`/`PyQt` stub package must never ship inside `constructel_bridge.zip`. `release.py`'s `rebuild_zip()` walks `PLUGIN_DIR = constructel_bridge/` only — the stub and all test code must live in the sibling `constructel_bridge_tests/` directory, never inside `constructel_bridge/`, except for `bridge_identity.py` itself (real shipped code, imported at runtime).
- `qgisMinimumVersion=3.28` (`metadata.txt:3`) — not directly exercised by this PR, but keep in mind: nothing added here should assume a newer QGIS API.
- Do not touch `sql/migrations/400_sec04_gis_identity_rls.sql` or anything under `~/projects/Farois` — this PR is scoped to `qgis_repo` only.
- Work happens on branch `feat/bridge0-discovery-tests`, in the isolated worktree `.worktrees/feat-bridge0-discovery-tests/` — never commit directly to `main` (repo convention, confirmed via `docs/superpowers/specs/2026-08-17-wyre-ldap-auth-design.md` and `.superpowers/sdd/`).

---

## File Structure

```
plugin-repo/packages/
├── constructel_bridge/                     # shipped plugin (release.py's PLUGIN_DIR)
│   ├── bridge_identity.py                  # NEW — pure logic, ships (needed at runtime)
│   └── bridge_plugin.py                    # MODIFIED — delegates to bridge_identity
├── constructel_bridge_tests/               # NEW — sibling, NEVER packaged into the zip
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_bridge_identity.py
│   ├── test_bridge_plugin_import.py
│   └── stubs/
│       └── qgis/
│           ├── __init__.py
│           ├── core.py
│           ├── gui.py
│           └── PyQt/
│               ├── __init__.py
│               ├── QtCore.py
│               ├── QtGui.py
│               └── QtWidgets.py
├── constructel_bridge.zip                  # untouched by this PR
└── plugins.xml                             # untouched by this PR
```

At repo root: `pytest.ini` (NEW) so `pytest` run from anywhere in the repo discovers `constructel_bridge_tests/`.

---

### Task 1: pytest scaffolding

**Files:**
- Create: `pytest.ini`
- Create: `plugin-repo/packages/constructel_bridge_tests/__init__.py`
- Create: `plugin-repo/packages/constructel_bridge_tests/conftest.py`

**Interfaces:**
- Produces: `constructel_bridge_tests` importable as a package; `sys.path` includes `plugin-repo/packages/` for every test in this package, so `from constructel_bridge import bridge_identity` resolves.

- [ ] **Step 1: Create `pytest.ini` at repo root**

```ini
[pytest]
testpaths = plugin-repo/packages/constructel_bridge_tests
python_files = test_*.py
```

- [ ] **Step 2: Create the empty test package marker**

```bash
mkdir -p plugin-repo/packages/constructel_bridge_tests
touch plugin-repo/packages/constructel_bridge_tests/__init__.py
```

- [ ] **Step 3: Write `conftest.py`**

```python
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
```

- [ ] **Step 4: Verify pytest runs (collects zero tests, no errors)**

Run: `pip install --user pytest && cd <repo-root> && pytest -v`
Expected: `collected 0 items` — no import errors, no missing-module errors.

- [ ] **Step 5: Commit**

```bash
git add pytest.ini plugin-repo/packages/constructel_bridge_tests/__init__.py plugin-repo/packages/constructel_bridge_tests/conftest.py
git commit -m "test(bridge0): add pytest scaffolding for constructel_bridge_tests"
```

---

### Task 2: `bridge_identity.py` — pure logic extraction + characterization tests

**Files:**
- Create: `plugin-repo/packages/constructel_bridge/bridge_identity.py`
- Test: `plugin-repo/packages/constructel_bridge_tests/test_bridge_identity.py`

**Interfaces:**
- Consumes: nothing (stdlib `base64` only).
- Produces (used by Task 4): `resolve_username(explicit_setting: str, profile_name: str, os_username: str) -> str`, `derive_email(username: str, domain: str = "constructel.be") -> str`, `parse_credentials_json(raw: dict) -> dict`, `decode_password(b64_password: str) -> str`, `resolve_credentials_for_realm(realm: str, username: str, *, be_enabled: bool, be_host: str, be_user: str, be_password: str, default_host: str, default_user: str, default_password: str) -> tuple[str, str] | None`, `build_set_config_sql(username: str) -> tuple[str, str]`.

- [ ] **Step 1: Write the failing tests**

Create `plugin-repo/packages/constructel_bridge_tests/test_bridge_identity.py`:

```python
"""Characterization tests for bridge_identity.py (PR Bridge 0, 2026-09-22).

These lock in the CURRENT behavior of logic extracted from
bridge_plugin.py. No QGIS import required — run with plain `pytest`.
"""
import base64

from constructel_bridge.bridge_identity import (
    build_set_config_sql,
    decode_password,
    derive_email,
    parse_credentials_json,
    resolve_credentials_for_realm,
    resolve_username,
)


# --- resolve_username -------------------------------------------------

def test_resolve_username_prefers_explicit_setting():
    result = resolve_username("alice.override", "bob_profile", "carol_os")
    assert result == "alice.override"


def test_resolve_username_falls_back_to_profile_name():
    result = resolve_username("", "bob_profile", "carol_os")
    assert result == "bob_profile"


def test_resolve_username_ignores_default_profile_name():
    result = resolve_username("", "default", "carol_os")
    assert result == "carol_os"


def test_resolve_username_falls_back_to_os_username():
    result = resolve_username("", "", "carol_os")
    assert result == "carol_os"


# --- derive_email -------------------------------------------------------

def test_derive_email_matches_hardcoded_domain():
    assert derive_email("jdupont") == "jdupont@constructel.be"


def test_derive_email_accepts_custom_domain():
    assert derive_email("jdupont", domain="example.com") == "jdupont@example.com"


# --- parse_credentials_json ---------------------------------------------

def test_parse_credentials_json_nested_format_passthrough():
    raw = {"wyre": {"host": "h"}, "be": {"host": "h2"}}
    assert parse_credentials_json(raw) == raw


def test_parse_credentials_json_flat_format_attaches_to_wyre():
    raw = {"host": "h", "port": 5432, "dbname": "db", "user": "u", "password": "cGFzcw=="}
    result = parse_credentials_json(raw)
    assert result["wyre"] == raw
    assert result["be"] == {}


# --- decode_password ------------------------------------------------------

def test_decode_password_roundtrip():
    encoded = base64.b64encode(b"s3cr3t").decode()
    assert decode_password(encoded) == "s3cr3t"


# --- resolve_credentials_for_realm ----------------------------------------

DEFAULT_KWARGS = dict(
    be_enabled=True,
    be_host="db.example.internal",
    be_user="bureau_etudes",
    be_password="be-pw",
    default_host="db.example.internal",
    default_user="ftth_editor",
    default_password="wyre-pw",
)


def test_resolve_credentials_be_matched_by_username():
    result = resolve_credentials_for_realm(
        "dbname='farois_ftth' host=db.example.internal port=5432",
        "bureau_etudes",
        **DEFAULT_KWARGS,
    )
    assert result == ("bureau_etudes", "be-pw")


def test_resolve_credentials_be_matched_by_realm_user_clause():
    result = resolve_credentials_for_realm(
        "dbname='farois_ftth' host=db.example.internal user='bureau_etudes'",
        "someone_else",
        **DEFAULT_KWARGS,
    )
    assert result == ("bureau_etudes", "be-pw")


def test_resolve_credentials_falls_back_to_default_host():
    result = resolve_credentials_for_realm(
        "dbname='farois_ftth' host=db.example.internal port=5432",
        "someone_else",
        **DEFAULT_KWARGS,
    )
    assert result == ("ftth_editor", "wyre-pw")


def test_resolve_credentials_be_disabled_falls_back_to_default():
    kwargs = dict(DEFAULT_KWARGS, be_enabled=False)
    result = resolve_credentials_for_realm(
        "dbname='farois_ftth' host=db.example.internal user='bureau_etudes'",
        "bureau_etudes",
        **kwargs,
    )
    assert result == ("ftth_editor", "wyre-pw")


def test_resolve_credentials_unrelated_realm_returns_none():
    result = resolve_credentials_for_realm(
        "dbname='other_db' host=third-party.example.com",
        "someone",
        **DEFAULT_KWARGS,
    )
    assert result is None


def test_resolve_credentials_third_party_host_with_be_username_does_not_leak():
    # Regression guard for the credential-leak scenario documented in
    # bridge_plugin.py's _credentials_for docstring: a third-party PG
    # server where the username happens to equal be_user must NOT
    # receive the be password.
    result = resolve_credentials_for_realm(
        "dbname='other_db' host=third-party.example.com",
        "bureau_etudes",
        **DEFAULT_KWARGS,
    )
    assert result is None


# --- build_set_config_sql --------------------------------------------------

def test_build_set_config_sql_simple_username():
    set_config_sql, app_name_sql = build_set_config_sql("jdupont")
    assert set_config_sql == "SELECT set_config('app.current_user', 'jdupont', true)"
    assert app_name_sql == "SET application_name = 'constructel_bridge:jdupont'"


def test_build_set_config_sql_escapes_single_quote():
    # Characterizes the CURRENT naive escaping (doubled quote), not a fix.
    set_config_sql, app_name_sql = build_set_config_sql("o'brien")
    assert set_config_sql == "SELECT set_config('app.current_user', 'o''brien', true)"
    assert app_name_sql == "SET application_name = 'constructel_bridge:o''brien'"
```

- [ ] **Step 2: Run tests to verify they fail with ImportError**

Run: `pytest plugin-repo/packages/constructel_bridge_tests/test_bridge_identity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'constructel_bridge.bridge_identity'`

- [ ] **Step 3: Write `bridge_identity.py`**

```python
"""Pure identity/credential-resolution logic, extracted from
bridge_plugin.py for unit testing without a QGIS runtime (PR Bridge 0,
2026-09-22).

These functions must stay side-effect-free: no QGIS, no psycopg2, no file
I/O beyond what's passed in as plain arguments. bridge_plugin.py delegates
to them; this module has no dependency on bridge_plugin.py.
"""
from __future__ import annotations

import base64


def resolve_username(explicit_setting: str, profile_name: str, os_username: str) -> str:
    """Reproduces the resolution order of _get_qgis_username():
    1. explicit QgsSettings override, if non-empty
    2. QGIS profile name, if set and not "default"
    3. OS username (getpass.getuser())
    """
    if explicit_setting:
        return explicit_setting
    if profile_name and profile_name != "default":
        return profile_name
    return os_username


def derive_email(username: str, domain: str = "constructel.be") -> str:
    """Reproduces the email construction in _register_bridge_user():
    f"{username}@constructel.be" hardcoded — domain kept as a parameter
    here for testability, default matches the hardcoded value exactly.
    """
    return f"{username}@{domain}"


def parse_credentials_json(raw: dict) -> dict:
    """Reproduces the flat-vs-nested normalization in _load_credentials().

    Pre-1.5.0 deployments have a FLAT object (host/port/... at the root).
    Since 1.5.0, credentials.json has named blocks {"wyre": {...}, "be":
    {...}}. A flat object is attached to "wyre"; "be" stays empty rather
    than raising a KeyError at import time (which would prevent the whole
    plugin from loading, wyre included).
    """
    if "host" in raw:
        return {"wyre": raw, "be": {}}
    return raw


def decode_password(b64_password: str) -> str:
    """Reproduces the base64 decode used for both wyre and be passwords."""
    return base64.b64decode(b64_password).decode()


def resolve_credentials_for_realm(
    realm: str,
    username: str,
    *,
    be_enabled: bool,
    be_host: str,
    be_user: str,
    be_password: str,
    default_host: str,
    default_user: str,
    default_password: str,
) -> tuple[str, str] | None:
    """Reproduces _BridgeCredentials._credentials_for() exactly.

    `be` is tested FIRST (more specific): only recognized if the BE user
    appears explicitly in the realm string (QGIS embeds `user='...'` when
    the connection remembers its username) or as the `username` argument.
    Anchored on be_host (not default_host): a request toward a
    THIRD-PARTY PG server where username happens to equal be_user must
    NOT receive the be password — anchoring on be_host prevents that
    credential leak. Falls back to (default_user, default_password) if
    default_host is in realm. Returns None if the realm doesn't concern
    us at all.
    """
    if be_enabled and be_host in realm and (f"user='{be_user}'" in realm or username == be_user):
        return be_user, be_password
    if default_host in realm:
        return default_user, default_password
    return None


def build_set_config_sql(username: str) -> tuple[str, str]:
    """Reproduces the manual-escaping fallback branch of
    _on_before_commit() used when provider.executeSql() (no parameterized
    API) is the only option. Returns (set_config_sql, application_name_sql).

    KNOWN LIMITATION, characterized not fixed by PR Bridge 0: this is a
    naive doubled-quote escape (`.replace("'", "''")`), not a real SQL
    literal encoder. It does not handle backslashes specially and assumes
    standard_conforming_strings=on (PostgreSQL default since 9.1). Do not
    extend this pattern to new call sites; the parameterized cursor path
    (used whenever self._conn is available) remains the safe default.
    """
    safe_user = username.replace("'", "''")
    set_config_sql = f"SELECT set_config('app.current_user', '{safe_user}', true)"
    application_name_sql = f"SET application_name = 'constructel_bridge:{safe_user}'"
    return set_config_sql, application_name_sql
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest plugin-repo/packages/constructel_bridge_tests/test_bridge_identity.py -v`
Expected: PASS — 17 passed.

- [ ] **Step 5: Commit**

```bash
git add plugin-repo/packages/constructel_bridge/bridge_identity.py plugin-repo/packages/constructel_bridge_tests/test_bridge_identity.py
git commit -m "refactor(bridge0): extract pure identity/credential logic into bridge_identity.py"
```

---

### Task 3: minimal `qgis`/`PyQt` stub + smoke-import test for `bridge_plugin.py`

**Files:**
- Create: `plugin-repo/packages/constructel_bridge_tests/stubs/qgis/__init__.py`
- Create: `plugin-repo/packages/constructel_bridge_tests/stubs/qgis/core.py`
- Create: `plugin-repo/packages/constructel_bridge_tests/stubs/qgis/gui.py`
- Create: `plugin-repo/packages/constructel_bridge_tests/stubs/qgis/PyQt/__init__.py`
- Create: `plugin-repo/packages/constructel_bridge_tests/stubs/qgis/PyQt/QtCore.py`
- Create: `plugin-repo/packages/constructel_bridge_tests/stubs/qgis/PyQt/QtGui.py`
- Create: `plugin-repo/packages/constructel_bridge_tests/stubs/qgis/PyQt/QtWidgets.py`
- Test: `plugin-repo/packages/constructel_bridge_tests/test_bridge_plugin_import.py`

**Interfaces:**
- Consumes: `constructel_bridge.bridge_identity` (Task 2, transitively — `bridge_plugin.py` will import it once Task 4 lands; this task's test must still pass with the PRE-Task-4 `bridge_plugin.py`, since it only checks that the module imports).
- Produces: nothing consumed by later tasks — this is a standalone regression signal.

- [ ] **Step 1: Write the failing test**

Create `plugin-repo/packages/constructel_bridge_tests/test_bridge_plugin_import.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest plugin-repo/packages/constructel_bridge_tests/test_bridge_plugin_import.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'qgis'`

- [ ] **Step 3: Write the stub package**

`plugin-repo/packages/constructel_bridge_tests/stubs/qgis/__init__.py` (empty file — just marks the package).

`plugin-repo/packages/constructel_bridge_tests/stubs/qgis/core.py`:

```python
"""Minimal stand-in for qgis.core, sufficient to import bridge_plugin.py
under plain pytest (no real QGIS runtime). Behavior is NOT faithful to
the real API beyond what's needed for a clean module import — extend as
needed if other constructel_bridge modules require more symbols; a
failing import's traceback names exactly what's missing.
"""


class Qgis:
    Info = 0
    Warning = 1
    Critical = 2


class _StubUserProfile:
    def name(self):
        return "default"


class _StubUserProfileManager:
    def userProfile(self):
        return _StubUserProfile()


class _StubAuthManager:
    def isDisabled(self):
        return True

    def masterPasswordIsSet(self):
        return False

    def setMasterPassword(self, *_args, **_kwargs):
        return False

    def configIds(self):
        return []

    def loadAuthenticationConfig(self, *_args, **_kwargs):
        return None

    def updateAuthenticationConfig(self, *_args, **_kwargs):
        return False

    def storeAuthenticationConfig(self, *_args, **_kwargs):
        return False

    def removeAuthenticationConfig(self, *_args, **_kwargs):
        return None


class QgsApplication:
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def authManager():
        return _StubAuthManager()

    def userProfileManager(self):
        return _StubUserProfileManager()


class QgsAuthMethodConfig:
    def __init__(self, method_name=""):
        self._method_name = method_name
        self._config = {}
        self._name = ""

    def setName(self, name):
        self._name = name

    def setConfig(self, key, value):
        self._config[key] = value

    def config(self, key, default=""):
        return self._config.get(key, default)

    def id(self):
        return "stub-cfg-id"


class QgsCredentials:
    _instance = None

    def __init__(self):
        QgsCredentials._instance = self

    @classmethod
    def instance(cls):
        return cls._instance

    def put(self, realm, username, password):
        pass

    def get(self, realm, username, password, message=""):
        return False, username, password

    def request(self, realm, username, password, message=""):
        raise NotImplementedError

    def requestMasterPassword(self, password, stored=False):
        raise NotImplementedError


class QgsDataProvider:
    pass


class QgsDataSourceUri:
    def __init__(self):
        self._params = {}

    def setConnection(self, *args, **kwargs):
        pass

    def setDataSource(self, *args, **kwargs):
        pass

    def uri(self, *args, **kwargs):
        return ""


class QgsMessageLog:
    @staticmethod
    def logMessage(*_args, **_kwargs):
        pass


class _StubSignal:
    def connect(self, *_args, **_kwargs):
        pass

    def disconnect(self, *_args, **_kwargs):
        pass


class QgsProject:
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def mapLayers(self):
        return {}

    @property
    def layersAdded(self):
        return _StubSignal()


class QgsProjectBadLayerHandler:
    pass


class QgsSettings:
    _store = {}

    def value(self, key, default=None):
        return QgsSettings._store.get(key, default)

    def setValue(self, key, value):
        QgsSettings._store[key] = value

    def remove(self, key):
        QgsSettings._store.pop(key, None)


class QgsVectorLayer:
    pass


class QgsWkbTypes:
    pass
```

`plugin-repo/packages/constructel_bridge_tests/stubs/qgis/gui.py`:

```python
class QgisInterface:
    pass
```

`plugin-repo/packages/constructel_bridge_tests/stubs/qgis/PyQt/__init__.py` (empty file).

`plugin-repo/packages/constructel_bridge_tests/stubs/qgis/PyQt/QtCore.py`:

```python
class Qt:
    pass
```

`plugin-repo/packages/constructel_bridge_tests/stubs/qgis/PyQt/QtGui.py`:

```python
class QIcon:
    def __init__(self, *_args, **_kwargs):
        pass
```

`plugin-repo/packages/constructel_bridge_tests/stubs/qgis/PyQt/QtWidgets.py`:

```python
class QAction:
    def __init__(self, *_args, **_kwargs):
        pass


class QDialog:
    Accepted = 1
    Rejected = 0


class QInputDialog:
    pass


class QMenu:
    def __init__(self, *_args, **_kwargs):
        pass


class QMessageBox:
    @staticmethod
    def critical(*_args, **_kwargs):
        pass

    @staticmethod
    def warning(*_args, **_kwargs):
        pass


class QToolButton:
    def __init__(self, *_args, **_kwargs):
        pass
```

- [ ] **Step 4: Run test, extend the stub if it still fails on a different missing name**

Run: `pytest plugin-repo/packages/constructel_bridge_tests/test_bridge_plugin_import.py -v`

`bridge_plugin.py` also does `from .i18n import ...`, `from . import bridge_sketcher`, `from .bridge_expressions import ...` — these sibling modules were **not** inspected during PR Bridge 0's discovery and may import additional `qgis.core`/`qgis.gui`/`qgis.PyQt` names not listed above. If the test still fails with `ImportError: cannot import name 'X' from 'qgis.core'` (or `qgis.gui`/`qgis.PyQt.*`), add a minimal stub class or constant named `X` to the relevant stub file (matching the pattern above: a class with `pass` or a couple of no-op methods is normally enough for an import-only smoke test) and re-run. Repeat until the test passes. Do not add behavior beyond what makes the import succeed — this test verifies importability, not QGIS behavior.

Expected once complete: PASS — 1 passed.

- [ ] **Step 5: Commit**

```bash
git add plugin-repo/packages/constructel_bridge_tests/stubs/ plugin-repo/packages/constructel_bridge_tests/test_bridge_plugin_import.py
git commit -m "test(bridge0): add qgis/PyQt stub + smoke-import test for bridge_plugin.py"
```

---

### Task 4: wire `bridge_identity.py` into `bridge_plugin.py` (behavior-preserving)

**Files:**
- Modify: `plugin-repo/packages/constructel_bridge/bridge_plugin.py:66-83` (`_load_credentials`)
- Modify: `plugin-repo/packages/constructel_bridge/bridge_plugin.py:91,110` (`_DEFAULT_PW`, `_BE_PW`)
- Modify: `plugin-repo/packages/constructel_bridge/bridge_plugin.py:938-954` (`_get_qgis_username`)
- Modify: `plugin-repo/packages/constructel_bridge/bridge_plugin.py:976-984` (email in `_register_bridge_user`)
- Modify: `plugin-repo/packages/constructel_bridge/bridge_plugin.py:207-213` (`_BridgeCredentials._credentials_for`)
- Modify: `plugin-repo/packages/constructel_bridge/bridge_plugin.py:1578-1584` (`_on_before_commit` fallback)

**Interfaces:**
- Consumes: all six functions from `constructel_bridge.bridge_identity` (Task 2).

- [ ] **Step 1: `_load_credentials()` — delegate JSON normalization**

Before (`bridge_plugin.py:66-76`):

```python
def _load_credentials() -> dict:
    """..."""
    import json
    with open(_CREDENTIALS_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if "host" in raw:
        return {"wyre": raw, "be": {}}
    return raw
```

After:

```python
def _load_credentials() -> dict:
    """..."""
    import json
    from .bridge_identity import parse_credentials_json
    with open(_CREDENTIALS_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return parse_credentials_json(raw)
```

- [ ] **Step 2: `_DEFAULT_PW` / `_BE_PW` — delegate base64 decode**

Add near the top of the file, alongside the other `qgis` imports (module-level, since these constants are computed at module level):

```python
from .bridge_identity import decode_password, derive_email
```

Before:

```python
_DEFAULT_PW = base64.b64decode(_WYRE_CREDS["password"]).decode()
...
_BE_PW = (
    base64.b64decode(_BE_CREDS["password"]).decode()
    if _BE_CREDS.get("password") else ""
)
```

After:

```python
_DEFAULT_PW = decode_password(_WYRE_CREDS["password"])
...
_BE_PW = decode_password(_BE_CREDS["password"]) if _BE_CREDS.get("password") else ""
```

(The `import base64` at the top of the file can now be removed if nothing else in the file uses `base64` directly — check with `grep -n "base64\." bridge_plugin.py` before removing; only drop the import if that grep returns nothing outside the lines just changed.)

- [ ] **Step 3: `_get_qgis_username()` — delegate resolution order**

Before:

```python
def _get_qgis_username(self) -> str:
    """Recupere le nom d'utilisateur depuis les settings QGIS ou l'OS."""
    settings = QgsSettings()

    explicit = settings.value("constructel_bridge/username", "")
    if explicit:
        return explicit

    try:
        profile = QgsApplication.instance().userProfileManager().userProfile()
        if profile and profile.name() and profile.name() != "default":
            return profile.name()
    except Exception:
        pass

    import getpass
    return getpass.getuser()
```

After:

```python
def _get_qgis_username(self) -> str:
    """Recupere le nom d'utilisateur depuis les settings QGIS ou l'OS."""
    from .bridge_identity import resolve_username

    settings = QgsSettings()
    explicit = settings.value("constructel_bridge/username", "")

    profile_name = ""
    try:
        profile = QgsApplication.instance().userProfileManager().userProfile()
        if profile:
            profile_name = profile.name() or ""
    except Exception:
        pass

    # NOTE (PR Bridge 0): getpass.getuser() is now evaluated eagerly, even
    # when `explicit` alone would already decide the result. Previously it
    # ran lazily, only when both prior checks failed. getpass.getuser()
    # has no side effects and essentially never raises on a normal
    # workstation, so this is a deliberate, low-risk deviation accepted
    # to make the decision logic a pure, testable function — not a silent
    # behavior change.
    import getpass
    return resolve_username(explicit, profile_name, getpass.getuser())
```

- [ ] **Step 4: `_register_bridge_user()` — delegate email derivation**

Before (inside the `INSERT INTO ref.users` call):

```python
cur.execute(
    """
    INSERT INTO ref.users (username, email, last_name, role)
    VALUES (%s, %s, %s, 'OPERATOR')
    ON CONFLICT (username) DO UPDATE
        SET last_login = NOW(), active = TRUE
    RETURNING id
    """,
    (username, f"{username}@constructel.be", username),
)
```

After:

```python
cur.execute(
    """
    INSERT INTO ref.users (username, email, last_name, role)
    VALUES (%s, %s, %s, 'OPERATOR')
    ON CONFLICT (username) DO UPDATE
        SET last_login = NOW(), active = TRUE
    RETURNING id
    """,
    (username, derive_email(username), username),
)
```

(`derive_email` is already imported at module level from Step 2 — no new import needed here.)

- [ ] **Step 5: `_BridgeCredentials._credentials_for()` — delegate realm matching**

Before:

```python
def _credentials_for(self, realm, username):
    """..."""
    if BE_ENABLED and BE_HOST in realm and (f"user='{BE_USER}'" in realm or username == BE_USER):
        return BE_USER, _BE_PW
    if DEFAULT_HOST in realm:
        return self._username, self._password
    return None
```

After:

```python
def _credentials_for(self, realm, username):
    """..."""
    from .bridge_identity import resolve_credentials_for_realm

    return resolve_credentials_for_realm(
        realm,
        username,
        be_enabled=BE_ENABLED,
        be_host=BE_HOST,
        be_user=BE_USER,
        be_password=_BE_PW,
        default_host=DEFAULT_HOST,
        default_user=self._username,
        default_password=self._password,
    )
```

Note: `default_user`/`default_password` are `self._username`/`self._password` (per-instance, updated by `update_password()`), **not** the module constants `DEFAULT_USER`/`_DEFAULT_PW` — this matches the original exactly.

- [ ] **Step 6: `_on_before_commit()` fallback — delegate SQL construction**

Before:

```python
else:
    # Fallback: escape value for provider.executeSql() (no parameterized API)
    safe_user = self._bridge_user.replace("'", "''")
    provider.executeSql(
        f"SELECT set_config('app.current_user', '{safe_user}', true)"
    )
    provider.executeSql(
        f"SET application_name = 'constructel_bridge:{safe_user}'"
    )
```

After:

```python
else:
    # Fallback: escape value for provider.executeSql() (no parameterized API)
    from .bridge_identity import build_set_config_sql

    set_config_sql, app_name_sql = build_set_config_sql(self._bridge_user)
    provider.executeSql(set_config_sql)
    provider.executeSql(app_name_sql)
```

- [ ] **Step 7: Run the full test suite**

Run: `pytest -v`
Expected: PASS — all tests from Task 2 and Task 3 pass, including the smoke-import test (which now also exercises the new `from .bridge_identity import ...` lines added in this task).

- [ ] **Step 8: Manual behavior-preservation review**

Run: `git diff plugin-repo/packages/constructel_bridge/bridge_plugin.py`

Confirm, reading the whole diff top to bottom:
- Every removed line is either an `import base64` (if step 2's grep found no other use) or logic now replaced by an equivalent call into `bridge_identity`.
- No line unrelated to the six call sites above was touched.
- No new parameter, default value, or control-flow branch was introduced beyond the documented `getpass.getuser()` eagerness change (Step 3).

- [ ] **Step 9: Commit**

```bash
git add plugin-repo/packages/constructel_bridge/bridge_plugin.py
git commit -m "refactor(bridge0): delegate identity/credential logic to bridge_identity.py

No behavior change except getpass.getuser() now evaluated eagerly in
_get_qgis_username() (documented, no observable side effect)."
```

---

## Self-Review

**Spec coverage** (against `docs/superpowers/specs/2026-09-22-constructel-bridge-mtls-design.md`, section "Découpage de PR recommandé", PR Bridge 0 = *"inventaire, abstractions, tests de configuration legacy, aucun changement utilisateur"*):
- *inventaire* → delivered separately, already committed to the spec file's "État réel du terrain" section (Phase 0 discovery, done 2026-09-22, not re-duplicated in this plan).
- *abstractions* → Task 2 (`bridge_identity.py`).
- *tests de configuration legacy* → Task 2 (characterization tests, 17 cases) + Task 3 (smoke-import test).
- *aucun changement utilisateur* → Task 4, with the one documented, justified exception (Step 3, eager `getpass.getuser()`) called out explicitly rather than hidden.

**Placeholder scan:** no `TODO`/`TBD`/"add appropriate error handling" anywhere above; every step has real, complete code. The one intentionally open-ended step (Task 3, Step 4 — "extend the stub if it still fails") is a bounded, well-defined loop with an exact stop condition (`pytest` passes), not an unspecified placeholder — it exists because `i18n.py`, `bridge_sketcher.py` and `bridge_expressions.py` were not read during Phase 0 discovery (out of scope for the mTLS-relevant inventory) and their exact `qgis` imports are genuinely unknown until the test is run.

**Type consistency:** `resolve_credentials_for_realm` returns `tuple[str, str] | None`, consumed directly as `_credentials_for`'s return value (same type). `build_set_config_sql` returns `tuple[str, str]`, unpacked consistently as `(set_config_sql, app_name_sql)` in both the test and the call site. `parse_credentials_json` takes and returns `dict`, matching `_load_credentials`'s existing return type.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-22-bridge0-discovery-tests.md`. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach?
