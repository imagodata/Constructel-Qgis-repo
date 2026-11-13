"""Bridge 1.9, tache 10 : revue i18n, metadata 1.9.0.

- toutes les cles ajoutees par le chantier (home.*, diag.*, profil hors
  connexion) existent en FR / EN / PT ;
- aucun appel tr() des modules 1.9 n'a de cle dynamique, et chaque appel
  litteral du paquet passe exactement les variables {x} du texte (un {x}
  oublie leverait KeyError a l'affichage) ;
- aucune cle orpheline nouvelle (les orphelines heritees sont listees) ;
- le groupe « Commun » est traduit ;
- version et changelog 1.9.0.
"""
from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "constructel_bridge"
_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")


def _load(name: str, relative: str):
    # Par chemin : le paquet i18n importe qgis.core, inutile pour des dictionnaires.
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TRANSLATIONS = _load("bridge19_translations", "i18n/translations.py").TRANSLATIONS
GROUP_NAMES = _load("bridge19_layer_translations", "i18n/layer_translations.py").GROUP_NAMES

KEYS_19 = [
    "home.no_operator", "home.reorganized", "home.not_connected", "home.connect", "home.tile_load",
    "home.operator_label", "home.btn_init", "home.btn_add", "home.loaded_title", "home.loaded_operator",
    "home.loaded_basemaps", "home.common_tag", "home.connect_to_see", "home.suffix_checkbox",
    "home.tile_project", "home.tile_project_sub", "home.tile_checkin", "home.tile_checkin_sub",
    "home.tile_checkin_updates", "home.tile_diagnostic", "home.tile_diagnostic_sub",
    "home.tile_language", "home.tile_language_sub", "onboard.action.profile_offline",
    "diag.title", "diag.running", "diag.section_connection", "diag.version_ok", "diag.version_update",
    "diag.version_unknown", "diag.plugin_ok", "diag.plugin_update", "diag.plugin_inactive",
    "diag.plugin_missing", "diag.server_ok", "diag.server_unreachable", "diag.server_tls_refused",
    "diag.server_cert_invalid", "diag.identity_ok", "diag.identity_no_password", "diag.identity_derived",
    "diag.identity_none", "diag.action_install", "diag.action_update", "diag.action_activate",
    "diag.action_plugin_manager",
    # Cles ajoutees en cours de chantier (hors liste de la fiche) : reorganisation et chargement
    # du seul groupe Commun, fonds de plan seuls, rien d'ajoute.
    "home.loaded_common", "home.reorganized_common", "init.success_basemaps", "init.nothing_added",
]

# Modules crees par le chantier 1.9 : jamais de cle dynamique.
MODULES_19 = ["bridge_operators.py", "bridge_home_model.py", "bridge_home.py",
              "bridge_diagnostic.py", "bridge_diagnostic_dialog.py"]

# Cles inutilisees avant le chantier 1.9, conservees (hors perimetre). Une nouvelle cle
# orpheline fait echouer test_no_new_orphan_key ; mtls.* est resolue dynamiquement
# (tr(f"mtls.{raison}")) et verifiee par test_bridge18_i18n.
LEGACY_ORPHANS = {
    "dialog.role", "dialog.save_password", "init.confirm", "init.confirm_title",
    "lang.restart", "pg.already_configured",
}
DYNAMIC_PREFIXES = ("mtls.",)
# Cles retirees par la revue : plus aucun appelant depuis l'accueil (init.*) et le Diagnostic (status.title).
REMOVED_KEYS = ["status.title", "init.title", "init.title_add"]


def _py_files():
    return [p for p in sorted(PLUGIN_DIR.rglob("*.py")) if "i18n" not in p.parts]


def _tr_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr":
            yield node


@pytest.mark.parametrize("key", KEYS_19)
def test_bridge19_keys_present_in_three_languages(key):
    for lang in ("en", "fr", "pt"):
        assert TRANSLATIONS[lang][key].strip(), (lang, key)


def test_common_group_translated():
    assert GROUP_NAMES["Commun"] == {"fr": "Commun", "en": "Common", "pt": "Comum"}


@pytest.mark.parametrize("module", MODULES_19)
def test_no_dynamic_tr_key_in_19_modules(module):
    for call in _tr_calls(PLUGIN_DIR / module):
        first = call.args[0] if call.args else None
        assert isinstance(first, ast.Constant) and isinstance(first.value, str), (
            f"{module}:{call.lineno} tr() sans cle litterale : {ast.unparse(call)[:80]}"
        )


def test_literal_tr_calls_pass_exactly_the_placeholders_of_their_text():
    checked = 0
    for path in _py_files():
        for call in _tr_calls(path):
            first = call.args[0] if call.args else None
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                continue  # tables de cles historiques (desc_key, _REASON_KEYS...)
            if any(k.arg is None for k in call.keywords):
                continue  # tr(key, **params) : verifie par le test de chaque module
            expected = set(_PLACEHOLDER_RE.findall(TRANSLATIONS["en"][first.value]))
            given = {k.arg for k in call.keywords}
            assert given == expected, f"{path.name}:{call.lineno} {first.value}: {given} != {expected}"
            checked += 1
    assert checked > 100, "garde cassee : trop peu d'appels releves"


def test_removed_keys_are_gone_in_every_language():
    for lang in ("en", "fr", "pt"):
        assert [k for k in REMOVED_KEYS if k in TRANSLATIONS[lang]] == [], lang


def test_no_new_orphan_key():
    text = "".join(p.read_text(encoding="utf-8") for p in _py_files())
    orphans = {
        key for key in TRANSLATIONS["en"]
        if f'"{key}"' not in text and f"'{key}'" not in text and not key.startswith(DYNAMIC_PREFIXES)
    }
    assert orphans == LEGACY_ORPHANS, {"new": orphans - LEGACY_ORPHANS, "now_used": LEGACY_ORPHANS - orphans}


def test_metadata_is_190():
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    assert "\nversion=1.9.0\n" in meta and "\nchangelog=v1.9.0 - " in meta
    # L'entree precedente reste dans l'historique, en retrait comme les autres.
    assert "\n    v1.8.4 - " in meta


def test_190_changelog_is_ascii_and_mentions_the_delivered_features():
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    start = meta.index("changelog=v1.9.0 - ")
    entry = meta[start:meta.index("\n    v1.8.4 - ")]
    assert entry.isascii(), [c for c in entry if ord(c) > 127]
    assert "\n" not in entry
    for word in ("accueil", "commun", "suffixe", "diagnostic", "hors connexion", "navigateur qgis",
                 "projet enregistre", "lecture seule", "prerequis"):
        assert word in entry.lower(), word
