# -*- coding: utf-8 -*-
"""
Constructel Bridge - page « Projets » de l'accueil 2.0 (plan 2026-11-18
tache 8, spec § 7 « Projet enregistre »).

Les projets QGIS stockes en base, groupes par schema : un groupe par
operateur (libelle fourni par l'appelant), « Commun » pour ``public``,
« Projets » pour le schema transverse ``projet`` (R7). Un champ de recherche
filtre sur le nom et la description, sans tenir compte de la casse ni des
accents ; « Ouvrir » (ou le double-clic) charge le projet choisi.

La fenetre se ferme AVANT l'ouverture (D11) : ``on_open()`` est appele, puis
``actions.open_project``. Hors connexion la base n'est jamais interrogee ;
une liste illisible (``list_projects()`` -> None) est dite par la page seule.
La page ne dessine que ce que la base donne : aucune section « Mes projets /
partages » (chantier 3) n'y est affichee en 2.0.
"""

from __future__ import annotations

import unicodedata
from typing import Callable, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .bridge_home_model import HomeActions
from .bridge_home_style import set_role
from .bridge_operators import PROJET_SCHEMA
from .i18n import tr

COMMON_SCHEMA = "public"


def normalize(text) -> str:
    """Forme de comparaison : sans accents ni casse (NFKD), ``None`` = vide."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def matches(project: dict, query: str) -> bool:
    """True si *query* figure dans le nom ou la description du projet."""
    needle = normalize(query.strip())
    if not needle:
        return True
    return needle in normalize(project.get("name")) or needle in normalize(project.get("description"))


class ProjectsPage(QWidget):
    """Page « Projets ». *labels* : schema -> libelle de l'operateur ;
    *on_open* : ferme la fenetre, appele avant ``actions.open_project``."""

    def __init__(self, actions: HomeActions, connected: bool, labels: dict,
                 on_open: Callable[[], None], parent=None):
        super().__init__(parent)
        self._actions = actions
        self._labels = dict(labels)
        self._on_open = on_open
        self._projects: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel(tr("home.projects_title"))
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("home.projects_search"))
        self._search.setClearButtonEnabled(True)
        layout.addWidget(self._search)

        self._message = QLabel("")
        self._message.setWordWrap(True)
        self._message.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._message)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderHidden(True)
        layout.addWidget(self._tree)

        self._open_button = QPushButton(tr("home.projects_open"))
        set_role(self._open_button, "primary")      # bouton principal de la page (feuille de style)
        layout.addWidget(self._open_button, 0, Qt.AlignmentFlag.AlignRight)

        self._search.textChanged.connect(lambda _text="": self._refresh())
        self._tree.currentItemChanged.connect(lambda *_args: self._update_open_state())
        self._tree.itemDoubleClicked.connect(lambda *_args: self._open_selected())
        self._open_button.clicked.connect(lambda _checked=False: self._open_selected())

        self._connected = bool(connected)
        self._unreadable = False
        if self._connected:
            projects = self._actions.list_projects()
            # None : liste illisible. Le plugin l'a journalisee sans boite ;
            # la page est seule a le dire (un message par echec).
            self._unreadable = projects is None
            self._projects = list(projects or [])
        self._refresh()

    # -- affichage -----------------------------------------------------------------------

    def _group_label(self, schema: str) -> str:
        if schema == COMMON_SCHEMA:
            return tr("home.projects_common")
        if schema == PROJET_SCHEMA:
            return tr("home.projects_projets")
        return self._labels.get(schema, schema)

    def _refresh(self) -> None:
        """Reconstruit l'arbre : groupes dans l'ordre de la liste recue, projets
        filtres par la recherche."""
        self._tree.clear()
        if not self._connected:
            self._show_message(tr("home.projects_offline"))
            self._search.setEnabled(False)
            self._update_open_state()
            return
        if self._unreadable:
            self._show_message(tr("home.projects_error"))
            self._update_open_state()
            return
        groups: dict = {}
        shown = 0
        for project in self._projects:
            if not matches(project, self._search.text()):
                continue
            schema = project.get("schema", "")
            group = groups.get(schema)
            if group is None:
                group = QTreeWidgetItem(self._tree, [self._group_label(schema)])
                groups[schema] = group
            item = QTreeWidgetItem(group, [project.get("name") or "", project.get("description") or ""])
            item.setData(0, Qt.ItemDataRole.UserRole, [schema, project.get("name")])
            if project.get("updated"):
                item.setToolTip(0, str(project["updated"]))
            shown += 1
        for group in groups.values():
            group.setExpanded(True)
        self._show_message("" if shown else tr("project.none_found"))
        self._update_open_state()

    def _show_message(self, text: str) -> None:
        self._message.setText(text)
        self._message.setVisible(bool(text))
        self._tree.setVisible(not text)

    # -- selection et ouverture ----------------------------------------------------------

    def _selected(self) -> Optional[tuple]:
        """(schema, nom) du projet choisi ; ``None`` si rien ou un groupe."""
        item = self._tree.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if not data:
            return None
        schema, name = data
        return schema, name

    def _update_open_state(self) -> None:
        self._open_button.setEnabled(self._selected() is not None)

    def _open_selected(self) -> None:
        selected = self._selected()
        if selected is None:
            return
        open_project = self._actions.open_project
        self._on_open()          # la fenetre se ferme d'abord (D11)
        open_project(*selected)
