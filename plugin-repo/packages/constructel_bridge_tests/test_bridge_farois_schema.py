"""Garde-fou 2.0.3 : le catalogue de couches ne doit plus pointer vers une table
renommee ou une geometrie inexistante cote Farois (Plaintes, Interventions
chantier, Planning facades, Interventions). Compare chaque entree non WFS et non
operateur de LAYER_CATALOG a farois_schema_snapshot.txt (extrait de
sql/schema_inventory/golden.txt de Farois ; procedure de rafraichissement en
tete du fichier). Lit le catalogue par ast : aucun QGIS requis."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from constructel_bridge_tests.fakes19 import WYRE, install_fake_project
from constructel_bridge_tests.test_bridge18_layers import (  # noqa: F401  (pi = fixture)
    _FakeIface,
    _shared_plugin,
    pi,
)

TESTS_DIR = Path(__file__).resolve().parent
MODULE = TESTS_DIR.parent / "constructel_bridge" / "bridge_project_init.py"
SNAPSHOT = TESTS_DIR / "farois_schema_snapshot.txt"
OPERATOR_GROUPS = ("Demand Points", "Infrastructure", "Zones")


def _module_literal(name):
    for node in ast.parse(MODULE.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} introuvable dans {MODULE.name}")


def _snapshot():
    """{(schema, table): {colonne: type}}"""
    relations: dict = {}
    for line in SNAPSHOT.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        kind, path, type_ = line.split(" ", 2)
        assert kind == "col", line
        schema, table, column = path.split(".")
        relations.setdefault((schema, table), {})[column] = type_
    return relations


def _checked_entries():
    """Entrees PostgreSQL non operateur du catalogue (hors WFS)."""
    return [e for e in _module_literal("LAYER_CATALOG") if e[2] != "wfs" and e[1] not in OPERATOR_GROUPS]


SNAPSHOT_RELATIONS = _snapshot()
ENTRIES = _checked_entries()


def test_snapshot_is_not_empty_and_covers_the_chantier_tables():
    assert {t for s, t in SNAPSHOT_RELATIONS if s == "chantier"} >= {
        "interventions", "complaints", "worksite_interventions", "facade_planning"}


def test_the_check_covers_every_non_operator_entry():
    keys = {e[0] for e in ENTRIES}
    assert {"interventions", "plaintes", "interventions_chantier", "planning_facades", "osiris_frozen",
            "docs_elements", "v_form_lists"} <= keys
    assert not keys & {"cables", "zone_pop", "wfs_parcels"}


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e[0])
def test_catalog_entry_matches_the_farois_schema(entry):
    key, _group, schema, table, geom_col, pk, _label = entry
    columns = SNAPSHOT_RELATIONS.get((schema, table))
    assert columns, f"{key}: la table {schema}.{table} n'est pas dans farois_schema_snapshot.txt (renommee cote Farois ?)"
    if geom_col is not None:
        assert geom_col in columns, f"{key}: {schema}.{table} n'a pas de colonne {geom_col}"
        assert columns[geom_col].startswith("public.geometry"), f"{key}: {geom_col} n'est pas une geometrie"
    else:
        geometries = [c for c, t in columns.items() if t.startswith("public.geometry")]
        assert not geometries, f"{key}: {schema}.{table} a une geometrie {geometries} declaree absente du catalogue"
    if pk is not None:
        assert pk in columns, f"{key}: {schema}.{table} n'a pas de colonne cle primaire {pk}"


def test_relations_on_non_operator_children_use_existing_columns():
    by_key = {e[0]: e for e in _module_literal("LAYER_CATALOG")}
    checked = 0
    for _parent, child, fk, name in _module_literal("RELATION_DEFS"):
        entry = by_key[child]
        if entry not in ENTRIES:
            continue
        checked += 1
        assert fk in SNAPSHOT_RELATIONS[(entry[2], entry[3])], f"{name}: {entry[2]}.{entry[3]} n'a pas {fk}"
    assert checked >= 3          # permis_voirie, interventions_chantier, docs_elements


# --- comportement du chargement (doublures fakes19, aucun QGIS) ---------------------------------


def test_chantier_layers_load_from_the_renamed_tables_and_interventions_without_geometry(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    keys = {"interventions", "plaintes", "interventions_chantier", "planning_facades"}
    assert pi.init_project({}, "", keys, operator=WYRE) == 4
    geometry = {l.name(): l.dataProvider().uri().geometryColumn() for l in project.mapLayers().values()}
    assert set(geometry) == {"interventions", "complaints", "worksite_interventions", "facade_planning"}
    # Table attributaire : aucune colonne de geometrie dans la source ; les autres gardent geom.
    assert not geometry["interventions"]
    assert all(geometry[t] == "geom" for t in ("complaints", "worksite_interventions", "facade_planning"))
    assert all(l.isValid() for l in project.mapLayers().values())
    # Deja chargees : reconnues, rien n'est recharge.
    assert pi._detect_existing_layers(None) >= keys
    assert pi.init_project({}, "", keys, operator=WYRE) == 0
    assert len(project.mapLayers()) == 4


def test_project_saved_with_the_old_table_names_opens_without_crash(pi, monkeypatch):
    """Un projet 2.0.2 n'avait jamais pu charger ces couches : mais un projet
    peut en contenir des restes (anciens noms) ; l'ouverture et le chargement
    ne plantent pas et ne confondent pas ces restes avec les nouvelles couches."""
    project = install_fake_project(pi, monkeypatch)
    for table in ("plaintes", "interventions_chantier", "planning_facades"):
        project.add_pg("chantier", table)
    assert pi._detect_existing_layers(None) == set()
    assert pi.init_project({}, "", {"plaintes", "planning_facades"}, operator=WYRE) == 2
    assert pi.count_loaded_layers(project).common >= 2


def test_renamed_tables_keep_their_accented_layer_labels():
    from constructel_bridge.i18n.layer_translations import LAYER_TREE_LABELS

    assert LAYER_TREE_LABELS["plaintes"] == {"fr": "Plaintes", "en": "Complaints", "pt": "Reclamações"}
    assert LAYER_TREE_LABELS["interventions_chantier"] == {
        "fr": "Interventions chantier", "en": "Worksite interventions", "pt": "Intervenções de obra"}
    assert LAYER_TREE_LABELS["planning_facades"] == {
        "fr": "Planning façades", "en": "Facade planning", "pt": "Planeamento de fachadas"}
