"""Pure-logic tests for bridge_nominatif.py (Bridge 1.8, logins PG
nominatifs LDAPS — plan 2026-10-29, volet B1). No QGIS, no psycopg2, no
network: every function under test takes plain values.

Server facts these tests encode (verified 2026-10-29 on prod):
  * psycopg2.connect() failures carry pgcode=None — the SQLSTATE class 28
    of the spec can only be read from the libpq message text;
  * role names are lower(sAMAccountName), regex ^[a-z0-9._-]{1,63}$.
"""
from pathlib import Path

import pytest

from constructel_bridge import bridge_nominatif as bn


# --- resolve_pg_login ---------------------------------------------------------


def test_resolve_pg_login_lowercases_windows_username():
    assert bn.resolve_pg_login("SimonDucourneau") == "simonducourneau"


def test_resolve_pg_login_strips_surrounding_whitespace():
    assert bn.resolve_pg_login("  jdoe ") == "jdoe"


@pytest.mark.parametrize("bad", ["", "   ", "jean dupont", "a" * 64, "domain\\user", "o'neil", "x@y"])
def test_resolve_pg_login_rejects_names_outside_server_regex(bad):
    assert bn.resolve_pg_login(bad) == ""


def test_resolve_pg_login_accepts_dots_dashes_underscores():
    assert bn.resolve_pg_login("j.doe_ext-1") == "j.doe_ext-1"


# --- classify_auth_failure ------------------------------------------------------


class _PgErr(Exception):
    def __init__(self, message, pgcode=None):
        super().__init__(message)
        self.pgcode = pgcode


_LIBPQ = 'connection to server at "192.168.160.31", port 5432 failed: FATAL:  '


def test_password_authentication_failed_is_auth_refused():
    exc = _PgErr(_LIBPQ + 'password authentication failed for user "jdoe"')
    assert bn.classify_auth_failure(exc) == bn.AUTH_REFUSED


def test_ldap_authentication_failed_is_auth_refused():
    exc = _PgErr(_LIBPQ + 'LDAP authentication failed for user "jdoe"')
    assert bn.classify_auth_failure(exc) == bn.AUTH_REFUSED


def test_role_not_permitted_to_log_in_is_login_disabled():
    exc = _PgErr(_LIBPQ + 'role "jdoe" is not permitted to log in')
    assert bn.classify_auth_failure(exc) == bn.LOGIN_DISABLED


def test_role_does_not_exist_is_login_disabled():
    exc = _PgErr(_LIBPQ + 'role "jdoe" does not exist')
    assert bn.classify_auth_failure(exc) == bn.LOGIN_DISABLED


def test_no_pg_hba_entry_is_login_disabled():
    exc = _PgErr(_LIBPQ + 'no pg_hba.conf entry for host "10.1.2.3", user "jdoe", database "farois_ftth", SSL encryption')
    assert bn.classify_auth_failure(exc) == bn.LOGIN_DISABLED


def test_sqlstate_28p01_is_auth_refused_other_28_is_login_disabled():
    assert bn.classify_auth_failure(_PgErr("something odd", pgcode="28P01")) == bn.AUTH_REFUSED
    assert bn.classify_auth_failure(_PgErr("something odd", pgcode="28000")) == bn.LOGIN_DISABLED


# Revue 29/10 (I2) : lc_messages francais du serveur (PostgreSQL 17, fr.po).
_LIBPQ_FR = 'la connexion au serveur sur « 192.168.160.31 », port 5432 a échoué : FATAL:  '


@pytest.mark.parametrize("message, kind", [
    (_LIBPQ_FR + "authentification par mot de passe échouée pour l'utilisateur  « jdoe »", bn.AUTH_REFUSED),
    (_LIBPQ_FR + "authentification LDAP échouée pour l'utilisateur « jdoe »", bn.AUTH_REFUSED),
    (_LIBPQ_FR + "le rôle « jdoe » n'est pas autorisé à se connecter", bn.LOGIN_DISABLED),
    (_LIBPQ_FR + "le rôle « jdoe » n'existe pas", bn.LOGIN_DISABLED),
    (_LIBPQ_FR + "aucune entrée dans pg_hba.conf pour l'hôte « 10.1.2.3 », utilisateur « jdoe »,\n"
                 "base de données « farois_ftth », chiffrement SSL", bn.LOGIN_DISABLED),
    (_LIBPQ_FR + "pg_hba.conf rejette la connexion pour l'hôte « 10.1.2.3 »", bn.LOGIN_DISABLED),
    (_LIBPQ + 'pg_hba.conf rejects connection for host "10.1.2.3", user "jdoe"', bn.LOGIN_DISABLED),
])
def test_french_and_pg_hba_reject_messages_are_classified(message, kind):
    assert bn.classify_auth_failure(_PgErr(message)) == kind


@pytest.mark.parametrize("message", [
    _LIBPQ + 'too many connections for role "jdoe"',
    _LIBPQ_FR + "trop de connexions pour le rôle « jdoe »",
    _LIBPQ + "canceling authentication due to timeout",
    _LIBPQ_FR + "annulation de l'authentification à cause du délai écoulé",
    _LIBPQ + 'certificate authentication failed for user "jdoe"',
])
def test_non_password_server_failures_are_not_a_password_refusal(message):
    # Pas de ressaisie : l'orchestrateur replie (I2).
    assert bn.classify_auth_failure(_PgErr(message)) != bn.AUTH_REFUSED


@pytest.mark.parametrize("message", [
    'connection to server at "192.168.160.31", port 5432 failed: Connection refused',
    'root certificate file "/x/root.crt" does not exist',
    'FATAL:  database "farois_ftth" does not exist',
    'server certificate for "farois-db" does not match host name "192.168.160.31"',
    "could not connect to server: timeout expired",
])
def test_non_auth_errors_are_not_classified(message):
    assert bn.classify_auth_failure(_PgErr(message)) is None


def test_classify_never_raises_on_exotic_exception():
    assert bn.classify_auth_failure(OSError(111, "Connection refused")) is None


# --- should_reprompt (I2 : une seule ressaisie, <= 2 binds refuses) ---------------


def test_password_refusal_reprompts_once_in_nominal_or_first_run():
    assert bn.should_reprompt(bn.AUTH_REFUSED, bn.AUTH_MODE_NOMINAL, 1) is True
    assert bn.should_reprompt(bn.AUTH_REFUSED, "", 1) is True


def test_never_more_than_two_refused_binds():
    assert bn.MAX_REFUSED_BINDS == 2
    assert bn.should_reprompt(bn.AUTH_REFUSED, bn.AUTH_MODE_NOMINAL, 2) is False
    assert bn.should_reprompt(bn.AUTH_REFUSED, bn.AUTH_MODE_NOMINAL, 2, explicit=True) is False


def test_shared_workstation_startup_never_reprompts_but_explicit_action_does():
    assert bn.should_reprompt(bn.AUTH_REFUSED, bn.AUTH_MODE_SHARED, 1) is False
    assert bn.should_reprompt(bn.AUTH_REFUSED, bn.AUTH_MODE_SHARED, 1, explicit=True) is True


@pytest.mark.parametrize("kind", [bn.LOGIN_DISABLED, None, "unavailable", "local_setup"])
def test_only_a_password_refusal_reprompts(kind):
    assert bn.should_reprompt(kind, bn.AUTH_MODE_NOMINAL, 1, explicit=True) is False


# --- normalize_login (I5) -----------------------------------------------------------


@pytest.mark.parametrize("typed, login", [
    ("CONSTRUCTELBE\\JDoe", "jdoe"),
    ("jdoe@constructelbe.corp", "jdoe"),
    ("J.Doe@constructel.be", "j.doe"),
    ("  JDoe  ", "jdoe"),
    ("ftth_editor", "ftth_editor"),
    ("jean dupont", ""),
    ("DOM\\", ""),
    ("@constructel.be", ""),
])
def test_normalize_login(typed, login):
    assert bn.normalize_login(typed) == login


# --- pem_blocks -------------------------------------------------------------------

CA_A = (
    "-----BEGIN CERTIFICATE-----\n"
    "MIIBaaaa\nBBBB\n"
    "-----END CERTIFICATE-----\n"
)
CA_B = (
    "-----BEGIN CERTIFICATE-----\n"
    "MIIBbbbb\n"
    "-----END CERTIFICATE-----\n"
)


def test_pem_blocks_extracts_normalized_certificates():
    blocks = bn.pem_blocks("junk\n" + CA_A + "more junk\n" + CA_B)
    assert len(blocks) == 2
    assert all(b.startswith("-----BEGIN CERTIFICATE-----") for b in blocks)


# --- rewrite_datasource_nominal -------------------------------------------------

_DS = ("dbname='farois_ftth' host=192.168.160.31 port=5432 user='ftth_editor' password='s3cret' "
       "sslmode=require authcfg=abc1234 key='id' estimatedmetadata=true srid=31370 type=MultiPolygon "
       "checkPrimaryKeyUnicity='0' table=\"wyre\".\"zone_pop\" (geom)")


def test_rewrite_drops_password_and_sets_login_authcfg_verify_full():
    out = bn.rewrite_datasource_nominal(_DS, "jdoe", "9i19s56")
    assert "password=" not in out
    assert "user='jdoe'" in out
    assert "authcfg=9i19s56" in out
    assert "sslmode=verify-full" in out
    assert "sslmode=require" not in out
    assert "user='ftth_editor'" not in out
    assert out.count("user=") == 1
    assert out.count("authcfg=") == 1
    assert out.count("sslmode=") == 1


def test_rewrite_keeps_table_and_geometry_clauses_intact():
    out = bn.rewrite_datasource_nominal(_DS, "jdoe", "9i19s56")
    assert "table=\"wyre\".\"zone_pop\" (geom)" in out
    assert "key='id'" in out
    assert "srid=31370" in out


def test_rewrite_handles_datasource_without_credentials():
    ds = "dbname='farois_ftth' host=192.168.160.31 port=5432 key='rid' table=\"ref\".\"v_form_lists\""
    out = bn.rewrite_datasource_nominal(ds, "jdoe", "9i19s56")
    assert "user='jdoe'" in out and "authcfg=9i19s56" in out and "sslmode=verify-full" in out
    assert "  " not in out


def test_rewrite_is_idempotent():
    once = bn.rewrite_datasource_nominal(_DS, "jdoe", "9i19s56")
    assert bn.rewrite_datasource_nominal(once, "jdoe", "9i19s56") == once


# Revue 29/10 (I12/M5) : filtre sql= jamais touche, valeurs echappees comprises.
_SQL = "sql=\"owner\" = 'user=x' AND note = 'sslmode=require password=''y''' AND  code <> 'a  b'"
_DS_FILTERED = ("dbname='farois_ftth' host=192.168.160.31 port=5432 user='ftth_editor' "
                "password='pa\\'ss word' sslmode=require authcfg=abc1234 key='id' srid=31370 "
                "table=\"wyre\".\"ducts\" (geom) " + _SQL)


def test_parse_datasource_follows_qgis_quoting_rules():
    params, sql_start = bn.parse_datasource(_DS_FILTERED)
    values = {name: value for (name, value, _s, _e) in params}
    assert values["password"] == "pa'ss word"
    assert values["table"] == "wyre.ducts"
    assert "sql" not in values
    assert _DS_FILTERED[sql_start:] == _SQL
    raw = {name: _DS_FILTERED[s:e] for (name, _v, s, e) in params}
    assert raw["table"] == 'table="wyre"."ducts" (geom)'
    assert raw["password"] == "password='pa\\'ss word'"


def test_datasource_param_ignores_the_filter():
    ds = "host=h table=\"s\".\"t\" sql=user = 'bob' AND authcfg = 'x'"
    assert bn.datasource_param(ds, "user") is None
    assert bn.datasource_param(ds, "authcfg") is None
    assert bn.datasource_param(ds, "host") == "h"


def test_rewrite_nominal_inserts_before_table_and_keeps_filter_verbatim():
    out = bn.rewrite_datasource_nominal(_DS_FILTERED, "jdoe", "9i19s56")
    assert out.endswith(" " + _SQL)
    head = out[: out.index(" sql=")]
    assert head.index("authcfg=9i19s56") < head.index("table=")
    assert "pa\\'ss" not in out and "ss word" not in head
    assert head.count("user=") == 1 and head.count("sslmode=") == 1 and head.count("authcfg=") == 1
    assert bn.datasource_param(out, "authcfg") == "9i19s56"
    assert bn.rewrite_datasource_nominal(out, "jdoe", "9i19s56") == out


def test_rewrite_identity_shared_plaintext_escapes_and_keeps_sslmode():
    out = bn.rewrite_datasource_identity(_DS_FILTERED, "ftth_editor", password="s'h\\x")
    assert bn.datasource_param(out, "password") == "s'h\\x"
    assert bn.datasource_param(out, "authcfg") is None
    assert bn.datasource_param(out, "sslmode") == "require"
    assert out.endswith(" " + _SQL)


def test_force_sslmode_touches_only_sslmode():
    out = bn.force_datasource_sslmode(_DS_FILTERED, "verify-full")
    assert bn.datasource_param(out, "sslmode") == "verify-full"
    assert bn.datasource_param(out, "authcfg") == "abc1234"
    assert bn.datasource_param(out, "password") == "pa'ss word"
    assert out.endswith(" " + _SQL)


def test_rewrite_datasource_without_table_appends_at_the_end():
    out = bn.rewrite_datasource_nominal("dbname='d' host=h port=5432 user='x'", "jdoe", "9i19s56")
    assert out == "dbname='d' host=h port=5432 user='jdoe' sslmode=verify-full authcfg=9i19s56"


# --- SessionScope ---------------------------------------------------------------


def test_parse_scope_admin_bypass_when_arrays_are_null():
    scope = bn.parse_session_scope(("ADMIN", True, True, None, None, None, None))
    assert scope.bypass is True
    assert scope.network_write is True
    assert bn.scope_kind(scope) == "all"


def test_parse_scope_designer_with_write_on_one_mro():
    scope = bn.parse_session_scope(("DESIGNER", True, True, ["m1", "m2"], ["m1"], [], []))
    assert scope.bypass is False
    assert scope.mro_ids == ["m1", "m2"]
    assert scope.mro_write_ids == ["m1"]
    assert bn.scope_kind(scope) == "scoped"


def test_parse_scope_without_any_perimeter_is_none():
    scope = bn.parse_session_scope(("DESIGNER", True, True, [], [], [], []))
    assert bn.scope_kind(scope) == "none"


def test_parse_scope_viewer_is_read_only():
    scope = bn.parse_session_scope(("VIEWER", True, False, ["m1"], [], [], []))
    assert scope.network_write is False
    assert bn.scope_kind(scope) == "scoped"


def test_parse_scope_unresolved_session_has_no_role():
    # current_gis_role() renvoie NULL pour un login be (hors ref.users).
    scope = bn.parse_session_scope((None, False, False, [], [], [], []))
    assert scope.role is None
    assert scope.network_read is False
    assert bn.scope_kind(scope) == "none"


def test_scope_labels_prefer_names_and_fall_back_to_short_ids():
    labels = bn.scope_labels(["11111111-2222-3333-4444-555555555555", "m2"], {"m2": "MRO Bxl"})
    assert labels == ["11111111", "MRO Bxl"]


def test_should_lock_layer_only_network_schemas_without_write():
    ro = bn.parse_session_scope(("VIEWER", True, False, ["m1"], [], [], []))
    rw = bn.parse_session_scope(("DESIGNER", True, True, ["m1"], ["m1"], [], []))
    assert bn.should_lock_layer("wyre", ro) is True
    # Revue 29/10 (I8) : schema wyre seulement (plan D2) ; chantier/docs
    # restent modifiables (spec D11), osiris n'est pas du reseau edite.
    for schema in ("osiris", "chantier", "docs"):
        assert bn.should_lock_layer(schema, ro) is False, schema
    assert bn.should_lock_layer("public", ro) is False
    assert bn.should_lock_layer("ref", ro) is False
    assert bn.should_lock_layer("wyre", rw) is False
    assert bn.should_lock_layer("wyre", None) is False  # mode partage : statu quo


@pytest.mark.parametrize("message", [
    "ERROR:  permission denied for table cables",
    "new row violates row-level security policy for table \"cables\"",
    "ERROR: [gis_scope] hors perimetre (MRO 1234)",
    "SQLSTATE 42501",
])
def test_scope_write_refusal_is_recognised(message):
    assert bn.is_scope_write_refusal(message) is True


def test_unrelated_commit_error_is_not_a_scope_refusal():
    assert bn.is_scope_write_refusal("duplicate key value violates unique constraint") is False
    assert bn.scope_refusal_kind("duplicate key value violates unique constraint") is None


@pytest.mark.parametrize("message, kind", [
    ('new row violates row-level security policy for table "cables"', bn.SCOPE_REFUSAL_PERIMETER),
    ("la nouvelle ligne viole la politique de sécurité au niveau ligne pour la table « cables »",
     bn.SCOPE_REFUSAL_PERIMETER),
    ("ERROR: [gis_scope] hors perimetre (MRO 1234)", bn.SCOPE_REFUSAL_PERIMETER),
    ("ERROR:  permission denied for table cables", bn.SCOPE_REFUSAL_RIGHT),
    ("ERREUR:  droit refusé pour la table cables", bn.SCOPE_REFUSAL_RIGHT),
    ("SQLSTATE 42501", bn.SCOPE_REFUSAL_UNKNOWN),
])
def test_scope_refusal_kind_distinguishes_perimeter_and_right(message, kind):
    # Revue 29/10 (M7) : un droit manquant n'est pas presente comme « hors perimetre ».
    assert bn.scope_refusal_kind(message) == kind
