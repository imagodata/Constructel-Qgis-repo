import socket
import sys
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
import geocode_asbuilt_depth as g


def _raises(exc):
    return mock.patch.object(g.urllib.request, "urlopen", side_effect=exc)


def _expect_unavailable(exc):
    with _raises(exc):
        try:
            g.nominatim_geocode("Rue X 1, 1000 Bruxelles", "UA")
        except g.NominatimUnavailableError:
            return
    raise AssertionError("NominatimUnavailableError attendue")


def test_url_error_est_une_panne_pas_un_introuvable():
    _expect_unavailable(urllib.error.URLError("dns"))


def test_timeout_est_une_panne():
    _expect_unavailable(socket.timeout("timed out"))


def test_http_5xx_est_une_panne():
    _expect_unavailable(urllib.error.HTTPError("u", 503, "x", {}, None))


def test_http_429_reste_un_blocage():
    with _raises(urllib.error.HTTPError("u", 429, "x", {}, None)):
        try:
            g.nominatim_geocode("q", "UA")
        except g.NominatimBlockedError:
            return
    raise AssertionError("NominatimBlockedError attendue")


def test_http_404_reste_un_introuvable():
    with _raises(urllib.error.HTTPError("u", 404, "x", {}, None)):
        assert g.nominatim_geocode("q", "UA") is None


def test_la_panne_remonte_a_travers_le_repli():
    def boom(*a, **k):
        raise g.NominatimUnavailableError("down")
    try:
        g.geocode_with_dedup_fallback("Rue X 1", "1000", "Bruxelles", "UA", geocode_fn=boom)
    except g.NominatimUnavailableError:
        return
    raise AssertionError("la panne ne doit pas devenir un None")
