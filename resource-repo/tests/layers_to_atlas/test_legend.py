"""Synthetic regressions: no SQL, project data, credentials or GUI required."""

import ast
import importlib.util
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "collections/layers_to_atlas/processing/layers_to_atlas.py"


def load_script():
    spec = importlib.util.spec_from_file_location("atlas_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def atlas_module(monkeypatch):
    # Build named placeholders for the exact imports, not an alternative script.
    for name in (
        "qgis",
        "qgis.core",
        "qgis.PyQt",
        "qgis.PyQt.QtCore",
        "qgis.PyQt.QtGui",
        "qgis.PyQt.QtSvg",
    ):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    for node in ast.walk(ast.parse(SCRIPT.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("qgis"):
            if node.module not in sys.modules:
                monkeypatch.setitem(sys.modules, node.module, ModuleType(node.module))
            target = sys.modules[node.module]
            for alias in node.names:
                setattr(target, alias.name, type(alias.name, (), {}))
    sys.modules["qgis.core"].QgsProcessingException = RuntimeError
    module = load_script()
    module.Qt = SimpleNamespace(ItemDataRole=SimpleNamespace(DisplayRole=0))
    return module


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Court",
        "a" * 300,
        "classe_avec_un_identifiant_très_long",
        "Avant\nAprès",
        "Nom de couche avec beaucoup de mots",
    ],
)
def test_wrap_preserves_all_non_whitespace_characters(atlas_module, text):
    result = atlas_module.wrap_legend_text(text, 12, len)
    assert "".join(result.split()) == "".join(text.split())
    assert all(len(line) <= 12 for line in result.split("\n"))


@pytest.mark.parametrize("width", [0, -1, math.inf, math.nan])
def test_wrap_rejects_invalid_width(atlas_module, width):
    with pytest.raises(ValueError):
        atlas_module.wrap_legend_text("Label", width, len)


def test_wrap_oversized_glyph_finishes(atlas_module):
    assert atlas_module.wrap_legend_text("WW", 1, lambda text: len(text) * 10) == "W\nW"


def test_import_without_qgis(monkeypatch):
    monkeypatch.setitem(sys.modules, "qgis", None)
    module = load_script()
    assert not module.HAS_QGIS
    assert module.extent_plans((0, 0, 1, 1), 10, 10)


def make_layout(module, monkeypatch, sizes, filtered=False):
    pages = [dict(page_type="detail", overview=0), dict(page_type="detail", overview=0)]
    state = SimpleNamespace(page=0, profile=0, visits=[], profiles=[])
    legend = Mock()
    legend.model().rootGroup().findLayers.return_value = []
    atlas = Mock()
    atlas.beginRender.return_value = True
    atlas.count.return_value = len(pages)

    def seek(index):
        state.page = index
        state.visits.append((state.profile, index))
        return True

    atlas.seekTo.side_effect = seek
    layout = Mock()
    layout.atlas.return_value = atlas
    layout.reportContext().feature.side_effect = lambda: pages[state.page]
    map_item = Mock()
    map_item.rect().size.return_value = 10
    layout.itemById.side_effect = lambda name: (
        legend if name == "atlas_legend" else map_item
    )

    def apply(legend, labels, font, columns):
        state.profile = len(state.profiles)
        state.profiles.append((font, columns))

    monkeypatch.setattr(module, "_apply_legend_profile", apply)

    def minimum():
        width, height = sizes(state.profile, state.page)
        return SimpleNamespace(width=lambda: width, height=lambda: height)

    renderer = Mock()
    renderer.return_value.minimumSize.side_effect = minimum
    monkeypatch.setattr(module, "QgsLegendRenderer", renderer)
    options = dict(
        SHOW_NORTH=True,
        SHOW_SCALEBAR=True,
        OVERVIEW_SHOW_LEGEND=False,
        SHOW_LEGEND=True,
        LEGEND_FILTER_BY_MAP=filtered,
    )
    feedback = Mock()
    feedback.isCanceled.return_value = False
    return layout, legend, atlas, options, feedback, state, pages, map_item


@pytest.mark.parametrize("profile", range(4))
def test_each_fallback_profile_can_fit_all_pages(atlas_module, monkeypatch, profile):
    args = make_layout(
        atlas_module,
        monkeypatch,
        lambda candidate, page: (40, 150) if candidate == profile else (80, 300),
    )
    layout, legend, atlas, options, feedback, state, _, _ = args
    atlas_module._fit_atlas_legend(layout, options, 297, feedback)
    assert state.profiles[-1] == atlas_module.legend_profiles()[profile]
    assert state.visits[-2:] == [(profile, 0), (profile, 1)]
    legend.adjustBoxSize.assert_called_once()
    atlas.endRender.assert_called_once()


def test_fallback_restarts_at_first_page(atlas_module, monkeypatch):
    args = make_layout(
        atlas_module,
        monkeypatch,
        lambda candidate, page: (
            (80, 300) if candidate == 0 and page == 1 else (40, 150)
        ),
    )
    layout, _, _, options, feedback, state, _, _ = args
    atlas_module._fit_atlas_legend(layout, options, 297, feedback)
    assert state.visits == [(0, 0), (0, 1), (1, 0), (1, 1)]


def test_irreducible_overflow_is_explicit(atlas_module, monkeypatch):
    args = make_layout(atlas_module, monkeypatch, lambda candidate, page: (80, 300))
    layout, legend, atlas, options, feedback, state, _, _ = args
    with pytest.raises(RuntimeError, match="page 1.*80.0.*300.0.*54.0.*202.0"):
        atlas_module._fit_atlas_legend(layout, options, 297, feedback)
    assert len(state.profiles) == 4
    legend.adjustBoxSize.assert_not_called()
    atlas.endRender.assert_called_once()


@pytest.mark.parametrize("filtered", [True, False])
def test_map_filter_is_measured_synchronously(atlas_module, monkeypatch, filtered):
    args = make_layout(
        atlas_module, monkeypatch, lambda candidate, page: (40, 150), filtered
    )
    layout, legend, _, options, feedback, _, _, map_item = args
    atlas_module._fit_atlas_legend(layout, options, 297, feedback)
    calls = legend.model().setLegendFilterByMap.call_args_list
    assert len(calls) == 2
    assert all((call.args[0] is not None) == filtered for call in calls)
    assert map_item.mapSettings.call_count == (2 if filtered else 0)


def test_cover_and_hidden_overview_are_not_measured(atlas_module, monkeypatch):
    args = make_layout(
        atlas_module,
        monkeypatch,
        lambda candidate, page: pytest.fail("hidden page measured"),
    )
    layout, _, _, options, feedback, _, pages, _ = args
    pages[0].update(page_type="cover")
    pages[1].update(page_type="overview", overview=1)
    atlas_module._fit_atlas_legend(layout, options, 297, feedback)


def test_cancel_always_ends_render(atlas_module, monkeypatch):
    layout, _, atlas, options, feedback, *_ = make_layout(
        atlas_module, monkeypatch, lambda candidate, page: (40, 150)
    )
    feedback.isCanceled.return_value = True
    with pytest.raises(RuntimeError, match="annulée"):
        atlas_module._fit_atlas_legend(layout, options, 297, feedback)
    atlas.endRender.assert_called_once()


def test_seek_failure_always_ends_render(atlas_module, monkeypatch):
    layout, _, atlas, options, feedback, *_ = make_layout(
        atlas_module, monkeypatch, lambda candidate, page: (40, 150)
    )
    atlas.seekTo.side_effect = None
    atlas.seekTo.return_value = False
    with pytest.raises(RuntimeError, match="préparer la page 1"):
        atlas_module._fit_atlas_legend(layout, options, 297, feedback)
    atlas.endRender.assert_called_once()


def test_missing_legend_does_nothing(atlas_module):
    layout = Mock()
    layout.itemById.return_value = None
    atlas_module._fit_atlas_legend(layout, {}, 297, Mock())
    layout.atlas.assert_not_called()


@pytest.mark.parametrize("mode, name", [(0, "Sélection"), (1, "Couche entière")])
def test_missing_input_has_mode_specific_message(atlas_module, mode, name):
    module = atlas_module
    module.QgsUnitTypes.DistanceUnit = SimpleNamespace(DistanceMeters=1)
    algorithm = Mock()
    crs = Mock()
    crs.isValid.return_value = True
    crs.isGeographic.return_value = False
    crs.mapUnits.return_value = 1
    algorithm.parameterAsCrs.return_value = crs
    algorithm.parameterAsEnum.side_effect = lambda parameters, key, context: (
        mode if key == "MODE" else 0
    )
    algorithm.parameterAsDouble.side_effect = lambda parameters, key, context: (
        5000 if key == "SCALE" else 10
    )
    algorithm.parameterAsBool.return_value = True
    algorithm.parameterAsEnums.return_value = [1, 2]
    algorithm.parameterAsVectorLayer.return_value = None
    with pytest.raises(RuntimeError, match=f"{name}.*INPUT"):
        module.LayersToAtlasAlgorithm.processAlgorithm(algorithm, {}, Mock(), Mock())


@pytest.mark.parametrize(
    "height, north, scalebar, available",
    [
        (297, True, True, 202),
        (210, True, True, 115),
        (210, False, True, 140),
        (210, False, False, 156),
    ],
)
def test_height_reserves_other_sidebar_items(
    atlas_module, monkeypatch, height, north, scalebar, available
):
    layout, _, _, options, feedback, *_ = make_layout(
        atlas_module, monkeypatch, lambda candidate, page: (40, available + 1)
    )
    options.update(SHOW_NORTH=north, SHOW_SCALEBAR=scalebar)
    with pytest.raises(RuntimeError, match=f"54.0 × {available:.1f} mm disponibles"):
        atlas_module._fit_atlas_legend(layout, options, height, feedback)


def test_wrapping_changes_only_private_tree(atlas_module, monkeypatch):
    module = atlas_module
    module.QgsLegendStyle = SimpleNamespace(
        Style=SimpleNamespace(Title=0, Group=1, Subgroup=2, SymbolLabel=3)
    )
    font = Mock()
    font.Weight.Bold = 1
    font.return_value = SimpleNamespace(size=7)
    monkeypatch.setattr(module, "QFont", font)
    module.QgsLayoutUtils.textWidthMM = lambda font, text: len(text)
    module.QgsMapLayerLegendUtils = Mock()
    legend, node = Mock(), Mock()
    original_name = "layer_identifier_" * 12
    original_label = "class_identifier_" * 12
    module._apply_legend_profile(
        legend, [(node, original_name, [original_label])], 7, 2
    )
    node.setUseLayerName.assert_called_once_with(False)
    wrapped = node.setName.call_args.args[0]
    assert wrapped.replace("\n", "") == original_name
    node.layer.assert_not_called()
    updated = module.QgsMapLayerLegendUtils.setLegendNodeUserLabel.call_args.args[2]
    assert updated.replace("\n", "") == original_label
    legend.model().refreshLayerLegend.assert_called_once_with(node)
    legend.setColumnCount.assert_called_once_with(2)


def test_native_qt_text_metrics(monkeypatch, atlas_module):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    # Liaison déjà chargée dans le processus (jamais deux Qt), sinon PyQt6
    # (QGIS 4) puis PyQt5 (QGIS 3).
    loaded = [name for name in ("PyQt6", "PyQt5") if name in sys.modules]
    names = [n for n in loaded or ("PyQt6", "PyQt5") if importlib.util.find_spec(n)]
    if not names:
        pytest.skip("ni PyQt6 ni PyQt5 installé")
    widgets = importlib.import_module(f"{names[0]}.QtWidgets")
    gui = importlib.import_module(f"{names[0]}.QtGui")
    app = widgets.QApplication.instance() or widgets.QApplication([])
    font = gui.QFont("Sans Serif")
    font.setPixelSize(25)
    metrics = gui.QFontMetricsF(font)

    def measure(text):
        return metrics.horizontalAdvance(text) / 10

    text = "identifiant_très_long_sans_espaces_" * 15
    result = atlas_module.wrap_legend_text(text, 12, measure)
    assert result.replace("\n", "") == text
    assert all(measure(line) <= 12 for line in result.split("\n"))
    assert app is not None
