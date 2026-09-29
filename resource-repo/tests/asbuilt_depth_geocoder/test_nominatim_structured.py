"""Nominatim : requete structuree, repli texte libre, validation Belgique."""
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    NominatimHit, build_structured_params, describe_structured,
    geocode_with_dedup_fallback, in_belgium_wgs84,
)


def test_parametres_structures():
    assert build_structured_params("Malmedyer Straße 203", "4760", "Büllingen") == {
        "street": "Malmedyer Straße 203", "postalcode": "4760", "city": "Büllingen",
        "country": "Belgium",
    }
    # Code postal repris de l'adresse et retire de la rue.
    assert build_structured_params("Rue X 12 1000", "", "") == {
        "street": "Rue X 12", "postalcode": "1000", "country": "Belgium"}
    assert build_structured_params("Rue X 12", "", "") is None     # trop incomplet
    assert build_structured_params("", "1000", "Bruxelles") is None


def test_trace_lisible():
    assert describe_structured({"street": "Rue X 1", "postalcode": "1000", "city": "Bxl",
                                "country": "Belgium"}) == \
        "street=Rue X 1; postalcode=1000; city=Bxl; country=Belgium"


def test_structuree_d_abord_puis_texte_libre():
    calls = []
    hit = NominatimHit(lat=50.4, lon=6.26)

    def geocode(query, ua, structured=None):
        calls.append("structured" if structured else "q")
        return hit if structured is None else None

    sleeps = []
    got, query, fallback = geocode_with_dedup_fallback(
        "Rue X 1", "4760", "Büllingen", "UA", geocode_fn=geocode,
        sleep_fn=lambda: sleeps.append(1),
    )
    assert got is hit and calls == ["structured", "q"] and len(sleeps) == 1
    assert query.startswith("Rue X 1") and not fallback


def test_structuree_reussie_trace_la_requete_structuree():
    def geocode(query, ua, structured=None):
        return NominatimHit(lat=50.4, lon=6.26) if structured else None

    got, query, _ = geocode_with_dedup_fallback("Rue X 1", "4760", "B", "UA", geocode_fn=geocode)
    assert got is not None and query.startswith("street=Rue X 1")


def test_sans_champs_structures_texte_libre_seul():
    calls = []

    def geocode(query, ua, structured=None):
        calls.append(structured)
        return None

    geocode_with_dedup_fallback("Rue X 1", "", "", "UA", geocode_fn=geocode)
    assert calls == [None]


def test_validation_belgique():
    assert in_belgium_wgs84(50.8467, 4.3525) and in_belgium_wgs84(50.39, 6.26)
    assert not in_belgium_wgs84(48.85, 2.35)     # Paris
    assert not in_belgium_wgs84(52.37, 4.89)     # Amsterdam
    assert not in_belgium_wgs84(4.35, 50.85)     # lat/lon inverses
    assert not in_belgium_wgs84(None, 4.0)
