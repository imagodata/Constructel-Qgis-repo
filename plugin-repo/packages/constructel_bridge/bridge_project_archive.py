"""Archive .qgz du projet QGIS courant pour l'enregistrer en base (Bridge 2.1).

``QgsProject.write(chemin)`` change le chemin du projet et ecrit les couches
fichier en chemins relatifs au temporaire : le temps de l'ecriture, les
chemins sont mis en absolu ; ensuite le chemin du fichier, le mode de chemins
et l'etat « modifie » du projet sont restaures (dans un ``finally``) et le
temporaire est supprime. Le projet de la personne n'en garde aucune trace.
"""
from __future__ import annotations

import os

from .bridge_db_save import clear_file_name

ARCHIVE_NAME = "bridge_save.qgz"


def _absolute_type():
    try:
        from qgis.core import Qgis  # noqa: PLC0415 - QGIS a l'execution seulement
        return Qgis.FilePathType.Absolute
    except Exception:  # noqa: BLE001 - QGIS < 3.22 ou stubs
        return None


def _read_storage(project):
    """("api", valeur) si filePathStorage existe, sinon ("entry", bool)."""
    getter = getattr(project, "filePathStorage", None)
    if callable(getter) and callable(getattr(project, "setFilePathStorage", None)):
        try:
            return "api", getter()
        except Exception:  # noqa: BLE001
            pass
    reader = getattr(project, "readBoolEntry", None)
    value = False
    if callable(reader):
        try:
            result = reader("Paths", "/Absolute", False)
            value = bool(result[0] if isinstance(result, tuple) else result)
        except Exception:  # noqa: BLE001
            value = False
    return "entry", value


def _set_absolute(project, kind: str) -> None:
    absolute = _absolute_type() if kind == "api" else None
    if kind == "api" and absolute is not None:
        project.setFilePathStorage(absolute)
    else:
        project.writeEntry("Paths", "/Absolute", True)


def _restore_storage(project, saved) -> None:
    kind, value = saved
    if kind == "api":
        project.setFilePathStorage(value)
    else:
        project.writeEntry("Paths", "/Absolute", bool(value))


def write_project_archive(project, directory: str) -> bytes:
    """Octets d'une archive .qgz du projet *project*, ecrite dans
    *directory* ; leve OSError si l'ecriture echoue. Chemin, mode de chemins
    et etat « modifie » toujours restaures."""
    path = os.path.join(directory, ARCHIVE_NAME)
    file_name = project.fileName()
    dirty = bool(project.isDirty())
    storage = _read_storage(project)
    try:
        _set_absolute(project, storage[0])
        if not project.write(path):
            error = getattr(project, "error", lambda: "")()
            raise OSError(f"ecriture du projet QGIS impossible : {error or path}")
        with open(path, "rb") as handle:
            return handle.read()
    finally:
        try:
            if file_name:
                project.setFileName(file_name)
            else:   # projet sans emplacement : chemin NUL, pas "" (disquette native)
                clear_file_name(project)
        finally:
            try:
                _restore_storage(project, storage)
            finally:
                project.setDirty(dirty)
                try:
                    os.remove(path)
                except OSError:
                    pass
