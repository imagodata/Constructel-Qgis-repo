"""Non-regression : WGS84 -> Lambert belge 72 (EPSG:31370), sans PyQGIS.

Valeurs de reference calculees par PROJ (cs2cs EPSG:4326 -> EPSG:31370,
operation « Inverse of BD72 to WGS 84 (3) + Belgian Lambert 72 », celle que
QGIS retient), le 29/09.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    BELGIAN_LAMBERT_AUTHID, lambert72_plausible, wgs84_to_lambert72_pure,
)

REFERENCES = [
    # (lon, lat, x_ref, y_ref)
    (4.3525, 50.8467, 148855.423, 170699.676),   # Bruxelles, Grand-Place
    (6.26, 50.39, 284472.568, 121612.483),       # Büllingen
    (5.5, 50.6, 230084.314, 143868.130),         # Liège (région)
]


@pytest.mark.parametrize("lon, lat, x_ref, y_ref", REFERENCES)
def test_projection_identique_a_proj_au_centimetre(lon, lat, x_ref, y_ref):
    x, y = wgs84_to_lambert72_pure(lon, lat)
    assert abs(x - x_ref) < 0.01 and abs(y - y_ref) < 0.01
    assert lambert72_plausible(x, y)


def test_ordre_des_axes_lon_lat():
    # Axes inverses (lat, lon) : resultat hors de Belgique -> detecte.
    x, y = wgs84_to_lambert72_pure(50.8467, 4.3525)
    assert not lambert72_plausible(x, y)


def test_ordres_de_grandeur_grand_place_et_bullingen():
    x, y = wgs84_to_lambert72_pure(4.3525, 50.8467)
    assert abs(x - 148_500) < 500 and abs(y - 170_500) < 500
    x, y = wgs84_to_lambert72_pure(6.26, 50.39)
    assert 280_000 < x < 290_000 and 118_000 < y < 128_000


def test_scr_unique_lambert_belge_72():
    assert BELGIAN_LAMBERT_AUTHID == "EPSG:31370"  # pas Lambert 2008 (EPSG:3812)


# --- emprises des requetes Overpass : 31370 -> WGS84, ordre lat/lon ----------
from geocode_asbuilt_depth import lambert72_to_wgs84_pure, lambert_bbox_to_wgs84  # noqa: E402


def test_inverse_identique_a_proj():
    # cs2cs EPSG:31370 EPSG:4326 : 280500.96 125280.9 -> 50.4238665 6.2054419
    lon, lat = lambert72_to_wgs84_pure(280500.96, 125280.9)
    assert abs(lat - 50.4238665) < 1e-6 and abs(lon - 6.2054419) < 1e-6


def test_aller_retour():
    for lon, lat, _x, _y in REFERENCES:
        back = lambert72_to_wgs84_pure(*wgs84_to_lambert72_pure(lon, lat))
        assert abs(back[0] - lon) < 1e-8 and abs(back[1] - lat) < 1e-8


def test_bbox_overpass_sud_ouest_nord_est_en_lat_lon():
    south, west, north, east = lambert_bbox_to_wgs84(
        (280_400.0, 125_200.0, 280_600.0, 125_400.0), lambert72_to_wgs84_pure
    )
    assert 50.42 < south < north < 50.43      # latitudes d'abord
    assert 6.20 < west < east < 6.21          # puis longitudes
    assert south <= 50.4238665 <= north and west <= 6.2054419 <= east
