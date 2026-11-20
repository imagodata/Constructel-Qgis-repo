"""Bridge 2.1 — etat de l'accueil avec projets metier et disponibilite des projets QGIS."""
from __future__ import annotations

from dataclasses import dataclass

from constructel_bridge import bridge_home_model as hm
from constructel_bridge import bridge_projets as pj
from constructel_bridge.bridge_presets import LayerSelection, UserPreset
from constructel_bridge_tests.fakes19 import ORANGE, WYRE


@dataclass(frozen=True)
class Counts:
    per_operator: dict
    common: int
    basemaps: int
    projet: int = 0


FULL = pj.ProjetCapabilities(True, True, True, True, True, True, True)
LAYER = (pj.ProjetLayer("t", "T", None, "default", "geom", 0),)
GOFIBER = pj.ProjetInfo("g", "GOFIBER", "GoFiber", "WYRE", LAYER)
ORFEO = pj.ProjetInfo("o", "ORFEO", "Orfeo", "ORANGE", LAYER)
LIBRE = pj.ProjetInfo("l", "LIBRE", "Libre", None, LAYER)


def last(schemas=(), projets=None):
    return UserPreset("", tuple(schemas), LayerSelection({}, frozenset(), projets or {}))


def snap(**kw):
    base = dict(connected=True, header="jdoe", operators=(WYRE, ORANGE), counts=Counts({}, 0, 0),
                labels={"wyre": "Wyre", "orange": "Orange"}, last_selection=None, project_suffix=None,
                last_suffix=False, login="jdoe", projets=(GOFIBER, ORFEO, LIBRE), capabilities=FULL,
                nominative=True, operator_code_labels=(("WYRE", "Wyre"), ("ORANGE", "Orange")))
    return hm.HomeSnapshot(**{**base, **kw})


def test_projet_groups_hidden_offline_or_without_registry():
    assert hm.home_state(snap(connected=False)).projet_groups == ()
    assert hm.home_state(snap(capabilities=pj.NO_CAPABILITIES)).projet_groups == ()
    assert hm.home_state(snap(projets=())).projet_groups == ()


def test_projet_groups_follow_usable_operator_order():
    groups = hm.home_state(snap(operators=(ORANGE, WYRE))).projet_groups
    assert [op for op, _ps in groups] == ["ORANGE", "WYRE", None]
    groups = hm.home_state(snap()).projet_groups
    assert [op for op, _ps in groups] == ["WYRE", "ORANGE", None]


def test_preselected_projets_from_last_selection_still_visible():
    sel = last(projets={"GOFIBER": frozenset({"t"}), "OLD": frozenset({"u"})})
    assert hm.home_state(snap(last_selection=sel, projets=(GOFIBER,))).preselected_projets == ("GOFIBER",)
    assert hm.home_state(snap()).preselected_projets == ()


def test_projets_work_without_any_operator():
    state = hm.home_state(snap(operators=(), projets=(GOFIBER,)))
    assert state.load_enabled and state.projet_groups == (("WYRE", (GOFIBER,)),)


def test_qgis_reason_offline_unavailable_nominative_ready():
    assert hm.home_state(snap(connected=False)).qgis_reason == hm.QGIS_OFFLINE
    assert hm.home_state(snap(capabilities=pj.ProjetCapabilities(registry=True))).qgis_reason == hm.QGIS_UNAVAILABLE
    assert hm.home_state(snap(nominative=False)).qgis_reason == hm.QGIS_NOMINATIVE
    assert hm.home_state(snap()).qgis_reason == ""


def test_2_0_fields_unchanged_by_the_2_1_ones():
    state = hm.home_state(snap())
    assert state.preselected == ("wyre",) and state.operators == (WYRE, ORANGE)


def test_home_actions_without_qgis_still_builds():
    fn = lambda *a, **k: None  # noqa: E731
    actions = hm.HomeActions(fn, fn, fn, fn, fn, fn, fn, fn, fn, fn, fn)
    assert actions.qgis is None


def test_snapshot_2_0_constructor_still_valid():
    s = hm.HomeSnapshot(True, "", (), Counts({}, 0, 0), {}, None, None, False)
    assert s.projets == () and s.capabilities == pj.NO_CAPABILITIES and s.nominative is False
    assert s.opened_qgis_project is None
