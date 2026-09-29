import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import extract_street_name


def test_numero_simple():
    assert extract_street_name("Rue de la Gare 12") == "Rue de la Gare"


def test_numero_boite_notation_belge():
    assert extract_street_name("Rue de la Gare 12/3") == "Rue de la Gare"


def test_numero_avec_lettre():
    assert extract_street_name("Avenue Louise 145A") == "Avenue Louise"


def test_sans_numero_repli_sur_la_chaine_entiere():
    assert extract_street_name("Rue de la Gare") == "Rue de la Gare"


def test_vide_ou_none():
    assert extract_street_name(None) == ""
    assert extract_street_name("") == ""
    assert extract_street_name("   ") == ""


def test_szett_suivi_de_s_parasite_est_nettoye():
    # Le ß allemand vaut deja "ss" : un 's' immediatement apres est une
    # duplication parasite observee en donnees reelles (export BeOn).
    assert extract_street_name("Malmedyer Straßse 12") == "Malmedyer Straße"


def test_szett_sans_s_parasite_est_inchange():
    assert extract_street_name("Malmedyer Straße 12") == "Malmedyer Straße"


def test_szett_suivi_de_S_majuscule_est_nettoye():
    assert extract_street_name("Kaiserstraßse") == "Kaiserstraße"


def test_nom_de_rue_repete_bug_export():
    # Bug d'export BeOn : libelle de rue repete via « / » (cf.
    # clean_duplicated_address) -- ne doit PAS finir en « Malmedyer Straße/... ».
    assert (
        extract_street_name("Malmedyer Straße/Malmedyer Straße/Malmedyer Straße 203")
        == "Malmedyer Straße"
    )


def test_nom_de_rue_repete_avec_artefact_szett():
    assert (
        extract_street_name("Malmedyer Straßse/Malmedyer Straße 203")
        == "Malmedyer Straße"
    )


def test_code_postal_apres_numero():
    assert extract_street_name("Rue de la Gare 12 1000") == "Rue de la Gare"


def test_suffixe_boite():
    assert extract_street_name("Rue de la Gare 12 bte 3") == "Rue de la Gare"
    assert extract_street_name("Rue de la Gare 12 boîte 3A") == "Rue de la Gare"
    assert extract_street_name("Rue de la Gare 12 bte. B 1000") == "Rue de la Gare"


def test_suffixe_boite_ne_mord_pas_sur_un_nom_de_rue():
    assert extract_street_name("Rue du Bus Rouge 5") == "Rue du Bus Rouge"


def test_format_a_virgule():
    assert extract_street_name("Rue de la Gare, 12") == "Rue de la Gare"
    assert extract_street_name("Rue de la Gare 12, 1000 Bruxelles") == "Rue de la Gare"
    assert extract_street_name("12, Rue de la Gare") == "Rue de la Gare"


def test_nom_de_rue_se_terminant_par_un_nombre_non_ampute_deux_fois():
    assert extract_street_name("Rue du 11 Novembre 7") == "Rue du 11 Novembre"
