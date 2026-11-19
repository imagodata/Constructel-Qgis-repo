# -*- coding: utf-8 -*-
"""
Constructel Bridge - fenetre d'accueil 2.0 a barre laterale (plan 2026-11-18
tache 9, spec § 6.1, § 6.5, § 7, § 8.3).

A gauche, la barre laterale : quatre entrees (Charger les couches, Projet
enregistre, Check-in avec sa pastille, Diagnostic) puis, en bas, l'etat de la
connexion (point, « login · perimetre » ou « non connecte », bouton « Se
connecter »), la langue (FR · EN · PT) et la version du plugin. A droite, la
page de l'entree choisie, dans un QStackedWidget ; chaque page n'est
construite qu'a son premier affichage (Projets n'interroge la base que si on
l'ouvre).

Toute la logique d'etat vient de bridge_home_model ; les pages vivent dans
leurs modules (bridge_home_load, bridge_home_projects, bridge_home_checkin,
bridge_diagnostic_dialog). ``render()`` reconstruit tout depuis
``actions.snapshot()`` (connexion, langue, chargement sans effet) en gardant
la page courante et, pour Charger, le choix affiche. La fenetre se ferme
apres un chargement qui a ajoute quelque chose et avant d'ouvrir un projet
enregistre (D11, T9-c1b). La sonde reseau du Diagnostic est close
(``close_panel``) quand la fenetre se ferme, quand on quitte sa page et
avant que ``render()`` ne la remplace. Aucune couleur de fond codee en dur :
la barre suit la palette de QGIS (theme clair ou sombre).
"""

from __future__ import annotations

import dataclasses

from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .bridge_diagnostic import LEVEL_OK, LEVEL_RUNNING
from .bridge_diagnostic_dialog import LEVEL_MARKS, DiagnosticPanel
from .bridge_home_checkin import CheckinPage
from .bridge_home_load import LoadPage
from .bridge_home_model import HomeActions, home_state
from .bridge_home_projects import ProjectsPage
from .bridge_presets import LAST_SELECTION_NAME, UserPreset
from .i18n import SUPPORTED_LANGUAGES, get_language, tr

PAGES = ("load", "projects", "checkin", "diagnostic")
_SIDEBAR_WIDTH = 230
_STATUS_DOT = "●"


class HomeDialog(QDialog):
    """Fenetre d'accueil. *actions* : HomeActions fournies par le plugin ;
    *page* : page affichee a l'ouverture (une de ``PAGES``, sinon Charger) ;
    *start_wizard* : la page Check-in lance l'assistant a sa construction
    (premier setup), une seule fois."""

    PAGES = PAGES

    def __init__(self, actions: HomeActions, parent=None, page: str = "load", start_wizard: bool = False):
        super().__init__(parent)
        self.actions = actions
        self._current = page if page in PAGES else "load"
        self._start_wizard = bool(start_wizard)
        self._pages: dict = {}
        self._indexes: dict = {}
        self._load_choice = None        # choix de la page Charger, garde d'un redessin a l'autre
        self._load_editable = False     # la page Charger etait-elle utilisable (connecte) ?
        self._diagnostic_left = False   # panneau clos en quittant sa page : relance au retour
        self._footer = None
        self._connect_button = None
        self._lang_buttons: dict = {}

        self.setWindowTitle("Constructel Bridge")
        self.setMinimumSize(980, 640)
        self.resize(1100, 720)

        root = QHBoxLayout(self)
        self._side = QWidget(self)
        self._side.setFixedWidth(_SIDEBAR_WIDTH)
        self._side_layout = QVBoxLayout(self._side)
        self._sidebar = QListWidget(self._side)
        self._sidebar.currentRowChanged.connect(self._on_row_changed)
        self._side_layout.addWidget(self._sidebar, 1)
        root.addWidget(self._side)
        self._stack = QStackedWidget(self)
        root.addWidget(self._stack, 1)
        self.render()

    # -- construction -------------------------------------------------------------------

    def render(self) -> None:
        """Reconstruit barre et pages depuis ``actions.snapshot()`` ; la page
        courante et le choix de Charger sont gardes, les autres pages seront
        reconstruites a leur prochain affichage."""
        self._keep_load_choice()
        self._close_diagnostic()
        for page in self._pages.values():
            self._stack.removeWidget(page)
            # Suppression differee : render() peut venir d'un clic dans une page.
            page.hide()
            page.deleteLater()
        self._pages, self._indexes = {}, {}
        self._diagnostic_left = False
        self._read_snapshot()
        self._build_chrome()
        self.show_page(self._current)

    def _read_snapshot(self) -> None:
        self._snapshot = self.actions.snapshot()
        self._state = home_state(self._snapshot)

    def _build_chrome(self) -> None:
        """Entrees de la barre (pastille du Check-in) et bas de barre."""
        labels = self._nav_labels()
        blocked = self._sidebar.blockSignals(True)
        try:
            self._sidebar.clear()
            for name in PAGES:
                self._sidebar.addItem(labels[name])
            self._sidebar.setCurrentRow(PAGES.index(self._current))
        finally:
            self._sidebar.blockSignals(blocked)
        footer = self._build_footer()
        if self._footer is None:
            self._side_layout.addWidget(footer)
        else:
            self._side_layout.replaceWidget(self._footer, footer)
            self._footer.hide()
            self._footer.deleteLater()
        self._footer = footer

    def _nav_labels(self) -> dict:
        checkin = tr("home.nav_checkin")
        badge = self._state.checkin_badge
        if badge:
            checkin = f"{checkin}  ⚠ {badge}"
        return {
            "load": tr("home.nav_load"),
            "projects": tr("home.nav_projects"),
            "checkin": checkin,
            "diagnostic": tr("home.nav_diagnostic"),
        }

    def _build_footer(self) -> QWidget:
        snapshot = self._snapshot
        footer = QWidget(self._side)
        layout = QVBoxLayout(footer)

        status = QHBoxLayout()
        _symbol, color = LEVEL_MARKS[LEVEL_OK if snapshot.connected else LEVEL_RUNNING]
        dot = QLabel(_STATUS_DOT)
        dot.setStyleSheet(f"color: {color};")     # couleur du texte seulement ; le fond suit la palette
        status.addWidget(dot)
        header = QLabel(snapshot.header if snapshot.connected else tr("home.not_connected"))
        header.setWordWrap(True)
        status.addWidget(header, 1)
        layout.addLayout(status)

        self._connect_button = None
        if not snapshot.connected:
            self._connect_button = QPushButton(tr("home.connect"))
            self._connect_button.clicked.connect(lambda _checked=False: self._on_connect())
            layout.addWidget(self._connect_button)

        languages = QHBoxLayout()
        current = get_language()
        self._lang_buttons = {}
        for code in SUPPORTED_LANGUAGES:
            button = QPushButton(code.upper())
            button.setCheckable(True)
            button.setChecked(code == current)
            button.setFlat(True)
            button.clicked.connect(lambda _checked=False, code=code: self._on_language(code))
            languages.addWidget(button)
            self._lang_buttons[code] = button
        languages.addStretch()
        layout.addLayout(languages)

        if snapshot.plugin_version:
            version = QLabel(f"Constructel Bridge {snapshot.plugin_version}")
            version.setEnabled(False)               # texte attenue, couleur de la palette
            layout.addWidget(version)
        return footer

    def _build_page(self, name: str) -> QWidget:
        snapshot, actions = self._snapshot, self.actions
        if name == "load":
            snapshot, state = self._load_inputs()
            self._load_editable = state.load_enabled
            return LoadPage(snapshot, state, actions, self._on_load_done, self._stack)
        if name == "projects":
            return ProjectsPage(actions, snapshot.connected, snapshot.labels, self.accept, self._stack)
        if name == "checkin":
            start, self._start_wizard = self._start_wizard, False   # premier setup : une fois
            page = CheckinPage(snapshot, actions, self._stack, start_wizard=start, email=snapshot.email)
            page.on_change = self._refresh_chrome
            return page
        status_text, local_checks, network_args = actions.diagnostic_inputs()
        return DiagnosticPanel(status_text, local_checks, network_args, actions.diagnostic_action, self._stack)

    def _load_inputs(self) -> tuple:
        """(instantane, etat) de la page Charger : apres un redessin, le choix
        affiche avant (perimetre et selection) remplace le dernier choix du
        poste. Un choix fait hors connexion (page inerte) n'est jamais garde."""
        choice = self._load_choice
        if choice is None:
            return self._snapshot, self._state
        kept = UserPreset(LAST_SELECTION_NAME, choice.schemas, choice.selection)
        snapshot = dataclasses.replace(self._snapshot, last_selection=kept)
        return snapshot, home_state(snapshot)

    def _keep_load_choice(self) -> None:
        page = self._pages.get("load")
        if page is not None and self._load_editable:
            self._load_choice = page.current_choice()

    # -- navigation ------------------------------------------------------------------------

    def show_page(self, name: str) -> None:
        """Affiche la page *name* (construite a son premier affichage) et
        selectionne son entree dans la barre."""
        if name not in PAGES:
            name = "load"
        previous = self._current
        if previous == "diagnostic" and name != "diagnostic" and "diagnostic" in self._pages:
            self._close_diagnostic()
            self._diagnostic_left = True
        self._current = name
        page = self._pages.get(name)
        if page is None:
            page = self._build_page(name)
            self._pages[name] = page
            self._indexes[name] = self._stack.addWidget(page)
        elif name == "diagnostic" and self._diagnostic_left:
            self._diagnostic_left = False
            page.restart()                      # sonde close en quittant la page : relancee
        self._stack.setCurrentIndex(self._indexes[name])
        blocked = self._sidebar.blockSignals(True)
        try:
            self._sidebar.setCurrentRow(PAGES.index(name))
        finally:
            self._sidebar.blockSignals(blocked)

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(PAGES) and PAGES[row] != self._current:
            self.show_page(PAGES[row])

    def _refresh_chrome(self) -> None:
        """Apres une action du Check-in : barre et bas de barre relus (pastille),
        pages inchangees (la page Check-in s'est deja redessinee)."""
        self._read_snapshot()
        self._build_chrome()

    # -- gestes ----------------------------------------------------------------------------

    def _on_load_done(self, loaded: bool) -> None:
        if loaded:
            self.accept()
        else:
            # Echec ou rien de nouveau : la fenetre reste ouverte, a jour (T9-c1b).
            self.render()

    def _on_connect(self) -> None:
        self.actions.connect()
        self.render()

    def _on_language(self, code: str) -> None:
        self.actions.set_language(code)
        self.render()

    # -- fermeture -------------------------------------------------------------------------

    def _close_diagnostic(self) -> None:
        panel = self._pages.get("diagnostic")
        if panel is not None:
            panel.close_panel()

    def done(self, result) -> None:
        # Toute fermeture (bouton, Echap, croix, chargement, projet ouvert) :
        # un resultat reseau tardif du Diagnostic est ignore.
        self._close_diagnostic()
        super().done(result)

    def exec(self) -> int:
        # exec() peut aussi finir sans done() (fenetre cachee) ; le plugin
        # detruit ensuite la fenetre (deleteLater) : resultat tardif ignore.
        try:
            return super().exec()
        finally:
            self._close_diagnostic()
