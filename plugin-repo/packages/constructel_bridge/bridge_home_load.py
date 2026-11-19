# -*- coding: utf-8 -*-
"""
Constructel Bridge - page « Charger les couches » de l'accueil 2.0 (plan
2026-11-18 tache 5, spec § 6.2, § 6.3, § 7).

De haut en bas : « Deja dans le projet » (texte 1.9, ``summary_text``), le
message d'etat, le perimetre (un bouton par operateur, multiple, et « Aucun —
couches communes »), les presets (tuiles et arbre du LayerSelectionWidget,
menu « Mes presets »), la ligne « Options » repliee (fonds de plan, styles,
suffixe) et le pied (resume + « Charger »).

Toute la logique d'etat vient de bridge_home_model ; la page ne fait que
dessiner et relayer vers HomeActions. ``on_done(True)`` apres un chargement
qui a ajoute quelque chose (la fenetre se ferme), ``on_done(False)`` sinon
(la fenetre se redessine). Rien n'est memorise sur le poste tant qu'un
chargement n'a rien ajoute : le dernier choix (LAST_SELECTION_KEY, preset
reserve LAST_SELECTION_NAME) et le suffixe (§ 9.5) ne le sont qu'apres un
chargement reussi.
"""

from __future__ import annotations

from typing import Callable, Optional

from qgis.core import QgsSettings
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .bridge_home_model import (
    MESSAGE_COMMON_ONLY,
    MESSAGE_CONNECT,
    HomeActions,
    HomeSnapshot,
    HomeState,
    select_none,
    suffix_state,
    toggle_operator,
)
from .bridge_layer_selection import LayerSelectionWidget, step_number_label, step_title_label
from .bridge_operators import SUFFIX_SETTINGS_KEY
from .bridge_presets import (
    LAST_SELECTION_KEY,
    LAST_SELECTION_NAME,
    LayerSelection,
    UserPreset,
    presets_to_json,
    restrict_preset,
)
from .i18n import tr

SEPARATOR = " · "

# K11 : un appel tr LITTERAL par cle de message (releve par les tests i18n).
_MESSAGES = {
    MESSAGE_CONNECT: lambda: tr("home.connect_to_see"),
    MESSAGE_COMMON_ONLY: lambda: tr("home.common_only"),
}

# R11 : premiere utilisation avec un operateur preselectionne.
_FIRST_USE_TILES = ("zones", "genie_civil", "cables", "demand_points")
_ARROW_FOLDED = "▸"
_ARROW_OPEN = "▾"


def summary_text(snapshot: HomeSnapshot, state: HomeState) -> str:
    """« ✓ Wyre · 14 couches · 3 fonds de plan » : chaque operateur charge,
    les couches communes, les fonds de plan ; jamais le modele (D11)."""
    parts = [tr("home.loaded_operator", operator=label, count=count) for label, count in state.summary]
    if snapshot.counts.common:
        parts.append(tr("home.loaded_common", count=snapshot.counts.common))
    if snapshot.counts.basemaps:
        parts.append(tr("home.loaded_basemaps", count=snapshot.counts.basemaps))
    return SEPARATOR.join(parts)


class LoadPage(QWidget):
    """Page « Charger les couches ». *on_done(loaded)* : voir la docstring du
    module."""

    def __init__(self, snapshot: HomeSnapshot, state: HomeState, actions: HomeActions,
                 on_done: Callable[[bool], None], parent=None, options: Optional[dict] = None):
        super().__init__(parent)
        self._snapshot = snapshot
        self._state = state
        self._actions = actions
        self._on_done = on_done
        self._order = [op.schema for op in state.operators]      # ordre des operateurs utilisables
        self._by_schema = {op.schema: op for op in state.operators}
        self._chosen: tuple = tuple(state.preselected)
        self._user_presets = [p for p in snapshot.user_presets if p.name != LAST_SELECTION_NAME]
        self._suffix_proposed = False
        # Case du suffixe cochee ou decochee a la main : gardee tant qu'elle
        # reste modifiable (None : jamais touchee, la valeur proposee s'applique).
        self._suffix_manual: Optional[bool] = None
        self._operator_buttons: dict = {}
        self._build_ui()
        if options and state.load_enabled:
            self._suffix_manual = options.get("suffix")
        self._apply_initial_choice()
        if options and state.load_enabled:
            self._apply_options(options)
        self._selection.on_change = self._refresh_count
        self._refresh_count()

    # -- construction ------------------------------------------------------------------

    def _build_ui(self) -> None:
        state, snapshot = self._state, self._snapshot
        layout = QVBoxLayout(self)

        # -- Deja dans le projet ---------------------------------------------------------
        self._summary_label = None
        summary = summary_text(snapshot, state)
        if summary:
            row = QHBoxLayout()
            row.addWidget(QLabel(tr("home.loaded_title")))
            self._summary_label = QLabel(summary)
            row.addWidget(self._summary_label)
            row.addStretch()
            layout.addLayout(row)

        self._message_label = None
        if state.message_key:
            self._message_label = QLabel(_MESSAGES[state.message_key]())
            self._message_label.setWordWrap(True)
            layout.addWidget(self._message_label)

        # -- Etape 1 : perimetre ------------------------------------------------------------
        step_one = QHBoxLayout()
        step_one.addWidget(step_number_label("1"))
        step_one.addWidget(step_title_label(tr("home.step_perimeter")))
        step_one.addStretch()
        layout.addLayout(step_one)
        perimeter = QHBoxLayout()
        for op in state.operators:
            caption = f"{op.label} ✓" if op.schema in state.loaded_marks else op.label
            button = QPushButton(caption)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, schema=op.schema: self._on_operator_clicked(schema))
            perimeter.addWidget(button)
            self._operator_buttons[op.schema] = button
        self._none_button = QPushButton(tr("home.none_operator"))
        self._none_button.setCheckable(True)
        self._none_button.clicked.connect(lambda _checked=False: self._on_none_clicked())
        perimeter.addWidget(self._none_button)
        perimeter.addStretch()
        layout.addLayout(perimeter)

        # -- Etape 2 : presets (menu) puis tuiles et arbre du widget ---------------------------
        header = QHBoxLayout()
        header.addWidget(step_number_label("2"))
        header.addWidget(step_title_label(tr("home.step_presets")))
        header.addStretch()
        self._presets_button = QToolButton()
        self._presets_button.setText(f"{tr('home.my_presets')} ▾")
        self._presets_menu = QMenu(self)
        self._presets_button.setMenu(self._presets_menu)
        self._presets_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        header.addWidget(self._presets_button)
        layout.addLayout(header)
        self._fill_presets_menu()

        self._selection = LayerSelectionWidget(self)
        layout.addWidget(self._selection)

        # -- Options (repliees) : fonds de plan, styles, suffixe ---------------------------------
        self._options_toggle = QToolButton()
        self._options_toggle.setCheckable(True)
        self._options_toggle.setText(f"{_ARROW_FOLDED} {tr('home.options')}")
        self._options_toggle.toggled.connect(self._on_options_toggled)
        layout.addWidget(self._options_toggle)
        self._options_body = QWidget()
        body = QVBoxLayout(self._options_body)
        body.addWidget(self._selection.options_panel())
        self._suffix_box = QCheckBox(tr("home.suffix_checkbox"))
        self._suffix_box.clicked.connect(lambda _checked=False: self._on_suffix_clicked())
        body.addWidget(self._suffix_box)
        self._options_body.setVisible(False)
        layout.addWidget(self._options_body)

        # -- Pied : resume et bouton ------------------------------------------------------------
        footer = QHBoxLayout()
        self._count_label = QLabel("")
        footer.addWidget(self._count_label)
        footer.addStretch()
        self._load_button = QPushButton(tr("home.btn_load"))
        self._load_button.clicked.connect(lambda _checked=False: self._on_load())
        footer.addWidget(self._load_button)
        layout.addLayout(footer)

        if not state.load_enabled:        # hors connexion : le message dit pourquoi
            for widget in (self._none_button, self._presets_button, self._options_toggle,
                           self._selection, self._load_button):
                widget.setEnabled(False)

    def _fill_presets_menu(self) -> None:
        menu = self._presets_menu
        menu.clear()
        for preset in self._user_presets:
            action = menu.addAction(preset.name)
            action.triggered.connect(lambda _checked=False, p=preset: self._choose_preset(p))
        if self._user_presets:
            menu.addSeparator()
        save = menu.addAction(tr("home.save_preset"))
        save.triggered.connect(lambda _checked=False: self._save_preset())

    def _apply_initial_choice(self) -> None:
        """Perimetre de ``state.preselected`` ; selection du dernier choix, ou
        (premiere utilisation, R11) les tuiles par operateur usuelles."""
        self._sync_perimeter()
        if not self._state.load_enabled:
            return
        last = self._snapshot.last_selection
        if last is None or (not last.name and last.selection.is_empty()):
            if self._chosen:
                self._selection.set_tiles(_FIRST_USE_TILES)
        else:
            self._selection.apply_selection(self._restricted(last)[1])

    # -- perimetre ----------------------------------------------------------------------

    def _chosen_operators(self) -> tuple:
        return tuple(self._by_schema[schema] for schema in self._chosen)

    def _sync_perimeter(self) -> None:
        """Boutons, widget de selection, case du suffixe : alignes sur
        ``self._chosen``."""
        for schema, button in self._operator_buttons.items():
            button.setChecked(schema in self._chosen)
        self._none_button.setChecked(not self._chosen)
        self._selection.set_operators(self._chosen_operators())
        self._refresh_suffix()

    def _set_chosen(self, chosen) -> None:
        self._chosen = tuple(chosen)
        self._sync_perimeter()

    def _on_operator_clicked(self, schema: str) -> None:
        self._set_chosen(toggle_operator(self._chosen, schema, self._order))

    def _on_none_clicked(self) -> None:
        self._set_chosen(select_none())

    def _refresh_suffix(self) -> None:
        """Case du suffixe (§ 6.4) : seule masquee sans operateur ; les fonds
        de plan et les styles restent offerts."""
        has_operator = bool(self._chosen)
        self._suffix_box.setVisible(has_operator)
        if not has_operator:
            return
        loaded = list(self._snapshot.project_operators) + list(self._snapshot.counts.per_operator)
        checked, editable = suffix_state(loaded, self._chosen, self._snapshot.project_suffix,
                                         self._snapshot.last_suffix)
        self._suffix_proposed = checked
        if not editable:
            self._suffix_manual = None        # impose : le choix manuel ne survit pas
        elif self._suffix_manual is not None:
            checked = self._suffix_manual
        self._suffix_box.setChecked(checked)
        self._suffix_box.setEnabled(editable)

    def _on_suffix_clicked(self) -> None:
        self._suffix_manual = self._suffix_box.isChecked()

    # -- presets ------------------------------------------------------------------------

    def _restricted(self, preset: UserPreset) -> tuple:
        """(operateurs, selection) de *preset* limites aux operateurs
        utilisables ET a ceux qu'il nomme : jamais les couches d'un operateur
        qu'il ne cite pas."""
        restricted = restrict_preset(preset, self._order)
        named = set(restricted.schemas)
        selection = LayerSelection({s: keys for s, keys in restricted.selection.per_operator.items() if s in named},
                                   restricted.selection.common)
        return tuple(s for s in self._order if s in named), selection

    def _choose_preset(self, preset: UserPreset) -> None:
        schemas, selection = self._restricted(preset)
        self._set_chosen(schemas)
        self._selection.apply_selection(selection)

    def current_choice(self) -> UserPreset:
        """Perimetre et selection affiches, sans nom."""
        return UserPreset("", self._chosen, self._selection.selection())

    def current_options(self) -> dict:
        """Options affichees, gardees par la fenetre d'un redessin a l'autre
        comme ``current_choice`` : fonds de plan coches, styles, et la case du
        suffixe si elle a ete changee a la main (None sinon)."""
        return {
            "basemaps": set(self._selection.selected_basemaps()),
            "styles": self._selection.want_styles(),
            "suffix": self._suffix_manual,
        }

    def _apply_options(self, options: dict) -> None:
        if "basemaps" in options:
            self._selection.set_basemaps(options["basemaps"])
        if "styles" in options:
            self._selection.set_want_styles(options["styles"])

    def default_button(self) -> QPushButton:
        """« Charger » : bouton par defaut de la fenetre quand la page est
        affichee (Entree dans l'arbre charge)."""
        return self._load_button

    def _save_preset(self) -> None:
        name, accepted = QInputDialog.getText(self, tr("home.my_presets"), tr("home.save_preset_prompt"))
        name = (name or "").strip()
        if not accepted or not name or name == LAST_SELECTION_NAME:
            return
        choice = self.current_choice()
        preset = UserPreset(name, choice.schemas, choice.selection)
        presets = list(self._user_presets)
        for index, existing in enumerate(presets):
            if existing.name == name:          # meme nom : remplace
                presets[index] = preset
                break
        else:
            presets.append(preset)
        self._user_presets = presets
        self._actions.save_presets(list(presets))
        self._fill_presets_menu()

    # -- options, resume, chargement --------------------------------------------------------

    def _on_options_toggled(self, checked: bool) -> None:
        self._options_body.setVisible(bool(checked))
        arrow = _ARROW_OPEN if checked else _ARROW_FOLDED
        self._options_toggle.setText(f"{arrow} {tr('home.options')}")

    def _refresh_count(self) -> None:
        """Ce que « Charger » va ajouter : couches et fonds de plan choisis."""
        self._count_label.setText(tr("home.load_summary", layers=self._selection.selection().layer_count(),
                                     basemaps=len(self._selection.selected_basemaps())))

    def _on_load(self) -> None:
        operators = self._chosen_operators()
        selection = self._selection.selection()
        has_operator = bool(operators)
        suffix: Optional[bool] = self._suffix_box.isChecked() if has_operator else None
        editable = has_operator and self._suffix_box.isEnabled()
        count = self._actions.load(operators, selection, self._selection.selected_basemaps(),
                                   self._selection.want_styles(), suffix)
        if count > 0:
            self._remember(selection, suffix, editable)
        self._on_done(count > 0)

    def _remember(self, selection: LayerSelection, suffix: Optional[bool], editable: bool) -> None:
        """Memorise sur le poste, apres un chargement qui a ajoute quelque
        chose : le dernier choix (R8) et, si la personne a change une case
        modifiable, le suffixe (jamais la valeur imposee ou venue du projet)."""
        settings = QgsSettings()
        last = UserPreset(LAST_SELECTION_NAME, self._chosen, selection)
        settings.setValue(LAST_SELECTION_KEY, presets_to_json([last]))
        if editable and suffix != self._suffix_proposed:
            settings.setValue(SUFFIX_SETTINGS_KEY, suffix)
