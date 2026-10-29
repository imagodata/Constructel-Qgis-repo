"""Bridge 1.8 — sonde nominative unique, ressaisie, repli D7, identité,
périmètre (plan 2026-10-29 volets B5, B8, C1, D1, D3 ; spec §5.7.4-6, AC8),
révisés après la revue du 29/10 (I2, I4, I5, I6, I9, I10, I13, M1-M3,
M9-M13).

Stub-level : faux psycopg2 (enregistreur, issue scriptée par appel à
connect()), faux curseur répondant au SQL du plugin, paquet qgis de stubs. Le
dialogue de connexion est remplacé par un `_ask_password` enregistreur : le
nombre de dialogues et de binds par démarrage est vérifié exactement.

Démarrage : `_auto_connect()` = phase silencieuse seule (jamais de
dialogue) ; `_start()` = démarrage complet (phase silencieuse puis
interactive, comme à `initializationCompleted`).
"""
import os
import sys
import types

import pytest

from constructel_bridge import bridge_nominatif as bn
from constructel_bridge_tests.conftest import CREDS_17, CREDS_18X

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


def _timeout():
    return _PgErr(LIBPQ + "canceling authentication due to timeout")


class _Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def disconnect(self, slot=None):
        if slot not in self.slots:
            raise TypeError("not connected")
        self.slots.remove(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class _FakeMessageBar:
    def __init__(self):
        self.messages = []
        self.items = []

    def pushSuccess(self, title, message):
        self.messages.append(("success", title, message))

    def pushWarning(self, title, message):
        self.messages.append(("warning", title, message))

    def pushCritical(self, title, message):
        self.messages.append(("critical", title, message))

    def pushMessage(self, title, message, level=None, duration=None):
        self.messages.append(("message", title, message))

    def pushItem(self, item):
        self.items.append(item)

    def popWidget(self, item):
        self.items.remove(item)
        return True

    def kinds(self):
        return [k for (k, _t, _m) in self.messages]


class _FakeIface:
    def __init__(self):
        self._bar = _FakeMessageBar()
        self.initializationCompleted = _Signal()

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
                 memorized=None, ask=None, qgis_user=QGIS_USER, pg_login=None):
    """*ask* : réponse du dialogue (tuple ou None), ou liste de réponses
    successives."""
    from qgis.core import QgsSettings

    QgsSettings().setValue("constructel_bridge/onboarding_done", True)
    if memorized is not None:
        QgsSettings().setValue(bn.NOMINAL_SETTINGS_KEYS["auth_mode"], memorized)
    if pg_login is not None:
        QgsSettings().setValue(bn.NOMINAL_SETTINGS_KEYS["pg_login"], pg_login)
    if stored_ad_pw:
        assert bp._store_password_encrypted(stored_ad_pw, "ad", username=pg_login or LOGIN)
    cursor = cursor or _FakeCursor()
    calls = _install_psycopg2(monkeypatch, outcomes, cursor)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())
    plugin._get_qgis_username = lambda: qgis_user
    asked = []
    answers = list(ask) if isinstance(ask, list) else None

    def _ask_password(login, reprompt=False):
        asked.append((login, reprompt))
        if answers is not None:
            return answers.pop(0) if answers else None
        return ask

    plugin._ask_password = _ask_password
    return plugin, calls, asked, cursor


def _start(plugin):
    """Démarrage complet : phase silencieuse puis interactive."""
    plugin._startup_state = "pending"
    plugin._on_initialization_completed()


def _config(cfg_id):
    from qgis.core import QgsApplication, QgsAuthMethodConfig

    cfg = QgsAuthMethodConfig()
    QgsApplication.authManager().loadAuthenticationConfig(cfg_id, cfg, True)
    return cfg


def _has_config(cfg_id):
    from qgis.core import QgsApplication

    return cfg_id in QgsApplication.authManager().configIds()


def _logs(level=None):
    from qgis.core import QgsMessageLog

    return [m for (m, _t, lvl) in QgsMessageLog._messages if level is None or lvl == level]


def _mode():
    from qgis.core import QgsSettings

    return QgsSettings().value(bn.NOMINAL_SETTINGS_KEYS["auth_mode"], "")


def _pg(bp, conn, key):
    from qgis.core import QgsSettings

    return QgsSettings().value(f"PostgreSQL/connections/{bp._PG_CONNECTIONS[conn]['name']}/{key}")


def _banner_texts(plugin):
    return [item.text for item in plugin.iface.messageBar().items]


def _expected_banner(bp, kind, login=LOGIN):
    reason = bp.tr(bp.ConstructelBridgePlugin._REASON_KEYS[kind], login=login)
    return bp.tr("nominal.banner", reason=reason)


# --- sonde nominative : succès ------------------------------------------------


def test_startup_probe_with_stored_ad_password_connects_nominal(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw")

    _start(plugin)

    assert plugin._connected is True
    assert len(calls) == 1
    assert calls[0]["user"] == LOGIN
    assert calls[0]["password"] == "ad-pw"
    assert calls[0]["sslmode"] == "verify-full"
    assert calls[0]["sslrootcert"] == str(bp18.ca_bundle_path(os.path.dirname(bp18.__file__)))
    assert calls[0]["connect_timeout"] == bp18.NOMINAL_CONNECT_TIMEOUT == 10  # I2
    assert asked == []
    assert plugin._auth_mode == bn.AUTH_MODE_NOMINAL
    assert _mode() == bn.AUTH_MODE_NOMINAL
    assert "success" in plugin.iface.messageBar().kinds()
    assert _banner_texts(plugin) == []


def test_cas_are_imported_into_qgis_before_the_probe(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsApplication, QgsAuthCertUtils

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
    from qgis.core import QgsSettings

    monkeypatch.setenv("PGOPTIONS", "-c app.current_user=stale@constructel.be")
    QgsSettings().setValue(bp18.AUDIT_EMAIL_KEY, EMAIL)
    plugin, _calls, _asked, cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert plugin._bridge_user_id == USER_ROW[0]
    assert not any("INSERT INTO ref.users" in s or "UPDATE ref.users" in s for s in cur.sql())
    assert not any("app.current_user" in s for s in cur.sql())
    assert "app.current_user" not in os.environ.get("PGOPTIONS", "")
    # M9 : l'adresse memorisee reste pour le plugin Historique.
    assert QgsSettings().value(bp18.AUDIT_EMAIL_KEY) == EMAIL


def test_nominal_user_is_looked_up_by_session_login_not_os_name(bp18, monkeypatch, tmp_path):
    # M10 : poste « PC-Jean » mais login AD jdoe (memorise).
    plugin, _calls, _asked, cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw", qgis_user="PC-Jean", pg_login=LOGIN)

    plugin._auto_connect()

    lookups = [p for (s, p) in cur.executed if "FROM ref.users WHERE" in s]
    assert lookups == [(LOGIN,)]
    assert plugin._bridge_user == QGIS_USER  # username de ref.users


def test_shared_password_precache_only_in_shared_mode(bp18, monkeypatch, tmp_path):
    # M13 : en nominatif, une couche sans authcfg ne doit pas trouver
    # l'identifiant partage dans le cache QgsCredentials.
    from qgis.core import QgsCredentials

    plugin, _c, _a, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert QgsCredentials.instance().puts == []

    plugin._connect_shared(silent=True)
    assert {user for (_realm, user, _pw) in QgsCredentials.instance().puts} == {"ftth_editor"}


# --- premier démarrage, dialogue différé (I13) ----------------------------------


def test_first_run_dialog_is_deferred_until_the_ui_is_ready(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None, None], ask=(LOGIN, "typed-pw"))

    plugin._auto_connect()  # phase silencieuse : pas de dialogue
    assert asked == []
    assert [c["user"] for c in calls] == ["ftth_editor"]  # poste utilisable en attendant

    plugin._startup_interactive()

    assert asked == [(LOGIN, False)]
    assert [(c["user"], c["password"]) for c in calls] == [("ftth_editor", "shared-pw"), (LOGIN, "typed-pw")]
    assert plugin._auth_mode == bn.AUTH_MODE_NOMINAL
    assert _config("nomin18").config("username") == LOGIN
    assert _config("nomin18").config("password") == "typed-pw"
    assert _banner_texts(plugin) == []


def test_stored_shared_password_of_17x_is_not_reused_as_ad_password(bp18, monkeypatch, tmp_path):
    # 1.7.x a laisse 9i19s56 = (ftth_editor, mot de passe partage) : ce n'est
    # pas le mot de passe AD de la personne -> dialogue, pas de bind aveugle.
    bp18._store_password_encrypted("shared-pw", "wyre")
    plugin, calls, asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], ask=(LOGIN, "ad-pw"))

    _start(plugin)

    assert asked == [(LOGIN, False)]
    assert all(c["password"] != "shared-pw" for c in calls if c["user"] == LOGIN)
    assert calls[-1]["password"] == "ad-pw"


def test_cancelled_first_run_dialog_is_asked_again_next_startup(bp18, load_bp18, monkeypatch, tmp_path):
    # I9 : annuler ne fige pas le poste en repli pour toujours.
    plugin, calls, asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], ask=None)

    _start(plugin)

    assert asked == [(LOGIN, False)]
    assert [c["user"] for c in calls] == ["ftth_editor"]
    assert plugin._connected is True
    assert _mode() == ""  # rien de memorise
    assert _banner_texts(plugin) == [_expected_banner(bp18, "no_password")]

    second, _calls2, asked2, _cur2 = _make_plugin(bp18, monkeypatch, tmp_path, [None], ask=None)
    _start(second)
    assert asked2 == [(LOGIN, False)]


def test_admin_rescue_login_typed_in_dialog_is_an_explicit_shared_session(bp18, monkeypatch, tmp_path):
    # D5 : « ftth_editor » saisi = session partagee explicite, aucun bind nominatif.
    plugin, calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None, None],
                                               ask=("ftth_editor", "rotated-pw"))

    _start(plugin)

    assert [(c["user"], c["password"]) for c in calls] == [("ftth_editor", "shared-pw"), ("ftth_editor", "rotated-pw")]
    assert calls[-1]["sslmode"] == "require"
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    assert _banner_texts(plugin) == []


def test_memorized_login_wins_over_os_name(bp18, monkeypatch, tmp_path):
    # I4 : compte AD different du nom Windows -> pas de dialogue a chaque demarrage.
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw", qgis_user="Jean", pg_login="jdupont")

    _start(plugin)

    assert asked == []
    assert calls[0]["user"] == "jdupont"
    assert plugin._pg_login == "jdupont"


def test_login_typed_in_dialog_is_memorized(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsSettings

    plugin, _calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None, None], ask=("jdupont", "pw"))
    _start(plugin)
    assert QgsSettings().value(bn.NOMINAL_SETTINGS_KEYS["pg_login"]) == "jdupont"


def test_unusable_workstation_name_defers_a_dialog_with_empty_login(bp18, monkeypatch, tmp_path):
    from qgis.core import Qgis

    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [None, None], qgis_user="Jean Dupont", ask=(LOGIN, "pw"))

    plugin._auto_connect()
    assert asked == []
    assert [c["user"] for c in calls] == ["ftth_editor"]
    assert any(bp18.tr("nominal.login_unusable", user="Jean Dupont") in m
               for m in _logs(level=Qgis.MessageLevel.Warning))

    plugin._startup_interactive()
    assert asked == [("", False)]
    assert plugin._pg_login == LOGIN


# --- repli D7 ------------------------------------------------------------------


def test_login_disabled_falls_back_to_shared_with_persistent_banner(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_not_permitted(), None], stored_ad_pw="ad-pw")

    _start(plugin)

    assert asked == []
    assert [c["user"] for c in calls] == [LOGIN, "ftth_editor"]
    assert calls[1]["password"] == "shared-pw"
    # D-TLS-2 : identifiant partage = kwargs 1.7.x (require, pas de CA ni delai)
    assert calls[1]["sslmode"] == "require"
    assert "sslrootcert" not in calls[1] and "connect_timeout" not in calls[1]
    assert plugin._connected is True
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    assert _mode() == bn.AUTH_MODE_SHARED
    # I9 : bandeau SANS expiration, pousse une fois l'interface prete
    items = plugin.iface.messageBar().items
    assert [i.text for i in items] == [_expected_banner(bp18, bn.LOGIN_DISABLED)]
    assert items[0].duration == 0
    # chemin 1.7.x exact : la config fixe wyre porte l'identifiant partage
    assert _config("9i19s56").config("username") == "ftth_editor"
    assert _pg(bp18, "wyre", "username") == "ftth_editor"
    assert _pg(bp18, "wyre", "sslmode") == "3"
    # ... et le mot de passe AD (non refuse) est conserve pour la sonde suivante
    assert _config("nomin18").config("password") == "ad-pw"


def test_banner_is_not_pushed_before_the_ui_is_ready(bp18, monkeypatch, tmp_path):
    plugin, _calls, _asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_not_permitted(), None], stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert plugin.iface.messageBar().items == []
    plugin._startup_interactive()
    assert len(plugin.iface.messageBar().items) == 1


def test_shared_session_is_shown_in_the_plugin_menu(bp18, monkeypatch, tmp_path):
    from qgis.PyQt.QtWidgets import QAction

    plugin, _c, _a, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [_not_permitted(), None, None],
                                        stored_ad_pw="ad-pw")
    plugin._action_retry = QAction(None, bp18.tr("menu.retry_nominal"), None)
    _start(plugin)
    assert plugin._action_retry.text() == bp18.tr("menu.retry_nominal_shared")


def test_shared_fallback_keeps_declared_audit_identity(bp18, monkeypatch, tmp_path):
    plugin, _calls, _asked, cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_not_permitted(), None], stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert os.environ.get("PGOPTIONS") == f"-c app.current_user={EMAIL}"
    assert any("app.current_user" in s for s in cur.sql())


def test_refused_stored_password_reprompts_once_after_startup_then_falls_back(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_ldap_failed(), None, _ldap_failed()],
        stored_ad_pw="old-pw", memorized=bn.AUTH_MODE_NOMINAL, ask=(LOGIN, "new-pw"))

    plugin._auto_connect()
    # Phase silencieuse : 1 bind refuse, repli partage, ressaisie differee.
    assert asked == []
    assert [(c["user"], c["password"]) for c in calls] == [(LOGIN, "old-pw"), ("ftth_editor", "shared-pw")]
    assert not _has_config("nomin18")  # I10 : mot de passe refuse oublie

    plugin._startup_interactive()

    assert asked == [(LOGIN, True)]
    assert [(c["user"], c["password"]) for c in calls] == [
        (LOGIN, "old-pw"), ("ftth_editor", "shared-pw"), (LOGIN, "new-pw")]  # 2 binds refuses, pas 3
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    assert _mode() == bn.AUTH_MODE_SHARED
    assert not _has_config("nomin18")
    assert _banner_texts(plugin) == [_expected_banner(bp18, bn.AUTH_REFUSED)]


def test_reprompt_success_switches_to_nominal_and_removes_the_banner(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_ldap_failed(), None, None],
        stored_ad_pw="old-pw", memorized=bn.AUTH_MODE_NOMINAL, ask=(LOGIN, "new-pw"))

    _start(plugin)

    assert asked == [(LOGIN, True)]
    assert len(calls) == 3
    assert plugin._auth_mode == bn.AUTH_MODE_NOMINAL
    assert _config("9i19s56").config("password") == "new-pw"
    assert _config("nomin18").config("password") == "new-pw"
    assert _banner_texts(plugin) == []


def test_refused_password_on_shared_workstation_is_forgotten_not_replayed(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_ldap_failed(), None],
        stored_ad_pw="ad-pw", memorized=bn.AUTH_MODE_SHARED, ask=(LOGIN, "never"))

    _start(plugin)

    assert asked == []
    assert len(calls) == 2
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    assert not _has_config("nomin18")

    # Demarrage suivant : rien a rejouer, aucun dialogue d'office (I10).
    second, calls2, asked2, _cur2 = _make_plugin(bp18, monkeypatch, tmp_path, [None], ask=(LOGIN, "never"))
    _start(second)
    assert asked2 == []
    assert [c["user"] for c in calls2] == ["ftth_editor"]
    assert _banner_texts(second) == [_expected_banner(bp18, "no_password")]


@pytest.mark.parametrize("error", [_refused(), _timeout(),
                                   _PgErr(LIBPQ + 'too many connections for role "jdoe"'),
                                   _PgErr(LIBPQ + "trop de connexions pour le rôle « jdoe »")])
def test_any_other_failure_falls_back_without_reprompt(bp18, monkeypatch, tmp_path, error):
    # I2 : delai, TLS, serveur, motif inconnu -> repli (jamais de poste bloque).
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [error, None], stored_ad_pw="ad-pw",
        memorized=bn.AUTH_MODE_NOMINAL, ask=(LOGIN, "x"))

    _start(plugin)

    assert asked == []
    assert [c["user"] for c in calls] == [LOGIN, "ftth_editor"]
    assert plugin._connected is True
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    assert _mode() == bn.AUTH_MODE_NOMINAL  # pas un verdict sur le login : nouvelle sonde au prochain demarrage
    assert _config("nomin18").config("password") == "ad-pw"  # pas refuse : conserve
    assert _banner_texts(plugin) == [_expected_banner(bp18, "unavailable")]


def test_french_password_refusal_triggers_the_reprompt(bp18, monkeypatch, tmp_path):
    fr = _PgErr(LIBPQ + "authentification LDAP échouée pour l'utilisateur « jdoe »")
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [fr, None, None], stored_ad_pw="old",
        memorized=bn.AUTH_MODE_NOMINAL, ask=(LOGIN, "new"))

    _start(plugin)

    assert asked == [(LOGIN, True)]
    assert plugin._auth_mode == bn.AUTH_MODE_NOMINAL


def test_login_disabled_without_shared_password_is_a_clear_error(load_bp18, monkeypatch, tmp_path):
    from qgis.core import Qgis

    bp = load_bp18(CREDS_18X)
    plugin, calls, _asked, _cur = _make_plugin(bp, monkeypatch, tmp_path, [_not_permitted(), None], stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert len(calls) == 1
    assert plugin._connected is False
    reason = bp.tr("nominal.reason_login_disabled")
    assert any(m.startswith(reason) for m in _logs(level=Qgis.MessageLevel.Critical))


def test_refused_password_is_removed_from_layer_configs_when_no_fallback(load_bp18, monkeypatch, tmp_path):
    # I10 (cloture 1.8.x) : 9i19s56/07254s7 ne gardent pas un mot de passe refuse.
    bp = load_bp18(CREDS_18X)
    bp._store_password_encrypted("old-pw", "wyre", username=LOGIN)
    bp._store_password_encrypted("old-pw", "be", username=LOGIN)
    plugin, _calls, _asked, _cur = _make_plugin(
        bp, monkeypatch, tmp_path, [_ldap_failed()], stored_ad_pw="old-pw", memorized=bn.AUTH_MODE_SHARED)

    plugin._auto_connect()

    assert plugin._connected is False
    assert not _has_config("9i19s56") and not _has_config("07254s7") and not _has_config("nomin18")


def test_shared_fallback_neutralizes_the_nominal_be_config(bp18, monkeypatch, tmp_path):
    # I10 : 07254s7 garderait login + mot de passe AD, rejoues par les couches be.
    from qgis.core import QgsSettings

    bp18._store_password_encrypted("ad-pw", "be", username=LOGIN)
    QgsSettings().setValue("PostgreSQL/connections/be/authcfg", "07254s7")
    plugin, _calls, _asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_not_permitted(), None], stored_ad_pw="ad-pw")

    plugin._auto_connect()

    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    assert not _has_config("07254s7")
    assert QgsSettings().value("PostgreSQL/connections/be/authcfg") is None


def test_shared_fallback_on_17x_credentials_keeps_shared_be(load_bp18, monkeypatch, tmp_path):
    bp = load_bp18(CREDS_17)
    plugin, _c, _a, _cur = _make_plugin(bp, monkeypatch, tmp_path, [_not_permitted(), None], stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert _config("07254s7").config("username") == "bureau_etudes"
    assert _config("07254s7").config("password") == "be-shared-pw"
    assert _pg(bp, "be", "username") == "bureau_etudes"
    assert _pg(bp, "be", "sslmode") == "3"


# --- prérequis locaux (D-TLS-1, M2, M3) ----------------------------------------


def test_ca_import_failure_falls_back_to_shared_without_nominal_bind(bp18, monkeypatch, tmp_path):
    plugin, calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw")
    monkeypatch.setattr(bp18, "_ensure_qgis_trusted_cas", lambda: False)

    _start(plugin)

    assert [c["user"] for c in calls] == ["ftth_editor"]
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    assert _banner_texts(plugin) == [_expected_banner(bp18, "local_setup")]


def test_declined_master_password_is_asked_once_then_shared(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsApplication

    plugin, calls, asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], ask=(LOGIN, "x"))
    mgr_cls = type(QgsApplication.authManager())
    prompts = []
    monkeypatch.setattr(mgr_cls, "masterPasswordIsSet", lambda self: False)
    monkeypatch.setattr(mgr_cls, "setMasterPassword", lambda self, *a: prompts.append(a) or False)

    _start(plugin)

    assert len(prompts) == 1  # M2 : une seule invite pour tout le demarrage
    assert asked == []
    assert [c["user"] for c in calls] == ["ftth_editor"]
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED

    plugin._on_retry_nominal()  # action explicite : l'invite revient (une fois)
    assert len(prompts) == 2


def test_auth_manager_write_failure_after_connect_falls_back(bp18, monkeypatch, tmp_path):
    # M3 : sans 9i19s56 a jour, la session nominative serait inutilisable.
    plugin, calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None, None], stored_ad_pw="ad-pw")
    real_store = bp18._store_password_encrypted
    monkeypatch.setattr(bp18, "_store_password_encrypted",
                        lambda pw, conn="wyre", username=None: False if conn == "wyre" and username
                        else real_store(pw, conn, username))
    opened = []
    real_connect = sys.modules["psycopg2"].connect
    sys.modules["psycopg2"].connect = lambda **kw: opened.append(real_connect(**kw)) or opened[-1]

    _start(plugin)

    assert [c["user"] for c in calls] == [LOGIN, "ftth_editor"]
    assert opened[0].closed is True
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    assert _banner_texts(plugin) == [_expected_banner(bp18, "local_setup")]


# --- actions explicites (Réessayer, Connecter : M1, M11) -------------------------


def test_retry_action_switches_a_shared_workstation_to_nominal(bp18, monkeypatch, tmp_path):
    plugin, calls, _asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_not_permitted(), None, None], stored_ad_pw="ad-pw")
    _start(plugin)
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    first_conn = plugin._conn

    plugin._on_retry_nominal()

    assert plugin._auth_mode == bn.AUTH_MODE_NOMINAL
    assert calls[-1]["user"] == LOGIN
    assert first_conn.closed is True
    assert any(bp18.tr("nominal.retry_ok", login=LOGIN) in m for (_k, _t, m) in plugin.iface.messageBar().messages)
    assert _banner_texts(plugin) == []


def test_failed_retry_keeps_the_working_shared_session(bp18, monkeypatch, tmp_path):
    # M1 : un « Reessayer » qui echoue ne ferme pas la connexion qui marchait.
    plugin, calls, _asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_not_permitted(), None, _refused()], stored_ad_pw="ad-pw")
    _start(plugin)
    first_conn = plugin._conn

    plugin._on_retry_nominal()

    assert len(calls) == 3
    assert plugin._conn is first_conn and first_conn.closed is False
    assert plugin._connected is True and plugin._auth_mode == bn.AUTH_MODE_SHARED


def test_connect_typo_gets_one_reprompt_with_message(bp18, monkeypatch, tmp_path):
    # M11 : meme machine d'etat qu'au demarrage.
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_ldap_failed(), None],
        ask=[(LOGIN, "typo"), (LOGIN, "right")])

    plugin._on_connect()

    assert asked == [(LOGIN, False), (LOGIN, True)]
    assert [c["password"] for c in calls] == ["typo", "right"]
    assert plugin._auth_mode == bn.AUTH_MODE_NOMINAL


def test_connect_failing_twice_keeps_the_nominal_session(bp18, monkeypatch, tmp_path):
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [None, _ldap_failed(), _ldap_failed()],
        stored_ad_pw="good", ask=[(LOGIN, "typo1"), (LOGIN, "typo2")])
    _start(plugin)
    first_conn = plugin._conn

    plugin._on_connect()

    assert len(calls) == 3  # pas de repli partage
    assert plugin._conn is first_conn and first_conn.closed is False
    assert plugin._auth_mode == bn.AUTH_MODE_NOMINAL
    assert _config("nomin18").config("password") == "good"  # pas le mot de passe saisi refuse


def test_admin_rescue_at_reprompt_is_an_explicit_shared_session(bp18, monkeypatch, tmp_path):
    # I5 : le test « login == ftth_editor » est refait apres CHAQUE dialogue.
    plugin, calls, asked, _cur = _make_plugin(
        bp18, monkeypatch, tmp_path, [_ldap_failed(), None],
        ask=[(LOGIN, "typo"), ("ftth_editor", "rotated")])

    plugin._on_connect()

    assert [(c["user"], c["password"]) for c in calls] == [(LOGIN, "typo"), ("ftth_editor", "rotated")]
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    assert _banner_texts(plugin) == []


# --- démarrage différé (I13) ------------------------------------------------------


def _initgui_ready(bp, monkeypatch, visible=False):
    from qgis.core import QgsApplication

    monkeypatch.setattr(QgsApplication, "getThemeIcon", staticmethod(lambda *_a: None), raising=False)
    monkeypatch.setattr(bp.ConstructelBridgePlugin, "_setup_external_services", lambda self: None)
    monkeypatch.setattr(bp.ConstructelBridgePlugin, "_ensure_extract_msg_available", lambda self: None)
    monkeypatch.setattr(bp, "register_expressions", lambda: None)
    monkeypatch.setattr(bp, "unregister_expressions", lambda: None)
    monkeypatch.setattr(bp, "init_language", lambda: None)

    class _Window:
        def isVisible(self):
            return visible

    class _Menu:
        def actions(self):
            return []

    iface = _FakeIface()
    iface.mainWindow = lambda: _Window()
    iface.addPluginToDatabaseMenu = lambda *a: None
    iface.removePluginDatabaseMenu = lambda *a: None
    iface.databaseMenu = lambda: _Menu()
    iface.addToolBarWidget = lambda widget: widget
    iface.removeToolBarIcon = lambda *a: None
    return iface


def test_initgui_neither_connects_nor_prompts(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsProject

    iface = _initgui_ready(bp18, monkeypatch)
    calls = _install_psycopg2(monkeypatch, [None], _FakeCursor())
    plugin = bp18.ConstructelBridgePlugin(iface)

    plugin.initGui()

    assert calls == []
    assert plugin._startup_state == "pending"
    assert plugin._on_initialization_completed in iface.initializationCompleted.slots
    assert plugin._on_layer_loaded in QgsProject.instance().layerLoaded._slots

    iface.initializationCompleted.emit()

    assert plugin._connected is True
    assert plugin._ui_ready is True
    assert plugin._on_layer_loaded not in QgsProject.instance().layerLoaded._slots
    plugin.unload()


def test_startup_project_triggers_the_silent_phase_before_its_first_layer(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsProject

    iface = _initgui_ready(bp18, monkeypatch)
    calls = _install_psycopg2(monkeypatch, [None], _FakeCursor())
    bp18._store_password_encrypted("ad-pw", "ad", username=LOGIN)
    plugin = bp18.ConstructelBridgePlugin(iface)
    plugin._get_qgis_username = lambda: QGIS_USER
    plugin.initGui()

    QgsProject.instance().layerLoaded.emit(0, 12)  # projet ouvert au lancement

    assert [c["user"] for c in calls] == [LOGIN]
    assert plugin._auth_mode == bn.AUTH_MODE_NOMINAL
    assert plugin._ui_ready is False  # aucun dialogue sous l'ecran de demarrage
    iface.initializationCompleted.emit()
    assert len(calls) == 1  # une seule sonde
    plugin.unload()


def test_plugin_enabled_after_startup_uses_a_zero_timer(bp18, monkeypatch, tmp_path):
    from qgis.PyQt.QtCore import QTimer

    iface = _initgui_ready(bp18, monkeypatch, visible=True)
    calls = _install_psycopg2(monkeypatch, [None], _FakeCursor())
    plugin = bp18.ConstructelBridgePlugin(iface)
    plugin.initGui()

    assert calls == []
    assert iface.initializationCompleted.slots == []
    QTimer.run_pending()
    assert plugin._connected is True
    plugin.unload()


def test_unload_before_the_deferred_startup_cancels_it(bp18, monkeypatch, tmp_path):
    from qgis.PyQt.QtCore import QTimer

    iface = _initgui_ready(bp18, monkeypatch, visible=True)
    calls = _install_psycopg2(monkeypatch, [None], _FakeCursor())
    plugin = bp18.ConstructelBridgePlugin(iface)
    plugin.initGui()
    plugin.unload()

    QTimer.run_pending()

    assert calls == []
    assert plugin._ui_ready is False


def test_onboarding_waits_for_the_interactive_phase(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsSettings

    plugin, _calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw")
    QgsSettings().remove("constructel_bridge/onboarding_done")
    runs = []
    plugin._run_onboarding = lambda is_new: runs.append(is_new)

    plugin._auto_connect()
    assert runs == []
    plugin._startup_interactive()
    assert runs == [False]


# --- périmètre (D1/D3) --------------------------------------------------------------


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


# --- mot de passe AD jamais exposé aux chemins partagés (I6) ------------------------


def test_ad_password_never_lands_in_the_shared_password_attribute(bp18, monkeypatch, tmp_path):
    plugin, _c, _a, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [_ldap_failed(), None], stored_ad_pw="ad-pw",
                                        memorized=bn.AUTH_MODE_SHARED)
    plugin._auto_connect()
    assert plugin._auth_mode == bn.AUTH_MODE_SHARED
    assert plugin._password == "shared-pw"

    nominal, _c2, _a2, _cur2 = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw2")
    nominal._auto_connect()
    assert nominal._auth_mode == bn.AUTH_MODE_NOMINAL
    assert nominal._password is None
    assert nominal._ad_password == "ad-pw2"
    assert nominal._init_conn_params()[1] == "ad-pw2"
