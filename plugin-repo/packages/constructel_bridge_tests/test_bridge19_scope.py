"""Bridge 1.9 : lecture seule et noms du perimetre sur tous les schemas
operateurs (plan 2026-11-12, tache 5 ; spec O6 et § 7 ; decisions K8, K13).
Doublures seulement, jamais de base reelle."""
from __future__ import annotations

from constructel_bridge import bridge_nominatif as bn
from constructel_bridge import bridge_operators as bo
from constructel_bridge_tests.fakes19 import ORANGE, WYRE
from constructel_bridge_tests.test_bridge18_connect import (
    _FakeCursor,
    _PgErr,
    _logs,
    _make_plugin,
)
from constructel_bridge_tests.test_bridge18_scope import VIEWER
from constructel_bridge_tests.test_bridge18_scope import _layer, _plugin, _src

M1 = "11111111-aaaa-aaaa-aaaa-111111111111"
M2 = "22222222-bbbb-bbbb-bbbb-222222222222"
P1 = "33333333-cccc-cccc-cccc-333333333333"
P2 = "44444444-dddd-dddd-dddd-444444444444"
BOTH = [("ORANGE", "Orange", "orange", True), ("WYRE", "Wyre", "wyre", True)]
SCOPE = ("VIEWER", True, False, [M1, M2], [], [P1, P2], [])


def _zone_sql(cur, dim):
    return [s for s in cur.sql() if f".zone_{dim}" in s]


# --- should_lock_layer -------------------------------------------------------


def test_should_lock_layer_all_operator_schemas():
    ro = bn.parse_session_scope(("VIEWER", True, False, ["m1"], [], [], []))
    ops = {"wyre", "orange"}
    assert bn.should_lock_layer("orange", ro, ops) is True
    assert bn.should_lock_layer("wyre", ro, ops) is True
    assert bn.should_lock_layer("chantier", ro, ops) is False
    assert bn.should_lock_layer("orange", ro) is False  # defaut historique : wyre seul
    assert bn.should_lock_layer("wyre", ro) is True
    assert bn.should_lock_layer("orange", None, ops) is False


def test_should_lock_layer_never_with_network_write():
    rw = bn.parse_session_scope(("DESIGNER", True, True, ["m1"], ["m1"], [], []))
    assert bn.should_lock_layer("orange", rw, {"wyre", "orange"}) is False


# --- _operator_schemas -------------------------------------------------------


def test_operator_schemas_default_is_wyre_only(bp18, monkeypatch):
    plugin = _plugin(bp18, monkeypatch, VIEWER)
    assert plugin._operator_schemas() == frozenset({"wyre"})


def test_operator_schemas_union_registry_and_project_identity(bp18, monkeypatch):
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, VIEWER)
    plugin._operator_registry = {"orange": ORANGE}
    QgsProject.instance().writeEntry("bridge", "operator", "proximus,x\";drop,orange")
    assert plugin._operator_schemas() == frozenset({"wyre", "orange", "proximus"})


# --- verrou de lecture seule -------------------------------------------------


def test_viewer_locks_every_operator_schema(bp18, monkeypatch):
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, VIEWER)
    plugin._operator_registry = {"orange": ORANGE, "wyre": WYRE}
    layers = {
        "wyre": _layer(_src("wyre", "ducts"), "Conduites Wyre"),
        "orange": _layer(_src("orange", "ducts"), "Conduites Orange"),
        "chantier": _layer(_src("chantier", "permis_voirie"), "Permis"),
    }
    for layer in layers.values():
        QgsProject.instance().addMapLayer(layer)

    assert plugin._apply_scope_to_layers() == 2
    assert layers["wyre"].read_only is True
    assert layers["orange"].read_only is True
    assert layers["chantier"].read_only is False


def test_project_operator_absent_from_registry_is_still_locked(bp18, monkeypatch):
    # K13 : operateur du projet inactif / non instancie : couche verrouillee quand meme.
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, VIEWER)
    plugin._operator_registry = {"wyre": WYRE}
    QgsProject.instance().writeEntry("bridge", "operator", "wyre,proximus")
    prox = _layer(_src("proximus", "ducts"), "Conduites Proximus")
    other = _layer(_src("telenet", "ducts"), "Conduites Telenet")
    for layer in (prox, other):
        QgsProject.instance().addMapLayer(layer)

    assert plugin._apply_scope_to_layers() == 1
    assert prox.read_only is True
    assert other.read_only is False


def test_unlisted_operator_schema_is_not_locked_without_identity(bp18, monkeypatch):
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, VIEWER)
    layer = _layer(_src("orange", "ducts"))
    QgsProject.instance().addMapLayer(layer)

    assert plugin._apply_scope_to_layers() == 0
    assert layer.read_only is False


def test_designer_never_locks_operator_schemas(bp18, monkeypatch):
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, ("DESIGNER", True, True, ["m1"], ["m1"], [], []))
    plugin._operator_registry = {"orange": ORANGE}
    layer = _layer(_src("orange", "ducts"))
    QgsProject.instance().addMapLayer(layer)

    assert plugin._apply_scope_to_layers() == 0
    assert layer.read_only is False


# --- noms du perimetre -------------------------------------------------------


def _connect(bp18, monkeypatch, tmp_path, cur):
    plugin, _calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")
    plugin._auto_connect()
    return plugin


def test_scope_names_resolved_in_every_usable_schema(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(scope_row=SCOPE, operator_rows=BOTH, mro_names=[(M1, "Anderlecht")],
                      pop_names=[(P1, "POP_01")],
                      extra_names={"orange": ([(M2, "Gent")], [(P2, "POP_02")])})
    plugin = _connect(bp18, monkeypatch, tmp_path, cur)

    assert plugin._scope_names[0] == {M1: "Anderlecht", M2: "Gent"}
    assert plugin._scope_names[1] == {P1: "POP_01", P2: "POP_02"}
    assert _zone_sql(cur, "mro") == [
        'SELECT id::text, name FROM "orange".zone_mro WHERE id = ANY(%s::uuid[])',
        'SELECT id::text, name FROM "wyre".zone_mro WHERE id = ANY(%s::uuid[])']
    assert _zone_sql(cur, "pop") == [
        'SELECT id::text, code FROM "orange".zone_pop WHERE id = ANY(%s::uuid[])',
        'SELECT id::text, code FROM "wyre".zone_pop WHERE id = ANY(%s::uuid[])']
    assert all(p == ([M1, M2],) for (s, p) in cur.executed if ".zone_mro" in s)


def test_unreadable_schema_keeps_other_names(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(scope_row=SCOPE, operator_rows=BOTH, mro_names=[(M1, "Anderlecht")],
                      pop_names=[(P1, "POP_01")],
                      extra_names={"orange": ([(M2, "Gent")], [(P2, "POP_02")])},
                      denied_schemas={"orange"})
    plugin = _connect(bp18, monkeypatch, tmp_path, cur)

    assert plugin._scope_names[0] == {M1: "Anderlecht"}
    assert plugin._scope_names[1] == {P1: "POP_01"}
    assert any("Noms des zones du perimetre illisibles" in m and "orange" in m for m in _logs())


def test_no_name_query_when_a_dimension_is_empty(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(scope_row=("VIEWER", True, False, [M1], [], [], []), operator_rows=BOTH,
                      mro_names=[(M1, "Anderlecht")])
    plugin = _connect(bp18, monkeypatch, tmp_path, cur)

    assert plugin._scope_names == ({M1: "Anderlecht"}, {})
    assert _zone_sql(cur, "pop") == []


def test_names_fall_back_to_wyre_when_registry_unreadable(bp18, monkeypatch, tmp_path):
    # K8 : liste des operateurs illisible -> comportement 1.8.4.
    cur = _FakeCursor(scope_row=SCOPE, operator_rows=_PgErr("permission denied for table operateurs"),
                      mro_names=[(M1, "Anderlecht")], pop_names=[(P1, "POP_01")],
                      extra_names={"orange": ([(M2, "Gent")], [])})
    plugin = _connect(bp18, monkeypatch, tmp_path, cur)

    assert plugin._operators_unavailable is True
    assert plugin._scope_names == ({M1: "Anderlecht"}, {P1: "POP_01"})
    assert len(_zone_sql(cur, "mro")) == 1 and '"wyre".zone_mro' in _zone_sql(cur, "mro")[0]


def test_names_fall_back_to_wyre_when_no_usable_operator(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(scope_row=SCOPE, operator_rows=[], mro_names=[(M1, "Anderlecht")])
    plugin = _connect(bp18, monkeypatch, tmp_path, cur)

    assert plugin._operators == []
    assert plugin._scope_names[0] == {M1: "Anderlecht"}
    assert '"wyre".zone_mro' in _zone_sql(cur, "mro")[0]


def test_unsafe_schema_is_never_interpolated(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(scope_row=SCOPE, mro_names=[(M1, "Anderlecht")])
    plugin, _calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")
    plugin._auto_connect()
    plugin._operators = [bo.OperatorInfo("X", "X", 'x"; drop schema wyre', True),
                         bo.OperatorInfo("O", "Orange", "orange", True)]
    plugin._operators_unavailable = False
    cur.executed.clear()

    plugin._read_session_scope()

    assert _zone_sql(cur, "mro") == ['SELECT id::text, name FROM "orange".zone_mro WHERE id = ANY(%s::uuid[])']
    assert not any("drop" in s for s in cur.sql())


def test_reserved_word_schema_is_quoted(bp18, monkeypatch, tmp_path):
    # Relecture finale M2 : un schema operateur nomme comme un mot reserve
    # (user, order...) passe is_safe_schema ; non quote, le SQL echouerait.
    cur = _FakeCursor(scope_row=SCOPE, mro_names=[(M1, "Anderlecht")])
    plugin, _calls, _asked, _cur = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")
    plugin._auto_connect()
    plugin._operators = [bo.OperatorInfo("USER", "User", "user", True)]
    plugin._operators_unavailable = False
    cur.executed.clear()

    plugin._read_session_scope()

    assert _zone_sql(cur, "mro") == ['SELECT id::text, name FROM "user".zone_mro WHERE id = ANY(%s::uuid[])']
    assert _zone_sql(cur, "pop") == ['SELECT id::text, code FROM "user".zone_pop WHERE id = ANY(%s::uuid[])']
