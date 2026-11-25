"""Bridge 2.1 — registre des projets metier et capacites de la base, sans Qt."""
from __future__ import annotations

from constructel_bridge import bridge_projets as pj

ROW = ("b3f1", "GOFIBER", "GoFiber", "WYRE")


def couche(table, label, order, geom="geom", group="Profondeur As-Built", style="default"):
    return ROW + (table, label, group, style, geom, order)


def test_parse_rows_groups_layers_by_projet_in_sort_order():
    rows = [couche("geofiber_asbuilt_depth_points", "Points", 30), couche("geofiber_asbuilt_depth_connectors", "Connecteurs", 10)]
    (projet,) = pj.parse_projet_rows(rows)
    assert (projet.code, projet.label, projet.operateur_code) == ("GOFIBER", "GoFiber", "WYRE")
    assert [l.label for l in projet.layers] == ["Connecteurs", "Points"]


def test_unsafe_table_or_geometry_is_dropped_and_empty_projet_too():
    rows = [couche('t"; drop', "X", 1), couche("ok_table", "Ok", 2, geom="geom; x"),
            ("p2", "AUTRE", "Autre", None) + ("bad-name", "Y", None, None, None, 1)]
    assert pj.parse_projet_rows(rows) == ()


def test_null_style_and_geometry():
    (projet,) = pj.parse_projet_rows([couche("t", "T", 1, geom=None, style=None, group=None)])
    layer = projet.layers[0]
    assert layer.style_name == "default" and layer.geom_column is None and layer.layer_group is None


def test_two_projets_keep_query_order():
    rows = [couche("t", "T", 1), ("p2", "AUTRE", "Autre", None, "u", "U", None, None, None, 0)]
    assert [p.code for p in pj.parse_projet_rows(rows)] == ["GOFIBER", "AUTRE"]


def test_capabilities_full_and_absent():
    rows = ([("r", "projets", True), ("r", "projet_couches", True), ("r", "projet_tables", True),
             ("r", "qgis_projects", True)]
            + [("f", n, True) for n in pj.CAPABILITY_FUNCTIONS])
    caps = pj.parse_capabilities(rows)
    assert caps.registry and caps.qgis_projects and caps.save and caps.delete and caps.share and caps.share_project
    assert pj.parse_capabilities([]) == pj.NO_CAPABILITIES and not pj.NO_CAPABILITIES.qgis_projects


def test_capabilities_partial_lot_a_only():
    caps = pj.parse_capabilities([("r", "projets", True), ("r", "projet_couches", True), ("r", "projet_tables", True)])
    assert caps.registry and not caps.qgis_table and not caps.qgis_projects and not caps.save


def test_capabilities_without_execute_or_one_share_function():
    rows = [("r", "qgis_projects", True), ("f", "fn_qgis_projects_visible", True), ("f", "fn_qgis_project_save", False),
            ("f", "fn_qgis_project_share", True), ("f", "fn_qgis_project_unshare", True),
            ("f", "fn_qgis_project_eligible_users", True)]
    caps = pj.parse_capabilities(rows)
    assert caps.qgis_projects and not caps.save and not caps.share


def test_write_capabilities_need_the_visible_list():
    rows = [("r", "qgis_projects", True)] + [("f", n, True) for n in pj.CAPABILITY_FUNCTIONS if n != "fn_qgis_projects_visible"]
    caps = pj.parse_capabilities(rows)
    assert not caps.qgis_projects and not caps.save and not caps.delete and not caps.share


def test_registry_not_readable_without_select():
    caps = pj.parse_capabilities([("r", "projets", False), ("r", "projet_couches", True)])
    assert not caps.registry


def test_capabilities_query_reads_the_catalog_only():
    q = pj.CAPABILITIES_QUERY
    assert "pg_class" in q and "pg_proc" in q and "has_function_privilege" in q and "%s" in q
    assert "projet." not in q.replace("'projet'", "")


def test_projets_query_never_reads_shared_account_columns():
    assert "lecture_qfield" not in pj.PROJETS_QUERY and "comptes_partages" not in pj.PROJETS_QUERY
    assert "to_jsonb(p) ->> 'operateur_code'" in pj.PROJETS_QUERY


def test_is_identifier():
    assert pj.is_identifier("geofiber_points") and pj.is_identifier("_x1")
    assert not pj.is_identifier("1x") and not pj.is_identifier("A") and not pj.is_identifier(None)
    assert not pj.is_identifier("a" * 64)


def test_group_projets_usable_first_then_others_then_none():
    def mk(code, label, op):
        return pj.ProjetInfo(code.lower(), code, label, op, (pj.ProjetLayer("t", "T", None, "default", None, 0),))
    projets = [mk("C", "Cirrus", None), mk("B", "beta", "ORANGE"), mk("A", "Alpha", "WYRE"), mk("Z", "Zeta", "PROXIMUS")]
    groups = pj.group_projets(projets, ["ORANGE", "WYRE"], {"PROXIMUS": "Proximus"})
    assert [(op, [p.code for p in ps]) for op, ps in groups] == [("ORANGE", ["B"]), ("WYRE", ["A"]), ("PROXIMUS", ["Z"]), (None, ["C"])]


def test_group_projets_sorts_inside_a_group_by_label():
    def mk(code, label):
        return pj.ProjetInfo(code.lower(), code, label, "WYRE", (pj.ProjetLayer("t", "T", None, "default", None, 0),))
    groups = pj.group_projets([mk("Z", "zz"), mk("A", "Ébène"), mk("B", "beta")], ["WYRE"], {})
    assert [p.code for p in groups[0][1]] == ["B", "A", "Z"]


# --- Bridge 2.2 : schema des tables lu dans le registre (Farois mig 596) ---------------


def test_parse_projets_lit_le_schema():
    rows = [couche("geofiber_asbuilt_depth_points", "Points", 1) + ("data",),
            couche("geofiber_meta", "Meta", 2) + ("projet",)]
    (projet,) = pj.parse_projet_rows(rows)
    assert {l.table: l.schema for l in projet.layers} == {"geofiber_asbuilt_depth_points": "data", "geofiber_meta": "projet"}
    assert pj.projet_layer_schemas((projet,)) == {"geofiber_asbuilt_depth_points": "data", "geofiber_meta": "projet"}
    q = pj.PROJETS_QUERY
    assert "JOIN projet.projet_tables t ON (t.projet_id, t.table_name) = (c.projet_id, c.table_name)" in q
    assert "COALESCE(to_jsonb(t) ->> 'schema_name', 'projet')" in q
    assert "LEFT JOIN" not in q


def test_parse_projets_schema_absent_vaut_projet():
    # Ligne a 10 colonnes (requete 2.1) ou schema NULL : projet.
    (projet,) = pj.parse_projet_rows([couche("t", "T", 1), couche("u", "U", 2) + (None,)])
    assert [l.schema for l in projet.layers] == ["projet", "projet"]
    assert pj.ProjetLayer("t", "T", None, "default", None, 0).schema == "projet"
    # Schema qui n'est pas un identifiant simple : la couche est ecartee.
    assert pj.parse_projet_rows([couche("t", "T", 1) + ('data"; x',)]) == ()


def test_capabilities_exige_projet_tables():
    base = [("r", "projets", True), ("r", "projet_couches", True)]
    assert not pj.parse_capabilities(base).registry
    assert not pj.parse_capabilities(base + [("r", "projet_tables", False)]).registry
    assert pj.parse_capabilities(base + [("r", "projet_tables", True)]).registry
    assert "'projet_tables'" in pj.CAPABILITIES_QUERY
