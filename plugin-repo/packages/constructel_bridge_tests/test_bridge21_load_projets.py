"""Bridge 2.1, tache 11 : _load_selection enchaine les projets metier coches
apres la chaine operateur (doublures, aucune base)."""
from __future__ import annotations

from constructel_bridge import bridge_operators as bo
from constructel_bridge import bridge_projets as pj
from constructel_bridge.bridge_presets import ALWAYS_KEYS, LayerSelection, selection_from_tiles
from constructel_bridge_tests.fakes19 import ORANGE, WYRE
from constructel_bridge_tests.test_bridge18_layers import pi  # noqa: F401  (fixture)
from constructel_bridge_tests.test_bridge20_load import _quiet_plugin, _spy_init_project

LAYER = pj.ProjetLayer("geofiber_points", "Points", None, "default", "geom", 1)
GOFIBER = pj.ProjetInfo("b3", "GOFIBER", "GoFiber", "WYRE", (LAYER,))
AUTRE = pj.ProjetInfo("c4", "AUTRE", "Autre", None, (pj.ProjetLayer("t", "T", None, "default", None, 0),))


def _spy_projets(pi, monkeypatch, events, fail=(), added=2):  # noqa: F811
    def fake(_params, _pw, projet, tables, apply_styles):
        events.append(("projet", projet.code, set(tables), apply_styles))
        if projet.code in fail:
            raise RuntimeError(f"permission denied for table {projet.code}")
        return added

    monkeypatch.setattr(pi, "load_projet_layers", fake)


def _spy_all(pi, monkeypatch, fail_ops=(), fail_projets=()):  # noqa: F811
    events = []
    calls = _spy_init_project(pi, monkeypatch, fail=fail_ops, added=3)
    real = pi.init_project

    def init(*a, **kw):
        events.append(("operator", kw["operator"].schema if kw["operator"] else None, set(a[2])))
        return real(*a, **kw)

    monkeypatch.setattr(pi, "init_project", init)
    _spy_projets(pi, monkeypatch, events, fail=fail_projets)
    return events, calls


def test_projets_load_after_operators_and_count_in_total(bp18, pi, monkeypatch, tmp_path):  # noqa: F811
    events, _calls = _spy_all(pi, monkeypatch)
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    plugin._projets = (AUTRE, GOFIBER)
    sel = selection_from_tiles({"cables"}, ["wyre"], {})
    sel = LayerSelection(sel.per_operator, sel.common, {"GOFIBER": frozenset({"geofiber_points"}), "AUTRE": frozenset({"t"})})
    assert plugin._load_selection([WYRE], sel, set(), True) == 3 + 2 + 2
    assert [e[:2] for e in events] == [("operator", "wyre"), ("projet", "AUTRE"), ("projet", "GOFIBER")]
    assert plugin.iface.messageBar().messages[0][2] == bp18.tr("init.success", count=7)


def test_projet_only_with_none_loads_form_lists_then_projet(bp18, pi, monkeypatch, tmp_path):  # noqa: F811
    events, _calls = _spy_all(pi, monkeypatch)
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    plugin._projets = (GOFIBER,)
    sel = LayerSelection({}, frozenset(), {"GOFIBER": frozenset({"geofiber_points"})})
    assert plugin._load_selection([], sel, set(), False) == 3 + 2
    assert events[0] == ("operator", None, set(ALWAYS_KEYS))
    assert events[1] == ("projet", "GOFIBER", {"geofiber_points"}, False)


def test_failing_projet_does_not_cancel_operators_and_is_reported(bp18, pi, monkeypatch, tmp_path):  # noqa: F811
    events, _calls = _spy_all(pi, monkeypatch, fail_projets=("GOFIBER",))
    errors = []
    monkeypatch.setattr(bp18.QMessageBox, "critical", staticmethod(lambda *a, **k: errors.append(a)))
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    plugin._projets = (GOFIBER,)
    sel = selection_from_tiles({"cables"}, ["wyre"], {})
    sel = LayerSelection(sel.per_operator, sel.common, {"GOFIBER": frozenset({"geofiber_points"})})
    assert plugin._load_selection([WYRE], sel, set(), True) == 3
    messages = [m[2] for m in plugin.iface.messageBar().messages]
    assert messages == [bp18.tr("init.success", count=3), bp18.tr("home.load_partial", operators="GoFiber")]
    assert errors == []


def test_unknown_projet_code_is_reported_not_raised(bp18, pi, monkeypatch, tmp_path):  # noqa: F811
    events, _calls = _spy_all(pi, monkeypatch)
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    plugin._projets = (GOFIBER,)
    sel = LayerSelection({"wyre": frozenset({"cables"})}, frozenset(), {"DISPARU": frozenset({"t"})})
    assert plugin._load_selection([WYRE], sel, set(), True) == 3
    assert plugin.iface.messageBar().messages[-1][2] == bp18.tr("home.load_partial", operators="DISPARU")


def test_only_projet_failing_reports_init_error(bp18, pi, monkeypatch, tmp_path):  # noqa: F811
    # L'entree None (listes de formulaires) reussit sans rien ajouter : pas
    # d'erreur bloquante, mais le projet metier est signale.
    events, _calls = _spy_all(pi, monkeypatch, fail_projets=("GOFIBER",))
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    plugin._projets = (GOFIBER,)
    sel = LayerSelection({}, frozenset(), {"GOFIBER": frozenset({"geofiber_points"})})
    plugin._load_selection([], sel, set(), True)
    assert plugin.iface.messageBar().messages[-1][2] == bp18.tr("home.load_partial", operators="GoFiber")


def test_projet_selection_never_writes_last_operators(bp18, pi, monkeypatch, tmp_path):  # noqa: F811
    from qgis.core import QgsSettings

    _spy_all(pi, monkeypatch)
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    plugin._projets = (GOFIBER,)
    QgsSettings().setValue(bo.LAST_OPERATORS_KEY, "orange")
    sel = LayerSelection({}, frozenset(), {"GOFIBER": frozenset({"geofiber_points"})})
    plugin._load_selection([ORANGE], sel, set(), True)
    assert QgsSettings().value(bo.LAST_OPERATORS_KEY) == "orange"
