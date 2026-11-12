"""Bridge 1.9, tache 2 (spec § 6.3, § 6.4, § 7 ; plan D1-D5, D17) :
catalogue par schema, groupes operateur et « Commun », identite du projet,
relations par operateur. Doublures T/fakes19.py, aucun QGIS ni aucune base."""
from __future__ import annotations

import pytest

from constructel_bridge import bridge_operators as bo
from constructel_bridge_tests.fakes19 import ORANGE, WYRE, FakeLayer, FakeRasterLayer, install_fake_project
from constructel_bridge_tests.test_bridge18_connect import _FakeCursor, _make_plugin, _PgErr
from constructel_bridge_tests.test_bridge18_layers import (  # noqa: F401  (pi = fixture)
    _FakeIface,
    _shared_plugin,
    pi,
)


def _names(group):
    return [c.name() for c in group.children()]


# --- module pur : catalogue, cles, identite -------------------------------------------


def test_catalog_for_substitutes_operator_schema_only(pi):
    cat = pi.catalog_for("orange")
    assert [e[0] for e in cat] == [e[0] for e in pi.LAYER_CATALOG]
    by_key = {e[0]: e for e in cat}
    assert by_key["cables"][2] == "orange" and by_key["duct_progress"][2:4] == ("orange", "v_duct_progress")
    assert by_key["interventions"][2] == "chantier" and by_key["v_form_lists"][2] == "ref"
    assert by_key["wfs_parcels"][2] == "wfs" and by_key["docs_elements"][2] == "docs"
    # D1 : LAYER_CATALOG garde le schema modele.
    assert pi.catalog_for("wyre") == pi.LAYER_CATALOG
    assert {e[2] for e in pi.LAYER_CATALOG if e[1] in bo.OPERATOR_GROUPS} == {"wyre"}


@pytest.mark.parametrize("schema", ["", "Orange", 'x"; drop', None])
def test_catalog_for_rejects_unsafe_schema(pi, schema):
    with pytest.raises(ValueError):
        pi.catalog_for(schema)


def test_operator_constants_match_catalog(pi):
    op = [e for e in pi.LAYER_CATALOG if e[1] in bo.OPERATOR_GROUPS]
    assert {e[0] for e in op} == bo.OPERATOR_KEYS and {e[3] for e in op} == bo.OPERATOR_TABLES
    assert len(bo.OPERATOR_KEYS) == len(bo.OPERATOR_TABLES) == 11
    assert {e[1] for e in pi.LAYER_CATALOG} - set(bo.OPERATOR_GROUPS) - {"Référence"} == set(bo.COMMON_GROUPS)


def test_every_relation_has_an_operator_end(pi):
    # ensure_relations construit chaque relation par operateur : une relation
    # entre deux couches communes serait creee en double.
    assert all(p in bo.OPERATOR_KEYS or c in bo.OPERATOR_KEYS for p, c, _fk, _n in pi.RELATION_DEFS)


def test_layer_keys_and_relation_ids():
    assert bo.layer_key("cables", "orange") == "cables@orange"
    assert bo.layer_key("cables", "wyre") == "cables@wyre"
    assert bo.layer_key("interventions", "orange") == "interventions"
    assert bo.base_key("cables@orange") == "cables" and bo.base_key("interventions") == "interventions"
    assert bo.relation_id("zone_pop_to_mro", "wyre", "wyre") == "zone_pop_to_mro"
    assert bo.relation_id("zone_pop_to_mro", "orange", "wyre") == "zone_pop_to_mro__orange"


def test_project_identity_helpers():
    assert bo.parse_project_operators("wyre") == ["wyre"]
    assert bo.parse_project_operators(" wyre, orange ,wyre") == ["wyre", "orange"]
    assert bo.parse_project_operators("") == []
    assert bo.parse_project_operators(None) == []
    assert bo.parse_project_operators('wyre,x"; drop') == ["wyre"]
    assert bo.format_project_operators(["wyre", "orange", "wyre"]) == "wyre,orange"
    assert bo.parse_operator_labels(bo.format_operator_labels({"wyre": "Wyre"})) == {"wyre": "Wyre"}
    assert bo.parse_operator_labels("not json") == {} == bo.parse_operator_labels("")
    assert bo.parse_operator_labels('["wyre"]') == {} == bo.parse_operator_labels('{"wyre": 3}')


def test_canonical_group_reads_every_language(pi):
    from constructel_bridge.i18n.layer_translations import GROUP_NAMES

    assert GROUP_NAMES["Commun"] == {"fr": "Commun", "en": "Common", "pt": "Comum"}
    assert bo.canonical_group("Points de demande", GROUP_NAMES) == "Demand Points"
    assert bo.canonical_group("Infraestrutura", GROUP_NAMES) == "Infrastructure"
    assert bo.canonical_group("Comum", GROUP_NAMES) == "Commun"
    assert bo.canonical_group("Zones", GROUP_NAMES) == "Zones"
    assert bo.canonical_group("Mes couches", GROUP_NAMES) is None


# --- detection « deja chargee » par operateur -------------------------------------------


def test_detect_existing_layers_is_per_operator(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    project.add_pg("wyre", "cables"); project.add_pg("chantier", "interventions")
    assert pi._detect_existing_layers("orange") == {"interventions"}
    assert {"cables", "interventions"} <= pi._detect_existing_layers("wyre")
    assert "cables" in pi._detect_existing_layers()  # defaut : schema modele


# --- arbre de couches ------------------------------------------------------------------


def test_two_operators_one_common_tree(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    sel = {"cables", "zone_pop", "interventions", "v_form_lists"}
    pi.init_project({}, "", sel, selected_basemaps={"osm"}, operator=WYRE)
    pi.init_project({}, "", sel, selected_basemaps={"osm"}, operator=ORANGE)
    root = project.layerTreeRoot()
    assert [c.name() for c in root.children()] == ["Wyre", "Orange", "Commun", "Basemaps", "Référence"]
    assert [c.name() for c in root.children()[1].children()] == ["Infrastructure", "Zones"]
    assert [c.name() for c in root.children()[2].children()] == ["Chantier"]
    assert project.count_pg("chantier", "interventions") == 1
    assert project.count_pg("wyre", "cables") == project.count_pg("orange", "cables") == 1
    assert [l.name() for l in project.mapLayers().values()].count("OpenStreetMap") == 1
    # Proprietes posees (D17) : schema sur le groupe racine, nom canonique ailleurs.
    wyre, orange, commun = root.children()[:3]
    assert (wyre.customProperty(bo.GROUP_SCHEMA_PROPERTY), orange.customProperty(bo.GROUP_SCHEMA_PROPERTY)) == (
        "wyre", "orange")
    assert commun.customProperty(bo.GROUP_KIND_PROPERTY) == "Commun"
    assert orange.children()[0].customProperty(bo.GROUP_KIND_PROPERTY) == "Infrastructure"
    infra_orange = orange.children()[0]
    assert infra_orange.findLayer(project.layer("orange", "cables").id()) is not None
    assert infra_orange.findLayer(project.layer("wyre", "cables").id()) is None


def test_operator_and_common_groups_go_before_technical_groups(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    for name in ("Basemaps", "Référence", "Mes couches"):
        root.addGroup(name)
    pi.init_project({}, "", {"cables", "interventions"}, operator=WYRE)
    assert _names(root) == ["Wyre", "Commun", "Basemaps", "Référence", "Mes couches"]


def test_basemaps_created_late_stay_above_reference(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    pi.init_project({}, "", {"cables", "v_form_lists"}, operator=WYRE)
    pi.init_project({}, "", {"cables"}, selected_basemaps={"osm"}, operator=ORANGE)
    assert _names(project.layerTreeRoot()) == ["Wyre", "Orange", "Basemaps", "Référence"]


def test_invalid_basemap_creates_no_group(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)

    class _InvalidRaster(FakeRasterLayer):
        def isValid(self):
            return False

    monkeypatch.setattr(pi, "QgsRasterLayer", _InvalidRaster)
    pi.init_project({}, "", {"cables"}, selected_basemaps={"osm"}, operator=WYRE)
    assert _names(project.layerTreeRoot()) == ["Wyre"]


def test_basemap_present_elsewhere_creates_no_empty_group(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    mine = project.layerTreeRoot().addGroup("Mes couches")
    osm = FakeRasterLayer("type=xyz", "OpenStreetMap", "wms")
    project.addMapLayer(osm, False)
    mine.addLayer(osm)
    pi.init_project({}, "", {"cables"}, selected_basemaps={"osm"}, operator=WYRE)
    assert _names(project.layerTreeRoot()) == ["Mes couches", "Wyre"]
    assert [ly.name() for ly in project.mapLayers().values()].count("OpenStreetMap") == 1


def test_add_mode_after_translation_reuses_subgroups(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    pi.init_project({}, "", {"demand_points"}, operator=WYRE)
    wyre = project.layerTreeRoot().children()[0]
    wyre.children()[0].setName("Points de demande")
    pi.init_project({}, "", {"demand_points", "cables"}, operator=WYRE)
    assert [c.name() for c in wyre.children()] == ["Points de demande", "Infrastructure"]


def test_translated_common_root_and_unmarked_subgroup_are_reused(pi, monkeypatch):
    # Projet traduit en PT (Comum), sous-groupe sans propriete (nom traduit) :
    # aucun doublon, et jamais un homonyme plus bas dans l'arbre (findGroup).
    project = install_fake_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    pi.init_project({}, "", {"interventions"}, operator=WYRE)
    root.children()[0].setName("Comum")
    root.children()[0].removeCustomProperty(bo.GROUP_KIND_PROPERTY)
    decoy = root.addGroup("Mes couches").addGroup("Infrastructure")
    wyre = pi.ensure_operator_group(root, WYRE)
    wyre.addGroup("Infraestrutura")
    pi.init_project({}, "", {"incidents", "cables"}, operator=WYRE)
    assert _names(root) == ["Wyre", "Comum", "Mes couches"]
    assert _names(root.children()[1]) == ["Chantier"]
    assert _names(wyre) == ["Infraestrutura"] and decoy.children() == []


def test_no_group_created_for_layers_already_loaded(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    mine = root.addGroup("Mes couches")
    project.add_pg("chantier", "interventions", group=mine)
    assert pi.init_project({}, "", {"interventions"}, operator=ORANGE) == 0
    assert _names(root) == ["Mes couches"]


def test_invalid_layer_creates_no_group(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)

    class _Invalid(FakeLayer):
        def isValid(self):
            return False

    monkeypatch.setattr(pi, "QgsVectorLayer", _Invalid)
    assert pi.init_project({}, "", {"cables", "interventions", "v_form_lists"}, operator=WYRE) == 0
    assert project.layerTreeRoot().children() == [] and project.mapLayers() == {}


def test_find_child_group_never_takes_another_bridge_group(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    zones = root.addGroup("Infrastructure")      # renomme par la personne
    zones.setCustomProperty(bo.GROUP_KIND_PROPERTY, "Zones")
    operator = root.addGroup("Zones")            # libelle d'un operateur
    operator.setCustomProperty(bo.GROUP_SCHEMA_PROPERTY, "zones")
    assert pi.find_child_group(root, "Zones") is zones
    assert pi.find_child_group(root, "Infrastructure") is None


# --- identite du projet -----------------------------------------------------------------


def test_stamp_accumulates_operators_before_first_layer(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    # Identite lue au moment de chaque addMapLayer (le renommage de la tache 3
    # se fait sur layersAdded et lit cette identite).
    seen = []
    add_map_layer = project.addMapLayer

    def spy(layer, add_to_legend=True):
        uri = layer.dataProvider().uri()
        seen.append((uri.schema(), uri.table(), pi.get_bridge_info()["operators"]))
        return add_map_layer(layer, add_to_legend)

    monkeypatch.setattr(project, "addMapLayer", spy)
    pi.init_project({}, "", {"cables"}, operator=WYRE)
    info = pi.get_bridge_info()
    assert info["operators"] == ["wyre"] and info["operator_labels"] == {"wyre": "Wyre"}
    pi.init_project({}, "", {"cables"}, operator=ORANGE)
    info = pi.get_bridge_info()
    assert info["operators"] == ["wyre", "orange"] and info["operator"] == "wyre,orange"
    assert info["operator_labels"] == {"wyre": "Wyre", "orange": "Orange"}
    first_add = next(i for i, e in enumerate(project.events) if e[0] == "add")
    assert ("entry", "operator_labels") in project.events[:first_add]
    assert seen == [("wyre", "cables", ["wyre"]), ("orange", "cables", ["wyre", "orange"])]
    # @bridge_operator : meme chaine que bridge/operator.
    assert project.customVariables()["bridge_operator"] == "wyre,orange"
    assert project.customVariables()["bridge_version"] == pi.WYRE_PROJECT_VERSION


def test_common_only_load_leaves_identity_unchanged(pi, monkeypatch):
    # Decision T2-c3 : un operateur n'entre dans l'identite que si une de ses
    # couches operateur est reellement ajoutee ; version et plugin toujours.
    project = install_fake_project(pi, monkeypatch)
    pi.init_project({}, "", {"interventions", "v_form_lists"}, operator=ORANGE, suffix=True)
    info = pi.get_bridge_info()
    assert (info["operators"], info["operator_labels"], info["operator_suffix"]) == ([], {}, None)
    assert info["version"] == pi.WYRE_PROJECT_VERSION and pi.is_bridge_project()
    pi.init_project({}, "", {"cables"}, operator=WYRE)
    pi.init_project({}, "", {"incidents"}, operator=ORANGE)
    assert pi.get_bridge_info()["operators"] == ["wyre"]
    assert project.customVariables()["bridge_operator"] == "wyre"
    assert _names(project.layerTreeRoot()) == ["Wyre", "Commun", "Référence"]


def test_operator_with_only_invalid_layers_stays_out_of_identity(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    pi.init_project({}, "", {"cables"}, operator=WYRE)

    class _InvalidOrange(FakeLayer):
        def isValid(self):
            return '"orange"' not in self.source()

    monkeypatch.setattr(pi, "QgsVectorLayer", _InvalidOrange)
    pi.init_project({}, "", {"cables", "zone_pop", "interventions"}, operator=ORANGE)
    info = pi.get_bridge_info()
    assert info["operators"] == ["wyre"] and info["operator_labels"] == {"wyre": "Wyre"}
    assert project.count_pg("chantier", "interventions") == 1
    assert "Orange" not in _names(project.layerTreeRoot())


def test_operator_loaded_after_common_only_load_is_primary(pi, monkeypatch):
    # Orange preselectionne, couches communes seules ; puis Wyre : Wyre est le
    # principal et garde les identifiants historiques des relations.
    project = install_fake_project(pi, monkeypatch)
    pi.init_project({}, "", {"interventions"}, operator=ORANGE)
    pi.init_project({}, "", {"cables", "zone_pop"}, operator=WYRE)
    rels = project.relationManager().relations()
    assert pi.get_bridge_info()["operators"] == ["wyre"]
    assert "cables_to_pop" in rels and not any(i.endswith("__wyre") for i in rels)
    assert rels["cables_to_pop"].referencingLayerId() == project.layer("wyre", "cables").id()


def test_operator_suffix_entry_is_none_until_chosen(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    pi.stamp_project(WYRE)
    assert pi.get_bridge_info()["operator_suffix"] is None
    assert project.readEntry("bridge", "operator_suffix", "") == ("", False)
    pi.stamp_project(WYRE, suffix=False)
    assert pi.get_bridge_info()["operator_suffix"] is False
    pi.stamp_project(ORANGE)                       # None : choix existant garde
    assert pi.get_bridge_info()["operator_suffix"] is False
    pi.stamp_project(ORANGE, suffix=True)
    assert pi.get_bridge_info()["operator_suffix"] is True
    assert project.readEntry("bridge", "operator_suffix", "") == ("1", True)
    assert pi.get_bridge_info()["operators"] == ["wyre", "orange"]


def test_legacy_identity_still_read(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    project.writeEntry("bridge", "operator", "wyre")
    info = pi.get_bridge_info()
    assert info["operators"] == ["wyre"] and pi.is_bridge_project()
    assert info["operator_labels"] == {} and info["operator_suffix"] is None


def test_identity_read_from_project_variables_only(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    project.setCustomVariables({"bridge_operator": "wyre,orange"})
    assert pi.get_bridge_info()["operators"] == ["wyre", "orange"] and pi.is_bridge_project()


# --- relations par operateur ------------------------------------------------------------


def test_relations_are_built_per_operator(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    for op in (WYRE, ORANGE):
        pi.init_project({}, "", {"cables", "zone_pop", "zone_mro"}, operator=op)
    rels = project.relationManager().relations()
    assert rels["zone_pop_to_mro"].referencedLayerId() == project.layer("wyre", "zone_mro").id()
    assert rels["zone_pop_to_mro__orange"].referencedLayerId() == project.layer("orange", "zone_mro").id()
    assert rels["cables_to_pop__orange"].referencingLayerId() == project.layer("orange", "cables").id()
    assert rels["cables_to_pop"].referencingLayerId() == project.layer("wyre", "cables").id()


def _operator_end_schemas(project, rel):
    return {project.schema_of(i) for i in (rel.referencingLayerId(), rel.referencedLayerId())} - {"docs"}


def test_relation_discovery_pairs_same_operator(pi, monkeypatch):
    # Projet rouvert : couches orange AVANT les couches wyre (une recherche par
    # table seule apparierait les mauvaises), Documents commun aux deux.
    project = install_fake_project(pi, monkeypatch)
    project.writeEntry("bridge", "operator", "wyre,orange")
    tables = ("zone_mro", "zone_pop", "cables", "structures")
    for schema in ("orange", "wyre"):
        for table in tables:
            project.add_pg(schema, table)
    docs = project.add_pg("docs", "v_element_documents_list", geom=None, key="link_id")

    count = pi.ensure_relations()

    rels = project.relationManager().relations()
    assert count == len(rels) and rels
    for rel_id, rel in rels.items():
        expected = rel_id.split("__")[1] if "__" in rel_id else "wyre"
        assert _operator_end_schemas(project, rel) == {expected}, rel_id
    assert {i.split("__")[0] for i in rels if i.endswith("__orange")} == {i for i in rels if "__" not in i}
    assert rels["cables_to_pop__orange"].referencedLayerId() == project.layer("orange", "zone_pop").id()
    assert rels["cables_to_pop"].referencedLayerId() == project.layer("wyre", "zone_pop").id()
    assert rels["docs_element_cable__orange"].referencingLayerId() == docs.id()
    assert rels["docs_element_cable__orange"].referencedLayerId() == project.layer("orange", "cables").id()


def test_relation_primary_schema_follows_identity(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    project.writeEntry("bridge", "operator", "orange,wyre")
    for schema in ("wyre", "orange"):
        project.add_pg(schema, "zone_mro"); project.add_pg(schema, "zone_pop")
    pi.ensure_relations()
    rels = project.relationManager().relations()
    assert rels["zone_pop_to_mro"].referencedLayerId() == project.layer("orange", "zone_mro").id()
    assert rels["zone_pop_to_mro__wyre"].referencedLayerId() == project.layer("wyre", "zone_mro").id()
    pi.ensure_relations(primary_schema="wyre")
    rels = project.relationManager().relations()
    assert rels["zone_pop_to_mro"].referencedLayerId() == project.layer("wyre", "zone_mro").id()


# --- cote plugin -----------------------------------------------------------------------


def test_load_operator_layers_passes_operator_and_remembers_it(bp18, pi, monkeypatch, tmp_path):
    from qgis.core import QgsSettings

    calls = []
    monkeypatch.setattr(pi, "init_project", lambda *args, **kwargs: calls.append(kwargs) or 3)
    monkeypatch.setattr(bp18.bridge_sketcher, "apply_all_translations", lambda *a, **k: None)
    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)

    assert plugin._load_operator_layers(ORANGE, {"cables"}, set(), True) == 3

    assert calls[0]["operator"] == ORANGE and calls[0]["suffix"] is None
    assert calls[0]["add_basemap"] is False and calls[0]["apply_styles"] is True
    assert QgsSettings().value(bo.LAST_OPERATOR_KEY) == "orange"
    assert plugin.iface.messageBar().messages[-1][2] == bp18.tr("init.success", count=3)


def test_load_operator_layers_never_raises(bp18, pi, monkeypatch, tmp_path):
    from qgis.core import QgsSettings

    errors = []

    def boom(*_args, **_kwargs):
        raise RuntimeError("permission denied for schema orange")

    monkeypatch.setattr(pi, "init_project", boom)
    monkeypatch.setattr(bp18.QMessageBox, "critical", staticmethod(lambda *a, **k: errors.append(a[2])))
    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)

    assert plugin._load_operator_layers(ORANGE, {"cables"}, {"osm"}, True, suffix=True) == 0

    assert errors == [bp18.tr("init.error", error="permission denied for schema orange")]
    assert QgsSettings().value(bo.LAST_OPERATOR_KEY) is None


def test_init_menu_without_usable_operator_warns(bp18, monkeypatch):
    warnings = []
    monkeypatch.setattr(bp18.QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a[2])))
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._connected, plugin._operators = True, []
    plugin._on_init_project()
    assert warnings == [bp18.tr("home.no_operator")]


def _fake_init_dialog(bp18, pi, monkeypatch):
    """InitProjectDialog factice : accepte, couches cables + v_form_lists,
    fond osm, sans styles. Rend la liste des operateurs recus."""
    opened = []

    class _Dialog:
        def __init__(self, parent=None, operator=None):
            opened.append(operator)

        def exec(self):
            return bp18.QDialog.DialogCode.Accepted

        def selected_layers(self):
            return {"cables", "v_form_lists"}

        def want_basemap(self):
            return True

        def selected_basemaps(self):
            return {"osm"}

        def want_styles(self):
            return False

    monkeypatch.setattr(pi, "InitProjectDialog", _Dialog)
    return opened


def test_init_menu_loads_preselected_operator(bp18, pi, monkeypatch):
    from qgis.core import QgsSettings

    loads = []
    opened = _fake_init_dialog(bp18, pi, monkeypatch)
    QgsSettings().setValue(bo.LAST_OPERATOR_KEY, "wyre")
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._connected, plugin._operators = True, [ORANGE, WYRE]
    monkeypatch.setattr(plugin, "_load_operator_layers", lambda *a, **k: loads.append(a) or 1)

    plugin._on_init_project()

    assert opened == [WYRE]
    assert loads == [(WYRE, {"cables", "v_form_lists"}, {"osm"}, False)]


def test_unreadable_operator_list_falls_back_to_wyre(bp18, pi, monkeypatch, tmp_path):
    # Decision T2-c4 : liste illisible (echec d'OPERATORS_QUERY) -> chargement
    # Wyre, comme 1.8.4.
    cur = _FakeCursor(operator_rows=_PgErr("permission denied for table operateurs"))
    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert plugin._connected is True and plugin._operators == [] and plugin._operators_unavailable is True
    loads = []
    opened = _fake_init_dialog(bp18, pi, monkeypatch)
    monkeypatch.setattr(plugin, "_load_operator_layers", lambda *a, **k: loads.append(a) or 1)

    plugin._on_init_project()

    assert opened == [bo.OperatorInfo("WYRE", "Wyre", "wyre")] == [bo.FALLBACK_OPERATOR]
    assert [call[0] for call in loads] == [bo.FALLBACK_OPERATOR]


def test_readable_list_without_usable_operator_blocks_loading(bp18, pi, monkeypatch, tmp_path):
    # Liste lue, aucun operateur utilisable : blocage home.no_operator (spec § 6.2).
    cur = _FakeCursor(operator_rows=[("ORANGE", "Orange", "orange", True)], operator_codes=["WYRE"])
    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert plugin._connected is True and plugin._operators == [] and plugin._operators_unavailable is False
    warnings = []
    monkeypatch.setattr(bp18.QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a[2])))
    opened = _fake_init_dialog(bp18, pi, monkeypatch)

    plugin._on_init_project()

    assert warnings == [bp18.tr("home.no_operator")] and opened == []
