"""Bridge 1.9, tache 4 (spec § 7, § 9.3 ; plan D4, decisions K7 et T3-I1) :
styles, listes de valeurs (ValueRelation) et get_feature ciblent le meme
operateur. Doublures T/fakes19.py, aucun QGIS ni aucune base.

La couche cible est cherchee par (schema de la source, table) et designee par
son identifiant, jamais par son nom affiche : avec un seul operateur, les
noms peuvent rester sans suffixe. Une couche operateur dont la cible n'est
pas chargee dans son schema n'est jamais reorientee vers un autre operateur.
Une couche commune (chantier...) vise le schema que le LayerSource de son
style designe (K7)."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

from constructel_bridge import bridge_operators as bo
from constructel_bridge_tests.fakes19 import FakeEditorWidgetSetup, FakeLayer, FakeUri
from constructel_bridge_tests.test_bridge19_names import project, sk, stamp  # noqa: F401
from constructel_bridge_tests.test_bridge1b_wiring import _FakeIface, qgis_stub_path  # noqa: F401
from constructel_bridge_tests.test_bridge_project_init import project_init  # noqa: F401

LABELS_TWO = {"wyre": "Wyre", "orange": "Orange"}


def source(schema, table):
    """LayerSource d'une liste de valeurs tel que les QML Farois l'ecrivent."""
    return (f"dbname='farois_ftth' host=192.168.160.31 port=5432 user='ftth_editor' sslmode=require "
            f"key='id' checkPrimaryKeyUnicity='0' table=\"{schema}\".\"{table}\" (geom)")


def add_vr(layer, *configs):
    """Une liste de valeurs par champ (champ 0, champ 1...)."""
    layer._field_names = [f"field_{i}" for i in range(len(configs))]
    for i, config in enumerate(configs):
        layer.setEditorWidgetSetup(i, FakeEditorWidgetSetup("ValueRelation", config))
    return layer


def vr(layer, index=0):
    return layer.editorWidgetSetup(index).config()


# --- module pur ---------------------------------------------------------------------


def test_style_sources():
    assert bo.style_sources("orange", "cables") == [("orange", "cables"), ("wyre", "cables")]
    assert bo.style_sources("wyre", "cables") == [("wyre", "cables")]
    assert bo.style_sources("chantier", "interventions") == [("chantier", "interventions")]


def test_retarget_get_feature():
    expr = "attribute(get_feature('zone_pop', 'id', zone_pop_id), 'code') || get_feature( 'Zones MRO · Wyre' ,'id',x)"
    out = bo.retarget_get_feature(expr, {"zone_pop": "zp_or", "Zones MRO · Wyre": "zm_or"})
    assert out == "attribute(get_feature('zp_or', 'id', zone_pop_id), 'code') || get_feature('zm_or','id',x)"
    assert bo.retarget_get_feature("get_feature('structures','id',1)", {}) == "get_feature('structures','id',1)"
    # Une cle vide n'est pas une cible : get_feature('', ...) reste intact.
    assert bo.retarget_get_feature("get_feature('','id',1)", {"": "x"}) == "get_feature('','id',1)"


def test_retarget_get_feature_only_first_argument_and_longest_key():
    # Seul le premier argument entre apostrophes est remplace ; une cle plus
    # courte ne mange pas une plus longue ; une valeur 'zone_pop' ailleurs
    # dans l'expression reste intacte.
    targets = {"Zones POP": "short", "Zones POP · Orange": "long"}
    expr = "get_feature('Zones POP · Orange','name','Zones POP') || get_feature(\"Zones POP\",'id',1)"
    assert bo.retarget_get_feature(expr, targets) == (
        "get_feature('long','name','Zones POP') || get_feature(\"Zones POP\",'id',1)")


def test_retarget_get_feature_quoted_name():
    # Dans une expression QGIS, une apostrophe d'un nom s'ecrit ''.
    expr = "get_feature('Zones d''Orange','id',1)"
    assert bo.retarget_get_feature(expr, {"Zones d'Orange": "zp_or"}) == "get_feature('zp_or','id',1)"


def test_retarget_layer_source():
    ds = "dbname='farois_ftth' host=h key='id' table=\"wyre\".\"zone_pop\" (geom)"
    assert bo.retarget_layer_source(ds, "orange") == ds.replace('"wyre"', '"orange"')
    ref = "dbname='x' host=h key='rid' table=\"ref\".\"v_form_lists\""
    assert bo.retarget_layer_source(ref, "orange") == ref


def test_retarget_layer_source_keeps_the_filter_and_refuses_unsafe_schema():
    ds = "dbname='x' host=h table=\"wyre\".\"zone_pop\" (geom) sql=\"code\" = 'wyre'"
    assert bo.retarget_layer_source(ds, "orange") == (
        "dbname='x' host=h table=\"orange\".\"zone_pop\" (geom) sql=\"code\" = 'wyre'")
    assert bo.retarget_layer_source(ds, 'orange"; drop') == ds
    assert bo.retarget_layer_source("", "orange") == ""


# --- styles de la base et styles embarques ---------------------------------------------------


class _StyleCursor:
    """Curseur psycopg2 : garde les parametres de chaque requete ; un style
    n'existe que pour les (schema, table, colonne geometrique) de *rows*."""

    def __init__(self, rows):
        self.rows, self.params = rows, []

    def execute(self, _sql, params=()):
        self.params.append(tuple(params))

    def fetchone(self):
        qml = self.rows.get(self.params[-1])
        return (qml,) if qml else None

    def close(self):
        pass


@pytest.fixture
def pi(project_init, monkeypatch):  # noqa: F811
    """bridge_project_init (recette de test_bridge_project_init.py), source des
    couches lue par FakeUri."""
    monkeypatch.setattr(project_init, "QgsDataSourceUri", FakeUri)
    return project_init


def db_cursor(monkeypatch, rows):
    cursor = _StyleCursor(rows)
    connection = SimpleNamespace(cursor=lambda: cursor, close=lambda: None)
    monkeypatch.setattr(sys.modules["psycopg2"], "connect", lambda **_kwargs: connection)
    return cursor


def test_db_style_falls_back_to_wyre_style(pi, monkeypatch):
    cursor = db_cursor(monkeypatch, {("wyre", "cables", "geom"): "<qgis/>"})
    orange_cables = FakeLayer.pg("orange", "cables")
    assert pi._apply_styles_from_db({}, "pw", {"cables@orange": orange_cables}) == {"cables@orange"}
    assert [p[:2] for p in cursor.params] == [("orange", "cables"), ("wyre", "cables")]
    assert len(orange_cables.imported_styles) == 1


def test_db_style_stops_at_the_first_source_found(pi, monkeypatch):
    cursor = db_cursor(monkeypatch, {("orange", "cables", "geom"): "<qgis/>",
                                     ("wyre", "cables", "geom"): "<qgis/>"})
    orange_cables = FakeLayer.pg("orange", "cables")
    assert pi._apply_styles_from_db({}, "pw", {"cables@orange": orange_cables}) == {"cables@orange"}
    assert [p[:2] for p in cursor.params] == [("orange", "cables")]


def test_db_style_of_a_common_table_has_no_fallback(pi, monkeypatch):
    cursor = db_cursor(monkeypatch, {("wyre", "interventions", "geom"): "<qgis/>"})
    interventions = FakeLayer.pg("chantier", "interventions")
    assert pi._apply_styles_from_db({}, "pw", {"interventions": interventions}) == set()
    assert [p[:2] for p in cursor.params] == [("chantier", "interventions")]


def test_embedded_style_found_by_base_key(pi):
    layer = FakeLayer.pg("orange", "cables")
    pi._apply_embedded_styles({"cables@orange": layer})
    assert layer.loaded_styles[0].endswith(os.path.join("styles", "cables.qml"))


def _plugin_with_pg_layer(bp, monkeypatch, schema, table, events):
    from qgis.core import QgsProject, QgsSettings

    QgsSettings().setValue("constructel_bridge/onboarding_done", True)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())
    uri = SimpleNamespace(schema=lambda: schema, table=lambda: table, geometryColumn=lambda: "geom")
    layer = type("PgLayer", (bp.QgsVectorLayer,), {
        "isValid": lambda self: True,
        "providerType": lambda self: "postgres",
        "dataProvider": lambda self: SimpleNamespace(uri=lambda: uri),
        "loadNamedStyle": lambda self, path: events.append("style") or ("", True),
        "triggerRepaint": lambda self: None,
        "isReadOnly": lambda self: False,
    })()
    QgsProject.instance().addMapLayer(layer)
    monkeypatch.setattr(plugin, "_ensure_ref_layers", lambda: None)
    monkeypatch.setattr(bp.bridge_sketcher, "_sync_value_relation_layer_names",
                        lambda project: events.append("sync"))
    return plugin


def test_plugin_default_styles_fall_back_to_wyre(bp18, monkeypatch):
    events = []
    plugin = _plugin_with_pg_layer(bp18, monkeypatch, "orange", "cables", events)
    cursor = _StyleCursor({("wyre", "cables", "geom"): "<qgis/>"})
    plugin._conn = SimpleNamespace(cursor=lambda: cursor)

    plugin._apply_db_default_styles()

    assert events[0] == "style"
    assert [p[:2] for p in cursor.params] == [("orange", "cables"), ("wyre", "cables")]


def test_plugin_default_styles_stop_at_own_style(bp18, monkeypatch):
    events = []
    plugin = _plugin_with_pg_layer(bp18, monkeypatch, "orange", "cables", events)
    cursor = _StyleCursor({("orange", "cables", "geom"): "<qgis/>", ("wyre", "cables", "geom"): "<qgis/>"})
    plugin._conn = SimpleNamespace(cursor=lambda: cursor)

    plugin._apply_db_default_styles()

    assert events == ["style", "sync"]
    assert [p[:2] for p in cursor.params] == [("orange", "cables")]


# --- ValueRelation, infobulles et expressions d'affichage ---------------------------------


def test_value_relations_target_own_operator(sk, project):  # noqa: F811
    stamp(project, ["wyre", "orange"], LABELS_TWO)
    project.add_pg("wyre", "zone_pop", "Zones POP")
    structures_w = project.add_pg("wyre", "structures", "Structures · Wyre")
    zone_pop_or = project.add_pg("orange", "zone_pop", "Zones POP · Orange")
    zone_mro_or = project.add_pg("orange", "zone_mro", "Zones MRO · Orange")
    structures_or = project.add_pg("orange", "structures", "Structures · Orange")
    cables_or = add_vr(
        project.add_pg("orange", "cables", "Cables · Orange"),
        {"Layer": "", "LayerName": "zone_pop", "LayerSource": source("wyre", "zone_pop"), "Key": "id",
         "Value": "coalesce(attribute(get_feature('zone_mro','id',zone_mro_id),'name'),'')"},
        {"Layer": "", "LayerName": structures_w.name(), "Key": "id", "Value": "nomenclature"},
    )

    assert sk.retarget_operator_references(project) == 1

    cfg0, cfg1 = vr(cables_or, 0), vr(cables_or, 1)
    assert cfg0["Layer"] == zone_pop_or.id() and cfg0["LayerName"] == zone_pop_or.name()
    assert 'table="orange"."zone_pop"' in cfg0["LayerSource"]
    assert f"get_feature('{zone_mro_or.id()}'," in cfg0["Value"]
    assert cfg1["Layer"] == structures_or.id() and cfg1["LayerName"] == structures_or.name()
    assert "LayerSource" not in cfg1  # rien a reecrire : pas de source inventee


def test_retarget_is_idempotent(sk, project):  # noqa: F811
    stamp(project, ["wyre", "orange"], LABELS_TWO)
    project.add_pg("wyre", "zone_pop", "Zones POP · Wyre")
    project.add_pg("orange", "zone_pop", "Zones POP · Orange")
    cables_or = add_vr(
        project.add_pg("orange", "cables", "Cables · Orange"),
        {"LayerName": "zone_pop", "LayerSource": source("wyre", "zone_pop"), "Key": "id",
         "Value": "attribute(get_feature('zone_pop','id',zone_pop_id),'code')"},
    )
    cables_or.setMapTipTemplate("[% attribute(get_feature('zone_pop','id',\"zone_pop_id\"),'code') %]")
    assert sk.retarget_operator_references(project) == 1
    once = (vr(cables_or), cables_or.mapTipTemplate())
    assert sk.retarget_operator_references(project) == 0
    assert (vr(cables_or), cables_or.mapTipTemplate()) == once


def test_targets_found_without_any_suffix(sk, project):  # noqa: F811
    # Un seul operateur, suffixe decoche : aucun nom ne porte de suffixe. La
    # cible est trouvee par (schema, table) : ni le Layer du style (identifiant
    # du projet de l'auteur, absent ici) ni son LayerSource (wyre) ne decident.
    stamp(project, ["orange"], {"orange": "Orange"}, suffix="0")
    zone_pop_or = project.add_pg("orange", "zone_pop")
    cables_or = add_vr(
        project.add_pg("orange", "cables"),
        {"Layer": "zone_pop_20261001_9f1c2e", "LayerName": "zone_pop", "LayerSource": source("wyre", "zone_pop"),
         "Key": "id", "Value": "code"},
    )
    cables_or.setMapTipTemplate("[% attribute(get_feature('zone_pop','id',\"zone_pop_id\"),'code') %]")

    sk.apply_all_translations("fr")

    assert (zone_pop_or.name(), cables_or.name()) == ("Zones POP", "Cables")
    cfg = vr(cables_or)
    assert cfg["Layer"] == zone_pop_or.id() and cfg["LayerName"] == "Zones POP"
    assert 'table="orange"."zone_pop"' in cfg["LayerSource"]
    assert f"get_feature('{zone_pop_or.id()}'," in cables_or.mapTipTemplate()


def test_map_tip_and_display_expression_retargeted(sk, project):  # noqa: F811
    stamp(project, ["wyre", "orange"], LABELS_TWO)
    zd_w = project.add_pg("wyre", "zone_distribution", "Zones Distribution · Wyre")
    zd_or = project.add_pg("orange", "zone_distribution", "Zones Distribution · Orange")
    drop_w = project.add_pg("wyre", "zone_drop", "Zones Drop · Wyre")
    drop_or = project.add_pg("orange", "zone_drop", "Zones Drop · Orange")
    tip = "[% attribute(get_feature('zone_distribution', 'id', \"zone_distribution_id\"), 'breakout_letter') %]"
    drop_w.setMapTipTemplate(tip)
    drop_or.setMapTipTemplate(tip)
    # Nom de la couche de l'autre operateur, identifiant de la couche de l'autre operateur.
    drop_or.setDisplayExpression("attribute(get_feature('Zones Distribution · Wyre','id',\"zone_distribution_id\"),'code')")
    drop_w.setDisplayExpression(f"attribute(get_feature('{zd_or.id()}','id',\"zone_distribution_id\"),'code')")

    assert sk.retarget_operator_references(project) == 2

    assert f"get_feature('{zd_or.id()}'," in drop_or.mapTipTemplate()
    assert f"get_feature('{zd_w.id()}'," in drop_w.mapTipTemplate()
    assert drop_or.displayExpression() == f"attribute(get_feature('{zd_or.id()}','id',\"zone_distribution_id\"),'code')"
    assert drop_w.displayExpression() == f"attribute(get_feature('{zd_w.id()}','id',\"zone_distribution_id\"),'code')"


def test_no_cross_operator_fallback(sk, project):  # noqa: F811  # Review Focus 4
    # Projet partage : orange.zone_pop n'est pas chargee, seule wyre.zone_pop
    # l'est. Les references d'une couche orange ne basculent jamais sur wyre,
    # ni par la passe dediee, ni par la passe complete d'un changement de langue.
    stamp(project, ["wyre", "orange"], LABELS_TWO)
    project.add_pg("wyre", "zone_pop", "Zones POP · Wyre")
    original = {"Layer": "", "LayerName": "zone_pop", "LayerSource": source("wyre", "zone_pop"), "Key": "id",
                "Value": "attribute(get_feature('zone_pop','id',zone_pop_id),'code')"}
    cables_or = add_vr(project.add_pg("orange", "cables", "Cables · Orange"), dict(original))
    tip = "[% attribute(get_feature('zone_pop','id',\"zone_pop_id\"),'code') %]"
    cables_or.setMapTipTemplate(tip)

    assert sk.retarget_operator_references(project) == 0
    sk.apply_all_translations("en")

    assert cables_or.name() == "Cables · Orange"
    assert vr(cables_or) == original
    assert cables_or.mapTipTemplate() == tip


def test_filtered_copy_is_kept(sk, project):  # noqa: F811
    stamp(project, ["wyre"], {"wyre": "Wyre"}, suffix="0")
    project.add_pg("wyre", "zone_pop", "Zones POP")
    copy = project.add_pg("wyre", "zone_pop", "Zones POP (copie)")
    ducts_w = add_vr(project.add_pg("wyre", "ducts", "Conduites"),
                     {"Layer": "", "LayerName": "Zones POP (copie)", "Key": "id", "Value": "code"})

    sk.retarget_operator_references(project)

    assert vr(ducts_w)["LayerName"] == "Zones POP (copie)"
    assert vr(ducts_w)["Layer"] == copy.id()


def test_language_switch_keeps_own_operator_targets(sk, project):  # noqa: F811  # Review Focus 3
    stamp(project, ["wyre", "orange"], LABELS_TWO, suffix="0")
    own = {schema: {t: project.add_pg(schema, t) for t in ("zone_mro", "zone_pop")} for schema in ("wyre", "orange")}
    for schema in ("wyre", "orange"):
        cables = add_vr(project.add_pg(schema, "cables"), {
            "Layer": "", "LayerName": "zone_pop", "LayerSource": source("wyre", "zone_pop"), "Key": "id",
            "Value": "attribute(get_feature('zone_mro','id',zone_mro_id),'name')"})
        cables.setMapTipTemplate("[% attribute(get_feature('zone_pop','id',\"zone_pop_id\"),'code') %]")
        own[schema]["cables"] = cables

    sk.apply_all_translations("fr")
    sk.apply_all_translations("en")

    for schema, label in (("wyre", "Wyre"), ("orange", "Orange")):
        layers = own[schema]
        cfg = vr(layers["cables"])
        assert cfg["LayerName"] == f"POP Zones · {label}"
        assert cfg["Layer"] == layers["zone_pop"].id()
        assert f'table="{schema}"."zone_pop"' in cfg["LayerSource"]
        assert cfg["Value"] == f"attribute(get_feature('{layers['zone_mro'].id()}','id',zone_mro_id),'name')"
        assert f"get_feature('{layers['zone_pop'].id()}'," in layers["cables"].mapTipTemplate()


def test_sync_two_operators_never_last_wins(sk, project):  # noqa: F811  # T3-I1
    # Noms suffixes perimes apres un changement de langue, deux operateurs :
    # chaque couche reste sur la couche de son operateur, jamais sur la
    # derniere couche zone_pop rencontree.
    stamp(project, ["wyre", "orange"], LABELS_TWO)
    pop_w = project.add_pg("wyre", "zone_pop", "Zones POP · Wyre")
    pop_or = project.add_pg("orange", "zone_pop", "Zones POP · Orange")
    gf = "attribute(get_feature('zone_pop','id',zone_pop_id),'code')"
    ducts_w = add_vr(project.add_pg("wyre", "ducts", "Conduites · Wyre"),
                     {"LayerName": "POP Zones · Wyre", "Key": "id", "Value": gf})
    ducts_or = add_vr(project.add_pg("orange", "ducts", "Conduites · Orange"),
                      {"LayerName": "POP Zones · Orange", "Key": "id", "Value": gf})

    sk._sync_value_relation_layer_names(project)

    assert vr(ducts_w)["LayerName"] == "Zones POP · Wyre"
    assert vr(ducts_or)["LayerName"] == "Zones POP · Orange"
    assert (vr(ducts_w)["Layer"], vr(ducts_or)["Layer"]) == (pop_w.id(), pop_or.id())
    assert vr(ducts_w)["Value"] == f"attribute(get_feature('{pop_w.id()}','id',zone_pop_id),'code')"
    assert vr(ducts_or)["Value"] == f"attribute(get_feature('{pop_or.id()}','id',zone_pop_id),'code')"


def test_common_layer_follows_the_style_schema(sk, project):  # noqa: F811  # K7
    # Couche commune : le schema vient du LayerSource de la liste (tel que le
    # style le definit), la table de LayerName ; jamais la derniere couche.
    stamp(project, ["wyre", "orange"], LABELS_TWO)
    pop_w = project.add_pg("wyre", "zone_pop", "Zones POP · Wyre")
    pop_or = project.add_pg("orange", "zone_pop", "Zones POP · Orange")
    interventions = add_vr(
        project.add_pg("chantier", "interventions", "Interventions"),
        {"LayerName": "zone_pop", "LayerSource": source("wyre", "zone_pop"), "Key": "id", "Value": "code"},
        {"LayerName": "POP Zones · Wyre", "LayerSource": source("orange", "zone_pop"), "Key": "id", "Value": "code"},
    )

    sk._sync_value_relation_layer_names(project)

    assert (vr(interventions, 0)["LayerName"], vr(interventions, 0)["Layer"]) == (pop_w.name(), pop_w.id())
    assert (vr(interventions, 1)["LayerName"], vr(interventions, 1)["Layer"]) == (pop_or.name(), pop_or.id())
    assert 'table="orange"."zone_pop"' in vr(interventions, 1)["LayerSource"]


def test_common_layer_single_loaded_layer_becomes_the_target(sk, project):  # noqa: F811  # T4-I4
    # Projet Orange seul : les QML figent wyre dans LayerSource ; wyre.zone_pop
    # n'est pas chargee et orange.zone_pop est la seule couche de la table.
    stamp(project, ["orange"], {"orange": "Orange"}, suffix="1")
    pop_or = project.add_pg("orange", "zone_pop", "Zones POP · Orange")
    interventions = add_vr(
        project.add_pg("chantier", "interventions", "Interventions"),
        {"LayerName": "zone_pop", "LayerSource": source("wyre", "zone_pop"), "Key": "id",
         "Value": "attribute(get_feature('zone_pop','id',zone_pop_id),'code')"},
    )

    assert sk._sync_value_relation_layer_names(project) == 1

    cfg = vr(interventions)
    assert (cfg["Layer"], cfg["LayerName"]) == (pop_or.id(), "Zones POP · Orange")
    assert 'table="orange"."zone_pop"' in cfg["LayerSource"]
    assert cfg["Value"] == f"attribute(get_feature('{pop_or.id()}','id',zone_pop_id),'code')"
    assert sk._sync_value_relation_layer_names(project) == 0  # stable


def test_common_layer_several_layers_none_in_style_schema_left_alone(sk, project):  # noqa: F811  # T4-I4
    # Deux operateurs charges, aucun dans le schema du style : rien ne
    # permet de choisir, aucune reecriture.
    stamp(project, ["orange", "proximus"], {"orange": "Orange", "proximus": "Proximus"})
    project.add_pg("orange", "zone_pop", "Zones POP · Orange")
    project.add_pg("proximus", "zone_pop", "Zones POP · Proximus")
    original = {"LayerName": "zone_pop", "LayerSource": source("wyre", "zone_pop"), "Key": "id",
                "Value": "attribute(get_feature('zone_pop','id',zone_pop_id),'code')"}
    interventions = add_vr(project.add_pg("chantier", "interventions", "Interventions"), dict(original))

    sk._sync_value_relation_layer_names(project)

    assert vr(interventions) == original


def test_common_layer_without_source_never_targeted_by_suffix(sk, project):  # noqa: F811  # T4-I3
    # Sans LayerSource, wyre n'est suppose que pour un nom sans suffixe ou
    # suffixe wyre : « POP Zones · Orange » est refuse, jamais remappe sur wyre
    # (ni sur orange : le suffixe sert a refuser, jamais a cibler).
    stamp(project, ["wyre", "orange"], LABELS_TWO)
    project.add_pg("wyre", "zone_pop", "Zones POP · Wyre")
    project.add_pg("orange", "zone_pop", "Zones POP · Orange")
    original = {"LayerName": "POP Zones · Orange", "Key": "id",
                "Value": "attribute(get_feature('zone_pop','id',zone_pop_id),'code')"}
    interventions = add_vr(project.add_pg("chantier", "interventions", "Interventions"), dict(original))

    sk.apply_all_translations("fr")

    assert vr(interventions) == original


# --- choix de la cible : copie filtree, ordre de l'arbre, couche invalide (T4-I1) --------


def _cables_pointing_at_zone_pop(project, schema):
    return add_vr(project.add_pg(schema, "cables"), {
        "LayerName": "zone_pop", "LayerSource": source("wyre", "zone_pop"), "Key": "id",
        "Value": "attribute(get_feature('zone_pop','id',zone_pop_id),'code')"})


def test_filtered_copy_listed_first_is_never_the_target(sk, project):  # noqa: F811
    # mapLayers() est trie par identifiant : la copie « Zones POP · Orange
    # (filtre) » (Z avant z) y passe avant l'originale « zone_pop_<n> », et
    # elle est aussi au-dessus dans l'arbre. La cible reste l'originale.
    stamp(project, ["orange"], {"orange": "Orange"}, suffix="1")
    original = project.add_pg("orange", "zone_pop")  # identifiant zone_pop_<n>
    original.setName("Zones POP · Orange")  # renommee : LayerName "zone_pop" = nom de table
    copy = FakeLayer.pg("orange", "zone_pop", "Zones POP · Orange (filtre)")
    copy.setSubsetString("\"code\" = 'BXL01'")
    project.addMapLayer(copy, False)
    project.layerTreeRoot().insertLayer(0, copy)
    cables = _cables_pointing_at_zone_pop(project, "orange")
    assert list(project.mapLayers())[0] == copy.id()

    sk.retarget_operator_references(project)

    assert (vr(cables)["Layer"], vr(cables)["LayerName"]) == (original.id(), original.name())
    assert vr(cables)["Value"] == f"attribute(get_feature('{original.id()}','id',zone_pop_id),'code')"


def test_tree_order_breaks_ties_between_unfiltered_layers(sk, project):  # noqa: F811
    stamp(project, ["orange"], {"orange": "Orange"}, suffix="1")
    first_in_tree = project.add_pg("orange", "zone_pop")  # identifiant zone_pop_<n>
    first_in_tree.setName("Zones POP · Orange")
    lower = project.add_pg("orange", "zone_pop", "Zones POP · Orange (2)")  # identifiant classe avant
    cables = _cables_pointing_at_zone_pop(project, "orange")
    assert lower.id() < first_in_tree.id()
    assert list(project.mapLayers())[0] == lower.id()

    sk.retarget_operator_references(project)

    assert vr(cables)["Layer"] == first_in_tree.id()


def test_invalid_layer_is_never_targeted(sk, project):  # noqa: F811
    # Couche PostgreSQL injoignable : fournisseur present, isValid() faux.
    stamp(project, ["wyre", "orange"], LABELS_TWO)
    project.add_pg("wyre", "zone_pop", "Zones POP · Wyre")
    broken = project.add_pg("orange", "zone_pop", "Zones POP · Orange")
    broken.isValid = lambda: False
    cables = _cables_pointing_at_zone_pop(project, "orange")
    original = vr(cables)

    assert sk.retarget_operator_references(project) == 0
    assert vr(cables) == original  # ni la couche invalide, ni wyre

    valid = project.add_pg("orange", "zone_pop", "Zones POP · Orange (2)")
    sk.retarget_operator_references(project)
    assert vr(cables)["Layer"] == valid.id()


# --- identifiants perimes (T4-I2) ----------------------------------------------------------


def test_stale_ids_repaired_after_remove_and_reload(sk, project):  # noqa: F811
    # « Ajouter » recharge orange.zone_pop supprimee : nouvel identifiant.
    # L'infobulle et le Value de cables, qui citaient l'ancien, le suivent.
    stamp(project, ["orange"], {"orange": "Orange"}, suffix="1")
    old = project.add_pg("orange", "zone_pop")
    cables = _cables_pointing_at_zone_pop(project, "orange")
    cables.setMapTipTemplate("[% attribute(get_feature('zone_pop','id',\"zone_pop_id\"),'code') %]")
    sk.apply_all_translations("fr")
    assert f"get_feature('{old.id()}'," in cables.mapTipTemplate()

    project.removeMapLayer(old.id())
    new = project.add_pg("orange", "zone_pop")
    sk.apply_all_translations("fr")

    assert new.id() != old.id()
    assert f"get_feature('{new.id()}'," in cables.mapTipTemplate()
    assert vr(cables)["Value"] == f"attribute(get_feature('{new.id()}','id',zone_pop_id),'code')"
    assert vr(cables)["Layer"] == new.id()


def test_stale_id_without_own_target_is_left_alone(sk, project):  # noqa: F811
    stamp(project, ["wyre", "orange"], LABELS_TWO)
    project.add_pg("wyre", "zone_pop", "Zones POP · Wyre")
    cables = project.add_pg("orange", "cables", "Cables · Orange")
    tip = "[% attribute(get_feature('zone_pop_404','id',\"zone_pop_id\"),'code') %]"
    cables.setMapTipTemplate(tip)

    sk.retarget_operator_references(project)

    assert cables.mapTipTemplate() == tip


def test_get_feature_refs_and_layer_id_table():
    assert bo.get_feature_refs("get_feature('a','id',1) || get_feature( 'd''O' ,'x',2)") == ["a", "d'O"]
    assert bo.layer_id_table("zone_pop_8f3a2b1c_4d5e") == "zone_pop"
    assert bo.layer_id_table("subducts_12") == "subducts"
    assert bo.layer_id_table("v_duct_progress_3") == "v_duct_progress"
    assert bo.layer_id_table("zone_pop") is None
    assert bo.layer_id_table("zone_pop_") is None
    assert bo.layer_id_table("interventions_3") is None


def test_common_layer_single_operator_with_filtered_copy_targets_original(sk, project):  # noqa: F811  # T4-I4
    # Projet Orange seul : l'original et une copie filtree de zone_pop, toutes
    # deux dans orange (un seul schema) ; la meilleure selon T4-I1 est l'original.
    stamp(project, ["orange"], {"orange": "Orange"}, suffix="1")
    original = project.add_pg("orange", "zone_pop")
    original.setName("Zones POP · Orange")
    copy = FakeLayer.pg("orange", "zone_pop", "Zones POP · Orange (filtre)")
    copy.setSubsetString("\"code\" = 'BXL01'")
    project.addMapLayer(copy, False)
    project.layerTreeRoot().insertLayer(0, copy)
    interventions = add_vr(
        project.add_pg("chantier", "interventions", "Interventions"),
        {"LayerName": "zone_pop", "LayerSource": source("wyre", "zone_pop"), "Key": "id",
         "Value": "attribute(get_feature('zone_pop','id',zone_pop_id),'code')"},
    )

    sk._sync_value_relation_layer_names(project)

    cfg = vr(interventions)
    assert (cfg["Layer"], cfg["LayerName"]) == (original.id(), "Zones POP · Orange")
    assert 'table="orange"."zone_pop"' in cfg["LayerSource"]
    assert cfg["Value"] == f"attribute(get_feature('{original.id()}','id',zone_pop_id),'code')"
