"""Bridge 1.9 (tache 7, spec § 6.6, decision D14) : le check-in est
lancable SANS connexion a la base Farois.

  * sans profil, la page Profil (la seule qui ecrit via db_conn) n'est pas
    enregistree et l'assistant demarre sur les plugins recommandes ; le
    resume indique « Profil : disponible une fois connecte » ;
  * hors connexion, rien ne tente la base (doublure qui leve si on la touche) ;
  * ``install_or_activate_plugin`` (K12) est l'UNIQUE chemin d'installation :
    ``_install_selected_plugins`` l'appelle, le Diagnostic (tache 8) aussi.

Les stubs n'ont pas de vrai QWizard : le fixture ``onb`` installe une
doublure de QWizard / QWizardPage et un ``qgis.utils`` factice AVANT
d'importer bridge_onboarding (la classe herite de QWizard a l'import), puis
remplace les six pages par des fabriques neutres. Le rendu Qt reste donc hors
de portee (recette manuelle, tache 10)."""
from __future__ import annotations

import importlib
import sys
import types

import pytest


# --- Doublures --------------------------------------------------------------

class _Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class FakeWizardPage:
    def __init__(self, *_args, **_kwargs):
        pass


class FakeWizard:
    """Sous-ensemble de QWizard : memorise les pages et la page de depart."""

    class WizardStyle:
        ModernStyle = 0

    def __init__(self, parent=None):
        self.page_ids = []
        self.pages = {}
        self.start_id = None
        self.currentIdChanged = _Signal()

    def setWindowTitle(self, *_args):
        pass

    def setMinimumWidth(self, *_args):
        pass

    def setMinimumHeight(self, *_args):
        pass

    def setWizardStyle(self, *_args):
        pass

    def setPage(self, page_id, page):
        self.page_ids.append(page_id)
        self.pages[page_id] = page

    def setStartId(self, page_id):
        self.start_id = page_id


class _Page:
    """Page neutre : choix de l'utilisateur injectes par le test."""

    def __init__(self, selected=(), configure=False):
        self.selected = list(selected)
        self.configure = configure
        self.summary = None

    def get_selected_plugins(self):
        return list(self.selected)

    def should_configure(self):
        return self.configure

    def set_summary(self, text):
        self.summary = text


class _Boom:
    """db_conn qui echoue des qu'on s'en sert : prouve que rien n'atteint la base."""

    def __getattr__(self, name):
        raise AssertionError(f"la base ne doit pas etre touchee hors connexion ({name})")


class _FakeInstaller:
    def __init__(self, calls, fail=()):
        self.calls = calls
        self.fail = set(fail)

    def fetchAvailablePlugins(self, reload_mode):
        self.calls.append(("fetch", reload_mode))

    def installPlugin(self, pid):
        self.calls.append(("install", pid))
        if pid in self.fail:
            raise RuntimeError(f"echec {pid}")


@pytest.fixture
def onb(bp18, monkeypatch):
    """bridge_onboarding importe sur des doublures de QWizard et de qgis.utils.
    ``onb.calls`` journalise l'installeur, ``onb.started`` les plugins demarres."""
    from qgis.PyQt import QtCore, QtGui, QtWidgets

    for module, names in (
        (QtWidgets, ("QApplication", "QCheckBox", "QFormLayout", "QFrame", "QGroupBox",
                     "QHBoxLayout", "QLabel", "QLineEdit", "QScrollArea", "QVBoxLayout",
                     "QWidget")),
        (QtGui, ("QCursor", "QFont")),
        (QtCore, ("QCoreApplication",)),
    ):
        for name in names:
            if not hasattr(module, name):
                monkeypatch.setattr(module, name, type(name, (), {}), raising=False)
    monkeypatch.setattr(QtWidgets, "QWizard", FakeWizard, raising=False)
    monkeypatch.setattr(QtWidgets, "QWizardPage", FakeWizardPage, raising=False)

    started, calls = [], []
    utils = types.ModuleType("qgis.utils")
    utils.available_plugins = ["a", "b"]
    utils.active_plugins = ["a"]
    utils.loadPlugin = lambda pid: True
    utils.startPlugin = lambda pid: started.append(pid) or True
    monkeypatch.setitem(sys.modules, "qgis.utils", utils)

    installer = _FakeInstaller(calls)
    installer_module = types.ModuleType("pyplugin_installer")
    installer_module.instance = lambda: installer
    monkeypatch.setitem(sys.modules, "pyplugin_installer", installer_module)

    monkeypatch.delitem(sys.modules, "constructel_bridge.bridge_onboarding", raising=False)
    module = importlib.import_module("constructel_bridge.bridge_onboarding")
    for cls in ("UserProfilePage", "PluginBundlePage", "ResourceSharingPage",
                "FilterMateSharingPage", "ExternalServicesPage", "SummaryPage"):
        monkeypatch.setattr(module, cls, lambda *a, **k: _Page())
    module.calls, module.started, module.installer = calls, started, installer
    yield module
    sys.modules.pop("constructel_bridge.bridge_onboarding", None)


# --- Assistant sans profil ----------------------------------------------------

def test_wizard_without_profile_skips_user_page(onb):
    w = onb.OnboardingWizard(None, "", "", False, include_profile=False)
    cls = onb.OnboardingWizard
    assert w.page_ids == [cls.PAGE_PLUGINS, cls.PAGE_RESOURCE_SHARING, cls.PAGE_FILTERMATE,
                          cls.PAGE_SERVICES, cls.PAGE_SUMMARY]
    assert w.start_id == cls.PAGE_PLUGINS


def test_wizard_with_profile_registers_user_page_first(onb):
    w = onb.OnboardingWizard(None, "SimonDucourneau", "id-1", False)
    cls = onb.OnboardingWizard
    assert w.page_ids[0] == cls.PAGE_USER and len(w.page_ids) == 6
    assert w.start_id in (None, cls.PAGE_USER)


def test_offline_summary_mentions_profile_later(onb):
    w = onb.OnboardingWizard(None, "", "", False, include_profile=False)
    w._update_user_profile()
    assert w._actions_done == [onb.tr("onboard.action.profile_offline")]


def test_profile_offline_text_in_the_three_languages():
    from constructel_bridge.i18n.translations import TRANSLATIONS

    assert TRANSLATIONS["fr"]["onboard.action.profile_offline"] == "Profil : disponible une fois connecté"
    for lang in ("en", "pt"):
        assert TRANSLATIONS[lang]["onboard.action.profile_offline"].strip()


def test_offline_execution_never_touches_the_database(onb):
    from qgis.core import QgsSettings

    QgsSettings().remove("constructel_bridge/onboarding_done")
    w = onb.OnboardingWizard(None, "", "", False, db_conn=_Boom(), include_profile=False)
    w._page_plugins = _Page()
    w._page_rs = _Page(configure=False)
    w._page_fm = _Page(configure=False)
    w._page_summary = _Page()

    w._execute_actions()  # _Boom leve si _db_conn est lu

    summary = w._page_summary.summary
    assert onb.tr("onboard.action.profile_offline") in summary
    assert onb.tr("onboard.action.no_plugins") in summary
    # Profil encore a faire : l'assistant n'est pas marque termine (la premiere
    # connexion le proposera avec sa page Profil).
    assert onb.tr("onboard.action.onboarding_done") not in summary
    assert not QgsSettings().value("constructel_bridge/onboarding_done", False)


def test_connected_execution_marks_the_onboarding_done(onb):
    from qgis.core import QgsSettings

    QgsSettings().remove("constructel_bridge/onboarding_done")
    w = onb.OnboardingWizard(None, "SimonDucourneau", "id-1", False, db_conn=None)
    w._page_plugins, w._page_rs, w._page_fm, w._page_summary = _Page(), _Page(), _Page(), _Page()

    w._execute_actions()

    assert QgsSettings().value("constructel_bridge/onboarding_done", False) is True
    assert onb.tr("onboard.action.onboarding_done") in w._page_summary.summary


def test_online_profile_page_still_skips_silently_without_connection(onb):
    # Session nominative : la page Profil est montree mais db_conn vaut None.
    w = onb.OnboardingWizard(None, "SimonDucourneau", "id-1", False, db_conn=None)
    w._update_user_profile()
    assert w._actions_done == []


# --- install_or_activate_plugin (K12) ------------------------------------------

def test_install_or_activate_plugin(onb):
    # disponibles {a, b}, actifs {a}
    assert onb.install_or_activate_plugin("a") == "active"
    assert onb.install_or_activate_plugin("b") == "activated" and onb.started == ["b"]
    assert onb.install_or_activate_plugin("c") == "installed" and ("install", "c") in onb.calls
    assert onb.install_or_activate_plugin("a", upgrade=True) == "updated"
    assert ("install", "a") in onb.calls


def test_install_fetches_the_installer_cache_before_installing(onb):
    onb.install_or_activate_plugin("c")
    assert onb.calls == [("fetch", False), ("install", "c")]


def test_active_or_inactive_plugin_needs_no_installer(onb, monkeypatch):
    def refuse():
        raise AssertionError("l'installeur ne sert qu'a installer")

    monkeypatch.setitem(sys.modules, "pyplugin_installer",
                        types.SimpleNamespace(instance=refuse))
    assert onb.install_or_activate_plugin("a") == "active"
    assert onb.install_or_activate_plugin("b") == "activated"


def test_install_failure_raises(onb):
    onb.installer.fail.add("c")
    with pytest.raises(RuntimeError, match="echec c"):
        onb.install_or_activate_plugin("c")


def test_missing_installer_raises(onb, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyplugin_installer", None)  # ImportError
    with pytest.raises(onb.PluginInstallerUnavailable):
        onb.install_or_activate_plugin("c")


def test_selected_plugins_go_through_install_or_activate(onb, monkeypatch):
    seen = []
    results = {"a": "active", "b": "activated", "c": "installed"}
    monkeypatch.setattr(onb, "install_or_activate_plugin",
                        lambda pid, upgrade=False: seen.append(pid) or results[pid])
    w = onb.OnboardingWizard(None, "", "", False, include_profile=False)
    w._page_plugins = _Page(["a", "b", "c"])

    w._install_selected_plugins()

    assert seen == ["a", "b", "c"]
    assert w._actions_done == [onb.tr("onboard.action.plugin_activated", pid="b"),
                               onb.tr("onboard.action.plugin_installed", pid="c")]


def test_selected_plugin_failure_is_reported_and_does_not_stop_the_others(onb):
    onb.installer.fail.add("c")
    w = onb.OnboardingWizard(None, "", "", False, include_profile=False)
    w._page_plugins = _Page(["c", "b"])

    w._install_selected_plugins()

    assert w._actions_done[0] == onb.tr("onboard.action.plugin_error", pid="c", error="echec c")
    assert w._actions_done[1] == onb.tr("onboard.action.plugin_activated", pid="b")


def test_unavailable_installer_is_reported_once(onb, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyplugin_installer", None)
    w = onb.OnboardingWizard(None, "", "", False, include_profile=False)
    w._page_plugins = _Page(["c", "d", "b"])

    w._install_selected_plugins()

    assert len(w._actions_done) == 2
    assert w._actions_done[0] == onb.tr(
        "onboard.action.installer_unavailable",
        error="import of pyplugin_installer halted; None in sys.modules")
    assert w._actions_done[1] == onb.tr("onboard.action.plugin_activated", pid="b")


# --- Plugin : _on_onboarding sans connexion --------------------------------------

class _FakeBar:
    def pushMessage(self, *a, **k):
        pass

    pushWarning = pushCritical = pushInfo = pushSuccess = pushMessage


class _FakeIface:
    def mainWindow(self):
        return None

    def messageBar(self):
        return _FakeBar()

    def activeLayer(self):
        return None


@pytest.fixture
def checkin(bp18, monkeypatch):
    """(plugin, created) : le plugin lance un assistant enregistreur."""
    from qgis.core import QgsSettings

    QgsSettings().setValue("constructel_bridge/onboarding_done", True)
    created = []

    class _RecordingWizard:
        def __init__(self, **kwargs):
            created.append(kwargs)

        def exec(self):
            return 0

    fake = types.ModuleType("constructel_bridge.bridge_onboarding")
    fake.OnboardingWizard = _RecordingWizard
    monkeypatch.setitem(sys.modules, "constructel_bridge.bridge_onboarding", fake)
    return bp18.ConstructelBridgePlugin(_FakeIface()), created


def test_checkin_opens_offline_without_profile(checkin):
    plugin, created = checkin
    plugin._connected = False
    plugin._conn = _Boom()  # reliquat : ne doit ni etre transmis ni etre interroge

    plugin._on_onboarding()

    assert len(created) == 1
    assert created[0]["include_profile"] is False and created[0]["db_conn"] is None


def test_checkin_offline_does_not_warn_nor_refresh_identity(checkin, monkeypatch, bp18):
    plugin, created = checkin
    plugin._connected = False
    warnings = []
    monkeypatch.setattr(bp18.QMessageBox, "warning", lambda *a, **k: warnings.append(a), raising=False)
    refreshed = []
    monkeypatch.setattr(plugin, "_refresh_audit_identity", lambda: refreshed.append(1))

    plugin._on_onboarding()

    assert warnings == [] and refreshed == []


def test_checkin_connected_keeps_profile(checkin):
    plugin, created = checkin
    conn = types.SimpleNamespace(closed=True)
    plugin._connected = True
    plugin._auth_mode = "shared"
    plugin._conn = conn

    plugin._on_onboarding()

    assert created[0]["include_profile"] is True and created[0]["db_conn"] is conn


def test_checkin_connected_nominal_keeps_profile_page_without_db_writes(checkin, bp18):
    plugin, created = checkin
    plugin._connected = True
    plugin._auth_mode = bp18.AUTH_MODE_NOMINAL
    plugin._conn = types.SimpleNamespace(closed=True)

    plugin._on_onboarding()

    assert created[0]["include_profile"] is True and created[0]["db_conn"] is None


def test_first_connection_onboarding_still_includes_the_profile(checkin):
    plugin, created = checkin
    plugin._connected = True
    plugin._auth_mode = "shared"

    plugin._run_onboarding(True)

    assert created[0]["include_profile"] is True and created[0]["is_new_user"] is True


def test_import_error_of_a_broken_plugin_is_not_an_unavailable_installer(onb, monkeypatch):
    # startPlugin d'un plugin casse leve ImportError : message de plugin, pas d'installeur.
    def broken(pid):
        raise ImportError("No module named 'dep'")

    monkeypatch.setattr(onb, "startPlugin", broken)
    w = onb.OnboardingWizard(None, "", "", False, include_profile=False)
    w._page_plugins = _Page(["b"])

    w._install_selected_plugins()

    assert w._actions_done == [onb.tr("onboard.action.plugin_error", pid="b", error="No module named 'dep'")]
