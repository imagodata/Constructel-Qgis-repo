"""Bridge 1.8 — couches et projets en session nominative (plan 2026-10-29
volets B7, B9-QML, C3 ; spec §5.7.7) : jamais de mot de passe en clair,
``user='<login>' authcfg=<id fixe> sslmode=verify-full`` partout (couches
ouvertes, projets enregistres, projets lus en base, couche cachee
ref.v_form_lists, LayerSource des listes de valeurs, initialisation de
projet). Stub-level, pas de QGIS reel.
"""
import os
import sys
import types
from types import SimpleNamespace

import pytest

from constructel_bridge import bridge_nominatif as bn
from constructel_bridge_tests.conftest import CREDS_17, CREDS_18, HOST18

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


class _FakeIface:
    def __init__(self):
        self._bar = _FakeMessageBar()

    def mainWindow(self):
        return None

    def messageBar(self):
        return self._bar

    def activeLayer(self):
        return None


def _make_fake_layer(source, valid=True, provider_type="postgres", name="fake_layer"):
    from qgis.core import QgsDataSourceUri, QgsVectorLayer

    class _FakeProvider:
        def __init__(self, uri_str):
            self._uri = QgsDataSourceUri(uri_str)

        def name(self):
            return "postgres"

        def uri(self):
            return self._uri

    class _FakeLayer(QgsVectorLayer):
        def __init__(self, uri_str, is_valid, ptype):
            self._source = uri_str
            self._valid = is_valid
            self._ptype = ptype
            self._provider = _FakeProvider(uri_str) if is_valid else None
            self.rewritten = []
            self.read_only = None

        def providerType(self):
            return self._ptype

        def dataProvider(self):
            return self._provider

        def source(self):
            return self._source

        def isValid(self):
            return self._valid

        def name(self):
            return name

        def setDataSource(self, uri_str, name, provider, options):
            self.rewritten.append(uri_str)
            self._source = uri_str
            self._provider = _FakeProvider(uri_str)
            self._valid = True

        def setReadOnly(self, ro):
            self.read_only = ro

    return _FakeLayer(source, valid, provider_type)


def _our_source(**overrides):
    params = {"dbname": "test_db", "host": HOST18, "port": "5432", "user": "ftth_editor",
              "sslmode": "require", "table": '"wyre"."ducts"'}
    params.update(overrides)
    return " ".join(f"{k}='{v}'" if k not in ("table", "sslmode", "authcfg", "port") else f"{k}={v}"
                    for k, v in params.items())


def _nominal_plugin(bp, monkeypatch, tmp_path):
    """Plugin already connected nominatively (no psycopg2 involved)."""
    from qgis.core import QgsSettings

    QgsSettings().setValue("constructel_bridge/onboarding_done", True)
    bp._store_password_encrypted("ad-pw", "wyre", username=LOGIN)
    bp._store_password_encrypted("ad-pw", "be", username=LOGIN)
    plugin = bp.ConstructelBridgePlugin(_FakeIface())
    plugin._auth_mode = bn.AUTH_MODE_NOMINAL
    plugin._pg_login = LOGIN
    plugin._ad_password = "ad-pw"  # I6 : jamais dans _password (chemins partages)
    plugin._connected = True
    return plugin


def _shared_plugin(bp, monkeypatch, tmp_path):
    from qgis.core import QgsSettings

    QgsSettings().setValue("constructel_bridge/onboarding_done", True)
    bp._store_password_encrypted("shared-pw", "wyre")
    plugin = bp.ConstructelBridgePlugin(_FakeIface())
    plugin._auth_mode = bn.AUTH_MODE_SHARED
    plugin._password = "shared-pw"
    plugin._connected = True
    return plugin


def _uri(bp, source):
    from qgis.core import QgsDataSourceUri

    return QgsDataSourceUri(source)


# --- _fix_layer_credentials (B7) ---------------------------------------------------


def test_fix_nominal_rewrites_shared_layer_to_login_authcfg_verify_full(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsProject

    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    layer = _make_fake_layer(_our_source(authcfg="9i19s56"), valid=False)
    QgsProject.instance().addMapLayer(layer)

    plugin._fix_layer_credentials()

    assert len(layer.rewritten) == 1
    uri = _uri(bp18, layer.source())
    assert uri.username() == LOGIN
    assert uri.authConfigId() == "9i19s56"
    assert uri.password() == ""
    assert uri.param("sslmode") == "verify-full"


def test_fix_nominal_plaintext_legacy_layer_loses_its_password(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsProject

    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    layer = _make_fake_layer(_our_source(password="oldpw"), valid=True)
    QgsProject.instance().addMapLayer(layer)

    plugin._fix_layer_credentials()

    uri = _uri(bp18, layer.source())
    assert uri.password() == ""
    assert uri.username() == LOGIN
    assert uri.authConfigId() == "9i19s56"


def test_fix_nominal_colleague_login_is_replaced_by_mine(bp18, monkeypatch, tmp_path):
    # Projet enregistre par alice (user='alice' authcfg=9i19s56) : sur mon
    # poste la config fixe porte MON login (spec §5.7.2).
    from qgis.core import QgsProject

    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    layer = _make_fake_layer(_our_source(user="alice", authcfg="9i19s56", sslmode="verify-full"), valid=False)
    QgsProject.instance().addMapLayer(layer)

    plugin._fix_layer_credentials()

    uri = _uri(bp18, layer.source())
    assert uri.username() == LOGIN
    assert uri.authConfigId() == "9i19s56"


def test_fix_nominal_keeps_be_identity_on_be_layers(load_bp18, monkeypatch, tmp_path):
    bp = load_bp18(CREDS_17)  # bloc be historique : user='bureau_etudes' reconnaissable
    # Import APRES load_bp18 : le stub qgis.core est reimporte par la fixture.
    from qgis.core import QgsProject

    plugin = _nominal_plugin(bp, monkeypatch, tmp_path)
    legacy_be = _make_fake_layer(_our_source(user="bureau_etudes", password="x"), valid=True)
    nominal_be = _make_fake_layer(_our_source(user="alice", authcfg="07254s7"), valid=False)
    QgsProject.instance().addMapLayer(legacy_be)
    QgsProject.instance().addMapLayer(nominal_be)

    plugin._fix_layer_credentials()

    for layer in (legacy_be, nominal_be):
        uri = _uri(bp, layer.source())
        assert uri.username() == LOGIN
        assert uri.authConfigId() == "07254s7"
        assert uri.password() == ""


def test_fix_nominal_already_correct_layer_is_untouched(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsProject

    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    layer = _make_fake_layer(_our_source(user=LOGIN, authcfg="9i19s56", sslmode="verify-full"), valid=True)
    QgsProject.instance().addMapLayer(layer)

    plugin._fix_layer_credentials()

    assert layer.rewritten == []


def test_fix_nominal_skips_third_party_host(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsProject

    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    source = "dbname='o' host=other.example.com port=5432 user='x' password='y' table=\"s\".\"t\""
    layer = _make_fake_layer(source, valid=False)
    QgsProject.instance().addMapLayer(layer)

    plugin._fix_layer_credentials()

    assert layer.rewritten == []


def test_fix_shared_mode_maps_colleague_login_to_shared_fixed_config(bp18, monkeypatch, tmp_path):
    # Poste en repli : un projet enregistre par un collegue nominatif ne
    # doit pas finir en mot de passe partage EN CLAIR dans la datasource.
    from qgis.core import QgsProject

    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)
    layer = _make_fake_layer(_our_source(user="alice", authcfg="9i19s56"), valid=False)
    QgsProject.instance().addMapLayer(layer)

    plugin._fix_layer_credentials()

    uri = _uri(bp18, layer.source())
    assert uri.username() == "ftth_editor"
    assert uri.authConfigId() == "9i19s56"
    assert uri.password() == ""


# --- _strip_authcfg_from_dom (B7, projets enregistres) ----------------------------


class _Null:
    def isNull(self):
        return True


class _Elem:
    def __init__(self, text="", children=None):
        self._text = text
        self._children = children or {}

    def isNull(self):
        return False

    def text(self):
        return self._text

    def toElement(self):
        return self

    def firstChildElement(self, name):
        return self._children.get(name, _Null())

    def hasChildNodes(self):
        return bool(self._text)

    def firstChild(self):
        return self

    def removeChild(self, _child):
        self._text = ""

    def appendChild(self, node):
        self._text += node.text


class _NodeList:
    def __init__(self, items):
        self._items = items

    def count(self):
        return len(self._items)

    def at(self, i):
        return self._items[i]


class _Doc:
    def __init__(self, datasources):
        self.layers = [
            _Elem(children={"provider": _Elem("postgres"), "datasource": _Elem(ds)})
            for ds in datasources
        ]

    def elementsByTagName(self, _tag):
        return _NodeList(self.layers)

    def createTextNode(self, text):
        return SimpleNamespace(text=text)

    def datasources(self):
        return [layer.firstChildElement("datasource").text() for layer in self.layers]


def test_strip_dom_nominal_writes_login_authcfg_without_password(bp18, monkeypatch, tmp_path):
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    doc = _Doc([_our_source(password="x", authcfg="old1234")])

    plugin._strip_authcfg_from_dom(doc)

    ds = doc.datasources()[0]
    assert "password=" not in ds
    assert f"user='{LOGIN}'" in ds
    assert "authcfg=9i19s56" in ds
    assert "sslmode=verify-full" in ds
    assert ds.count("user=") == 1


def test_strip_dom_nominal_cleans_plaintext_datasource_too(bp18, monkeypatch, tmp_path):
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    doc = _Doc([_our_source(password="x")])  # pas d'authcfg : 1.7.x la laissait telle quelle

    plugin._strip_authcfg_from_dom(doc)

    ds = doc.datasources()[0]
    assert "password=" not in ds
    assert "authcfg=9i19s56" in ds


def test_strip_dom_nominal_keeps_be_authcfg(bp18, monkeypatch, tmp_path):
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    doc = _Doc([_our_source(user="alice", authcfg="07254s7")])

    plugin._strip_authcfg_from_dom(doc)

    ds = doc.datasources()[0]
    assert "authcfg=07254s7" in ds and f"user='{LOGIN}'" in ds


FILTER = "sql=\"owner\" = 'user=x' AND note = 'sslmode=require' AND  code <> 'a  b'"


def test_strip_dom_nominal_keeps_sql_filter_and_authcfg(bp18, monkeypatch, tmp_path):
    # Revue 29/10 (I12) : jetons ajoutes en fin de chaine = filtre corrompu.
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    doc = _Doc([_our_source(authcfg="old1234") + " " + FILTER])

    plugin._strip_authcfg_from_dom(doc)

    ds = doc.datasources()[0]
    assert ds.endswith(" " + FILTER)
    assert bn.datasource_param(ds, "authcfg") == "9i19s56"
    assert bn.datasource_param(ds, "user") == LOGIN


def test_strip_dom_shared_keeps_sql_filter(bp18, monkeypatch, tmp_path):
    # Meme faute dans le chemin partage 1.7.x : corrigee aussi.
    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)
    doc = _Doc([_our_source(user="alice", authcfg="old1234") + " " + FILTER])

    plugin._strip_authcfg_from_dom(doc)

    ds = doc.datasources()[0]
    assert ds.endswith(" " + FILTER)
    assert bn.datasource_param(ds, "user") == "ftth_editor"
    assert bn.datasource_param(ds, "authcfg") == "9i19s56"
    assert bn.datasource_param(ds, "sslmode") == "require"


def test_strip_dom_nominal_leaves_third_party_datasource_alone(bp18, monkeypatch, tmp_path):
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    source = "dbname='o' host=other.example.com user='x' password='y' authcfg=abc table=\"s\".\"t\""
    doc = _Doc([source])

    plugin._strip_authcfg_from_dom(doc)

    assert doc.datasources()[0] == source


# --- _read_and_clean_project (B7, projets en base) ----------------------------------


class _XmlCursor:
    def __init__(self, xml):
        self._xml = xml

    def execute(self, *_a, **_k):
        pass

    def fetchone(self):
        return (self._xml,)

    def close(self):
        pass


def test_read_project_nominal_injects_authcfg_not_password(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsProject

    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    xml = ("<qgis><maplayer><datasource>" + _our_source(password="x", authcfg="zzz9999")
           + "</datasource></maplayer></qgis>")
    plugin._conn = SimpleNamespace(cursor=lambda: _XmlCursor(xml), closed=False)
    project = QgsProject.instance()

    assert plugin._read_and_clean_project(project, "wyre", "proj") is True

    assert "password=" not in project.read_xml
    assert f"user='{LOGIN}'" in project.read_xml
    assert "authcfg=9i19s56" in project.read_xml
    assert "sslmode=verify-full" in project.read_xml


def test_read_project_shared_mode_keeps_17x_plaintext_injection(bp18, monkeypatch, tmp_path):
    from qgis.core import QgsProject

    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)
    xml = "<qgis><maplayer><datasource>" + _our_source(authcfg="zzz9999") + "</datasource></maplayer></qgis>"
    plugin._conn = SimpleNamespace(cursor=lambda: _XmlCursor(xml), closed=False)
    project = QgsProject.instance()

    assert plugin._read_and_clean_project(project, "wyre", "proj") is True

    assert "authcfg=" not in project.read_xml
    assert "user='ftth_editor' password='shared-pw'" in project.read_xml


@pytest.mark.parametrize("nominal", [True, False])
def test_read_project_keeps_xml_escaped_sql_filter(bp18, monkeypatch, tmp_path, nominal):
    from xml.sax.saxutils import escape

    from qgis.core import QgsProject

    plugin = (_nominal_plugin if nominal else _shared_plugin)(bp18, monkeypatch, tmp_path)
    source = _our_source(authcfg="zzz9999") + " " + FILTER
    xml = "<qgis><maplayer><datasource>" + escape(source, {'"': "&quot;"}) + "</datasource></maplayer></qgis>"
    plugin._conn = SimpleNamespace(cursor=lambda: _XmlCursor(xml), closed=False)
    project = QgsProject.instance()

    assert plugin._read_and_clean_project(project, "wyre", "proj") is True

    assert escape(" " + FILTER) + "</datasource>" in project.read_xml
    assert "&lt;&gt;" in project.read_xml


# --- _ensure_ref_layers (couche cachee v_form_lists, revue 29/10 I7) ----------------


@pytest.fixture
def form_lists_project(monkeypatch):
    """Projet Bridge dont une liste de valeurs depend de v_form_lists."""
    state = {"bridge": True, "needs": True}
    monkeypatch.setitem(sys.modules, "constructel_bridge.bridge_project_init",
                        SimpleNamespace(is_bridge_project=lambda: state["bridge"]))
    import constructel_bridge.bridge_sketcher as sketcher
    monkeypatch.setattr(sketcher, "value_relations_use_form_lists", lambda project: state["needs"])
    return state


def test_ensure_ref_layers_nominal_uses_authcfg_without_password(bp18, monkeypatch, tmp_path, form_lists_project):
    from qgis.core import QgsProject

    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)

    plugin._ensure_ref_layers()

    layers = list(QgsProject.instance().mapLayers().values())
    assert len(layers) == 1
    uri = _uri(bp18, layers[0].source())
    assert uri.table() == "v_form_lists"
    assert uri.username() == LOGIN
    assert uri.authConfigId() == "9i19s56"
    assert uri.password() == ""
    assert uri.param("sslmode") == "verify-full"


def test_ensure_ref_layers_shared_uses_fixed_config_never_a_plaintext_password(
        bp18, monkeypatch, tmp_path, form_lists_project):
    from qgis.core import QgsProject

    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)

    plugin._ensure_ref_layers()

    (layer,) = QgsProject.instance().mapLayers().values()
    uri = _uri(bp18, layer.source())
    assert uri.username() == "ftth_editor"
    assert uri.authConfigId() == "9i19s56"
    assert uri.password() == ""
    assert uri.param("sslmode") == "require"  # D-TLS-2


def test_ensure_ref_layers_shared_without_fixed_config_adds_nothing(bp18, monkeypatch, tmp_path, form_lists_project):
    from qgis.core import QgsApplication, QgsProject

    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)
    QgsApplication.authManager().removeAuthenticationConfig("9i19s56")

    plugin._ensure_ref_layers()

    assert QgsProject.instance().mapLayers() == {}


@pytest.mark.parametrize("bridge, needs", [(False, True), (True, False)])
def test_ensure_ref_layers_only_for_bridge_projects_that_need_it(
        bp18, monkeypatch, tmp_path, form_lists_project, bridge, needs):
    # I7 : plus d'injection d'une couche cachee dans un projet tiers.
    from qgis.core import QgsProject

    form_lists_project.update(bridge=bridge, needs=needs)
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)

    plugin._ensure_ref_layers()

    assert QgsProject.instance().mapLayers() == {}


def test_value_relations_use_form_lists_detection(sk):
    by_name = _VrLayer([{"LayerName": "v_form_lists", "Value": "label_fr"}])
    by_source = _VrLayer([{"LayerName": "Listes formulaires",
                           "LayerSource": QML_SOURCE.replace('"wyre"."zone_pop" (geom)', '"ref"."v_form_lists"')}])
    unrelated = _VrLayer([{"LayerName": "zone_pop", "LayerSource": QML_SOURCE}])

    assert sk.value_relations_use_form_lists(_vr_project(by_name)) is True
    assert sk.value_relations_use_form_lists(_vr_project(by_source)) is True
    assert sk.value_relations_use_form_lists(_vr_project(unrelated)) is False


# --- initialisation de projet (bridge_project_init) ---------------------------------


@pytest.fixture
def pi(bp18, monkeypatch):
    """bridge_project_init sous les stubs partages, completes par des classes
    nommees pour ses imports qgis.* non couverts (meme recette que
    test_bridge_project_init.py), QgsDataSourceUri du stub conservee."""
    import ast
    import importlib
    from pathlib import Path
    from types import ModuleType

    module_path = Path(bp18.__file__).resolve().parent / "bridge_project_init.py"
    monkeypatch.delitem(sys.modules, "constructel_bridge.bridge_project_init", raising=False)
    for node in ast.walk(ast.parse(module_path.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("qgis")):
            continue
        try:
            module = importlib.import_module(node.module)
        except ImportError:
            module = ModuleType(node.module)
            monkeypatch.setitem(sys.modules, node.module, module)
        for alias in node.names:
            if not hasattr(module, alias.name):
                monkeypatch.setattr(module, alias.name, type(alias.name, (), {}), raising=False)
    return importlib.import_module("constructel_bridge.bridge_project_init")


def test_init_conn_params_nominal_carry_authcfg_and_no_password(bp18, monkeypatch, tmp_path):
    plugin = _nominal_plugin(bp18, monkeypatch, tmp_path)
    params, password = plugin._init_conn_params()
    assert params["user"] == LOGIN
    assert params["authcfg"] == "9i19s56"
    assert params["sslmode"] == "verify-full"
    assert params["sslrootcert"] == str(bp18.ca_bundle_path(os.path.dirname(bp18.__file__)))
    assert password == "ad-pw"


def test_init_conn_params_shared_mode_are_17x(bp18, monkeypatch, tmp_path):
    plugin = _shared_plugin(bp18, monkeypatch, tmp_path)
    params, password = plugin._init_conn_params()
    assert params == {"host": HOST18, "port": 5432, "dbname": "test_db",
                      "user": "ftth_editor", "sslmode": "require"}  # 1.7.x (D-TLS-2)
    assert password == "shared-pw"


def test_build_uri_with_authcfg_has_no_password_and_verify_full(pi):
    uri = pi._build_uri(
        {"host": HOST18, "port": 5432, "dbname": "test_db", "user": LOGIN,
         "sslmode": "verify-full", "authcfg": "9i19s56"},
        "ad-pw", "wyre", "ducts", "geom", "id",
    )
    assert uri.password() == ""
    assert uri.authConfigId() == "9i19s56"
    assert uri.username() == LOGIN
    assert uri.param("sslmode") == "verify-full"
    assert uri.table() == "ducts"


def test_build_uri_without_authcfg_keeps_17x_plaintext(pi):
    uri = pi._build_uri(
        {"host": HOST18, "port": 5432, "dbname": "test_db", "user": "ftth_editor", "sslmode": "require"},
        "shared-pw", "wyre", "ducts", "geom", "id",
    )
    assert uri.password() == "shared-pw"
    assert uri.authConfigId() == ""


def test_apply_styles_from_db_passes_ssl_params(pi, monkeypatch):
    calls = []
    module = types.ModuleType("psycopg2")
    module.Error = Exception

    def connect(**kwargs):
        calls.append(kwargs)
        raise Exception("stop here")

    module.connect = connect
    monkeypatch.setitem(sys.modules, "psycopg2", module)

    pi._apply_styles_from_db(
        {"host": HOST18, "port": 5432, "dbname": "test_db", "user": LOGIN,
         "sslmode": "verify-full", "sslrootcert": "/x/root-ca-bundle.pem", "authcfg": "9i19s56"},
        "ad-pw", {},
    )

    assert calls and calls[0]["user"] == LOGIN
    assert calls[0]["sslmode"] == "verify-full"
    assert calls[0]["sslrootcert"] == "/x/root-ca-bundle.pem"


# --- LayerSource des listes de valeurs (B9 : 38 user='ftth_editor' dans les QML) --------


class _FakeSetup:
    def __init__(self, widget_type, config):
        self._type, self._config = widget_type, dict(config)

    def type(self):
        return self._type

    def config(self):
        return dict(self._config)


class _VrLayer:
    def __init__(self, value_relations):
        self._setups = [_FakeSetup("ValueRelation", cfg) for cfg in value_relations]

    def name(self):
        return "ducts"

    def fields(self):
        return SimpleNamespace(count=lambda: len(self._setups))

    def editorWidgetSetup(self, index):
        return self._setups[index]

    def setEditorWidgetSetup(self, index, setup):
        self._setups[index] = setup

    def sources(self):
        return [s.config().get("LayerSource", "") for s in self._setups]


def _vr_project(*layers):
    return SimpleNamespace(mapLayers=lambda: {str(i): layer for i, layer in enumerate(layers)})


@pytest.fixture
def sk(bp18, monkeypatch):
    import importlib

    module = importlib.import_module("constructel_bridge.bridge_sketcher")
    monkeypatch.setattr(module, "QgsVectorLayer", _VrLayer)
    monkeypatch.setattr(module, "QgsEditorWidgetSetup", _FakeSetup)
    return module


QML_SOURCE = (f"dbname='farois_ftth' host={HOST18} port=5432 user='ftth_editor' sslmode=require key='id' "
              "estimatedmetadata=true srid=31370 type=MultiPolygon checkPrimaryKeyUnicity='0' "
              "table=\"wyre\".\"zone_pop\" (geom)")


def test_vr_sources_rewritten_to_nominal_identity(sk):
    ducts = _VrLayer([{"LayerName": "zone_pop", "LayerSource": QML_SOURCE, "Value": "code"}])

    patched = sk.rewrite_value_relation_sources(_vr_project(ducts), LOGIN, "9i19s56", (HOST18,))

    assert patched == 1
    src = ducts.sources()[0]
    assert f"user='{LOGIN}'" in src and "authcfg=9i19s56" in src and "sslmode=verify-full" in src
    assert "ftth_editor" not in src
    assert "table=\"wyre\".\"zone_pop\" (geom)" in src


def test_vr_sources_third_party_and_already_nominal_untouched(sk):
    foreign = "dbname='o' host=other.example.com user='x' table=\"s\".\"t\""
    done = bn.rewrite_datasource_nominal(QML_SOURCE, LOGIN, "9i19s56")
    ducts = _VrLayer([{"LayerSource": foreign}, {"LayerSource": done}, {"Value": "no source"}])

    patched = sk.rewrite_value_relation_sources(_vr_project(ducts), LOGIN, "9i19s56", (HOST18,))

    assert patched == 0
    assert ducts.sources() == [foreign, done, ""]


def test_plugin_rewrites_vr_sources_only_in_nominal_mode(bp18, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        bp18.bridge_sketcher, "rewrite_value_relation_sources",
        lambda project, login, authcfg, hosts: calls.append((login, authcfg)) or 0,
    )
    shared = _shared_plugin(bp18, monkeypatch, tmp_path)
    shared._rewrite_value_relation_sources()
    assert calls == []

    nominal = _nominal_plugin(bp18, monkeypatch, tmp_path)
    nominal._rewrite_value_relation_sources()
    assert calls == [(LOGIN, "9i19s56")]



# --- revue 2 (M7) : hôte comparé exactement ------------------------------------------


@pytest.mark.parametrize("nominal", [True, False])
def test_strip_dom_ignores_a_host_that_only_contains_ours(bp18, monkeypatch, tmp_path, nominal):
    plugin = (_nominal_plugin if nominal else _shared_plugin)(bp18, monkeypatch, tmp_path)
    lookalike = _our_source(host=f"{HOST18}.evil.example.com", authcfg="old1234")
    in_filter = ("dbname='o' host=other.example.com port=5432 user='x' authcfg=abc "
                 f"table=\"s\".\"t\" sql=note = 'host={HOST18}'")
    doc = _Doc([lookalike, in_filter])

    plugin._strip_authcfg_from_dom(doc)

    assert doc.datasources() == [lookalike, in_filter]


def test_vr_source_on_a_lookalike_host_is_untouched(sk):
    lookalike = QML_SOURCE.replace(f"host={HOST18}", f"host={HOST18}.evil.example.com")
    ducts = _VrLayer([{"LayerSource": lookalike}])
    assert sk.rewrite_value_relation_sources(_vr_project(ducts), LOGIN, "9i19s56", (HOST18,)) == 0
