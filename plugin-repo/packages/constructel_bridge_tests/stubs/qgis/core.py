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
