"""Dialogues des projets QGIS (Bridge 2.1, spec § 7.7 a § 7.11) :
« Enregistrer le projet courant… », conflit de version, « Partager… » et
confirmation de suppression.

Les dialogues recoivent la feuille de style de l'accueil (objet nomme
``bridgeHome``, couleurs de la palette QGIS, aucune couleur de fond codee en
dur) et une taille par defaut bornee a l'ecran disponible (1366x768 compris).
La logique (noms, cible d'un enregistrement, plan de partage) vient des
modules sans Qt ; les dialogues dessinent et relaient vers
``QgisProjectActions``.
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from .bridge_home_model import (
    VISIBILITY_PEOPLE,
    VISIBILITY_PRIVATE,
    VISIBILITY_PROJET,
    SaveRequest,
)
from .bridge_home_style import home_style_sheet, set_role
from .bridge_people_picker import PeoplePicker
from .bridge_project_safety import (
    FINDING_ACTION,
    FINDING_EXPRESSION_FUNCTIONS,
    FINDING_FORM_INIT,
    FINDING_MACROS,
    FINDING_PASSWORD,
    FINDING_PYTHON_FILE,
    Finding,
)
from .bridge_qgis_projects import name_error, save_target, suggest_name
from .bridge_qgis_store import (
    STATUS_CONFLICT,
    STATUS_GONE,
    STATUS_INVALID,
    STATUS_NAME_TAKEN,
    STATUS_NOMINATIVE,
    STATUS_OK,
    STATUS_PROJET_DENIED,
)
from .i18n import tr

DIALOG_SIZE = (560, 520)
_FRAME_MARGIN = (16, 48)

# K11 : un appel tr LITTERAL par cle.
_NAME_ERRORS = {
    "empty": lambda: tr("save.name_empty"),
    "too_long": lambda: tr("save.name_too_long"),
    "control": lambda: tr("save.name_control"),
    "spaces": lambda: tr("save.name_spaces"),
}
_FINDINGS = {
    FINDING_MACROS: lambda f: tr("save.finding_macros"),
    FINDING_EXPRESSION_FUNCTIONS: lambda f: tr("save.finding_expression_functions"),
    FINDING_ACTION: lambda f: tr("save.finding_action", detail=f.detail),
    FINDING_FORM_INIT: lambda f: tr("save.finding_form_init", detail=f.detail),
    FINDING_PASSWORD: lambda f: tr("save.finding_password"),
    FINDING_PYTHON_FILE: lambda f: tr("save.finding_python_file", detail=f.detail),
}


def _available_size(widget):
    """(largeur, hauteur) de l'ecran disponible, None si illisible (meme
    calcul que HomeDialog._available_size)."""
    screen = None
    try:
        screen = widget.screen()
    except Exception:  # noqa: BLE001 -- Qt < 5.14, doublures
        screen = None
    if screen is None:
        try:
            from qgis.PyQt.QtGui import QGuiApplication

            screen = QGuiApplication.primaryScreen()
        except Exception:  # noqa: BLE001
            screen = None
    if screen is None:
        return None
    try:
        geometry = screen.availableGeometry()
        width, height = int(geometry.width()), int(geometry.height())
    except Exception:  # noqa: BLE001
        return None
    return (width, height) if width > 0 and height > 0 else None


def fitted_size(widget, wanted=DIALOG_SIZE) -> tuple:
    available = _available_size(widget)
    if available is None:
        return tuple(wanted)
    room = tuple(max(1, side - margin) for side, margin in zip(available, _FRAME_MARGIN))
    return tuple(min(w, side) for w, side in zip(wanted, room))


def style_dialog(dialog, title: str) -> None:
    """Feuille de style de l'accueil, titre et taille bornee a l'ecran."""
    dialog.setObjectName("bridgeHome")
    dialog.setStyleSheet(home_style_sheet(dialog.palette()))
    dialog.setWindowTitle(title)
    dialog.resize(*fitted_size(dialog))


def format_finding(finding: Finding) -> str:
    """Constat du controle a l'enregistrement, lisible (« couche « Points » :
    action de type Python… »)."""
    text = _FINDINGS.get(finding.kind, lambda f: f.kind)(finding)
    if finding.layer:
        return tr("save.finding_layer", layer=finding.layer) + " " + text
    return text


def _accepted(code) -> bool:
    try:
        return int(code) == int(QDialog.DialogCode.Accepted)
    except Exception:  # noqa: BLE001 -- doublures
        return bool(code)


# =====================================================================
# Enregistrer le projet courant (spec § 7.7)
# =====================================================================

class SaveDialog(QDialog):
    """Nom, description, projet metier, visibilite (a la creation seulement)."""

    def __init__(self, projets: Sequence, opened, state, capabilities, search: Callable, parent=None):
        super().__init__(parent)
        self._projets = tuple(projets)
        self._opened = opened
        self._state = state
        self._capabilities = capabilities
        self._search = search
        self._visibility = VISIBILITY_PRIVATE
        style_dialog(self, tr("save.title"))

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("save.name")))
        self.name_edit = QLineEdit()
        layout.addWidget(self.name_edit)
        self.name_error_label = QLabel("")
        set_role(self.name_error_label, "muted")
        layout.addWidget(self.name_error_label)

        layout.addWidget(QLabel(tr("save.description")))
        self.description_edit = QLineEdit()
        layout.addWidget(self.description_edit)

        layout.addWidget(QLabel(tr("save.projet")))
        self.projet_combo = QComboBox()
        self.projet_combo.addItem(tr("save.projet_none"), None)
        for projet in self._projets:
            self.projet_combo.addItem(projet.label, projet)
        layout.addWidget(self.projet_combo)

        self.visibility_box = QGroupBox(tr("save.visibility"))
        box = QVBoxLayout(self.visibility_box)
        self.private_radio = QRadioButton(tr("save.private"))
        self.projet_radio = QRadioButton(tr("save.projet_members_any"))
        box.addWidget(self.private_radio)
        box.addWidget(self.projet_radio)
        self.people_radio = None
        self.picker = None
        if capabilities.share:
            self.people_radio = QRadioButton(tr("save.people"))
            box.addWidget(self.people_radio)
            self.picker = PeoplePicker(self._search_people, self)
            box.addWidget(self.picker)
        layout.addWidget(self.visibility_box)
        self.visibility_note = QLabel(tr("save.visibility_unchanged"))
        self.visibility_note.setWordWrap(True)
        set_role(self.visibility_note, "muted")
        layout.addWidget(self.visibility_note)

        self.outcome_label = QLabel("")
        self.outcome_label.setWordWrap(True)
        layout.addWidget(self.outcome_label)
        self.empty_label = QLabel(tr("save.empty_project"))
        set_role(self.empty_label, "muted")
        layout.addWidget(self.empty_label)
        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton(tr("save.cancel"))
        self.cancel_button.setAutoDefault(False)
        self.cancel_button.clicked.connect(lambda _checked=False: self.reject())
        buttons.addWidget(self.cancel_button)
        self.save_button = QPushButton(tr("save.button"))
        set_role(self.save_button, "primary")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(lambda _checked=False: self._on_save())
        buttons.addWidget(self.save_button)
        layout.addLayout(buttons)

        self._prefill()
        self.private_radio.toggled.connect(lambda on: on and self._set_visibility(VISIBILITY_PRIVATE))
        self.projet_radio.toggled.connect(lambda on: on and self._set_visibility(VISIBILITY_PROJET))
        if self.people_radio is not None:
            self.people_radio.toggled.connect(lambda on: on and self._set_visibility(VISIBILITY_PEOPLE))
        self.projet_combo.currentIndexChanged.connect(lambda _index=0: self._on_projet_changed())
        self.name_edit.textChanged.connect(lambda _text="": self.refresh_mode())
        self._set_visibility(VISIBILITY_PRIVATE)
        self._on_projet_changed()
        self.refresh_mode()

    # -- pre-remplissage et modes ----------------------------------------------------------

    def _editable_opened(self) -> bool:
        opened = self._opened
        return opened is not None and bool(opened.can_edit or opened.is_owner)

    def _prefill(self) -> None:
        opened, state = self._opened, self._state
        if self._editable_opened():
            name = opened.name
        elif opened is not None:
            name = suggest_name(state.title or opened.name, state.login)
        else:
            name = state.title or ""
        self.name_edit.setText(name)
        if opened is not None:
            self.description_edit.setText(str((opened.metadata or {}).get("description") or ""))
        if self._editable_opened() and opened.projet_id:
            self._select_projet_id(opened.projet_id)

    def _select_projet_id(self, projet_id) -> None:
        for index, projet in enumerate(self._projets, start=1):
            if projet.id == projet_id:
                self.projet_combo.setCurrentIndex(index)
                return
        self.projet_combo.setCurrentIndex(0)

    def is_update(self) -> bool:
        expected, _locked = save_target(self.name_edit.text(), self._opened)
        return expected is not None

    def refresh_mode(self) -> None:
        """Nom du projet QGIS ouvert et modifiable : mise a jour (projet metier
        verrouille, visibilite masquee) ; sinon creation."""
        updating = self.is_update()
        if updating:
            blocked = self.projet_combo.blockSignals(True)
            try:
                if self._opened.projet_id:
                    self._select_projet_id(self._opened.projet_id)
                else:
                    self.projet_combo.setCurrentIndex(0)
            finally:
                self.projet_combo.blockSignals(blocked)
        self.projet_combo.setEnabled(not updating)
        self.visibility_box.setVisible(not updating)
        self.visibility_note.setVisible(updating)
        self._validate()

    def selected_projet(self):
        return self.projet_combo.currentData()

    def _on_projet_changed(self) -> None:
        projet = self.selected_projet()
        if self.picker is not None:
            self.picker.clear()       # les eligibles changent avec le projet metier
        allowed = projet is not None and bool(self._capabilities.share_project)
        self.projet_radio.setText(tr("save.projet_members", projet=projet.label) if projet is not None
                                  else tr("save.projet_members_any"))
        self.projet_radio.setEnabled(allowed)
        if not allowed and self._visibility == VISIBILITY_PROJET:
            self._set_visibility(VISIBILITY_PRIVATE)

    def _set_visibility(self, value: str) -> None:
        self._visibility = value
        radios = ((self.private_radio, VISIBILITY_PRIVATE), (self.projet_radio, VISIBILITY_PROJET),
                  (self.people_radio, VISIBILITY_PEOPLE))
        for radio, kind in radios:
            if radio is None:
                continue
            blocked = radio.blockSignals(True)
            try:
                radio.setChecked(kind == value)
            finally:
                radio.blockSignals(blocked)
        if self.picker is not None:
            self.picker.setVisible(value == VISIBILITY_PEOPLE)

    def visibility(self) -> str:
        return VISIBILITY_PRIVATE if self.is_update() else self._visibility

    def _search_people(self, prefix: str, exclude: Sequence[str]):
        projet = self.selected_projet()
        return self._search(projet.code if projet is not None else None, prefix, exclude)

    def _validate(self) -> None:
        error = name_error(self.name_edit.text())
        self.name_error_label.setText(_NAME_ERRORS[error]() if error else "")
        empty = self._state.layer_count == 0
        self.empty_label.setVisible(empty)
        self.save_button.setEnabled(error is None and not empty)

    # -- resultat ---------------------------------------------------------------------------

    def request(self) -> SaveRequest:
        projet = self.selected_projet()
        visibility = self.visibility()
        people = self.picker.chosen() if (self.picker is not None and visibility == VISIBILITY_PEOPLE) else ()
        return SaveRequest(
            name=self.name_edit.text(),
            description=self.description_edit.text().strip(),
            projet_id=projet.id if projet is not None else None,
            projet_code=projet.code if projet is not None else None,
            visibility=visibility,
            people=tuple(people),
        )

    def _on_save(self) -> None:
        if self.save_button.isEnabled():
            self.accept()

    def suggest_rename(self, login: str) -> None:
        self.name_edit.setText(suggest_name(self.name_edit.text(), login))

    def show_outcome(self, outcome, login: str) -> None:
        """Refus d'un enregistrement : message dedie ; le dialogue reste
        ouvert (nom remplace par une suggestion si le nom est en cause)."""
        status = outcome.status
        if status == STATUS_NAME_TAKEN:
            text = tr("save.name_taken")
            self.suggest_rename(login)
        elif status == STATUS_GONE:
            text = tr("save.gone")
            self.suggest_rename(login)
        elif status == "unsafe":
            lines = [tr("save.unsafe_intro")] + ["• " + format_finding(f) for f in (outcome.value or ())]
            text = "\n".join(lines)
        elif status == STATUS_NOMINATIVE:
            text = tr("save.nominative")
        elif status == STATUS_PROJET_DENIED:
            text = tr("save.projet_denied")
        elif status == STATUS_INVALID:
            text = tr("save.invalid", message=outcome.message or "")
        elif status == "too_large":
            text = tr("save.too_large")
        elif status == "empty":
            text = tr("save.empty_project")
        else:
            text = tr("save.error", message=outcome.message or "")
        self.outcome_label.setText(text)


# =====================================================================
# Conflit de version (spec § 7.10)
# =====================================================================

CHOICE_RENAME = "rename"
CHOICE_OVERWRITE = "overwrite"
CHOICE_CANCEL = "cancel"


class ConflictDialog(QDialog):
    """« Enregistrer sous un autre nom… » / « Ecraser » / « Annuler » (defaut)."""

    def __init__(self, name: str, creating: bool, detail: str, parent=None):
        super().__init__(parent)
        self._choice = CHOICE_CANCEL
        style_dialog(self, tr("conflict.title"))
        self.resize(*fitted_size(self, (520, 220)))
        layout = QVBoxLayout(self)
        text = tr("conflict.exists", name=name) if creating else tr("conflict.changed", name=name)
        self.message_label = QLabel(text + (f"\n{detail}" if detail else ""))
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)
        layout.addStretch()
        buttons = QHBoxLayout()
        self.rename_button = QPushButton(tr("conflict.rename"))
        self.overwrite_button = QPushButton(tr("conflict.overwrite"))
        self.cancel_button = QPushButton(tr("conflict.cancel"))
        for button, choice in ((self.rename_button, CHOICE_RENAME), (self.overwrite_button, CHOICE_OVERWRITE),
                               (self.cancel_button, CHOICE_CANCEL)):
            button.setAutoDefault(False)
            button.clicked.connect(lambda _checked=False, c=choice: self._choose(c))
            buttons.addWidget(button)
        self.cancel_button.setAutoDefault(True)
        self.cancel_button.setDefault(True)
        layout.addLayout(buttons)

    def _choose(self, choice: str) -> None:
        self._choice = choice
        if choice == CHOICE_CANCEL:
            self.reject()
        else:
            self.accept()

    def choice(self) -> str:
        return self._choice


def run_save_flow(dialog_factory, conflict_factory, actions, login: str):
    """Enregistrer -> conflit -> « autre nom » (retour au dialogue, nom
    suggere) / « ecraser » (``actions.overwrite`` ; nouveau conflit : le
    dialogue de conflit revient) / « annuler » (None). Un refus garde le
    dialogue ouvert (message, puis nouvelle saisie). Rend le resultat ``ok``
    ou None (annule)."""
    dialog = dialog_factory()
    while True:
        if not _accepted(dialog.exec()):
            return None
        request = dialog.request()
        creating = not dialog.is_update()
        outcome = actions.save(request)
        while outcome is not None and outcome.status == STATUS_CONFLICT:
            conflict = conflict_factory(request.name, creating, outcome.detail)
            conflict.exec()
            choice = conflict.choice()
            if choice == CHOICE_OVERWRITE:
                outcome = actions.overwrite(request)
            elif choice == CHOICE_RENAME:
                dialog.suggest_rename(login)
                outcome = None
            else:
                return None
        if outcome is None:
            continue
        if outcome.status == STATUS_OK:
            return outcome
        dialog.show_outcome(outcome, login)

