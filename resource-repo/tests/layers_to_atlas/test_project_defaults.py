"""Regressions for project order, live layouts and successful output handling."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from test_legend import atlas_module as atlas_module  # shared isolated QGIS import fixture


def layer(identifier, index=False, legacy=False):
    result = Mock()
    result.id.return_value = identifier
    properties = {"map_atlas/index": index, "gofiber/atlas_index": legacy}
    result.customProperty.side_effect = lambda key, default: properties.get(key, default)
    return result


def project(order, visible):
    result = Mock()
    result.layerTreeRoot().layerOrder.return_value = order
    result.mapThemeCollection().masterVisibleLayers.return_value = visible
    return result


def test_default_uses_native_visible_render_order(atlas_module):
    bottom, hidden, top = layer("bottom"), layer("hidden"), layer("top")
    old_index, legacy = layer("index", index=True), layer("legacy", legacy=True)
    # Native QGIS visibility already incorporates parents/custom order/group layers.
    current = project([bottom, hidden, top], [top, old_index, legacy, bottom])
    assert atlas_module._map_layers(current, [], False) == [top, bottom]
    assert atlas_module._map_layers(current, [], True) == [top, bottom]
    hidden.isValid.assert_not_called()


def test_explicit_choice_keeps_project_order_and_deduplicates(atlas_module):
    top, bottom, extra = layer("top"), layer("bottom"), layer("extra")
    current = project([top, bottom], [top])
    assert atlas_module._map_layers(current, [bottom, extra, top, bottom], False) == [top, bottom, extra]


def test_optional_background_does_not_reorder_project_or_add_hidden(atlas_module, monkeypatch):
    top, background, bottom, hidden = (layer(name) for name in ("top", "bg", "bottom", "hidden"))
    current = project([top, background, bottom, hidden], [top, background, bottom])
    monkeypatch.setattr(atlas_module, "_is_project_background", lambda item, node: item in (background, hidden))
    assert atlas_module._map_layers(current, [bottom, top], True) == [top, background, bottom]


def test_live_layout_clears_stored_layers_and_style_overrides(atlas_module):
    layout, map_item, legend = Mock(), Mock(), Mock()
    layout.itemById.side_effect = lambda key: map_item if key == "atlas_map" else legend
    atlas_module._follow_project(layout)
    map_item.setLayers.assert_called_once_with([])
    map_item.setKeepLayerSet.assert_called_once_with(False)
    map_item.setKeepLayerStyles.assert_called_once_with(False)
    map_item.setLayerStyleOverrides.assert_called_once_with({})
    legend.setAutoUpdateModel.assert_called_once_with(True)
    # A live model must never receive wrapped names/user labels: it is the source tree.
    legend.model.assert_not_called()


def test_live_layout_without_legend(atlas_module):
    layout, map_item = Mock(), Mock()
    layout.itemById.side_effect = lambda key: map_item if key == "atlas_map" else None
    atlas_module._follow_project(layout)
    map_item.refresh.assert_called_once()


def test_auto_index_avoids_existing_index_and_logo(atlas_module, tmp_path):
    pdf = tmp_path / "dossier.pdf"
    existing = tmp_path / "dossier_plans.gpkg"
    assert atlas_module._default_index_path(str(pdf)) == str(existing)
    existing.write_bytes(b"original index")
    logo = tmp_path / "dossier_plans_2_logo.svg"
    logo.write_bytes(b"original logo")
    assert atlas_module._default_index_path(str(pdf)) == str(tmp_path / "dossier_plans_3.gpkg")
    assert existing.read_bytes() == b"original index"
    assert logo.read_bytes() == b"original logo"


@pytest.mark.parametrize("outcome", [True, False, OSError("no desktop handler")])
def test_folder_open_uses_local_directory_and_failure_is_nonfatal(atlas_module, monkeypatch, tmp_path, outcome):
    monkeypatch.setitem(sys.modules, "qgis.utils", SimpleNamespace(iface=object()))
    services = Mock()
    if isinstance(outcome, Exception):
        services.openUrl.side_effect = outcome
    else:
        services.openUrl.return_value = outcome
    monkeypatch.setattr(atlas_module, "QDesktopServices", services)
    monkeypatch.setattr(atlas_module, "QUrl", SimpleNamespace(fromLocalFile=lambda value: ("local", value)))
    feedback = Mock()
    atlas_module._open_pdf_folder(str(tmp_path / "atlas.pdf"), feedback)
    services.openUrl.assert_called_once_with(("local", str(tmp_path)))
    assert feedback.pushWarning.call_count == (0 if outcome is True else 1)


def test_headless_does_not_launch_file_manager(atlas_module, monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "qgis.utils", SimpleNamespace(iface=None))
    services = Mock()
    monkeypatch.setattr(atlas_module, "QDesktopServices", services)
    feedback = Mock()
    atlas_module._open_pdf_folder(str(tmp_path / "atlas.pdf"), feedback)
    services.openUrl.assert_not_called()
    feedback.pushInfo.assert_called_once()
