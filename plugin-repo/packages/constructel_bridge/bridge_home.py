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

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from .bridge_diagnostic import LEVEL_OK, LEVEL_RUNNING, LEVEL_WARNING
from .bridge_diagnostic_dialog import LEVEL_MARKS, DiagnosticPanel
from .bridge_home_checkin import CheckinPage
from .bridge_home_load import LoadPage
from .bridge_home_model import HomeActions, home_state
from .bridge_home_projects import ProjectsPage
from .bridge_home_style import home_style_sheet, set_role
from .bridge_presets import LAST_SELECTION_NAME, UserPreset
from .i18n import SUPPORTED_LANGUAGES, get_language, tr

PAGES = ("load", "projects", "checkin", "diagnostic")
_SIDEBAR_WIDTH = 230
# Taille par defaut et minimale, bornees a l'ecran disponible (anti-objectif
# § 4 : 1366x768 sans debordement) ; marges pour le cadre et la barre de titre
# de la fenetre, hors de la geometrie du contenu.
_DEFAULT_SIZE = (1100, 720)
_MINIMUM_SIZE = (980, 640)
_FRAME_MARGIN = (16, 48)
_STATUS_DOT = "●"
# Icone de chaque entree de la barre : icone du theme QGIS (suit le theme
# clair ou sombre), sinon icone standard du style Qt.
_NAV_ICONS = {
    "load": ("/mActionAddLayer.svg", "SP_ArrowDown"),
    "projects": ("/mActionFileOpen.svg", "SP_DirOpenIcon"),
    "checkin": ("/mActionShowPluginManager.svg", "SP_DialogApplyButton"),
    "diagnostic": ("/mIconInfo.svg", "SP_MessageBoxInformation"),
}


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
        self._load_options = None       # ses options (fonds de plan, styles, suffixe), idem
        self._load_editable = False     # la page Charger etait-elle utilisable (connecte) ?
        self._diagnostic_left = False   # panneau clos en quittant sa page : relance au retour
        self._requested = None          # (page, assistant) demandes par le plugin, cf. request_page
        self._footer = None
        self._connect_button = None
        self._lang_buttons: dict = {}

        self.setWindowTitle("Constructel Bridge")
        size, minimum = self._fitted_sizes()
        self.setMinimumSize(*minimum)
        self.resize(*size)
        # Mise en forme (2.0.2) : feuille de style limitee a cette fenetre,
        # couleurs tirees de la palette de QGIS (bridge_home_style).
        self.setObjectName("bridgeHome")
        self.setStyleSheet(home_style_sheet(self.palette()))

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)
        self._side = QFrame(self)
        self._side.setObjectName("bridgeSide")
        self._side.setFixedWidth(_SIDEBAR_WIDTH)
        self._side_layout = QVBoxLayout(self._side)
        self._side_layout.setContentsMargins(6, 8, 6, 8)
        self._sidebar = QListWidget(self._side)
        self._sidebar.setObjectName("bridgeNav")
        self._sidebar.setIconSize(QSize(18, 18))
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
        if self._requested is not None:
            page, start_wizard = self._requested
            self._requested = None
            self._current = page if page in PAGES else self._current
            self._start_wizard = self._start_wizard or start_wizard
        self._keep_load_choice()
        self._close_diagnostic()
        # R13 : un Check-in qui heberge l'assistant n'est jamais detruit (sinon
        # l'assistant disparait sans « finished » et le setup se rejoue au
        # prochain demarrage) ; il garde sa page et son assistant.
        kept = {name: page for name, page in self._pages.items()
                if name == "checkin" and page.hosts_wizard()}
        for name, page in self._pages.items():
            if name in kept:
                continue
            self._stack.removeWidget(page)
            # Suppression differee : render() peut venir d'un clic dans une page.
            page.hide()
            page.deleteLater()
        if kept:
            self._start_wizard = False      # un assistant tourne deja : jamais un second
        # Pile reduite aux pages gardees, dans leur ordre d'ajout.
        self._pages = kept
        self._indexes = {name: index for index, name in enumerate(kept)}
        self._diagnostic_left = False
        self._read_snapshot()
        self._build_chrome()
        self.show_page(self._current)

    def _fitted_sizes(self) -> tuple:
        """((largeur, hauteur), (largeur min, hauteur min)) : 1100x720 et
        980x640 quand ils tiennent dans l'ecran disponible, sinon l'ecran
        disponible moins les marges du cadre et de la barre de titre."""
        available = self._available_size()
        if available is None:
            return _DEFAULT_SIZE, _MINIMUM_SIZE
        room = tuple(max(1, side - margin) for side, margin in zip(available, _FRAME_MARGIN))
        size = tuple(min(wanted, side) for wanted, side in zip(_DEFAULT_SIZE, room))
        minimum = tuple(min(wanted, side) for wanted, side in zip(_MINIMUM_SIZE, room))
        return size, minimum

    def _available_size(self):
        """(largeur, hauteur) de l'ecran disponible (hors barre des taches),
        None si illisible : Qt5 avant 5.14 (pas de ``screen()``), Qt6, doublures."""
        screen = None
        try:
            screen = self.screen()
        except Exception:  # noqa: BLE001 -- QWidget.screen() absent (Qt < 5.14, doublures)
            screen = None
        if screen is None:
            try:
                from qgis.PyQt.QtGui import QGuiApplication

                screen = QGuiApplication.primaryScreen()
            except Exception:  # noqa: BLE001 -- pas d'application graphique
                screen = None
        if screen is None:
            return None
        try:
            geometry = screen.availableGeometry()
            width, height = int(geometry.width()), int(geometry.height())
        except Exception:  # noqa: BLE001 -- geometrie illisible : tailles par defaut
            return None
        return (width, height) if width > 0 and height > 0 else None

    def _read_snapshot(self) -> None:
        self._snapshot = self.actions.snapshot()
        self._state = home_state(self._snapshot)

    def _build_chrome(self) -> None:
        """Entrees de la barre (pastille du Check-in) et bas de barre."""
        labels = self._nav_labels()
        blocked = self._sidebar.blockSignals(True)
        try:
            self._sidebar.clear()
            for row, name in enumerate(PAGES):
                self._sidebar.addItem(labels[name])
                self._decorate_nav_item(self._sidebar.item(row), name)
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

    def _decorate_nav_item(self, item, name: str) -> None:
        """Icone de l'entree ; pastille du Check-in en couleur d'alerte (texte
        seulement, comme les marques du Diagnostic)."""
        icon = self._nav_icon(name)
        if icon is not None:
            item.setIcon(icon)
        if name == "checkin" and self._state.checkin_badge:
            item.setToolTip(self._nav_labels()["checkin"])
            item.setForeground(QBrush(QColor(LEVEL_MARKS[LEVEL_WARNING][1])))

    def _nav_icon(self, name: str):
        """Icone du theme QGIS de l'entree *name*, sinon icone standard du
        style Qt ; None si aucune n'est lisible."""
        theme, standard = _NAV_ICONS[name]
        try:
            icon = QgsApplication.getThemeIcon(theme)
            if icon is not None and not icon.isNull():
                return icon
        except Exception:  # noqa: BLE001 -- hors QGIS (stubs) : icone du style Qt
            pass
        try:
            return self.style().standardIcon(getattr(QStyle.StandardPixmap, standard))
        except Exception:  # noqa: BLE001 -- doublures : pas d'icone
            return None

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
        layout.setContentsMargins(4, 4, 4, 0)

        status = QHBoxLayout()
        _symbol, color = LEVEL_MARKS[LEVEL_OK if snapshot.connected else LEVEL_RUNNING]
        dot = QLabel(_STATUS_DOT)
        dot.setStyleSheet(f"color: {color};")     # couleur du texte seulement ; le fond suit la palette
        status.addWidget(dot)
        header = QLabel(snapshot.header if snapshot.connected else tr("home.not_connected"))
        header.setWordWrap(True)
        status.addWidget(header, 1)
        layout.addLayout(status)

        locked = self._wizard_hosted()      # R13 : rien qui redessine pendant l'assistant
        self._connect_button = None
        if not snapshot.connected:
            self._connect_button = QPushButton(tr("home.connect"))
            self._connect_button.setEnabled(not locked)
            self._connect_button.clicked.connect(lambda _checked=False: self._on_connect())
            layout.addWidget(self._connect_button)

        languages = QHBoxLayout()
        current = get_language()
        self._lang_buttons = {}
        for code in SUPPORTED_LANGUAGES:
            button = QPushButton(code.upper())
            button.setCheckable(True)
            button.setChecked(code == current)
            set_role(button, "seg")
            button.setEnabled(not locked)
            button.clicked.connect(lambda _checked=False, code=code: self._on_language(code))
            languages.addWidget(button)
            self._lang_buttons[code] = button
        languages.addStretch()
        layout.addLayout(languages)

        if snapshot.plugin_version:
            version = QLabel(f"Constructel Bridge {snapshot.plugin_version}")
            set_role(version, "muted")              # texte attenue, couleur tiree de la palette
            layout.addWidget(version)
        return footer

    def _build_page(self, name: str) -> QWidget:
        snapshot, actions = self._snapshot, self.actions
        if name == "load":
            snapshot, state = self._load_inputs()
            self._load_editable = state.load_enabled
            options = self._load_options if self._load_choice is not None else None
            return LoadPage(snapshot, state, actions, self._on_load_done, self._stack, options=options)
        if name == "projects":
            return ProjectsPage(actions, snapshot.connected, snapshot.labels, self.accept, self._stack)
        if name == "checkin":
            start, self._start_wizard = self._start_wizard, False   # premier setup : une fois
            page = CheckinPage(snapshot, actions, self._stack, start_wizard=start, email=snapshot.email)
            page.on_change = self._refresh_chrome
            page.on_wizard_started = self._lock_for_wizard
            if page.hosts_wizard():        # premier setup : lance a la construction
                self._pages["checkin"] = page
                self._lock_for_wizard()
            return page
        status_text, local_checks, network_args = actions.diagnostic_inputs()
        panel = DiagnosticPanel(status_text, local_checks, network_args, actions.diagnostic_action, self._stack)
        panel.on_change = self._refresh_chrome      # pastille du Check-in apres une installation
        return panel

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
            self._load_options = page.current_options()

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
        self._set_default_buttons()

    def _set_default_buttons(self) -> None:
        """Entree ne presse jamais un bouton de la barre ou d'une page (dans un
        QDialog, tout QPushButton est « autoDefault ») : aucun bouton par
        defaut, sauf « Charger » quand la page Charger est affichee. Rejoue
        apres chaque redessin et chaque construction de page. Les boutons
        d'un dialogue heberge (assistant du Check-in) gardent les leurs."""
        page = self._pages.get("load") if self._current == "load" else None
        default = page.default_button() if page is not None else None
        for button in self.findChildren(QPushButton):
            if not self._owns(button):
                continue
            button.setAutoDefault(False)
            button.setDefault(button is default)

    def _owns(self, button) -> bool:
        """*button* releve de cette fenetre et non d'un dialogue heberge."""
        parent = button.parentWidget()
        while parent is not None and parent is not self:
            if isinstance(parent, QDialog):
                return False
            parent = parent.parentWidget()
        return True

    def request_page(self, name: str, start_wizard: bool = False) -> None:
        """Demande du plugin pendant une action de la fenetre, appliquee au
        redessin qui la suit : « Se connecter » qui declenche le premier setup
        bascule CETTE fenetre sur le Check-in, assistant lance, au lieu d'en
        ouvrir une seconde par-dessus."""
        self._requested = (name, bool(start_wizard))

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < len(PAGES) and PAGES[row] != self._current:
            self.show_page(PAGES[row])

    def _wizard_hosted(self) -> bool:
        page = self._pages.get("checkin")
        return page is not None and page.hosts_wizard()

    def _lock_for_wizard(self) -> None:
        """R13 : assistant heberge -> langue et connexion inactives (elles
        redessineraient la fenetre) ; reactivees par _refresh_chrome a sa fin."""
        for button in list(self._lang_buttons.values()) + [self._connect_button]:
            if button is not None:
                button.setEnabled(False)

    def _refresh_chrome(self) -> None:
        """Apres une action du Check-in ou du Diagnostic : barre et bas de
        barre relus (pastille), pages inchangees (la page s'est deja
        redessinee)."""
        self._read_snapshot()
        self._build_chrome()
        self._set_default_buttons()

    # -- gestes ----------------------------------------------------------------------------

    def _on_load_done(self, loaded: bool) -> None:
        if loaded:
            self.accept()
        else:
            # Echec ou rien de nouveau : la fenetre reste ouverte, a jour (T9-c1b).
            self.render()

    def _on_connect(self) -> None:
        if self._wizard_hosted():
            return
        try:
            self.actions.connect()
        finally:
            # Meme si la connexion leve : une demande du plugin (request_page)
            # ne reste jamais en attente, la fenetre reste a jour.
            self.render()

    def _on_language(self, code: str) -> None:
        if self._wizard_hosted():
            return                          # R13 : boutons inactifs, defense en plus
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
