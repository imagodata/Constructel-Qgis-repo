"""Bridge 1.9, tache 9b (spec § 6.7) : le navigateur QGIS (connexion `wyre`) et
la liste des projets enregistres suivent les operateurs utilisables.

  * fonctions pures de bridge_operators (``browser_schemas``, ``project_schemas``) ;
  * plugin : ``_project_schemas`` (garde anti-injection de
    ``_read_and_clean_project`` et parcours de ``_list_db_projects``),
    ``_refresh_browser_schemas`` (K6 : jamais d'entree partielle, jamais
    l'entree `be`) et ecriture de ``{base}/schemas`` par
    ``_setup_qgis_pg_connection``.
Doublures seulement, jamais de base reelle."""
from __future__ import annotations

import pytest

from constructel_bridge import bridge_operators as bo
from constructel_bridge_tests.fakes19 import ORANGE, WYRE
from constructel_bridge_tests.test_bridge18_connect import _FakeCursor, _make_plugin
from constructel_bridge_tests.test_bridge18_layers import LOGIN, _FakeIface, _XmlCursor

WYRE_KEY = "PostgreSQL/connections/wyre"
BE_KEY = "PostgreSQL/connections/be"


# --- doublures et fixtures (K15) ----------------------------------------------------------


class _ProjectsCursor:
    """Curseur de _list_db_projects : enregistre les schemas sondes dans
    information_schema.tables ; ``missing`` = schemas sans qgis_projects."""

    def __init__(self, missing=()):
        self.schemas_probed = []
        self.listed_from = []
        self.missing = set(missing)
        self.description = [("name",), ("description",), ("updated",), ("schema",)]
        self._one = None
        self._all = []

    def execute(self, sql, params=None):
        self._one, self._all = None, []
        if "information_schema.tables" in sql:
            self.schemas_probed.append(params[0])
            self._one = (params[0] not in self.missing,)
        elif "qgis_projects" in sql:
            schema = params[0]
            self.listed_from.append(schema)
            self._all = [(f"projet_{schema}", "", "", schema)]

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all

    def close(self):
        pass


@pytest.fixture
def settings(bp18):
    """QgsSettings du stub, vide au depart et nettoye ensuite."""
    from qgis.core import QgsSettings

    QgsSettings._store.clear()
    yield QgsSettings()
    QgsSettings._store.clear()


@pytest.fixture
def fake_cursor():
    return _ProjectsCursor()


@pytest.fixture
def plugin(bp18, fake_cursor, settings, monkeypatch):
    """Plugin connecte (sans psycopg2) dont la connexion rend ``fake_cursor``."""
    from types import SimpleNamespace

    instance = bp18.ConstructelBridgePlugin(_FakeIface())
    instance._connected = True
    instance._conn = SimpleNamespace(cursor=lambda: fake_cursor, closed=False)
    return instance


def _seed_wyre_entry(settings, schemas="wyre,osiris"):
    settings.setValue(f"{WYRE_KEY}/host", "test-host.invalid")
    settings.setValue(f"{WYRE_KEY}/schemas", schemas)


# --- fonctions pures ----------------------------------------------------------------------


def test_browser_schemas_operateurs_puis_osiris():
    assert bo.browser_schemas([WYRE, ORANGE]) == "wyre,orange,osiris"


def test_browser_schemas_vide_repli_historique():
    assert bo.browser_schemas([]) == "wyre,osiris"


def test_browser_schemas_un_seul_operateur_non_wyre():
    assert bo.browser_schemas([ORANGE]) == "orange,osiris"


def test_project_schemas_operateurs_puis_public():
    assert bo.project_schemas([WYRE, ORANGE]) == ("wyre", "orange", "public")
    assert bo.project_schemas([]) == ("wyre", "public")


# --- projets enregistres ------------------------------------------------------------------


def test_project_schemas_du_plugin_suit_les_operateurs(plugin):
    plugin._operators = [WYRE, ORANGE]
    assert plugin._project_schemas() == ("wyre", "orange", "public")


def test_project_schemas_repli_sans_operateur_ou_liste_illisible(plugin):
    plugin._operators = []
    assert plugin._project_schemas() == ("wyre", "public")
    plugin._operators = [ORANGE]
    plugin._operators_unavailable = True
    assert plugin._project_schemas() == ("wyre", "public")


def test_constante_de_classe_supprimee(bp18):
    assert not hasattr(bp18.ConstructelBridgePlugin, "_PROJECT_SCHEMAS")


def test_projet_dun_schema_non_utilisable_refuse(plugin, monkeypatch):
    plugin._operators = [WYRE]
    plugin._conn = type("C", (), {"cursor": lambda self: pytest.fail("la base ne doit pas etre lue"),
                                  "closed": False})()
    assert plugin._read_and_clean_project(object(), "orange", "x") is False
    from qgis.core import QgsMessageLog

    assert any("Rejected invalid schema" in m[0] for m in QgsMessageLog._messages)


@pytest.mark.parametrize("schema", ["wyre; DROP TABLE x", "ref", "chantier", "", 'wyre"'])
def test_projet_injection_de_schema_refuse(plugin, schema):
    plugin._operators = [WYRE, ORANGE]
    plugin._conn = type("C", (), {"cursor": lambda self: pytest.fail("la base ne doit pas etre lue"),
                                  "closed": False})()
    assert plugin._read_and_clean_project(object(), schema, "x") is False


def test_projet_dun_operateur_utilisable_est_lu(plugin):
    from qgis.core import QgsProject

    plugin._operators = [WYRE, ORANGE]
    plugin._auth_mode = ""
    plugin._password = "shared-pw"
    cursor = _XmlCursor("<qgis></qgis>")
    queries = []
    cursor.execute = lambda sql, *_a, **_k: queries.append(sql)
    plugin._conn.cursor = lambda: cursor
    assert plugin._read_and_clean_project(QgsProject.instance(), "orange", "proj") is True
    assert 'FROM "orange".qgis_projects' in queries[0]


def test_schema_mot_reserve_entre_guillemets(plugin, fake_cursor):
    # Relecture finale M2 : schema operateur « order » (mot reserve, mais
    # identifiant sur) : quote dans la liste et dans la lecture du projet.
    from qgis.core import QgsProject

    plugin._operators = [bo.OperatorInfo("ORDER", "Order", "order", True)]
    listed = []
    real_execute = fake_cursor.execute
    fake_cursor.execute = lambda sql, params=None: listed.append(sql) or real_execute(sql, params)
    assert [p["schema"] for p in plugin._list_db_projects()] == ["order", "public"]
    assert any('FROM "order".qgis_projects' in sql for sql in listed)
    assert any('FROM "public".qgis_projects' in sql for sql in listed)

    plugin._auth_mode = ""
    plugin._password = "shared-pw"
    cursor = _XmlCursor("<qgis></qgis>")
    queries = []
    cursor.execute = lambda sql, *_a, **_k: queries.append(sql)
    plugin._conn.cursor = lambda: cursor
    assert plugin._read_and_clean_project(QgsProject.instance(), "order", "proj") is True
    assert 'FROM "order".qgis_projects' in queries[0]


def test_projet_wyre_et_public_acceptes_sans_liste_d_operateurs(plugin):
    # Repli 1.8 : sans operateur, wyre et public restent charges.
    from qgis.core import QgsProject

    plugin._operators = []
    plugin._password = "shared-pw"
    for schema in ("wyre", "public"):
        cursor = _XmlCursor("<qgis></qgis>")
        plugin._conn.cursor = lambda cursor=cursor: cursor
        assert plugin._read_and_clean_project(QgsProject.instance(), schema, "proj") is True


def test_liste_projets_parcourt_les_schemas_utilisables(plugin, fake_cursor):
    plugin._operators = [WYRE, ORANGE]
    results = plugin._list_db_projects()
    assert fake_cursor.schemas_probed == ["wyre", "orange", "public"]
    assert [r["schema"] for r in results] == ["wyre", "orange", "public"]


def test_liste_projets_saute_un_schema_sans_table(plugin, fake_cursor):
    plugin._operators = [WYRE, ORANGE]
    fake_cursor.missing = {"orange"}
    results = plugin._list_db_projects()
    assert [r["schema"] for r in results] == ["wyre", "public"]
    assert fake_cursor.listed_from == ["wyre", "public"]


def test_liste_projets_repli_sans_operateur(plugin, fake_cursor):
    plugin._operators = []
    plugin._list_db_projects()
    assert fake_cursor.schemas_probed == ["wyre", "public"]


# --- navigateur QGIS ----------------------------------------------------------------------


def test_refresh_browser_schemas_ecrit_le_reglage_sans_toucher_be(plugin, settings):
    _seed_wyre_entry(settings)
    settings.setValue(f"{BE_KEY}/host", "test-host.invalid")
    settings.setValue(f"{BE_KEY}/schemas", "public")
    plugin._operators = [WYRE, ORANGE]
    plugin._refresh_browser_schemas()
    assert settings.value(f"{WYRE_KEY}/schemas") == "wyre,orange,osiris"
    assert settings.value(f"{BE_KEY}/schemas") == "public"


def test_refresh_browser_schemas_entree_absente_rien_ecrit(plugin, settings):
    # K6 : jamais d'entree partielle (cas mTLS invalide : rien n'a ete ecrit).
    from qgis.core import QgsSettings

    plugin._operators = [WYRE, ORANGE]
    plugin._refresh_browser_schemas()
    assert QgsSettings._store == {}


def test_refresh_browser_schemas_entree_par_service_suffit(plugin, settings):
    settings.setValue(f"{WYRE_KEY}/service", "constructel_bridge")
    plugin._operators = [ORANGE]
    plugin._refresh_browser_schemas()
    assert settings.value(f"{WYRE_KEY}/schemas") == "orange,osiris"


def test_refresh_browser_schemas_repli_historique(plugin, settings):
    _seed_wyre_entry(settings, schemas="wyre,orange,osiris")
    plugin._operators = []
    plugin._refresh_browser_schemas()
    assert settings.value(f"{WYRE_KEY}/schemas") == "wyre,osiris"


def test_setup_connexion_wyre_expose_les_operateurs_et_be_reste_public(plugin, settings):
    plugin._operators = [WYRE, ORANGE]
    plugin._setup_qgis_pg_connection("pw", use_authcfg=False)
    plugin._setup_qgis_pg_connection("pw", use_authcfg=False, conn="be")
    assert settings.value(f"{WYRE_KEY}/schemas") == "wyre,orange,osiris"
    assert settings.value(f"{BE_KEY}/schemas") == "public"


def test_setup_connexion_sans_operateur_garde_wyre_osiris(plugin, settings):
    plugin._operators = []
    plugin._setup_qgis_pg_connection("pw", use_authcfg=False)
    assert settings.value(f"{WYRE_KEY}/schemas") == "wyre,osiris"


def test_connexion_nominative_publie_les_schemas_des_operateurs(bp18, monkeypatch, tmp_path, settings):
    both = [("ORANGE", "Orange", "orange", True), ("WYRE", "Wyre", "wyre", True)]
    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None],
                              cursor=_FakeCursor(operator_rows=both), stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert plugin._connected is True and [o.schema for o in plugin._operators] == ["orange", "wyre"]
    assert settings.value(f"{WYRE_KEY}/schemas") == "orange,wyre,osiris"


def test_connexion_nominative_liste_illisible_garde_wyre_osiris(bp18, monkeypatch, tmp_path, settings):
    from constructel_bridge_tests.test_bridge18_connect import _PgErr

    cursor = _FakeCursor(operator_rows=_PgErr("permission denied for table operateurs"))
    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cursor, stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert plugin._connected is True and plugin._operators_unavailable is True
    assert settings.value(f"{WYRE_KEY}/schemas") == "wyre,osiris"
