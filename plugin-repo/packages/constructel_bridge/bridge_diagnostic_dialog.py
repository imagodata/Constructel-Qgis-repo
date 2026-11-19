# -*- coding: utf-8 -*-
"""
Constructel Bridge - Panneau « Statut et diagnostic » (1.9.0, spec
2026-11-12 § 6.6 et § 7, decisions D13 et D15 ; 2.0 : panneau hebergeable,
spec 2026-11-18 § 7 et § 8.3).

``DiagnosticPanel`` est un QWidget heberge par la fenetre laterale ;
``DiagnosticDialog`` en est l'enveloppe QDialog (bouton Fermer), utilisee par
``_on_diagnostic`` tant que la fenetre laterale ne l'a pas remplacee.

En tete, le message de l'ancien « Statut connexion ». Dessous, les quatre
verifications de ``bridge_diagnostic``, chacune avec son etat et, quand
c'est possible, un bouton d'action. Les verifications locales s'affichent
tout de suite ; les deux verifications reseau (``run_network_checks``,
echeance de 3 s chacune) tournent dans une QgsTask, hors du fil de
l'interface. Leur resultat est ignore si le panneau a ete ferme entre-temps
(``close_panel``) ; ``restart`` relance la sonde reseau.
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
LEVEL_MARKS = {
    LEVEL_OK: ("✔", "#2e7d32"),
    LEVEL_WARNING: ("⚠", "#ef6c00"),
    LEVEL_ERROR: ("✖", "#c62828"),
    LEVEL_RUNNING: ("…", "#757575"),
}
_LEVEL_MARKS = LEVEL_MARKS  # alias historique


def check_message(check: Check) -> str:
    render = _MESSAGES.get(check.message_key)
    return render(check.params) if render else check.message_key


def action_label(action: str) -> str:
    render = _ACTIONS.get(action)
    return render() if render else ""


def _network_job(task, network_args: dict) -> list:
    """Corps de la QgsTask (fil de travail) : aucun widget touche ici."""
    return run_network_checks(**network_args)


# Taches reseau en cours, gardees jusqu'a leur fin independamment du
# dialogue : le plugin detruit le dialogue ferme (deleteLater, relecture
# finale M5) et le wrapper Python d'une QgsTask non referencee peut etre
# collecte en plein travail. Liste (identite), relachee dans on_finished.
_PENDING_TASKS: list = []


def _release_task(task) -> None:
    for index, pending in enumerate(_PENDING_TASKS):
        if pending is task:
            del _PENDING_TASKS[index]
            return


class DiagnosticPanel(QWidget):
    def __init__(self, status_text: str, local_checks: list, network_args: dict,
                 on_action: Callable[[Check], list], parent=None):
        super().__init__(parent)
        self._on_action = on_action
        self._network_args = dict(network_args)
        self._local_checks = list(local_checks)
        self._network_checks = None  # None : verifications reseau en cours
        self._closed = False
        self._busy = False  # action en cours (boucle d'evenements imbriquee possible)
        self._task = None
        # Drapeau de destruction hors de l'objet C++ : un panneau heberge peut
        # etre detruit sans close_panel() (fenetre parente fermee, page
        # remplacee, decharge du plugin). La fermeture ne capture que ce dict
        # (jamais self), lu par le chemin du resultat tardif.
        state = {"destroyed": False}
        self._state = state
        self.destroyed.connect(lambda *_args: state.update(destroyed=True))

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
        self._restart_button = QPushButton(tr("diag.restart"))
        self._restart_button.clicked.connect(lambda _checked=False: self.restart())
        self._restart_button.setEnabled(False)  # reactive a la fin de la sonde reseau
        self._layout.addWidget(self._restart_button)

        self._start_network_task()

    def _start_network_task(self) -> None:
        # Reference gardee (panneau ET module) : sans elle, le wrapper Python
        # de la tache peut etre collecte avant la fin du travail, y compris
        # apres la destruction du panneau ferme. Le rappel porte sa propre
        # tache : le resultat d'une tache remplacee par restart() ne relache
        # ni n'ecrase la tache courante.
        holder: dict = {}

        def on_finished(exception, result=None) -> None:
            self._on_network_done(exception, result, holder["task"])

        task = QgsTask.fromFunction(
            tr("diag.title"), _network_job,
            network_args=dict(self._network_args), on_finished=on_finished,
        )
        holder["task"] = task
        self._task = task
        _PENDING_TASKS.append(task)
        QgsApplication.taskManager().addTask(task)

    def _build_rows(self) -> QWidget:
        container = QWidget(self)
        grid = QGridLayout(container)
        grid.setColumnStretch(1, 1)
        for row, check in enumerate(ordered_checks(self._local_checks, self._network_checks)):
            symbol, color = LEVEL_MARKS.get(check.level, LEVEL_MARKS[LEVEL_RUNNING])
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

    def _on_network_done(self, exception, result=None, task=None) -> None:
        """Fil de l'interface. QgsTaskWrapper appelle on_finished(exception)
        sans resultat si la tache a echoue ou a ete annulee. Panneau ferme
        (peut-etre deja detruit) : seuls des attributs Python sont lus."""
        task = self._task if task is None else task
        _release_task(task)
        if self._state["destroyed"] or self._closed or task is not self._task:
            return  # panneau detruit ou ferme, ou tache remplacee par restart()
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
        try:
            if not self._busy:
                self._render()
            self._restart_button.setEnabled(True)
        except RuntimeError:
            # « wrapped C/C++ object has been deleted » : panneau detruit sans
            # destroyed ni close_panel(). Plus rien a afficher, ni a rouvrir.
            self._state["destroyed"] = True
            self._closed = True

    def restart(self) -> None:
        """Relance la sonde reseau : lignes reseau repassees a « ... », nouvelle
        tache. Le resultat de la tache precedente, s'il arrive, est ignore."""
        if self._state["destroyed"]:
            return  # un panneau detruit ne se rouvre pas
        self._closed = False
        self._network_checks = None
        try:
            if not self._busy:  # pendant une action, _run_action redessine a la fin
                self._render()
            self._restart_button.setEnabled(False)  # reactive a la fin de la sonde
        except RuntimeError:
            self._state["destroyed"] = True
            self._closed = True
            return
        self._start_network_task()

    def close_panel(self) -> None:
        """Fermeture (equivalent de ``done`` du dialogue) : un resultat reseau
        tardif est ignore."""
        self._closed = True


class DiagnosticDialog(QDialog):
    """Enveloppe QDialog du panneau (``_on_diagnostic``, jusqu'a la fenetre
    laterale)."""

    def __init__(self, parent, status_text: str, local_checks: list, network_args: dict,
                 on_action: Callable[[Check], list]):
        super().__init__(parent)
        self.setWindowTitle(tr("diag.title"))
        self.setMinimumWidth(620)
        self.panel = DiagnosticPanel(status_text, local_checks, network_args, on_action, self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.panel)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def done(self, result) -> None:
        # Fermeture (bouton, Echap, croix) : un resultat reseau tardif est ignore.
        self.panel.close_panel()
        super().done(result)

    def exec(self) -> int:
        # exec() peut aussi finir sans done() (dialogue cache) ; le plugin
        # detruit ensuite le dialogue (deleteLater) : resultat tardif ignore.
        try:
            return super().exec()
        finally:
            self.panel.close_panel()
