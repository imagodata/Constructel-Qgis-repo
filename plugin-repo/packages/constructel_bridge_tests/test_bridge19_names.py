"""Bridge 1.9, tache 3 (spec § 6.4, § 9.5 ; plan D6) : suffixe de l'operateur
sur les noms de couches et groupes imbriques traduits. Doublures
T/fakes19.py, aucun QGIS ni aucune base.

Regle du suffixe : un seul operateur dans le projet -> facultatif (case
decochee par defaut) ; au moins deux -> obligatoire. Il s'applique apres la
traduction du nom, suit la langue courante et ne touche jamais une couche
commune. Le nom est toujours recalcule depuis LAYER_DISPLAY_NAMES : jamais
« Cables · Wyre · Wyre »."""
from __future__ import annotations

import importlib
import sys

import pytest

from constructel_bridge import bridge_operators as bo
from constructel_bridge_tests.fakes19 import FakeEditorWidgetSetup, FakeGroup, FakeLayer, FakeUri, install_fake_project
from constructel_bridge_tests.test_bridge1b_wiring import qgis_stub_path  # noqa: F401

LABELS_TWO = {"wyre": "Wyre", "orange": "Orange"}


@pytest.fixture
def sk(qgis_stub_path, monkeypatch):  # noqa: F811
    """bridge_sketcher sous le stub qgis, branche sur un FakeProject."""
    for name in list(sys.modules):
        if name.startswith(("qgis", "constructel_bridge.bridge_sketcher", "constructel_bridge.i18n")):
            monkeypatch.delitem(sys.modules, name)
    module = importlib.import_module("constructel_bridge.bridge_sketcher")
    monkeypatch.setattr(module, "QgsDataSourceUri", FakeUri)
    monkeypatch.setattr(module, "QgsEditorWidgetSetup", FakeEditorWidgetSetup)
    install_fake_project(module, monkeypatch)
    # apply_label_expressions importe ces classes a l'appel ; le stub ne les a pas.
    core = sys.modules["qgis.core"]
    for name in ("QgsPalLayerSettings", "QgsVectorLayerSimpleLabeling"):
        monkeypatch.setattr(core, name, type(name, (), {}), raising=False)
    return module


@pytest.fixture
def project(sk):
    return sk.QgsProject.instance()


def stamp(project, schemas, labels, suffix=None):
    """Identite 1.9 du projet : bridge/operator, operator_labels et, quand
    *suffix* est donne ("0" / "1"), operator_suffix."""
    project.writeEntry("bridge", "operator", ",".join(schemas))
    project.writeEntry("bridge", "operator_labels", bo.format_operator_labels(labels))
    if suffix is not None:
        project.writeEntry("bridge", "operator_suffix", suffix)


def names(project):
    """Noms des groupes de l'arbre, en profondeur d'abord."""
    out = []

    def walk(group):
        for child in group.children():
            if isinstance(child, FakeGroup):
                out.append(child.name())
                walk(child)

    walk(project.layerTreeRoot())
    return out


# --- module pur ---------------------------------------------------------------------


def test_name_helpers():
    assert bo.operator_layer_name("Cables", "Wyre") == "Cables · Wyre"
    assert bo.split_operator_suffix("Zones POP · Orange") == ("Zones POP", "Orange")
    assert bo.split_operator_suffix("Zones POP") == ("Zones POP", None)
    assert bo.suffix_applies(["wyre"], False) is False
    assert bo.suffix_applies(["wyre"], True) is True
    assert bo.suffix_applies(["wyre", "orange"], False) is True


def test_split_cuts_at_the_last_separator_only():
    assert bo.split_operator_suffix("A · B · Wyre") == ("A · B", "Wyre")
    assert bo.split_operator_suffix("Cables ·Wyre") == ("Cables ·Wyre", None)


def test_suffix_applies_edge_cases():
    # 0 operateur (chargement de couches communes seules) : pas de suffixe
    # sauf si l'option est cochee ; les doublons ne comptent pas pour deux.
    assert bo.suffix_applies([], False) is False
    assert bo.suffix_applies([], True) is True
    assert bo.suffix_applies(["wyre", "wyre"], False) is False
    assert bo.suffix_applies(iter(["wyre", "orange"]), False) is True


@pytest.mark.parametrize("raw, expected", [
    ("1", True), ("true", True), (" TRUE ", True), ("0", False), ("false", False),
    ("", False), ("n'importe quoi", False), (None, False),
])
def test_parse_suffix_flag(raw, expected):
    assert bo.parse_suffix_flag(raw) is expected


# --- noms de couches ----------------------------------------------------------------


def test_single_operator_without_opt_in_keeps_plain_names(sk, project):
    stamp(project, ["wyre"], {"wyre": "Wyre"}, suffix="0")
    cables = project.add_pg("wyre", "cables")
    sk.apply_layer_name(cables, "fr")
    assert cables.name() == "Cables"


def test_single_operator_opt_in_adds_suffix(sk, project):
    stamp(project, ["wyre"], {"wyre": "Wyre"}, suffix="1")
    cables = project.add_pg("wyre", "cables")
    sk.apply_layer_name(cables, "fr")
    assert cables.name() == "Cables · Wyre"


def test_missing_suffix_entry_counts_as_not_opted_in(sk, project):
    stamp(project, ["wyre"], {"wyre": "Wyre"})
    cables = project.add_pg("wyre", "cables")
    sk.apply_layer_name(cables, "fr")
    assert cables.name() == "Cables"


def test_second_operator_forces_suffix_on_both(sk, project):
    stamp(project, ["wyre", "orange"], LABELS_TWO, suffix="0")
    cables_wyre = project.add_pg("wyre", "cables")
    cables_orange = project.add_pg("orange", "cables")
    sk.apply_layer_name(cables_wyre, "en")
    sk.apply_layer_name(cables_orange, "en")
    assert (cables_wyre.name(), cables_orange.name()) == ("Cables · Wyre", "Cables · Orange")


def test_suffix_is_never_doubled(sk, project):
    stamp(project, ["wyre", "orange"], LABELS_TWO, suffix="1")
    cables = project.add_pg("wyre", "cables")
    seen = []
    for lang in ("fr", "fr", "pt"):
        sk.apply_layer_name(cables, lang)
        seen.append(cables.name())
    assert seen == ["Cables · Wyre", "Cables · Wyre", "Cabos · Wyre"]
    # Un second « Ajouter » rejoue le passage sur une couche deja suffixee.
    sk.apply_layer_name(cables, "pt")
    assert cables.name() == "Cabos · Wyre"
    assert cables.name().count(bo.SUFFIX_SEP) == 1


def test_apply_layer_name_reports_whether_it_renamed(sk, project):
    stamp(project, ["wyre", "orange"], LABELS_TWO, suffix="1")
    cables = project.add_pg("wyre", "cables")
    assert sk.apply_layer_name(cables, "fr") is True
    assert sk.apply_layer_name(cables, "fr") is False


def test_unchecking_suffix_removes_it_at_next_pass(sk, project):
    stamp(project, ["wyre"], {"wyre": "Wyre"}, suffix="1")
    cables = project.add_pg("wyre", "cables")
    sk.apply_layer_name(cables, "fr")
    assert cables.name() == "Cables · Wyre"
    project.writeEntry("bridge", "operator_suffix", "0")
    sk.apply_layer_name(cables, "fr")
    assert cables.name() == "Cables"


def test_legacy_project_is_never_suffixed(sk, project):
    project.writeEntry("bridge", "operator", "wyre")  # 1.8 : pas d'operator_labels
    project.writeEntry("bridge", "operator_suffix", "1")
    cables = project.add_pg("wyre", "cables")
    sk.apply_layer_name(cables, "fr")
    assert cables.name() == "Cables"


def test_schema_without_label_is_not_suffixed(sk, project):
    stamp(project, ["wyre", "orange"], {"wyre": "Wyre"}, suffix="1")
    cables = project.add_pg("orange", "cables")
    sk.apply_layer_name(cables, "fr")
    assert cables.name() == "Cables"


def test_common_layer_never_suffixed(sk, project):
    stamp(project, ["wyre", "orange"], LABELS_TWO, suffix="1")
    interventions = project.add_pg("chantier", "interventions", "Interventions")
    sk.apply_layer_name(interventions, "fr")
    assert interventions.name() == "Interventions"


def test_zero_operators_suffixes_only_when_opted_in(sk, project):
    # Chargement de couches communes seules : identite sans operateur.
    stamp(project, [], {}, suffix="0")
    assert sk.project_operator_naming(project) == ({}, False)
    stamp(project, [], {}, suffix="1")
    labels, active = sk.project_operator_naming(project)
    assert labels == {} and active is True
    cables = project.add_pg("wyre", "cables")
    sk.apply_layer_name(cables, "fr")
    assert cables.name() == "Cables"  # pas de libelle : rien a suffixer


def test_project_operator_naming_reads_the_identity(sk, project):
    assert sk.project_operator_naming(project) == ({}, False)
    stamp(project, ["wyre", "orange"], LABELS_TWO)
    assert sk.project_operator_naming(project) == (LABELS_TWO, True)
    stamp(project, ["wyre"], {"wyre": "Wyre"}, suffix="1")
    assert sk.project_operator_naming(project) == ({"wyre": "Wyre"}, True)


def test_offline_language_switch_keeps_suffix(sk, project):
    stamp(project, ["wyre", "orange"], LABELS_TWO, suffix="0")
    pop_wyre = project.add_pg("wyre", "zone_pop")
    pop_orange = project.add_pg("orange", "zone_pop")
    sk.apply_all_translations("fr")
    assert (pop_wyre.name(), pop_orange.name()) == ("Zones POP · Wyre", "Zones POP · Orange")
    sk.apply_all_translations("en")
    assert (pop_wyre.name(), pop_orange.name()) == ("POP Zones · Wyre", "POP Zones · Orange")
    sk.apply_all_translations("pt")
    assert (pop_wyre.name(), pop_orange.name()) == ("Zonas POP · Wyre", "Zonas POP · Orange")


def test_apply_to_layer_suffixes_a_layer_added_later(sk, project):
    stamp(project, ["wyre", "orange"], LABELS_TWO, suffix="0")
    cables = project.add_pg("orange", "cables")
    sk.apply_to_layer(cables, "fr")
    assert cables.name() == "Cables · Orange"


# --- groupes ---------------------------------------------------------------------------


def _group_tree(project):
    root = project.layerTreeRoot()
    wyre = root.addGroup("Wyre")
    wyre.setCustomProperty(bo.GROUP_SCHEMA_PROPERTY, "wyre")
    wyre.addGroup("Demand Points").setCustomProperty(bo.GROUP_KIND_PROPERTY, "Demand Points")
    commun = root.addGroup("Commun")
    commun.setCustomProperty(bo.GROUP_KIND_PROPERTY, "Commun")
    commun.addGroup("Chantier").setCustomProperty(bo.GROUP_KIND_PROPERTY, "Chantier")
    root.addGroup("Mes couches").addGroup("Zones")  # groupe personnel
    return root


def test_groups_translated_inside_operator_and_common(sk, project):
    _group_tree(project)
    sk.apply_group_names("fr")
    assert names(project) == ["Wyre", "Points de demande", "Commun", "Chantier", "Mes couches", "Zones"]
    sk.apply_group_names("pt")
    assert names(project) == ["Wyre", "Pontos de procura", "Comum", "Chantier", "Mes couches", "Zones"]
    sk.apply_group_names("en")
    assert names(project) == ["Wyre", "Demand Points", "Common", "Chantier", "Mes couches", "Zones"]


def test_operator_group_is_never_renamed(sk, project):
    # Un operateur dont le libelle serait aussi un nom de groupe connu.
    root = project.layerTreeRoot()
    group = root.addGroup("Zones")
    group.setCustomProperty(bo.GROUP_SCHEMA_PROPERTY, "zones")
    group.addGroup("Infrastructure").setCustomProperty(bo.GROUP_KIND_PROPERTY, "Infrastructure")
    sk.apply_group_names("pt")
    assert names(project) == ["Zones", "Infraestrutura"]


def test_group_kind_property_wins_over_the_current_name(sk, project):
    # Groupe renomme a la main puis marque : la propriete donne la traduction.
    root = project.layerTreeRoot()
    commun = root.addGroup("Nom libre")
    commun.setCustomProperty(bo.GROUP_KIND_PROPERTY, "Commun")
    sk.apply_group_names("pt")
    assert names(project) == ["Comum"]


def test_legacy_root_groups_still_translated_by_name(sk, project):
    # Projet 1.8 : groupes racine sans propriete, reconnus par leur nom.
    root = project.layerTreeRoot()
    root.addGroup("Demand Points")
    root.addGroup("Zonas")
    sk.apply_group_names("fr")
    assert names(project) == ["Points de demande", "Zones"]


def test_root_layer_node_is_never_renamed_as_a_group(sk, project):
    # Une couche personnelle a la racine, nommee comme un groupe connu, reste
    # intacte : seul un groupe est renomme.
    layer = FakeLayer("", "Zones", "memory")
    project.addMapLayer(layer)
    sk.apply_group_names("pt")
    assert layer.name() == "Zones"


# --- ValueRelation : nom suffixe perime --------------------------------------------------


def _vr_layer(project, schema, table, layer_name, vr_layer_name):
    layer = project.add_pg(schema, table, layer_name)
    layer._field_names = ["pop_id"]
    layer.setEditorWidgetSetup(0, FakeEditorWidgetSetup(
        "ValueRelation", {"LayerName": vr_layer_name, "Value": "code"}))
    return layer


def test_sync_recognizes_stale_suffixed_name(sk, project):
    stamp(project, ["wyre", "orange"], LABELS_TWO, suffix="0")
    project.add_pg("wyre", "zone_pop", "Zones POP · Wyre")
    chantier = _vr_layer(project, "chantier", "interventions", "Interventions", "POP Zones · Wyre")
    sk._sync_value_relation_layer_names(project)
    assert chantier.editorWidgetSetup(0).config()["LayerName"] == "Zones POP · Wyre"


def test_sync_still_recognizes_unsuffixed_stale_name(sk, project):
    project.add_pg("wyre", "zone_pop", "Zones POP")
    chantier = _vr_layer(project, "chantier", "interventions", "Interventions", "POP Zones")
    sk._sync_value_relation_layer_names(project)
    assert chantier.editorWidgetSetup(0).config()["LayerName"] == "Zones POP"
