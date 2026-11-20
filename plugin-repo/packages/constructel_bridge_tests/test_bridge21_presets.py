"""Bridge 2.1 — selection et presets portent les couches des projets metier."""
from __future__ import annotations

from constructel_bridge import bridge_presets as bp


def test_projet_layers_count_but_never_enter_the_load_plan():
    sel = bp.LayerSelection({}, frozenset(), {"GOFIBER": frozenset({"t1", "t2"}), "VIDE": frozenset()})
    assert sel.projet == {"GOFIBER": frozenset({"t1", "t2"})} and sel.layer_count() == 2 and not sel.is_empty()
    assert sel.load_plan() == []


def test_projet_with_operator_keeps_the_operator_plan():
    sel = bp.LayerSelection({"wyre": frozenset({"cables"})}, frozenset(), {"GOFIBER": frozenset({"t1"})})
    assert [schema for schema, _keys in sel.load_plan()] == ["wyre"] and sel.layer_count() == 2


def test_old_selections_still_compare_equal():
    assert bp.LayerSelection({}, frozenset({"osiris_events"})) == bp.LayerSelection({}, frozenset({"osiris_events"}), {})


def test_json_round_trip_with_projets_and_old_json_without():
    p = bp.UserPreset("x", (), bp.LayerSelection({}, frozenset(), {"GOFIBER": frozenset({"t1"})}))
    assert bp.presets_from_json(bp.presets_to_json([p])) == [p]
    assert bp.presets_from_json('[{"name": "old", "schemas": [], "common": ["osiris_events"]}]')[0].selection.projet == {}


def test_bad_projet_entry_is_ignored():
    assert bp.presets_from_json('[{"name": "x", "schemas": [], "projets": {"bad code": ["t"]}}]') == []
    assert bp.presets_from_json('[{"name": "x", "schemas": [], "projets": {"GOFIBER": ["Bad-Table"]}}]') == []
    assert bp.presets_from_json('[{"name": "x", "schemas": [], "projets": ["GOFIBER"]}]') == []


def test_restrict_preset_drops_invisible_projets():
    p = bp.UserPreset("x", (), bp.LayerSelection({}, frozenset(), {"GOFIBER": frozenset({"t"}), "OLD": frozenset({"u"})}))
    assert set(bp.restrict_preset(p, [], visible_projets={"GOFIBER"}).selection.projet) == {"GOFIBER"}
    assert set(bp.restrict_preset(p, []).selection.projet) == {"GOFIBER", "OLD"}
