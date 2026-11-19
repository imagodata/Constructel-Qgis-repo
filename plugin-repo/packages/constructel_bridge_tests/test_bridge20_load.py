"""Bridge 2.0, tache 2 (spec § 8) : chargement sans operateur et
multi-operateur. init_project accepte ``operator=None`` (communes seules,
jamais d'identite operateur), _load_selection enchaine les operateurs du
plan de chargement d'une LayerSelection. Doublures T/fakes19.py, aucun QGIS
ni aucune base."""
from __future__ import annotations

import pytest

from constructel_bridge import bridge_operators as bo
from constructel_bridge.bridge_presets import LayerSelection, selection_from_tiles
from constructel_bridge_tests.fakes19 import ORANGE, WYRE, FakeRasterLayer, install_fake_project
from constructel_bridge_tests.test_bridge18_layers import _shared_plugin, pi  # noqa: F401  (pi = fixture)
from constructel_bridge_tests.test_bridge19_reorganize import _names, plugin18  # noqa: F401  (plugin18 = fixture)


def _quiet_plugin(bp18, monkeypatch, tmp_path):
    monkeypatch.setattr(bp18.bridge_sketcher, "apply_all_translations", lambda *a, **k: None)
    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)
    for name in ("_hook_layers", "_apply_scope_to_layers", "_rewrite_value_relation_sources"):
        monkeypatch.setattr(plugin, name, lambda *a, **k: None)
    return plugin


def _spy_init_project(pi, monkeypatch, fail=(), added=1):
    """init_project factice : enregistre chaque appel ; leve pour les schemas
    de *fail*."""
    calls = []

    def fake(_params, _pw, selected, add_basemap=True, apply_styles=True, selected_basemaps=None, **kw):
        calls.append({"selected": set(selected), "add_basemap": add_basemap, "apply_styles": apply_styles,
                      "basemaps": set(selected_basemaps or ()), **kw})
        if kw["operator"] is not None and kw["operator"].schema in fail:
            raise RuntimeError(f"permission denied for schema {kw['operator'].schema}")
        return added

    monkeypatch.setattr(pi, "init_project", fake)
    return calls


# --- init_project / _detect_existing_layers sans operateur --------------------------------


def test_init_project_without_operator_loads_common_only_and_never_stamps(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    stamps = []
    monkeypatch.setattr(pi, "stamp_project", lambda *a, **k: stamps.append(a))

    count = pi.init_project({}, "", {"osiris_frozen", "v_form_lists", "cables"}, operator=None)

    assert count == 2 and stamps == []                 # cables (operateur) ecartee
    assert project.count_pg("osiris", "frozen_zones") == 1 and project.count_pg("wyre", "cables") == 0
    root = project.layerTreeRoot()
    assert _names(root) == ["Commun", "Référence"]      # v_form_lists : Reference ; aucun groupe operateur
    assert _names(root.children()[0]) == ["OSIRIS"]
    info = pi.get_bridge_info()
    assert info["operators"] == [] and info["version"] == pi.WYRE_PROJECT_VERSION
    assert pi.is_bridge_project()


def test_detect_existing_layers_none_is_common_only(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    project.add_pg("wyre", "cables")
    project.add_pg("chantier", "interventions")
    assert pi._detect_existing_layers(None) == {"interventions"}
    assert pi._detect_existing_layers("wyre") == {"cables", "interventions"}


def test_existing_by_schema_has_the_shape_selection_from_tiles_expects(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    project.add_pg("wyre", "cables")
    project.add_pg("chantier", "interventions")
    existing = pi.existing_by_schema(["wyre", "orange"])
    assert existing == {None: {"interventions"}, "wyre": {"cables"}, "orange": set()}
    selection = selection_from_tiles({"cables", "chantier"}, ["wyre", "orange"], existing)
    assert "cables" not in selection.per_operator.get("wyre", frozenset())
    assert selection.per_operator["orange"] == {"cables"} and "interventions" not in selection.common


# --- _load_selection -------------------------------------------------------------------------


def test_load_selection_chains_operators_and_loads_common_once(bp18, pi, monkeypatch, tmp_path):
    from qgis.core import QgsSettings

    calls = _spy_init_project(pi, monkeypatch)
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    selection = selection_from_tiles({"zones", "osiris"}, ["wyre", "orange"], {})

    assert plugin._load_selection([WYRE, ORANGE], selection, {"osm"}, True) == 2

    assert [c["operator"] for c in calls] == [WYRE, ORANGE]
    assert "osiris_frozen" in calls[0]["selected"] and "osiris_frozen" not in calls[1]["selected"]
    assert "zone_pop" in calls[0]["selected"] and "zone_pop" in calls[1]["selected"]
    assert [(c["add_basemap"], c["basemaps"]) for c in calls] == [(True, {"osm"}), (False, set())]
    assert all(c["suffix"] is True and c["apply_styles"] is True for c in calls)  # 2 operateurs : suffixe
    assert QgsSettings().value(bo.LAST_OPERATORS_KEY) == "wyre,orange"
    assert plugin.iface.messageBar().messages[-1][2] == bp18.tr("init.success", count=2)


def test_load_selection_single_operator_keeps_the_suffix_choice(bp18, pi, monkeypatch, tmp_path):
    calls = _spy_init_project(pi, monkeypatch)
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    selection = LayerSelection({"orange": frozenset({"cables"})}, frozenset())
    assert plugin._load_selection([WYRE, ORANGE], selection, set(), True) == 1
    assert calls[0]["operator"] == ORANGE and calls[0]["suffix"] is None and calls[0]["add_basemap"] is False


def test_load_selection_common_only_calls_init_project_with_none(bp18, pi, monkeypatch, tmp_path):
    from qgis.core import QgsSettings

    QgsSettings().setValue(bo.LAST_OPERATORS_KEY, "wyre")
    calls = _spy_init_project(pi, monkeypatch)
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    selection = selection_from_tiles({"osiris"}, [], {})

    assert plugin._load_selection([], selection, set(), True) == 1

    assert len(calls) == 1 and calls[0]["operator"] is None
    assert "osiris_frozen" in calls[0]["selected"] and "v_form_lists" in calls[0]["selected"]
    assert QgsSettings().value(bo.LAST_OPERATORS_KEY) == "wyre"      # inchange


def test_load_selection_basemaps_only_without_operator(bp18, pi, monkeypatch, tmp_path):
    calls = _spy_init_project(pi, monkeypatch, added=0)
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    plugin._load_selection([], LayerSelection({}, frozenset()), {"osm"}, True)
    assert len(calls) == 1 and calls[0]["operator"] is None and calls[0]["basemaps"] == {"osm"}


def test_load_selection_ignores_an_empty_request(bp18, pi, monkeypatch, tmp_path):   # K2, T9-c1b
    from qgis.core import QgsSettings

    calls = _spy_init_project(pi, monkeypatch)
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    assert plugin._load_selection([WYRE], LayerSelection({}, frozenset()), set(), True) == 0
    assert plugin._load_selection([WYRE], LayerSelection({"wyre": frozenset({"v_form_lists"})}, frozenset()),
                                  set(), True) == 0
    assert calls == [] and QgsSettings().value(bo.LAST_OPERATORS_KEY) is None


def test_one_operator_failing_does_not_cancel_the_others(bp18, pi, monkeypatch, tmp_path):
    from qgis.core import QgsSettings

    calls = _spy_init_project(pi, monkeypatch, fail=("orange",), added=3)
    errors = []
    monkeypatch.setattr(bp18.QMessageBox, "critical", staticmethod(lambda *a, **k: errors.append(a[2])))
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    selection = selection_from_tiles({"cables"}, ["wyre", "orange"], {})

    assert plugin._load_selection([WYRE, ORANGE], selection, set(), True) == 3

    assert [c["operator"] for c in calls] == [WYRE, ORANGE] and errors == []
    messages = [m[2] for m in plugin.iface.messageBar().messages]
    assert messages == [bp18.tr("init.success", count=3), bp18.tr("home.load_partial", operators="Orange")]
    assert QgsSettings().value(bo.LAST_OPERATORS_KEY) == "wyre"      # seuls les operateurs charges


def test_basemaps_are_retried_on_the_next_call_when_the_first_operator_fails(bp18, pi, monkeypatch, tmp_path):
    calls = _spy_init_project(pi, monkeypatch, fail=("wyre",))
    monkeypatch.setattr(bp18.QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    selection = selection_from_tiles({"cables"}, ["wyre", "orange"], {})
    plugin._load_selection([WYRE, ORANGE], selection, {"osm"}, True)
    assert [c["basemaps"] for c in calls] == [{"osm"}, {"osm"}]


def test_common_layers_are_retried_on_the_next_operator_when_the_first_fails(bp18, pi, monkeypatch, tmp_path):
    calls = _spy_init_project(pi, monkeypatch, fail=("wyre",))
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    selection = selection_from_tiles({"zones", "osiris"}, ["wyre", "orange"], {})

    assert plugin._load_selection([WYRE, ORANGE], selection, set(), True) == 1

    assert [c["operator"] for c in calls] == [WYRE, ORANGE]
    assert "osiris_frozen" in calls[0]["selected"] and "osiris_frozen" in calls[1]["selected"]
    assert "zone_pop" in calls[1]["selected"]


def test_common_layers_are_not_repeated_once_loaded(bp18, pi, monkeypatch, tmp_path):
    calls = _spy_init_project(pi, monkeypatch, fail=("orange",))
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    selection = selection_from_tiles({"zones", "osiris"}, ["wyre", "orange"], {})
    plugin._load_selection([WYRE, ORANGE], selection, set(), True)
    assert "osiris_frozen" in calls[0]["selected"] and "osiris_frozen" not in calls[1]["selected"]


def test_every_operator_failing_reports_init_error_and_returns_zero(bp18, pi, monkeypatch, tmp_path):
    from qgis.core import QgsSettings

    _spy_init_project(pi, monkeypatch, fail=("wyre", "orange"))
    errors = []
    monkeypatch.setattr(bp18.QMessageBox, "critical", staticmethod(lambda *a, **k: errors.append(a[2])))
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    selection = selection_from_tiles({"cables"}, ["wyre", "orange"], {})

    assert plugin._load_selection([WYRE, ORANGE], selection, {"osm"}, True) == 0

    assert errors == [bp18.tr("init.error", error="permission denied for schema wyre")]
    assert plugin.iface.messageBar().messages == []
    assert QgsSettings().value(bo.LAST_OPERATORS_KEY) is None


def test_load_selection_never_raises_on_unexpected_error(bp18, pi, monkeypatch, tmp_path):
    errors = []
    monkeypatch.setattr(bp18.QMessageBox, "critical", staticmethod(lambda *a, **k: errors.append(a[2])))
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin, "_init_conn_params", lambda: (_ for _ in ()).throw(RuntimeError("pas de connexion")))
    selection = LayerSelection({"wyre": frozenset({"cables"})}, frozenset())
    assert plugin._load_selection([WYRE], selection, set(), True) == 0
    assert errors == [bp18.tr("init.error", error="pas de connexion")]


def test_operator_missing_from_the_list_counts_as_a_failure(bp18, pi, monkeypatch, tmp_path):
    calls = _spy_init_project(pi, monkeypatch)
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    selection = selection_from_tiles({"cables"}, ["wyre", "orange"], {})
    assert plugin._load_selection([WYRE], selection, set(), True) == 1
    assert [c["operator"] for c in calls] == [WYRE]
    assert plugin.iface.messageBar().messages[-1][2] == bp18.tr("home.load_partial", operators="orange")


def test_load_selection_counts_basemaps_added(bp18, pi, monkeypatch, tmp_path):
    project = install_fake_project(pi, monkeypatch)

    def fake_init(_params, _pw, selected, add_basemap=True, apply_styles=True, selected_basemaps=None, **kw):
        for bm in pi.BASEMAPS:
            if bm["key"] in (selected_basemaps or ()):
                project.addMapLayer(FakeRasterLayer(bm["source"], bm["name"], "wms"))
        return 0

    monkeypatch.setattr(pi, "init_project", fake_init)
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    assert plugin._load_selection([], LayerSelection({}, frozenset()), {"osm"}, True) == 1
    assert plugin.iface.messageBar().messages[-1][2] == bp18.tr("init.success_basemaps", count=1)


# --- reorganisation 1.8 --------------------------------------------------------------------


def test_reorganize_runs_once_with_first_operator(bp18, pi, plugin18, monkeypatch):
    plugin, project, _layers = plugin18
    plugin._operator_registry = {"wyre": WYRE, "orange": ORANGE}
    seen = []
    real = plugin._reorganize_legacy_project
    monkeypatch.setattr(plugin, "_reorganize_legacy_project", lambda op, suffix: seen.append(op) or real(op, suffix))
    selection = selection_from_tiles({"cables"}, ["wyre", "orange"], {})

    plugin._load_selection([WYRE, ORANGE], selection, set(), True)

    assert seen == [WYRE]
    assert pi.needs_reorganization(project.layerTreeRoot()) is False


def test_common_only_load_reorganizes_a_1_8_project_once(bp18, pi, plugin18, monkeypatch):
    # Revue finale (spec § 8.2) : un chargement des seules couches communes
    # range aussi un projet 1.8, une fois, sans operateur a comparer.
    plugin, project, _layers = plugin18
    plugin._operator_registry = {"wyre": WYRE}
    seen = []
    real = plugin._reorganize_legacy_project
    monkeypatch.setattr(plugin, "_reorganize_legacy_project",
                        lambda op, suffix: seen.append((op, suffix)) or real(op, suffix))
    plugin._load_selection([], selection_from_tiles({"osiris"}, [], {}), set(), True)
    assert seen == [(None, None)]
    assert pi.needs_reorganization(project.layerTreeRoot()) is False
    assert project.readEntry("bridge", "operator", "")[0] == "wyre"


def test_reorganize_without_operator_never_forces_the_suffix(bp18, pi, plugin18):
    plugin, project, _layers = plugin18
    plugin._operator_registry = {"wyre": WYRE}
    assert plugin._reorganize_legacy_project(None, None) is None
    assert plugin._reorganize_legacy_project(None, False) is False   # deja range : tel quel
