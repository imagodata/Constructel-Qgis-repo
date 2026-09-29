"""Scenarios reels du run du 29/09 (points en retrait de la rue, rues coupees)."""
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    LOCATE_RADIUS_M, LOW_CONFIDENCE_DISTANCE_M, ROAD_JOIN_TOLERANCE_M, OsmWay,
    compact_street_name, diagnose_unlocated, extract_street_name, fuzzy_name_match,
    homonym_components_ambiguous, homonym_decision, index_ways_by_name,
    locate_on_ways, locate_rows_on_osm, nearest_way, normalize_street_name,
)


def _way(way_id, y, name=None, highway="residential", x0=-200.0, x1=200.0):
    """Voie horizontale a l'ordonnee y (le point teste est en (0, 0))."""
    return OsmWay(way_id=way_id, names=(normalize_street_name(name),) if name else (),
                  highway=highway, coords=[(x0, y), (x1, y)])


def _locate(ways, names=(), coords_only=False):
    items = [] if coords_only else [("p", tuple(names), 0.0, 0.0)]
    extra = [("p", 0.0, 0.0)] if coords_only else []
    results, reasons, _ = locate_rows_on_osm(items, extra, ways)
    return results.get("p"), reasons.get("p")


def test_constantes_du_passage():
    assert LOCATE_RADIUS_M >= 80 and LOW_CONFIDENCE_DISTANCE_M == 50
    assert 10 <= ROAD_JOIN_TOLERANCE_M <= 15


def test_a_am_ranzelborn_34_m_et_homonyme_a_90_m():
    ways = [_way(1, 34, "Am Ranzelborn"), _way(2, -90, "Am Ranzelborn"),
            _way(3, 24, None, highway="track")]
    (match, method), _ = _locate(ways, ["Am Ranzelborn"])
    assert method == "name" and round(match["distance"]) == 34 and match["way_id"] == 1


def test_b_am_sonnenhang_33_et_50_m():
    ways = [_way(1, 33, "Am Sonnenhang"), _way(2, -50, "Am Sonnenhang"),
            _way(3, 16, None, highway="track")]
    (match, method), _ = _locate(ways, ["Am Sonnenhang"])
    assert method == "name" and round(match["distance"]) == 33


def test_c_auf_dem_kamp_secondary_a_47_m():
    ways = [_way(1, 47, "Auf dem Kamp", highway="secondary"), _way(2, 29, None, highway="path")]
    (match, method), _ = _locate(ways, ["Auf dem Kamp"])
    assert method == "name" and round(match["distance"]) == 47


def test_d_dellenstrasse_39_m_prefere_aux_autres_noms_a_29_m():
    ways = [_way(1, 39, "Dellenstraße", highway="tertiary"),
            _way(2, 29, "Zur Stöck"), _way(3, -29, "Vennstraße")]
    (match, method), _ = _locate(ways, ["Dellenstrasse"])
    assert method == "name" and match["way_id"] == 1


def test_e_zur_domaene_41_m():
    (match, method), _ = _locate([_way(1, 41, "Zur Domäne")], ["Zur Domäne"])
    assert method == "name" and round(match["distance"]) == 41
    assert match["distance"] <= LOW_CONFIDENCE_DISTANCE_M      # confiance normale


def test_f_klosterstrasse_aucune_voie_a_120_m():
    ways = [_way(1, 125, "Hauptstraße"), _way(2, -130, "Kirchweg")]
    result, reason = _locate(ways, ["Klosterstrasse"])
    assert result is None and reason == "no_match"
    cause, distance = diagnose_unlocated(0.0, 0.0, ["Klosterstrasse"], ways)
    assert cause == "aucune voie à proximité" and round(distance) == 125


def test_voie_du_meme_nom_entre_50_et_150_m_rattachee_faible_confiance():
    (match, method), _ = _locate([_way(1, 120, "Rue X"), _way(2, 10, "Rue Y")], ["Rue X"])
    assert method == "name" and match["distance"] > LOW_CONFIDENCE_DISTANCE_M


def test_au_dela_de_150_m_non_localise_cause_trop_loin():
    ways = [_way(1, 160, "Rue X")]
    result, _ = _locate(ways, ["Rue X"])
    assert result is None
    cause, distance = diagnose_unlocated(0.0, 0.0, ["Rue X"], ways)
    assert cause == "voie du même nom trop loin" and round(distance) == 160


def test_nom_introuvable_mais_voies_proches():
    ways = [_way(1, 10, "Rue Y"), _way(2, -12, "Rue Z")]
    cause, distance = diagnose_unlocated(0.0, 0.0, ["Rue X"], ways)
    assert cause == "nom introuvable" and round(distance) == 10


def test_chemins_sans_nom_jamais_cible_ni_voisin_ambigu():
    ways = [_way(1, 20, None, highway="track"), _way(2, 18, "Rue Y"),
            _way(3, 3, None, highway="path")]
    (match, method), _ = _locate(ways, coords_only=True)
    assert method == "coords" and match["way_names"] == (normalize_street_name("Rue Y"),)


# --- homonymes / raccord -----------------------------------------------------

def test_regle_d_ambiguite_des_homonymes_quasi_egalite_seulement():
    assert homonym_decision(15.0, 15.0) == "ambiguous"
    assert homonym_decision(20.0, 22.0) == "ambiguous"         # +2 m, rapport 1,1
    assert homonym_decision(10.0, 22.0) == "low"               # la plus proche, marge < 15 m
    assert homonym_decision(30.0, 40.0) == "low"
    assert homonym_decision(34.0, 90.0) == "ok"
    assert homonym_decision(45.0, 55.0) == "ambiguous"         # les deux > 40 m : regle historique
    assert homonym_decision(45.0, 80.0) == "ok"
    assert homonym_components_ambiguous(20.0, 22.0)


def test_rue_en_deux_composantes_a_10_et_22_m_localisee_la_plus_proche():
    ways = [_way(1, 10, "Major Long Straße"), _way(2, -22, "Major Long Straße")]
    (match, method), _ = _locate(ways, ["Major Long Strasse"])
    assert method == "name" and match["way_id"] == 1
    assert match["low_confidence"]                       # marge 12 m < 15 m


def test_deux_composantes_a_20_et_22_m_ambigu():
    ways = [_way(1, 20, "Rue X"), _way(2, -22, "Rue X")]
    assert _locate(ways, ["Rue X"]) == (None, "ambiguous")


def test_adresse_x_slash_x_avec_code_postal_et_localite():
    assert extract_street_name(
        "Malmedyer Straße/Malmedyer Straße 175 4780 Sankt Vith") == "Malmedyer Straße"
    assert extract_street_name("Malmedyer Straße/Malmedyer Straße 175") == "Malmedyer Straße"
    assert extract_street_name("Rue de la Gare 12/3") == "Rue de la Gare"
    assert extract_street_name("Rue X/3") == "Rue X/3"        # notation boite : inchangee
    ways = [_way(1, 31, "Malmedyer Straße")]
    name = extract_street_name("Malmedyer Straße/Malmedyer Straße 175 4780 Sankt Vith")
    (match, method), _ = _locate(ways, [name])
    assert method == "name" and round(match["distance"]) == 31


def test_nom_approchant_lindenallee():
    assert fuzzy_name_match("Lindenallee", "Linden-Allee")
    assert compact_street_name("Linden-Allee") == compact_street_name("Lindenalee")
    (match, method), _ = _locate([_way(1, 0.5, "Linden-Allee")], ["Lindenallee"])
    assert method == "fuzzy" and "approchant" in match["low_confidence"]


def test_nom_approchant_wiesenbachstrasse():
    for osm in ("Wiesenbachstraße", "Wiesenbachstrasse", "Wiesenbach Straße", "Wiesenbach-Str."):
        assert fuzzy_name_match("Wiesenbachstraße", osm), osm
    (match, method), _ = _locate([_way(1, 26, "Wiesenbach Straße")], ["Wiesenbachstraße"])
    assert method == "fuzzy" and round(match["distance"]) == 26


def test_nom_approchant_refuse_si_autre_nom_nettement_plus_proche_ou_trop_loin():
    ways = [_way(1, 30, "Linden-Allee"), _way(2, 10, "Kirchweg")]
    result, _ = _locate(ways, ["Lindenallee"])
    assert result is None or result[1] != "fuzzy"
    assert _locate([_way(1, 45, "Linden-Allee")], ["Lindenallee"])[0] is None \
        or _locate([_way(1, 45, "Linden-Allee")], ["Lindenallee"])[0][1] != "fuzzy"
    assert not fuzzy_name_match("Lindenallee", "Kirchweg")
    assert not fuzzy_name_match("Hauptstraße", "Hochstraße")


def test_repli_coordonnees_prefere_la_voie_de_nom_canonique_jusqu_a_80_m():
    ways = [_way(1, 60, "Malmedyer Straße"), _way(2, 5, "Zur Stöck")]
    results, _r, _l = locate_rows_on_osm([], [], ways)
    way, reason = nearest_way(0.0, 0.0, ways, preferred_names=("malmedyer strasse",))
    assert reason is None and way.way_id == 1
    way, reason = nearest_way(0.0, 0.0, ways, preferred_names=("autre",))
    assert way.way_id == 2


def test_repli_coordonnees_ambigu_seulement_a_moins_de_3_m():
    near = [_way(1, 10, "Rue A"), _way(2, -12, "Rue B")]
    assert nearest_way(0.0, 0.0, near)[1] == "ambiguous"
    far = [_way(1, 10, "Rue A"), _way(2, -14, "Rue B")]
    assert nearest_way(0.0, 0.0, far)[0].way_id == 1


def test_rue_coupee_au_carrefour_recollee_a_12_m():
    # Deux troncons de la meme rue separes de 10 m (carrefour) : meme composante.
    west = OsmWay(1, ("rue x",), "residential", [(-200.0, 20.0), (-5.0, 20.0)])
    east = OsmWay(2, ("rue x",), "residential", [(5.0, 20.0), (200.0, 20.0)])
    index = index_ways_by_name([west, east])
    cache = {}
    m1, _ = locate_on_ways(-50.0, 0.0, "Rue X", index, cache=cache)
    m2, _ = locate_on_ways(50.0, 0.0, "Rue X", index, cache=cache)
    assert m1["road_key"] == m2["road_key"] == "overpass:rue x:1"
