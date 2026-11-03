# resource-repo/tests/asbuilt_depth_geocoder/test_styles_from_farois.py
"""Styles As-Built : source de vérité = Farois (mig 538, 03/11/2026).

``bureau_etudes`` est en lecture seule sur ``public.layer_styles``,
``public.qgis_projects`` et ``public.map_themes`` ; il n'a plus TEMPORARY. Les
styles par défaut des tables ``geofiber_asbuilt_*`` sont poussés par
``farois styles init`` (dépôt Farois, ``styles/asbuilt_depth_*.qml``). Le
script ne doit donc plus rien écrire hors des tables ``geofiber_asbuilt_*`` ni
livrer ses propres ``.qml``.
"""
import re
import sys
from pathlib import Path

COLLECTION = Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder"
SCRIPT = COLLECTION / "processing/geocode_asbuilt_depth.py"

sys.path.insert(0, str(COLLECTION / "processing"))
import geocode_asbuilt_depth as mod  # noqa: E402


def _code_without_comments() -> str:
    """Source du script sans commentaires ``#`` (les docstrings restent)."""
    lines = []
    for line in SCRIPT.read_text(encoding="utf-8").splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


def test_aucune_ecriture_de_style_en_base():
    code = _code_without_comments()
    assert "saveStyleToDatabase" not in code
    assert "_sync_styles_to_db" not in code
    assert "_sync_style_to_db" not in code


def test_aucun_qml_livre_par_la_collection():
    assert not list(COLLECTION.rglob("*.qml"))
    assert "loadNamedStyle" not in _code_without_comments()


def test_pas_de_sql_interdit_depuis_la_538():
    """Ni objet temporaire, ni écriture des tables de projet/thèmes/styles, ni
    fonction d'administration ESB, dans les requêtes SQL du script."""
    code = _code_without_comments()
    forbidden = [
        r"\bCREATE\s+(GLOBAL\s+|LOCAL\s+)?TEMP(ORARY)?\b",
        r"\bpg_temp\b",
        r"\bINTO\s+(TEMP|TEMPORARY)\b",
        # Toute forme qualifiée : public., "public"., {schema}., wyre.
        r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+[^\s;]*?(layer_styles|qgis_projects|map_themes)\b",
        r"\besb\.",
    ]
    for pattern in forbidden:
        assert not re.search(pattern, code, re.IGNORECASE), pattern


def test_message_styles_farois():
    message = mod.STYLES_FROM_FAROIS_MESSAGE
    assert "farois styles init" in message
    assert "styles/" in message
    assert "layer_styles" in message


def test_le_garde_sql_attrape_les_formes_qualifiees():
    pattern = r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+[^\s;]*?(layer_styles|qgis_projects|map_themes)\b"
    for sql in ('UPDATE {schema}.qgis_projects SET', 'INSERT INTO "public"."layer_styles"',
                "DELETE FROM wyre.qgis_projects", "UPDATE map_themes SET"):
        assert re.search(pattern, sql, re.IGNORECASE), sql
    assert re.search(r"\bINTO\s+(TEMP|TEMPORARY)\b", "SELECT 1 INTO TEMP t", re.IGNORECASE)


def test_style_loaded_ok():
    assert mod._style_loaded_ok(("", True)) is True
    assert mod._style_loaded_ok(("Style chargé", True)) is True
    assert mod._style_loaded_ok(("", False)) is False
    assert mod._style_loaded_ok(True) is True
    assert mod._style_loaded_ok(None) is False
    assert mod._style_loaded_ok(1) is False


def test_style_load_message():
    assert mod._style_load_message(("Cannot apply style with symbology", False)) == (
        "Cannot apply style with symbology"
    )
    assert mod._style_load_message(("  ", False)) == ""
    assert mod._style_load_message(None) == ""
