# -*- coding: utf-8 -*-
"""
Constructel Bridge - ecran d'accueil (1.9.0, plan 2026-11-12 tache 9, spec
§ 6.1, § 6.2, § 6.4, § 6.6, solution « B »).

En-tete : etat de connexion. Grande tuile « Charger les couches » : choix de
l'operateur (parmi les utilisables seulement), puis la selection actuelle
(LayerSelectionWidget : modele, arbre, fonds de plan, styles, Tout/Rien), la
case du suffixe et le bouton principal. Tuiles secondaires : Projet
enregistre, Check-in, Diagnostic, Langue.

Toute la logique d'etat vient de bridge_home_model ; ce module ne fait que
dessiner et relayer les clics vers HomeActions. render() reconstruit tout
depuis actions.snapshot() (apres une connexion, un check-in, un diagnostic
ou un changement de langue). L'ecran se ferme apres un chargement qui a
ajoute des couches, et avant d'ouvrir un projet enregistre (D11).
"""

from __future__ import annotations

from qgis.core import QgsSettings
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .bridge_home_model import (
    MODE_ADD,
    SELECTOR_BUTTONS,
    SELECTOR_LABEL,
    HomeActions,
    HomeSnapshot,
    HomeState,
    home_state,
    suffix_state,
)
from .bridge_operators import SUFFIX_SETTINGS_KEY, OperatorInfo
from .bridge_project_init import LayerSelectionWidget
from .i18n import tr

# K11 : un appel tr LITTERAL par cle de message (releve par test_bridge18_i18n).
_MESSAGES = {
    "home.connect_to_see": lambda: tr("home.connect_to_see"),
    "home.no_operator": lambda: tr("home.no_operator"),
}
_SEP = " · "
_CONNECTED_COLOR = "#2e7d32"
_OFFLINE_COLOR = "#9e9e9e"


def summary_text(snapshot: HomeSnapshot, state: HomeState) -> str:
    """« ✓ Wyre · 14 couches · 3 fonds de plan » : chaque operateur charge,
    les couches communes, les fonds de plan ; jamais le modele (D11)."""
    parts = [tr("home.loaded_operator", operator=label, count=count) for label, count in state.summary]
    if snapshot.counts.common:
        parts.append(tr("home.loaded_common", count=snapshot.counts.common))
    if snapshot.counts.basemaps:
        parts.append(tr("home.loaded_basemaps", count=snapshot.counts.basemaps))
    return _SEP.join(parts)


def checkin_subtitle(summary) -> str:
    """« extensions 5/6 · 1 a mettre a jour » ; "" si le resume est illisible."""
    if summary is None:
        return ""
    text = tr("home.tile_checkin_sub", active=summary.active, total=summary.total)
    if summary.updates:
        text = f"{text}{_SEP}{tr('home.tile_checkin_updates', count=summary.updates)}"
    return text


class HomeDialog(QDialog):
    """Ecran d'accueil. *actions* : HomeActions fournies par le plugin."""

    def __init__(self, actions: HomeActions, parent=None):
        super().__init__(parent)
        self.actions = actions
        self._selected_schema = ""   # choix de la personne, garde d'un redessin a l'autre
        self._body = None
        self.setWindowTitle("Constructel Bridge")
        self.setMinimumWidth(820)
        self._layout = QVBoxLayout(self)
        self.render()

    # -- construction -------------------------------------------------------------

    def render(self) -> None:
        """Reconstruit tout l'ecran depuis actions.snapshot()."""
        snapshot = self.actions.snapshot()
        state = home_state(snapshot)
        self._snapshot, self._state = snapshot, state
        self._operator = self._current_operator(snapshot, state)

        body = QWidget(self)
        layout = QVBoxLayout(body)
        layout.addWidget(self._build_header(snapshot))
        layout.addWidget(self._build_load_tile(snapshot, state))
        layout.addLayout(self._build_tiles(snapshot, state))

        if self._body is None:
            self._layout.addWidget(body)
        else:
            # Suppression differee : render() peut etre appele depuis un clic
            # sur un bouton de l'ancien corps.
            self._layout.replaceWidget(self._body, body)
            self._body.hide()
            self._body.deleteLater()
        self._body = body

    def _current_operator(self, snapshot: HomeSnapshot, state: HomeState):
        if not state.load_enabled:
            return None
        chosen = next((op for op in snapshot.operators if op.schema == self._selected_schema), None)
        return chosen or state.preselected

    def _build_header(self, snapshot: HomeSnapshot):
        header = QWidget()
        row = QHBoxLayout(header)
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(f"color: {_CONNECTED_COLOR if snapshot.connected else _OFFLINE_COLOR};")
        row.addWidget(self._status_dot)
        self._header_label = QLabel(snapshot.header if snapshot.connected else tr("home.not_connected"))
        self._header_label.setWordWrap(True)
        row.addWidget(self._header_label, 1)
        self._connect_button = None
        if not snapshot.connected:
            self._connect_button = QPushButton(tr("home.connect"))
            self._connect_button.clicked.connect(lambda _checked=False: self._on_connect())
            row.addWidget(self._connect_button)
        return header

    def _build_load_tile(self, snapshot: HomeSnapshot, state: HomeState):
        tile = QGroupBox(tr("home.tile_load"))
        layout = QVBoxLayout(tile)

        # -- Operateur (utilisables seulement, K14) --------------------------
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("home.operator_label")))
        self._operator_buttons = {}
        self._operator_label = None
        if state.selector == SELECTOR_LABEL:
            self._operator_label = QLabel(self._operator_caption(snapshot.operators[0], state))
            top.addWidget(self._operator_label)
        elif state.selector == SELECTOR_BUTTONS:
            for op in snapshot.operators:
                button = QPushButton(self._operator_caption(op, state))
                button.setCheckable(True)
                button.setChecked(op == self._operator)
                button.clicked.connect(lambda _checked=False, op=op: self._select(op))
                top.addWidget(button)
                self._operator_buttons[op.schema] = button
        top.addStretch()
        layout.addLayout(top)

        self._message_label = None
        if state.message_key:
            self._message_label = QLabel(_MESSAGES[state.message_key]())
            self._message_label.setWordWrap(True)
            layout.addWidget(self._message_label)

        # -- Deja dans le projet ----------------------------------------------
        self._summary_label = None
        summary = summary_text(snapshot, state)
        if summary:
            row = QHBoxLayout()
            row.addWidget(QLabel(tr("home.loaded_title")))
            self._summary_label = QLabel(summary)
            self._summary_label.setStyleSheet(f"color: {_CONNECTED_COLOR};")
            row.addWidget(self._summary_label)
            row.addStretch()
            layout.addLayout(row)

        # -- Selection actuelle + suffixe (seulement avec un operateur) ----------
        self._selection = None
        self._suffix_box = None
        if self._operator is not None:
            self._selection = LayerSelectionWidget(tile)
            self._selection.set_operator(self._operator.schema, self._operator.label)
            layout.addWidget(self._selection)
            self._suffix_box = QCheckBox(tr("home.suffix_checkbox"))
            layout.addWidget(self._suffix_box)
            self._refresh_suffix()

        bar = QHBoxLayout()
        bar.addStretch()
        self._load_button = QPushButton(self._load_caption())
        self._load_button.setEnabled(state.load_enabled)
        self._load_button.clicked.connect(lambda _checked=False: self._on_load())
        bar.addWidget(self._load_button)
        layout.addLayout(bar)
        return tile

    def _build_tiles(self, snapshot: HomeSnapshot, state: HomeState):
        row = QHBoxLayout()
        specs = (
            ("project", tr("home.tile_project"), tr("home.tile_project_sub"),
             self._on_saved_project, state.saved_project_enabled),
            ("checkin", tr("home.tile_checkin"), checkin_subtitle(snapshot.plugin_summary),
             lambda: self._run_and_render(self.actions.checkin), True),
            ("diagnostic", tr("home.tile_diagnostic"), tr("home.tile_diagnostic_sub", version=snapshot.plugin_version),
             lambda: self._run_and_render(self.actions.diagnostic), True),
            ("language", tr("home.tile_language"), tr("home.tile_language_sub"),
             lambda: self._run_and_render(self.actions.change_language), True),
        )
        self._tiles = {}
        for name, title, subtitle, slot, enabled in specs:
            button = QPushButton(f"{title}\n{subtitle}" if subtitle else title)
            button.setEnabled(enabled)
            button.setMinimumHeight(48)
            button.clicked.connect(lambda _checked=False, slot=slot: slot())
            row.addWidget(button)
            self._tiles[name] = button
        return row

    # -- textes ---------------------------------------------------------------------

    @staticmethod
    def _operator_caption(op: OperatorInfo, state: HomeState) -> str:
        return f"{op.label} ✓" if op.schema in state.loaded_marks else op.label

    def _load_caption(self) -> str:
        add = self._state.mode == MODE_ADD
        if self._operator is None:
            return tr("init.btn_add") if add else tr("init.btn_init")
        if add:
            return tr("home.btn_add", operator=self._operator.label)
        return tr("home.btn_init", operator=self._operator.label)

    def _refresh_suffix(self) -> None:
        """Case du suffixe recalculee pour l'operateur choisi (§ 6.4)."""
        loaded = list(self._snapshot.project_operators) + list(self._snapshot.counts.per_operator)
        checked, editable = suffix_state(loaded, self._operator.schema,
                                         self._snapshot.project_suffix, self._snapshot.last_suffix)
        self._suffix_box.setChecked(checked)
        self._suffix_box.setEnabled(editable)

    # -- gestes ---------------------------------------------------------------------

    def _select(self, op: OperatorInfo) -> None:
        self._operator = op
        self._selected_schema = op.schema
        for schema, button in self._operator_buttons.items():
            button.setChecked(schema == op.schema)
        self._selection.set_operator(op.schema, op.label)
        self._refresh_suffix()
        self._load_button.setText(self._load_caption())

    def _on_load(self) -> None:
        op, widget = self._operator, self._selection
        if op is None or widget is None:
            return
        suffix = self._suffix_box.isChecked()
        if self._suffix_box.isEnabled():
            # Choix libre (un seul operateur) : memorise sur le poste (§ 9.5).
            QgsSettings().setValue(SUFFIX_SETTINGS_KEY, suffix)
        basemaps = widget.selected_basemaps() if widget.want_basemap() else set()
        count = self.actions.load(op, widget.selected_layers(), basemaps, widget.want_styles(), suffix)
        if count > 0:
            self.accept()

    def _on_connect(self) -> None:
        self.actions.connect()
        self.render()

    def _on_saved_project(self) -> None:
        self.accept()
        self.actions.open_saved_project()

    def _run_and_render(self, action) -> None:
        action()
        self.render()
