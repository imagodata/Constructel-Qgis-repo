"""Bridge 1.9, tache 9 (spec § 6.1, § 6.2, § 6.4, § 6.6 ; decisions K2, K3,
K14, D11, D12, D15) : ecran d'accueil (solution B) avec la selection actuelle
dans la grande tuile.

  * logique sans Qt (``bridge_home_model``) testee a fond ;
  * ``count_loaded_layers`` / ``_detect_existing_basemaps`` sur le FakeProject
    de fakes19 ;
  * ``HomeDialog`` (2.0, fenetre a barre laterale) : test_bridge20_home.py ;
  * cote plugin, l'ecran est remplace par un enregistreur ; hors connexion,
    des doublures qui echouent si on les touche prouvent que rien ne tente la
    base."""
from __future__ import annotations

import re
import sys
import types
from dataclasses import dataclass, fields
from pathlib import Path

import pytest

from constructel_bridge import bridge_diagnostic as bd
from constructel_bridge import bridge_home_model as hm
from constructel_bridge import bridge_operators as bo
from constructel_bridge.bridge_presets import (
    LAST_SELECTION_KEY,
    USER_PRESETS_KEY,
    LayerSelection,
    UserPreset,
    presets_to_json,
)
from constructel_bridge_tests.fakes19 import (
    ORANGE,
    WYRE,
    FakeLayer,
    FakeRasterLayer,
    install_fake_project,
    load_keys,
)
from constructel_bridge_tests.test_bridge18_layers import (  # noqa: F401  (pi = fixture)
    LOGIN,
    _FakeIface,
    _nominal_plugin,
    _shared_plugin,
    pi,
)
from constructel_bridge_tests.test_bridge19_checkin import onb  # noqa: F401  (fixture)

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "constructel_bridge"
PROXIMUS = bo.OperatorInfo("PROXIMUS", "Proximus", "proximus")


@dataclass(frozen=True)
class Counts:
    """Meme forme que bridge_project_init.LoadedCounts (module Qt : importe
    seulement sous la fixture pi ; test_loaded_counts_shape les garde alignes)."""
    per_operator: dict
    common: int
    basemaps: int
    projet: int = 0      # 2.1 : couches de projets metier


def snap(**kw):
    base = dict(connected=True, header="jdoe · 10 MRO", operators=(WYRE, ORANGE), counts=Counts({}, 0, 0),
                labels={"wyre": "Wyre", "orange": "Orange"}, last_selection=None, project_suffix=None, last_suffix=False,
                plugin_summary=bd.PluginSummary(5, 6, 1), plugin_version="1.9.0", project_operators=())
    return hm.HomeSnapshot(**{**base, **kw})


# Modele de l'ecran (home_state, suffix_state, HomeActions) : voir test_bridge20_home_model.py.


# --- bridge_project_init : couches et fonds deja charges --------------------------------


def test_loaded_counts_shape(pi):
    assert [f.name for f in fields(pi.LoadedCounts)] == [f.name for f in fields(Counts)]


def test_count_loaded_layers_ignores_layers_outside_the_tree(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    project.add_pg("wyre", "cables")
    project.addMapLayer(FakeLayer.pg("wyre", "zone_pop"), False)   # couche fantome d'un QML : sans noeud
    project.addMapLayer(FakeRasterLayer("type=xyz", "OpenStreetMap", "wms"))
    assert pi.count_loaded_layers(project) == pi.LoadedCounts({"wyre": 1}, 0, 1)


def test_count_loaded_layers_counts_common_layers_and_known_schemas(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    mine = project.layerTreeRoot().addGroup("Mes couches")
    for schema, table in (("orange", "cables"), ("orange", "zone_pop"), ("wyre", "ducts"), ("public", "cables"),
                          ("chantier", "interventions"), ("ref", "v_form_lists"),
                          ("docs", "v_element_documents_list")):
        project.add_pg(schema, table, group=mine)
    wfs = FakeLayer("typename='urbisvector:Buildings' url='https://geoservices-vector.irisnet.be'", "Batiments", "WFS")
    project.addMapLayer(wfs)
    counts = pi.count_loaded_layers(project)
    assert list(counts.per_operator.items()) == [("orange", 2), ("wyre", 1), ("public", 1)]   # ordre de l'arbre
    assert (counts.common, counts.basemaps) == (2, 0)   # v_form_lists et Documents : techniques
    known = pi.count_loaded_layers(project, known={"wyre", "orange"})
    assert known.per_operator == {"orange": 2, "wyre": 1} and known.common == 2


def test_count_loaded_layers_counts_each_basemap_once(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    for name in ("OpenStreetMap", "OpenStreetMap", "UrbIS FR", "Ma photo"):
        project.addMapLayer(FakeRasterLayer("type=xyz", name, "wms"))
    assert pi.count_loaded_layers(project).basemaps == 2


def test_detect_existing_basemaps(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    project.addMapLayer(FakeRasterLayer("type=xyz", "OpenStreetMap", "wms"))
    project.add_pg("wyre", "cables")
    assert pi._detect_existing_basemaps() == {"osm"}


def test_detected_basemaps_are_exactly_those_add_basemaps_skips(pi, monkeypatch):
    # D12 : meme regle de nom que _add_basemaps (couches du projet, arbre ou non).
    project = install_fake_project(pi, monkeypatch)
    project.addMapLayer(FakeRasterLayer("type=xyz", "UrbIS FR", "wms"), False)
    assert pi._detect_existing_basemaps() == {"urbis_fr"}
    pi._add_basemaps(project.layerTreeRoot(), {"urbis_fr", "osm"})
    names = [ly.name() for ly in project.mapLayers().values()]
    assert names.count("UrbIS FR") == 1 and names.count("OpenStreetMap") == 1


# --- init_project : couches deja presentes jamais restylees, mais reliees (T9-c2b) ------


def _style_spies(pi, monkeypatch):
    """Cles de couche passees aux styles base / embarques, appel par appel."""
    db, embedded = [], []
    monkeypatch.setattr(pi, "_apply_styles_from_db", lambda _p, _pw, loaded: db.append(set(loaded)) or set())
    monkeypatch.setattr(pi, "_apply_embedded_styles", lambda loaded: embedded.append(set(loaded)))
    return db, embedded


def test_adding_orange_restyles_no_common_layer_already_present(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    db, embedded = _style_spies(pi, monkeypatch)
    pi.init_project({}, "", {"cables", "osiris_frozen", "interventions", "v_form_lists"}, operator=WYRE)
    db.clear(), embedded.clear()

    # Meme si la selection les cite encore (appel direct), les couches communes
    # et v_form_lists deja chargees ne sont ni rechargees ni restylees.
    added = pi.init_project({}, "", {"cables", "osiris_frozen", "interventions", "v_form_lists"}, operator=ORANGE)

    assert added == 1 and project.count_pg("osiris", "frozen_zones") == 1
    assert db == [{"cables@orange"}] and embedded == [{"cables@orange"}]


def test_nothing_added_means_no_style_connection(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    project.add_pg("chantier", "interventions")
    db, embedded = _style_spies(pi, monkeypatch)
    assert pi.init_project({}, "", {"interventions"}, selected_basemaps={"osm"}, operator=WYRE) == 0
    assert db == [] and embedded == []


def test_new_layer_is_related_to_a_layer_already_present(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    ducts = project.add_pg("wyre", "ducts")
    project.add_pg("orange", "ducts")                      # autre operateur : jamais relie a wyre
    docs = project.add_pg("docs", "v_element_documents_list", geom=None, key="link_id")
    project.writeEntry("bridge", "operator", "wyre")
    db, embedded = _style_spies(pi, monkeypatch)

    pi.init_project({}, "", {"subducts"}, operator=WYRE)   # ducts et Documents non selectionnes

    rels = project.relationManager().relations()
    subducts = project.layer("wyre", "subducts")
    assert rels["subducts_to_duct"].referencingLayerId() == subducts.id()
    assert rels["subducts_to_duct"].referencedLayerId() == ducts.id()
    assert rels["docs_element_duct"].referencingLayerId() == docs.id()
    assert not any(i.endswith("__orange") for i in rels)
    assert db == [{"subducts@wyre"}] and embedded == [{"subducts@wyre"}]


def test_present_operator_layer_enters_identity_without_being_selected(pi, monkeypatch):
    # T2-c3 (« ajoutee ou deja presente ») avec une selection qui ne cite
    # plus les couches deja chargees.
    project = install_fake_project(pi, monkeypatch)
    project.add_pg("orange", "cables")
    pi.init_project({}, "", {"interventions"}, operator=ORANGE)
    assert pi.get_bridge_info()["operators"] == ["orange"]
    pi.init_project({}, "", {"incidents"}, operator=WYRE)    # aucune couche wyre : hors identite
    assert pi.get_bridge_info()["operators"] == ["orange"]


# --- doublures de widgets (HomeDialog) : fakes_widgets.py -----------------------------------


def test_init_project_dialog_is_gone(pi):
    assert not hasattr(pi, "InitProjectDialog")


# --- HomeDialog -------------------------------------------------------------------------
# Reecrit en tache 9 (2.0) : la fenetre a barre laterale et ses pages sont testees
# dans test_bridge20_home.py (fenetre), test_bridge20_load_page.py (Charger),
# test_bridge20_projects.py, test_bridge20_checkin.py et test_bridge19_diagnostic.py.
# Chaque regle 1.9 encore valable y est reprise (correspondance : rapport de la
# tache 9) ; les tuiles et le selecteur d'operateur 1.9 ont disparu (spec § 6.1).


def test_home_modules_use_literal_keys_only():
    for name in ("bridge_home.py", "bridge_home_model.py"):
        src = (PLUGIN_DIR / name).read_text(encoding="utf-8")
        assert not re.search(r"\btr\(\s*f[\"']", src) and not re.search(r"\btr\(\s*[a-z_]", src), name


def test_home_texts_in_three_languages():
    from constructel_bridge.i18n.translations import TRANSLATIONS

    fr = TRANSLATIONS["fr"]
    assert fr["menu.init_project"] == "Accueil · charger les couches"
    assert TRANSLATIONS["en"]["menu.init_project"] == "Home · load layers"
    assert TRANSLATIONS["pt"]["menu.init_project"] == "Início · carregar camadas"
    assert fr["home.connect_to_see"] == "Connecte-toi pour voir les opérateurs auxquels tu as accès"
    assert fr["home.suffix_checkbox"] == "Ajouter le nom de l'opérateur aux couches"
    # D11 : le resume ne nomme pas le modele.
    assert " · ".join([fr["home.loaded_operator"].format(operator="Wyre", count=14),
                       fr["home.loaded_basemaps"].format(count=3)]) == "✓ Wyre · 14 couches · 3 fonds de plan"


# --- cote plugin ------------------------------------------------------------------------


class _RecordingHome:
    def __init__(self, actions, parent=None, page="load", start_wizard=False):
        self.actions = actions
        self.parent = parent
        self.page = page
        self.start_wizard = start_wizard
        self.executed = 0
        self.script = []
        self.loads = []
        self.events = []  # "exec", "deleteLater"
        self.deleted = False

    def exec(self):
        self.executed += 1
        self.events.append("exec")
        for step in self.script:
            step(self)
        return 0

    def deleteLater(self):
        self.events.append("deleteLater")
        self.deleted = True


@pytest.fixture
def homes(monkeypatch):
    """Ecran d'accueil remplace par un enregistreur ; ``homes.script`` = gestes
    de l'utilisateur joues pendant exec()."""
    created, script = [], []

    class Home(_RecordingHome):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.script = list(script)
            created.append(self)

    fake = types.ModuleType("constructel_bridge.bridge_home")
    fake.HomeDialog = Home
    monkeypatch.setitem(sys.modules, "constructel_bridge.bridge_home", fake)
    return types.SimpleNamespace(created=created, script=script)


def click_load(selected=frozenset({"cables"}), basemaps=frozenset({"osm"})):
    """Geste : garder les operateurs preselectionnes (modele 2.0) et cliquer
    le bouton principal, s'il est actif ; *selected* = cles operateur de
    chaque operateur coche."""
    def step(dialog):
        state = hm.home_state(dialog.actions.snapshot())
        if state.load_enabled:
            operators = tuple(op for op in state.operators if op.schema in state.preselected)
            selection = LayerSelection({op.schema: frozenset(selected) for op in operators}, frozenset())
            dialog.loads.append(dialog.actions.load(operators, selection, set(basemaps), False, False))
    return step


def test_home_opens_offline(bp18, pi, homes, monkeypatch):            # O1
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._connected = False
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: [])
    plugin._on_home()
    assert len(homes.created) == 1 and homes.created[0].executed == 1
    assert homes.created[0].actions.snapshot().connected is False


def test_home_dialog_is_deleted_after_exec(bp18, pi, homes, monkeypatch):
    # Relecture finale M5 : enfant de la fenetre principale, l'ecran restait
    # en memoire jusqu'a la fin de la session (un par clic).
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._connected = False
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: [])
    plugin._on_home()
    plugin._on_home()
    assert [h.events for h in homes.created] == [["exec", "deleteLater"]] * 2


def test_home_dialog_already_destroyed_is_not_an_error(bp18, pi, homes, monkeypatch):
    def already_deleted(self):
        raise RuntimeError("wrapped C/C++ object of type HomeDialog has been deleted")

    monkeypatch.setattr(_RecordingHome, "deleteLater", already_deleted)
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._connected = False
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: [])
    plugin._on_home()
    assert homes.created[0].executed == 1


def test_home_offline_never_touches_the_database(bp18, pi, onb, homes, monkeypatch):  # noqa: F811
    class _NoDb:
        def __getattr__(self, name):
            raise AssertionError(f"base sollicitee hors connexion : {name}")

    def _connect(*_args, **_kwargs):
        raise AssertionError("psycopg2.connect hors connexion")

    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(connect=_connect, Error=Exception))
    plugin = bp18.ConstructelBridgePlugin(_FakeIface())
    plugin._connected = False
    plugin._conn = _NoDb()
    plugin._operators = [WYRE]   # liste d'une session precedente : jamais montree
    homes.script.append(click_load())

    plugin._on_home()

    snapshot = homes.created[0].actions.snapshot()
    state = hm.home_state(snapshot)
    assert (snapshot.connected, snapshot.header, snapshot.operators) == (False, "", ())
    assert (state.load_enabled, state.message_key, state.operators, state.saved_project_enabled) == (
        False, "home.connect_to_see", (), False)
    assert homes.created[0].loads == []
    assert snapshot.plugin_summary == bd.plugin_summary(plugin._diagnostic_local_checks())


def test_home_snapshot_connected(bp18, pi, monkeypatch, tmp_path):
    from qgis.core import QgsSettings

    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    plugin._operators = [WYRE]
    plugin._operator_registry = {"wyre": WYRE, "orange": ORANGE}
    checks = [bd.Check("plugin", "ok", "diag.plugin_ok", {"name": "A"}),
              bd.Check("plugin", "warning", "diag.plugin_update", {"name": "B"}, "update", "b"),
              bd.Check("plugin", "warning", "diag.plugin_missing", {"name": "C"}, "install", "c"),
              bd.Check("identity", "ok", "diag.identity_ok", {"login": LOGIN})]
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: checks)
    QgsSettings().setValue(bo.LAST_OPERATORS_KEY, "orange")
    QgsSettings().setValue(bo.SUFFIX_SETTINGS_KEY, "true")   # QGIS relit un booleen en texte

    snapshot = plugin.home_snapshot()

    assert snapshot.operators == (WYRE,) and snapshot.header.startswith(LOGIN + " · ")
    assert snapshot.header == f"{LOGIN} · {plugin._scope_text()}"
    assert snapshot.labels == {"wyre": "Wyre", "orange": "Orange"}
    assert snapshot.last_selection == UserPreset("", ("orange",), LayerSelection({}, frozenset()))   # R2 : suit LAST_OPERATORS_KEY
    assert (snapshot.last_suffix, snapshot.project_suffix) == (True, None)
    assert snapshot.user_presets == ()
    assert snapshot.checkin.plugins == snapshot.plugin_summary   # pastille du Check-in (tache 9)
    assert (snapshot.login, snapshot.email) == (LOGIN, "")
    assert snapshot.plugin_summary == bd.PluginSummary(2, 3, 1)
    assert snapshot.plugin_version == bp18.PLUGIN_VERSION
    assert snapshot.counts == pi.LoadedCounts({}, 0, 0) and snapshot.project_operators == ()


def test_home_snapshot_reads_the_project(bp18, pi, monkeypatch, tmp_path):
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    plugin._operators = [WYRE]
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: [])
    project = install_fake_project(pi, monkeypatch)
    monkeypatch.setattr(bp18, "QgsProject", pi.QgsProject)
    for schema in ("wyre", "orange", "public"):
        project.add_pg(schema, "cables")
    project.writeEntry("bridge", "operator", "wyre")
    project.writeEntry("bridge", "operator_labels", bo.format_operator_labels({"wyre": "Wyre (projet)"}))
    project.writeEntry("bridge", "operator_suffix", "0")

    snapshot = plugin.home_snapshot()

    # Schemas operateur connus seulement (registre, identite, wyre) : jamais « Public ».
    assert snapshot.counts.per_operator == {"wyre": 1}
    assert snapshot.project_operators == ("wyre",) and snapshot.project_suffix is False
    assert snapshot.labels == {"wyre": "Wyre"}   # registre / operateurs utilisables avant le projet
    plugin._operator_registry = {"wyre": WYRE, "orange": ORANGE}
    assert plugin.home_snapshot().counts.per_operator == {"wyre": 1, "orange": 1}   # K14 : hors scopes resume


def test_home_snapshot_with_unreadable_operator_list_offers_wyre(bp18, pi, monkeypatch, tmp_path):
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    plugin._operators_unavailable = True
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: [])
    snapshot = plugin.home_snapshot()
    assert snapshot.operators == (bo.FALLBACK_OPERATOR,) and snapshot.labels["wyre"] == "Wyre"
    assert hm.home_state(snapshot).preselected == ("wyre",)
    assert snapshot.last_selection is None   # premiere ouverture : rien de memorise


def test_home_snapshot_survives_unreadable_plugin_lists(bp18, pi, monkeypatch, tmp_path):
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)

    def boom():
        raise RuntimeError("qgis.utils indisponible")

    monkeypatch.setattr(plugin, "_diagnostic_local_checks", boom)
    assert plugin.home_snapshot().plugin_summary is None


# _home_actions : test_bridge20_home.py::test_home_actions_are_wired.


def test_home_snapshot_prefers_the_stored_selection_and_reads_presets(bp18, pi, monkeypatch, tmp_path):
    from qgis.core import QgsSettings

    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    plugin._operators = [WYRE, ORANGE]
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: [])
    stored = UserPreset("last", ("orange",), LayerSelection({"orange": {"cables"}}, {"osiris_events"}))   # nom non vide : presets_from_json ecarte ""
    mine = UserPreset("Mon jeu", ("wyre", "orange"), LayerSelection({"wyre": {"zone_pop"}}, frozenset()))
    QgsSettings().setValue(bo.LAST_OPERATORS_KEY, "wyre")
    QgsSettings().setValue(LAST_SELECTION_KEY, presets_to_json([stored]))
    QgsSettings().setValue(USER_PRESETS_KEY, presets_to_json([mine]))

    snapshot = plugin.home_snapshot()

    assert snapshot.last_selection == stored and snapshot.user_presets == (mine,)
    assert hm.home_state(snapshot).preselected == ("orange",)


def test_save_presets_round_trips_through_the_settings(bp18, monkeypatch, tmp_path, pi):
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin, "_diagnostic_local_checks", lambda: [])
    mine = UserPreset("Mon jeu", ("wyre",), LayerSelection({"wyre": {"cables"}}, {"osiris_events"}))
    plugin._home_actions().save_presets([mine])
    assert plugin.home_snapshot().user_presets == (mine,)


# Clic principal et menus : test_bridge20_home.py::test_toolbar_click_opens_home_on_load
# et ::test_menu_entries_open_home_on_their_page (_on_init_project : ::test_separate_dialogs_are_gone).


def test_load_selection_ignores_an_empty_request(bp18, pi, monkeypatch, tmp_path):   # K2, T9-c1b
    from qgis.core import QgsSettings

    calls = []
    monkeypatch.setattr(pi, "init_project", lambda *a, **k: calls.append(k) or 3)
    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)
    assert load_keys(plugin, WYRE, {"v_form_lists"}, set(), True) == 0
    assert load_keys(plugin, WYRE, set(), set(), True, suffix=True) == 0
    assert calls == [] and QgsSettings().value(bo.LAST_OPERATORS_KEY) is None


def _project_with_basemap_loader(bp18, pi, monkeypatch, added_layers=0):
    """FakeProject + init_project factice qui ajoute les fonds demandes
    absents (comme _add_basemaps) et rend *added_layers*."""
    project = install_fake_project(pi, monkeypatch)
    calls = []

    def fake_init(_params, _pw, selected, add_basemap=True, apply_styles=True, selected_basemaps=None, **kw):
        calls.append((set(selected), set(selected_basemaps or ())))
        names = {ly.name() for ly in project.mapLayers().values()}
        for bm in pi.BASEMAPS:
            if bm["key"] in (selected_basemaps or ()) and bm["name"] not in names:
                project.addMapLayer(FakeRasterLayer(bm["source"], bm["name"], "wms"))
        return added_layers

    monkeypatch.setattr(pi, "init_project", fake_init)
    monkeypatch.setattr(bp18.bridge_sketcher, "apply_all_translations", lambda *a, **k: None)
    return project, calls


def test_basemaps_only_load_counts_the_basemaps(bp18, pi, monkeypatch, tmp_path):   # T9-c1b
    project, calls = _project_with_basemap_loader(bp18, pi, monkeypatch)
    project.addMapLayer(FakeRasterLayer("type=xyz", "OpenStreetMap", "wms"))   # deja la : non compte
    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)

    assert load_keys(plugin, WYRE, {"v_form_lists"}, {"osm", "urbis_fr", "google_roads"}, True) == 2

    assert calls == [({"v_form_lists"}, {"osm", "urbis_fr", "google_roads"})]
    assert plugin.iface.messageBar().messages[-1][2] == bp18.tr("init.success_basemaps", count=2)


def test_layers_and_basemaps_are_both_counted(bp18, pi, monkeypatch, tmp_path):   # T9-c1b
    _project, _calls = _project_with_basemap_loader(bp18, pi, monkeypatch, added_layers=3)
    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)
    assert load_keys(plugin, WYRE, {"cables"}, {"osm"}, True) == 4
    assert plugin.iface.messageBar().messages[-1][2] == bp18.tr("init.success", count=3)


def test_load_adding_nothing_returns_zero_and_never_says_success(bp18, pi, monkeypatch, tmp_path):   # T9-c1b
    project, _calls = _project_with_basemap_loader(bp18, pi, monkeypatch)
    project.addMapLayer(FakeRasterLayer("type=xyz", "OpenStreetMap", "wms"))
    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)
    assert load_keys(plugin, WYRE, {"cables"}, {"osm"}, True) == 0
    assert plugin.iface.messageBar().messages[-1][2] == bp18.tr("init.nothing_added")
