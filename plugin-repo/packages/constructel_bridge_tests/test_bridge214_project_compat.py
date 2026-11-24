"""Bridge 2.1.4 : SCR d'un projet enregistre par un QGIS plus recent.

Un projet enregistre en QGIS 4.2 et ouvert en QGIS 3.x perd son SCR de
projet (le bloc <projectCrs> est lisible, mais QGIS 3 ne le relit pas) :
l'echelle part a 1:85 000 000 et aucune couche a visibilite par echelle ne
s'affiche (journal et capture du 24/11, projet « test »). Le Bridge relit
alors <projectCrs> et recadre le canevas sur l'emprise enregistree.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from constructel_bridge import bridge_project_compat as bpc

QtXml = None
for _name in ("PyQt6.QtXml", "PyQt5.QtXml"):
    try:
        QtXml = __import__(_name, fromlist=["QDomDocument"])
        break
    except ImportError:
        continue

pytestmark = pytest.mark.skipif(QtXml is None, reason="QtXml (PyQt5/PyQt6) absent")

QGS = """<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis projectname="test" version="4.2.3-Belém do Pará">
  <projectCrs>
    <spatialrefsys nativeFormat="Wkt">
      <srid>31370</srid>
      <authid>EPSG:31370</authid>
    </spatialrefsys>
  </projectCrs>
  <mapcanvas annotationsVisible="1" name="theMapCanvas">
    <units>meters</units>
    <extent>
      <xmin>140753.3</xmin><ymin>160964.3</ymin><xmax>159283.4</xmax><ymax>179275.6</ymax>
    </extent>
  </mapcanvas>
</qgis>"""


def _doc(xml=QGS):
    doc = QtXml.QDomDocument()
    doc.setContent(xml)
    return doc


class _Crs:
    def __init__(self, authid="", valid=False):
        self._authid, self._valid = authid, valid

    def isValid(self):
        return self._valid

    def authid(self):
        return self._authid


class _Project:
    def __init__(self, crs, dirty=False):
        self._crs, self.dirty, self.set_crs = crs, dirty, []

    def crs(self):
        return self._crs

    def setCrs(self, crs):
        self._crs = crs
        self.set_crs.append(crs)
        self.dirty = True

    def isDirty(self):
        return self.dirty

    def setDirty(self, dirty):
        self.dirty = dirty


class _Canvas:
    def __init__(self):
        self.calls = []

    def setDestinationCrs(self, crs):
        self.calls.append(("crs", crs.authid()))

    def setExtent(self, rect):
        self.calls.append(("extent", rect))

    def refresh(self):
        self.calls.append(("refresh",))


def _read_crs(node):
    authid = node.firstChildElement("spatialrefsys").firstChildElement("authid").text()
    return _Crs(authid, True) if authid else None


def _restore(project, doc, canvas=None):
    return bpc.restore_project_crs(project, doc, canvas, read_crs=_read_crs, make_rect=lambda *xy: xy)


def test_saved_version_and_canvas_extent_are_read_from_the_document():
    doc = _doc()
    assert bpc.saved_qgis_version(doc) == "4.2.3-Belém do Pará"
    assert bpc.canvas_extent(doc) == (140753.3, 160964.3, 159283.4, 179275.6)


def test_invalid_project_crs_is_restored_and_the_canvas_reframed():
    project, canvas = _Project(_Crs()), _Canvas()
    assert _restore(project, _doc(), canvas) == "EPSG:31370"
    assert project.crs().authid() == "EPSG:31370"
    assert canvas.calls == [("crs", "EPSG:31370"),
                            ("extent", (140753.3, 160964.3, 159283.4, 179275.6)),
                            ("refresh",)]


def test_restoring_does_not_leave_a_freshly_opened_project_modified():
    project = _Project(_Crs(), dirty=False)
    _restore(project, _doc())
    assert project.dirty is False
    already_modified = _Project(_Crs(), dirty=True)
    _restore(already_modified, _doc())
    assert already_modified.dirty is True


def test_valid_project_crs_is_left_alone():
    project, canvas = _Project(_Crs("EPSG:3857", True)), _Canvas()
    assert _restore(project, _doc(), canvas) is None
    assert project.set_crs == [] and canvas.calls == []


def test_document_without_a_readable_project_crs_changes_nothing():
    for xml in ('<qgis version="4.2.3"/>',
                '<qgis version="4.2.3"><projectCrs><spatialrefsys/></projectCrs></qgis>'):
        project = _Project(_Crs())
        assert _restore(project, _doc(xml)) is None
        assert project.set_crs == []


def test_missing_or_garbled_canvas_extent_only_restores_the_crs():
    xml = QGS.replace("<xmin>140753.3</xmin>", "<xmin>abc</xmin>")
    project, canvas = _Project(_Crs()), _Canvas()
    assert _restore(project, _doc(xml), canvas) == "EPSG:31370"
    assert bpc.canvas_extent(_doc(xml)) is None
    assert canvas.calls == [("crs", "EPSG:31370"), ("refresh",)]


def test_the_main_canvas_extent_wins_over_other_canvases():
    xml = QGS.replace('<mapcanvas annotationsVisible="1" name="theMapCanvas">',
                      '<mapcanvas name="other"><extent><xmin>0</xmin><ymin>0</ymin><xmax>1</xmax>'
                      '<ymax>1</ymax></extent></mapcanvas><mapcanvas annotationsVisible="1" name="theMapCanvas">')
    assert bpc.canvas_extent(_doc(xml)) == (140753.3, 160964.3, 159283.4, 179275.6)


# --- branchement dans le plugin ------------------------------------------------------------

def test_plugin_project_read_restores_the_crs_and_says_so(bp18, monkeypatch):
    bp = bp18

    calls, logs, bar = [], [], []
    monkeypatch.setattr(bp, "restore_project_crs",
                        lambda project, doc, canvas: calls.append((doc, canvas)) or "EPSG:31370")
    canvas = object()
    plugin = SimpleNamespace(
        iface=SimpleNamespace(mapCanvas=lambda: canvas,
                              messageBar=lambda: SimpleNamespace(pushWarning=lambda *a: bar.append(a))),
        _log=lambda msg, *a: logs.append(msg),
    )
    doc = _doc()
    bp.ConstructelBridgePlugin._restore_project_crs(plugin, doc)
    assert calls == [(doc, canvas)]
    assert any("EPSG:31370" in m and "4.2.3" in m for m in logs)
    assert bar and "EPSG:31370" in bar[0][1]


def test_plugin_project_read_survives_a_restore_error(bp18, monkeypatch):
    bp = bp18

    def boom(*_a):
        raise RuntimeError("crs")

    logs = []
    monkeypatch.setattr(bp, "restore_project_crs", boom)
    plugin = SimpleNamespace(iface=SimpleNamespace(mapCanvas=lambda: None), _log=lambda msg, *a: logs.append(msg))
    bp.ConstructelBridgePlugin._restore_project_crs(plugin, _doc())
    assert any("crs" in m for m in logs)


def test_on_project_read_calls_the_crs_restore_first(bp18):
    import inspect
    bp = bp18
    src = inspect.getsource(bp.ConstructelBridgePlugin._on_project_read)
    assert "self._restore_project_crs(doc)" in src
    assert src.index("self._restore_project_crs(doc)") < src.index("self._fix_layer_credentials()")


# --- fonds WMTS d'un projet QGIS 4.x : parametres encodes ------------------------------------
# QGIS 4.2 enregistre tileMatrixSet=EPSG%3A31370 ; QGIS 3.44 ne le decode pas
# (« Tile layer or tile matrix set not found », verifie dans qgis/qgis:ltr),
# la forme decodee est valide en 3.44 comme en 4.3.

URL = ("https%3A%2F%2Fgeoservices-basemap.irisnet.be%2Fgeowebcache%2Fservice%2Fwmts"
       "%3Fservice%3DWMTS%26request%3DGetCapabilities%26version%3D1.0.0")
ENCODED = ("crs=EPSG%3A31370&dpiMode=7&featureCount=10&format=image%2Fpng&layers=UrbISFrenchLabeledGray"
           "&styles=&tileMatrixSet=EPSG%3A31370&tilePixelRatio=0&url=" + URL)
DECODED = ("crs=EPSG:31370&dpiMode=7&featureCount=10&format=image/png&layers=UrbISFrenchLabeledGray"
           "&styles=&tileMatrixSet=EPSG:31370&tilePixelRatio=0&url=" + URL)


def test_wms_source_parameters_are_decoded_but_the_url_is_kept():
    assert bpc.decode_wms_params(ENCODED) == DECODED


def test_already_decoded_source_is_returned_unchanged():
    assert bpc.decode_wms_params(DECODED) is DECODED


def test_a_value_that_would_decode_to_a_separator_stays_encoded():
    src = "crs=EPSG:31370&styles=a%26b&layers=x%3Dy&tileMatrixSet=EPSG%3A31370"
    assert bpc.decode_wms_params(src) == "crs=EPSG:31370&styles=a%26b&layers=x%3Dy&tileMatrixSet=EPSG:31370"


class _Layer:
    def __init__(self, name, source, provider="wms", valid=False, fixable=True):
        self._name, self._source, self._provider = name, source, provider
        self._valid, self._fixable = valid, fixable

    def name(self):
        return self._name

    def source(self):
        return self._source

    def providerType(self):
        return self._provider

    def isValid(self):
        return self._valid


def _set_source(layer, source):
    layer._source = source
    layer._valid = layer._fixable and source == DECODED


def test_only_invalid_wms_layers_with_encoded_parameters_are_repaired():
    broken = _Layer("UrbIS FR Gray", ENCODED)
    valid = _Layer("UrbIS 4.x", ENCODED, valid=True)          # QGIS 4 : valide, jamais touchee
    postgres = _Layer("Cables", "dbname='x' crs=EPSG%3A31370", provider="postgres")
    clean = _Layer("OSM", DECODED)                              # rien a decoder
    assert bpc.repair_wms_layers([broken, valid, postgres, clean], _set_source) == (["UrbIS FR Gray"], [])
    assert broken.source() == DECODED and broken.isValid()
    assert valid.source() == ENCODED and postgres.source().endswith("EPSG%3A31370") and clean.source() is DECODED


def test_a_layer_still_invalid_after_decoding_is_reported():
    still = _Layer("UrbIS hors ligne", ENCODED, fixable=False)
    assert bpc.repair_wms_layers([still], _set_source) == ([], ["UrbIS hors ligne"])


def test_plugin_repairs_wms_layers_on_project_read(bp18, monkeypatch):
    bp = bp18
    logs = []
    monkeypatch.setattr(bp, "repair_wms_layers", lambda layers, set_source: (["UrbIS FR Gray"], ["X"]))
    plugin = SimpleNamespace(_log=lambda msg, *a: logs.append(msg))
    bp.ConstructelBridgePlugin._repair_wms_sources(plugin)
    assert any("UrbIS FR Gray" in m for m in logs) and any("X" in m for m in logs)
    import inspect
    src = inspect.getsource(bp.ConstructelBridgePlugin._on_project_read)
    assert src.index("self._repair_wms_sources()") < src.index("self._fix_layer_credentials()")
