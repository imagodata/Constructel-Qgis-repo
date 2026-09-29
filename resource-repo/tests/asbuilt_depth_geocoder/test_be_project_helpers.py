import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import build_locate_failure_warning, same_postgres_table


def _ident(**overrides):
    base = {
        "schema": "public",
        "table": "geofiber_asbuilt_depth_points",
        "database": "ftth",
        "host": "db.example",
        "port": "5432",
        "service": "",
    }
    base.update(overrides)
    return base


# --- same_postgres_table ---------------------------------------------------

def test_meme_table_meme_serveur():
    assert same_postgres_table(_ident(), _ident())


def test_table_differente():
    assert not same_postgres_table(
        _ident(), _ident(table="geofiber_asbuilt_depth_segments")
    )


def test_schema_different():
    assert not same_postgres_table(_ident(), _ident(schema="ref"))


def test_schema_vide_equivaut_a_public():
    assert same_postgres_table(_ident(schema=""), _ident())


def test_port_vide_equivaut_a_5432_et_hote_insensible_a_la_casse():
    assert same_postgres_table(_ident(port="", host="DB.Example"), _ident())


def test_autre_serveur_ou_autre_base():
    assert not same_postgres_table(_ident(host="autre"), _ident())
    assert not same_postgres_table(_ident(database="autre"), _ident())
    assert not same_postgres_table(_ident(port="5433"), _ident())


def test_via_service_identique():
    a = _ident(host="", port="", service="be")
    assert same_postgres_table(a, dict(a))
    assert not same_postgres_table(a, _ident(host="", port="", service="autre"))


def test_mixte_service_et_hote_repli_sur_la_base():
    svc = _ident(host="", port="", service="be")
    assert same_postgres_table(svc, _ident())
    assert not same_postgres_table(svc, _ident(database="autre"))
    # Base inconnue des deux côtés : non décidable -> pas la même table.
    assert not same_postgres_table(_ident(host="", port="", service="be", database=""),
                                   _ident(database=""))


def test_table_vide_jamais_egale():
    assert not same_postgres_table(_ident(table=""), _ident(table=""))


# --- build_locate_failure_warning -------------------------------------------

def test_aucun_point_a_localiser_pas_d_avertissement():
    assert build_locate_failure_warning(0, 0, 0, 0) is None


def test_au_moins_un_point_localise_pas_d_avertissement():
    assert build_locate_failure_warning(10, 1, 2, 7) is None


def test_aucun_troncon_trouve_pointe_ref_osm_roads():
    msg = build_locate_failure_warning(12, 0, 2, 10)
    assert msg is not None
    assert "12 point(s)" in msg
    assert "2 sans nom de rue" in msg
    assert "10 sans tronçon" in msg
    assert "ref.osm_roads" in msg


def test_aucun_nom_de_rue_ne_blame_pas_osm():
    msg = build_locate_failure_warning(5, 0, 5, 0)
    assert msg is not None
    assert "ref.osm_roads" not in msg
    assert "Address" in msg


def test_repli_overpass_en_echec_le_dit():
    msg = build_locate_failure_warning(4, 0, 0, 4, overpass_status="failed")
    assert "Overpass" in msg and "échoué" in msg


def test_repli_overpass_sans_resultat_pointe_les_noms():
    msg = build_locate_failure_warning(4, 0, 1, 3, overpass_status="ok")
    assert "Overpass" in msg and "orthographe" in msg


# --- SCR des couches 'be' ----------------------------------------------------
import pytest  # noqa: E402

from geocode_asbuilt_depth import InterventionRecord, crs_needs_fix, split_ungeocoded  # noqa: E402


@pytest.mark.parametrize("authid, fix", [
    ("", True), (None, True), ("EPSG:3857", True), ("EPSG:4326", True),
    ("EPSG:31370", False), ("epsg:31370", False), (" EPSG:31370 ", False),
    ("EPSG:3812", True),
])
def test_crs_needs_fix(authid, fix):
    assert crs_needs_fix(authid) is fix


# --- non geocodees : « si geocode, garder que geocode » ------------------------

def _entry(intervention):
    return (InterventionRecord(intervention=intervention, address="Rue X 1"), "q")


def test_echec_de_regeocodage_d_un_point_existant_non_pousse():
    entries = [_entry("11111111"), _entry("22222222")]
    to_push, kept = split_ungeocoded(entries, existing_point_ids={"22222222"})
    assert [e[0].intervention for e in to_push] == ["11111111"]
    assert [e[0].intervention for e in kept] == ["22222222"]


def test_ids_compares_en_texte():
    to_push, kept = split_ungeocoded([_entry("12345678")], existing_point_ids={12345678})
    assert to_push == [] and len(kept) == 1


def test_aucun_point_existant_tout_est_pousse():
    entries = [_entry("1"), _entry("2")]
    assert split_ungeocoded(entries, set()) == (entries, [])
