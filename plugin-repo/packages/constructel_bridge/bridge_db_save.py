"""Disquette et Ctrl+S d'un projet QGIS ouvert ou enregistre en base par le
Bridge (`projet.qgis_projects`).

Plutot que de detourner l'action « Enregistrer » de QGIS (connexion C++
privee, partagee avec les autres plugins), le Bridge declare un stockage de
projet (``QgsProjectStorage``, API publique depuis QGIS 3.2, presente en
QGIS 4) pour le schema d'URI ``constructel-bridge:``. Le projet courant recoit
l'URI ``constructel-bridge:projet/<nom>`` : la disquette, Ctrl+S, la question
« Enregistrer les modifications ? » a la fermeture et tout ``QgsProject.write()``
passent alors par QGIS lui-meme (archive .qgz, signal ``writeProject`` donc
nettoyage des identifiants), puis par ``writeProject`` ci-dessous, qui confie
les octets au plugin (``projet.fn_qgis_project_save``, version attendue).
« Enregistrer sous » reste natif : il donne un chemin local au projet, qui
quitte ce stockage. ``unload`` retire le stockage et l'URI du projet courant.

La lecture par ce stockage (projets recents, « Revenir ») est refusee avec un
message : un projet en base ne s'ouvre que par le Bridge, qui neutralise le
code embarque et les identifiants avant ``project.read``.

Aucun import QGIS au niveau du module (tests sans QGIS).
"""
from __future__ import annotations

from typing import Callable, Optional, Tuple
from urllib.parse import quote, unquote

STORAGE_TYPE = "constructel-bridge"
_PROJET_PREFIX = STORAGE_TYPE + ":projet/"

# writer(uri, contenu .qgz) -> (enregistre, message de refus)
Writer = Callable[[str, bytes], Tuple[bool, str]]


def bridge_uri(name: str) -> str:
    """URI du projet QGIS *name* de `projet.qgis_projects` (nom encode :
    un nom peut contenir « / », « : » ou des espaces)."""
    return _PROJET_PREFIX + quote(name or "", safe="")


def is_bridge_uri(uri) -> bool:
    return isinstance(uri, str) and uri.startswith(STORAGE_TYPE + ":")


def name_from_uri(uri) -> Optional[str]:
    if not isinstance(uri, str) or not uri.startswith(_PROJET_PREFIX):
        return None
    return unquote(uri[len(_PROJET_PREFIX):])


def clear_file_name(project) -> None:
    """Projet sans emplacement, comme un projet neuf : chemin NUL.

    ``setFileName("")`` donne une chaine vide NON nulle (PyQt) : la disquette
    de QGIS saute alors « Enregistrer sous » et tente d'ecrire dans « »
    (« Impossible d'enregistrer le projet »). ``None`` donne une chaine nulle :
    la disquette ouvre « Enregistrer sous », comportement natif."""
    try:
        project.setFileName(None)
    except TypeError:  # liaison qui refuserait None : repli historique
        project.setFileName("")


def _bytes(data) -> bytes:
    getter = getattr(data, "data", None)          # QByteArray (PyQt5/6)
    if callable(getter):
        data = getter()
    return bytes(data or b"")


def _push(context, message: str) -> None:
    """Message de refus repris par QGIS dans sa boite « Impossible
    d'enregistrer le projet » (dernier message du contexte)."""
    if not message or context is None:
        return
    try:
        from qgis.core import Qgis  # noqa: PLC0415 - QGIS a l'execution seulement
        context.pushMessage(message, Qgis.MessageLevel.Critical)
    except Exception:  # noqa: BLE001 - jamais d'exception vers QGIS
        try:
            context.pushMessage(message)
        except Exception:  # noqa: BLE001
            pass


def storage_class():
    """Classe ``QgsProjectStorage`` du Bridge (construite a l'appel : la
    base vient de ``qgis.core``). Aucune methode ne laisse passer
    d'exception vers QGIS."""
    from qgis.core import QgsProjectStorage  # noqa: PLC0415

    from .i18n import tr  # noqa: PLC0415

    class BridgeProjectStorage(QgsProjectStorage):
        def __init__(self, writer: Optional[Writer]):
            super().__init__()
            self.writer = writer

        def type(self):  # noqa: A003 - nom impose par QGIS
            return STORAGE_TYPE

        def listProjects(self, uri):  # noqa: N802
            return []

        def readProject(self, uri, device, context):  # noqa: N802
            _push(context, tr("disquette.open_via_bridge"))
            return False

        def writeProject(self, uri, device, context):  # noqa: N802
            writer = self.writer
            if writer is None:
                _push(context, tr("disquette.unavailable"))
                return False
            try:
                saved, message = writer(uri, _bytes(device.readAll()))
            except Exception as exc:  # noqa: BLE001
                saved, message = False, tr("save.error", message=str(exc))
            if not saved:
                _push(context, message)
            return bool(saved)

        def removeProject(self, uri):  # noqa: N802
            return False

    return BridgeProjectStorage


def _registry():
    from qgis.core import QgsApplication  # noqa: PLC0415

    return QgsApplication.projectStorageRegistry()


def register_storage(writer: Writer, log: Optional[Callable[[str], None]] = None):
    """Declare le stockage du Bridge ; rend l'objet (a garder pour
    ``unregister_storage``) ou None si l'API manque ou echoue. Un stockage
    du meme type reste d'un chargement precedent est d'abord retire."""
    try:
        registry = _registry()
        stale = registry.projectStorageFromType(STORAGE_TYPE)
        if stale is not None:
            registry.unregisterProjectStorage(stale)
        storage = storage_class()(writer)
        registry.registerProjectStorage(storage)
        return storage
    except Exception as exc:  # noqa: BLE001 - disquette native, jamais bloquant
        if log is not None:
            log(f"Stockage de projet du Bridge indisponible : {exc}")
        return None


def unregister_storage(storage) -> None:
    if storage is None:
        return
    storage.writer = None
    try:
        _registry().unregisterProjectStorage(storage)
    except Exception:  # noqa: BLE001 - dechargement best effort
        pass
