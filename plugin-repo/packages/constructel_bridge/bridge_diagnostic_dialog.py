# -*- coding: utf-8 -*-
"""
Constructel Bridge - Dialogue « Statut et diagnostic » (1.9.0, spec
2026-11-12 § 6.6 et § 7, decisions D13 et D15).

En tete, le message de l'ancien « Statut connexion ». Dessous, les quatre
verifications de ``bridge_diagnostic``, chacune avec son etat et, quand
c'est possible, un bouton d'action. Les verifications locales s'affichent
tout de suite ; les deux verifications reseau (``run_network_checks``,
echeance de 3 s chacune) tournent dans une QgsTask, hors du fil de
l'interface. Leur resultat est ignore si le dialogue a ete ferme entre-temps.
"""

from __future__ import annotations

from typing import Callable

from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .bridge_diagnostic import (
    LEVEL_ERROR,
    LEVEL_OK,
    LEVEL_RUNNING,
    LEVEL_WARNING,
    Check,
    ordered_checks,
    run_network_checks,
    server_check,
    version_check,
)
from .i18n import tr

# K11 : un appel tr LITTERAL (cle ecrite en toutes lettres) par cle de message (relevee par
# test_bridge18_i18n), jamais de cle calculee.
_MESSAGES = {
    "diag.running": lambda p: tr("diag.running"),
    "diag.version_ok": lambda p: tr("diag.version_ok", **p),
    "diag.version_update": lambda p: tr("diag.version_update", **p),
    "diag.version_unknown": lambda p: tr("diag.version_unknown", **p),
    "diag.plugin_ok": lambda p: tr("diag.plugin_ok", **p),
    "diag.plugin_update": lambda p: tr("diag.plugin_update", **p),
    "diag.plugin_inactive": lambda p: tr("diag.plugin_inactive", **p),
    "diag.plugin_missing": lambda p: tr("diag.plugin_missing", **p),
    "diag.server_ok": lambda p: tr("diag.server_ok", **p),
    "diag.server_unreachable": lambda p: tr("diag.server_unreachable", **p),
    "diag.server_tls_refused": lambda p: tr("diag.server_tls_refused", **p),
    "diag.server_cert_invalid": lambda p: tr("diag.server_cert_invalid", **p),
    "diag.identity_ok": lambda p: tr("diag.identity_ok", **p),
    "diag.identity_no_password": lambda p: tr("diag.identity_no_password", **p),
    "diag.identity_derived": lambda p: tr("diag.identity_derived", **p),
    "diag.identity_none": lambda p: tr("diag.identity_none"),
}
_ACTIONS = {
    "install": lambda: tr("diag.action_install"),
    "update": lambda: tr("diag.action_update"),
    "activate": lambda: tr("diag.action_activate"),
    "plugin_manager": lambda: tr("diag.action_plugin_manager"),
}
# Symbole et couleur de chaque niveau.
_LEVEL_MARKS = {
    LEVEL_OK: ("✔", "#2e7d32"),
    LEVEL_WARNING: ("⚠", "#ef6c00"),
    LEVEL_ERROR: ("✖", "#c62828"),
    LEVEL_RUNNING: ("…", "#757575"),
}


def check_message(check: Check) -> str:
    render = _MESSAGES.get(check.message_key)
    return render(check.params) if render else check.message_key


def action_label(action: str) -> str:
    render = _ACTIONS.get(action)
    return render() if render else ""


def _network_job(task, network_args: dict) -> list:
    """Corps de la QgsTask (fil de travail) : aucun widget touche ici."""
    return run_network_checks(**network_args)


class DiagnosticDialog(QDialog):
    def __init__(self, parent, status_text: str, local_checks: list, network_args: dict,
                 on_action: Callable[[Check], list]):
        super().__init__(parent)
        self.setWindowTitle(tr("diag.title"))
        self.setMinimumWidth(620)
        self._on_action = on_action
        self._network_args = dict(network_args)
        self._local_checks = list(local_checks)
        self._network_checks = None  # None : verifications reseau en cours
        self._closed = False
        self._busy = False  # action en cours (boucle d'evenements imbriquee possible)

        self._layout = QVBoxLayout(self)
        title = QLabel(tr("diag.section_connection"))
        title.setStyleSheet("font-weight: bold;")
        self._layout.addWidget(title)
        status = QLabel(status_text)
        status.setTextFormat(Qt.TextFormat.PlainText)
        status.setWordWrap(True)
        self._layout.addWidget(status)
        self._rows = self._build_rows()
        self._layout.addWidget(self._rows)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        self._layout.addWidget(buttons)

        # Reference gardee : sans elle, le wrapper Python de la tache peut
        # etre collecte avant la fin du travail.
        self._task = QgsTask.fromFunction(
            tr("diag.title"), _network_job,
            network_args=dict(self._network_args), on_finished=self._on_network_done,
        )
        QgsApplication.taskManager().addTask(self._task)

    def _build_rows(self) -> QWidget:
        container = QWidget(self)
        grid = QGridLayout(container)
        grid.setColumnStretch(1, 1)
        for row, check in enumerate(ordered_checks(self._local_checks, self._network_checks)):
            symbol, color = _LEVEL_MARKS.get(check.level, _LEVEL_MARKS[LEVEL_RUNNING])
            mark = QLabel(symbol)
            mark.setStyleSheet(f"color: {color}; font-weight: bold;")
            grid.addWidget(mark, row, 0)
            text = QLabel(check_message(check))
            text.setTextFormat(Qt.TextFormat.PlainText)
            text.setWordWrap(True)
            grid.addWidget(text, row, 1)
            label = action_label(check.action)
            if label:
                button = QPushButton(label)
                button.clicked.connect(lambda _checked=False, c=check: self._run_action(c))
                grid.addWidget(button, row, 2)
        return container

    def _render(self) -> None:
        rows = self._build_rows()
        self._layout.replaceWidget(self._rows, rows)
        self._rows.hide()
        self._rows.deleteLater()
        self._rows = rows

    def _run_action(self, check: Check) -> None:
        self._busy = True
        self.setEnabled(False)  # pas de double clic pendant une installation
        local_checks = None
        try:
            local_checks = self._on_action(check)
        finally:
            self._busy = False
            self.setEnabled(True)
            if local_checks is not None:
                self._local_checks = list(local_checks)
            self._render()  # y compris un resultat reseau arrive pendant l'action

    def _on_network_done(self, exception, result=None) -> None:
        """Fil de l'interface. QgsTaskWrapper appelle on_finished(exception)
        sans resultat si la tache a echoue ou a ete annulee."""
        if self._closed:
            return
        if exception is not None or not result:
            error = str(exception) if exception is not None else "no result"
            args = self._network_args
            result = [
                version_check(args["installed_version"], None, error),
                server_check(args["host"], args["port"], "unreachable", error),
            ]
        self._network_checks = list(result)
        # Pendant une action (fetch de l'installeur, gestionnaire d'extensions :
        # boucle d'evenements imbriquee), ne pas detruire les lignes dont le
        # bouton est en cours de clic : _run_action redessine a la fin.
        if not self._busy:
            self._render()

    def done(self, result) -> None:
        # Fermeture (bouton, Echap, croix) : un resultat reseau tardif est ignore.
        self._closed = True
        super().done(result)
