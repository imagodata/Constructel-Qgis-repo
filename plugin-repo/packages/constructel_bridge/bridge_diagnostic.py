# -*- coding: utf-8 -*-
"""
Constructel Bridge - Diagnostic du poste (1.9.0, spec 2026-11-12 § 6.6, D13).

Logique PURE (ni QGIS, ni pilote PostgreSQL, ni texte traduit) : chaque
verification rend un ``Check`` (niveau, cle de message, parametres, action) ;
le dialogue traduit la cle par un appel tr litteral (K11).

Quatre verifications, toutes utilisables SANS connexion :
  1. version du plugin comparee a plugins.xml du depot Constructel ;
  2. extensions recommandees installees, activees et a jour ;
  3. acces au serveur Farois : TCP, SSLRequest PostgreSQL, poignee de main
     TLS verifiee par la CA du paquet, nom d'hote verifie -- AUCUN login,
     aucune session PostgreSQL, aucun bind AD ;
  4. identifiant nominatif configure (login memorise, configs Auth Manager
     presentes -- leurs identifiants seulement, jamais leur contenu).

Les verifications reseau (1 et 3) ont chacune une ECHEANCE GLOBALE
(``time.monotonic()``, K9) : un connect rapide suivi d'une reponse lente
finit quand meme dans le delai.
"""

from __future__ import annotations

import functools
import os
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from xml.etree import ElementTree

LEVEL_OK, LEVEL_WARNING, LEVEL_ERROR = "ok", "warning", "error"
# Ligne d'attente des verifications reseau (affichage seulement).
LEVEL_RUNNING = "running"

PLUGIN_REPO_URL = os.environ.get(
    "CONSTRUCTEL_PLUGIN_REPO_URL", "http://192.168.160.31:9080/plugin-repo/plugins.xml"
)
PLUGIN_NAME = "Constructel Bridge"
NETWORK_TIMEOUT = 3.0

# Opener DEDIE, sans proxy (T8-c3) : l'opener global d'urllib lit getproxies()
# (environnement, registre WinINET sous Windows) une fois pour toutes et peut
# avoir ete remplace par une autre extension (install_opener). Le depot
# Constructel est sur le reseau local : connexion directe, comme le
# gestionnaire reseau de QGIS par defaut.
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# Premier message du protocole PostgreSQL pour demander TLS (longueur 8,
# code 80877103) : le serveur repond 'S' (TLS accepte) ou 'N'.
SSL_REQUEST = struct.pack("!ii", 8, 80877103)


@dataclass(frozen=True)
class Check:
    key: str             # "version" | "plugin" | "server" | "identity"
    level: str
    message_key: str
    params: dict = field(default_factory=dict)
    action: str = ""     # "" | "plugin_manager" | "install" | "update" | "activate"
    target: str = ""     # identifiant d'extension


RUNNING_CHECK = Check("network", LEVEL_RUNNING, "diag.running")


# --- Version du plugin -----------------------------------------------------------


def _version_parts(version: str) -> list[int]:
    return [int(p) if p.isascii() and p.isdigit() else 0 for p in (version or "").strip().split(".")]


def compare_versions(a: str, b: str) -> int:
    """-1, 0 ou 1. Parties numeriques comparees une a une ; partie manquante
    = 0, partie non numerique (« 0-beta ») = 0."""
    pa, pb = _version_parts(a), _version_parts(b)
    width = max(len(pa), len(pb))
    pa += [0] * (width - len(pa))
    pb += [0] * (width - len(pb))
    return (pa > pb) - (pa < pb)


def latest_published_version(xml_text: str, plugin_name: str = PLUGIN_NAME) -> str | None:
    """Plus grande version publiee de *plugin_name* dans plugins.xml
    (attribut ``version`` des ``pyqgis_plugin``) ; None si illisible ou absent."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return None
    versions = [
        node.get("version", "") for node in root.iter("pyqgis_plugin") if node.get("name") == plugin_name
    ]
    versions = [v for v in versions if v]
    if not versions:
        return None
    return max(versions, key=functools.cmp_to_key(compare_versions))


def version_check(installed: str, latest: str | None, error: str = "") -> Check:
    if latest is None:
        return Check("version", LEVEL_WARNING, "diag.version_unknown", {"installed": installed, "error": error})
    if compare_versions(installed, latest) < 0:
        return Check("version", LEVEL_WARNING, "diag.version_update",
                     {"installed": installed, "latest": latest}, action="plugin_manager")
    return Check("version", LEVEL_OK, "diag.version_ok", {"installed": installed})


def plugin_version_from_metadata(metadata_text: str) -> str:
    """Version declaree par metadata.txt (``version=``), "" si absente.
    Source de PLUGIN_VERSION (tuile Diagnostic de l'accueil, K3)."""
    for line in metadata_text.splitlines():
        if line.startswith("version="):
            return line.strip().split("=", 1)[1]
    return ""


# --- Extensions recommandees -------------------------------------------------------


def plugin_checks(recommended, available, active, statuses) -> list[Check]:
    """Un Check par extension de *recommended* (``{"id", "name"}``).
    *statuses* : ``{id: statut}`` du cache de l'installeur QGIS (« upgradeable »
    = mise a jour connue), None s'il est indisponible. Absente -> installer ;
    desactivee -> activer (la mise a jour QGIS ne relance pas une extension
    desactivee) ; mise a jour connue -> mettre a jour."""
    available, active, statuses = set(available), set(active), statuses or {}
    checks = []
    for plugin in recommended:
        pid, params = plugin["id"], {"name": plugin["name"]}
        if pid not in available:
            checks.append(Check("plugin", LEVEL_WARNING, "diag.plugin_missing", params, "install", pid))
        elif pid not in active:
            checks.append(Check("plugin", LEVEL_WARNING, "diag.plugin_inactive", params, "activate", pid))
        elif statuses.get(pid) == "upgradeable":
            checks.append(Check("plugin", LEVEL_WARNING, "diag.plugin_update", params, "update", pid))
        else:
            checks.append(Check("plugin", LEVEL_OK, "diag.plugin_ok", params, target=pid))
    return checks


@dataclass(frozen=True)
class PluginSummary:
    active: int    # extensions recommandees installees et activees
    total: int     # extensions recommandees
    updates: int   # extensions actives dont une mise a jour est connue


def plugin_summary(checks) -> PluginSummary:
    """Resume des Check « plugin » (les autres sont ignores) pour la tuile
    Check-in de l'accueil (K3) : « extensions 5/6 · 1 a mettre a jour »."""
    plugins = [c for c in checks if c.key == "plugin"]
    updates = sum(1 for c in plugins if c.action == "update")
    active = sum(1 for c in plugins if c.level == LEVEL_OK) + updates
    return PluginSummary(active, len(plugins), updates)


# --- Identifiant nominatif ------------------------------------------------------------


def identity_check(memorized_login: str, derived_login: str, config_ids, ad_cfg_id: str, wyre_cfg_id: str) -> Check:
    """*memorized_login* : login valide lors d'une connexion (QgsSettings) ;
    *derived_login* : login deduit du nom d'utilisateur du poste ;
    *config_ids* : identifiants Auth Manager (configIds(), sans mot de passe
    maitre). Le mot de passe est enregistre si le mot de passe AD (*ad_cfg_id*)
    ET la config des couches (*wyre_cfg_id*) existent."""
    ids = set(config_ids or ())
    if memorized_login:
        params = {"login": memorized_login}
        if ad_cfg_id in ids and wyre_cfg_id in ids:
            return Check("identity", LEVEL_OK, "diag.identity_ok", params)
        return Check("identity", LEVEL_WARNING, "diag.identity_no_password", params)
    if derived_login:
        return Check("identity", LEVEL_WARNING, "diag.identity_derived", {"login": derived_login})
    return Check("identity", LEVEL_ERROR, "diag.identity_none")


# --- Echeance globale (K9) -----------------------------------------------------------


class _Deadline:
    def __init__(self, timeout: float):
        self._end = time.monotonic() + timeout

    def left(self) -> float:
        return max(0.0, self._end - time.monotonic())

    def remaining(self) -> float:
        """Temps restant, socket.timeout si l'echeance est passee : a donner
        a settimeout() avant CHAQUE operation bloquante."""
        left = self._end - time.monotonic()
        if left <= 0:
            raise socket.timeout("timed out")
        return left


def _call_before(deadline: _Deadline, function, *args):
    """function(*args) dans un fil d'appoint, abandonne a l'echeance
    (socket.timeout) : getaddrinfo et urlopen n'ont pas d'echeance globale.
    Le fil abandonne finit seul (ses propres operations ont un delai)."""
    box = {}

    def work():
        try:
            box["value"] = function(*args)
        except BaseException as exc:  # noqa: BLE001 -- relevee chez l'appelant
            box["error"] = exc

    worker = threading.Thread(target=work, name="constructel-bridge-diagnostic", daemon=True)
    worker.start()
    worker.join(deadline.left())
    if worker.is_alive():
        raise socket.timeout("timed out")
    if "error" in box:
        raise box["error"]
    return box["value"]


def _error_text(exc: BaseException) -> str:
    return getattr(exc, "verify_message", "") or str(exc) or exc.__class__.__name__


# --- Serveur Farois -------------------------------------------------------------------


def _connect(host: str, port: int, deadline: _Deadline) -> socket.socket:
    addresses = _call_before(deadline, socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
    error = None
    for family, socktype, proto, _name, address in addresses:
        sock = socket.socket(family, socktype, proto)
        try:
            sock.settimeout(deadline.remaining())
            sock.connect(address)
            return sock
        except OSError as exc:
            sock.close()
            error = exc
    raise error if error is not None else OSError(f"no address for {host}")


def probe_server(host: str, port: int, cafile: str, timeout: float = NETWORK_TIMEOUT) -> tuple[str, str]:
    """Sonde SANS authentification : TCP, SSLRequest PostgreSQL, poignee de
    main TLS verifiee par *cafile* avec le nom d'hote (verify-full). Le
    socket est ferme avant tout message de demarrage : aucun login transmis.

    Rend (issue, detail), issue parmi "ok", "unreachable", "tls_refused",
    "cert_invalid". *timeout* est une echeance GLOBALE (K9)."""
    deadline = _Deadline(timeout)
    sock = None
    try:
        try:
            sock = _connect(host, port, deadline)
            sock.settimeout(deadline.remaining())
            sock.sendall(SSL_REQUEST)
            sock.settimeout(deadline.remaining())
            answer = sock.recv(1)
        except (OSError, ValueError) as exc:  # ValueError : nom d'hote invalide (idna)
            return "unreachable", _error_text(exc)
        if answer == b"":
            return "unreachable", "connection closed by the server"
        if answer != b"S":
            return "tls_refused", repr(answer)
        try:
            context = ssl.create_default_context(cafile=cafile)  # CERT_REQUIRED, check_hostname
        except OSError as exc:  # CA du paquet absente ou illisible (ssl.SSLError compris)
            return "cert_invalid", _error_text(exc)
        try:
            sock = context.wrap_socket(sock, server_hostname=host, do_handshake_on_connect=False)
            sock.settimeout(deadline.remaining())
            sock.do_handshake()
        except ssl.SSLCertVerificationError as exc:
            return "cert_invalid", _error_text(exc)
        except (OSError, ValueError) as exc:
            return "unreachable", _error_text(exc)
        return "ok", ""
    finally:
        if sock is not None:
            sock.close()


def server_check(host: str, port: int, outcome: str, detail: str) -> Check:
    params = {"host": host, "port": port}
    if outcome == "ok":
        return Check("server", LEVEL_OK, "diag.server_ok", params)
    if outcome == "tls_refused":
        return Check("server", LEVEL_ERROR, "diag.server_tls_refused", params)
    if outcome == "cert_invalid":
        return Check("server", LEVEL_ERROR, "diag.server_cert_invalid", {**params, "error": detail})
    return Check("server", LEVEL_ERROR, "diag.server_unreachable", {**params, "error": detail})


# --- Depot Constructel -----------------------------------------------------------------


def _read_url(url: str, deadline: _Deadline) -> str:
    try:
        response = _DIRECT_OPENER.open(url, timeout=deadline.remaining())
    except urllib.error.HTTPError as exc:
        exc.close()  # HTTPError (404...) garde la reponse, et son socket, ouverte
        raise
    with response:
        read = getattr(response, "read1", response.read)
        chunks = []
        while True:
            deadline.remaining()  # corps servi au compte-gouttes : arret a l'echeance
            chunk = read(65536)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


def fetch_latest_version(url: str = PLUGIN_REPO_URL, timeout: float = NETWORK_TIMEOUT) -> tuple[str | None, str]:
    """(derniere version publiee, "") ou (None, raison). Echeance globale
    (K9) sur toute la lecture de plugins.xml."""
    deadline = _Deadline(timeout)
    try:
        xml_text = _call_before(deadline, _read_url, url, deadline)
    except Exception as exc:  # noqa: BLE001 -- toute erreur devient le detail affiche
        return None, _error_text(exc)
    latest = latest_published_version(xml_text)
    if latest is None:
        return None, f"plugins.xml: no readable '{PLUGIN_NAME}' entry"
    return latest, ""


def run_network_checks(host: str, port: int, cafile: str, installed_version: str,
                       url: str = PLUGIN_REPO_URL, timeout: float = NETWORK_TIMEOUT) -> list[Check]:
    """[version, serveur], lancees en parallele : chacune tient dans son
    echeance, l'ensemble dans *timeout*. Appele hors du fil de l'interface
    (QgsTask du dialogue)."""
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="constructel-bridge-diagnostic") as pool:
        version = pool.submit(fetch_latest_version, url, timeout)
        server = pool.submit(probe_server, host, port, cafile, timeout)
        latest, error = version.result()
        outcome, detail = server.result()
    return [version_check(installed_version, latest, error), server_check(host, port, outcome, detail)]


# --- Affichage -------------------------------------------------------------------------

_ORDER = {"network": 0, "version": 0, "plugin": 1, "server": 2, "identity": 3}


def ordered_checks(local_checks, network_checks=None) -> list[Check]:
    """Ordre de la spec (§ 6.6) : version, extensions, serveur, identifiant.
    Tant que les verifications reseau tournent (*network_checks* None), une
    seule ligne d'attente tient leur place, en tete."""
    pending = [RUNNING_CHECK] if network_checks is None else []
    checks = pending + list(network_checks or ()) + list(local_checks)
    return sorted(checks, key=lambda c: _ORDER.get(c.key, len(_ORDER)))
