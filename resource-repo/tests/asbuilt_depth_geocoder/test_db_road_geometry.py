"""Axe + type de voie des routes de la base via fn_asbuilt_road_geometry (par lots)."""
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    batch_road_geometry_sql, first_rows_by_tag, pick_db_road_geometry,
)


def test_requete_par_lot():
    sql = batch_road_geometry_sql([(0, 1.5, 2.5, "'Keppelborn'"), (1, 3.0, 4.0, "'l''Église'")], 150.0)
    assert sql.startswith("SELECT v.tag, g.road_key, ST_AsText(g.road_geom), g.road_highway ")
    assert "CROSS JOIN LATERAL public.fn_asbuilt_road_geometry(" in sql
    assert "(0, 1.5::double precision, 2.5::double precision, 'Keppelborn'::text)" in sql
    assert "'l''Église'::text" in sql and "150.0" in sql
    assert "WITH ORDINALITY AS g(road_key, road_geom, road_highway, ord)" in sql
    assert "ref.osm_roads" not in sql              # aucun acces direct au schema ref


def test_geometrie_retenue_si_meme_road_key_et_meme_longueur():
    rows = first_rows_by_tag([[0, "keppelborn#42", "LINESTRING(0 0, 30 40)", "residential"]])
    parts, highway = pick_db_road_geometry(rows[0], "keppelborn#42", 50.0)
    assert parts == [[(0.0, 0.0), (30.0, 40.0)]] and highway == "residential"


def test_road_key_discordant_ou_longueur_differente_ou_vide_non_retenue():
    row = ("keppelborn#42", "LINESTRING(0 0, 30 40)", "residential")
    assert pick_db_road_geometry(row, "keppelborn#7", 50.0) is None
    assert pick_db_road_geometry(row, "keppelborn#42", 80.0) is None
    assert pick_db_road_geometry(None, "keppelborn#42", 50.0) is None       # fail-closed
    assert pick_db_road_geometry(("keppelborn#42", None, "x"), "keppelborn#42", 50.0) is None


def test_highway_absent_donne_decalage_par_defaut():
    parts, highway = pick_db_road_geometry(
        ("k#1", "MULTILINESTRING((0 0,10 0),(10 0,20 0))", None), "k#1", 20.0
    )
    assert len(parts) == 2 and highway == ""
