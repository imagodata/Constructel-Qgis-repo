"""Bridge 1.9, tache 6 (spec § 6.5) : reorganisation des projets 1.8 au clic
« Ajouter des couches ». Un projet 1.8 a ses groupes a la racine (Demand
Points, Infrastructure, Zones, Chantier, OSIRIS...), parfois sous leur nom
FR ou PT ; ouvrir un tel projet ne le modifie jamais, ajouter des couches le
range par operateur (groupe au libelle de l'operateur, groupe « Commun »).
Doublures T/fakes19.py, aucun QGIS ni aucune base."""
from __future__ import annotations

import sys

import pytest

from constructel_bridge import bridge_operators as bo
from constructel_bridge_tests.fakes19 import (
    ORANGE,
    WYRE,
    FakeEditorWidgetSetup,
    FakeGroup,
    FakeLayer,
    FakeUri,
    install_fake_project,
)
from constructel_bridge_tests.test_bridge18_layers import _shared_plugin, pi  # noqa: F401  (pi = fixture)


def tree_names(project):
    """Arbre complet : groupes (nom, enfants) et couches (nom), en profondeur."""

    def walk(group):
        return [(c.name(), walk(c)) if isinstance(c, FakeGroup) else c.name() for c in group.children()]

    return walk(project.layerTreeRoot())


def tree_shape(project):
    """Arbre sans les noms de couches (identifiants a la place) : la
    structure, que la traduction des noms de couches ne change pas."""

    def walk(group):
        return [(c.name(), walk(c)) if isinstance(c, FakeGroup) else c.layerId() for c in group.children()]

    return walk(project.layerTreeRoot())


def _names(group):
    return [c.name() for c in group.children()]


def legacy_project(pi, monkeypatch, names=("Demand Points", "Infrastructure", "Zones", "Chantier"), schema="wyre"):
    """Projet 1.8 : quatre groupes racine (demande, infrastructure, zones,
    chantier) puis Basemaps, Reference et un groupe personnel, plus une
    couche personnelle a la racine. Rend (project, couches par table)."""
    project = install_fake_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    demand, infra, zones, chantier = (root.addGroup(name) for name in names)
    layers = {
        "demand_points": project.add_pg(schema, "demand_points", group=demand),
        "cables": project.add_pg(schema, "cables", group=infra),
        "zone_pop": project.add_pg(schema, "zone_pop", group=zones),
        "interventions": project.add_pg("chantier", "interventions", group=chantier),
    }
    root.addGroup("Basemaps")
    root.addGroup("Référence")
    mine = root.addGroup("Mes couches")
    layers["mine"] = project.add_pg("public", "mes_points", group=mine)
    layers["root_layer"] = project.add_pg("public", "ma_couche")  # directement a la racine
    return project, layers


# --- reorganisation (module projet) ------------------------------------------------------


def test_reorganizes_18_project_in_french(pi, monkeypatch):  # Review Focus 1
    project, layers = legacy_project(pi, monkeypatch, ("Points de demande", "Infrastructure", "Zones", "Chantier"))
    root = project.layerTreeRoot()

    assert pi.needs_reorganization(root) is True
    assert pi.reorganize_legacy_tree(project, {"wyre": WYRE}) == [WYRE]

    # Aucun groupe en double : chaque nom FR a ete reconnu, rien n'est reste a la racine.
    assert _names(root) == ["Wyre", "Commun", "Basemaps", "Référence", "Mes couches", "ma_couche"]
    assert _names(root.children()[0]) == ["Points de demande", "Infrastructure", "Zones"]
    assert _names(root.children()[1]) == ["Chantier"]
    for table in ("demand_points", "cables", "zone_pop", "interventions"):
        assert root.findLayer(layers[table].id()) is not None
    assert root.findLayer(layers["cables"].id()).parent() is root.children()[0].children()[1]
    assert root.findLayer(layers["interventions"].id()).parent() is root.children()[1].children()[0]
    assert len(root.findLayers()) == 6  # aucune couche perdue ni dupliquee
    # Proprietes Bridge posees : l'arbre est desormais celui d'un projet 1.9.
    wyre, commun = root.children()[:2]
    assert wyre.customProperty(bo.GROUP_SCHEMA_PROPERTY) == "wyre"
    assert commun.customProperty(bo.GROUP_KIND_PROPERTY) == "Commun"
    assert [c.customProperty(bo.GROUP_KIND_PROPERTY) for c in wyre.children()] == [
        "Demand Points", "Infrastructure", "Zones"]
    assert commun.children()[0].customProperty(bo.GROUP_KIND_PROPERTY) == "Chantier"


def test_reorganize_portuguese_names(pi, monkeypatch):  # Review Focus 1
    project, layers = legacy_project(pi, monkeypatch, ("Pontos de procura", "Infraestrutura", "Zonas", "Chantier"))
    root = project.layerTreeRoot()

    assert pi.reorganize_legacy_tree(project, {"wyre": WYRE}) == [WYRE]

    assert _names(root) == ["Wyre", "Commun", "Basemaps", "Référence", "Mes couches", "ma_couche"]
    assert _names(root.children()[0]) == ["Pontos de procura", "Infraestrutura", "Zonas"]
    assert [c.customProperty(bo.GROUP_KIND_PROPERTY) for c in root.children()[0].children()] == [
        "Demand Points", "Infrastructure", "Zones"]
    assert root.findLayer(layers["zone_pop"].id()).parent() is root.children()[0].children()[2]


def test_reorganize_english_names(pi, monkeypatch):
    project, _layers = legacy_project(pi, monkeypatch)
    assert pi.reorganize_legacy_tree(project, {"wyre": WYRE}) == [WYRE]
    root = project.layerTreeRoot()
    assert _names(root)[:2] == ["Wyre", "Commun"]
    assert _names(root.children()[0]) == ["Demand Points", "Infrastructure", "Zones"]


def test_reorganize_is_idempotent(pi, monkeypatch):  # Review Focus 2
    project, _layers = legacy_project(pi, monkeypatch, ("Points de demande", "Infrastructure", "Zones", "Chantier"))
    root = project.layerTreeRoot()
    assert pi.reorganize_legacy_tree(project, {"wyre": WYRE}) == [WYRE]
    before = tree_names(project)

    assert pi.reorganize_legacy_tree(project, {"wyre": WYRE}) == []
    assert tree_names(project) == before
    assert pi.needs_reorganization(root) is False
    # Ni « Wyre » dans « Wyre », ni second « Commun ».
    assert _names(root).count("Wyre") == 1 and _names(root).count("Commun") == 1
    assert "Wyre" not in _names(root.children()[0])
    # Un chargement 1.9 par-dessus reutilise les groupes existants (traduits).
    pi.init_project({}, "", {"cables", "interventions"}, operator=WYRE)
    assert _names(root).count("Wyre") == 1 and _names(root).count("Commun") == 1
    assert _names(root.children()[0]) == ["Points de demande", "Infrastructure", "Zones"]
    assert _names(root.children()[1]) == ["Chantier"]


def test_wyre_group_label_without_wyre_scope(pi, monkeypatch):
    # Utilisateur sans le scope Wyre (D7) : registre vide, groupe tout de meme
    # reconnu, au libelle « Wyre », non lisible.
    project, _layers = legacy_project(pi, monkeypatch)
    operators = pi.reorganize_legacy_tree(project, {})
    assert [o.label for o in operators] == ["Wyre"]
    assert operators == [bo.OperatorInfo("WYRE", "Wyre", "wyre", readable=False)]
    assert _names(project.layerTreeRoot())[0] == "Wyre"


def test_known_schema_without_registry_uses_stored_label_then_capitalized_schema(pi, monkeypatch):
    # Schema connu par l'identite du projet (bridge/operator) : operateur non
    # lisible, libelle mémorise dans bridge/operator_labels, a defaut schema capitalise.
    project, _layers = legacy_project(pi, monkeypatch, schema="orange")
    project.writeEntry("bridge", "operator", "orange")
    operators = pi.reorganize_legacy_tree(project, {})
    assert operators == [bo.OperatorInfo("ORANGE", "Orange", "orange", readable=False)]
    root = project.layerTreeRoot()
    assert root.children()[0].customProperty(bo.GROUP_SCHEMA_PROPERTY) == "orange"

    project, _layers = legacy_project(pi, monkeypatch, schema="orange")
    project.writeEntry("bridge", "operator_labels", bo.format_operator_labels({"orange": "Orange BE"}))
    assert [o.label for o in pi.reorganize_legacy_tree(project, {})] == ["Orange BE"]
    assert _names(project.layerTreeRoot())[0] == "Orange BE"


def test_schema_unknown_to_registry_and_identity_is_left_in_place(pi, monkeypatch):
    project, _layers = legacy_project(pi, monkeypatch, schema="orange")
    root = project.layerTreeRoot()
    before = tree_names(project)
    assert pi.reorganize_legacy_tree(project, {"wyre": WYRE}) == []
    # Les groupes operateur restent a la racine ; seul « Chantier » (commun) est range.
    assert _names(root) == ["Demand Points", "Infrastructure", "Zones", "Commun", "Basemaps", "Référence",
                            "Mes couches", "ma_couche"]
    assert tree_names(project) != before and pi.get_bridge_info()["operators"] == []


def test_registry_operator_is_returned_as_is(pi, monkeypatch):
    project, _layers = legacy_project(pi, monkeypatch, schema="orange")
    custom = bo.OperatorInfo("ORANGE", "Orange Belgium", "orange")
    assert pi.reorganize_legacy_tree(project, {"orange": custom, "wyre": WYRE}) == [custom]
    assert _names(project.layerTreeRoot())[0] == "Orange Belgium"


def test_empty_legacy_operator_group_is_left_in_place(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    root.addGroup("Zones")
    root.addGroup("Infrastructure")
    assert pi.needs_reorganization(root) is False
    assert pi.reorganize_legacy_tree(project, {"wyre": WYRE}) == []
    assert _names(root) == ["Zones", "Infrastructure"]
    assert root.children()[0].customProperty(bo.GROUP_SCHEMA_PROPERTY) is None
    assert pi.get_bridge_info()["operators"] == []


def test_legacy_operator_group_without_postgres_layer_is_left_in_place(pi, monkeypatch):
    # Couche non PostgreSQL (WFS) et couche non chargee (node.layer() None).
    project = install_fake_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    zones = root.addGroup("Zones")
    wfs = FakeLayer("typename=x", "wfs_zone", "WFS")
    project.addMapLayer(wfs, False)
    zones.addLayer(wfs)
    broken = FakeLayer.pg("wyre", "cables")
    infra = root.addGroup("Infrastructure")
    node = infra.addLayer(broken)
    node.layer = lambda: None  # couche non chargee : le noeud n'a plus de couche
    assert pi.needs_reorganization(root) is False
    assert pi.reorganize_legacy_tree(project, {"wyre": WYRE}) == []
    assert _names(root) == ["Zones", "Infrastructure"]


def test_legacy_group_with_only_non_operator_schema_creates_no_operator(pi, monkeypatch):
    # public.structures / chantier.cables : table operateur, mais schema qui
    # n'est ni dans le registre, ni dans l'identite, ni wyre -> pas d'operateur « Public ».
    project = install_fake_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    project.add_pg("public", "structures", group=root.addGroup("Infrastructure"))
    project.add_pg("chantier", "cables", group=root.addGroup("Zones"))
    assert pi.needs_reorganization(root, pi.known_operator_schemas(project, {"wyre": WYRE})) is False
    assert pi.reorganize_legacy_tree(project, {"wyre": WYRE}) == []
    assert _names(root) == ["Infrastructure", "Zones"]
    assert pi.get_bridge_info()["operators"] == [] and pi.get_bridge_info()["operator_labels"] == {}


def test_first_known_schema_decides_not_the_first_layer(pi, monkeypatch):
    # public.structures d'abord, wyre.cables ensuite : le groupe va chez Wyre.
    project = install_fake_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    infra = root.addGroup("Infrastructure")
    project.add_pg("public", "structures", group=infra)
    project.add_pg("wyre", "cables", group=infra)
    assert pi.reorganize_legacy_tree(project, {"wyre": WYRE}) == [WYRE]
    assert _names(root) == ["Wyre"]


def test_layer_ids_order_and_state_are_kept(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    infra = root.addGroup("Infrastructure")
    infra.setExpanded(False)
    ducts = project.add_pg("wyre", "ducts", group=infra)
    cables = project.add_pg("wyre", "cables", group=infra)
    root.findLayer(cables.id()).setItemVisibilityChecked(False)
    before = [ducts.id(), cables.id()]

    pi.reorganize_legacy_tree(project, {"wyre": WYRE})

    moved = root.children()[0].children()[0]
    assert [n.layerId() for n in moved.children()] == before
    assert moved.isExpanded() is False
    assert root.findLayer(cables.id()).itemVisibilityChecked() is False
    assert project.mapLayer(cables.id()) is cables  # la couche reste au projet


def test_homonymous_legacy_groups_are_merged_not_doubled(pi, monkeypatch):
    # « Infrastructure » (EN) et « Infraestrutura » (PT) a la racine : un seul
    # sous-groupe, les deux contenus reunis.
    project = install_fake_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    first = project.add_pg("wyre", "ducts", group=root.addGroup("Infrastructure"))
    second = project.add_pg("wyre", "cables", group=root.addGroup("Infraestrutura"))

    assert pi.reorganize_legacy_tree(project, {"wyre": WYRE}) == [WYRE]

    assert _names(root) == ["Wyre"] and _names(root.children()[0]) == ["Infrastructure"]
    assert [n.layerId() for n in root.children()[0].children()[0].children()] == [first.id(), second.id()]


def test_personal_layers_and_groups_are_never_moved(pi, monkeypatch):
    project, layers = legacy_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    mine = next(c for c in root.children() if c.name() == "Mes couches")
    personal_group_layer = layers["mine"]
    extra = root.addGroup("Infrastructure perso")           # hors catalogue : meme prefixe, autre nom
    perso = project.add_pg("wyre", "cables", name="Mes cables", group=extra)
    nested = root.addGroup("Autre").addGroup("Zones")       # groupe du catalogue, mais pas a la racine
    nested_layer = project.add_pg("wyre", "zone_pop", name="Zone perso", group=nested)
    personal_root = [mine, root.findLayer(layers["root_layer"].id()), extra, nested.parent()]
    mine_children = mine.children()

    pi.reorganize_legacy_tree(project, {"wyre": WYRE})

    after = root.children()
    for node in personal_root:
        assert node in after and node.parent() is root     # memes noeuds, toujours a la racine
    assert mine.children() == mine_children
    assert mine.children()[0].layer() is personal_group_layer
    assert extra.children()[0].layer() is perso
    assert nested.parent().children() == [nested] and nested.children()[0].layer() is nested_layer
    assert _names(root)[:2] == ["Wyre", "Commun"]
    # Aucun nom perdu : memes couches avant / apres.
    assert {n.layerId() for n in root.findLayers()} == {ly.id() for ly in project.mapLayers().values()}


def test_needs_reorganization_false_for_19_project(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    pi.init_project({}, "", {"cables", "interventions"}, operator=WYRE)
    root = project.layerTreeRoot()
    assert pi.needs_reorganization(root) is False
    before = tree_names(project)
    assert pi.reorganize_legacy_tree(project, {"wyre": WYRE}) == []
    assert tree_names(project) == before


def test_needs_reorganization_cases(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    root = project.layerTreeRoot()
    assert pi.needs_reorganization(root) is False                      # projet vide
    for name in ("Basemaps", "Référence", "Mes couches", "Listes"):
        root.addGroup(name)
    project.add_pg("wyre", "cables")                                   # couche a la racine : pas un groupe
    assert pi.needs_reorganization(root) is False
    infra = root.addGroup("Infraestrutura")
    assert pi.needs_reorganization(root) is False                      # groupe operateur vide : reste en place
    project.add_pg("wyre", "cables", group=infra)
    assert pi.needs_reorganization(root) is True
    root.addGroup("Chantier")                                          # groupe commun : toujours a ranger
    assert pi.needs_reorganization(root) is True


def test_common_only_bridge_project_does_not_need_reorganization(pi, monkeypatch):
    # Chargement de couches communes seules : projet Bridge sans operateur.
    project = install_fake_project(pi, monkeypatch)
    pi.init_project({}, "", {"interventions"}, operator=ORANGE)
    assert pi.get_bridge_info()["operators"] == [] and pi.is_bridge_project()
    assert pi.needs_reorganization(project.layerTreeRoot()) is False
    assert pi.reorganize_legacy_tree(project, {}) == []


# --- cote plugin : clic « Ajouter des couches » ----------------------------------------------


@pytest.fixture
def plugin18(bp18, pi, monkeypatch, tmp_path):  # noqa: F811
    """Plugin connecte sur un projet 1.8 (identite ``wyre`` seule, groupes a
    la racine) ; le FakeProject est partage par le plugin, le chargement et
    le renommage. Hooks, perimetre et sources des listes de valeurs sont
    neutralises ; noms de couches et groupes sont ceux du vrai
    ``apply_all_translations`` (langue courante : en, d'ou « Common »)."""
    project, layers = legacy_project(pi, monkeypatch)
    project.writeEntry("bridge", "operator", "wyre")
    project.writeEntry("bridge", "version", "3.0.0")
    sketcher = bp18.bridge_sketcher
    for module in (bp18, sketcher):
        monkeypatch.setattr(module, "QgsProject", pi.QgsProject)
    monkeypatch.setattr(sketcher, "QgsDataSourceUri", FakeUri)
    monkeypatch.setattr(sketcher, "QgsVectorLayer", FakeLayer)
    monkeypatch.setattr(sketcher, "QgsEditorWidgetSetup", FakeEditorWidgetSetup)
    core = sys.modules["qgis.core"]
    for name in ("QgsPalLayerSettings", "QgsVectorLayerSimpleLabeling"):
        monkeypatch.setattr(core, name, type(name, (), {}), raising=False)
    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)
    for name in ("_hook_layers", "_apply_scope_to_layers", "_rewrite_value_relation_sources"):
        monkeypatch.setattr(plugin, name, lambda *a, **k: None)
    return plugin, project, layers


def _operator_layer_names(project, schema, table):
    return [ly.name() for ly in project.pg_layers(schema, table)]


def test_adding_second_operator_reorganizes_and_forces_suffix(bp18, pi, plugin18):
    plugin, project, layers = plugin18
    messages = plugin.iface.messageBar().messages
    root = project.layerTreeRoot()
    plugin._operator_registry = {"wyre": WYRE, "orange": ORANGE}

    plugin._load_operator_layers(ORANGE, {"cables"}, set(), True, suffix=False)

    info = pi.get_bridge_info()
    assert info["operators"] == ["wyre", "orange"]
    assert info["operator_labels"] == {"wyre": "Wyre", "orange": "Orange"}
    assert info["operator_suffix"] is True  # deuxieme operateur : obligatoire, la case decochee est ecartee
    assert messages[-2][2] == bp18.tr("home.reorganized", operators="Wyre")
    assert messages[-1][2] == bp18.tr("init.success", count=1)
    assert _operator_layer_names(project, "wyre", "cables") == ["Cables · Wyre"]  # suffixe recu au clic « Ajouter »
    assert _operator_layer_names(project, "orange", "cables") == ["Cables · Orange"]
    assert _names(root)[:3] == ["Wyre", "Orange", "Common"]
    assert root.findLayer(layers["cables"].id()).parent() is root.children()[0].children()[1]
    assert "Infrastructure" in _names(root.children()[1])
    assert pi.needs_reorganization(root) is False


def test_adding_same_operator_to_18_project_respects_the_suffix_box(bp18, pi, plugin18):
    plugin, project, layers = plugin18
    messages = plugin.iface.messageBar().messages
    plugin._operator_registry = {"wyre": WYRE}

    plugin._load_operator_layers(WYRE, {"structures"}, set(), True, suffix=False)

    info = pi.get_bridge_info()
    assert info["operators"] == ["wyre"] and info["operator_suffix"] is False
    assert messages[-2][2] == bp18.tr("home.reorganized", operators="Wyre")
    assert _operator_layer_names(project, "wyre", "cables") == ["Cables"]
    root = project.layerTreeRoot()
    assert _names(root)[:2] == ["Wyre", "Common"]
    assert project.count_pg("wyre", "structures") == 1

    # Second « Ajouter » : rien a reorganiser, pas de nouveau message, suffixe coche.
    count_messages = len(messages)
    plugin._load_operator_layers(WYRE, {"ducts"}, set(), True, suffix=True)
    assert [m[2] for m in messages[count_messages:]] == [bp18.tr("init.success", count=1)]
    assert _operator_layer_names(project, "wyre", "cables") == ["Cables · Wyre"]
    assert _names(root).count("Wyre") == 1 and _names(root).count("Common") == 1
    assert "Wyre" not in _names(root.children()[0])


def test_legacy_group_message_lists_every_operator(bp18, pi, plugin18):
    plugin, project, _layers = plugin18
    project.add_pg("orange", "zone_mro", group=project.layerTreeRoot().addGroup("Zones"))
    plugin._operator_registry = {"wyre": WYRE, "orange": ORANGE}

    plugin._load_operator_layers(WYRE, {"structures"}, set(), True)

    assert plugin.iface.messageBar().messages[-2][2] == bp18.tr("home.reorganized", operators="Wyre, Orange")
    assert pi.get_bridge_info()["operators"] == ["wyre", "orange"]


def test_phantom_legacy_group_neither_stamps_nor_forces_suffix(bp18, pi, plugin18):
    # Seul un groupe « Zones » vide traine a la racine : aucun operateur Wyre
    # n'est invente (identite inchangee, suffixe non force, pas de message).
    plugin, project, _layers = plugin18
    root = project.layerTreeRoot()
    for layer in list(project.mapLayers().values()):
        project.removeMapLayer(layer)
    for node in root.children():
        root.removeChildNode(node)
    root.addGroup("Zones")
    project.writeEntry("bridge", "operator", "")
    messages = plugin.iface.messageBar().messages
    plugin._operator_registry = {"wyre": WYRE, "orange": ORANGE}

    plugin._load_operator_layers(ORANGE, {"cables"}, set(), True, suffix=False)

    info = pi.get_bridge_info()
    assert info["operators"] == ["orange"] and info["operator_labels"] == {"orange": "Orange"}
    assert info["operator_suffix"] is False
    assert _names(root)[0] == "Zones" and _names(root)[1:] == ["Orange"]  # « Zones » reste a la racine
    assert [m[2] for m in messages] == [bp18.tr("init.success", count=1)]


def test_already_19_project_gets_no_reorganization(bp18, pi, plugin18, monkeypatch):
    plugin, project, _layers = plugin18
    plugin._operator_registry = {"wyre": WYRE}
    plugin._load_operator_layers(WYRE, {"structures"}, set(), True)
    calls = []
    monkeypatch.setattr(pi, "reorganize_legacy_tree", lambda *a, **k: calls.append(a) or [])
    plugin._load_operator_layers(WYRE, {"ducts"}, set(), True)
    assert calls == []


def test_load_failure_after_reorganization_is_reported_not_raised(bp18, pi, plugin18, monkeypatch):
    plugin, project, _layers = plugin18
    errors = []

    def boom(*_args, **_kwargs):
        raise RuntimeError("permission denied for schema orange")

    monkeypatch.setattr(pi, "init_project", boom)
    monkeypatch.setattr(bp18.QMessageBox, "critical", staticmethod(lambda *a, **k: errors.append(a[2])))
    plugin._operator_registry = {"wyre": WYRE, "orange": ORANGE}
    assert plugin._load_operator_layers(ORANGE, {"cables"}, set(), True) == 0
    assert errors == [bp18.tr("init.error", error="permission denied for schema orange")]
    # La reorganisation, faite avant le chargement, reste (et sera enregistree).
    assert pi.needs_reorganization(project.layerTreeRoot()) is False
    assert _names(project.layerTreeRoot())[:2] == ["Wyre", "Commun"]


def test_only_common_legacy_groups_get_their_own_message(bp18, pi, monkeypatch, tmp_path):
    project = install_fake_project(pi, monkeypatch)
    project.add_pg("chantier", "interventions", group=project.layerTreeRoot().addGroup("Chantier"))
    for module in (bp18, bp18.bridge_sketcher):
        monkeypatch.setattr(module, "QgsProject", pi.QgsProject)
    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)
    monkeypatch.setattr(bp18.bridge_sketcher, "apply_all_translations", lambda *a, **k: None)
    for name in ("_hook_layers", "_apply_scope_to_layers", "_rewrite_value_relation_sources"):
        monkeypatch.setattr(plugin, name, lambda *a, **k: None)

    plugin._load_operator_layers(WYRE, {"cables"}, set(), True)

    messages = plugin.iface.messageBar().messages
    assert messages[-2][2] == bp18.tr("home.reorganized_common")
    assert _names(project.layerTreeRoot()) == ["Wyre", "Commun"]  # traductions neutralisees ici
    assert pi.get_bridge_info()["operators"] == ["wyre"]  # l'operateur charge, pas un operateur « herite »


def test_opening_legacy_project_never_reorganizes(bp18, pi, plugin18, monkeypatch):
    plugin, project, _layers = plugin18
    calls = []
    # Espion (et non une exception, que le try/except de _on_project_read
    # avalerait) : zero appel, sur la fonction du module et sur l'attribut
    # que bridge_plugin importe a l'appel.
    monkeypatch.setattr(pi, "reorganize_legacy_tree", lambda *a, **k: calls.append(a) or [])
    stamps = []
    real_stamp = pi.stamp_project
    monkeypatch.setattr(pi, "stamp_project", lambda *a, **k: stamps.append(a) or real_stamp(*a, **k))
    legacy_shape = tree_shape(project)
    legacy_entries = dict(project._entries)
    assert plugin._connected is True and pi.is_bridge_project()

    plugin._on_project_read(None)

    assert calls == [] and stamps == []
    assert tree_shape(project) == legacy_shape  # seuls les noms de couches sont traduits, comme en 1.8
    assert project._entries == legacy_entries
    assert pi.needs_reorganization(project.layerTreeRoot()) is True
