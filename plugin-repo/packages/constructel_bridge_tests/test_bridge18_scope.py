"""Bridge 1.8 — perimetre effectif dans QGIS (plan 2026-10-29 volet D2) :
sans capacite network.write, les couches des schemas reseau de nos serveurs
passent en lecture seule (la barriere reelle reste le serveur : RLS + trigger
ref.trg_enforce_gis_scope) ; un refus serveur (42501, RLS, perimetre) sur un
commit est traduit en message clair. Stub-level, pas de QGIS reel.
"""
from types import SimpleNamespace

import pytest

from constructel_bridge import bridge_nominatif as bn
from constructel_bridge_tests.conftest import HOST18

LOGIN = "jdoe"


class _FakeMessageBar:
    def __init__(self):
        self.messages = []

    def pushSuccess(self, title, message):
        self.messages.append(("success", title, message))

    def pushWarning(self, title, message):
        self.messages.append(("warning", title, message))

    def pushCritical(self, title, message):
        self.messages.append(("critical", title, message))

    def pushMessage(self, title, message, level=None, duration=None):
        self.messages.append(("message", title, message))

    def warnings(self):
        return [m for (k, _t, m) in self.messages if k == "warning"]


class _FakeIface:
    def __init__(self):
        self._bar = _FakeMessageBar()

    def mainWindow(self):
        return None

    def messageBar(self):
        return self._bar

    def activeLayer(self):
        return None


class _Signal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def disconnect(self, slot=None):
        if slot is None:
            self.slots = []
        elif slot in self.slots:
            self.slots.remove(slot)
        else:
            raise TypeError("not connected")

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


def _layer(source, name="couche"):
    from qgis.core import QgsDataSourceUri, QgsVectorLayer

    class _Provider:
        def __init__(self, uri_str):
            self._uri = QgsDataSourceUri(uri_str)

        def name(self):
            return "postgres"

        def uri(self):
            return self._uri

    class _Layer(QgsVectorLayer):
        def __init__(self):
            self._src = source
            self._provider = _Provider(source)
            self.read_only = False
            self.beforeCommitChanges = _Signal()
            self.raiseError = _Signal()

        def name(self):
            return name

        def source(self):
            return self._src

        def providerType(self):
            return "postgres"

        def dataProvider(self):
            return self._provider

        def isValid(self):
            return True

        def isReadOnly(self):
            return self.read_only

        def setReadOnly(self, ro):
            if ro and self.editing:  # QgsVectorLayer : refuse en cours d'edition
                return False
            self.read_only = ro
            return True

    layer = _Layer()
    layer.editing = False
    return layer


def _src(schema, table, host=HOST18):
    return f"dbname='test_db' host={host} port=5432 user='{LOGIN}' authcfg=9i19s56 sslmode=verify-full table=\"{schema}\".\"{table}\" (geom)"


def _plugin(bp, monkeypatch, scope_row=None, mode=bn.AUTH_MODE_NOMINAL):
    from qgis.core import QgsSettings

    QgsSettings().setValue("constructel_bridge/onboarding_done", True)
    monkeypatch.setattr(bp.bridge_sketcher, "apply_to_layer", lambda layer, lang=None: None)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())
    plugin._auth_mode = mode
    plugin._pg_login = LOGIN if mode == bn.AUTH_MODE_NOMINAL else ""
    plugin._connected = True
    plugin._bridge_user = "JDoe"
    plugin._scope = bn.parse_session_scope(scope_row) if scope_row else None
    return plugin


VIEWER = ("VIEWER", True, False, ["m1"], [], [], [])
DESIGNER = ("DESIGNER", True, True, ["m1"], ["m1"], [], [])


def _five_layers():
    return {
        "ducts": _layer(_src("wyre", "ducts"), "Conduites"),
        "osiris": _layer(_src("osiris", "worksites"), "Chantiers"),
        "chantier": _layer(_src("chantier", "permis_voirie"), "Permis"),
        "docs": _layer(_src("docs", "documents"), "Documents"),
        "public": _layer(_src("public", "geofiber_asbuilt_depth_points"), "Profondeurs"),
        "ref": _layer(_src("ref", "v_form_lists"), "v_form_lists"),
        "foreign": _layer(_src("wyre", "ducts", host="other.example.com"), "Ailleurs"),
    }


def test_read_only_session_locks_network_layers_only(bp18, monkeypatch):
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, VIEWER)
    layers = _five_layers()
    for layer in layers.values():
        QgsProject.instance().addMapLayer(layer)

    locked = plugin._apply_scope_to_layers()

    # Revue 29/10 (I8) : schema wyre seulement (chantier/docs : spec D11).
    assert locked == 1
    assert layers["ducts"].read_only is True
    for name in ("osiris", "chantier", "docs", "public", "ref", "foreign"):
        assert layers[name].read_only is False, name
    assert bp18.tr("scope.layers_locked", count=1) in plugin.iface.messageBar().warnings()


def test_lock_is_idempotent_and_silent_the_second_time(bp18, monkeypatch):
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, VIEWER)
    QgsProject.instance().addMapLayer(_layer(_src("wyre", "ducts")))

    assert plugin._apply_scope_to_layers() == 1
    assert plugin._apply_scope_to_layers() == 0
    assert len(plugin.iface.messageBar().warnings()) == 1


def test_write_capability_never_locks(bp18, monkeypatch):
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, DESIGNER)
    layer = _layer(_src("wyre", "ducts"))
    QgsProject.instance().addMapLayer(layer)

    assert plugin._apply_scope_to_layers() == 0
    assert layer.read_only is False


def test_shared_mode_never_locks(bp18, monkeypatch):
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, VIEWER, mode=bn.AUTH_MODE_SHARED)
    layer = _layer(_src("wyre", "ducts"))
    QgsProject.instance().addMapLayer(layer)

    assert plugin._apply_scope_to_layers() == 0
    assert layer.read_only is False


def test_unknown_scope_never_locks(bp18, monkeypatch):
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, None)
    layer = _layer(_src("wyre", "ducts"))
    QgsProject.instance().addMapLayer(layer)

    assert plugin._apply_scope_to_layers() == 0


def test_layers_added_later_are_locked_too(bp18, monkeypatch):
    # M8 : branche au niveau du projet courant, projet Bridge ou non.
    plugin = _plugin(bp18, monkeypatch, VIEWER)
    layer = _layer(_src("wyre", "cables"), "Cables")

    plugin._on_layers_added_scope([layer])

    assert layer.read_only is True


# --- refus d'ecriture traduit (42501 / RLS / perimetre) ------------------------


def test_hooked_layer_translates_scope_refusal(bp18, monkeypatch):
    plugin = _plugin(bp18, monkeypatch, DESIGNER)
    layer = _layer(_src("wyre", "cables"), "Cables")

    plugin._hook_single_layer(layer)
    layer.raiseError.emit('ERROR:  new row violates row-level security policy for table "cables"')

    assert bp18.tr("scope.write_refused_perimeter", layer="Cables") in plugin.iface.messageBar().warnings()


def test_hooked_layer_ignores_unrelated_errors(bp18, monkeypatch):
    plugin = _plugin(bp18, monkeypatch, DESIGNER)
    layer = _layer(_src("wyre", "cables"), "Cables")

    plugin._hook_single_layer(layer)
    layer.raiseError.emit("ERROR: duplicate key value violates unique constraint")

    assert plugin.iface.messageBar().warnings() == []


def test_hooking_twice_does_not_duplicate_the_refusal_banner(bp18, monkeypatch):
    plugin = _plugin(bp18, monkeypatch, DESIGNER)
    layer = _layer(_src("wyre", "cables"), "Cables")

    plugin._hook_single_layer(layer)
    plugin._hook_single_layer(layer)
    layer.raiseError.emit("permission denied for table cables")

    assert len(plugin.iface.messageBar().warnings()) == 1


def test_shared_mode_refusal_is_not_translated_as_scope(bp18, monkeypatch):
    # Postes en repli : ftth_editor voit tout (D6), un refus n'est pas un perimetre.
    plugin = _plugin(bp18, monkeypatch, None, mode=bn.AUTH_MODE_SHARED)
    layer = _layer(_src("wyre", "cables"), "Cables")

    plugin._hook_single_layer(layer)
    layer.raiseError.emit("permission denied for table cables")

    assert plugin.iface.messageBar().warnings() == []


# --- revue 29/10 : verrou leve quand la session change, jamais persiste (I8) ----


def test_lock_is_lifted_when_the_session_falls_back_to_shared(bp18, monkeypatch):
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, VIEWER)
    mine = _layer(_src("wyre", "ducts"))
    user_locked = _layer(_src("wyre", "cables"))
    user_locked.read_only = True  # verrou pose par la personne : jamais touche
    for layer in (mine, user_locked):
        QgsProject.instance().addMapLayer(layer)
    plugin._apply_scope_to_layers()
    assert mine.read_only is True

    plugin._auth_mode = bn.AUTH_MODE_SHARED
    plugin._scope = None
    plugin._apply_scope_to_layers()

    assert mine.read_only is False
    assert user_locked.read_only is True
    assert plugin._locked_layer_ids == set()


def test_lock_is_lifted_when_write_capability_appears(bp18, monkeypatch):
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, VIEWER)
    layer = _layer(_src("wyre", "ducts"))
    QgsProject.instance().addMapLayer(layer)
    plugin._apply_scope_to_layers()

    plugin._scope = bn.parse_session_scope(DESIGNER)  # Reessayer apres changement de role
    plugin._apply_scope_to_layers()

    assert layer.read_only is False


def test_layer_in_edit_mode_is_reported_not_counted(bp18, monkeypatch):
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, VIEWER)
    layer = _layer(_src("wyre", "ducts"), "Conduites")
    layer.editing = True
    QgsProject.instance().addMapLayer(layer)

    assert plugin._apply_scope_to_layers() == 0
    assert layer.read_only is False
    assert plugin._locked_layer_ids == set()
    assert bp18.tr("scope.layers_lock_busy", names="Conduites") in plugin.iface.messageBar().warnings()


def test_unload_releases_every_lock_of_the_plugin(bp18, monkeypatch):
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, VIEWER)
    layer = _layer(_src("wyre", "ducts"))
    QgsProject.instance().addMapLayer(layer)
    plugin._apply_scope_to_layers()

    plugin._release_scope_locks()

    assert layer.read_only is False


class _Elem:
    def __init__(self, text="", children=None, attrs=None):
        self._text = text
        self._children = children or {}
        self.attrs = dict(attrs or {})

    def isNull(self):
        return False

    def text(self):
        return self._text

    def toElement(self):
        return self

    def firstChildElement(self, name):
        return self._children.get(name, _Elem())

    def setAttribute(self, name, value):
        self.attrs[name] = value


def test_plugin_lock_is_not_written_into_the_project(bp18, monkeypatch):
    from qgis.core import QgsProject

    plugin = _plugin(bp18, monkeypatch, VIEWER)
    layer = _layer(_src("wyre", "ducts"))
    layer._layer_id = "ducts_1234"
    QgsProject.instance().addMapLayer(layer)
    plugin._apply_scope_to_layers()
    ours = _Elem(children={"id": _Elem("ducts_1234")}, attrs={"readOnly": "1"})
    theirs = _Elem(children={"id": _Elem("other_9")}, attrs={"readOnly": "1"})
    doc = SimpleNamespace(elementsByTagName=lambda _t: SimpleNamespace(
        count=lambda: 2, at=lambda i: [ours, theirs][i]))

    plugin._strip_scope_locks_from_dom(doc)

    assert ours.attrs["readOnly"] == "0"
    assert theirs.attrs["readOnly"] == "1"


# --- M6 / M7 ----------------------------------------------------------------


def test_error_slots_are_keyed_by_layer_id_and_disconnected_on_unload(bp18, monkeypatch):
    plugin = _plugin(bp18, monkeypatch, DESIGNER)
    layer = _layer(_src("wyre", "cables"), "Cables")
    layer._layer_id = "cables_1"

    plugin._hook_single_layer(layer)
    assert list(plugin._layer_error_slots) == ["cables_1"]
    assert len(layer.raiseError.slots) == 1

    plugin._unhook_layers()

    assert layer.raiseError.slots == []
    assert plugin._layer_error_slots == {}


@pytest.mark.parametrize("message, key", [
    ("ERROR:  permission denied for table cables", "scope.write_refused_right"),
    ("ERREUR:  droit refusé pour la table cables", "scope.write_refused_right"),
    ("SQLSTATE 42501", "scope.write_refused"),
])
def test_missing_right_is_not_reported_as_out_of_perimeter(bp18, monkeypatch, message, key):
    plugin = _plugin(bp18, monkeypatch, DESIGNER)
    layer = _layer(_src("wyre", "cables"), "Cables")

    plugin._hook_single_layer(layer)
    layer.raiseError.emit(message)

    assert plugin.iface.messageBar().warnings() == [bp18.tr(key, layer="Cables")]
