"""Bridge 2.1.1 : zones gelees OSIRIS servies par la vue
osiris.v_frozen_zones_communs aux logins qui n'ont pas le SELECT sur
osiris.frozen_zones (scope PROJET seul, groupe ftth_reader_communs, Farois
mig 573). Decision prise une fois par connexion ; cle, libelle, groupe, style
et detection « deja chargee » inchanges."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from constructel_bridge import bridge_operators as bo
from constructel_bridge_tests.fakes19 import WYRE, install_fake_project
from constructel_bridge_tests.test_bridge18_connect import _FakeCursor, _logs, _make_plugin
from constructel_bridge_tests.test_bridge18_layers import pi  # noqa: F401  (fixture)
from constructel_bridge_tests.test_bridge20_load import _quiet_plugin, _spy_init_project
from constructel_bridge.bridge_presets import LayerSelection

VIEW = ("osiris", "v_frozen_zones_communs")


# --- module pur : requete et decision -----------------------------------------------------

def test_fallback_table_is_small_and_names_the_view():
    assert bo.CATALOG_FALLBACKS == {"osiris_frozen": (("osiris", "frozen_zones"), VIEW)}


def test_query_reads_the_catalog_with_to_regclass_and_parameters():
    q = bo.CATALOG_SOURCES_QUERY
    assert "has_table_privilege" in q and "to_regclass" in q and "COALESCE" in q and "%s" in q
    assert bo.catalog_sources_params() == (["osiris_frozen"], ["osiris.frozen_zones"], ["osiris.v_frozen_zones_communs"])


@pytest.mark.parametrize("table_ok,view_ok,fallback", [
    (True, True, False),     # login ordinaire : la table
    (True, False, False),    # base sans la mig 573 (pas de vue) : la table
    (False, True, True),     # externe (scope PROJET seul) : la vue
    (False, False, False),   # ni l'une ni l'autre : la table, en erreur de droits comme aujourd'hui
    (None, None, False),
])
def test_parse_catalog_sources(table_ok, view_ok, fallback):
    keys = bo.parse_catalog_sources([("osiris_frozen", table_ok, view_ok)])
    assert keys == (frozenset({"osiris_frozen"}) if fallback else frozenset())


def test_unknown_key_in_rows_is_ignored():
    assert bo.parse_catalog_sources([("autre", False, True), "pas une ligne"]) == frozenset()


# --- catalogue : chargement et « deja chargee » ---------------------------------------------

def test_fallback_entry_matches_the_catalog(pi):  # noqa: F811
    entry = next(e for e in pi.LAYER_CATALOG if e[0] == "osiris_frozen")
    assert (entry[2], entry[3]) == bo.CATALOG_FALLBACKS["osiris_frozen"][0]
    assert pi.catalog_table_ids(entry) == ["osiris.frozen_zones", "osiris.v_frozen_zones_communs"]


def test_ordinary_login_loads_the_table(pi, monkeypatch):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)
    assert pi.init_project({}, "", {"osiris_frozen"}, operator=None) == 1
    assert project.count_pg("osiris", "frozen_zones") == 1 and project.count_pg(*VIEW) == 0


def test_external_login_loads_the_view_with_same_name_key_and_style(pi, monkeypatch):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)
    styled = []
    monkeypatch.setattr(pi, "_apply_embedded_styles", lambda loaded: styled.append(set(loaded)))
    assert pi.init_project({}, "", {"osiris_frozen"}, operator=None, fallback_keys={"osiris_frozen"}) == 1
    (layer,) = project.pg_layers(*VIEW)
    assert project.count_pg("osiris", "frozen_zones") == 0
    assert layer.name() == "frozen_zones"                       # meme nom que la table (traductions, listes)
    source = layer.dataProvider().uri()
    assert source.param("key") == "ogc_fid" and source.geometryColumn() == "geom"   # cle de l'URI : une vue n'en declare pas
    assert styled == [{"osiris_frozen"}]                       # style embarque osiris_frozen_zones.qml
    group = project.layerTreeRoot().children()[0]
    assert group.name() == "Commun" and group.children()[0].name() == "OSIRIS"


@pytest.mark.parametrize("schema_table", [("osiris", "frozen_zones"), VIEW])
def test_layer_loaded_from_either_source_is_recognized(pi, monkeypatch, schema_table):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)
    project.add_pg(*schema_table)
    assert "osiris_frozen" in pi._detect_existing_layers(None)
    assert pi.count_loaded_layers(project).common == 1
    for fallback in (frozenset(), frozenset({"osiris_frozen"})):
        assert pi.init_project({}, "", {"osiris_frozen"}, operator=None, fallback_keys=fallback) == 0
    assert len(project.mapLayers()) == 1


def test_existing_by_schema_marks_the_view_layer_as_loaded(pi, monkeypatch):  # noqa: F811
    project = install_fake_project(pi, monkeypatch)
    project.add_pg(*VIEW)
    assert "osiris_frozen" in pi.existing_by_schema(["wyre"])[None]


# --- plugin : decision a la connexion et passage au chargement ----------------------------------

class _SourcesCursor(_FakeCursor):
    def __init__(self, sources=(("osiris_frozen", True, True),), **kw):
        super().__init__(**kw)
        self.sources = sources

    def execute(self, sql, params=None):
        if sql == bo.CATALOG_SOURCES_QUERY:
            self.executed.append((sql, params))
            self._one, self._all = None, []
            if isinstance(self.sources, Exception):
                raise self.sources
            self._all = list(self.sources)
            return
        super().execute(sql, params)


def _connected(bp18, monkeypatch, tmp_path, **kw):
    cur = _SourcesCursor(**kw)
    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert plugin._connected
    return plugin, cur


def test_ordinary_login_keeps_the_table(bp18, monkeypatch, tmp_path):
    plugin, cur = _connected(bp18, monkeypatch, tmp_path)
    assert plugin._catalog_fallbacks == frozenset()
    assert [s for s in cur.sql() if s == bo.CATALOG_SOURCES_QUERY] == [bo.CATALOG_SOURCES_QUERY]   # une fois


def test_external_login_reads_the_view(bp18, monkeypatch, tmp_path):
    plugin, _cur = _connected(bp18, monkeypatch, tmp_path, sources=(("osiris_frozen", False, True),))
    assert plugin._catalog_fallbacks == frozenset({"osiris_frozen"})
    assert any("osiris.v_frozen_zones_communs" in m for m in _logs())


def test_unreadable_capability_query_keeps_the_table_without_error(bp18, monkeypatch, tmp_path):
    from constructel_bridge_tests.test_bridge18_connect import _PgErr

    plugin, _cur = _connected(bp18, monkeypatch, tmp_path, sources=_PgErr("function to_regclass(text) does not exist"))
    assert plugin._connected and plugin._catalog_fallbacks == frozenset()


def test_load_selection_passes_the_fallback_keys(bp18, pi, monkeypatch, tmp_path):  # noqa: F811
    calls = _spy_init_project(pi, monkeypatch)
    plugin = _quiet_plugin(bp18, monkeypatch, tmp_path)
    plugin._catalog_fallbacks = frozenset({"osiris_frozen"})
    plugin._load_selection([WYRE], LayerSelection({"wyre": frozenset({"cables"})}, frozenset({"osiris_frozen"})),
                           set(), True)
    assert calls[0]["fallback_keys"] == frozenset({"osiris_frozen"})


def test_offline_or_reset_forgets_the_fallbacks(bp18, monkeypatch, tmp_path):
    plugin, _cur = _connected(bp18, monkeypatch, tmp_path, sources=(("osiris_frozen", False, True),))
    plugin._reset_projet_registry()
    assert plugin._catalog_fallbacks == frozenset()


def test_view_layer_is_never_locked_nor_filtered_by_mro(bp18, monkeypatch, tmp_path):
    from constructel_bridge.bridge_nominatif import should_lock_layer

    scope = SimpleNamespace(network_write=False)
    assert should_lock_layer("osiris", scope, ("wyre",)) is False


def test_embedded_style_and_catalog_never_depend_on_zone_mro_id(pi):  # noqa: F811
    from pathlib import Path

    styles = Path(pi.__file__).resolve().parent / "styles"
    assert pi.EMBEDDED_STYLES["osiris_frozen"] == "osiris_frozen_zones.qml"
    assert "zone_mro_id" not in (styles / "osiris_frozen_zones.qml").read_text(encoding="utf-8")
    assert not [r for r in pi.RELATION_DEFS if "osiris_frozen" in r[:2]]      # aucune relation, aucun formulaire lie
