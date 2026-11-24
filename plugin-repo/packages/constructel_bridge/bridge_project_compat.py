# -*- coding: utf-8 -*-
"""Bridge 2.1.4 : projet enregistre par un QGIS plus recent (4.x) ouvert en
QGIS 3.x. Deux pertes constatees le 24/11 sur le projet « test » :

* SCR du projet (``restore_project_crs``) ;
* fonds WMTS (``repair_wms_layers``) : QGIS 4 encode les parametres de la
  source (``tileMatrixSet=EPSG%3A31370``) et QGIS 3.44 ne les decode pas
  (« Tile layer or tile matrix set not found ») ; la forme decodee est
  valide en 3.44 comme en 4.3. Seules les couches wms restees invalides
  sont reprises : une couche valide n'est jamais touchee.

SCR du projet. Un projet enregistre en QGIS 4.2 et ouvert en QGIS 3.x perd son SCR de
projet : le bloc ``<projectCrs>`` est lisible tel quel
(``QgsCoordinateReferenceSystem.readXml`` le lit), mais QGIS 3 ne le relit
pas a l'ouverture. Sans SCR, l'echelle du canevas part a 1:85 000 000 et
aucune couche a visibilite par echelle ne s'affiche (24/11, projet « test »).

``restore_project_crs`` est appele sur ``QgsProject.readProject`` : si le SCR
du projet est invalide, il le relit dans le document, puis recadre le canevas
principal sur l'emprise enregistree (``<mapcanvas name="theMapCanvas">``),
que le canevas a deja lue avec un SCR invalide. Un projet dont le SCR est
valide n'est jamais touche.

Les imports qgis.core sont paresseux : le module se charge sous les stubs.
"""
from __future__ import annotations

from typing import Callable, Iterable, List, Optional, Tuple
from urllib.parse import unquote

MAIN_CANVAS = "theMapCanvas"
# Parametres de source wms/wmts decodes ; `url` reste tel quel (QGIS 3 le
# decode lui-meme, et sa valeur porte ses propres & et =).
WMS_DECODED_KEYS = ("crs", "tileMatrixSet", "format", "layers", "styles")
Extent = Tuple[float, float, float, float]


def _read_crs(node):
    from qgis.core import QgsCoordinateReferenceSystem
    crs = QgsCoordinateReferenceSystem()
    if crs.readXml(node) and crs.isValid():
        return crs
    return None


def _make_rect(xmin, ymin, xmax, ymax):
    from qgis.core import QgsRectangle
    return QgsRectangle(xmin, ymin, xmax, ymax)


def saved_qgis_version(doc) -> str:
    """Version de QGIS qui a enregistre le projet (attribut version)."""
    return doc.documentElement().attribute("version", "")


def canvas_extent(doc) -> Optional[Extent]:
    """Emprise enregistree du canevas principal, None si absente ou illisible."""
    root = doc.documentElement()
    chosen = None
    canvas = root.firstChildElement("mapcanvas")
    while not canvas.isNull():
        if chosen is None or canvas.attribute("name") == MAIN_CANVAS:
            chosen = canvas
            if canvas.attribute("name") == MAIN_CANVAS:
                break
        canvas = canvas.nextSiblingElement("mapcanvas")
    if chosen is None:
        return None
    extent = chosen.firstChildElement("extent")
    if extent.isNull():
        return None
    try:
        xmin, ymin, xmax, ymax = (float(extent.firstChildElement(k).text())
                                  for k in ("xmin", "ymin", "xmax", "ymax"))
    except ValueError:
        return None
    if not (xmax > xmin and ymax > ymin):
        return None
    return xmin, ymin, xmax, ymax


def restore_project_crs(project, doc, canvas=None, *,
                        read_crs: Callable = _read_crs,
                        make_rect: Callable = _make_rect) -> Optional[str]:
    """Retablit le SCR du projet depuis ``<projectCrs>`` s'il est invalide.

    Retourne l'identifiant du SCR retabli (authid), None si rien n'a ete fait
    (SCR deja valide, ou bloc absent / illisible). Un projet qui n'etait pas
    modifie ne l'est pas davantage apres.
    """
    if project.crs().isValid():
        return None
    node = doc.documentElement().firstChildElement("projectCrs")
    if node.isNull():
        return None
    crs = read_crs(node)
    if crs is None or not crs.isValid():
        return None
    was_dirty = project.isDirty()
    project.setCrs(crs)
    if not was_dirty:
        project.setDirty(False)
    if canvas is not None:
        canvas.setDestinationCrs(crs)
        extent = canvas_extent(doc)
        if extent is not None:
            canvas.setExtent(make_rect(*extent))
        canvas.refresh()
    return crs.authid() or "?"


def decode_wms_params(source: str) -> str:
    """Source wms/wmts avec les parametres WMS_DECODED_KEYS decodes.

    Rendue telle quelle (meme objet) si rien n'est a decoder. Une valeur qui
    se decoderait en ``&`` ou ``=`` reste encodee (separateurs de la source).
    """
    parts, changed = [], False
    for part in source.split("&"):
        key, sep, value = part.partition("=")
        if sep and key in WMS_DECODED_KEYS and "%" in value:
            decoded = unquote(value)
            if decoded != value and "&" not in decoded and "=" not in decoded:
                part, changed = f"{key}={decoded}", True
        parts.append(part)
    return "&".join(parts) if changed else source


def repair_wms_layers(layers: Iterable, set_source: Callable) -> Tuple[List[str], List[str]]:
    """Reprend les couches wms invalides dont la source a des parametres
    encodes : ``set_source(layer, source_decodee)``. Retourne (reparees,
    toujours invalides) par nom de couche."""
    repaired, still_bad = [], []
    for layer in layers:
        if layer.providerType() != "wms" or layer.isValid():
            continue
        source = layer.source()
        fixed = decode_wms_params(source)
        if fixed is source:
            continue
        set_source(layer, fixed)
        (repaired if layer.isValid() else still_bad).append(layer.name())
    return repaired, still_bad
