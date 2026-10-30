"""Bridge 1.8 volet B10 — i18n FR/EN/PT complet : chaque cle tr("...") du
code du plugin existe dans les trois langues avec un texte non vide, les
trois dictionnaires ont exactement les memes cles, et les substitutions
{var} d'une cle sont identiques d'une langue a l'autre (un {login} oublie
en PT leverait KeyError... ou afficherait la cle brute).
"""
import importlib.util
import re
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "constructel_bridge"


def _load_translations():
    # Charge translations.py par son chemin : le paquet i18n importe
    # qgis.core, inutile ici (dictionnaires purs).
    spec = importlib.util.spec_from_file_location(
        "bridge18_translations", PLUGIN_DIR / "i18n" / "translations.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.TRANSLATIONS


TRANSLATIONS = _load_translations()
_TR_CALL_RE = re.compile(r"\btr\(\s*[\"']([a-z0-9_.]+)[\"']")
_TR_FSTRING_RE = re.compile(r"\btr\(\s*f[\"']([a-z0-9_.]+)\{")
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")

# Prefixes passes dynamiquement : tr(f"mtls.{reason}") -- verifies via
# les cles mtls.* existantes (chaque raison de CertValidationResult).
_DYNAMIC_PREFIXES = {"mtls."}


def _used_keys():
    keys = set()
    for path in PLUGIN_DIR.rglob("*.py"):
        if "i18n" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        keys.update(_TR_CALL_RE.findall(text))
    return keys


def test_same_key_set_in_every_language():
    en, fr, pt = (set(TRANSLATIONS[lang]) for lang in ("en", "fr", "pt"))
    assert fr == en, {"missing_in_fr": en - fr, "extra_in_fr": fr - en}
    assert pt == en, {"missing_in_pt": en - pt, "extra_in_pt": pt - en}


def test_every_key_used_in_code_is_translated():
    used = _used_keys()
    assert used, "no tr() call found -- regex broken?"
    for lang in ("en", "fr", "pt"):
        missing = sorted(k for k in used if k not in TRANSLATIONS[lang])
        assert missing == [], f"{lang}: {missing}"


def test_no_empty_text():
    for lang, table in TRANSLATIONS.items():
        empty = sorted(k for k, v in table.items() if not isinstance(v, str) or not v.strip())
        assert empty == [], f"{lang}: {empty}"


def test_placeholders_match_across_languages():
    for key, en_text in TRANSLATIONS["en"].items():
        en_vars = set(_PLACEHOLDER_RE.findall(en_text))
        for lang in ("fr", "pt"):
            vars_ = set(_PLACEHOLDER_RE.findall(TRANSLATIONS[lang][key]))
            assert vars_ == en_vars, f"{key} ({lang}): {vars_} != {en_vars}"


@pytest.mark.parametrize("key", [
    "menu.retry_nominal", "menu.retry_nominal_shared", "dialog.login", "dialog.login_invalid",
    "dialog.reprompt", "conn.connected_nominal", "nominal.banner", "nominal.retry_failed",
    "nominal.reason_login_disabled", "nominal.reason_auth_refused", "nominal.reason_unavailable",
    "nominal.reason_local_setup", "nominal.reason_no_password",
    "nominal.no_fallback", "nominal.ca_import_failed", "nominal.login_unusable", "nominal.retry_ok",
    "scope.all", "scope.none", "scope.scoped", "scope.readonly", "scope.unknown",
    "scope.layers_locked", "scope.write_refused",
])
def test_bridge18_keys_present_in_three_languages(key):
    for lang in ("en", "fr", "pt"):
        assert TRANSLATIONS[lang][key].strip()


def test_refusal_wording_does_not_blame_the_password_only():
    # Revue 29/10 (I14) : un role absent recoit aussi « password
    # authentication failed » (ligne scram) -> le message cite l'activation.
    for lang, word in (("fr", "activ"), ("en", "activat"), ("pt", "ativad")):
        for key in ("dialog.reprompt", "nominal.reason_auth_refused"):
            assert word in TRANSLATIONS[lang][key].lower(), (lang, key)
