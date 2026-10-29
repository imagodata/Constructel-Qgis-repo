"""Bridge 1.8 — sonde nominative unique, ressaisie, repli D7, identite,
perimetre (plan 2026-10-29 volets B5, B8, C1, D1, D3 ; spec §5.7.4-6, AC8).

Stub-level: fake psycopg2 (recording, scripted outcomes per connect() call),
fake cursor answering the plugin's SQL, qgis stub package. The connection
dialog is replaced by a recording `_ask_password` so the number of prompts
and of binds per startup is asserted exactly.
"""
import os
import sys
import types

import pytest

from constructel_bridge import bridge_nominatif as bn
from constructel_bridge_tests.conftest import CREDS_17, CREDS_18, CREDS_18X

LOGIN = "jdoe"
QGIS_USER = "JDoe"
EMAIL = "jdoe@constructel.be"
USER_ROW = ("11111111-1111-1111-1111-111111111111", QGIS_USER, EMAIL)
LIBPQ = 'connection to server at "test-host.invalid", port 5432 failed: FATAL:  '


class _PgErr(Exception):
    pass


def _not_permitted():
    return _PgErr(LIBPQ + 'role "jdoe" is not permitted to log in')


def _ldap_failed():
    return _PgErr(LIBPQ + 'LDAP authentication failed for user "jdoe"')


def _refused():
    return _PgErr('connection to server at "test-host.invalid", port 5432 failed: Connection refused')


class _FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushSuccess(self, title, message):
        self.messages.append(("success", title, message))

    def pushWarning(self, title, message):
        self.messages.append(("warning", title, message))

    def pushCritical(self, title, message):
        self.messages.append(("critical", title, message))

    def pushMessage(self, title, message, level=None, duration=None):
        self.messages.append(("message", title, message))

    def kinds(self):
        return [k for (k, _t, _m) in self.messages]


class _FakeIface:
    def __init__(self):
        self._bar = _FakeMessageBar()

    def mainWindow(self):
        return None

    def messageBar(self):
        return self._bar

    def activeLayer(self):
        return None

    def reloadConnections(self):
        pass


class _FakeCursor:
    """Answers _register_bridge_user, the scope query and the zone names."""

    def __init__(self, user_row=USER_ROW, scope_row=None, mro_names=(), pop_names=()):
        self.user_row = user_row
        self.scope_row = scope_row
        self.mro_names = list(mro_names)
        self.pop_names = list(pop_names)
        self.executed = []
        self._one = None
        self._all = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self._one, self._all = None, []
        if "FROM ref.users WHERE" in sql and "username" in sql:
            self._one = self.user_row
        elif "INSERT INTO ref.users" in sql:
            self._one = ("22222222-2222-2222-2222-222222222222", "new@constructel.be")
        elif "SELECT email FROM ref.users WHERE id" in sql:
            self._one = (EMAIL,)
        elif "current_gis_role" in sql:
            if self.scope_row is None:
                raise _PgErr("permission denied for function current_gis_role")
            self._one = self.scope_row
        elif "FROM wyre.zone_mro" in sql:
            self._all = self.mro_names
        elif "FROM wyre.zone_pop" in sql:
            self._all = self.pop_names

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all

    def close(self):
        pass

    def sql(self):
        return [s for (s, _p) in self.executed]


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.autocommit = False
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


def _install_psycopg2(monkeypatch, outcomes, cursor):
    """Scripted psycopg2: outcomes[i] is None (connect ok) or an Exception
    raised by the i-th connect() call. Extra calls succeed."""
    calls = []
    module = types.ModuleType("psycopg2")
    module.Error = _PgErr

    def connect(**kwargs):
        calls.append(kwargs)
        idx = len(calls) - 1
        outcome = outcomes[idx] if idx < len(outcomes) else None
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeConnection(cursor)

    module.connect = connect
    monkeypatch.setitem(sys.modules, "psycopg2", module)
    return calls


def _make_plugin(bp, monkeypatch, tmp_path, outcomes, *, cursor=None, stored_ad_pw=None,
                 memorized=None, ask=None, qgis_user=QGIS_USER):
    from qgis.core import QgsSettings

    QgsSettings().setValue("constructel_bridge/onboarding_done", True)
    if memorized is not None:
        QgsSettings().setValue(bn.NOMINAL_SETTINGS_KEYS["auth_mode"], memorized)
    if stored_ad_pw:
        assert bp._store_password_encrypted(stored_ad_pw, "ad", username=LOGIN)
    cursor = cursor or _FakeCursor()
    calls = _install_psycopg2(monkeypatch, outcomes, cursor)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())
    plugin._get_qgis_username = lambda: qgis_user
    asked = []

    def _ask_password(login, reprompt=False):
        asked.append((login, reprompt))
        return ask

    plugin._ask_password = _ask_password
    return plugin, calls, asked, cursor


def _config(cfg_id):
    from qgis.core import QgsApplication, QgsAuthMethodConfig

    cfg = QgsAuthMethodConfig()
    QgsApplication.authManager().loadAuthenticationConfig(cfg_id, cfg, True)
    return cfg


def _logs(level=None):
    from qgis.core import QgsMessageLog

    return [m for (m, _t, lvl) in QgsMessageLog._messages if level is None or lvl == level]


def _mode():
    from qgis.core import QgsSettings

    return QgsSettings().value(bn.NOMINAL_SETTINGS_KEYS["auth_mode"], "")


def _pg(bp, conn, key):
    from qgis.core import QgsSettings

    return QgsSettings().value(f"PostgreSQL/connections/{bp._PG_CONNECTIONS[conn]['name']}/{key}")


# --- sonde nominative : succes -------------------------------------------------


def test_startup_probe_with_stored_ad_password_connects_nominal(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert plugin._connected is True
    assert len(calls) == 1
    assert calls[0]["user"] == LOGIN
    assert calls[0]["password"] == "ad-pw"
    assert calls[0]["sslmode"] == "verify-full"
    assert calls[0]["sslrootcert"] == str(bp18.ca_bundle_path(os.path.dirname(bp18.__file__)))
    assert asked == []
    assert plugin._auth_mode == bn.AUTH_MODE_NOMINAL
    assert _mode() == bn.AUTH_MODE_NOMINAL
    assert "success" in plugin.iface.messageBar().kinds()


def test_cas_are_imported_into_qgis_before_the_probe(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsAuthCertUtils, QgsApplication

    events = []
    real = bp18._ensure_qgis_trusted_cas
    monkeypatch.setattr(bp18, "_ensure_qgis_trusted_cas", lambda: events.append("cas") or real())
    plugin, calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw")
    real_connect = plugin._connect
    plugin._connect = lambda *a, **k: events.append("probe") or real_connect(*a, **k)

    plugin._auto_connect()

    assert events[:2] == ["cas", "probe"]
    mgr = QgsApplication.authManager()
    assert len(mgr._cas) == 2
    assert set(mgr._trust.values()) == {QgsAuthCertUtils.CertTrustPolicy.Trusted}
    assert not (tmp_path / "root.crt").exists()


def test_nominal_success_writes_login_in_fixed_wyre_and_be_configs(bp18, monkeypatch, tmp_path):
    plugin, _calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw")
    plugin._auto_connect()

    wyre = _config("9i19s56")
    assert (wyre.config("username"), wyre.config("password")) == (LOGIN, "ad-pw")
    be = _config("07254s7")
    assert (be.config("username"), be.config("password")) == (LOGIN, "ad-pw")
    assert _pg(bp18, "wyre", "username") == LOGIN
    assert _pg(bp18, "wyre", "sslmode") == "5"
    assert _pg(bp18, "wyre", "authcfg") == "9i19s56"
    assert _pg(bp18, "be", "username") == LOGIN
    assert _pg(bp18, "be", "sslmode") == "5"
    assert _pg(bp18, "be", "authcfg") == "07254s7"


def test_nominal_mode_never_writes_ref_users_nor_app_current_user(bp18, monkeypatch, tmp_path):
    monkeypatch.setenv("PGOPTIONS", "-c app.current_user=stale@constructel.be")
    plugin, _calls, _asked, cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert plugin._bridge_user_id == USER_ROW[0]
    assert not any("INSERT INTO ref.users" in s or "UPDATE ref.users" in s for s in cur.sql())
    assert not any("app.current_user" in s for s in cur.sql())
    assert "app.current_user" not in os.environ.get("PGOPTIONS", "")


def test_nominal_mode_first_run_asks_password_once_and_stores_it(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], ask=(LOGIN, "typed-pw"))

    plugin._auto_connect()

    assert asked == [(LOGIN, False)]
    assert len(calls) == 1 and calls[0]["password"] == "typed-pw"
    assert plugin._auth_mode == bn.AUTH_MODE_NOMINAL
    assert _config("nomin18").config("username") == LOGIN
    assert _config("nomin18").config("password") == "typed-pw"


def test_stored_shared_password_of_17x_is_not_reused_as_ad_password(bp18, monkeypatch, tmp_path):
    # 1.7.x a laisse 9i19s56 = (ftth_editor, mot de passe partage) : ce n'est
    # pas le mot de passe AD de la personne -> dialogue, pas de bind aveugle.
    bp18._store_password_encrypted("shared-pw", "wyre")
    plugin, calls, asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], ask=(LOGIN, "ad-pw"))

    plugin._auto_connect()

    assert asked == [(LOGIN, False)]
    assert calls[0]["password"] == "ad-pw"


# --- repli D7 -------------------------------------------------------------------


def test_login_disabled_falls_back_to_shared_with_banner_and_no_reprompt(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_not_permitted(), None], stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert asked == []
    assert [c["user"] for c in calls] == [LOGIN, "ftth_editor"]
    assert calls[1]["password"] == "shared-pw"
    # D-TLS-2 : identifiant partage = kwargs 1.7.x (require, pas de CA)
    assert calls[1]["sslmode"] == "require"
    assert "sslrootcert" not in calls[1]
    assert plugin._connected is True
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    assert _mode() == bn.AUTH_MODE_SHARED
    bar = plugin.iface.messageBar()
    assert any(k == "warning" and bp18.tr("nominal.banner_login_disabled") in m for (k, _t, m) in bar.messages)
    # chemin 1.7.3 exact : la config fixe wyre porte l'identifiant partage
    assert _config("9i19s56").config("username") == "ftth_editor"
    assert _pg(bp18, "wyre", "username") == "ftth_editor"
    assert _pg(bp18, "wyre", "sslmode") == "3"
    # ... et le mot de passe AD est conserve pour la sonde du prochain demarrage
    assert _config("nomin18").config("password") == "ad-pw"


def test_shared_fallback_keeps_declared_audit_identity(bp18, monkeypatch, tmp_path):
    plugin, _calls, _asked, cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_not_permitted(), None], stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert os.environ.get("PGOPTIONS") == f"-c app.current_user={EMAIL}"
    assert any("app.current_user" in s for s in cur.sql())


def test_auth_refused_in_nominal_mode_reprompts_once_then_falls_back(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_ldap_failed(), _ldap_failed(), None],
        stored_ad_pw="old-pw", memorized=bn.AUTH_MODE_NOMINAL, ask=(LOGIN, "new-pw"))

    plugin._auto_connect()

    assert asked == [(LOGIN, True)]
    assert [(c["user"], c["password"]) for c in calls] == [
        (LOGIN, "old-pw"), (LOGIN, "new-pw"), ("ftth_editor", "shared-pw")]
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    assert _config("nomin18").config("password") == "new-pw"
    bar = plugin.iface.messageBar()
    assert any(k == "warning" and bp18.tr("nominal.banner_auth_refused", login=LOGIN) in m
               for (k, _t, m) in bar.messages)


def test_auth_refused_reprompt_success_switches_to_nominal(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_ldap_failed(), None],
        stored_ad_pw="old-pw", memorized=bn.AUTH_MODE_NOMINAL, ask=(LOGIN, "new-pw"))

    plugin._auto_connect()

    assert asked == [(LOGIN, True)]
    assert len(calls) == 2
    assert plugin._auth_mode == bn.AUTH_MODE_NOMINAL
    assert _config("9i19s56").config("password") == "new-pw"


def test_auth_refused_in_shared_mode_falls_back_silently(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_ldap_failed(), None],
        stored_ad_pw="ad-pw", memorized=bn.AUTH_MODE_SHARED, ask=(LOGIN, "never"))

    plugin._auto_connect()

    assert asked == []
    assert len(calls) == 2
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED


def test_shared_mode_without_stored_ad_password_does_not_prompt_at_startup(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [None], memorized=bn.AUTH_MODE_SHARED, ask=(LOGIN, "never"))

    plugin._auto_connect()

    assert asked == []
    assert [c["user"] for c in calls] == ["ftth_editor"]
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED


def test_cancelled_first_run_dialog_falls_back_to_shared(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], ask=None)

    plugin._auto_connect()

    assert asked == [(LOGIN, False)]
    assert [c["user"] for c in calls] == ["ftth_editor"]
    assert plugin._connected is True


def test_other_error_never_falls_back(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_refused(), None], stored_ad_pw="ad-pw", ask=(LOGIN, "x"))

    plugin._auto_connect()

    assert len(calls) == 1
    assert asked == []
    assert plugin._connected is False
    assert any("Connection failed" in m for m in _logs(level=2))


def test_login_disabled_without_shared_password_is_a_clear_error(load_bp18, monkeypatch, tmp_path):
    from qgis.core import Qgis

    bp = load_bp18(CREDS_18X)
    plugin, calls, _asked, _cur = _make_plugin(bp, monkeypatch, tmp_path, [_not_permitted(), None], stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert len(calls) == 1
    assert plugin._connected is False
    assert any(bp.tr("nominal.no_fallback", login=LOGIN, error="")[:30] in m
               for m in _logs(level=Qgis.MessageLevel.Critical))


def test_ca_import_failure_falls_back_to_shared_without_nominal_bind(bp18, monkeypatch, tmp_path):
    # D-TLS-1 : sans la CA dans QGIS, aucune couche nominative ne passerait
    # verify-full -> nominatif impossible, repli partage (jamais bloque).
    plugin, calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw")
    monkeypatch.setattr(bp18, "_ensure_qgis_trusted_cas", lambda: False)

    plugin._auto_connect()

    assert [c["user"] for c in calls] == ["ftth_editor"]
    assert plugin._connected is True
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED


def test_unusable_workstation_name_goes_straight_to_shared(bp18, monkeypatch, tmp_path):
    from qgis.core import Qgis

    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [None], qgis_user="Jean Dupont", ask=(LOGIN, "x"))

    plugin._auto_connect()

    assert asked == []
    assert [c["user"] for c in calls] == ["ftth_editor"]
    assert any(bp18.tr("nominal.login_unusable", user="Jean Dupont") in m
               for m in _logs(level=Qgis.MessageLevel.Warning))


# --- action « Reessayer mon acces nominatif » -------------------------------------


def test_retry_action_switches_a_shared_workstation_to_nominal(bp18, monkeypatch, tmp_path):
    plugin, calls, _asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_not_permitted(), None, None], stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    first_conn = plugin._conn

    plugin._on_retry_nominal()

    assert plugin._auth_mode == bn.AUTH_MODE_NOMINAL
    assert calls[-1]["user"] == LOGIN
    assert first_conn.closed is True
    assert any(bp18.tr("nominal.retry_ok", login=LOGIN) in m for (_k, _t, m) in plugin.iface.messageBar().messages)


# --- perimetre (D1/D3) -------------------------------------------------------------


def test_nominal_connect_reads_scope_and_names_it(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(
        scope_row=("DESIGNER", True, True, ["m1"], ["m1"], ["p1", "p2"], []),
        mro_names=[("m1", "MRO Bruxelles")], pop_names=[("p1", "POP_01"), ("p2", "POP_02")])
    plugin, _calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert plugin._scope.role == "DESIGNER"
    assert plugin._scope.network_write is True
    text = plugin._scope_text()
    assert "MRO Bruxelles" in text and "POP_01" in text and "POP_02" in text
    success = [m for (k, _t, m) in plugin.iface.messageBar().messages if k == "success"]
    assert success and LOGIN in success[0] and "MRO Bruxelles" in success[0]


def test_admin_scope_is_reported_as_full_network(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(scope_row=("ADMIN", True, True, None, None, None, None))
    plugin, _c, _a, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert plugin._scope_text() == bp18.tr("scope.all")


def test_viewer_scope_is_reported_read_only(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(scope_row=("VIEWER", True, False, ["m1"], [], [], []))
    plugin, _c, _a, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert bp18.tr("scope.readonly") in plugin._scope_text()


def test_scope_query_failure_is_not_blocking(bp18, monkeypatch, tmp_path):
    # Login be (bureau d'etudes) : EXECUTE non accorde -> perimetre inconnu, connexion OK.
    plugin, _c, _a, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=_FakeCursor(scope_row=None), stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert plugin._connected is True
    assert plugin._scope is None
    assert plugin._scope_text() == bp18.tr("scope.unknown")


def test_shared_mode_scope_text_names_the_shared_login(bp18, monkeypatch, tmp_path):
    plugin, _c, _a, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [_not_permitted(), None], stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert plugin._scope_text() == bp18.tr("nominal.mode_shared", user="ftth_editor")


# --- be en mode partage (1.7.x) ------------------------------------------------------


def test_shared_fallback_on_17x_credentials_keeps_shared_be(load_bp18, monkeypatch, tmp_path):
    bp = load_bp18(CREDS_17)
    plugin, _c, _a, _cur = _make_plugin(bp, monkeypatch, tmp_path, [_not_permitted(), None], stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert _config("07254s7").config("username") == "bureau_etudes"
    assert _config("07254s7").config("password") == "be-shared-pw"
    assert _pg(bp, "be", "username") == "bureau_etudes"
