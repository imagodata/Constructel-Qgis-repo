"""Repli Overpass allege : requetes par noms, regroupement, backoff, cache, isolation."""
import io
import json
import os
import re
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(
    0, str(Path(__file__).parents[2] / "collections/asbuilt_depth_geocoder/processing")
)
from geocode_asbuilt_depth import (
    OverpassError, OverpassRequest, build_overpass_query, fetch_overpass_cached,
    OVERPASS_MIRRORS, lambert72_plausible, overpass_cache_path, overpass_cache_read,
    overpass_cache_write, overpass_fetch, overpass_wait_s, parse_overpass_status,
    plan_overpass_requests, run_overpass_requests, street_name_regex,
)


def _matches(address_name, osm_name):
    return re.fullmatch(street_name_regex(address_name), osm_name, re.IGNORECASE) is not None


# --- regex / echappement ------------------------------------------------------

@pytest.mark.parametrize("address, osm", [
    ("Malmedyer Strasse", "Malmedyer Straße"),
    ("Malmedyer Straße", "Malmedyer Strasse"),
    ("Rue de l'Eglise", "Rue de l’Église"),
    ("rue de l'église", "Rue de l'Église"),
    ("Saint-Vith Strasse", "Saint Vith Straße"),
    ("Am Sidders", "Am Sidders"),
])
def test_regex_tolere_accents_eszett_apostrophes_tirets_casse(address, osm):
    assert _matches(address, osm)


def test_regex_ne_matche_pas_une_autre_rue():
    assert not _matches("Am Sidders", "Am Siddersweg")
    assert not _matches("Rue X", "Rue Y")


def test_regex_echappe_les_metacaracteres():
    pattern = street_name_regex("Rue (A.B)+ [x]|y*")
    assert re.fullmatch(pattern, "Rue (A.B)+ [x]|y*", re.IGNORECASE)
    assert not re.fullmatch(pattern, "Rue AxB", re.IGNORECASE)
    for meta in "().+[]|*":
        assert "\\" + meta in pattern


def test_requete_echappe_guillemets_et_antislash_pour_le_ql():
    query = build_overpass_query(['Rue "A".B'], 50.0, 6.0, 50.1, 6.1)
    # Guillemet echappe, antislash de la regex double dans la chaine QL.
    assert query.count('\\"') == 8 and "\\\\.B" in query  # 2 guillemets x 4 cles
    # Une seule clause par cle de nom, toutes filtrees.
    assert query.count('way["highway"]') == 4
    assert query.count('~"^(') == 4


def test_requete_contient_les_noms_de_la_tuile_seulement():
    query = build_overpass_query(["Am Sidders", "Auf dem Hütel"], 50.0, 6.0, 50.1, 6.1)
    ql = query.split('["name"~')[1].split(",i]")[0]
    regex = json.loads(ql)  # litteral QL == litteral JSON pour ces echappements
    assert re.fullmatch(regex, "Am Sidders", re.IGNORECASE)
    assert re.fullmatch(regex, "Auf dem Hütel", re.IGNORECASE)
    assert not re.fullmatch(regex, "Büllinger Straße", re.IGNORECASE)


# --- regroupement ---------------------------------------------------------------

def test_regroupement_localite_emprise_serree_arrondie():
    items = [
        ("1", "Am Sidders", 280_120.0, 125_480.0, "Büllingen"),
        ("2", "Am Sidders", 280_300.0, 125_500.0, "Büllingen"),
        ("3", "Auf dem Hütel", 281_000.0, 125_900.0, "Büllingen"),
        ("4", "Rue X", 150_000.0, 170_000.0, "Bruxelles"),  # loin : autre requete
    ]
    reqs = plan_overpass_requests(items, margin_m=250.0, grid_m=100.0)
    assert len(reqs) == 2
    near = next(r for r in reqs if "1" in r.ids)
    assert near.names == ("Am Sidders", "Auf dem Hütel") and near.ids == ("1", "2", "3")
    assert near.bbox == (279_800.0, 125_200.0, 281_300.0, 126_200.0)


def test_rues_homonymes_de_localites_differentes_jamais_dans_la_meme_requete():
    items = [
        ("1", "Hauptstraße", 280_000.0, 125_000.0, "Büllingen"),
        ("2", "Hauptstraße", 281_000.0, 125_500.0, "Bütgenbach"),  # proche mais autre localite
        ("3", "Kirchweg", 280_100.0, 125_100.0, "Büllingen"),
    ]
    reqs = plan_overpass_requests(items)
    with_1 = next(r for r in reqs if "1" in r.ids)
    with_2 = next(r for r in reqs if "2" in r.ids)
    assert with_1 is not with_2
    # Emprise de chaque requete : ses propres points seulement (± marge).
    assert with_1.bbox[2] < 281_000.0 and with_2.bbox[0] > 280_100.0


def test_regroupement_jusqu_a_40_noms_et_emprise_bornee():
    items = [(str(i), f"Rue {i:03d}", 100_000.0 + i, 100_000.0, "X") for i in range(85)]
    reqs = plan_overpass_requests(items, max_names=40)
    assert [len(r.names) for r in reqs] == [40, 40, 5]
    far = [("a", "Rue A", 100_000.0, 100_000.0, "X"), ("b", "Rue B", 110_000.0, 100_000.0, "X")]
    assert len(plan_overpass_requests(far, max_span_m=3000.0)) == 2


def test_regroupement_ignore_les_rues_vides_et_regroupe_les_graphies():
    reqs = plan_overpass_requests([
        ("1", "", 0.0, 0.0), ("2", "Rue X", 0.0, 0.0), ("3", "RUE  X", 1.0, 0.0),
    ])
    assert len(reqs) == 1 and reqs[0].ids == ("2", "3")


# --- fetch : backoff / miroirs / slots ----------------------------------------------

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http(code, retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return urllib.error.HTTPError("u", code, "err", headers, None)


def _urlopen(script, status_text=None):
    calls = []

    def urlopen(request, timeout):
        if request.full_url.endswith("/status"):
            calls.append(("status", timeout))
            return _Resp((status_text or "Rate limit: 4\n2 slots available now.\n").encode())
        calls.append((request.full_url, timeout))
        behaviour = script[sum(1 for c in calls if c[0] != "status") - 1]
        if isinstance(behaviour, Exception):
            raise behaviour
        return _Resp(json.dumps(behaviour).encode("utf-8"))

    return urlopen, calls


OK = {"elements": [{"type": "way", "id": 1}]}
MIRRORS = ("https://m1/api/interpreter", "https://m2/api/interpreter", "https://m3/api/interpreter")


def _post_calls(calls):
    return [c for c in calls if c[0] != "status"]


def test_504_retente_sur_le_meme_miroir_avec_backoff_4_8_16():
    urlopen, calls = _urlopen([_http(504), _http(504), _http(504), OK])
    sleeps = []
    data = overpass_fetch("q", "UA", mirrors=MIRRORS, urlopen=urlopen, sleep=sleeps.append,
                          rng=lambda: 0.0)
    assert data == OK
    assert [c[0] for c in _post_calls(calls)] == [MIRRORS[0]] * 4
    assert sleeps == [4.0, 8.0, 16.0]


def test_502_503_aussi_retentes_et_gigue_ajoutee():
    urlopen, calls = _urlopen([_http(502), _http(503), OK])
    sleeps = []
    overpass_fetch("q", "UA", mirrors=MIRRORS, urlopen=urlopen, sleep=sleeps.append,
                   rng=lambda: 1.0, check_status=False)
    assert sleeps == [4.0 + 2.0, 8.0 + 2.0]


def test_429_respecte_retry_after_plafonne():
    urlopen, _ = _urlopen([_http(429, "30"), _http(429, "600"), OK])
    sleeps = []
    overpass_fetch("q", "UA", mirrors=MIRRORS, urlopen=urlopen, sleep=sleeps.append,
                   rng=lambda: 0.0, check_status=False)
    assert sleeps == [30.0, 60.0]


def test_attente_d_un_slot_libre_via_api_status():
    status = "Rate limit: 2\nSlot available after: 2026-09-29T12:00:05Z, in 7 seconds.\n" \
             "Slot available after: 2026-09-29T12:00:20Z, in 22 seconds.\n"
    urlopen, calls = _urlopen([OK], status_text=status)
    sleeps = []
    overpass_fetch("q", "UA", mirrors=MIRRORS, urlopen=urlopen, sleep=sleeps.append)
    assert calls[0][0] == "status" and sleeps == [7.0]


def test_parse_overpass_status():
    assert parse_overpass_status("Rate limit: 4\n2 slots available now.") == 0.0
    assert parse_overpass_status("0 slots available now.\nSlot available after: x, in 12 seconds.") == 12.0
    assert parse_overpass_status("") is None
    assert parse_overpass_status("n'importe quoi") is None


def test_backoff_pur():
    assert overpass_wait_s(0) == 4.0 and overpass_wait_s(2) == 16.0
    assert overpass_wait_s(1, jitter=1.5) == 9.5
    assert overpass_wait_s(0, retry_after=45) == 45.0
    assert overpass_wait_s(5) == 60.0  # plafond


def test_miroirs_de_repli_apres_4_essais_du_principal():
    urlopen, calls = _urlopen([_http(504)] * 4 + [_http(429), OK])
    sleeps = []
    data = overpass_fetch("q", "UA", mirrors=MIRRORS, urlopen=urlopen, sleep=sleeps.append,
                          rng=lambda: 0.0, check_status=False, timeout=35.0,
                          fallback_timeout=20.0)
    assert data == OK
    posts = _post_calls(calls)
    assert [c[0] for c in posts] == [MIRRORS[0]] * 4 + [MIRRORS[1]] * 2
    assert [c[1] for c in posts] == [35.0] * 4 + [20.0] * 2


def test_timeout_passe_au_miroir_suivant_sans_attendre():
    urlopen, calls = _urlopen([OSError("The read operation timed out"), OK])
    sleeps = []
    assert overpass_fetch("q", "UA", mirrors=MIRRORS, urlopen=urlopen, sleep=sleeps.append,
                          check_status=False) == OK
    assert [c[0] for c in _post_calls(calls)] == [MIRRORS[0], MIRRORS[1]] and sleeps == []


def test_tous_les_miroirs_en_echec():
    urlopen, _ = _urlopen([_http(504)] * 4 + [OSError("t")] * 2)
    with pytest.raises(OverpassError):
        overpass_fetch("q", "UA", mirrors=MIRRORS[:2], urlopen=urlopen, sleep=lambda s: None,
                       check_status=False)


def test_miroirs_publics_verifies():
    assert OVERPASS_MIRRORS[0] == "https://overpass-api.de/api/interpreter"
    assert "https://overpass.openstreetmap.fr/api/interpreter" in OVERPASS_MIRRORS
    assert not any("osm.ch" in m for m in OVERPASS_MIRRORS)  # extrait suisse


# --- cache ---------------------------------------------------------------------------

def test_cache_miss_puis_hit(tmp_path):
    calls = []

    def fetch(query, ua):
        calls.append(query)
        return OK

    assert fetch_overpass_cached("q1", "UA", str(tmp_path), fetch=fetch) == (OK, False)
    assert fetch_overpass_cached("q1", "UA", str(tmp_path), fetch=fetch) == (OK, True)
    assert calls == ["q1"]
    assert fetch_overpass_cached("q2", "UA", str(tmp_path), fetch=fetch)[1] is False


def test_cache_perime_ou_corrompu_ignore(tmp_path):
    path = overpass_cache_path(str(tmp_path), "q")
    assert overpass_cache_write(path, OK)
    mtime = os.path.getmtime(path)
    assert overpass_cache_read(path, ttl_s=10, now=mtime + 5) == OK
    assert overpass_cache_read(path, ttl_s=10, now=mtime + 11) is None
    Path(path).write_text("{pas du json", encoding="utf-8")
    assert overpass_cache_read(path) is None
    Path(path).write_text('{"autre": 1}', encoding="utf-8")
    assert overpass_cache_read(path) is None
    assert overpass_cache_read(str(tmp_path / "absent.json")) is None


def test_echec_non_mis_en_cache(tmp_path):
    def fetch(query, ua):
        raise OverpassError("504")

    with pytest.raises(OverpassError):
        fetch_overpass_cached("q", "UA", str(tmp_path), fetch=fetch)
    assert not os.listdir(tmp_path)


def test_sans_dossier_de_cache():
    assert fetch_overpass_cached("q", "UA", None, fetch=lambda q, u: OK) == (OK, False)


# --- execution : isolation des echecs ------------------------------------------------

def _reqs(n):
    return [OverpassRequest((0, 0, 1, 1), (f"Rue {i}",), (str(i),)) for i in range(n)]


def test_echec_d_une_requete_isole():
    def fetch(req):
        if req.ids == ("1",):
            raise OverpassError("504")
        return OK, req.ids == ("2",)

    pauses, reports = [], []
    outcomes = run_overpass_requests(
        _reqs(4), fetch, pause=lambda: pauses.append(1),
        report=lambda i, n, o: reports.append((i, n, o.error == "")),
    )
    assert [o.data is not None for o in outcomes] == [True, False, True, True]
    assert reports == [(1, 4, True), (2, 4, False), (3, 4, True), (4, 4, True)]
    # Pause apres chaque requete reseau sauf la derniere et celles du cache.
    assert len(pauses) == 2


def test_coupe_circuit_seulement_sans_aucun_succes_apres_pause_longue():
    calls, pauses = [], []

    def fetch(req):
        calls.append(req.ids)
        raise OverpassError("504")

    outcomes = run_overpass_requests(_reqs(12), fetch, max_consecutive_failures=8,
                                     give_up_pause=lambda: pauses.append(30))
    # 8 echecs, pause longue, 1 dernier essai, puis renoncement.
    assert len(calls) == 9 and pauses == [30]
    assert all(o.data is None for o in outcomes)
    assert "non tentée" in outcomes[9].error


def test_pas_de_coupe_circuit_si_un_succes_dans_le_run():
    state = {}
    run_overpass_requests(_reqs(1), lambda r: (OK, False), state=state)
    calls = []

    def fetch(req):
        calls.append(req.ids)
        raise OverpassError("504")

    run_overpass_requests(_reqs(12), fetch, max_consecutive_failures=8, state=state)
    assert len(calls) == 12  # instabilite toleree : tout est tente


def test_reprise_apres_echec_partiel_via_le_cache(tmp_path):
    """Run 1 : la requete 1 echoue ; run 2 : seules les requetes manquantes partent."""
    network = []

    def make_fetch(failing):
        def fetch_net(query, ua):
            network.append(query)
            if query in failing:
                raise OverpassError("504")
            return {"elements": [{"type": "way", "id": len(query)}]}

        def fetch(req):
            return fetch_overpass_cached(f"q{req.ids[0]}", "UA", str(tmp_path), fetch=fetch_net)
        return fetch

    run1 = run_overpass_requests(_reqs(3), make_fetch({"q1"}))
    assert [o.data is not None for o in run1] == [True, False, True]
    network.clear()
    run2 = run_overpass_requests(_reqs(3), make_fetch(set()))
    assert network == ["q1"]  # seule la requete manquante
    assert [o.from_cache for o in run2] == [True, False, True]


def test_annulation_respectee():
    state = {"n": 0}

    def fetch(req):
        state["n"] += 1
        return OK, False

    outcomes = run_overpass_requests(_reqs(3), fetch, is_canceled=lambda: state["n"] >= 1)
    assert state["n"] == 1 and outcomes[1].error == "annulé"


def test_fetch_injecte_via_urlopen_isolation_bout_en_bout(tmp_path):
    script = {"Rue 0": [OK], "Rue 1": [_http(400)] + [OSError("t")] * 4, "Rue 2": [OK]}

    def fetch(req):
        urlopen, _ = _urlopen(script[req.names[0]])
        data = overpass_fetch(build_overpass_query(req.names, 50, 6, 50.1, 6.1), "UA",
                              mirrors=MIRRORS, urlopen=urlopen, sleep=lambda s: None,
                              check_status=False)
        return data, False

    outcomes = run_overpass_requests(_reqs(3), fetch)
    assert [o.data is not None for o in outcomes] == [True, False, True]


def test_plage_lambert72():
    assert lambert72_plausible(274_781.0, 108_690.0)
    assert not lambert72_plausible(6.2, 50.3)       # degres non reprojetes
    assert not lambert72_plausible(0.0, 0.0) and not lambert72_plausible(-1.0, 10.0)
    assert not lambert72_plausible(150_000.0, 260_000.0)
    assert not lambert72_plausible(None, 1.0)
