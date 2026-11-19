"""Captures Qt reel (2.0.2) : la fenetre d'accueil construite avec de VRAIS
widgets PyQt5 (rendu hors ecran, style Fusion), photographiee page par page
sous trois palettes proches de QGIS : sombre a surbrillance bleue, sombre a
surbrillance verte (#589632, « Night Mapping ») et claire. Sert a comparer
le rendu a la maquette ; meme montage que smoke_real_qt.py (stubs qgis.*).
Lancement manuel (non collecte par pytest) :

    QT_QPA_PLATFORM=offscreen python3 plugin-repo/packages/constructel_bridge_tests/screenshot_real_qt.py [dossier]

Sortie : un PNG par page et par palette dans *dossier* (defaut : ./qtshots),
plus la page Charger a 1100x680 (ecran 1366x768) et la barre laterale seule.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smoke_real_qt as smoke  # noqa: E402  (installe stubs, QApplication et PyQt5)

from PyQt5 import QtGui, QtWidgets  # noqa: E402

from constructel_bridge import bridge_home_model as hm  # noqa: E402
from constructel_bridge.bridge_diagnostic import Check, PluginSummary  # noqa: E402
from constructel_bridge.bridge_project_init import LoadedCounts  # noqa: E402
from constructel_bridge.i18n import set_language  # noqa: E402

app = smoke.app


def _palette(window, base, alternate, text, button, highlight, highlighted_text, mid, dark, light):
    palette = QtGui.QPalette()
    role = QtGui.QPalette.ColorRole
    group = QtGui.QPalette.ColorGroup
    for name, value in (("Window", window), ("WindowText", text), ("Base", base), ("AlternateBase", alternate),
                        ("Text", text), ("Button", button), ("ButtonText", text), ("Highlight", highlight),
                        ("HighlightedText", highlighted_text), ("ToolTipBase", base), ("ToolTipText", text),
                        ("Mid", mid), ("Dark", dark), ("Light", light), ("Midlight", light),
                        ("BrightText", "#ff5555"), ("Link", highlight)):
        palette.setColor(getattr(role, name), QtGui.QColor(value))
    disabled = QtGui.QColor(text)
    disabled.setAlpha(110)
    for name in ("WindowText", "Text", "ButtonText"):
        palette.setColor(group.Disabled, getattr(role, name), disabled)
    return palette


PALETTES = {
    "dark-blue": _palette("#323232", "#262626", "#2d2d2d", "#e6e6e6", "#3a3a3a", "#2c6bbf", "#ffffff",
                          "#1f1f1f", "#141414", "#4a4a4a"),
    "dark-green": _palette("#323232", "#262626", "#2d2d2d", "#e6e6e6", "#3a3a3a", "#589632", "#ffffff",
                           "#1f1f1f", "#141414", "#4a4a4a"),
    "light": _palette("#efefef", "#ffffff", "#f7f7f7", "#1e1e1e", "#e6e6e6", "#2c6bbf", "#ffffff",
                      "#b8b8b8", "#9f9f9f", "#ffffff"),
}


def _snapshot():
    snap = smoke.snapshot()
    checks = hm.CheckinState(PluginSummary(5, 6, 1), True, False)
    return snap.__class__(**{**snap.__dict__, "counts": LoadedCounts({"wyre": 9}, 0, 2), "checkin": checks})


def _actions():
    actions = smoke.actions()
    checks = [Check("plugin", "ok", "diag.plugin_ok", {"name": "FilterMate"}),
              Check("plugin", "ok", "diag.plugin_ok", {"name": "QField Sync"}),
              Check("plugin", "warning", "diag.plugin_missing", {"name": "Plugin Reloader"}, action="install"),
              Check("plugin", "warning", "diag.plugin_update", {"name": "Resource Sharing"}, action="update")]
    inputs = actions.diagnostic_inputs()
    return actions.__class__(**{**actions.__dict__,
                                "diagnostic_inputs": lambda: (inputs[0], checks, inputs[2])})


def _windows_fonts() -> None:
    """Segoe UI 9 pt (police de QGIS sous Windows) et ses emoji, si les polices
    Windows sont lisibles (WSL) ; sinon la police du systeme."""
    fonts = Path("/mnt/c/Windows/Fonts")
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf", "seguiemj.ttf"):
        if (fonts / name).exists():
            QtGui.QFontDatabase.addApplicationFont(str(fonts / name))
    QtGui.QFont.insertSubstitutions("Segoe UI", ["Segoe UI Symbol", "Segoe UI Emoji"])
    app.setFont(QtGui.QFont("Segoe UI", 9))


def _shoot(widget, path: Path) -> None:
    app.processEvents()
    widget.grab().save(str(path))
    print("wrote", path)


def main(out: Path) -> int:
    from constructel_bridge.bridge_home import HomeDialog

    out.mkdir(parents=True, exist_ok=True)
    QtWidgets.QApplication.setStyle("Fusion")
    _windows_fonts()
    set_language("fr")
    for name, palette in PALETTES.items():
        app.setPalette(palette)
        smoke.STATE["snap"] = _snapshot()
        dialog = HomeDialog(_actions(), None)
        dialog.setMinimumSize(0, 0)
        dialog.resize(1100, 720)
        dialog.show()
        load = dialog._pages["load"]
        load._operator_buttons["orange"].click()
        selection = load._selection
        selection.toggle_tile("genie_civil")               # tuile « on »
        selection.toggle_tile("osiris")
        items = [item for (schema, key), item in selection._items.items() if schema is None and key.startswith("wfs_")]
        if items:
            items[0].setCheckState(0, items[0].checkState(0).__class__.Checked)   # cadastre : partielle
        _shoot(dialog, out / f"load-{name}.png")
        dialog.resize(1100, 680)
        _shoot(dialog, out / f"load-{name}-1100x680.png")
        dialog.resize(1100, 720)
        for page in ("checkin", "diagnostic", "projects"):
            dialog.show_page(page)
            _shoot(dialog, out / f"{page}-{name}.png")
        dialog.show_page("load")
        _shoot(dialog._side, out / f"sidebar-{name}.png")
        dialog.reject()
        dialog.deleteLater()
        app.processEvents()
    print("SCREENSHOTS OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("qtshots")))
