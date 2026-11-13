"""Bridge 1.9 (tache 8, spec § 6.6 et § 7, decisions D13 et D15) : Diagnostic
utilisable SANS connexion.

Quatre verifications, chacune OK / avertissement / erreur, avec une action
quand c'est possible : version du plugin (depot Constructel), extensions
recommandees, acces au serveur Farois (TCP + SSLRequest PostgreSQL + poignee
de main TLS verifiee, sans login), identifiant nominatif.

  * logique pure (``bridge_diagnostic``) testee a fond ; les tests reseau
    utilisent de VRAIS sockets locaux (127.0.0.1, port ephemere) et des
    certificats jetables generes par openssl (comme test_bridge_mtls) ;
  * K9 : echeance globale ``time.monotonic()`` par verification, pas un
    delai par operation (connect rapide puis reponse lente : toujours dans
    le delai) ;
  * le Diagnostic n'ouvre aucune session PostgreSQL et ne lit aucun secret
    de l'Auth Manager (doublures qui echouent si on les touche) ;
  * le dialogue tourne ici sur des doublures de widgets et de QgsTask : le
    rendu Qt reel reste a la recette manuelle (tache 10)."""
from __future__ import annotations

import contextlib
import gc
import importlib
import importlib.util
import re
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import types
import urllib.request
import warnings
from pathlib import Path

import pytest

from constructel_bridge import bridge_diagnostic as bd
from constructel_bridge_tests.test_bridge18_connect import (
    LOGIN,
    _initgui_ready,
    _make_plugin,
    _not_permitted,
    _start,
)
from constructel_bridge_tests.test_bridge19_checkin import onb  # noqa: F401  (fixture)

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "constructel_bridge"
SSL_REQUEST = struct.pack("!ii", 8, 80877103)
REAL_CA_BUNDLE = str(PLUGIN_DIR / "certs" / "root-ca-bundle.pem")


# --- Serveurs locaux (vrais sockets) ------------------------------------------


def _recv_exact(conn, size):
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            break
        data += chunk
    return data


@contextlib.contextmanager
def _server(handler):
    """Serveur TCP sur 127.0.0.1 (port ephemere) : la PREMIERE connexion
    acceptee est confiee a handler(conn, stop) dans un fil. En sortie, stop est
    leve, tout est ferme et le fil rejoint (aucun socket laisse ouvert)."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(0.05)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                conn, _addr = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(5)
                try:
                    handler(conn, stop)
                except OSError:
                    pass
            return

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1]
    finally:
        stop.set()
        thread.join(5)
        listener.close()
        assert not thread.is_alive()


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _silent(conn, stop):
    stop.wait(10)


def _read_http_request(conn):
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


def _http_body(body: bytes, status="200 OK"):
    def handler(conn, stop):
        _read_http_request(conn)
        conn.sendall(f"HTTP/1.0 {status}\r\nContent-Type: text/xml\r\n"
                     f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    return handler


@pytest.fixture(autouse=True)
def _no_leaked_socket():
    """Aucun socket laisse ouvert : les fils d'appoint du Diagnostic (DNS,
    lecture abandonnee a l'echeance) doivent finir seuls, puis le GC ne doit
    lever aucun ResourceWarning."""
    gc.collect()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        yield
        for thread in threading.enumerate():
            if thread.name.startswith("constructel-bridge-diagnostic"):
                thread.join(3)
                assert not thread.is_alive(), thread.name
        gc.collect()
    assert [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)] == []


# --- PKI jetable (openssl, comme test_bridge_mtls) ------------------------------

_CA_CNF = """[req]
distinguished_name = dn
prompt = no
x509_extensions = v3_ca
[dn]
CN = diag-test-ca
[v3_ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always
"""
_SERVER_EXT = """basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = IP:127.0.0.1
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid
"""


def _openssl(*args):
    subprocess.run(["openssl", *map(str, args)], check=True, capture_output=True)


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    """CA de test + certificat serveur pour IP:127.0.0.1 (et rien d'autre)."""
    d = tmp_path_factory.mktemp("diag_pki")
    cnf, ext = d / "ca.cnf", d / "server.ext"
    cnf.write_text(_CA_CNF)
    ext.write_text(_SERVER_EXT)
    ec = ("-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes")
    _openssl("req", "-x509", "-config", cnf, *ec, "-days", "3650", "-keyout", d / "ca.key", "-out", d / "ca.crt")
    _openssl("req", "-new", "-config", cnf, *ec, "-subj", "/CN=diag-test-server",
             "-keyout", d / "server.key", "-out", d / "server.csr")
    _openssl("x509", "-req", "-in", d / "server.csr", "-CA", d / "ca.crt", "-CAkey", d / "ca.key",
             "-CAcreateserial", "-days", "3650", "-extfile", ext, "-out", d / "server.crt")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(d / "server.crt"), str(d / "server.key"))
    return types.SimpleNamespace(ca=str(d / "ca.crt"), server_context=context)


def _postgres_tls(context, outcome):
    """Serveur PostgreSQL minimal : SSLRequest -> 'S' -> poignee de main TLS.
    *outcome* recoit "ok" ou l'erreur cote serveur (certificat refuse par le
    client, par exemple)."""
    def handler(conn, stop):
        assert _recv_exact(conn, 8) == SSL_REQUEST
        conn.sendall(b"S")
        try:
            with context.wrap_socket(conn, server_side=True):
                outcome.append("ok")
        except (ssl.SSLError, OSError) as exc:
            outcome.append(exc)
    return handler


# --- Versions -------------------------------------------------------------------


@pytest.mark.parametrize("a,b,expected", [
    ("1.8.4", "1.9.0", -1), ("1.10.0", "1.9.9", 1), ("1.9", "1.9.0", 0), ("1.9.0", "1.9.0", 0),
    ("1.9.0", "1.8.4", 1), ("1.9.0-beta", "1.9.0", 0), ("", "0", 0), ("1.9.²", "1.9.0", 0),
])
def test_compare_versions(a, b, expected):
    assert bd.compare_versions(a, b) == expected


XML = ('<plugins><pyqgis_plugin name="Constructel Bridge" version="1.8.3"/>'
       '<pyqgis_plugin name="Constructel Bridge" version="1.8.4"/><pyqgis_plugin name="Autre" version="9.9"/></plugins>')
REAL_XML = ('<?xml version="1.0" encoding="UTF-8"?>\n<plugins>\n'
            '  <pyqgis_plugin name="Constructel Bridge" version="1.10.0">\n    <version>1.10.0</version>\n'
            '  </pyqgis_plugin>\n  <pyqgis_plugin name="Constructel Bridge" version="1.9.2"/>\n'
            '  <pyqgis_plugin name="Farois — Historique et rollback" version="0.3.0"/>\n</plugins>\n')


def test_latest_published_version():
    assert bd.latest_published_version(XML) == "1.8.4"
    assert bd.latest_published_version("<oops") is None
    assert bd.latest_published_version("<plugins/>") is None


def test_latest_published_version_real_repository_format():
    # Format de plugin-repo/plugins.xml : declaration XML, attribut version,
    # tri numerique (1.10.0 > 1.9.2), autres plugins ignores.
    assert bd.latest_published_version(REAL_XML) == "1.10.0"
    assert bd.latest_published_version(REAL_XML, "Farois — Historique et rollback") == "0.3.0"


def test_version_check_levels():
    c = bd.version_check("1.8.4", "1.9.0")
    assert (c.level, c.message_key, c.action) == ("warning", "diag.version_update", "plugin_manager")
    assert c.params == {"installed": "1.8.4", "latest": "1.9.0"} and c.key == "version"
    assert bd.version_check("1.9.0", "1.9.0").level == "ok"
    u = bd.version_check("1.9.0", None, "timed out")
    assert (u.level, u.message_key, u.params["error"]) == ("warning", "diag.version_unknown", "timed out")


def test_newer_installed_version_is_ok():
    c = bd.version_check("1.9.1", "1.9.0")
    assert (c.level, c.message_key, c.action, c.params) == ("ok", "diag.version_ok", "", {"installed": "1.9.1"})


# --- Extensions recommandees ---------------------------------------------------


def test_plugin_checks():
    rec = [{"id": i, "name": i.upper()} for i in ("a", "b", "c", "d")]
    checks = bd.plugin_checks(rec, {"a", "b", "d"}, {"a", "d"}, {"d": "upgradeable"})
    assert [(c.target, c.level, c.action) for c in checks] == [
        ("a", "ok", ""), ("b", "warning", "activate"), ("c", "warning", "install"), ("d", "warning", "update")]
    assert [c.message_key for c in checks] == [
        "diag.plugin_ok", "diag.plugin_inactive", "diag.plugin_missing", "diag.plugin_update"]
    assert {c.key for c in checks} == {"plugin"} and checks[0].params == {"name": "A"}


def test_plugin_checks_without_installer_cache():
    # Cache de l'installeur indisponible (None) : aucune mise a jour connue.
    rec = [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}]
    checks = bd.plugin_checks(rec, ["a", "b"], ["a"], None)
    assert [(c.level, c.action) for c in checks] == [("ok", ""), ("warning", "activate")]


def test_inactive_upgradeable_plugin_is_activated_first():
    # La mise a jour QGIS ne relance pas une extension desactivee : on l'active d'abord.
    checks = bd.plugin_checks([{"id": "b", "name": "B"}], {"b"}, set(), {"b": "upgradeable"})
    assert checks[0].action == "activate"


def test_plugin_summary_for_the_home_tile():
    # K3 : « extensions 5/6 · 1 a mettre a jour » (tuile Check-in, tache 9).
    rec = [{"id": i, "name": i} for i in "abcdef"]
    checks = bd.plugin_checks(rec, set("abcdef"), set("abcde"), {"e": "upgradeable", "f": "upgradeable"})
    checks.append(bd.identity_check("jdoe", "jdoe", set(), "nomin18", "9i19s56"))
    assert bd.plugin_summary(checks) == bd.PluginSummary(active=5, total=6, updates=1)
    assert bd.plugin_summary([]) == bd.PluginSummary(0, 0, 0)


def test_plugin_version_from_metadata():
    # K3 : version affichee par la tuile Diagnostic, lue comme PLUGIN_VERSION.
    assert bd.plugin_version_from_metadata("[general]\nname=Constructel Bridge\nversion=1.9.0\n") == "1.9.0"
    assert bd.plugin_version_from_metadata("[general]\nname=x\n") == ""
    real = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    assert bd.plugin_version_from_metadata(real) == re.search(r"^version=(.+)$", real, re.M).group(1).strip()


# --- Identifiant nominatif -------------------------------------------------------


def test_identity_check():
    ids = {"nomin18", "9i19s56"}
    assert bd.identity_check("jdoe", "jdoe", ids, "nomin18", "9i19s56").message_key == "diag.identity_ok"
    assert bd.identity_check("jdoe", "jdoe", {"9i19s56"}, "nomin18", "9i19s56").message_key == "diag.identity_no_password"
    assert bd.identity_check("", "jdoe", set(), "nomin18", "9i19s56").message_key == "diag.identity_derived"
    assert bd.identity_check("", "", set(), "nomin18", "9i19s56").level == "error"


def test_identity_check_levels_and_params():
    ok = bd.identity_check("adlogin", "jdoe", ["nomin18", "9i19s56", "x"], "nomin18", "9i19s56")
    assert (ok.key, ok.level, ok.params) == ("identity", "ok", {"login": "adlogin"})
    # Config des couches (9i19s56) absente : mot de passe pas enregistre non plus.
    missing = bd.identity_check("jdoe", "jdoe", {"nomin18"}, "nomin18", "9i19s56")
    assert (missing.level, missing.message_key) == ("warning", "diag.identity_no_password")
    derived = bd.identity_check("", "jdoe", {"nomin18", "9i19s56"}, "nomin18", "9i19s56")
    assert (derived.level, derived.params) == ("warning", {"login": "jdoe"})
    none = bd.identity_check("", "", None, "nomin18", "9i19s56")
    assert (none.message_key, none.params, none.action) == ("diag.identity_none", {}, "")


# --- Serveur : correspondance des issues -------------------------------------------


def test_server_check_mapping():
    ok = bd.server_check("h", 5432, "ok", "")
    assert (ok.key, ok.level, ok.message_key, ok.params) == ("server", "ok", "diag.server_ok", {"host": "h", "port": 5432})
    down = bd.server_check("h", 5432, "unreachable", "timed out")
    assert (down.level, down.message_key, down.params["error"]) == ("error", "diag.server_unreachable", "timed out")
    refused = bd.server_check("h", 5432, "tls_refused", "b'N'")
    assert (refused.level, refused.message_key, refused.params) == (
        "error", "diag.server_tls_refused", {"host": "h", "port": 5432})
    cert = bd.server_check("h", 5432, "cert_invalid", "self-signed")
    assert (cert.level, cert.message_key, cert.params["error"]) == ("error", "diag.server_cert_invalid", "self-signed")


# --- Serveur : sonde sur de vrais sockets --------------------------------------------


def test_probe_server_sends_ssl_request_and_reads_refusal():
    received = []

    def refuse(conn, stop):
        received.append(_recv_exact(conn, 8))
        conn.sendall(b"N")

    with _server(refuse) as port:
        outcome = bd.probe_server("127.0.0.1", port, "/nope.pem", timeout=1.0)
    assert received == [struct.pack("!ii", 8, 80877103)]
    assert outcome == ("tls_refused", "b'N'")


def test_probe_server_silent_server_times_out():           # Review Focus 5
    # Le serveur accepte la connexion TCP puis ne repond jamais.
    with _server(_silent) as port:
        start = time.monotonic()
        outcome = bd.probe_server("127.0.0.1", port, "/nope.pem", timeout=0.5)
        elapsed = time.monotonic() - start
    assert outcome[0] == "unreachable" and outcome[1]
    assert elapsed < 1.0


def test_probe_server_deadline_is_global_fast_tcp_then_slow_answers():   # K9
    # TCP immediat, 'S' apres 0,7 s, puis poignee de main TLS muette : un
    # delai PAR OPERATION (1 s) laisserait la sonde courir ~1,7 s ; l'echeance
    # globale l'arrete a 1 s.
    def slow(conn, stop):
        _recv_exact(conn, 8)
        if not stop.wait(0.7):
            conn.sendall(b"S")
        stop.wait(10)

    with _server(slow) as port:
        start = time.monotonic()
        outcome = bd.probe_server("127.0.0.1", port, REAL_CA_BUNDLE, timeout=1.0)
        elapsed = time.monotonic() - start
    assert outcome[0] == "unreachable"
    assert 0.9 < elapsed < 1.4


def test_probe_server_closed_port():
    outcome = bd.probe_server("127.0.0.1", _free_port(), "/nope.pem", timeout=0.5)
    assert outcome[0] == "unreachable" and outcome[1]


def test_probe_server_closed_connection_is_unreachable():
    def hang_up(conn, stop):
        _recv_exact(conn, 8)

    with _server(hang_up) as port:
        assert bd.probe_server("127.0.0.1", port, "/nope.pem", timeout=1.0)[0] == "unreachable"


def test_probe_server_name_resolution_counts_in_the_deadline(monkeypatch):   # K9
    # getaddrinfo n'a pas de delai : un DNS fige ne doit pas retenir la sonde.
    release = threading.Event()

    def frozen_dns(*_args, **_kwargs):
        release.wait(5)
        raise socket.gaierror("too late")

    monkeypatch.setattr(bd.socket, "getaddrinfo", frozen_dns)
    start = time.monotonic()
    try:
        outcome = bd.probe_server("farois.invalid", 5432, "/nope.pem", timeout=0.3)
    finally:
        release.set()
    assert outcome[0] == "unreachable"
    assert time.monotonic() - start < 0.8


def test_probe_server_valid_certificate_is_ok(pki):
    server_side = []
    with _server(_postgres_tls(pki.server_context, server_side)) as port:
        outcome = bd.probe_server("127.0.0.1", port, pki.ca, timeout=2.0)
    assert outcome == ("ok", "")
    assert server_side == ["ok"]


def test_probe_server_unknown_authority_is_cert_invalid(pki):
    # CA du paquet (Farois / Constructel) : le certificat de test n'en vient pas.
    server_side = []
    with _server(_postgres_tls(pki.server_context, server_side)) as port:
        outcome = bd.probe_server("127.0.0.1", port, REAL_CA_BUNDLE, timeout=2.0)
    assert outcome[0] == "cert_invalid" and outcome[1]


def test_probe_server_checks_the_host_name(pki):
    # Certificat emis pour IP:127.0.0.1 seulement : « localhost » est refuse
    # (verify-full), meme si la connexion aboutit au meme serveur.
    server_side = []
    with _server(_postgres_tls(pki.server_context, server_side)) as port:
        outcome = bd.probe_server("localhost", port, pki.ca, timeout=2.0)
    assert outcome[0] == "cert_invalid"
    assert "localhost" in outcome[1] or "mismatch" in outcome[1].lower()


def test_probe_server_missing_ca_file_is_cert_invalid():
    def accept_tls(conn, stop):
        _recv_exact(conn, 8)
        conn.sendall(b"S")
        conn.recv(1)

    with _server(accept_tls) as port:
        outcome = bd.probe_server("127.0.0.1", port, "/nope.pem", timeout=1.0)
    assert outcome[0] == "cert_invalid" and outcome[1]


# --- Version publiee : lecture de plugins.xml ------------------------------------------


def test_fetch_latest_version_reads_plugins_xml():
    with _server(_http_body(REAL_XML.encode("utf-8"))) as port:
        assert bd.fetch_latest_version(f"http://127.0.0.1:{port}/plugin-repo/plugins.xml", timeout=2.0) == ("1.10.0", "")


def test_fetch_latest_version_unreachable_repository():
    latest, error = bd.fetch_latest_version(f"http://127.0.0.1:{_free_port()}/plugins.xml", timeout=0.5)
    assert latest is None and error


def test_fetch_latest_version_unreadable_answer():
    with _server(_http_body(b"<html>proxy error</html")) as port:
        latest, error = bd.fetch_latest_version(f"http://127.0.0.1:{port}/plugins.xml", timeout=2.0)
    assert latest is None and error
    with _server(_http_body(b"", status="404 Not Found")) as port:
        latest, error = bd.fetch_latest_version(f"http://127.0.0.1:{port}/plugins.xml", timeout=2.0)
    assert latest is None and "404" in error


def test_fetch_latest_version_silent_repository_times_out():
    with _server(_silent) as port:
        start = time.monotonic()
        latest, error = bd.fetch_latest_version(f"http://127.0.0.1:{port}/plugins.xml", timeout=0.5)
        elapsed = time.monotonic() - start
    assert latest is None and error
    assert elapsed < 1.0


def test_fetch_latest_version_deadline_is_global_on_a_slow_body():   # K9
    # En-tetes immediats puis un octet toutes les 50 ms : aucune lecture ne
    # depasse le delai, seule l'echeance globale arrete la lecture.
    def drip(conn, stop):
        _read_http_request(conn)
        conn.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 100000\r\n\r\n<plugins>")
        while not stop.wait(0.05):
            conn.sendall(b" ")

    with _server(drip) as port:
        start = time.monotonic()
        latest, error = bd.fetch_latest_version(f"http://127.0.0.1:{port}/plugins.xml", timeout=0.5)
        elapsed = time.monotonic() - start
    assert latest is None and error
    assert elapsed < 0.9


def test_fetch_ignores_system_proxies_and_the_global_opener(monkeypatch):   # T8-c3
    # Le depot est sur le reseau local : connexion directe, comme le
    # gestionnaire reseau de QGIS par defaut. Ni les variables de proxy (ou le
    # registre WinINET sous Windows), ni un opener installe par une autre
    # extension (install_opener) ne s'appliquent.
    dead_proxy = f"http://127.0.0.1:{_free_port()}"
    for name in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, dead_proxy)
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(urllib.request, "_opener", None)  # un opener global relirait ces proxys
    with _server(_http_body(XML.encode())) as port:
        assert bd.fetch_latest_version(f"http://127.0.0.1:{port}/plugins.xml", timeout=2.0) == ("1.8.4", "")

    class _ForeignOpener:
        def open(self, *_args, **_kwargs):
            raise AssertionError("opener global d'une autre extension utilise")

    monkeypatch.setattr(urllib.request, "_opener", _ForeignOpener())
    with _server(_http_body(XML.encode())) as port:
        assert bd.fetch_latest_version(f"http://127.0.0.1:{port}/plugins.xml", timeout=2.0) == ("1.8.4", "")


def test_run_network_checks_returns_version_then_server(pki):
    server_side = []
    with _server(_http_body(XML.encode())) as http_port, \
            _server(_postgres_tls(pki.server_context, server_side)) as pg_port:
        checks = bd.run_network_checks("127.0.0.1", pg_port, pki.ca, "1.8.4",
                                       url=f"http://127.0.0.1:{http_port}/plugins.xml", timeout=2.0)
    assert [(c.key, c.message_key) for c in checks] == [("version", "diag.version_ok"), ("server", "diag.server_ok")]


def test_run_network_checks_share_one_deadline():
    # Depot et serveur muets : les deux verifications courent en parallele,
    # l'ensemble tient dans le delai d'une seule (pas 2 x 0,6 s).
    with _server(_silent) as http_port, _server(_silent) as pg_port:
        start = time.monotonic()
        checks = bd.run_network_checks("127.0.0.1", pg_port, REAL_CA_BUNDLE, "1.9.0",
                                       url=f"http://127.0.0.1:{http_port}/plugins.xml", timeout=0.6)
        elapsed = time.monotonic() - start
    assert [(c.key, c.level) for c in checks] == [("version", "warning"), ("server", "error")]
    assert elapsed < 1.1


# --- Ordre d'affichage -------------------------------------------------------------


def test_ordered_checks_follow_the_spec_order():
    plugins = bd.plugin_checks([{"id": "a", "name": "A"}, {"id": "b", "name": "B"}], {"a"}, {"a"}, None)
    identity = bd.identity_check("", "jdoe", set(), "nomin18", "9i19s56")
    running = bd.ordered_checks(plugins + [identity], None)
    assert [c.key for c in running] == ["network", "plugin", "plugin", "identity"]
    assert (running[0].level, running[0].message_key) == (bd.LEVEL_RUNNING, "diag.running")
    network = [bd.version_check("1.9.0", "1.9.0"), bd.server_check("h", 1, "ok", "")]
    done = bd.ordered_checks([identity] + plugins, network)
    assert [c.key for c in done] == ["version", "plugin", "plugin", "server", "identity"]
    assert [c.target for c in done if c.key == "plugin"] == ["a", "b"]


# --- Purete --------------------------------------------------------------------------


def test_diagnostic_module_is_pure():
    src = (PLUGIN_DIR / "bridge_diagnostic.py").read_text(encoding="utf-8")
    assert "psycopg2" not in src and "import qgis" not in src and "from qgis" not in src
    assert "from .i18n" not in src and "authManager" not in src


def _fresh_diagnostic_module(monkeypatch):
    """Copie neuve du module (lecture de l'environnement a l'import), sans
    toucher a constructel_bridge.bridge_diagnostic."""
    spec = importlib.util.spec_from_file_location("bridge_diagnostic_copy", PLUGIN_DIR / "bridge_diagnostic.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "bridge_diagnostic_copy", module)  # dataclass : module enregistre
    spec.loader.exec_module(module)
    return module


def test_repository_url_and_timeout(monkeypatch):
    monkeypatch.delenv("CONSTRUCTEL_PLUGIN_REPO_URL", raising=False)
    default = _fresh_diagnostic_module(monkeypatch)
    assert default.PLUGIN_REPO_URL == "http://192.168.160.31:9080/plugin-repo/plugins.xml"
    assert default.NETWORK_TIMEOUT == 3.0
    monkeypatch.setenv("CONSTRUCTEL_PLUGIN_REPO_URL", "http://example.invalid/plugins.xml")
    assert _fresh_diagnostic_module(monkeypatch).PLUGIN_REPO_URL == "http://example.invalid/plugins.xml"


# --- Plugin : statut, menu, Diagnostic hors connexion ----------------------------------


class _RecordingDialog:
    def __init__(self, parent, status_text, local_checks, network_args, on_action):
        self.parent = parent
        self.status_text = status_text
        self.local_checks = local_checks
        self.network_args = network_args
        self.on_action = on_action
        self.executed = 0
        self.script = []  # actions jouees pendant exec()
        self.results = []

    def exec(self):
        self.executed += 1
        for check in self.script:
            self.results.append(self.on_action(check))
        return 0


@pytest.fixture
def dialogs(monkeypatch):
    """Dialogue de Diagnostic remplace par un enregistreur (les widgets Qt
    reels ne tournent pas sur les stubs) ; ``dialogs.script`` = actions que
    l'utilisateur declenche pendant exec()."""
    created = []
    script = []

    class Dialog(_RecordingDialog):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.script = list(script)
            created.append(self)

    fake = types.ModuleType("constructel_bridge.bridge_diagnostic_dialog")
    fake.DiagnosticDialog = Dialog
    monkeypatch.setitem(sys.modules, "constructel_bridge.bridge_diagnostic_dialog", fake)
    created_list = types.SimpleNamespace(created=created, script=script)
    return created_list


class _Iface:
    def __init__(self):
        self.managed = []

    def mainWindow(self):
        return None

    def messageBar(self):
        return types.SimpleNamespace(pushMessage=lambda *a, **k: None)

    def activeLayer(self):
        return None

    def actionManagePlugins(self):
        return types.SimpleNamespace(trigger=lambda: self.managed.append(1))


def _offline_plugin(bp18):
    plugin = bp18.ConstructelBridgePlugin(_Iface())
    plugin._get_qgis_username = lambda: "JDoe"
    plugin._connected = False
    return plugin


def test_status_text_matches_previous_message(bp18, monkeypatch, tmp_path):
    # Session nominative connectee : texte exact de l'ancien « Statut connexion ».
    plugin, _calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], stored_ad_pw="ad-pw")
    _start(plugin)
    assert plugin._connected and plugin._auth_mode == bp18.AUTH_MODE_NOMINAL
    assert plugin._status_text() == "\n".join([
        bp18.tr("status.connected_to", host=bp18.DEFAULT_HOST, port=bp18.DEFAULT_PORT, dbname=bp18.DEFAULT_DBNAME,
                user=LOGIN, bridge_user=plugin._bridge_user, bridge_user_id=plugin._bridge_user_id,
                hooks=plugin._layer_hooks_installed),
        bp18.tr("nominal.mode_nominal", login=LOGIN), plugin._scope_text()])
    plugin._connected = False
    assert plugin._status_text() == bp18.tr("status.not_connected")


def test_status_text_of_a_shared_session(bp18, monkeypatch, tmp_path):
    plugin, _calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [_not_permitted(), None, None],
                                                stored_ad_pw="ad-pw")
    _start(plugin)
    assert plugin._connected and plugin._auth_mode == "shared"
    assert plugin._status_text() == "\n".join([
        bp18.tr("status.connected_to", host=bp18.DEFAULT_HOST, port=bp18.DEFAULT_PORT, dbname=bp18.DEFAULT_DBNAME,
                user=bp18.DEFAULT_USER, bridge_user=plugin._bridge_user, bridge_user_id=plugin._bridge_user_id,
                hooks=plugin._layer_hooks_installed),
        bp18.tr("nominal.mode_shared", user=bp18.DEFAULT_USER), plugin._scope_text()])


def test_old_status_message_box_is_gone(bp18):
    assert not hasattr(bp18.ConstructelBridgePlugin, "_on_status")


def test_diagnostic_opens_offline_with_local_checks(bp18, onb, dialogs, monkeypatch):  # noqa: F811
    plugin = _offline_plugin(bp18)
    plugin._on_diagnostic()
    assert len(dialogs.created) == 1 and dialogs.created[0].executed == 1
    dialog = dialogs.created[0]
    assert [c.key for c in dialog.local_checks] == ["plugin"] * 6 + ["identity"]
    assert [c.target for c in dialog.local_checks[:6]] == [p["id"] for p in onb.RECOMMENDED_PLUGINS]
    assert dialog.status_text == bp18.tr("status.not_connected")
    assert dialog.network_args == {
        "host": bp18.DEFAULT_HOST, "port": bp18.DEFAULT_PORT,
        "cafile": str(bp18.ca_bundle_path(PLUGIN_DIR)), "installed_version": bp18.PLUGIN_VERSION}
    assert dialog.on_action == plugin._run_diagnostic_action


def test_local_checks_read_plugins_installer_cache_and_auth_ids(bp18, onb, monkeypatch):  # noqa: F811
    from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

    rec = [p["id"] for p in onb.RECOMMENDED_PLUGINS]
    onb.utils.available_plugins = rec[:5]
    onb.utils.active_plugins = rec[:4]
    package = types.ModuleType("pyplugin_installer")
    package.__path__ = []
    data = types.ModuleType("pyplugin_installer.installer_data")
    data.plugins = types.SimpleNamespace(all=lambda: {rec[0]: {"status": "upgradeable"}, rec[1]: {"status": "installed"}})
    package.installer_data = data
    monkeypatch.setitem(sys.modules, "pyplugin_installer", package)
    monkeypatch.setitem(sys.modules, "pyplugin_installer.installer_data", data)
    QgsSettings().setValue("constructel_bridge/pg_login", "CONSTRUCTEL\\AdLogin")
    for cfg_id in ("nomin18", "9i19s56"):
        cfg = QgsAuthMethodConfig("Basic")
        cfg.setId(cfg_id)
        cfg.setName(cfg_id)
        assert QgsApplication.authManager().storeAuthenticationConfig(cfg)[0]

    checks = _offline_plugin(bp18)._diagnostic_local_checks()

    assert [(c.target, c.action) for c in checks[:6]] == [
        (rec[0], "update"), (rec[1], ""), (rec[2], ""), (rec[3], ""), (rec[4], "activate"), (rec[5], "install")]
    assert (checks[6].message_key, checks[6].params) == ("diag.identity_ok", {"login": "adlogin"})
    assert bd.plugin_summary(checks) == bd.PluginSummary(active=4, total=6, updates=1)


def test_local_checks_without_installer_cache_nor_memorized_login(bp18, onb):  # noqa: F811
    # pyplugin_installer factice sans installer_data : statuts inconnus.
    checks = _offline_plugin(bp18)._diagnostic_local_checks()
    assert {c.action for c in checks[:6]} == {"install"}
    assert (checks[6].message_key, checks[6].params) == ("diag.identity_derived", {"login": "jdoe"})


class _Boom:
    def __init__(self, what):
        self.what = what

    def __call__(self, *_args, **_kwargs):
        raise AssertionError(f"le Diagnostic ne doit pas {self.what}")


def test_diagnostic_never_opens_a_session_nor_reads_secrets(bp18, onb, dialogs, monkeypatch):  # noqa: F811
    from qgis.core import _StubAuthManager

    psycopg2 = types.ModuleType("psycopg2")
    psycopg2.connect = _Boom("ouvrir de session PostgreSQL")
    psycopg2.Error = Exception
    monkeypatch.setitem(sys.modules, "psycopg2", psycopg2)
    for name in ("loadAuthenticationConfig", "availableAuthMethodConfigs", "setMasterPassword",
                 "masterPasswordIsSet", "updateAuthenticationConfig", "storeAuthenticationConfig"):
        monkeypatch.setattr(_StubAuthManager, name, _Boom(f"lire un secret ({name})"))
    for name in ("_retrieve_password_encrypted", "_stored_login", "_ensure_auth_manager_ready"):
        monkeypatch.setattr(bp18, name, _Boom(f"appeler {name}"))
    plugin = _offline_plugin(bp18)
    for name in ("_connect_nominal_or_fallback", "_auto_connect", "_on_connect", "_ask_password"):
        monkeypatch.setattr(plugin, name, _Boom(f"appeler {name}"))
    dialogs.script.extend([bd.Check("plugin", "warning", "diag.plugin_inactive", {"name": "B"}, "activate", "b"),
                           bd.Check("version", "warning", "diag.version_update", {}, "plugin_manager")])

    plugin._on_diagnostic()

    assert len(dialogs.created[0].results) == 2
    assert onb.started == ["b"]


def test_diagnostic_network_part_never_touches_postgresql(monkeypatch):
    # Sonde reelle sur un serveur local, psycopg2 piege : la sonde parle le
    # protocole PostgreSQL a la main (SSLRequest), sans login.
    psycopg2 = types.ModuleType("psycopg2")
    psycopg2.connect = _Boom("ouvrir de session PostgreSQL")
    monkeypatch.setitem(sys.modules, "psycopg2", psycopg2)
    with _server(_silent) as port:
        checks = bd.run_network_checks("127.0.0.1", port, REAL_CA_BUNDLE, "1.9.0",
                                       url=f"http://127.0.0.1:{_free_port()}/plugins.xml", timeout=0.3)
    assert [c.key for c in checks] == ["version", "server"]


def test_status_menu_entry_opens_diagnostic(bp18, monkeypatch):
    iface = _initgui_ready(bp18, monkeypatch)
    plugin = bp18.ConstructelBridgePlugin(iface)
    plugin.initGui()
    status = next(a for a in plugin._actions if a.text() == bp18.tr("menu.status"))
    assert status.triggered._slots == [plugin._on_diagnostic]


def test_status_menu_label_in_three_languages():
    from constructel_bridge.i18n.translations import TRANSLATIONS

    assert TRANSLATIONS["fr"]["menu.status"] == "Statut et diagnostic"
    assert TRANSLATIONS["en"]["menu.status"] == "Status and diagnostics"
    assert TRANSLATIONS["pt"]["menu.status"] == "Estado e diagnóstico"
    assert TRANSLATIONS["fr"]["diag.running"] == "Vérification en cours…"


# --- Plugin : actions du Diagnostic (K12 : un seul chemin d'installation) ----------------


def test_install_actions_share_one_installer_session(bp18, onb, dialogs):  # noqa: F811
    rec = [p["id"] for p in onb.RECOMMENDED_PLUGINS]
    dialogs.script.extend([bd.Check("plugin", "warning", "diag.plugin_missing", {}, "install", rec[0]),
                           bd.Check("plugin", "warning", "diag.plugin_missing", {}, "install", rec[1])])
    plugin = _offline_plugin(bp18)

    plugin._on_diagnostic()

    assert [c for c in onb.calls if c[0] == "fetch"] == [("fetch", False)]
    assert [c for c in onb.calls if c[0] == "install"] == [("install", rec[0]), ("install", rec[1])]
    # Verifications locales recalculees apres chaque action : installee, pas encore active.
    first, second = dialogs.created[0].results
    assert [c.action for c in first[:2]] == ["activate", "install"]
    assert [c.action for c in second[:2]] == ["activate", "activate"]
    assert plugin._diagnostic_session is None  # session limitee a une execution


def test_update_action_upgrades_through_install_or_activate_plugin(bp18, onb, monkeypatch):  # noqa: F811
    seen = []
    monkeypatch.setattr(onb, "install_or_activate_plugin",
                        lambda pid, upgrade=False, session=None: seen.append((pid, upgrade, session)) or "updated")
    plugin = _offline_plugin(bp18)
    checks = plugin._run_diagnostic_action(bd.Check("plugin", "warning", "diag.plugin_update", {}, "update", "a"))
    plugin._run_diagnostic_action(bd.Check("plugin", "warning", "diag.plugin_inactive", {}, "activate", "b"))
    assert [(pid, upgrade) for pid, upgrade, _s in seen] == [("a", True), ("b", False)]
    assert all(isinstance(s, onb.PluginInstallerSession) for _p, _u, s in seen)
    assert [c.key for c in checks] == ["plugin"] * 6 + ["identity"]


def test_activation_is_remembered_after_a_qgis_restart(bp18, onb):  # noqa: F811
    # T8-I2 : comme le gestionnaire d'extensions de QGIS, « Activer » ecrit
    # PythonPlugins/<id> = True ; sinon l'extension redevient desactivee au
    # prochain lancement et le Diagnostic la signale encore.
    from qgis.core import QgsSettings

    plugin = _offline_plugin(bp18)
    plugin._run_diagnostic_action(bd.Check("plugin", "warning", "diag.plugin_inactive", {}, "activate", "b"))
    assert onb.started == ["b"]
    assert QgsSettings().value("PythonPlugins/b") is True


def test_failed_start_is_not_remembered(onb, monkeypatch):  # noqa: F811
    from qgis.core import QgsSettings

    monkeypatch.setattr(onb, "startPlugin", lambda pid: False)
    with pytest.raises(RuntimeError):  # M4 : demarrage refuse = echec
        onb.install_or_activate_plugin("b")
    assert QgsSettings().value("PythonPlugins/b") is None


def test_refused_start_is_reported_by_the_diagnostic(bp18, onb, monkeypatch):  # noqa: F811
    # Relecture finale M4 : « Activer » dont startPlugin rend False affiche
    # l'erreur de l'extension, et le reglage PythonPlugins n'est pas ecrit.
    from qgis.core import QgsSettings

    shown = []
    monkeypatch.setattr(bp18.QMessageBox, "warning", lambda *a, **k: shown.append(a[2]), raising=False)
    monkeypatch.setattr(onb, "startPlugin", lambda pid: False)
    with pytest.raises(RuntimeError) as refused:
        onb.install_or_activate_plugin("b")
    plugin = _offline_plugin(bp18)

    checks = plugin._run_diagnostic_action(bd.Check("plugin", "warning", "diag.plugin_inactive", {}, "activate", "b"))

    assert shown == [bp18.tr("onboard.action.plugin_error", pid="b", error=str(refused.value))]
    assert QgsSettings().value("PythonPlugins/b") is None
    assert len(checks) == 7


def test_installed_and_started_plugin_is_remembered(onb, monkeypatch):  # noqa: F811
    from qgis.core import QgsSettings

    install = onb.installer.installPlugin

    def install_and_start(pid):  # QGIS demarre l'extension qu'il vient d'installer
        install(pid)
        onb.utils.active_plugins = onb.utils.active_plugins + [pid]

    monkeypatch.setattr(onb.installer, "installPlugin", install_and_start)
    assert onb.install_or_activate_plugin("c") == "installed"
    assert QgsSettings().value("PythonPlugins/c") is True


def test_installed_but_not_started_plugin_is_not_remembered(onb):  # noqa: F811
    from qgis.core import QgsSettings

    assert onb.install_or_activate_plugin("c") == "installed"  # disponible, pas demarree
    assert QgsSettings().value("PythonPlugins/c") is None


def test_plugin_manager_action_opens_qgis_plugin_manager(bp18, onb):  # noqa: F811
    plugin = _offline_plugin(bp18)
    checks = plugin._run_diagnostic_action(bd.Check("version", "warning", "diag.version_update", {}, "plugin_manager"))
    assert plugin.iface.managed == [1]
    assert len(checks) == 7


def test_failed_install_is_reported_and_checks_are_refreshed(bp18, onb, monkeypatch):  # noqa: F811
    shown = []
    monkeypatch.setattr(bp18.QMessageBox, "warning", lambda *a, **k: shown.append(a[2]), raising=False)
    onb.installer.silent.add("qfieldsync")
    plugin = _offline_plugin(bp18)

    checks = plugin._run_diagnostic_action(bd.Check("plugin", "warning", "diag.plugin_missing", {}, "install", "qfieldsync"))

    assert len(shown) == 1 and shown[0].startswith(bp18.tr("onboard.action.plugin_error", pid="qfieldsync", error="")[:12])
    assert "qfieldsync" in shown[0]
    assert next(c for c in checks if c.target == "qfieldsync").action == "install"


def test_unavailable_installer_is_reported(bp18, onb, monkeypatch):  # noqa: F811
    shown = []
    monkeypatch.setattr(bp18.QMessageBox, "warning", lambda *a, **k: shown.append(a[2]), raising=False)
    monkeypatch.setitem(sys.modules, "pyplugin_installer", None)
    plugin = _offline_plugin(bp18)

    plugin._run_diagnostic_action(bd.Check("plugin", "warning", "diag.plugin_missing", {}, "install", "qfieldsync"))

    assert shown == [bp18.tr("onboard.action.installer_unavailable",
                             error="import of pyplugin_installer halted; None in sys.modules")]


# --- Dialogue sur doublures (widgets et QgsTask) ------------------------------------------


class _Sig:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class _W:
    def __init__(self, *args, **_kwargs):
        self.args = args
        self.enabled = True
        self.hidden = False
        self.deleted = False
        self.layout = None
        self.style = ""

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def setMinimumWidth(self, *_a):
        pass

    def setWindowTitle(self, title):
        self.title = title

    def setStyleSheet(self, style):
        self.style = style

    def hide(self):
        self.hidden = True

    def deleteLater(self):
        self.deleted = True


class _Dialog(_W):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.result = None

    def done(self, result):
        self.result = result

    def reject(self):
        self.done(0)

    def exec(self):
        return 0


class _Label(_W):
    def __init__(self, text="", *args):
        super().__init__(*args)
        self._text = text

    def text(self):
        return self._text

    def setWordWrap(self, *_a):
        pass

    def setTextFormat(self, *_a):
        pass


class _Button(_W):
    def __init__(self, text="", *args):
        super().__init__(*args)
        self._text = text
        self.clicked = _Sig()

    def text(self):
        return self._text


class _ButtonBox(_W):
    class StandardButton:
        Close = 0x00200000

    def __init__(self, *args):
        super().__init__(*args)
        self.rejected = _Sig()


class _Layout:
    def __init__(self, parent=None):
        self.items = []
        self.cells = {}
        if parent is not None:
            parent.layout = self

    def addWidget(self, widget, *position):
        self.items.append(widget)
        if position:
            self.cells[tuple(position[:2])] = widget

    def replaceWidget(self, old, new, *_a):
        self.items[self.items.index(old)] = new

    def setColumnStretch(self, *_a):
        pass


class _Task:
    @staticmethod
    def fromFunction(description, function, *args, on_finished=None, **kwargs):
        task = _Task()
        task.description, task.function, task.args, task.kwargs = description, function, args, kwargs
        task.on_finished = on_finished
        return task


@pytest.fixture
def dlg(bp18, monkeypatch):
    """bridge_diagnostic_dialog importe sur des doublures de widgets, de
    QgsTask et du gestionnaire de taches (``dlg.tasks``)."""
    from qgis import core
    from qgis.PyQt import QtCore, QtWidgets

    tasks = []
    monkeypatch.setattr(core, "QgsTask", _Task, raising=False)
    monkeypatch.setattr(core.QgsApplication, "taskManager",
                        staticmethod(lambda: types.SimpleNamespace(addTask=tasks.append)), raising=False)
    for name, fake in (("QDialog", _Dialog), ("QLabel", _Label), ("QPushButton", _Button),
                       ("QDialogButtonBox", _ButtonBox), ("QWidget", _W), ("QVBoxLayout", _Layout),
                       ("QGridLayout", _Layout)):
        monkeypatch.setattr(QtWidgets, name, fake, raising=False)
    monkeypatch.setattr(QtCore.Qt, "TextFormat", types.SimpleNamespace(PlainText=0), raising=False)
    monkeypatch.delitem(sys.modules, "constructel_bridge.bridge_diagnostic_dialog", raising=False)
    module = importlib.import_module("constructel_bridge.bridge_diagnostic_dialog")
    module.tasks = tasks
    yield module
    sys.modules.pop("constructel_bridge.bridge_diagnostic_dialog", None)


NET_ARGS = {"host": "farois.test", "port": 5432, "cafile": "/ca.pem", "installed_version": "1.9.0"}
LOCAL = [bd.Check("plugin", "warning", "diag.plugin_missing", {"name": "QField Sync"}, "install", "qfieldsync"),
         bd.Check("identity", "ok", "diag.identity_ok", {"login": "jdoe"})]


def _rows(dialog):
    """[(symbole, message, libelle d'action ou "")] des lignes affichees."""
    cells = dialog._rows.layout.cells
    count = 1 + max(row for row, _col in cells)
    return [(cells[(r, 0)].text(), cells[(r, 1)].text(), cells[(r, 2)].text() if (r, 2) in cells else "")
            for r in range(count)]


def test_dialog_shows_local_checks_and_runs_network_checks_in_a_task(dlg):
    dialog = dlg.DiagnosticDialog(None, "Non connecte.", LOCAL, NET_ARGS, lambda c: LOCAL)
    assert dialog.title == dlg.tr("diag.title")
    assert len(dlg.tasks) == 1 and dialog._task is dlg.tasks[0]   # reference gardee
    task = dlg.tasks[0]
    assert task.kwargs == {"network_args": NET_ARGS} and task.on_finished == dialog._on_network_done
    assert [r[1] for r in _rows(dialog)] == [
        dlg.tr("diag.running"), dlg.tr("diag.plugin_missing", name="QField Sync"), dlg.tr("diag.identity_ok", login="jdoe")]
    assert _rows(dialog)[1][2] == dlg.tr("diag.action_install")


def test_task_function_runs_the_network_checks_off_the_ui(dlg, monkeypatch):
    seen = []
    monkeypatch.setattr(dlg, "run_network_checks", lambda **kw: seen.append(kw) or ["checks"])
    dlg.DiagnosticDialog(None, "", LOCAL, NET_ARGS, lambda c: LOCAL)
    task = dlg.tasks[0]
    assert task.function(task, *task.args, **task.kwargs) == ["checks"]
    assert seen == [NET_ARGS]


def test_network_result_is_shown_in_the_spec_order(dlg):
    dialog = dlg.DiagnosticDialog(None, "", LOCAL, NET_ARGS, lambda c: LOCAL)
    old_rows = dialog._rows
    dialog._on_network_done(None, [bd.version_check("1.9.0", "1.9.1"), bd.server_check("farois.test", 5432, "ok", "")])
    rows = _rows(dialog)
    assert [r[1] for r in rows] == [
        dlg.tr("diag.version_update", installed="1.9.0", latest="1.9.1"),
        dlg.tr("diag.plugin_missing", name="QField Sync"),
        dlg.tr("diag.server_ok", host="farois.test", port=5432),
        dlg.tr("diag.identity_ok", login="jdoe")]
    assert rows[0][2] == dlg.tr("diag.action_plugin_manager")
    assert old_rows.hidden and old_rows.deleted and dialog._rows is not old_rows


def test_result_is_ignored_once_the_dialog_is_closed(dlg):
    dialog = dlg.DiagnosticDialog(None, "", LOCAL, NET_ARGS, lambda c: LOCAL)
    rows = dialog._rows
    dialog.reject()
    dialog._on_network_done(None, [bd.version_check("1.9.0", "1.9.0"), bd.server_check("h", 1, "ok", "")])
    assert dialog._rows is rows and _rows(dialog)[0][1] == dlg.tr("diag.running")


def test_failed_or_cancelled_task_shows_both_network_checks_failed(dlg):
    dialog = dlg.DiagnosticDialog(None, "", LOCAL, NET_ARGS, lambda c: LOCAL)
    dialog._on_network_done(Exception("Task canceled"))   # QgsTaskWrapper : on_finished(exception) sans resultat
    rows = _rows(dialog)
    assert rows[0][1] == dlg.tr("diag.version_unknown", installed="1.9.0", error="Task canceled")
    assert rows[2][1] == dlg.tr("diag.server_unreachable", host="farois.test", port=5432, error="Task canceled")


def test_action_button_runs_on_action_and_redraws_local_checks(dlg):
    calls = []
    refreshed = [bd.Check("plugin", "warning", "diag.plugin_inactive", {"name": "QField Sync"}, "activate", "qfieldsync"),
                 LOCAL[1]]
    dialog = dlg.DiagnosticDialog(None, "", LOCAL, NET_ARGS, lambda c: calls.append(c) or refreshed)
    button = dialog._rows.layout.cells[(1, 2)]
    button.clicked.emit(False)
    assert calls == [LOCAL[0]]
    assert _rows(dialog)[1][1:] == (dlg.tr("diag.plugin_inactive", name="QField Sync"), dlg.tr("diag.action_activate"))
    assert dialog.enabled is True


def test_network_result_during_an_action_is_drawn_after_it(dlg):
    # Installation (fetch de l'installeur) ou gestionnaire d'extensions :
    # boucle d'evenements imbriquee. Le resultat reseau qui arrive pendant
    # l'action ne doit pas detruire les lignes (bouton en cours de clic).
    holder = {}

    def on_action(check):
        dialog = holder["dialog"]
        rows = dialog._rows
        dialog._on_network_done(None, [bd.version_check("1.9.0", "1.9.0"), bd.server_check("h", 1, "ok", "")])
        assert dialog._rows is rows and not rows.deleted
        return LOCAL

    holder["dialog"] = dialog = dlg.DiagnosticDialog(None, "", LOCAL, NET_ARGS, on_action)
    dialog._rows.layout.cells[(1, 2)].clicked.emit(False)
    assert [r[1] for r in _rows(dialog)][0::2] == [
        dlg.tr("diag.version_ok", installed="1.9.0"), dlg.tr("diag.server_ok", host="h", port=1)]


def test_task_is_named_after_the_diagnostic(dlg):
    dlg.DiagnosticDialog(None, "", LOCAL, NET_ARGS, lambda c: LOCAL)
    assert dlg.tasks[0].description == dlg.tr("diag.title")


def test_every_message_key_has_a_literal_translation(dlg):
    # K11 : chaque message_key produit par bridge_diagnostic a son tr("...")
    # litteral dans le dialogue (sinon la cle brute serait affichee).
    src = (PLUGIN_DIR / "bridge_diagnostic.py").read_text(encoding="utf-8")
    keys = set(re.findall(r'"(diag\.[a-z_]+)"', src))
    assert keys == {
        "diag.running", "diag.version_ok", "diag.version_update", "diag.version_unknown",
        "diag.plugin_ok", "diag.plugin_update", "diag.plugin_inactive", "diag.plugin_missing",
        "diag.server_ok", "diag.server_unreachable", "diag.server_tls_refused", "diag.server_cert_invalid",
        "diag.identity_ok", "diag.identity_no_password", "diag.identity_derived", "diag.identity_none"}
    params = {"installed": "1.9.0", "latest": "1.9.1", "error": "e", "name": "N", "host": "h", "port": 1, "login": "l"}
    for key in keys:
        text = dlg.check_message(bd.Check("x", "ok", key, params))
        assert text != key and text == dlg.tr(key, **params), key
    for action in ("install", "update", "activate", "plugin_manager"):
        assert dlg.action_label(action) and dlg.action_label(action) != action
    assert dlg.action_label("") == ""


def test_dialog_module_uses_literal_keys_only():
    src = (PLUGIN_DIR / "bridge_diagnostic_dialog.py").read_text(encoding="utf-8")
    assert not re.search(r"\btr\(\s*f[\"']", src) and not re.search(r"\btr\(\s*[a-z_]", src)

