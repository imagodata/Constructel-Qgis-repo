"""Bridge 2.0, tache 6 (plan 2026-11-18, spec § 6.4, § 6.5, § 7) : page
« Check-in » (bridge_home_checkin.CheckinPage) et partages extraits de
l'assistant (bridge_onboarding.configure_resource_sharing /
configure_filtermate_sharing / resource_sharing_configured /
filtermate_configured).

La page tourne sur les doublures de fakes_widgets.py ; le rendu Qt reel
(QWizard integre sans cadre, theme sombre) reste a la recette manuelle."""
from __future__ import annotations

import importlib
import json
import sys
import types

import pytest

from constructel_bridge import bridge_diagnostic as bd
from constructel_bridge import bridge_home_model as hm
from constructel_bridge_tests.fakes_widgets import (
    _Button,
    _Dialog,
    _GroupBox,
    _Label,
    _Layout,
    _Sig,
    _W,
    _texts,
    _widgets,
)
from constructel_bridge_tests.test_bridge19_checkin import onb  # noqa: F401  (onb = fixture)
from constructel_bridge_tests.test_bridge20_home_model import snap

MODULE = "constructel_bridge.bridge_home_checkin"
RS_NAME, RS_URL = "Constructel", "http://rs.test/"


# --- Doublures ----------------------------------------------------------------

class _FakeSettings:
    """QgsSettings : valeurs a plat, groupes lus sur les cles."""

    def __init__(self, values=None):
        self.values = dict(values or {})
        self._groups = []

    def beginGroup(self, prefix):
        self._groups.append(prefix.strip("/"))

    def endGroup(self):
        self._groups.pop()

    def childGroups(self):
        prefix = "/".join(self._groups)
        return sorted({k[len(prefix) + 1:].split("/", 1)[0] for k in self.values
                       if k.startswith(prefix + "/") and "/" in k[len(prefix) + 1:]})

    def value(self, key, default=None, type=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


def _repos(*pairs):
    """Reglages Resource Sharing : un depot par couple (nom, url)."""
    values = {}
    for index, (name, url) in enumerate(pairs):
        values[f"ResourceSharing/repositories/{index}/name"] = name
        values[f"ResourceSharing/repositories/{index}/url"] = url
    return values


class _FakeWizard(_Dialog):
    """QWizard : fenetre integrable, signal finished."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.finished = _Sig()
        self.flags = None

    def setWindowFlags(self, flags):
        self.flags = flags


@pytest.fixture
def ob(onb, monkeypatch):  # noqa: F811
    """bridge_onboarding (doublures de QWizard, onb) avec ses reglages et
    ses extensions installees : Resource Sharing et FilterMate disponibles."""
    from qgis.core import QgsSettings

    monkeypatch.setattr(QgsSettings, "_store", {})
    monkeypatch.setattr(onb, "RESOURCE_SHARING_REPO_URL", RS_URL)
    onb.utils.available_plugins = ["qgis_resource_sharing", "filter_mate"]
    onb.utils.active_plugins = ["qgis_resource_sharing", "filter_mate"]
    return onb


@pytest.fixture
def page_mod(ob, monkeypatch):
    """bridge_home_checkin (et le vrai bridge_diagnostic_dialog) importes sur
    des doublures de widgets ; Resource Sharing / FilterMate branches sur ``ob``."""
    from qgis import core
    from qgis.PyQt import QtCore, QtWidgets

    for name, fake in (("QWidget", _W), ("QDialog", _Dialog), ("QGroupBox", _GroupBox),
                       ("QLabel", _Label), ("QPushButton", _Button),
                       ("QVBoxLayout", _Layout), ("QHBoxLayout", _Layout), ("QGridLayout", _Layout),
                       ("QDialogButtonBox", type("QDialogButtonBox", (), {}))):
        monkeypatch.setattr(QtWidgets, name, fake, raising=False)
    monkeypatch.setattr(core, "QgsTask", type("QgsTask", (), {}), raising=False)
    monkeypatch.setattr(QtCore.Qt, "WindowType", types.SimpleNamespace(Widget=0x0), raising=False)
    monkeypatch.setattr(QtCore.Qt, "TextFormat", types.SimpleNamespace(PlainText=0), raising=False)
    for name in ("bridge_home_checkin", "bridge_diagnostic_dialog"):
        monkeypatch.delitem(sys.modules, f"constructel_bridge.{name}", raising=False)
    module = importlib.import_module(MODULE)
    module.ob = ob
    yield module
    for name in ("bridge_home_checkin", "bridge_diagnostic_dialog"):
        sys.modules.pop(f"constructel_bridge.{name}", None)


def _check(action, pid, name, level="warning", key="plugin"):
    message = {"install": "diag.plugin_missing", "update": "diag.plugin_update",
               "activate": "diag.plugin_inactive", "": "diag.plugin_ok"}[action]
    return bd.Check(key, level, message, {"name": name}, action, pid)


CHECKS = [_check("install", "qfieldsync", "QField Sync"),
          _check("", "filter_mate", "FilterMate", level="ok"),
          bd.Check("version", "ok", "diag.version_ok", {"installed": "2.0.0"})]


class _Actions:
    """HomeActions : appels journalises, reponses preparees par le test."""

    def __init__(self, checks=None, wizard=None):
        self.checks = list(CHECKS if checks is None else checks)
        self.calls = []
        self.after_action = None
        self.sharing_message = "fait"
        self.wizard = wizard

    def diagnostic_inputs(self):
        return ("", list(self.checks), {})

    def diagnostic_action(self, check):
        self.calls.append(("action", check.target))
        if self.after_action is not None:
            self.checks = list(self.after_action)
        return list(self.checks)

    def configure_sharing(self, kind):
        self.calls.append(("configure", kind))
        return self.sharing_message

    def make_wizard(self, parent):
        self.calls.append(("wizard", parent))
        return self.wizard


def _buttons(page):
    return [w for w in _widgets(page) if isinstance(w, _Button)]


def _button(page, text):
    return next(b for b in _buttons(page) if b.text() == text)


def _states(monkeypatch, page_mod, rs, fm):
    monkeypatch.setattr(page_mod, "resource_sharing_configured", lambda settings=None: rs)
    monkeypatch.setattr(page_mod, "filtermate_configured", lambda: fm)


def _page(page_mod, actions, monkeypatch, rs=False, fm=False, **kwargs):
    _states(monkeypatch, page_mod, rs, fm)
    return page_mod.CheckinPage(snap(), actions, **kwargs)


# --- Etat des partages -------------------------------------------------------------

def test_resource_sharing_configured_reads_settings(ob):
    both = _FakeSettings(_repos(("Autre", "http://x/"), (RS_NAME, RS_URL)))
    other_url = _FakeSettings(_repos((RS_NAME, "http://ailleurs/")))
    absent = _FakeSettings(_repos(("Autre", "http://x/")))
    assert ob.resource_sharing_configured(both) is True
    assert ob.resource_sharing_configured(other_url) is False
    assert ob.resource_sharing_configured(absent) is False
    assert ob.resource_sharing_configured(_FakeSettings()) is False
    # Extension absente (ni disponible ni active) : sans objet.
    ob.utils.available_plugins, ob.utils.active_plugins = [], []
    assert ob.resource_sharing_configured(both) is None


def test_resource_sharing_state_needs_no_network_nor_extension_state(ob):
    # Revue finale : l'URL Constructel suffit, quel que soit le nom du depot
    # (meme regle que « Configurer », qui n'y touche pas).
    assert ob.resource_sharing_configured(_FakeSettings(_repos(("Autre", RS_URL)))) is True


def test_configure_resource_sharing_ends_in_a_state_the_check_accepts(ob):
    # Revue finale : un seul predicat. L'URL Constructel sous un autre nom :
    # deja configure, rien n'est change, la pastille s'eteint.
    renamed = _FakeSettings(_repos(("Mon depot", RS_URL)))
    before = dict(renamed.values)
    assert ob.configure_resource_sharing(renamed) == ob.tr("onboard.action.rs_exists", name=RS_NAME)
    assert renamed.values == before
    assert ob.resource_sharing_configured(renamed) is True
    # « Constructel » a une mauvaise URL : non configure, URL corrigee, puis accepte.
    stale = _FakeSettings(_repos(("Autre", "http://x/"), (RS_NAME, "http://perime/")))
    assert ob.resource_sharing_configured(stale) is False
    assert ob.configure_resource_sharing(stale) == ob.tr("onboard.action.rs_updated", name=RS_NAME, url=RS_URL)
    assert stale.values["ResourceSharing/repositories/1/url"] == RS_URL
    assert ob.resource_sharing_configured(stale) is True
    # Les deux a la fois : le depot a la bonne URL suffit, l'autre n'est pas touche.
    both = _FakeSettings(_repos((RS_NAME, "http://perime/"), ("Mon depot", RS_URL)))
    assert ob.configure_resource_sharing(both) == ob.tr("onboard.action.rs_exists", name=RS_NAME)
    assert both.values["ResourceSharing/repositories/0/url"] == "http://perime/"
    # Rien : ajoute, puis accepte.
    empty = _FakeSettings()
    ob.configure_resource_sharing(empty)
    assert ob.resource_sharing_configured(empty) is True


def _fm_config(tmp_path, monkeypatch, repos):
    from qgis.core import QgsApplication

    monkeypatch.setattr(QgsApplication, "qgisSettingsDirPath", staticmethod(lambda: str(tmp_path)), raising=False)
    if repos is not None:
        folder = tmp_path / "FilterMate"
        folder.mkdir()
        (folder / "config.json").write_text(json.dumps(
            {"EXTENSIONS": {"favorites_sharing": {"remote_repos": {"value": repos}}}}), encoding="utf-8")


def test_filtermate_configured_reads_the_json_config(ob, tmp_path, monkeypatch):
    _fm_config(tmp_path, monkeypatch, [{"name": "Autre"}, {"name": "Constructel"}])
    assert ob.filtermate_configured() is True


def test_filtermate_not_configured_without_the_repo_or_the_file(ob, tmp_path, monkeypatch):
    _fm_config(tmp_path, monkeypatch, [{"name": "Autre"}])
    assert ob.filtermate_configured() is False
    other = tmp_path / "vide"
    other.mkdir()
    _fm_config(other, monkeypatch, None)
    assert ob.filtermate_configured() is False


def test_filtermate_absent_is_not_applicable(ob, tmp_path, monkeypatch):
    _fm_config(tmp_path, monkeypatch, [{"name": "Constructel"}])
    ob.utils.available_plugins, ob.utils.active_plugins = [], []
    assert ob.filtermate_configured() is None


def test_filtermate_configured_prefers_the_api(ob, tmp_path, monkeypatch):
    # L'API de FilterMate prime sur le JSON (memes chemins que la configuration).
    _fm_config(tmp_path, monkeypatch, [])           # le JSON dit « absent »

    class _Manager:
        def __init__(self, ext):
            pass

        def get_by_name(self, name):
            return object() if name == "Constructel" else None

    registry = types.SimpleNamespace(get_extension=lambda name: object())
    for name, attrs in (
        ("filter_mate", {}), ("filter_mate.extensions", {}),
        ("filter_mate.extensions.registry", {"get_extension_registry": lambda: registry}),
        ("filter_mate.extensions.favorites_sharing", {}),
        ("filter_mate.extensions.favorites_sharing.remote_repo_manager",
         {"RemoteRepoManager": _Manager, "RemoteRepo": object}),
    ):
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    assert ob.filtermate_configured() is True


# --- Code extrait de l'assistant ----------------------------------------------------

def test_configure_resource_sharing_adds_updates_or_keeps_the_repo(ob):
    settings = _FakeSettings()
    assert ob.configure_resource_sharing(settings) == ob.tr("onboard.action.rs_added", name=RS_NAME, url=RS_URL)
    assert settings.values["ResourceSharing/repositories/0/name"] == RS_NAME
    assert settings.values["ResourceSharing/repositories/0/url"] == RS_URL
    assert settings.values["ResourceSharing/repositories/0/auth_cfg"] == ""
    assert ob.configure_resource_sharing(settings) == ob.tr("onboard.action.rs_exists", name=RS_NAME)
    stale = _FakeSettings(_repos((RS_NAME, "http://perime/")))
    assert ob.configure_resource_sharing(stale) == ob.tr("onboard.action.rs_updated", name=RS_NAME, url=RS_URL)
    assert stale.values["ResourceSharing/repositories/0/url"] == RS_URL


def test_configure_resource_sharing_needs_the_extension(ob):
    ob.utils.available_plugins, ob.utils.active_plugins = [], []
    settings = _FakeSettings()
    assert ob.configure_resource_sharing(settings) == ob.tr("onboard.action.rs_not_installed")
    assert settings.values == {}


def test_configure_resource_sharing_is_the_wizard_code(ob, monkeypatch):
    from qgis.core import QgsSettings

    # Meme message et memes ecritures que le module : l'assistant en est un client.
    expected = ob.configure_resource_sharing()
    written = dict(QgsSettings._store)
    QgsSettings._store.clear()

    seen = []
    real = ob.configure_resource_sharing
    monkeypatch.setattr(ob, "configure_resource_sharing", lambda *a, **k: seen.append(1) or real(*a, **k))
    w = ob.OnboardingWizard(None, "", "", False, include_profile=False)
    w._configure_resource_sharing()

    assert seen == [1]
    assert w._actions_done == [expected] and QgsSettings._store == written


def test_configure_filtermate_sharing_needs_the_extension(ob):
    ob.utils.available_plugins, ob.utils.active_plugins = [], []
    logged = []
    assert ob.configure_filtermate_sharing(logged.append) == ob.tr("onboard.action.fm_not_installed")


def test_configure_filtermate_sharing_is_the_wizard_code(ob, tmp_path, monkeypatch):
    from qgis.core import QgsApplication

    monkeypatch.setattr(QgsApplication, "qgisSettingsDirPath", staticmethod(lambda: str(tmp_path)), raising=False)
    monkeypatch.setattr(ob.shutil, "which", lambda name: "/usr/bin/git")
    first = ob.filtermate_sharing_actions(lambda message, *a: None)
    assert first[0] == ob.tr("onboard.action.fm_git_system", path="/usr/bin/git")
    assert ob.tr("onboard.action.fm_restart_needed") in first            # chemin JSON (pas d'API en test)
    assert ob.filtermate_configured() is True                            # ce qui a ete ecrit est relu
    (tmp_path / "FilterMate" / "config.json").unlink()

    # L'assistant : memes messages, dans le meme ordre, par la meme fonction.
    seen = []
    real = ob.filtermate_sharing_actions
    monkeypatch.setattr(ob, "filtermate_sharing_actions",
                        lambda *a, **k: seen.append(1) or real(*a, **k))
    w = ob.OnboardingWizard(None, "", "", False, include_profile=False)
    w._page_summary = _Dummy()
    w._configure_filtermate_sharing()
    assert seen == [1] and w._actions_done == first


def test_configure_filtermate_sharing_joins_the_messages(ob, monkeypatch):
    monkeypatch.setattr(ob, "filtermate_sharing_actions", lambda log, progress=None: ["un", "deux"])
    assert ob.configure_filtermate_sharing(lambda message, *a: None) == "un\ndeux"


class _Dummy:
    def set_summary(self, text):
        pass


# --- Page ---------------------------------------------------------------------------

def test_page_lists_plugins_with_actions_and_sharing_rows(page_mod, monkeypatch):
    actions = _Actions()
    page = _page(page_mod, actions, monkeypatch, rs=True, fm=False)
    texts = _texts(page)
    # Profil (login de l'en-tete), puis une ligne par extension (pas la version).
    assert "jdoe" in " ".join(texts)
    assert page_mod.check_message(CHECKS[0]) in texts and page_mod.check_message(CHECKS[1]) in texts
    assert page_mod.check_message(CHECKS[2]) not in texts
    # Bouton d'action de la seule ligne qui en a une.
    assert page_mod.action_label("install") in [b.text() for b in _buttons(page)]
    assert len([b for b in _buttons(page) if b.text() == page_mod.action_label("install")]) == 1
    # Partages : Resource Sharing configure, FilterMate a configurer (bouton).
    assert page_mod.tr("home.rs_configured") in texts and page_mod.tr("home.fm_missing") in texts
    assert [b.text() for b in _buttons(page)].count(page_mod.tr("home.configure")) == 1
    assert _button(page, page_mod.tr("home.checkin_full")) is page._wizard_button


def test_sharing_not_applicable_has_no_configure_button(page_mod, monkeypatch):
    page = _page(page_mod, _Actions(), monkeypatch, rs=None, fm=None)
    assert [b.text() for b in _buttons(page)].count(page_mod.tr("home.configure")) == 0
    assert _texts(page).count(page_mod.tr("home.sharing_na")) == 2


def test_offline_profile_text(page_mod, monkeypatch):
    _states(monkeypatch, page_mod, None, None)
    page = page_mod.CheckinPage(snap(connected=False, header=""), _Actions())
    assert page_mod.tr("home.checkin_profile_offline") in _texts(page)


def test_profile_reads_the_login_field_not_the_header(page_mod, monkeypatch):
    # Tache 9 : login et e-mail sont des champs de HomeSnapshot (plus de
    # decoupage de l'en-tete « login · perimetre »).
    _states(monkeypatch, page_mod, None, None)
    page = page_mod.CheckinPage(snap(header="Bruxelles · 10 MRO", login="s.ducournau"), _Actions())
    profile = page._profile_label.text()
    assert profile == page_mod.tr("home.checkin_profile", login="s.ducournau") and "Bruxelles" not in profile
    page = page_mod.CheckinPage(snap(login=""), _Actions())
    assert page._profile_label.text() == page_mod.tr("home.checkin_profile_offline")


def test_email_is_shown_when_known(page_mod, monkeypatch):
    _states(monkeypatch, page_mod, None, None)
    page = page_mod.CheckinPage(snap(), _Actions(), email="jdoe@constructel.be")
    assert any("jdoe@constructel.be" in t for t in _texts(page))


def test_plugin_action_runs_then_redraws_with_the_new_checks(page_mod, monkeypatch):
    actions = _Actions()
    actions.after_action = [_check("", "qfieldsync", "QField Sync", level="ok"), CHECKS[1]]
    page = _page(page_mod, actions, monkeypatch)
    changes = []
    page.on_change = lambda: changes.append(1)

    _button(page, page_mod.action_label("install")).clicked.emit()

    assert actions.calls == [("action", "qfieldsync")]
    assert page_mod.action_label("install") not in [b.text() for b in _buttons(page)]
    assert changes == [1] and page.isEnabled()


def test_configure_button_calls_action_then_refreshes(page_mod, monkeypatch):
    actions = _Actions()
    _states(monkeypatch, page_mod, True, False)
    page = page_mod.CheckinPage(snap(), actions)
    changes = []
    page.on_change = lambda: changes.append(1)
    # Apres l'action, FilterMate est configure.
    monkeypatch.setattr(page_mod, "filtermate_configured", lambda: True)

    _button(page, page_mod.tr("home.configure")).clicked.emit()

    assert actions.calls == [("configure", "filtermate")]
    texts = _texts(page)
    assert page_mod.tr("home.fm_configured") in texts and page_mod.tr("home.fm_missing") not in texts
    assert "fait" in texts                  # message de l'action affiche
    assert changes == [1]


def test_resource_sharing_configure_uses_its_kind(page_mod, monkeypatch):
    actions = _Actions()
    page = _page(page_mod, actions, monkeypatch, rs=False, fm=True)
    _button(page, page_mod.tr("home.configure")).clicked.emit()
    assert actions.calls == [("configure", "resource_sharing")]


def test_full_checkin_hosts_the_wizard_in_the_page(page_mod, monkeypatch):
    wizard = _FakeWizard()
    actions = _Actions(wizard=wizard)
    page = _page(page_mod, actions, monkeypatch)
    changes = []
    page.on_change = lambda: changes.append(1)
    layout = page.layout
    assert wizard not in layout.items and page._wizard is None

    page._wizard_button.clicked.emit()

    assert actions.calls == [("wizard", page)]
    assert wizard.flags == page_mod.Qt.WindowType.Widget
    assert wizard in layout.items and page._wizard is wizard
    assert page._rows.hidden and page._wizard_button.hidden       # lignes remplacees par l'assistant

    # Fin de l'assistant : retire, lignes revenues et rafraichies, fenetre prevenue.
    actions.checks = [_check("", "qfieldsync", "QField Sync", level="ok"), CHECKS[1]]
    wizard.finished.emit(1)

    assert wizard not in layout.items and page._wizard is None and wizard.deleted
    assert page_mod.action_label("install") not in [b.text() for b in _buttons(page)]
    assert not page._rows.hidden and not page._wizard_button.hidden
    assert changes == [1]


def test_wizard_button_does_nothing_without_a_wizard(page_mod, monkeypatch):
    actions = _Actions(wizard=None)
    page = _page(page_mod, actions, monkeypatch)
    page._wizard_button.clicked.emit()
    assert page._wizard is None


def test_start_wizard_opens_it_immediately(page_mod, monkeypatch):
    wizard = _FakeWizard()
    actions = _Actions(wizard=wizard)
    page = _page(page_mod, actions, monkeypatch, start_wizard=True)
    assert page._wizard is wizard and wizard in page.layout.items


def test_wizard_is_not_started_twice(page_mod, monkeypatch):
    actions = _Actions(wizard=_FakeWizard())
    page = _page(page_mod, actions, monkeypatch, start_wizard=True)
    page._wizard_button.clicked.emit()
    assert [c[0] for c in actions.calls].count("wizard") == 1


# --- Textes ---------------------------------------------------------------------------

KEYS = ("home.checkin_title", "home.checkin_profile", "home.checkin_profile_offline", "home.checkin_plugins",
        "home.checkin_sharing", "home.rs_configured", "home.rs_missing", "home.fm_configured",
        "home.fm_missing", "home.sharing_na", "home.configure", "home.checkin_full")


def test_checkin_texts_in_the_three_languages():
    from constructel_bridge.i18n.translations import TRANSLATIONS

    for lang in ("fr", "en", "pt"):
        for key in KEYS:
            assert TRANSLATIONS[lang][key].strip(), (lang, key)
    assert TRANSLATIONS["fr"]["home.checkin_full"] == "Refaire le check-in complet"
    assert TRANSLATIONS["fr"]["home.sharing_na"] == "extension non installée"
