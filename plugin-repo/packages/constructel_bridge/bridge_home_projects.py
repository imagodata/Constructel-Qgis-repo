# -*- coding: utf-8 -*-
"""
Constructel Bridge - page « Projets QGIS » de l'accueil (2.0 tache 8 ; 2.1,
spec § 7.6).

2.1 (projets QGIS du schema Farois `projet`, `state.qgis_reason == ""`) :
trois sections « Mes projets », « Partages avec moi », « Publies » (un projet
dans une seule section, priorite Mes projets > Publies > Partages), colonnes
nom · projet metier · detail ; les projets de reference des schemas operateur
et de ``public`` sont listes sous « Publies ». Boutons « Ouvrir »,
« Enregistrer le projet courant… », « Partager… » et « Supprimer » (ces deux
derniers sur un de MES projets QGIS seulement).

Login partage (``QGIS_NOMINATIVE``) : explication a la place des sections
personnelles, « Publies » = projets de reference seuls, enregistrement
desactive ; ``list_visible`` n'est jamais appelee. Base sans les fonctions du
lot (b) (``QGIS_UNAVAILABLE``) : page 2.0 (groupes par schema, ``projet``
compris en lecture seule). Hors connexion : message, aucune requete.

La fenetre se ferme AVANT l'ouverture (D11) : ``on_open()`` puis l'ouverture.
"""

from __future__ import annotations

import unicodedata
from typing import Callable, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .bridge_home_model import QGIS_NOMINATIVE, QGIS_OFFLINE, HomeActions
from .bridge_home_style import set_role
from .bridge_operators import PROJET_SCHEMA
from .bridge_qgis_projects import build_sections
from .i18n import tr

COMMON_SCHEMA = "public"

MODE_OFFLINE = "offline"
MODE_LEGACY = "legacy"          # page 2.0
MODE_QGIS = "qgis"              # page 2.1 complete
MODE_NOMINATIVE = "nominative"  # login partage : projets de reference seuls


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


def row_matches(row, query: str) -> bool:
    """Projet QGIS : nom, description ou libelle du projet metier."""
    needle = normalize(query.strip())
    if not needle:
        return True
    return any(needle in normalize(value) for value in (row.name, row.description, row.projet_label))


class ProjectsPage(QWidget):
    """Page « Projets QGIS » (voir la docstring du module). *on_open* : ferme
    la fenetre, appele avant l'ouverture."""

    def __init__(self, actions: HomeActions, snapshot, state, on_open: Callable[[], None], parent=None):
        super().__init__(parent)
        self._actions = actions
        self._snapshot = snapshot
        self._state = state
        self._qgis = getattr(actions, "qgis", None)
        self._labels = dict(snapshot.labels or {})
        self._operator_labels = dict(snapshot.operator_code_labels or ())
        self._on_open = on_open
        self._capabilities = snapshot.capabilities
        self._projects: list = []        # projets de reference (dicts 2.0)
        self._rows: list = []            # QgisProjectRow
        self._entries: list = []         # donnees des elements de l'arbre (index en UserRole)
        self._entry_items: list = []     # elements porteurs d'une donnee, dans l'ordre de l'arbre
        self._unreadable = False

        if not snapshot.connected or state.qgis_reason == QGIS_OFFLINE:
            self._mode = MODE_OFFLINE
        elif self._qgis is not None and state.qgis_reason == "":
            self._mode = MODE_QGIS
        elif self._qgis is not None and state.qgis_reason == QGIS_NOMINATIVE:
            self._mode = MODE_NOMINATIVE
        else:
            self._mode = MODE_LEGACY

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        title = QLabel(tr("home.projects_title"))
        title.setStyleSheet("font-weight: bold;")
        header.addWidget(title)
        header.addStretch()
        self._save_button = QPushButton(tr("qgis.save_current"))
        self._save_button.clicked.connect(lambda _checked=False: self._save_current())
        header.addWidget(self._save_button)
        layout.addLayout(header)

        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("home.projects_search"))
        self._search.setClearButtonEnabled(True)
        layout.addWidget(self._search)

        self._notice = QLabel("")        # login partage : explication permanente
        self._notice.setWordWrap(True)
        set_role(self._notice, "muted")
        layout.addWidget(self._notice)

        self._message = QLabel("")
        self._message.setWordWrap(True)
        self._message.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._message)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3 if self._mode in (MODE_QGIS, MODE_NOMINATIVE) else 2)
        self._tree.setHeaderHidden(True)
        layout.addWidget(self._tree)

        self._feedback = QLabel("")      # resultat d'un enregistrement, partage, suppression
        self._feedback.setWordWrap(True)
        layout.addWidget(self._feedback)

        buttons = QHBoxLayout()
        self._share_button = QPushButton(tr("qgis.share"))
        self._delete_button = QPushButton(tr("qgis.delete"))
        self._open_button = QPushButton(tr("home.projects_open"))
        set_role(self._open_button, "primary")      # bouton principal de la page (feuille de style)
        buttons.addWidget(self._share_button)
        buttons.addWidget(self._delete_button)
        buttons.addStretch()
        buttons.addWidget(self._open_button)
        layout.addLayout(buttons)

        self._search.textChanged.connect(lambda _text="": self._refresh())
        self._tree.currentItemChanged.connect(lambda *_args: self._update_buttons())
        self._tree.itemDoubleClicked.connect(lambda *_args: self._open_selected())
        self._open_button.clicked.connect(lambda _checked=False: self._open_selected())
        self._share_button.clicked.connect(lambda _checked=False: self._share_selected())
        self._delete_button.clicked.connect(lambda _checked=False: self._delete_selected())

        self._setup_write_buttons()
        if self._mode != MODE_OFFLINE:
            self._load()
        self._refresh()

    # -- donnees -----------------------------------------------------------------------------

    def _setup_write_buttons(self) -> None:
        caps = self._capabilities
        personal = self._mode in (MODE_QGIS, MODE_NOMINATIVE)
        self._save_button.setVisible(personal and bool(caps.save))
        self._share_button.setVisible(self._mode == MODE_QGIS and bool(caps.share))
        self._delete_button.setVisible(self._mode == MODE_QGIS and bool(caps.delete))
        if self._mode == MODE_NOMINATIVE:
            self._save_button.setEnabled(False)
            self._save_button.setToolTip(tr("qgis.nominative_required"))
            self._notice.setText(tr("qgis.nominative_required"))
        self._notice.setVisible(self._mode == MODE_NOMINATIVE)

    def _load(self) -> None:
        """Relit les listes (une requete par liste) : projets de reference, et
        projets QGIS en mode 2.1 seulement."""
        projects = self._actions.list_projects()
        rows = self._qgis.list_visible() if self._mode == MODE_QGIS else []
        # None : liste illisible, journalisee par le plugin ; la page le dit.
        self._unreadable = projects is None or rows is None
        self._projects = list(projects or [])
        if self._mode in (MODE_QGIS, MODE_NOMINATIVE):
            # Les projets QGIS du schema `projet` viennent de list_visible.
            self._projects = [p for p in self._projects if p.get("schema") != PROJET_SCHEMA]
        self._rows = list(rows or [])

    # -- affichage ---------------------------------------------------------------------------

    def _group_label(self, schema: str) -> str:
        if schema == COMMON_SCHEMA:
            return tr("home.projects_common")
        if schema == PROJET_SCHEMA:
            return tr("qgis.legacy_projet_group")
        return self._labels.get(schema, schema)

    def _add_item(self, parent, texts, entry=None):
        item = QTreeWidgetItem(parent, list(texts))
        if entry is not None:
            item.setData(0, Qt.ItemDataRole.UserRole, len(self._entries))
            self._entries.append(entry)
            self._entry_items.append(item)
        return item

    def _refresh(self, select: Optional[str] = None) -> None:
        """Reconstruit l'arbre selon le mode, filtre par la recherche ;
        *select* : nom du projet a reselectionner."""
        self._tree.clear()
        self._entries = []
        self._entry_items = []
        if self._mode == MODE_OFFLINE:
            self._show_message(tr("home.projects_offline"))
            self._search.setEnabled(False)
            self._update_buttons()
            return
        if self._unreadable:
            self._show_message(tr("home.projects_error"))
            self._update_buttons()
            return
        if self._mode == MODE_LEGACY:
            shown = self._fill_legacy()
        else:
            shown = self._fill_sections()
        self._show_message("" if shown else tr("project.none_found"))
        if select:
            self._select_name(select)
        self._update_buttons()

    def _fill_legacy(self) -> int:
        groups: dict = {}
        shown = 0
        query = self._search.text()
        for project in self._projects:
            if not matches(project, query):
                continue
            schema = project.get("schema", "")
            group = groups.get(schema)
            if group is None:
                group = self._add_item(self._tree, [self._group_label(schema)])
                groups[schema] = group
            item = self._add_item(group, [project.get("name") or "", project.get("description") or ""],
                                  ("ref", schema, project.get("name")))
            if project.get("updated"):
                item.setToolTip(0, str(project["updated"]))
            shown += 1
        for group in groups.values():
            group.setExpanded(True)
        return shown

    def _fill_sections(self) -> int:
        query = self._search.text()
        operators = {p.code: p.operateur_code for p in (self._snapshot.projets or ())}
        rows = [r for r in self._rows if row_matches(r, query)]
        sections = build_sections(rows, operators)
        refs = [p for p in self._projects if matches(p, query)]
        shown = 0
        if self._mode == MODE_QGIS:
            mine = self._add_item(self._tree, [tr("qgis.section_mine", count=len(sections.mine))])
            for row in sections.mine:
                self._add_row(mine, row, self._mine_detail(row))
            shared = self._add_item(self._tree, [tr("qgis.section_shared", count=len(sections.shared))])
            for row in sections.shared:
                self._add_row(shared, row, self._shared_detail(row))
            mine.setExpanded(True)
            shared.setExpanded(True)
            shown += len(sections.mine) + len(sections.shared)
        published_count = sum(len(group_rows) for _c, _o, group_rows in sections.published) + len(refs)
        published = self._add_item(self._tree, [tr("qgis.section_published", count=published_count)])
        published.setExpanded(True)
        for code, operator, group_rows in sections.published:
            if code:
                label = group_rows[0].projet_label or code
            else:
                label = tr("qgis.published_unattached")
            if operator:
                label = f"{label} · {self._operator_labels.get(operator, operator)}"
            group = self._add_item(published, [label])
            group.setExpanded(True)
            for row in group_rows:
                self._add_row(group, row, self._shared_detail(row))
        groups: dict = {}
        for project in refs:
            schema = project.get("schema", "")
            group = groups.get(schema)
            if group is None:
                group = self._add_item(published, [self._group_label(schema)])
                group.setExpanded(True)
                groups[schema] = group
            item = self._add_item(group, [project.get("name") or "", "", project.get("description") or ""],
                                  ("ref", schema, project.get("name")))
            if project.get("updated"):
                item.setToolTip(0, str(project["updated"]))
        return shown + published_count

    def _add_row(self, parent, row, detail: str):
        item = self._add_item(parent, [row.name, row.projet_label or "", detail], ("qgis", row))
        if row.description:
            item.setToolTip(0, row.description)
        return item

    def _mine_detail(self, row) -> str:
        badges = []
        if row.share_count:
            badges.append(tr("qgis.badge_shared", count=row.share_count))
        if row.share_project:
            badges.append(tr("qgis.badge_projet", projet=row.projet_label or row.projet_code or ""))
        if row.published:
            badges.append(tr("qgis.badge_published"))
        if not badges:
            badges.append(tr("qgis.badge_private"))
        return " · ".join(badges)

    def _shared_detail(self, row) -> str:
        right = tr("qgis.can_edit") if row.can_edit else tr("qgis.can_open")
        return f"{tr('qgis.from_owner', owner=row.owner or '?')} · {right}"

    def _show_message(self, text: str) -> None:
        self._message.setText(text)
        self._message.setVisible(bool(text))
        self._tree.setVisible(not text)

    # -- selection ----------------------------------------------------------------------------

    def _select_name(self, name: str) -> None:
        for item, entry in zip(self._entry_items, self._entries):
            if entry[0] == "qgis" and entry[1].name == name:
                self._tree.setCurrentItem(item)
                return

    def _entry_of(self, item):
        if item is None:
            return None
        index = item.data(0, Qt.ItemDataRole.UserRole)
        if index is None or not isinstance(index, int) or index >= len(self._entries):
            return None
        return self._entries[index]

    def _selected(self):
        """("qgis", row) ou ("ref", schema, nom) ; ``None`` si rien ou un groupe."""
        return self._entry_of(self._tree.currentItem())

    def _selected_own_row(self):
        entry = self._selected()
        if entry is not None and entry[0] == "qgis" and entry[1].is_owner:
            return entry[1]
        return None

    def _update_buttons(self) -> None:
        self._open_button.setEnabled(self._selected() is not None)
        own = self._selected_own_row() is not None
        self._share_button.setEnabled(own)
        self._delete_button.setEnabled(own)

    # -- actions ------------------------------------------------------------------------------

    def _open_selected(self) -> None:
        entry = self._selected()
        if entry is None:
            return
        if entry[0] == "qgis":
            open_row = self._qgis.open
            self._on_open()          # la fenetre se ferme d'abord (D11)
            open_row(entry[1])
            return
        open_project = self._actions.open_project
        self._on_open()
        open_project(entry[1], entry[2])

    def _reload(self, select: Optional[str] = None) -> None:
        self._load()
        self._refresh(select)

    def _opened(self):
        getter = getattr(self._qgis, "opened", None)
        return getter() if callable(getter) else self._snapshot.opened_qgis_project

    def _save_current(self) -> None:
        if self._mode != MODE_QGIS or self._qgis is None:
            return
        from .bridge_qgis_dialogs import ConflictDialog, SaveDialog, run_save_flow

        qgis = self._qgis
        state = qgis.current_state()

        def make_dialog():
            return SaveDialog(self._snapshot.projets, self._opened(), state, self._capabilities,
                              qgis.eligible_users, self)

        outcome = run_save_flow(make_dialog, lambda name, creating, detail: ConflictDialog(name, creating, detail, self),
                                qgis, state.login)
        if outcome is None:
            return
        opened = self._opened()
        name = opened.name if opened is not None else ""
        self._feedback.setText(self.save_feedback(outcome, name))
        self._reload(name)

    @staticmethod
    def save_feedback(outcome, name: str) -> str:
        """Message apres un enregistrement reussi (partage refuse compris)."""
        text = tr("save.done", name=name, version=outcome.value)
        if outcome.message == "ineligible":
            text = tr("save.share_refused", count=outcome.count or 0)
        elif outcome.message:
            text += "\n" + tr("save.share_failed", message=outcome.detail or outcome.message)
        return text

    def _share_selected(self) -> None:
        row = self._selected_own_row()
        if row is None:
            return
        from .bridge_qgis_dialogs import ShareDialog

        dialog = ShareDialog(row, self._qgis, self._capabilities, self)
        dialog.exec()
        self._feedback.setText(dialog.done_message or "")
        self._reload(row.name)

    def _delete_selected(self, ask=None) -> None:
        row = self._selected_own_row()
        if row is None:
            return
        from .bridge_qgis_dialogs import confirm_delete, delete_message

        if not confirm_delete(self, row.name, ask):
            return
        names = [entry[1].name for entry in self._entries if entry[0] == "qgis"]
        index = names.index(row.name) if row.name in names else -1
        outcome = self._qgis.delete(row.name)
        self._feedback.setText(delete_message(outcome))
        self._reload()
        remaining = [entry[1].name for entry in self._entries if entry[0] == "qgis"]
        if remaining:
            # La selection passe au projet suivant (ou au dernier).
            follower = next((n for n in names[index + 1:] if n in remaining), remaining[-1])
            self._select_name(follower)
            self._update_buttons()
