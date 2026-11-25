"""Bridge 2.0, tache 10 (plan 2026-11-18, spec § 8.4) : revue i18n, version 2.0.0.

- toutes les cles ajoutees par le chantier (home.*, diag.restart) existent en
  FR / EN / PT, avec les memes variables {x} ;
- aucun appel tr() des modules 2.0 n'a de cle dynamique ;
- aucune cle orpheline nouvelle, et les cles de l'ecran 1.9 sont retirees ;
- metadata.txt en version 2.0.0, avec son entree de changelog.
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
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TRANSLATIONS = _load("bridge20_translations", "i18n/translations.py").TRANSLATIONS

# Cles ajoutees par les taches 2 a 9 de la 2.0 (diff de translations.py depuis la 1.9.0).
KEYS_20 = [
    "diag.restart",
    "home.btn_load", "home.checkin_full", "home.checkin_plugins", "home.checkin_profile",
    "home.checkin_profile_offline", "home.checkin_sharing", "home.checkin_title", "home.common_only",
    "home.configure", "home.fm_configured", "home.fm_missing", "home.group_loaded", "home.load_partial",
    "home.load_summary", "home.my_presets", "home.nav_checkin", "home.nav_diagnostic", "home.nav_load",
    "home.nav_projects", "home.none_operator", "home.options",
    "home.projects_common", "home.projects_error", "home.projects_offline", "home.projects_open",
    "home.projects_search", "home.projects_title",   # 2.1 : home.projects_projets retiree (REMOVED_20)
    "home.row_all", "home.row_common", "home.row_none", "home.row_operator",
    "home.rs_configured", "home.rs_missing", "home.save_preset", "home.save_preset_prompt",
    "home.sharing_na", "home.show_expert", "home.step_layers", "home.step_perimeter", "home.step_presets",
    "home.tile.cables", "home.tile.cadastre", "home.tile.chantier", "home.tile.demand_points",
    "home.tile.genie_civil", "home.tile.osiris", "home.tile.urbanisme", "home.tile.zones",
    "home.tile_done", "home.tile_layers",
    # 2.0.2 : singuliers (« 1 couche », « 1 fond de plan »)
    "home.tile_layer_one", "home.loaded_operator_one", "home.loaded_common_one", "home.loaded_basemaps_one",
]

# Modules crees ou refaits par le chantier 2.0 : jamais de cle dynamique.
MODULES_20 = ["bridge_presets.py", "bridge_layer_selection.py", "bridge_home_load.py", "bridge_home_checkin.py",
              "bridge_home_projects.py", "bridge_home.py", "bridge_home_model.py"]

# Cles de l'ecran 1.9 retirees avant (revue 1.9) ou pendant la 2.0 (taches 9 et 10).
REMOVED_20 = ["home.common_tag", "init.custom_desc", "init.custom_select", "init.group_layers",
              "init.group_template", "init.select_all", "init.select_none",
              "home.projects_projets"]   # 2.1 : « Projets » nu ambigu, remplace par qgis.legacy_projet_group

# Heritees d'avant le chantier 1.9 (test_bridge19_i18n.LEGACY_ORPHANS), seules orphelines admises.
LEGACY_ORPHANS = {
    "dialog.role", "dialog.save_password", "init.confirm", "init.confirm_title",
    "lang.restart", "pg.already_configured",
}
DYNAMIC_PREFIXES = ("mtls.",)


def _py_files():
    return [p for p in sorted(PLUGIN_DIR.rglob("*.py")) if "i18n" not in p.parts]


def _variables(text: str) -> set:
    return set(_PLACEHOLDER_RE.findall(text))


@pytest.mark.parametrize("key", KEYS_20)
def test_bridge20_keys_present_with_the_same_variables_in_three_languages(key):
    for lang in ("en", "fr", "pt"):
        assert TRANSLATIONS[lang][key].strip(), (lang, key)
    expected = _variables(TRANSLATIONS["en"][key])
    for lang in ("fr", "pt"):
        assert _variables(TRANSLATIONS[lang][key]) == expected, (lang, key)


def test_languages_have_exactly_the_same_keys():
    assert set(TRANSLATIONS["fr"]) == set(TRANSLATIONS["en"]) == set(TRANSLATIONS["pt"])


@pytest.mark.parametrize("module", MODULES_20)
def test_no_dynamic_tr_key_in_20_modules(module):
    path = PLUGIN_DIR / module
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr":
            first = node.args[0] if node.args else None
            assert isinstance(first, ast.Constant) and isinstance(first.value, str), (
                f"{module}:{node.lineno} tr() sans cle litterale : {ast.unparse(node)[:80]}"
            )


def test_every_20_key_is_used_by_the_plugin():
    text = "".join(p.read_text(encoding="utf-8") for p in _py_files())
    unused = [k for k in KEYS_20 if f'"{k}"' not in text and f"'{k}'" not in text]
    assert unused == []


def test_no_new_orphan_key_and_no_exception_list():
    text = "".join(p.read_text(encoding="utf-8") for p in _py_files())
    orphans = {
        key for key in TRANSLATIONS["en"]
        if f'"{key}"' not in text and f"'{key}'" not in text and not key.startswith(DYNAMIC_PREFIXES)
    }
    assert orphans == LEGACY_ORPHANS, {"new": orphans - LEGACY_ORPHANS, "now_used": LEGACY_ORPHANS - orphans}


def test_1_9_screen_keys_are_gone_in_every_language():
    for lang in ("en", "fr", "pt"):
        assert [k for k in REMOVED_20 if k in TRANSLATIONS[lang]] == [], lang


def test_portuguese_common_only_text_is_accented():
    assert TRANSLATIONS["pt"]["home.common_only"] == (
        "Nenhum operador disponível: só as camadas comuns podem ser carregadas.")


def test_metadata_is_220():
    # 2.2.0 : version courante ; les entrees precedentes restent en retrait.
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    assert "\nversion=2.2.0\n" in meta and "\nchangelog=v2.2.0 - " in meta
    assert (meta.index("\nchangelog=v2.2.0 - ") < meta.index("\n    v2.1.4 - ") < meta.index("\n    v2.1.3 - ")
            < meta.index("\n    v2.1.2 - ") < meta.index("\n    v2.1.1 - ") < meta.index("\n    v2.1.0 - ")
            < meta.index("\n    v2.0.4 - ")
            < meta.index("\n    v2.0.3 - ") < meta.index("\n    v2.0.2 - ") < meta.index("\n    v2.0.1 - ")
            < meta.index("\n    v2.0.0 - ") < meta.index("\n    v1.9.0 - ") < meta.index("\n    v1.8.4 - "))


def test_220_changelog_is_ascii_and_names_the_change():
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    entry = meta[meta.index("changelog=v2.2.0 - "):meta.index("\n    v2.1.4 - ")]
    assert entry.isascii() and "\n" not in entry
    assert entry.startswith("changelog=v2.2.0 - feat(plugin): schema des couches de projet lu dans le registre")
    for word in ("projet_tables", "schema_name", "data", "596", "repointe", "en memoire",
                 "avant comme apres", "relocate-sources"):
        assert word in entry, word


def test_214_changelog_is_ascii_and_names_the_fix():
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    entry = meta[meta.index("v2.1.4 - "):meta.index("\n    v2.1.3 - ")]
    assert entry.isascii() and "\n" not in entry
    assert entry.startswith("v2.1.4 - fix(plugin): carte vide et fonds UrbIS d un projet QGIS 4.2 ouvert en QGIS 3, styles par defaut de la base")
    for word in ("readOnly", "Style loading error", "zones gelees", "unnest", "SCR du projet", "QGIS 4.2",
                 "EPSG:31370", "UrbIS", "tile matrix set", "Cote serveur : aucune modification"):
        assert word in entry, word


def test_213_changelog_is_ascii_and_names_the_fix():
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    entry = meta[meta.index("v2.1.3 - "):meta.index("\n    v2.1.2 - ")]
    assert entry.isascii() and "\n" not in entry
    assert entry.startswith("v2.1.3 - fix(plugin): la disquette et Ctrl+S enregistrent en base")
    for word in ("constructel-bridge", "FP409", "rien n est ecrase", "peut modifier", "Enregistrer sous",
                 "Projets recents"):
        assert word in entry, word


def test_212_changelog_is_ascii_and_names_the_fix():
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    entry = meta[meta.index("v2.1.2 - "):meta.index("\n    v2.1.1 - ")]
    assert entry.isascii() and "\n" not in entry
    assert entry.startswith("v2.1.2 - fix(plugin): page Projets QGIS lisible")
    for word in ("tronques", "En-tetes", "FR/EN/PT", "Projet metier", "Detail", "Login partage"):
        assert word in entry, word


def test_211_changelog_is_ascii_and_names_the_fix():
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    entry = meta[meta.index("v2.1.1 - "):meta.index("\n    v2.1.0 - ")]
    assert entry.isascii() and "\n" not in entry
    assert entry.startswith("v2.1.1 - fix(plugin): zones gelees OSIRIS")
    for word in ("v_frozen_zones_communs", "frozen_zones", "ogc_fid", "ftth_reader_communs", "573", "sans la vue"):
        assert word in entry, word


def test_210_changelog_is_ascii_and_names_the_features():
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    entry = meta[meta.index("v2.1.0 - "):meta.index("\n    v2.0.4 - ")]
    assert entry.isascii() and "\n" not in entry
    assert entry.startswith("v2.1.0 - feat(plugin): projets metier et projets QGIS")
    lowered = entry.lower()
    for word in ("projets metier", "mes projets", "partages avec moi", "publies", "autocompletion", "nominatif",
                 "conflit de version", "neutralise", "le sien compris", "sans schema projet", "macros",
                 "demander", "583"):
        assert word in lowered, word


def test_204_changelog_is_ascii_and_names_the_fix():
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    entry = meta[meta.index("v2.0.4 - "):meta.index("\n    v2.0.3 - ")]
    assert entry.isascii() and "\n" not in entry
    assert entry.startswith("v2.0.4 - fix(plugin): fonds de carte UrbIS")
    assert "urbisFRGray" in entry and "geoservices-basemap.irisnet.be" in entry and "UrbIS NL" in entry


def test_203_changelog_is_ascii_and_names_the_fix():
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    entry = meta[meta.index("v2.0.3 - "):meta.index("\n    v2.0.2 - ")]
    assert entry.isascii() and "\n" not in entry
    assert entry.startswith("v2.0.3 - fix(plugin): couches Chantier")
    assert "complaints" in entry and "worksite_interventions" in entry and "facade_planning" in entry


def test_202_changelog_is_ascii_and_names_the_fix():
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    entry = meta[meta.index("v2.0.2 - "):meta.index("\n    v2.0.1 - ")]
    assert entry.isascii() and "\n" not in entry
    assert entry.startswith("v2.0.2 - fix(plugin): mise en forme de l ecran d accueil")


def test_201_changelog_is_ascii_and_names_the_fix():
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    entry = meta[meta.index("v2.0.1 - "):meta.index("\n    v2.0.0 - ")]
    assert entry.isascii() and "\n" not in entry
    assert "qtreewidgetitem" in entry.lower() and "vrais widgets qt" in entry.lower()


def test_200_changelog_is_ascii_and_mentions_the_delivered_features():
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    start = meta.index("v2.0.0 - ")
    entry = meta[start:meta.index("\n    v1.9.0 - ")]
    assert entry.isascii(), [c for c in entry if ord(c) > 127]
    assert "\n" not in entry
    lowered = entry.lower()
    for word in ("barre laterale", "charger", "projets", "check-in", "diagnostic", "plusieurs operateurs",
                 "communes", "sans operateur", "deux rangees", "arbre", "mes presets", "dernier choix",
                 "recherche", "schema projet", "assistant", "relancer", "setup non rejoue", "onboarding_done"):
        assert word in lowered, word

