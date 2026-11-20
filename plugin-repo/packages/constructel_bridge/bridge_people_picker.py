"""Selecteur de personnes avec autocompletion (Bridge 2.1, spec § 7.9),
pour l'enregistrement et le partage d'un projet QGIS.

Recherche lancee DEBOUNCE_MS apres la derniere frappe, a partir de 3
caracteres, par la fonction *search(prefixe, exclus)* fournie par l'appelant
(`projet.fn_qgis_project_eligible_users`, seule source des personnes : le
Bridge ne lit jamais `ref.users`). Propositions « Nom (login) — unite » dans un
QCompleter sans filtrage Qt ; une proposition choisie rejoint la liste « A
ajouter » (droit « peut ouvrir » par defaut, modifiable, bouton Retirer).
20 personnes au plus.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

from qgis.PyQt.QtCore import QStringListModel, QTimer
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QCompleter,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .bridge_home_style import set_role
from .bridge_qgis_projects import ELIGIBLE_MIN_PREFIX, MAX_SHARE_LOGINS, EligibleUser
from .i18n import tr

DEBOUNCE_MS = 300


class PeoplePicker(QWidget):
    """Champ d'autocompletion et liste « A ajouter » (voir le module)."""

    def __init__(self, search: Callable[[str, Sequence[str]], Optional[list]], parent=None,
                 excluded: Sequence[str] = ()):
        super().__init__(parent)
        self._search = search
        self._excluded: Tuple[str, ...] = tuple(excluded)
        self._chosen: List[Tuple[EligibleUser, bool]] = []
        self._proposals: List[EligibleUser] = []
        self.on_change: Optional[Callable[[], None]] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.input = QLineEdit()
        self.input.setPlaceholderText(tr("people.placeholder"))
        self._model = QStringListModel(self)
        self.completer = QCompleter(self._model, self)
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.input.setCompleter(self.completer)
        self.completer.activated.connect(self._on_activated)
        layout.addWidget(self.input)

        self.help = QLabel("")
        set_role(self.help, "muted")
        self.help.setWordWrap(True)
        layout.addWidget(self.help)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(DEBOUNCE_MS)
        self.timer.timeout.connect(self._run_search)
        self.input.textEdited.connect(lambda _text="": self.timer.start())

        self.list = QTreeWidget()
        self.list.setColumnCount(3)
        self.list.setHeaderHidden(True)
        self.list.setRootIsDecorated(False)
        layout.addWidget(self.list)
        self._refresh_list()

    # -- recherche -------------------------------------------------------------------------

    def _excluded_now(self) -> List[str]:
        chosen = [user.username for user, _edit in self._chosen]
        return list(dict.fromkeys([*self._excluded, *chosen]))

    def _run_search(self) -> None:
        prefix = (self.input.text() or "").strip()
        if len(prefix) < ELIGIBLE_MIN_PREFIX:
            self._proposals = []
            self._model.setStringList([])
            self.help.setText(tr("people.min_chars") if prefix else "")
            return
        found = self._search(prefix, self._excluded_now())
        if found is None:
            self._proposals = []
            self._model.setStringList([])
            self.help.setText(tr("people.search_error"))
            return
        taken = set(self._excluded_now())
        self._proposals = [user for user in found if user.username not in taken]
        self._model.setStringList([user.caption() for user in self._proposals])
        self.help.setText("")
        if self._proposals:
            self.completer.complete()

    def proposals(self) -> List[EligibleUser]:
        return list(self._proposals)

    def _on_activated(self, value) -> None:
        text = value if isinstance(value, str) else (value.data() if hasattr(value, "data") else str(value))
        for user in self._proposals:
            if user.caption() == text:
                self.choose(user)
                return

    # -- liste « A ajouter » -----------------------------------------------------------------

    def choose(self, user: EligibleUser) -> None:
        """Ajoute *user* (droit « peut ouvrir ») et vide le champ ; doublon
        ou maximum atteint : ignore."""
        self._clear_input()
        if any(existing.username == user.username for existing, _edit in self._chosen):
            return
        if len(self._chosen) >= MAX_SHARE_LOGINS:
            return
        self._chosen.append((user, False))
        self._refresh_list()
        self._notify()

    def _clear_input(self) -> None:
        self.input.clear()
        # Le QCompleter recopie la proposition dans le champ apres activated.
        QTimer.singleShot(0, self.input.clear)

    def chosen(self) -> tuple:
        return tuple((user.username, edit) for user, edit in self._chosen)

    def set_right(self, login: str, can_edit: bool) -> None:
        self._chosen = [(user, bool(can_edit) if user.username == login else edit) for user, edit in self._chosen]
        self._notify()

    def remove(self, login: str) -> None:
        self._chosen = [(user, edit) for user, edit in self._chosen if user.username != login]
        self._refresh_list()
        self._notify()

    def clear(self) -> None:
        self._chosen = []
        self._proposals = []
        self._model.setStringList([])
        self.input.clear()
        self.help.setText("")
        self._refresh_list()
        self._notify()

    def set_excluded(self, logins: Sequence[str]) -> None:
        self._excluded = tuple(logins)

    def _notify(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def _refresh_list(self) -> None:
        """Lignes « A ajouter » reconstruites ; champ desactive a 20 personnes."""
        self.list.clear()
        for user, edit in self._chosen:
            item = QTreeWidgetItem(self.list, [user.caption()])
            combo = QComboBox()
            combo.addItem(tr("people.right_open"), False)
            combo.addItem(tr("people.right_edit"), True)
            combo.setCurrentIndex(1 if edit else 0)
            combo.currentIndexChanged.connect(
                lambda _index=0, login=user.username, box=combo: self.set_right(login, bool(box.currentData())))
            self.list.setItemWidget(item, 1, combo)
            button = QPushButton(tr("people.remove"))
            set_role(button, "link")
            button.clicked.connect(lambda _checked=False, login=user.username: self.remove(login))
            self.list.setItemWidget(item, 2, button)
        full = len(self._chosen) >= MAX_SHARE_LOGINS
        self.input.setEnabled(not full)
        if full:
            self.help.setText(tr("people.max_reached", count=MAX_SHARE_LOGINS))
        elif self.help.text() == tr("people.max_reached", count=MAX_SHARE_LOGINS):
            self.help.setText("")
        self.list.setVisible(bool(self._chosen))
