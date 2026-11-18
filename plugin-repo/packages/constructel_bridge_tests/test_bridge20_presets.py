"""Bridge 2.0, tache 1 (accueil v2, spec § 6.2, § 8.1) : tuiles, selection et
presets sans Qt (``bridge_presets``), importe directement comme
``bridge_home_model`` ; seul le test d'alignement sur le catalogue passe par
la fixture ``pi`` (module Qt sous stubs)."""
from __future__ import annotations

import json

from constructel_bridge import bridge_presets as bp
from constructel_bridge_tests.test_bridge18_layers import pi  # noqa: F401  (fixture)


def test_expert_layers_are_never_in_a_tile_by_default():
    assert "subducts" not in bp.tile_keys("genie_civil")
    assert "subducts" in bp.tile_keys("genie_civil", expert=True)
    assert len(bp.tile_keys("chantier")) == 6


def test_zones_for_two_operators():
    sel = bp.selection_from_tiles({"zones"}, ("wyre", "orange"), {})
    assert sel.per_operator == {"wyre": bp.tile_keys("zones"), "orange": bp.tile_keys("zones")}
    assert sel.common == frozenset() and sel.layer_count() == 8


def test_common_tiles_without_operator_go_to_none_plan():
    sel = bp.selection_from_tiles({"osiris", "zones"}, (), {})
    assert sel.per_operator == {} and sel.load_plan() == [(None, bp.tile_keys("osiris") | bp.ALWAYS_KEYS)]


def test_load_plan_attaches_common_and_auto_keys_to_first_operator_only():
    sel = bp.selection_from_tiles({"zones", "osiris"}, ("wyre", "orange"), {})
    plan = sel.load_plan()
    assert [s for s, _ in plan] == ["wyre", "orange"]
    assert bp.tile_keys("osiris") <= plan[0][1] and not (bp.tile_keys("osiris") & plan[1][1])
    assert {"docs_elements", "v_form_lists"} <= plan[0][1] and {"docs_elements", "v_form_lists"} <= plan[1][1]


def test_operator_with_no_operator_layer_is_left_out_of_the_plan():
    sel = bp.selection_from_tiles({"osiris"}, ("wyre",), {})
    assert sel.per_operator == {} and sel.load_plan()[0][0] is None


def test_already_loaded_layers_are_excluded():
    sel = bp.selection_from_tiles({"zones", "osiris"}, ("wyre",), {"wyre": {"zone_mro"}, None: {"osiris_events"}})
    assert "zone_mro" not in sel.per_operator["wyre"] and "osiris_events" not in sel.common


def test_tile_done_only_when_every_operator_has_it():
    existing = {"wyre": set(bp.tile_keys("zones"))}
    sel = bp.selection_from_tiles({"zones"}, ("wyre", "orange"), existing)
    assert bp.tile_state("zones", sel, ("wyre", "orange"), existing) == "on"
    assert bp.tile_state("zones", sel, ("wyre",), existing) == "done"


def test_tile_states_partial_off_disabled():
    sel = bp.LayerSelection({"wyre": frozenset({"zone_mro"})}, frozenset())
    assert bp.tile_state("zones", sel, ("wyre",), {}) == "partial"
    assert bp.tile_state("cables", sel, ("wyre",), {}) == "off"
    assert bp.tile_state("zones", bp.LayerSelection({}, frozenset()), (), {}) == "disabled"


def test_presets_round_trip_and_garbage():
    p = bp.UserPreset("Coordo", ("wyre",), bp.selection_from_tiles({"zones", "osiris"}, ("wyre",), {}))
    assert bp.presets_from_json(bp.presets_to_json([p])) == [p]
    assert bp.presets_from_json("not json") == [] and bp.presets_from_json(None) == []


def test_restrict_preset_drops_unusable_operators():
    p = bp.UserPreset("x", ("wyre", "orange"), bp.selection_from_tiles({"zones", "osiris"}, ("wyre", "orange"), {}))
    r = bp.restrict_preset(p, {"wyre"})
    assert r.schemas == ("wyre",) and set(r.selection.per_operator) == {"wyre"} and r.selection.common == p.selection.common


# --- complements : cas limites de la selection et du JSON ------------------------

def test_selection_is_comparable_and_normalised():
    a = bp.LayerSelection({"wyre": ["zone_mro", "zone_pop"], "orange": []}, ["wms"])
    b = bp.LayerSelection({"wyre": frozenset({"zone_pop", "zone_mro"})}, frozenset({"wms"}))
    assert a == b and not a.is_empty()
    assert bp.LayerSelection({}, frozenset()).is_empty()
    assert bp.LayerSelection({"wyre": frozenset()}, frozenset()).is_empty()


def test_layer_count_ignores_always_and_auto_keys():
    sel = bp.LayerSelection({"wyre": frozenset({"cables", "docs_elements"})}, frozenset({"osiris_events", "v_form_lists"}))
    assert sel.layer_count() == 2


def test_empty_selection_has_empty_plan():
    assert bp.selection_from_tiles(set(), ("wyre",), {}).load_plan() == []
    assert bp.selection_from_tiles({"zones"}, (), {}).load_plan() == []


def test_common_tile_state_done_off_on():
    existing = {None: set(bp.tile_keys("osiris"))}
    sel = bp.selection_from_tiles({"osiris"}, (), existing)
    assert bp.tile_state("osiris", sel, (), existing) == "done"
    assert bp.tile_state("cadastre", sel, (), existing) == "off"
    on = bp.selection_from_tiles({"cadastre"}, (), {})
    assert bp.tile_state("cadastre", on, (), {}) == "on"


def test_operator_tile_done_for_one_operator_other_still_pending_is_on_or_off():
    existing = {"wyre": set(bp.tile_keys("cables"))}
    empty = bp.LayerSelection({}, frozenset())
    assert bp.tile_state("cables", empty, ("wyre", "orange"), existing) == "off"


def test_presets_json_shape_and_bad_entries():
    p = bp.UserPreset("A", ("wyre",), bp.LayerSelection({"wyre": frozenset({"cables", "zone_mro"})}, frozenset({"wfs_parcels"})))
    data = json.loads(bp.presets_to_json([p]))
    assert data == [{"name": "A", "schemas": ["wyre"],
                     "per_operator": {"wyre": ["cables", "zone_mro"]}, "common": ["wfs_parcels"]}]
    mixed = json.dumps([data[0], 3, {"name": "", "schemas": []}, {"name": "B", "schemas": "wyre"},
                        {"name": "C", "schemas": ["x; drop"], "per_operator": {}, "common": []}])
    assert bp.presets_from_json(mixed) == [p]
    assert bp.presets_from_json("{}") == [] and bp.presets_from_json("") == [] and bp.presets_from_json(42) == []


def test_tiles_cover_the_catalog(pi):  # noqa: F811
    from constructel_bridge import bridge_project_init as bpi
    tiled = {k for keys in bp.TILE_LAYERS.values() for k in keys}
    assert tiled | bp.ALWAYS_KEYS | bp.OPERATOR_AUTO_KEYS == {e[0] for e in bpi.LAYER_CATALOG}
    assert {k for t in bp.OPERATOR_TILES for k in bp.TILE_LAYERS[t]} == set(bpi.OPERATOR_KEYS) - bp.OPERATOR_AUTO_KEYS
