#!/usr/bin/env python3
"""Test de fumée des plugins et scripts Processing dans un vrai QGIS (Qt5 ou Qt6).

À lancer dans une image QGIS officielle (voir scripts/test_qgis_matrix.sh) :

1. statique : chaque nom importé depuis qgis.* et chaque chaîne `Nom.attr[.attr]`
   sur ces noms (enums, classes) doit exister dans l'API du QGIS courant ;
2. plugins : classFactory(iface) -> initGui() -> fenêtres -> unload() ;
3. TLS nominatif (Bridge 1.8, D-TLS-1) : CA Farois importée dans la base
   d'authentification QGIS, présente dans le sslrootcert que QGIS fabrique
   pour une config Basic en verify-full, import idempotent ;
4. scripts Processing : instanciation + initAlgorithm().

Sort en code 1 si un contrôle échoue.
"""
import ast
import base64
import configparser
import importlib
import json
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

from qgis.core import (
    Qgis,
    QgsMessageLog,
    QgsProcessingAlgorithm,
    QgsProject,
    QgsVectorLayer,
)
from qgis.gui import QgisInterface, QgsMessageBar
from qgis.PyQt.QtWidgets import QDialog, QMenu, QToolBar
from qgis.testing import start_app
from qgis.testing.mocked import get_iface

REPO = Path(__file__).resolve().parents[1]
COLLECTIONS = REPO / "resource-repo/collections"

# Base d'authentification jetable (lue par QgsApplication à l'initialisation) :
# le contrôle TLS y importe des CA et y pose un mot de passe maître.
os.environ["QGIS_AUTH_DB_DIR_PATH"] = tempfile.mkdtemp(prefix="qgis-auth-smoke-")
app = start_app()
print(f"QGIS {Qgis.version()}")
QGIS_VERSION = tuple(int(part) for part in Qgis.QGIS_VERSION.split("-")[0].split(".")[:2])
failures = []
log = []

_log_message = QgsMessageLog.logMessage


def _capture(message, tag="", level=Qgis.MessageLevel.Warning, *args, **kwargs):
    log.append((int(level), tag, str(message).splitlines()[0][:160] if message else ""))
    return _log_message(message, tag, level, *args, **kwargs)


QgsMessageLog.logMessage = staticmethod(_capture)


def fail(where, what):
    failures.append(f"{where}: {what}")
    print(f"  FAIL {where}: {what}")


def collection_scripts():
    """Scripts dont la collection accepte le QGIS courant (qgis_minimum_version)."""
    metadata = configparser.ConfigParser(interpolation=None)
    metadata.read(REPO / "resource-repo/metadata.ini", encoding="utf-8")
    scripts = []
    for script in sorted(COLLECTIONS.glob("*/processing/*.py")):
        name = script.parents[1].name
        minimum = metadata.get(name, "qgis_minimum_version", fallback="0.0")
        if tuple(int(part) for part in minimum.split(".")[:2]) > QGIS_VERSION:
            print(f"  -- {script.name} ignoré (collection {name} : QGIS >= {minimum})")
            continue
        scripts.append(script)
    return scripts


# --- 1. statique -------------------------------------------------------------
def _guarded_nodes(tree):
    """Nœuds placés dans un `try` qui rattrape AttributeError (repli de version)."""
    guarded = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        caught = set()
        for handler in node.handlers:
            if handler.type is None:
                caught.add("")  # except nu
                continue
            types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
            caught.update(t.id if isinstance(t, ast.Name) else getattr(t, "attr", "?") for t in types)
        if "AttributeError" in caught:  # repli de version, pas une gestion d'erreur
            for statement in node.body:
                guarded.update(id(child) for child in ast.walk(statement))
    return guarded


def check_static(path):
    where = path.relative_to(REPO)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    guarded = _guarded_nodes(tree)
    names = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "qgis"):
            continue
        try:
            module = importlib.import_module(node.module)
        except Exception as exc:
            fail(f"{where}:{node.lineno}", f"import {node.module} : {exc}")
            continue
        for alias in node.names:
            if alias.name == "*" or (node.module, alias.name) == ("qgis.utils", "iface"):
                continue  # iface : posé par QGIS Desktop au démarrage
            obj = getattr(module, alias.name, None)
            if obj is None:
                try:
                    obj = importlib.import_module(f"{node.module}.{alias.name}")
                except Exception:
                    if id(node) not in guarded:
                        fail(f"{where}:{node.lineno}", f"{node.module}.{alias.name} absent")
                    continue
            names[alias.asname or alias.name] = obj
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or id(node) in guarded or node.attr == "iface":
            continue
        chain, current = [], node
        while isinstance(current, ast.Attribute):
            chain.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name) or current.id not in names:
            continue
        chain.reverse()
        obj = names[current.id]
        # Seule la partie « classe/enum » est vérifiable : on s'arrête à la
        # première fonction (ses attributs sont dynamiques).
        for depth, attr in enumerate(chain):
            if depth and callable(obj) and not isinstance(obj, type):
                break
            if not hasattr(obj, attr):
                fail(f"{where}:{node.lineno}", f"{current.id}.{'.'.join(chain[:depth + 1])} absent")
                break
            obj = getattr(obj, attr)


print("== statique")
SCRIPTS = collection_scripts()
for root in (REPO / "plugin-repo/packages/constructel_bridge", REPO / "plugins/farois_audit_rollback"):
    for path in sorted(p for p in root.rglob("*.py") if "tests" not in p.parts):
        check_static(path)
for path in SCRIPTS:
    check_static(path)


# --- 2. plugins --------------------------------------------------------------
def make_iface():
    """iface simulée de qgis.testing, complétée de vrais menus/barres Qt."""
    iface = get_iface()
    window = iface.mainWindow()
    iface.addToolBar = lambda name: QToolBar(name, window)
    for name in dir(QgisInterface):
        if name.startswith(("add", "remove")):
            continue
        if name.endswith("Menu"):
            menu = QMenu(name, window)
            setattr(iface, name, lambda menu=menu: menu)
        elif name.endswith("ToolBar"):
            bar = QToolBar(name, window)
            setattr(iface, name, lambda bar=bar: bar)
    message_bar = QgsMessageBar(window)
    iface.messageBar = lambda: message_bar
    layer = QgsVectorLayer("Point?crs=EPSG:31370&field=label:string", "smoke", "memory")
    QgsProject.instance().addMapLayer(layer)
    iface.activeLayer = lambda: layer
    return iface


def exercise_ui(name, plugin):
    """Construit chaque fenêtre, sans boucle modale, pour exécuter les enums Qt."""
    if not hasattr(QDialog, "exec"):
        raise AssertionError("QDialog.exec() absent de cette liaison Qt")
    real_exec = QDialog.exec
    QDialog.exec = lambda self: QDialog.DialogCode.Rejected
    try:
        widgets = _build_windows(name, plugin)
    finally:
        QDialog.exec = real_exec
    print(f"  ok fenêtres {name} ({len(widgets)})")


def _build_windows(name, plugin):
    if name == "constructel_bridge":
        from constructel_bridge.bridge_dialog import ConstructelConnectDialog
        from constructel_bridge.bridge_onboarding import OnboardingWizard
        from constructel_bridge.bridge_project_init import InitProjectDialog

        wizard = OnboardingWizard(None, "smoke", "00000000-0000-0000-0000-000000000000", True)
        widgets = [ConstructelConnectDialog(), wizard, InitProjectDialog()]
        wizard.show()
        for _ in wizard.pageIds():
            wizard.next()
            app.processEvents()
    else:
        from farois_audit_rollback.gui import change_details, login_dialog
        from farois_audit_rollback.gui.history_model import HistoryEntry

        plugin.show_dock()
        app.processEvents()
        # L'iface simulée est un Mock et non un QObject comme dans QGIS :
        # sip.isdeleted() la refuserait au déchargement.
        is_deleted = plugin.dock._signals.is_deleted
        plugin.dock._signals.is_deleted = (
            lambda obj: False if "mock" in type(obj).__module__ else is_deleted(obj)
        )
        entry = HistoryEntry(
            change_id="1",
            operation="UPDATE",
            changed_columns=("label",),
            before={"label": "a"},
            after={"label": "b"},
        )
        widgets = [change_details.build_dialog(entry)]
        change_details.show_change_details(entry)
        login_dialog.ask_credentials(None, "smoke@example.org")
    for widget in widgets:
        widget.show()
        app.processEvents()
        widget.close()
    return widgets


print("== plugins")
work = Path(tempfile.mkdtemp())
shutil.copytree(REPO / "plugin-repo/packages/constructel_bridge", work / "bridge/constructel_bridge")
shutil.copytree(REPO / "plugins/farois_audit_rollback", work / "audit/farois_audit_rollback")
fake = {
    "host": "127.0.0.1",
    "port": 1,
    "dbname": "smoke",
    "user": "smoke",
    "password": base64.b64encode(b"smoke").decode(),
}
# Utilisateur « be » distinct : sinon Bridge désactive la connexion be.
(work / "bridge/constructel_bridge/credentials.json").write_text(
    json.dumps({"wyre": fake, "be": {**fake, "user": "smoke_be"}})
)
iface = make_iface()
for name, parent in (("constructel_bridge", work / "bridge"), ("farois_audit_rollback", work / "audit")):
    sys.path.insert(0, str(parent))
    try:
        plugin = importlib.import_module(name).classFactory(iface)
        plugin.initGui()
        app.processEvents()
        exercise_ui(name, plugin)
        plugin.unload()
        app.processEvents()
        print(f"  ok {name}")
    except Exception:
        fail(name, traceback.format_exc())

# --- 3. TLS nominatif ----------------------------------------------------------
def check_bridge_tls():
    """QgsAuthBasicMethod remplace tout sslrootcert= d'une datasource
    verify-* par un fichier temporaire des CA de confiance de QGIS : la CA
    Farois doit y figurer après l'import du plugin (_ensure_qgis_trusted_cas)."""
    from qgis.core import QgsApplication, QgsAuthCertUtils, QgsAuthMethodConfig
    from qgis.PyQt.QtNetwork import QSslCertificate

    bridge = importlib.import_module("constructel_bridge.bridge_plugin")
    mgr = QgsApplication.authManager()
    if mgr.isDisabled():
        fail("tls", f"Auth Manager désactivé : {mgr.disabledMessage()}")
        return
    ca_path = work / "bridge/constructel_bridge/certs/farois-db-ca.crt"
    farois = QSslCertificate.fromData(ca_path.read_bytes())[0]
    farois_der = farois.toDer().data()

    def occurrences():
        return sum(1 for cert in mgr.databaseCAs() if cert.toDer().data() == farois_der)

    for attempt in (1, 2):  # le second import ne doit rien dupliquer
        if not bridge._ensure_qgis_trusted_cas():
            fail("tls", f"import des CA en échec (essai {attempt})")
            return
        if occurrences() != 1:
            fail("tls", f"CA Farois présente {occurrences()} fois dans la base (essai {attempt})")
    if len(mgr.databaseCAs()) != 2:
        fail("tls", f"{len(mgr.databaseCAs())} CA en base, 2 attendues")
    if mgr.certTrustPolicy(farois) != QgsAuthCertUtils.CertTrustPolicy.Trusted:
        fail("tls", "CA Farois sans la politique Trusted")

    # Config Basic jetable (son stockage exige un mot de passe maître).
    if not mgr.setMasterPassword("smoke-master", True):
        fail("tls", "mot de passe maître jetable refusé")
        return
    config = QgsAuthMethodConfig("Basic")
    config.setName("smoke_tls")
    config.setConfig("username", "smoke")
    config.setConfig("password", "smoke")
    if not bridge._stored(mgr.storeAuthenticationConfig(config)) or not config.id():
        fail("tls", "config Basic jetable non enregistrée")
        return
    try:
        items = ["dbname='smoke'", "host=127.0.0.1", "port=1", "sslmode=verify-full"]
        result = mgr.updateDataSourceUriItems(items, config.id(), "postgres")
        ok, items = result if isinstance(result, tuple) else (result, items)
        roots = [i.split("=", 1)[1].strip("'") for i in items if i.startswith("sslrootcert=")]
        if not ok or len(roots) != 1:
            fail("tls", f"updateDataSourceUriItems sans sslrootcert : {ok} {items}")
            return
        try:
            with open(roots[0], "rb") as f:
                ders = [cert.toDer().data() for cert in QSslCertificate.fromData(f.read())]
        finally:
            os.remove(roots[0])
        if farois_der not in ders:
            fail("tls", f"CA Farois absente du sslrootcert produit par QGIS ({len(ders)} CA)")
        else:
            print(f"  ok CA Farois dans le sslrootcert verify-full de QGIS ({len(ders)} CA)")
    finally:
        mgr.removeAuthenticationConfig(config.id())


print("== TLS nominatif (Bridge 1.8)")
try:
    check_bridge_tls()
except Exception:
    fail("tls", traceback.format_exc())

# --- 4. scripts Processing ---------------------------------------------------
print("== scripts Processing")
for script in SCRIPTS:
    namespace = {"__name__": f"script_{script.stem}", "__file__": str(script)}
    try:
        exec(compile(script.read_text(encoding="utf-8"), str(script), "exec"), namespace)
        algorithms = [
            value
            for value in namespace.values()
            if isinstance(value, type)
            and issubclass(value, QgsProcessingAlgorithm)
            and value is not QgsProcessingAlgorithm
        ]
        if not algorithms:
            fail(script.name, "aucun QgsProcessingAlgorithm")
        for cls in algorithms:
            algorithm = cls().createInstance()
            algorithm.initAlgorithm({})
            count = len(algorithm.parameterDefinitions())
            print(f"  ok {script.name} : {cls.__name__} ({count} paramètres)")
    except Exception:
        fail(script.name, traceback.format_exc())

# Bruit attendu du banc : pas de pip inscriptible, base injoignable, pas de
# mot de passe maître ni d'installateur de plugins dans un QGIS sans interface.
EXPECTED_LOG = (
    "'extract-msg'",
    "Connection failed to 127.0.0.1:1/smoke",
    "pyplugin_installer unavailable",
    "Auth Manager not available, cannot store encrypted password",
    "Auth Manager unavailable, PG connection 'be' has no saved password",
)
print("== journal QGIS (avertissements et erreurs)")
for level, tag, message in log:
    if level < 1 or tag == "Python warning":
        continue
    print(f"  [{level}] {tag} : {message}")
    if not any(expected in message for expected in EXPECTED_LOG):
        fail("journal", f"[{level}] {tag} : {message}")
print(f"== {len(failures)} échec(s)")
sys.exit(1 if failures else 0)
