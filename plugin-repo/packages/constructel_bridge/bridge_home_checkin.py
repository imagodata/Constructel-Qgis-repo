# -*- coding: utf-8 -*-
"""
Constructel Bridge - page « Check-in » de l'accueil 2.0 (plan 2026-11-18
tache 6, spec § 6.4, § 6.5, § 7).

L'etat, puis les actions : profil (login, e-mail si connu), une ligne par
extension recommandee avec son bouton (Installer / Mettre a jour / Activer,
memes actions que le Diagnostic), puis les partages Constructel (Resource
Sharing, FilterMate : configure ou non, bouton « Configurer »). « Refaire le
check-in complet » heberge l'assistant (OnboardingWizard, fenetre sans cadre)
DANS la page a la place des lignes ; a sa fin les lignes sont relues.

Aucun acces reseau ni lecture de l'etat interne de Resource Sharing : l'etat
des partages est celui de leurs reglages (bridge_onboarding). La page relaie
vers HomeActions ; ``on_change`` previent la fenetre (redessin, pastille).
"""

from __future__ import annotations

from typing import Callable, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .bridge_diagnostic_dialog import LEVEL_MARKS, action_label, check_message
from .bridge_diagnostic import LEVEL_OK, LEVEL_RUNNING, LEVEL_WARNING, Check
from .bridge_home_model import HomeActions, HomeSnapshot
from .bridge_onboarding import filtermate_configured, resource_sharing_configured
from .i18n import tr

SEPARATOR = " · "

# Marque de chaque etat de partage (couleurs deja utilisees par le Diagnostic) ;
# None = extension absente, sans objet.
_SHARING_MARKS = {
    True: LEVEL_MARKS[LEVEL_OK],
    False: LEVEL_MARKS[LEVEL_WARNING],
    None: ("–", LEVEL_MARKS[LEVEL_RUNNING][1]),
}


def _section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet("font-weight: bold;")
    return label


def _mark_label(mark) -> QLabel:
    symbol, color = mark
    label = QLabel(symbol)
    label.setStyleSheet(f"color: {color}; font-weight: bold;")
    return label


def _text_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class CheckinPage(QWidget):
    """Page « Check-in ». *start_wizard* : lance l'assistant des l'ouverture
    (premier setup). *email* : e-mail du profil, s'il est connu de l'appelant
    (``HomeSnapshot.email``) ; le login vient de ``HomeSnapshot.login``."""

    def __init__(self, snapshot: HomeSnapshot, actions: HomeActions, parent=None,
                 start_wizard: bool = False, email: str = ""):
        super().__init__(parent)
        self._snapshot = snapshot
        self._actions = actions
        self._email = email
        self._message = ""                       # retour de la derniere action « Configurer »
        self._wizard = None                      # assistant heberge, None sinon
        self.on_change: Optional[Callable[[], None]] = None

        self._layout = QVBoxLayout(self)
        self._layout.addWidget(_section_title(tr("home.checkin_title")))
        self._profile_label = _text_label(self._profile_text())
        self._layout.addWidget(self._profile_label)
        self._rows = self._build_rows(self._read_plugin_checks())
        self._layout.addWidget(self._rows)
        self._wizard_button = QPushButton(tr("home.checkin_full"))
        self._wizard_button.clicked.connect(lambda _checked=False: self._start_wizard())
        self._layout.addWidget(self._wizard_button)
        self._layout.addStretch()
        if start_wizard:
            self._start_wizard()

    # -- construction ------------------------------------------------------------------

    def _profile_text(self) -> str:
        snapshot = self._snapshot
        login = snapshot.login.strip() if snapshot.connected else ""
        if not login:
            return tr("home.checkin_profile_offline")
        text = tr("home.checkin_profile", login=login)
        return f"{text}{SEPARATOR}{self._email}" if self._email else text

    def _read_plugin_checks(self) -> list:
        return self._plugin_only(self._actions.diagnostic_inputs()[1])

    @staticmethod
    def _plugin_only(checks) -> list:
        return [c for c in checks if c.key == "plugin"]

    def _build_rows(self, checks: list) -> QWidget:
        """Extensions recommandees, puis partages Constructel."""
        container = QWidget(self)
        box = QVBoxLayout(container)
        box.addWidget(_section_title(tr("home.checkin_plugins")))
        for check in checks:
            box.addLayout(self._check_row(check))
        box.addWidget(_section_title(tr("home.checkin_sharing")))
        rs, fm = resource_sharing_configured(), filtermate_configured()
        box.addLayout(self._sharing_row(
            "resource_sharing", rs,
            tr("home.rs_configured") if rs else tr("home.rs_missing")))
        box.addLayout(self._sharing_row(
            "filtermate", fm,
            tr("home.fm_configured") if fm else tr("home.fm_missing")))
        if self._message:
            box.addWidget(_text_label(self._message))
        return container

    def _check_row(self, check: Check) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(_mark_label(LEVEL_MARKS.get(check.level, LEVEL_MARKS[LEVEL_RUNNING])))
        row.addWidget(_text_label(check_message(check)), 1)
        label = action_label(check.action)
        if label:
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, c=check: self._run_action(c))
            row.addWidget(button)
        return row

    def _sharing_row(self, kind: str, configured: Optional[bool], text: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(_mark_label(_SHARING_MARKS[configured]))
        row.addWidget(_text_label(tr("home.sharing_na") if configured is None else text), 1)
        if configured is False:
            button = QPushButton(tr("home.configure"))
            button.clicked.connect(lambda _checked=False, k=kind: self._configure(k))
            row.addWidget(button)
        return row

    def _refresh(self, checks: Optional[list] = None) -> None:
        """Relit l'etat et redessine les lignes (hors assistant heberge, qui
        les masque)."""
        rows = self._build_rows(self._read_plugin_checks() if checks is None else checks)
        self._layout.replaceWidget(self._rows, rows)
        self._rows.hide()
        self._rows.deleteLater()
        self._rows = rows
        if self._wizard is not None:
            rows.hide()

    def _notify(self) -> None:
        if self.on_change is not None:
            self.on_change()

    # -- actions ------------------------------------------------------------------------

    def _run_action(self, check: Check) -> None:
        """Action d'une extension (installation, mise a jour, activation) :
        pas de double clic pendant qu'elle tourne ; les lignes se redessinent
        sur les verifications rendues, meme si l'action a echoue."""
        self._message = ""
        self.setEnabled(False)
        checks = None
        try:
            checks = self._actions.diagnostic_action(check)
        finally:
            self.setEnabled(True)
            self._refresh(self._plugin_only(checks) if checks is not None else None)
        self._notify()

    def _configure(self, kind: str) -> None:
        self.setEnabled(False)
        try:
            self._message = self._actions.configure_sharing(kind) or ""
        finally:
            self.setEnabled(True)
            self._refresh()
        self._notify()

    # -- assistant heberge ---------------------------------------------------------------

    def _start_wizard(self) -> None:
        """« Refaire le check-in complet » : l'assistant remplace les lignes
        dans la page (un QWizard sans cadre), jamais de seconde fenetre."""
        if self._wizard is not None:
            return
        wizard = self._actions.make_wizard(self)
        if wizard is None:
            return
        self._wizard = wizard
        wizard.setWindowFlags(Qt.WindowType.Widget)
        wizard.finished.connect(self._on_wizard_finished)
        self._rows.hide()
        self._wizard_button.hide()
        self._layout.addWidget(wizard, 1)
        wizard.show()

    def _on_wizard_finished(self, _result=0) -> None:
        wizard, self._wizard = self._wizard, None
        if wizard is not None:
            self._layout.removeWidget(wizard)
            wizard.hide()
            wizard.deleteLater()
        self._wizard_button.show()
        self._refresh()
        self._notify()
