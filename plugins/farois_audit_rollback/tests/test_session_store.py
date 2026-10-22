"""Magasin de la session Farois mémorisée (« Se souvenir de moi », 30 jours)."""

import sys
from types import ModuleType

import pytest

from plugins.farois_audit_rollback.api import session_store as ss

EMAIL, TOKEN = "simon@constructel.example.be", "rt.jwt-refresh_value"


@pytest.mark.parametrize("make", [ss.MemorySessionStore])
def test_memory_store_contract(make):
    store = make()
    assert store.load() is None
    store.save(EMAIL, TOKEN)
    assert store.load() == (EMAIL, TOKEN)
    store.save("autre@constructel.example.be", "rt-2")
    assert store.load() == ("autre@constructel.example.be", "rt-2")
    store.clear()
    assert store.load() is None
    store.clear()  # idempotent


class FakeConfig:
    def __init__(self, method="", version=0):
        self._method, self._id, self._name, self._values = method, "", "", {}

    def method(self):
        return self._method

    def setMethod(self, method):
        self._method = method

    def id(self):
        return self._id

    def setId(self, ident):
        self._id = ident

    def name(self):
        return self._name

    def setName(self, name):
        self._name = name

    def config(self, field, default=""):
        return self._values.get(field, default)

    def setConfig(self, field, value):
        self._values[field] = value

    def isValid(self, validateid=False):
        return bool(self._name and self._method)


class FakeAuthManager:
    """Base d'authentification QGIS factice : verrou du mot de passe maître, API tuple."""

    def __init__(self, disabled=False, unlocked=True, tuple_api=False, broken=False):
        self.disabled, self.unlocked = disabled, unlocked
        self.tuple_api, self.broken = tuple_api, broken
        self.configs, self.loads, self.counter = {}, 0, 0

    def _answer(self, ok, config):
        return (ok, config) if self.tuple_api else ok

    def _check(self):
        if self.broken:
            raise RuntimeError("authentication database locked")

    def isDisabled(self):
        self._check()
        return self.disabled

    def configIds(self):
        self._check()
        return list(self.configs)

    def storeAuthenticationConfig(self, config, *overwrite):
        self._check()
        if not self.unlocked:
            return self._answer(False, config)
        self.counter += 1
        ident = f"fx{self.counter:05d}"
        self.configs[ident] = (config.name(), config.method(), dict(config._values))
        if self.tuple_api:  # SIP_INOUT : la config renvoyée porte l'id
            stored = FakeConfig(config.method())
            stored.setId(ident)
            return True, stored
        config.setId(ident)
        return True

    def loadAuthenticationConfig(self, authcfg, config, full=False):
        self._check()
        self.loads += 1
        if not self.unlocked or authcfg not in self.configs:
            return self._answer(False, config)
        name, method, values = self.configs[authcfg]
        loaded = FakeConfig(method) if self.tuple_api else config
        loaded.setId(authcfg)
        loaded.setName(name)
        if full:
            loaded._values = dict(values)
        return (True, loaded) if self.tuple_api else True

    def removeAuthenticationConfig(self, authcfg):
        self._check()
        return self.configs.pop(authcfg, None) is not None


@pytest.fixture
def qgis_auth(monkeypatch):
    """qgis.core factice : gestionnaire d'authentification, réglages, journal."""
    settings, logged = {}, []
    manager = FakeAuthManager()

    class Settings:
        def value(self, key, default=None):
            return settings.get(key, default)

        def setValue(self, key, value):
            settings[key] = value

        def remove(self, key):
            settings.pop(key, None)

    core = ModuleType("qgis.core")
    core.QgsSettings = Settings
    core.QgsAuthMethodConfig = FakeConfig
    core.QgsApplication = type("QgsApplication", (), {"authManager": staticmethod(lambda: state.manager)})
    core.QgsMessageLog = type("QgsMessageLog", (), {
        "logMessage": staticmethod(lambda message, tag="", level=0: logged.append((message, tag, level)))
    })
    core.Qgis = type("Qgis", (), {"Warning": 1, "MessageLevel": type("MessageLevel", (), {"Warning": 1})})
    monkeypatch.setitem(sys.modules, "qgis", ModuleType("qgis"))
    monkeypatch.setitem(sys.modules, "qgis.core", core)

    class State:
        pass

    state = State()
    state.manager, state.settings, state.logged = manager, settings, logged
    return state


def test_qgis_store_keeps_email_and_refresh_token_in_a_basic_authcfg(qgis_auth):
    store = ss.QgisSessionStore()
    store.save(EMAIL, TOKEN)
    authcfg = qgis_auth.settings[ss.SETTINGS_KEY]
    name, method, values = qgis_auth.manager.configs[authcfg]
    assert (name, method) == ("Farois — session historique", "Basic")
    assert values == {"username": EMAIL, "password": TOKEN}
    assert ss.QgisSessionStore().load() == (EMAIL, TOKEN)


def test_qgis_store_save_replaces_the_previous_session(qgis_auth):
    store = ss.QgisSessionStore()
    store.save(EMAIL, TOKEN)
    store.save("autre@constructel.example.be", "rt-2")
    assert len(qgis_auth.manager.configs) == 1
    assert store.load() == ("autre@constructel.example.be", "rt-2")


def test_qgis_store_clear_removes_config_and_setting(qgis_auth):
    store = ss.QgisSessionStore()
    store.save(EMAIL, TOKEN)
    store.clear()
    assert qgis_auth.manager.configs == {}
    assert ss.SETTINGS_KEY not in qgis_auth.settings
    assert store.load() is None
    store.clear()  # rien à effacer : sans erreur


def test_qgis_store_without_saved_session_never_opens_the_auth_database(qgis_auth):
    assert ss.QgisSessionStore().load() is None
    assert qgis_auth.manager.loads == 0  # pas de demande de mot de passe maître


def test_qgis_store_handles_the_tuple_returning_sip_api(qgis_auth):
    qgis_auth.manager.tuple_api = True
    store = ss.QgisSessionStore()
    store.save(EMAIL, TOKEN)
    assert qgis_auth.settings[ss.SETTINGS_KEY] in qgis_auth.manager.configs
    assert store.load() == (EMAIL, TOKEN)


def test_qgis_store_master_password_refused_is_swallowed(qgis_auth):
    store = ss.QgisSessionStore()
    store.save(EMAIL, TOKEN)
    qgis_auth.manager.unlocked = False
    assert store.load() is None
    assert ss.SETTINGS_KEY in qgis_auth.settings  # lecture refusée : session gardée
    store.save("autre@constructel.example.be", "rt-2")  # ne lève pas
    # Échec d'enregistrement : l'identité mémorisée auparavant ne doit pas survivre.
    assert qgis_auth.manager.configs == {}
    assert ss.SETTINGS_KEY not in qgis_auth.settings
    qgis_auth.manager.unlocked = True
    assert store.load() is None
    assert qgis_auth.logged and all(tag == "Farois" for _, tag, _ in qgis_auth.logged)


def test_qgis_store_save_crash_drops_the_previous_identity_and_logs_the_type_only(qgis_auth):
    store = ss.QgisSessionStore()
    store.save(EMAIL, TOKEN)
    qgis_auth.manager.broken = True  # RuntimeError("authentication database locked")
    store.save("autre@constructel.example.be", "rt-2")
    assert ss.SETTINGS_KEY not in qgis_auth.settings
    assert any("RuntimeError" in message for message, _, _ in qgis_auth.logged)
    assert all("database locked" not in message for message, _, _ in qgis_auth.logged)


def test_qgis_store_disabled_or_broken_manager_is_swallowed(qgis_auth):
    store = ss.QgisSessionStore()
    store.save(EMAIL, TOKEN)
    qgis_auth.manager.disabled = True
    assert store.load() is None
    qgis_auth.manager.disabled, qgis_auth.manager.broken = False, True
    assert store.load() is None
    assert qgis_auth.logged
    assert all("database locked" not in message for message, _, _ in qgis_auth.logged)


@pytest.mark.parametrize("failure", ["disabled", "broken", "refused"])
def test_qgis_store_clear_keeps_the_key_until_the_config_is_really_deleted(qgis_auth, failure):
    store = ss.QgisSessionStore()
    store.save(EMAIL, TOKEN)
    authcfg = qgis_auth.settings[ss.SETTINGS_KEY]
    manager = qgis_auth.manager
    if failure == "refused":
        manager.removeAuthenticationConfig = lambda ident: False
    else:
        setattr(manager, failure, True)
    store.clear()
    assert qgis_auth.settings[ss.SETTINGS_KEY] == authcfg  # un clear() ultérieur réessaiera
    assert authcfg in manager.configs  # rien n'a été supprimé
    assert all("database locked" not in message for message, _, _ in qgis_auth.logged)
    assert qgis_auth.logged
    vars(manager).pop("removeAuthenticationConfig", None)
    manager.disabled = manager.broken = False
    store.clear()
    assert manager.configs == {} and ss.SETTINGS_KEY not in qgis_auth.settings


def test_qgis_store_clear_of_a_config_deleted_in_qgis_drops_the_key(qgis_auth):
    store = ss.QgisSessionStore()
    store.save(EMAIL, TOKEN)
    qgis_auth.manager.configs.clear()
    store.clear()
    assert ss.SETTINGS_KEY not in qgis_auth.settings


def test_qgis_store_forgets_a_config_deleted_in_qgis(qgis_auth):
    store = ss.QgisSessionStore()
    store.save(EMAIL, TOKEN)
    qgis_auth.manager.configs.clear()
    assert store.load() is None
    assert ss.SETTINGS_KEY not in qgis_auth.settings


def test_qgis_store_never_logs_secrets(qgis_auth):
    store = ss.QgisSessionStore()
    qgis_auth.manager.unlocked = False
    store.save(EMAIL, TOKEN)
    qgis_auth.manager.unlocked, qgis_auth.manager.broken = True, True
    store.save(EMAIL, TOKEN)
    assert qgis_auth.logged
    assert all(TOKEN not in message for message, _, _ in qgis_auth.logged)


def test_qgis_store_without_qgis_bindings_is_inert(monkeypatch):
    monkeypatch.setitem(sys.modules, "qgis", None)
    monkeypatch.setitem(sys.modules, "qgis.core", None)
    store = ss.QgisSessionStore()
    assert store.load() is None
    store.save(EMAIL, TOKEN)
    store.clear()

