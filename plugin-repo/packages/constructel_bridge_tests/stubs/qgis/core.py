"""Minimal stand-in for qgis.core, sufficient to import bridge_plugin.py
under plain pytest (no real QGIS runtime). Behavior is NOT faithful to
the real API beyond what's needed for a clean module import — extend as
needed if other constructel_bridge modules require more symbols; a
failing import's traceback names exactly what's missing.
"""
import re


_URI_TOKEN_RE = re.compile(r"(\w+)=('([^']*)'|\"([^\"]*)\"|(\S+))")
_URI_BARE_RE = re.compile(r"^[\w.\-]+$")


class Qgis:
    QGIS_VERSION_INT = 34400

    class MessageLevel:
        Info = 0
        Warning = 1
        Critical = 2

    Info = MessageLevel.Info
    Warning = MessageLevel.Warning
    Critical = MessageLevel.Critical


class _StubUserProfile:
    def name(self):
        return "default"


class _StubUserProfileManager:
    def userProfile(self):
        return _StubUserProfile()


class _StubAuthManager:
    # Shared across instances like the real Auth Manager (QgsApplication
    # hands out the same manager); tests reset via a fresh module import.
    # Default state is READY (production-normal); tests flip isDisabled for
    # the not-ready path.
    _configs = {}
    _next_id = 1
    # Tests flip this to simulate a refused write (auth DB error, invalid
    # config). Like QGIS, an id already in use is refused too.
    _store_fails = False

    def isDisabled(self):
        return False

    def masterPasswordIsSet(self):
        return True

    def setMasterPassword(self, *_args, **_kwargs):
        return False

    def configIds(self):
        return list(_StubAuthManager._configs)

    def loadAuthenticationConfig(self, authcfg_id, config, full=False):
        # NOTE: `full` accepted for signature fidelity; the stub stores
        # plaintext and ignores decryption depth. The return is ignored by
        # production and tests alike (unknown ids leave the probe untouched).
        stored = _StubAuthManager._configs.get(authcfg_id)
        if stored is None:
            return None
        config.setId(authcfg_id)
        config.setName(stored["name"])
        # Test-double private write: the real API restores the method on load.
        config._method_name = stored["method"]
        for key, value in stored["config"].items():
            config.setConfig(key, value)
        return None

    def _snapshot(self, config):
        # Test-double introspection: real code never reads these privates.
        return {
            "method": config.method(),
            "name": config.name(),
            "config": dict(config._config),
        }

    def storeAuthenticationConfig(self, config):
        # Real API (QGIS 3.28 -> 4.x, SIP_INOUT): returns (ok, config), never
        # a bare bool -- the tuple is always truthy, callers must read [0].
        # Like QGIS: a refused write leaves an automatic id empty, while a
        # caller-set (fixed) id stays on the config.
        if _StubAuthManager._store_fails or config.id() in _StubAuthManager._configs:
            return False, config
        if not config.id():
            config.setId(f"stub-authcfg-{_StubAuthManager._next_id}")
            _StubAuthManager._next_id += 1
        _StubAuthManager._configs[config.id()] = self._snapshot(config)
        return True, config

    def updateAuthenticationConfig(self, config):
        if config.id() not in _StubAuthManager._configs:
            return False
        _StubAuthManager._configs[config.id()] = self._snapshot(config)
        return True

    def removeAuthenticationConfig(self, authcfg_id):
        _StubAuthManager._configs.pop(authcfg_id, None)
        return True


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
        self._id = ""

    def setId(self, id):
        self._id = id

    def id(self):
        return self._id

    def setName(self, name):
        self._name = name

    def name(self):
        return self._name

    def method(self):
        # Used by wiring tests to assert PKI-Paths vs Basic.
        return self._method_name

    def setConfig(self, key, value):
        self._config[key] = value

    def config(self, key, default=""):
        return self._config.get(key, default)


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
    class ProviderOptions:
        pass


class QgsDataSourceUri:
    """Minimal subset of the real QgsDataSourceUri: parses a postgres
    provider URI string (whitespace-separated key=value / key='value' /
    key="value" tokens) and rebuilds it. Only the connection-parameter
    accessors used by bridge_plugin._fix_layer_credentials are
    implemented; other tokens round-trip verbatim. Anything beyond that
    (table/key/sql clauses, service= connections) is out of scope."""

    class SslMode:
        # Same numeric values as QgsDataSourceUri::SslMode (settings key
        # "sslmode" of a PG connection stores the number as a string).
        SslPrefer = 0
        SslDisable = 1
        SslAllow = 2
        SslRequire = 3
        SslVerifyCa = 4
        SslVerifyFull = 5

    _SSL_NAMES = {0: "prefer", 1: "disable", 2: "allow", 3: "require", 4: "verify-ca", 5: "verify-full"}

    def __init__(self, uri=""):
        self._params = {}
        if uri:
            for match in _URI_TOKEN_RE.finditer(uri):
                key = match.group(1)
                value = match.group(3)
                if value is None:
                    value = match.group(4)
                if value is None:
                    value = match.group(5)
                self._params[key] = value

    def setConnection(self, host, port, database, username, password, sslmode=None, authcfg=None):
        # Bridge 1.8 tests: a faithful-enough setConnection (the real one
        # stores every item; sslmode is an SslMode enum value).
        self._params["host"] = str(host)
        self._params["port"] = str(port)
        self._params["dbname"] = database
        if username:
            self._params["user"] = username
        else:
            self._params.pop("user", None)
        self.setPassword(password)
        if sslmode is not None:
            self.setSslMode(sslmode)
        self.setAuthConfigId(authcfg or "")

    def setDataSource(self, schema, table, geometry_column=None, sql="", key_column=""):
        self._params["table"] = f'"{schema}"."{table}"' if schema else f'"{table}"'
        if geometry_column:
            self._params["geom"] = geometry_column
        else:
            self._params.pop("geom", None)
        if key_column:
            self._params["key"] = key_column

    def setParam(self, key, value):
        self._params[key] = str(value)

    def param(self, key):
        return self._params.get(key, "")

    def setSslMode(self, mode):
        self._params["sslmode"] = self._SSL_NAMES.get(int(mode), str(mode))

    def sslMode(self):
        names = {v: k for k, v in self._SSL_NAMES.items()}
        return names.get(self._params.get("sslmode", "prefer"), 0)

    def schema(self):
        table = self._params.get("table", "")
        if table.startswith('"') and '"."' in table:
            return table.split('"."')[0].strip('"')
        return ""

    def table(self):
        table = self._params.get("table", "")
        if '"."' in table:
            return table.split('"."')[1].strip('"')
        return table.strip('"')

    def geometryColumn(self):
        return self._params.get("geom", "")

    def host(self):
        return self._params.get("host", "")

    def username(self):
        return self._params.get("user", "")

    def password(self):
        return self._params.get("password", "")

    def authConfigId(self):
        return self._params.get("authcfg", "")

    def setUsername(self, username):
        self._params["user"] = username

    def setPassword(self, password):
        if password:
            self._params["password"] = password
        else:
            self._params.pop("password", None)

    def setAuthConfigId(self, authcfg_id):
        if authcfg_id:
            self._params["authcfg"] = authcfg_id
        else:
            self._params.pop("authcfg", None)

    def uri(self, *args, **kwargs):
        parts = []
        for key, value in self._params.items():
            if _URI_BARE_RE.match(value):
                parts.append(f"{key}={value}")
            else:
                parts.append(f"{key}='{value}'")
        return " ".join(parts)


class QgsMessageLog:
    # Test-double introspection: real code never reads this; wiring tests
    # assert diagnostics through it. Reset by a fresh module import.
    _messages = []

    @staticmethod
    def logMessage(message, tag="", level=None):
        if level is None:
            level = Qgis.MessageLevel.Info
        QgsMessageLog._messages.append((message, tag, level))


class _StubSignal:
    def connect(self, *_args, **_kwargs):
        pass

    def disconnect(self, *_args, **_kwargs):
        pass


class QgsProject:
    _instance = None

    def __init__(self):
        self._layers = {}
        self._next_layer_id = 1

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def mapLayers(self):
        return dict(self._layers)

    def addMapLayer(self, layer, add_to_legend=True):
        layer_id = f"stub-layer-{self._next_layer_id}"
        self._next_layer_id += 1
        self._layers[layer_id] = layer
        return layer

    @property
    def layersAdded(self):
        return _StubSignal()

    # Bridge 1.8 tests (_read_and_clean_project): the XML handed to
    # project.read() is kept for inspection; nothing is parsed.
    def read(self, path):
        with open(path, "r", encoding="utf-8") as f:
            self.read_xml = f.read()
        return True

    def setTitle(self, title):
        self.title = title

    def setFileName(self, name):
        self.file_name = name

    def setDirty(self, dirty):
        self.dirty = dirty

    def error(self):
        return ""


class QgsProjectBadLayerHandler:
    pass


class QgsSettings:
    _store = {}

    def value(self, key, default=None, type=None):
        value = QgsSettings._store.get(key, default)
        if type is bool and isinstance(value, str):
            # Real QGIS persists bools as strings; type=bool converts.
            return value.lower() in ("true", "1")
        return value

    def setValue(self, key, value):
        QgsSettings._store[key] = value

    def remove(self, key):
        QgsSettings._store.pop(key, None)

    def sync(self):
        pass


class QgsVectorLayer:
    # Constructible like the real one (source, name, provider) so code that
    # creates layers (_ensure_ref_layers) runs under the stub; subclasses in
    # tests override whatever they need.
    def __init__(self, source="", name="", provider=""):
        self._source = source
        self._name = name
        self._provider_type = provider

    def source(self):
        return self._source

    def name(self):
        return self._name

    def providerType(self):
        return self._provider_type

    def isValid(self):
        return True


class QgsWkbTypes:
    pass


class QgsAttributeEditorContainer:
    pass


class QgsEditorWidgetSetup:
    def __init__(self, *_args, **_kwargs):
        pass


class QgsExpressionContextUtils:
    @staticmethod
    def setProjectVariable(*_args, **_kwargs):
        pass


class QgsExpression:
    @staticmethod
    def isFunctionName(*_args, **_kwargs):
        return False

    @staticmethod
    def registerFunction(*_args, **_kwargs):
        pass

    @staticmethod
    def unregisterFunction(*_args, **_kwargs):
        pass


def qgsfunction(*_args, **_kwargs):
    """Stand-in for the qgis.core qgsfunction decorator factory. Used at
    module level in bridge_expressions.py as
    @qgsfunction(args=..., group=..., usesGeometry=..., referencedColumns=...)
    — must actually be callable at import time, unlike most other stubs
    here (which only need to exist, since they are referenced inside
    function bodies executed later, not during import).
    """
    def _decorator(func):
        return func
    return _decorator
