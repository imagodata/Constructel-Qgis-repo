"""Bridge 1.8, revue du 29/10 — décisions D-TLS-1 / D-TLS-2.

D-TLS-1 : les CA embarquées sont importées dans la base d'authentification
QGIS (QgsAuthBasicMethod remplace tout sslrootcert= d'une couche authcfg en
verify-* par les CA de confiance de QGIS) ; plus aucun root.crt écrit sur le
poste.
D-TLS-2 : session nominative en verify-full obligatoire ; identifiant
partagé (repli D7, secours admin) en require exactement comme 1.7.x ; un
préprocesseur QgsPathResolver force verify-full sur les couches qui
recevront le mot de passe AD (authcfg 9i19s56/07254s7 quand ces configs le
portent) avant même leur création.

Stub-level : la vérification en vrai QGIS est dans scripts/qgis_smoke.py.
"""
import pytest

from constructel_bridge import bridge_nominatif as bn
from constructel_bridge_tests.conftest import HOST18


class _FakeIface:
    def mainWindow(self):
        return None


def _log_messages(level=None):
    from qgis.core import QgsMessageLog

    return [m for (m, _t, lvl) in QgsMessageLog._messages if level is None or lvl == level]


def _mgr():
    from qgis.core import QgsApplication

    return QgsApplication.authManager()


# --- D-TLS-1 : import des CA dans la base d'authentification QGIS --------------


def test_both_cas_are_imported_as_trusted_and_caches_rebuilt(bp18):
    from qgis.core import QgsAuthCertUtils

    assert bp18._ensure_qgis_trusted_cas() is True

    mgr = _mgr()
    assert len(mgr._cas) == 2
    assert set(mgr._trust) == set(mgr._cas)
    assert set(mgr._trust.values()) == {QgsAuthCertUtils.CertTrustPolicy.Trusted}
    assert mgr._cache_rebuilds == ["ca", "trust", "trusted"]


def test_import_is_idempotent(bp18, monkeypatch):
    assert bp18._ensure_qgis_trusted_cas() is True
    mgr = _mgr()
    stored = []
    monkeypatch.setattr(type(mgr), "storeCertAuthority", lambda self, cert: stored.append(cert) or True)
    monkeypatch.setattr(type(mgr), "storeCertTrustPolicy", lambda self, cert, p: stored.append(cert) or True)

    assert bp18._ensure_qgis_trusted_cas() is True

    assert stored == []
    assert mgr._cache_rebuilds == ["ca", "trust", "trusted"]  # pas de reconstruction inutile


def test_untrusted_existing_ca_gets_trusted_again(bp18):
    from qgis.core import QgsAuthCertUtils

    assert bp18._ensure_qgis_trusted_cas() is True
    mgr = _mgr()
    first = next(iter(mgr._trust))
    mgr._trust[first] = QgsAuthCertUtils.CertTrustPolicy.Untrusted

    assert bp18._ensure_qgis_trusted_cas() is True

    assert mgr._trust[first] == QgsAuthCertUtils.CertTrustPolicy.Trusted


def test_import_failure_is_logged_and_reported(bp18):
    from qgis.core import Qgis

    type(_mgr())._ca_store_fails = True

    assert bp18._ensure_qgis_trusted_cas() is False
    assert any(bp18.tr("nominal.ca_import_failed") in m for m in _log_messages(Qgis.MessageLevel.Critical))


def test_disabled_auth_manager_means_no_import(bp18, monkeypatch):
    monkeypatch.setattr(type(_mgr()), "isDisabled", lambda self: True)
    assert bp18._ensure_qgis_trusted_cas() is False


def test_no_root_crt_helper_left(bp18):
    assert not hasattr(bp18, "_ensure_root_crt")
    assert not hasattr(bn, "upsert_root_crt_pem")
    assert not hasattr(bn, "root_crt_file_path")


# --- D-TLS-2 : entrées navigateur ------------------------------------------------


@pytest.mark.parametrize("login, expected", [("jdoe", "5"), (None, "3")])
def test_browser_entry_sslmode_nominal_vs_shared(bp18, login, expected):
    from qgis.core import QgsSettings

    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._setup_qgis_pg_connection("pw", use_authcfg=True, login=login)
    assert QgsSettings().value("PostgreSQL/connections/wyre/sslmode") == expected


# --- D-TLS-2 : préprocesseur des datasources lues dans un projet ---------------

SHARED_SAVED = (f"dbname='test_db' host={HOST18} port=5432 user='ftth_editor' sslmode=require "
                "authcfg=9i19s56 key='id' table=\"wyre\".\"ducts\" (geom) sql=\"x\" = 'sslmode=require'")


def _plugin(bp, *, connected=None, mode=None, memorized=None):
    from qgis.core import QgsSettings

    if memorized is not None:
        QgsSettings().setValue(bn.NOMINAL_SETTINGS_KEYS["auth_mode"], memorized)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())
    if connected is not None:
        plugin._connected = connected
        plugin._auth_mode = mode
    return plugin


def test_nominal_session_forces_verify_full_on_our_fixed_authcfg(bp18):
    plugin = _plugin(bp18, connected=True, mode=bn.AUTH_MODE_NOMINAL)
    out = plugin._nominal_source_preprocessor(SHARED_SAVED)
    assert bn.datasource_param(out, "sslmode") == "verify-full"
    assert bn.datasource_param(out, "authcfg") == "9i19s56"
    assert out.endswith("sql=\"x\" = 'sslmode=require'")


def test_before_startup_probe_memorized_nominal_counts_as_nominal(bp18):
    plugin = _plugin(bp18, memorized=bn.AUTH_MODE_NOMINAL)
    assert bn.datasource_param(plugin._nominal_source_preprocessor(SHARED_SAVED), "sslmode") == "verify-full"


@pytest.mark.parametrize("source", [
    SHARED_SAVED.replace("authcfg=9i19s56", "authcfg=zzz9999"),            # config d'un tiers
    SHARED_SAVED.replace("authcfg=9i19s56", "authcfg=zzz9999").replace(HOST18, "other.example.com"),
    SHARED_SAVED.replace("authcfg=9i19s56 ", "password='x' "),             # pas de config fixe
    "/home/jdoe/projets/ducts.gpkg|layername=ducts",                       # chemin de fichier
])
def test_preprocessor_leaves_other_sources_alone(bp18, source):
    plugin = _plugin(bp18, connected=True, mode=bn.AUTH_MODE_NOMINAL)
    assert plugin._nominal_source_preprocessor(source) == source


def test_shared_session_keeps_17x_require(bp18):
    plugin = _plugin(bp18, connected=True, mode=bn.AUTH_MODE_SHARED)
    assert plugin._nominal_source_preprocessor(SHARED_SAVED) == SHARED_SAVED
    unconnected = _plugin(bp18, memorized=bn.AUTH_MODE_SHARED)
    assert unconnected._nominal_source_preprocessor(SHARED_SAVED) == SHARED_SAVED


def test_preprocessor_never_raises(bp18, monkeypatch):
    plugin = _plugin(bp18, connected=True, mode=bn.AUTH_MODE_NOMINAL)
    monkeypatch.setattr(bp18, "datasource_param", lambda *a: 1 / 0)
    assert plugin._nominal_source_preprocessor(SHARED_SAVED) == SHARED_SAVED


def test_preprocessor_is_removed_by_unload(bp18, monkeypatch):
    from qgis.core import QgsPathResolver

    plugin = _plugin(bp18)
    monkeypatch.setattr(bp18, "unregister_expressions", lambda: None)
    pid = QgsPathResolver.setPathPreprocessor(plugin._nominal_source_preprocessor)
    plugin._path_preprocessor_id = pid
    plugin._actions = []

    plugin.unload()

    assert pid not in QgsPathResolver._preprocessors
    assert plugin._path_preprocessor_id is None



# --- revue 2 (I-7) : nos configs fixes ne partent jamais vers un hôte tiers ---------


@pytest.mark.parametrize("mode", [bn.AUTH_MODE_NOMINAL, bn.AUTH_MODE_SHARED])
@pytest.mark.parametrize("host", ["other.example.com", f"{HOST18}.evil.example.com", f"'{HOST18}0'"])
def test_our_fixed_config_is_stripped_for_a_third_party_host(bp18, mode, host):
    plugin = _plugin(bp18, connected=True, mode=mode)
    source = SHARED_SAVED.replace(f"host={HOST18}", f"host={host}").replace(
        "port=5432 user='ftth_editor' sslmode=require", "port=5432 user='ftth_editor' sslmode=disable")

    out = plugin._nominal_source_preprocessor(source)

    assert bn.datasource_param(out, "authcfg") is None
    assert bn.datasource_param(out, "sslmode") == "disable"
    assert out.endswith("sql=\"x\" = 'sslmode=require'")


def test_fix_layer_credentials_strips_our_config_from_a_third_party_layer(bp18):
    from qgis.core import QgsProject

    from constructel_bridge_tests.test_bridge18_layers import _make_fake_layer

    plugin = _plugin(bp18, connected=True, mode=bn.AUTH_MODE_NOMINAL)
    plugin._pg_login = "jdoe"
    layer = _make_fake_layer("dbname='o' host=other.example.com port=5432 user='jdoe' authcfg=9i19s56 "
                             "table=\"s\".\"t\"", valid=True)
    QgsProject.instance().addMapLayer(layer)

    plugin._fix_layer_credentials()

    assert len(layer.rewritten) == 1
    assert bn.datasource_param(layer.source(), "authcfg") is None
    assert bn.datasource_param(layer.source(), "host") == "other.example.com"


# --- revue 2 (I-4) : identité AD laissée dans 9i19s56 (mot de passe maître refusé) ----


def _declined_master_password(bp, monkeypatch):
    from qgis.core import QgsApplication

    mgr_cls = type(QgsApplication.authManager())
    monkeypatch.setattr(mgr_cls, "masterPasswordIsSet", lambda self: False)
    monkeypatch.setattr(mgr_cls, "setMasterPassword", lambda self, *a: False)


def test_writing_a_nominal_identity_raises_the_persistent_flag(bp18):
    from qgis.core import QgsSettings

    assert bp18._ad_identity_flag() is False
    bp18._store_password_encrypted("shared-pw", "wyre")
    assert bp18._ad_identity_flag() is False
    bp18._store_password_encrypted("ad-pw", "be", username="jdoe")
    assert str(QgsSettings().value(bp18.AD_IDENTITY_KEY)).lower() == "true"


def test_flag_is_lowered_only_once_no_config_carries_the_ad_identity(bp18, monkeypatch):
    from qgis.core import QgsApplication

    bp18._store_password_encrypted("ad-pw", "wyre", username="jdoe")
    bp18._store_password_encrypted("ad-pw", "be", username="jdoe")
    bp18._store_password_encrypted("shared-pw", "wyre")
    assert bp18._refresh_ad_identity_flag() is True  # 07254s7 porte encore jdoe

    QgsApplication.authManager().removeAuthenticationConfig("07254s7")
    _declined_master_password(bp18, monkeypatch)
    assert bp18._refresh_ad_identity_flag() is True  # 9i19s56 illisible : maintenu

    monkeypatch.undo()
    assert bp18._refresh_ad_identity_flag() is False


def test_declined_master_password_keeps_verify_full_on_our_configs(bp18, monkeypatch, tmp_path):
    # Sonde de revue : le repli partage « local_setup » laissait 9i19s56
    # (login + mot de passe AD) en require via le preprocesseur.
    from constructel_bridge_tests.test_bridge18_connect import _make_plugin, _start, _config, LOGIN

    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw",
                              memorized=bn.AUTH_MODE_NOMINAL)
    assert bp18._store_password_encrypted("ad-pw", "wyre", username=LOGIN)
    _declined_master_password(bp18, monkeypatch)

    _start(plugin)

    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    assert _config("9i19s56").config("username") == LOGIN  # non reecrite (pas de mot de passe maitre)
    assert bp18._ad_identity_flag() is True
    out = plugin._nominal_source_preprocessor(SHARED_SAVED)
    assert bn.datasource_param(out, "sslmode") == "verify-full"


def test_shared_fix_with_ad_identity_never_attaches_to_9i19s56(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsProject, QgsSettings

    from constructel_bridge_tests.test_bridge18_layers import _make_fake_layer

    plugin = _plugin(bp18, connected=True, mode=bn.AUTH_MODE_SHARED)
    plugin._password = "shared-pw"
    bp18._store_password_encrypted("ad-pw", "wyre", username="jdoe")
    QgsSettings().setValue(bp18.AD_IDENTITY_KEY, True)
    attached = _make_fake_layer(SHARED_SAVED.split(" sql=")[0], valid=True)
    colleague = _make_fake_layer(SHARED_SAVED.split(" sql=")[0].replace("authcfg=9i19s56", "")
                                 .replace("user='ftth_editor'", "user='alice'"), valid=True)
    for layer in (attached, colleague):
        QgsProject.instance().addMapLayer(layer)
    monkeypatch.setattr(plugin, "_apply_db_default_styles", lambda: None)

    plugin._fix_layer_credentials()

    assert bn.datasource_param(attached.source(), "authcfg") == "9i19s56"
    assert bn.datasource_param(attached.source(), "sslmode") == "verify-full"
    assert bn.datasource_param(colleague.source(), "authcfg") is None
    assert bn.datasource_param(colleague.source(), "user") == "ftth_editor"


def test_unreadable_be_config_with_ad_identity_is_removed_in_shared_mode(bp18, monkeypatch):
    from qgis.core import QgsApplication, QgsSettings

    bp18._store_password_encrypted("ad-pw", "be", username="jdoe")
    QgsSettings().setValue(bp18.AD_IDENTITY_KEY, True)
    plugin = _plugin(bp18, connected=True, mode=bn.AUTH_MODE_SHARED)
    _declined_master_password(bp18, monkeypatch)

    plugin._neutralize_nominal_be()

    assert "07254s7" not in QgsApplication.authManager().configIds()


# --- revue 2 (I-5) : plugin active ou recharge avec un projet ouvert ----------------


def test_layers_already_open_get_verify_full_when_the_session_turns_nominal(bp18, monkeypatch, tmp_path):
    # Sonde de revue : chemin QTimer -> phase silencieuse sans correction des couches.
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QTimer

    from constructel_bridge_tests.test_bridge18_connect import (
        LOGIN, QGIS_USER, _FakeCursor, _initgui_ready, _install_psycopg2)
    from constructel_bridge_tests.test_bridge18_layers import _make_fake_layer

    iface = _initgui_ready(bp18, monkeypatch, visible=True)
    _install_psycopg2(monkeypatch, [None], _FakeCursor())
    bp18._store_password_encrypted("ad-pw", "ad", username=LOGIN)
    layer = _make_fake_layer(SHARED_SAVED.split(" sql=")[0], valid=True)
    QgsProject.instance().addMapLayer(layer)
    plugin = bp18.ConstructelBridgePlugin(iface)
    plugin._get_qgis_username = lambda: QGIS_USER

    plugin.initGui()
    QTimer.run_pending()

    assert plugin._auth_mode == bn.AUTH_MODE_NOMINAL
    assert bn.datasource_param(layer.source(), "sslmode") == "verify-full"
    assert bn.datasource_param(layer.source(), "authcfg") == "9i19s56"
    plugin.unload()


# --- revue 2 (I-8) : projets enregistrés dans PostgreSQL ---------------------------

STORAGE_URI = (f"postgresql://{HOST18}:5432?authcfg=9i19s56&sslmode=require&dbname=test_db"
               "&schema=wyre&project=Mon%20projet")


def test_recent_db_projects_are_secured_when_9i19s56_carries_the_ad_identity(bp18):
    from qgis.core import QgsSettings

    QgsSettings().setValue("UI/recentProjects/1/path", STORAGE_URI)
    QgsSettings().setValue("UI/recentProjects/2/path", "/home/jdoe/projet.qgz")
    QgsSettings().setValue(bp18.AD_IDENTITY_KEY, True)
    plugin = _plugin(bp18)

    plugin._secure_recent_projects()

    secured = QgsSettings().value("UI/recentProjects/1/path")
    assert "sslmode=verify-full" in secured and "sslmode=require" not in secured
    assert "project=Mon%20projet" in secured
    assert QgsSettings().value("UI/recentProjects/2/path") == "/home/jdoe/projet.qgz"


def test_recent_db_projects_untouched_in_shared_mode(bp18):
    from qgis.core import QgsSettings

    QgsSettings().setValue("UI/recentProjects/1/path", STORAGE_URI)
    QgsSettings().setValue(bp18.AD_IDENTITY_KEY, False)
    _plugin(bp18)._secure_recent_projects()
    assert QgsSettings().value("UI/recentProjects/1/path") == STORAGE_URI


def test_project_opened_from_db_saves_back_in_verify_full_without_becoming_dirty(bp18):
    from qgis.core import QgsProject, QgsSettings

    QgsSettings().setValue(bp18.AD_IDENTITY_KEY, True)
    project = QgsProject.instance()
    project.setFileName(STORAGE_URI)
    project.setDirty(False)
    plugin = _plugin(bp18, connected=True, mode=bn.AUTH_MODE_NOMINAL)

    plugin._secure_current_project_uri()

    assert "sslmode=verify-full" in project.fileName()
    assert project.isDirty() is False
