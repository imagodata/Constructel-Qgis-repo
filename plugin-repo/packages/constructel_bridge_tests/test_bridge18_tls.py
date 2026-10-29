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
    SHARED_SAVED.replace(HOST18, "other.example.com"),                     # serveur tiers
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
