# -*- coding: utf-8 -*-
"""
Constructel Bridge — widget de selection des couches de l'accueil 2.0
(plan 2026-11-18 tache 4, spec § 6.2).

Deux rangees de tuiles (4 tuiles « par operateur », 4 tuiles « commun »)
pilotent un arbre allege : un groupe par tuile et par operateur
(« Zones [Wyre] »), puis un groupe par tuile commune. L'arbre fait foi : les
tuiles n'en sont que le resume (« on » / « partial » / « off » / « done » /
« disabled », calcule par bridge_presets.tile_state). Les couches deja
chargees sont grisees ET jamais rendues par selection() (decision T9-c2b : en
Qt, la case d'un groupe se propage jusqu'aux enfants desactives ; le filtre
porte sur « deja chargee », pas sur la case). Idem pour les fonds de plan.

selection() ne contient jamais v_form_lists ni docs_elements : le plan de
chargement (LayerSelection.load_plan) les ajoute.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, Optional, Sequence, Tuple

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .bridge_operators import OperatorInfo
from .bridge_presets import (
    COMMON_TILES,
    EXPERT_KEYS,
    OPERATOR_TILES,
    STATE_DISABLED,
    STATE_DONE,
    STATE_ON,
    STATE_PARTIAL,
    TILE_LAYERS,
    LayerSelection,
    selection_from_tiles,
    tile_keys,
    tile_state,
)
from .bridge_project_init import (
    BASEMAPS,
    LAYER_CATALOG,
    _detect_existing_basemaps,
    catalog_for,
    existing_by_schema,
)
from .i18n import get_language, tr
from .i18n.layer_translations import LAYER_DISPLAY_NAMES

# K11 : un appel tr LITTERAL par cle (releve par les tests i18n).
_TILE_NAMES = {
    "zones": lambda: tr("home.tile.zones"),
    "genie_civil": lambda: tr("home.tile.genie_civil"),
    "cables": lambda: tr("home.tile.cables"),
    "demand_points": lambda: tr("home.tile.demand_points"),
    "chantier": lambda: tr("home.tile.chantier"),
    "osiris": lambda: tr("home.tile.osiris"),
    "cadastre": lambda: tr("home.tile.cadastre"),
    "urbanisme": lambda: tr("home.tile.urbanisme"),
}
_ROW_TITLES = {
    "operator": lambda: tr("home.row_operator"),
    "common": lambda: tr("home.row_common"),
}
_ROW_TILES = {"operator": OPERATOR_TILES, "common": COMMON_TILES}
_TILE_ICONS = {
    "zones": "🗺", "genie_civil": "🚧", "cables": "🔌", "demand_points": "📍",
    "chantier": "🏗", "osiris": "📋", "cadastre": "🏠", "urbanisme": "🏛",
}
_PARTIAL_MARK = "◪"
_LOADED_MARK = "✔"

Key = Tuple[Optional[str], str]     # (schema operateur ou None si commune, cle du catalogue)


def _layer_label(entry: tuple) -> str:
    """Libelle court d'une couche : celui de layer_translations (meme source
    que le renommage des couches du projet, indexe par la table), sinon le
    libelle francais du catalogue."""
    names = LAYER_DISPLAY_NAMES.get(entry[3])
    if names:
        return names.get(get_language()) or names.get("en") or entry[6]
    return entry[6]


def step_number_label(number: str) -> QLabel:
    """Numero d'etape (1 / 2 / 3), hors traduction, devant le titre."""
    label = QLabel(number)
    label.setStyleSheet("font-weight: bold;")
    return label


def step_title_label(title: str) -> QLabel:
    label = QLabel(title)
    label.setStyleSheet("font-weight: bold;")
    return label


class _Group:
    """Groupe de l'arbre : tuile, operateur (None si commune) et ses couches
    encore a charger (les couches deja chargees ne comptent pas)."""

    def __init__(self, item, tile: str, label: Optional[str], loadable: list, core: list):
        self.item = item
        self.tile = tile
        self.label = label
        self.loadable = loadable      # [QTreeWidgetItem] cochables, expert compris
        self.core = core              # idem hors couches expert : le denominateur du compteur


class LayerSelectionWidget(QWidget):
    """Tuiles « par operateur » / « commun », arbre des couches, fonds de plan
    et « Appliquer les styles de la base » (voir la docstring du module).

    ``on_change`` est appele apres tout changement de case (couche, groupe,
    tuile, ligne, fond de plan, styles), une seule fois par action."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.on_change: Optional[Callable[[], None]] = None
        self._operators: Tuple[OperatorInfo, ...] = ()
        self._existing: Dict[Optional[str], set] = {None: set()}
        self._expert = False
        self._items: Dict[Key, QTreeWidgetItem] = {}
        self._tiles: Dict[str, QToolButton] = {}
        self._row_buttons: Dict[str, Tuple[QPushButton, QPushButton]] = {}
        self._groups: list = []
        self._group_of: Dict[object, _Group] = {}
        self._basemap_items: Dict[str, QTreeWidgetItem] = {}
        self._existing_basemaps = _detect_existing_basemaps()
        self._build_ui()
        self.set_operators(())

    # -- construction ------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        for row in ("operator", "common"):
            header = QHBoxLayout()
            header.addWidget(QLabel(_ROW_TITLES[row]()))
            header.addStretch()
            btn_all = QPushButton(tr("home.row_all"))
            btn_none = QPushButton(tr("home.row_none"))
            btn_all.clicked.connect(lambda _checked=False, r=row: self.set_row(r, True))
            btn_none.clicked.connect(lambda _checked=False, r=row: self.set_row(r, False))
            header.addWidget(btn_all)
            header.addWidget(btn_none)
            self._row_buttons[row] = (btn_all, btn_none)
            layout.addLayout(header)

            tiles = QHBoxLayout()
            for tile in _ROW_TILES[row]:
                button = QToolButton()
                button.setCheckable(True)
                button.clicked.connect(lambda _checked=False, t=tile: self.toggle_tile(t))
                tiles.addWidget(button)
                self._tiles[tile] = button
            layout.addLayout(tiles)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.itemChanged.connect(self._on_item_changed)
        # Etape 3 « Couches » : l'entete porte aussi la case « Afficher toutes les couches ».
        header = QHBoxLayout()
        header.addWidget(step_number_label("3"))
        header.addWidget(step_title_label(tr("home.step_layers")))
        header.addStretch()
        self._chk_expert = QCheckBox(tr("home.show_expert"))
        self._chk_expert.toggled.connect(self.set_show_expert)
        header.addWidget(self._chk_expert)
        layout.addLayout(header)
        layout.addWidget(self._tree)

        # Fonds de plan et styles : un bloc a part, que la page place dans sa
        # ligne « Options » repliable (options_panel). Sans parent : jamais
        # affiche tant que personne ne le place dans une mise en page.
        self._options = QWidget()
        options_layout = QVBoxLayout(self._options)
        basemap_box = QGroupBox(tr("init.group_basemaps"))
        basemap_layout = QVBoxLayout(basemap_box)
        self._basemap_tree = QTreeWidget()
        self._basemap_tree.setHeaderHidden(True)
        self._basemap_tree.setRootIsDecorated(True)
        self._fill_basemaps()
        self._basemap_tree.itemChanged.connect(lambda _item, _column=0: self._notify())
        basemap_layout.addWidget(self._basemap_tree)
        options_layout.addWidget(basemap_box)
        self._chk_styles = QCheckBox(tr("init.apply_styles"))
        self._chk_styles.setChecked(True)
        self._chk_styles.toggled.connect(lambda _checked=False: self._notify())
        options_layout.addWidget(self._chk_styles)

    def _fill_basemaps(self):
        basemap_groups = {}
        for bm in BASEMAPS:
            grp_name = bm.get("group", "Autres")
            if grp_name not in basemap_groups:
                gi = QTreeWidgetItem(self._basemap_tree, [grp_name])
                gi.setFlags(gi.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                gi.setCheckState(0, Qt.CheckState.Unchecked)
                gi.setExpanded(True)
                basemap_groups[grp_name] = gi

            already = bm["key"] in self._existing_basemaps
            item = QTreeWidgetItem(basemap_groups[grp_name], [bm["name"] + (f"  {_LOADED_MARK}" if already else "")])
            if already:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                item.setToolTip(0, tr("init.already_loaded"))
                item.setDisabled(True)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if bm.get("default") else Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole, bm["key"])
            self._basemap_items[bm["key"]] = item

    # -- arbre -------------------------------------------------------------------------

    @property
    def _schemas(self) -> list:
        return [operator.schema for operator in self._operators]

    def _is_loaded(self, schema: Optional[str], key: str) -> bool:
        return key in self._existing.get(schema, ())

    def _checked_keys(self) -> set:
        return {k for k, item in self._items.items()
                if not self._is_loaded(*k) and item.checkState(0) == Qt.CheckState.Checked}

    def _rebuild_tree(self, checked: Iterable[Key] = ()):
        """(Re)construit l'arbre ; les cases de *checked* encore presentes et
        non chargees sont recochees. Appelant : signaux de l'arbre bloques."""
        checked = set(checked)
        self._tree.clear()
        self._items, self._groups, self._group_of = {}, [], {}
        for operator in self._operators:
            catalog = {entry[0]: entry for entry in catalog_for(operator.schema)}
            for tile in OPERATOR_TILES:
                self._add_group(tile, operator.schema, operator.label, catalog, checked)
        common = {entry[0]: entry for entry in LAYER_CATALOG}
        for tile in COMMON_TILES:
            self._add_group(tile, None, None, common, checked)

    def _add_group(self, tile: str, schema: Optional[str], label: Optional[str], catalog: dict, checked: set):
        group_item = QTreeWidgetItem(self._tree, [""])
        group_item.setCheckState(0, Qt.CheckState.Unchecked)
        loadable, core = [], []
        for key in (k for k in TILE_LAYERS[tile] if k in tile_keys(tile, self._expert)):
            entry = catalog[key]
            loaded = self._is_loaded(schema, key)
            item = QTreeWidgetItem(group_item, [_layer_label(entry) + (f"  {_LOADED_MARK}" if loaded else "")])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            if loaded:
                # Deja chargee : grisee et decochee, jamais selectionnee (T9-c2b)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                item.setToolTip(0, f"{entry[2]}.{entry[3]} — {tr('init.already_loaded')}")
                item.setDisabled(True)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setToolTip(0, f"{entry[2]}.{entry[3]}")
                if (schema, key) in checked:
                    item.setCheckState(0, Qt.CheckState.Checked)
                loadable.append(item)
                if key not in EXPERT_KEYS:
                    core.append(item)
            self._items[(schema, key)] = item
        group = _Group(group_item, tile, label, loadable, core)
        if loadable:
            group_item.setFlags(group_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        else:
            group_item.setFlags(group_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            group_item.setDisabled(True)
        group_item.setExpanded(bool(loadable))     # groupe entierement charge : replie
        self._groups.append(group)
        self._group_of[group_item] = group

    def _refresh(self):
        """Legendes et cases des groupes, texte et etat des tuiles. Appelant :
        signaux de l'arbre bloques."""
        for group in self._groups:
            name = _TILE_NAMES[group.tile]()
            caption = f"{name}  [{group.label}]" if group.label else name
            if group.core:
                # R10 : une couche expert n'est comptee ni au numerateur ni au denominateur
                # (« 5/4 » serait illisible) ; la case du groupe suit les memes couches.
                ticked = sum(item.checkState(0) == Qt.CheckState.Checked for item in group.core)
                caption += f"  {ticked}/{len(group.core)}"
                state = (Qt.CheckState.Checked if ticked == len(group.core) else
                         Qt.CheckState.PartiallyChecked if ticked else Qt.CheckState.Unchecked)
            else:
                caption += "  " + tr("home.group_loaded")
                state = Qt.CheckState.Unchecked
            group.item.setText(0, caption)
            group.item.setCheckState(0, state)
        states = self.tile_states()
        for tile, button in self._tiles.items():
            state = states[tile]
            second = (tr("home.tile_done") if state == STATE_DONE
                      else tr("home.tile_layers", count=len(tile_keys(tile))))     # R10 : jamais d'expert
            head = f"{_TILE_ICONS[tile]} {_TILE_NAMES[tile]()}"
            if state == STATE_PARTIAL:
                head = f"{_PARTIAL_MARK} {head}"
            button.setText(f"{head}\n{second}")
            button.setToolTip(", ".join(self._tile_labels(tile)))
            button.setEnabled(state not in (STATE_DISABLED, STATE_DONE))
            button.setChecked(state == STATE_ON)
        for button in self._row_buttons["operator"]:
            button.setEnabled(bool(self._schemas))

    def _tile_labels(self, tile: str) -> list:
        catalog = {entry[0]: entry for entry in LAYER_CATALOG}
        return [_layer_label(catalog[key]) for key in TILE_LAYERS[tile] if key in tile_keys(tile, self._expert)]

    def _mutate(self, change: Callable[[], None]):
        """Applique *change* sur l'arbre signaux bloques, remet les legendes
        et les tuiles a jour, puis previent ``on_change`` (une fois)."""
        blocked = self._tree.blockSignals(True)
        try:
            change()
            self._refresh()
        finally:
            self._tree.blockSignals(blocked)
        self._notify()

    def _notify(self):
        if self.on_change is not None:
            self.on_change()

    def _on_item_changed(self, item, _column=0):
        """Case cochee par l'utilisateur : une case de groupe se propage a ses
        couches cochables."""
        group = self._group_of.get(item)

        def change():
            if group is not None:
                state = item.checkState(0)
                if state == Qt.CheckState.Checked:
                    for child in group.core:           # comme une tuile : jamais les couches expert
                        child.setCheckState(0, state)
                elif state == Qt.CheckState.Unchecked:
                    for child in group.loadable:
                        child.setCheckState(0, state)

        self._mutate(change)

    # -- operateurs, tuiles, selection -----------------------------------------------------

    def set_operators(self, operators: Sequence[OperatorInfo]) -> None:
        """Reconstruit l'arbre pour *operators* (un groupe par tuile et par
        operateur, puis les tuiles communes) et relit ce qui est deja charge.
        Les couches cochees restent cochees ; une tuile entierement cochee
        s'etend aux operateurs ajoutes."""
        full = [tile for tile, state in self.tile_states().items() if state == STATE_ON]
        kept = self._checked_keys()
        self._operators = tuple(operators)
        self._existing = existing_by_schema(self._schemas)

        def change():
            self._rebuild_tree(kept)
            for tile in full:
                self._check_tile(tile, True)

        self._mutate(change)

    def _tile_items(self, tile: str, expert: bool = False) -> list:
        keys = tile_keys(tile, expert)
        schemas = self._schemas if tile in OPERATOR_TILES else [None]
        return [self._items[(schema, key)] for schema in schemas for key in TILE_LAYERS[tile]
                if key in keys and (schema, key) in self._items and not self._is_loaded(schema, key)]

    def _check_tile(self, tile: str, checked: bool):
        """Coche (couches hors expert) ou decoche (toutes, expert compris) les
        couches de *tile*. Appelant : signaux de l'arbre bloques."""
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for item in self._tile_items(tile, expert=not checked):
            item.setCheckState(0, state)

    def toggle_tile(self, tile: str) -> None:
        """Tuile « on » -> tout decocher ; sinon tout cocher (couches expert
        exclues). Sans effet sur une tuile « done » ou « disabled »."""
        state = self.tile_states()[tile]
        if state in (STATE_DISABLED, STATE_DONE):
            return
        self._mutate(lambda: self._check_tile(tile, state != STATE_ON))

    def set_row(self, row: str, checked: bool) -> None:
        """Coche ou decoche toutes les tuiles d'une rangee (``"operator"`` ou
        ``"common"``)."""
        def change():
            for tile in _ROW_TILES[row]:
                self._check_tile(tile, checked)

        self._mutate(change)

    def set_tiles(self, tiles: Iterable[str]) -> None:
        """Selection issue des seules *tiles* (remplace la selection)."""
        self.apply_selection(self._selection_of(tiles))

    def _selection_of(self, tiles: Iterable[str]) -> LayerSelection:
        return selection_from_tiles(tiles, self._schemas, self._existing)

    def apply_selection(self, selection: LayerSelection) -> None:
        """Remplace la selection : seules les couches de *selection* sont
        cochees (operateurs absents et couches deja chargees ignores). Une
        couche expert de la selection fait afficher les couches expert."""
        wanted_expert = any(key in EXPERT_KEYS for keys in (*selection.per_operator.values(), selection.common)
                            for key in keys)
        if wanted_expert and not self._expert:
            self._set_expert(True)

        def change():
            for (schema, key), item in self._items.items():
                if self._is_loaded(schema, key):
                    continue
                keys = selection.common if schema is None else selection.per_operator.get(schema, ())
                item.setCheckState(0, Qt.CheckState.Checked if key in keys else Qt.CheckState.Unchecked)

        self._mutate(change)

    def selection(self) -> LayerSelection:
        """Couches cochees, jamais celles deja chargees (T9-c2b : le filtre
        porte sur « deja chargee », pas sur la case), jamais v_form_lists ni
        docs_elements (ajoutes par le plan de chargement)."""
        checked = self._checked_keys()
        return LayerSelection(
            {schema: frozenset(key for s, key in checked if s == schema) for schema in self._schemas},
            frozenset(key for s, key in checked if s is None),
        )

    def tile_states(self) -> Dict[str, str]:
        selection = self.selection()
        return {tile: tile_state(tile, selection, self._schemas, self._existing)
                for tile in (*OPERATOR_TILES, *COMMON_TILES)}

    def set_show_expert(self, show: bool) -> None:
        """Montre ou cache les couches expert (jamais cochees par une tuile).
        Cacher une couche expert cochee la decoche."""
        show = bool(show)
        if show == self._expert:
            return
        self._set_expert(show)
        self._mutate(lambda: None)

    def _set_expert(self, show: bool):
        """Change l'affichage expert sans prevenir ``on_change`` : l'arbre est
        reconstruit, la case du widget alignee."""
        self._expert = show
        if self._chk_expert.isChecked() != show:
            self._chk_expert.setChecked(show)      # rappelle set_show_expert : sans effet (meme valeur)
        kept = self._checked_keys()
        blocked = self._tree.blockSignals(True)
        try:
            self._rebuild_tree(kept)
        finally:
            self._tree.blockSignals(blocked)

    # -- fonds de plan et styles (inchanges depuis 1.9) --------------------------------------

    def options_panel(self) -> QWidget:
        """Bloc « fonds de plan + appliquer les styles », a placer par
        l'appelant dans sa propre mise en page (ligne « Options » de la page
        de chargement). ``selected_basemaps`` / ``want_styles`` le lisent
        toujours ici."""
        return self._options

    def selected_basemaps(self) -> set:
        """Cles des fonds de plan coches, sans ceux deja charges."""
        return {key for key, item in self._basemap_items.items()
                if key not in self._existing_basemaps and item.checkState(0) == Qt.CheckState.Checked}

    def want_basemap(self) -> bool:
        return bool(self.selected_basemaps())

    def want_styles(self) -> bool:
        return self._chk_styles.isChecked()
