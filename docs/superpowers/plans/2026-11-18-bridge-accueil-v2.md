# Constructel Bridge 2.0 — écran d'accueil v2 — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer l'écran d'accueil 1.9.0 par une fenêtre à barre latérale (Charger, Projets, Check-in, Diagnostic) dont la page Charger propose un périmètre multi-opérateur ou « Aucun », des tuiles cumulables en deux rangées et un arbre allégé ; le setup ne se rejoue plus après une mise à jour.

**Architecture:** La logique sans Qt (tuiles, sélection, presets, état de l'écran) vit dans `bridge_presets.py` et `bridge_home_model.py`, testés sans QGIS. Les vues Qt (`bridge_layer_selection.py`, `bridge_home_load.py`, `bridge_home_checkin.py`, `bridge_home_projects.py`, `bridge_diagnostic_dialog.py` → panneau) ne font que dessiner et relayer vers `HomeActions`, fournies par `bridge_plugin.py`. `init_project` accepte `operator=None` ; le plugin enchaîne un appel par opérateur.

**Tech Stack:** Python 3.9+, PyQt via `qgis.PyQt` (Qt5/Qt6), QGIS 3.28–4.99, pytest sur stubs (`plugin-repo/packages/constructel_bridge_tests/stubs`).

**Spec:** `docs/superpowers/specs/2026-11-18-bridge-accueil-v2-design.md` (et, pour les règles reprises telles quelles, `docs/superpowers/specs/2026-11-12-bridge-accueil-operateur-design.md` § 6.2–6.6).

Chemins : `PKG = plugin-repo/packages/constructel_bridge`, `TESTS = plugin-repo/packages/constructel_bridge_tests`. Commandes lancées depuis la racine du dépôt.

## Global Constraints

- QGIS **3.28 minimum** (Python 3.9 : pas de `match`, pas de `X | Y` hors annotations avec `from __future__ import annotations`) à **4.99** (Qt5/Qt6) ; enums qualifiés (`Qt.CheckState.Checked`, `QDialog.DialogCode.Accepted`).
- Tout texte affiché en **FR / EN / PT** dans `PKG/i18n/translations.py`, **un appel `tr` littéral par clé** (K11) ; chaque tâche ajoute ses clés dans les trois langues, sinon `test_bridge18_i18n.py::test_every_key_used_in_code_is_translated` échoue.
- La suite pytest complète reste verte à la fin de chaque tâche (`python3 -m pytest -q`, ≈ 4 min 30, 988 tests au départ). Un test 1.9 rendu obsolète par la spec est **réécrit** dans la même tâche, jamais supprimé sans remplaçant.
- Règle T9-c2b conservée : une couche ou un fond déjà chargé est grisé, décoché, et jamais rendu par la sélection, quel que soit l'état de sa case.
- Aucune couleur de **fond** codée en dur (thème sombre QGIS) ; couleurs de texte d'état existantes (`#2e7d32`, `#ef6c00`, `#c62828`) tolérées.
- Fenêtre utilisable en **1366×768** dans l'état par défaut (taille minimale ≤ 1000×680).
- Développement dans `.worktrees/feat-bridge-accueil-v2` (ou un clone de cette branche) ; **jamais** dans le working tree `main` du VPS, qui sert le dépôt de plugins. Publication (`release.py`) hors plan, sur GO de Simon.

## Review Focus

1. **Multi-opérateur avec couches déjà chargées pour un seul opérateur** (Wyre a déjà ses zones, Orange non) : la tuile Zones n'est « done » que si tous les opérateurs cochés l'ont ; seules les zones Orange partent. → test `test_tile_done_only_when_every_operator_has_it` (Task 1).
2. **Un opérateur échoue au milieu d'un chargement** (droits absents sur `orange`) : Wyre est chargé, l'échec est signalé, les communes ne sont pas perdues, le compte rendu reflète ce qui est arrivé. → `test_one_operator_failing_does_not_cancel_the_others` (Task 2).
3. **Preset perso ou dernier choix citant un opérateur devenu inutilisable** (scope retiré) : l'opérateur est ignoré, le reste s'applique, rien ne plante. → `test_restrict_preset_drops_unusable_operators` (Task 1), `test_last_selection_is_restored_on_open` (Task 5).
4. **Fermeture de la fenêtre pendant la sonde réseau du Diagnostic** : résultat tardif ignoré, aucun widget détruit touché. → `test_late_network_result_after_close_is_ignored` (Task 7).
5. **Changement de langue fenêtre ouverte** : la fenêtre se redessine dans la nouvelle langue sur la même page, la sélection en cours est conservée. → `test_language_change_keeps_page_and_selection` (Task 9).

---

### Task 1: Tuiles, sélection et presets sans Qt (`bridge_presets.py`)

**Files:**
- Create: `PKG/bridge_presets.py`
- Test: `TESTS/test_bridge20_presets.py`

**Interfaces:**
- Produces:
  - `OPERATOR_TILES = ("zones", "genie_civil", "cables", "demand_points")`, `COMMON_TILES = ("chantier", "osiris", "cadastre", "urbanisme")`
  - `TILE_LAYERS: dict[str, tuple[str, ...]]` (valeurs ci-dessous), `EXPERT_KEYS = frozenset({"subducts", "planning_facades"})`, `ALWAYS_KEYS = frozenset({"v_form_lists"})`, `OPERATOR_AUTO_KEYS = frozenset({"docs_elements"})`
  - `LAST_SELECTION_KEY = "constructel_bridge/last_selection"`, `USER_PRESETS_KEY = "constructel_bridge/user_presets"`
  - `tile_keys(tile: str, expert: bool = False) -> frozenset[str]`
  - `@dataclass(frozen=True) class LayerSelection: per_operator: Mapping[str, frozenset[str]]; common: frozenset[str]` avec `is_empty() -> bool`, `layer_count() -> int` (hors `ALWAYS_KEYS`/`OPERATOR_AUTO_KEYS`), `load_plan() -> list[tuple[Optional[str], frozenset[str]]]`
  - `selection_from_tiles(tiles: Iterable[str], schemas: Sequence[str], existing: Mapping[Optional[str], set]) -> LayerSelection` (`existing[None]` = communes déjà chargées, `existing[schema]` = clés opérateur déjà chargées)
  - `tile_state(tile: str, selection: LayerSelection, schemas: Sequence[str], existing: Mapping[Optional[str], set]) -> str` parmi `"on" | "off" | "partial" | "done" | "disabled"`
  - `@dataclass(frozen=True) class UserPreset: name: str; schemas: tuple[str, ...]; selection: LayerSelection`
  - `presets_to_json(presets: Sequence[UserPreset]) -> str`, `presets_from_json(raw) -> list[UserPreset]` (entrée illisible → `[]`), `restrict_preset(preset: UserPreset, usable: Iterable[str]) -> UserPreset`

`TILE_LAYERS` (spec § 6.2, § 8.1) :
- `zones`: zone_mro, zone_pop, zone_distribution, zone_drop
- `genie_civil`: structures, ducts, trench_segments, duct_progress, subducts
- `cables`: cables · `demand_points`: demand_points
- `chantier`: interventions, incidents, permis_voirie, planning_facades, plaintes, interventions_chantier, synergies
- `osiris`: osiris_frozen, osiris_worksites, osiris_autorises, osiris_phases, osiris_hypercoord, osiris_deviations, osiris_events
- `cadastre`: wfs_buildings, wfs_parcels, wfs_blocks, wfs_municipalities · `urbanisme`: wfs_protection, wfs_heritage

- [ ] **Step 1: Write the failing tests** in `TESTS/test_bridge20_presets.py` (module importé directement, sans fixture Qt, comme `bridge_home_model`) :

```python
from constructel_bridge import bridge_presets as bp

def test_expert_layers_are_never_in_a_tile_by_default():
    assert "subducts" not in bp.tile_keys("genie_civil")
    assert "subducts" in bp.tile_keys("genie_civil", expert=True)
    assert len(bp.tile_keys("chantier")) == 6

def test_zones_for_two_operators():
    sel = bp.selection_from_tiles({"zones"}, ("wyre", "orange"), {})
    assert sel.per_operator == {"wyre": bp.tile_keys("zones"), "orange": bp.tile_keys("zones")}
    assert sel.common == frozenset() and sel.layer_count() == 8

def test_common_tiles_without_operator_go_to_none_plan():
    sel = bp.selection_from_tiles({"osiris", "zones"}, (), {})
    assert sel.per_operator == {} and sel.load_plan() == [(None, bp.tile_keys("osiris") | bp.ALWAYS_KEYS)]

def test_load_plan_attaches_common_and_auto_keys_to_first_operator_only():
    sel = bp.selection_from_tiles({"zones", "osiris"}, ("wyre", "orange"), {})
    plan = sel.load_plan()
    assert [s for s, _ in plan] == ["wyre", "orange"]
    assert bp.tile_keys("osiris") <= plan[0][1] and not (bp.tile_keys("osiris") & plan[1][1])
    assert {"docs_elements", "v_form_lists"} <= plan[0][1] and {"docs_elements", "v_form_lists"} <= plan[1][1]

def test_operator_with_no_operator_layer_is_left_out_of_the_plan():
    sel = bp.selection_from_tiles({"osiris"}, ("wyre",), {})
    assert sel.per_operator == {} and sel.load_plan()[0][0] is None

def test_already_loaded_layers_are_excluded():
    sel = bp.selection_from_tiles({"zones", "osiris"}, ("wyre",), {"wyre": {"zone_mro"}, None: {"osiris_events"}})
    assert "zone_mro" not in sel.per_operator["wyre"] and "osiris_events" not in sel.common

def test_tile_done_only_when_every_operator_has_it():
    existing = {"wyre": set(bp.tile_keys("zones"))}
    sel = bp.selection_from_tiles({"zones"}, ("wyre", "orange"), existing)
    assert bp.tile_state("zones", sel, ("wyre", "orange"), existing) == "on"
    assert bp.tile_state("zones", sel, ("wyre",), existing) == "done"

def test_tile_states_partial_off_disabled():
    sel = bp.LayerSelection({"wyre": frozenset({"zone_mro"})}, frozenset())
    assert bp.tile_state("zones", sel, ("wyre",), {}) == "partial"
    assert bp.tile_state("cables", sel, ("wyre",), {}) == "off"
    assert bp.tile_state("zones", bp.LayerSelection({}, frozenset()), (), {}) == "disabled"

def test_presets_round_trip_and_garbage():
    p = bp.UserPreset("Coordo", ("wyre",), bp.selection_from_tiles({"zones", "osiris"}, ("wyre",), {}))
    assert bp.presets_from_json(bp.presets_to_json([p])) == [p]
    assert bp.presets_from_json("not json") == [] and bp.presets_from_json(None) == []

def test_restrict_preset_drops_unusable_operators():
    p = bp.UserPreset("x", ("wyre", "orange"), bp.selection_from_tiles({"zones", "osiris"}, ("wyre", "orange"), {}))
    r = bp.restrict_preset(p, {"wyre"})
    assert r.schemas == ("wyre",) and set(r.selection.per_operator) == {"wyre"} and r.selection.common == p.selection.common
```

Plus un test d'alignement sous la fixture `pi` (module Qt) :

```python
def test_tiles_cover_the_catalog(pi):
    from constructel_bridge import bridge_project_init as bpi
    tiled = {k for keys in bp.TILE_LAYERS.values() for k in keys}
    assert tiled | bp.ALWAYS_KEYS | bp.OPERATOR_AUTO_KEYS == {e[0] for e in bpi.LAYER_CATALOG}
    assert {k for t in bp.OPERATOR_TILES for k in bp.TILE_LAYERS[t]} == set(bpi.OPERATOR_KEYS) - bp.OPERATOR_AUTO_KEYS
```

(Si `OPERATOR_KEYS` contient `docs_elements` ou non, ajuster la seconde assertion pour refléter le catalogue réel : le test fige l'appartenance, il ne la change pas.)

- [ ] **Step 2: Run** `python3 -m pytest TESTS/test_bridge20_presets.py -q` — Expected: FAIL (`ModuleNotFoundError: constructel_bridge.bridge_presets`).
- [ ] **Step 3: Implement `PKG/bridge_presets.py`** — aucun import qgis/Qt ; JSON via `json`, `per_operator` sérialisé en `{schema: sorted(keys)}` ; `LayerSelection` comparable (frozensets, dict trié à la construction).
- [ ] **Step 4: Run** the same command — Expected: PASS.
- [ ] **Step 5: Commit** — `git add PKG/bridge_presets.py TESTS/test_bridge20_presets.py && git commit -m "feat(bridge): tuiles et sélection de couches sans Qt (2.0)"`

---

### Task 2: Chargement sans opérateur et multi-opérateur

**Files:**
- Modify: `PKG/bridge_project_init.py` (`init_project` ≈ l. 1199, `_detect_existing_layers` l. 610, `_layer_group` l. 759)
- Modify: `PKG/bridge_plugin.py` (`_load_operator_layers` l. 3904 → `_load_selection`, `_reorganize_legacy_project` l. 3962)
- Modify: `PKG/bridge_operators.py` (clé `LAST_OPERATORS_KEY`)
- Test: `TESTS/test_bridge20_load.py` ; adapter les tests 1.9 qui appellent `_load_operator_layers` (`grep -rn _load_operator_layers TESTS`)

**Interfaces:**
- Consumes: `LayerSelection.load_plan()` (Task 1)
- Produces:
  - `init_project(conn_params, password, selected, add_basemap=True, apply_styles=True, selected_basemaps=None, *, operator: OperatorInfo | None, suffix: bool | None = None) -> int` — `operator=None` : seules les entrées hors `OPERATOR_GROUPS` sont lues, `stamp_project` jamais appelé, `_stamp_version` toujours.
  - `_detect_existing_layers(schema: str | None) -> set[str]` — `None` : clés communes présentes seulement.
  - `existing_by_schema(schemas: Sequence[str]) -> dict[Optional[str], set[str]]` dans `bridge_project_init` (forme attendue par Task 1).
  - `LAST_OPERATORS_KEY = "constructel_bridge/last_operators"` (liste séparée par des virgules) dans `bridge_operators`.
  - `ConstructelBridge._load_selection(operators: Sequence[OperatorInfo], selection: LayerSelection, basemaps: set, apply_styles: bool, suffix: bool | None) -> int` — remplace `_load_operator_layers`, retourne couches + fonds ajoutés ; ne lève jamais.

- [ ] **Step 1: Write the failing tests** (`TESTS/test_bridge20_load.py`, fixtures `pi`/`install_fake_project` de `fakes19` comme `test_bridge19_catalog.py`) :
  - `test_init_project_without_operator_loads_common_only_and_never_stamps` : `init_project(..., {"osiris_frozen", "v_form_lists"}, operator=None)` → couche `osiris.frozen_zones` dans le groupe « Commun », `get_bridge_info()["operators"] == []`, `bridge/version` écrit.
  - `test_detect_existing_layers_none_is_common_only` : projet avec `wyre.cables` et `chantier.interventions` → `_detect_existing_layers(None) == {"interventions"}`.
  - `test_load_selection_chains_operators_and_loads_common_once` : plugin factice (patron `test_bridge19_home` « load ») avec `init_project` espionné ; sélection Zones+OSIRIS pour (WYRE, ORANGE) → deux appels, `operator` = WYRE puis ORANGE, OSIRIS dans le premier `selected` seulement, `basemaps` au premier appel seulement, `LAST_OPERATORS_KEY == "wyre,orange"`.
  - `test_load_selection_common_only_calls_init_project_with_none` → un appel, `operator is None`, `LAST_OPERATORS_KEY` inchangé.
  - `test_one_operator_failing_does_not_cancel_the_others` : `init_project` lève pour ORANGE → WYRE chargé, retour = couches WYRE, un message d'avertissement `tr("home.load_partial", operators="Orange")` poussé, pas de `QMessageBox.critical` si au moins un opérateur a réussi.
  - `test_reorganize_runs_once_with_first_operator` : projet 1.8 à ranger → `_reorganize_legacy_project` appelé une fois, avec WYRE.
- [ ] **Step 2: Run** `python3 -m pytest TESTS/test_bridge20_load.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** : `init_project` (catalogue filtré si `operator is None`, `_layer_group` jamais appelé avec un groupe opérateur dans ce cas), `_detect_existing_layers(None)`, `existing_by_schema`, `_load_selection` (boucle sur `selection.load_plan()`, opérateur retrouvé par schéma dans *operators*, réorganisation 1.8 une fois avec le premier opérateur s'il y en a un, traductions / hooks / scope une fois à la fin, message `init.success` / `init.success_basemaps` / `init.nothing_added` / `home.load_partial`). Supprimer `_load_operator_layers`. Clé i18n `home.load_partial` (FR « Chargement incomplet : échec pour {operators} (voir le journal). » + EN/PT).
- [ ] **Step 4: Run** `python3 -m pytest TESTS/test_bridge20_load.py -q` puis la suite complète — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(bridge): chargement sans opérateur et multi-opérateur (2.0)"`

---

### Task 3: Modèle de l'écran v2 (`bridge_home_model.py`)

**Files:**
- Modify: `PKG/bridge_home_model.py`
- Modify: `TESTS/test_bridge19_home.py` (section « modele » réécrite) → nouveaux tests dans `TESTS/test_bridge20_home_model.py`

**Interfaces:**
- Consumes: `UserPreset`, `restrict_preset` (Task 1) ; `PluginSummary` (`bridge_diagnostic`)
- Produces:
  - `@dataclass(frozen=True) class CheckinState: plugins: Optional[PluginSummary]; resource_sharing: Optional[bool]; filtermate: Optional[bool]` (`None` = extension absente, sans objet)
  - `HomeSnapshot` : champs 1.9 conservés sauf `last_schema` → `last_selection: Optional[UserPreset]` ; ajouts `user_presets: tuple = ()`, `checkin: Optional[CheckinState] = None`
  - `HomeState(load_enabled: bool, message_key: str, operators: tuple, preselected: tuple[str, ...], loaded_marks: frozenset, summary: tuple, saved_project_enabled: bool, checkin_badge: int)`
  - `MESSAGE_CONNECT = "home.connect_to_see"`, `MESSAGE_COMMON_ONLY = "home.common_only"` (`MESSAGE_NO_OPERATOR` et `SELECTOR_*`, `MODE_*` supprimés)
  - `toggle_operator(current: tuple[str, ...], schema: str, order: Sequence[str]) -> tuple[str, ...]` (ordre = ordre des opérateurs utilisables) ; `select_none() -> tuple` = `()`
  - `suffix_state(loaded_schemas: Iterable[str], selected_schemas: Iterable[str], project_suffix, last_suffix) -> tuple[bool, bool]`
  - `checkin_badge(state: Optional[CheckinState]) -> int` = `updates + (total - active)` des extensions + 1 par partage `False`
  - `HomeActions(snapshot, connect, load, list_projects, open_project, diagnostic_inputs, diagnostic_action, configure_sharing, make_wizard, set_language, save_presets)` — signatures :
    `load(operators: tuple[OperatorInfo, ...], selection: LayerSelection, basemaps: set, styles: bool, suffix: Optional[bool]) -> int` ;
    `list_projects() -> Optional[list[dict]]` (clés `name`, `schema`, `description`, `updated`) ; `open_project(schema: str, name: str) -> bool` ;
    `diagnostic_inputs() -> tuple[str, list, dict]` (texte d'état, vérifications locales, arguments réseau) ; `diagnostic_action(check) -> list` ;
    `configure_sharing(kind: str) -> str` (`"resource_sharing"` | `"filtermate"`, retourne le message affiché) ; `make_wizard(parent) -> QWizard` ;
    `set_language(code: str) -> None` ; `save_presets(presets: list[UserPreset]) -> None`

- [ ] **Step 1: Write the failing tests** (`test_bridge20_home_model.py`, helper `snap()` repris de `test_bridge19_home.py` avec les nouveaux champs) :
  - `test_offline_disables_loading_and_projects` → `load_enabled False`, `message_key == "home.connect_to_see"`, `preselected == ()`, `saved_project_enabled False`.
  - `test_connected_without_operator_allows_common_only` → `load_enabled True`, `message_key == "home.common_only"`, `operators == ()`, `preselected == ()`.
  - `test_first_open_preselects_first_operator` → `preselected == ("wyre",)`.
  - `test_last_selection_preselects_its_usable_operators` : `last_selection` sur (orange, proximus), utilisables (wyre, orange) → `preselected == ("orange",)` ; `last_selection` avec `schemas == ()` → `preselected == ()`.
  - `test_toggle_operator_keeps_order_and_none_is_empty` : `toggle_operator(("orange",), "wyre", ("wyre", "orange")) == ("wyre", "orange")` ; retirer le dernier → `()`.
  - `test_suffix_forced_with_two_selected` : `suffix_state([], ["wyre", "orange"], None, False) == (True, False)` ; `suffix_state([], [], None, True) == (True, True)` (sans opérateur : case sans objet mais état stable).
  - `test_checkin_badge` : `CheckinState(PluginSummary(5, 6, 1), True, False)` → `3` ; `None` → `0` ; partage `None` non compté.
  - Conserver/adapter `test_loaded_counts_shape` et les tests `summary`/`loaded_marks` existants.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** ; clé i18n `home.common_only` (FR « Aucun opérateur disponible : seules les couches communes peuvent être chargées. » + EN/PT).
- [ ] **Step 4: Run** `python3 -m pytest TESTS/test_bridge20_home_model.py -q` — Expected: PASS. (Les tests de `bridge_home`/plugin cassés par la nouvelle forme sont réparés aux tâches 5 et 9 ; la suite complète doit néanmoins rester verte : marquer temporairement ces tests `pytest.mark.skip(reason="réécrit en Task 9")` **seulement** s'ils dépendent de `HomeDialog`, et les retirer en Task 9.)
- [ ] **Step 5: Commit** — `git commit -m "feat(bridge): modèle de l'accueil 2.0 (périmètre multiple, communes seules, pastille)"`

---

### Task 4: Widget de sélection v2 (`bridge_layer_selection.py`) et doublures partagées

**Files:**
- Create: `PKG/bridge_layer_selection.py` (déplace et réécrit `LayerSelectionWidget` ; `bridge_project_init` ne le contient plus, `TEMPLATES` et `_INFRA_BASE` supprimés — `topo_violations` disparaît avec eux)
- Create: `TESTS/fakes_widgets.py` (doublures `_W`, `_Label`, `_Button`, `_CheckBox`, `_GroupBox`, `_Dialog`, `_Layout`, `_Item`, `_Tree`, `_Combo`, `_Sig`, `_widgets`, `_texts`, enums `_ITEM_FLAG`, `_CHECK`, `_ROLE` sortis de `test_bridge19_home.py`, plus `_ToolButton(_Button)`, `_Menu`, `_LineEdit`, `_Stack`, `_ListWidget`)
- Test: `TESTS/test_bridge20_selection.py` ; supprimer de `test_bridge19_home.py` la section « LayerSelectionWidget » (remplacée)

**Interfaces:**
- Consumes: Task 1 (`tile_keys`, `selection_from_tiles`, `tile_state`, `LayerSelection`, `EXPERT_KEYS`), Task 2 (`existing_by_schema`), `BASEMAPS`, `_detect_existing_basemaps`, `catalog_for`, `GROUP_NAMES`
- Produces: `class LayerSelectionWidget(QWidget)` :
  - `__init__(parent=None)` ; attribut `on_change: Optional[Callable[[], None]]` appelé après tout changement de case
  - `set_operators(operators: Sequence[OperatorInfo]) -> None` : reconstruit l'arbre, **un groupe par tuile et par opérateur** (« Zones [Wyre] ») puis un groupe par tuile commune ; Référence absente ; couches expert absentes tant que `set_show_expert(False)`
  - `set_tiles(tiles: Iterable[str]) -> None`, `toggle_tile(tile: str) -> None`, `set_row(row: str, checked: bool) -> None` (`row` ∈ `"operator" | "common"`)
  - `apply_selection(selection: LayerSelection) -> None`, `selection() -> LayerSelection`, `tile_states() -> dict[str, str]`
  - `set_show_expert(show: bool) -> None`
  - `selected_basemaps() -> set[str]`, `want_basemap() -> bool`, `want_styles() -> bool` (inchangés)
  - `_items: dict[tuple[Optional[str], str], QTreeWidgetItem]` (clé `(schema, key)`, `None` pour une commune) ; `_tiles: dict[str, QToolButton]`

Rendu : tuile = `QToolButton` checkable, texte `"{icône} {nom}\n{n} couches"` (`tr("home.tile_layers", count=n)`), infobulle = libellés de ses couches ; état partiel = case à trois états via `setText` préfixé `◪`, « done » = désactivée + `tr("home.tile_done")`. Libellé d'item = libellé court seul (`layer_translations`), infobulle `schema.table`. Groupe : `"{nom}  [{opérateur}]"` ou `"{nom}"` + compteur `"  {coché}/{total}"` ou `"  " + tr("home.group_loaded")` ; groupe entièrement chargé replié.

- [ ] **Step 1: Write the failing tests** (`test_bridge20_selection.py`, fixture `sel` reprise sur `fakes_widgets`, `QToolButton` doublé) :
  - `test_tree_has_one_group_per_tile_and_operator` : `set_operators((WYRE, ORANGE))` → légendes commençant par Zones [Wyre], Génie civil [Wyre], Câbles [Wyre], Points de demande [Wyre], puis les mêmes [Orange], puis Chantier, OSIRIS, Cadastre UrbIS, Urbanisme ; aucune légende « Référence ».
  - `test_short_labels_and_table_in_tooltip` : item `("wyre", "cables")` → texte sans `(wyre.cables)`, infobulle `"wyre.cables"`.
  - `test_expert_layers_hidden_until_requested` : `("wyre", "subducts") not in _items` ; après `set_show_expert(True)` présent et décoché ; `toggle_tile("genie_civil")` ne le coche pas.
  - `test_tile_toggles_layers_for_every_operator` : `toggle_tile("zones")` → les 8 items zones cochés ; `tile_states()["zones"] == "on"`.
  - `test_manual_change_makes_tile_partial_and_calls_on_change` : décocher `("orange", "zone_drop")` → `"partial"`, `on_change` appelé.
  - `test_loaded_layers_greyed_per_schema` (T9-c2b) : `wyre.zone_mro` chargé → `("wyre","zone_mro")` grisé, `("orange","zone_mro")` cochable ; jamais dans `selection()` même case cochée.
  - `test_no_operator_disables_operator_row` : `set_operators(())` → `tile_states()` des 4 tuiles opérateur `"disabled"`, boutons désactivés.
  - `test_apply_selection_round_trip` : `apply_selection(s)` puis `selection() == s`.
  - `test_row_all_none` : `set_row("common", True)` coche les 4 tuiles communes (hors expert) ; `False` les décoche.
  - Reprendre les tests fonds de plan / styles 1.9 (`test_basemaps_already_loaded_are_greyed_and_never_selected_again`, `test_nothing_new_to_add_means_no_basemap_wanted`, `test_selected_layers_always_include_form_lists_and_styles_default_on` → `selection()` ne contient jamais `v_form_lists`, le plan de chargement l'ajoute).
- [ ] **Step 2: Run** `python3 -m pytest TESTS/test_bridge20_selection.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** ; clés i18n `home.tile_layers` (« {count} couches »), `home.tile_done` (« déjà chargé »), `home.group_loaded` (« déjà chargé »), `home.row_operator` (« Par opérateur »), `home.row_common` (« Commun »), `home.row_all` (« tout »), `home.row_none` (« rien »), `home.show_expert` (« Afficher toutes les couches »), et les 8 noms de tuiles `home.tile.zones` … `home.tile.urbanisme` (Zones, Génie civil, Câbles, Points de demande, Chantier, OSIRIS, Cadastre UrbIS, Urbanisme) — un `tr` littéral par clé dans un dict `_TILE_NAMES` (patron `_MESSAGES`).
- [ ] **Step 4: Run** the file then the full suite — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(bridge): sélection par tuiles et arbre allégé (2.0)"`

---

### Task 5: Page « Charger les couches » (`bridge_home_load.py`)

**Files:**
- Create: `PKG/bridge_home_load.py`
- Test: `TESTS/test_bridge20_load_page.py`

**Interfaces:**
- Consumes: Task 3 (`HomeSnapshot`, `HomeState`, `HomeActions`, `toggle_operator`, `suffix_state`), Task 4 (`LayerSelectionWidget`), Task 1 (`UserPreset`, `restrict_preset`, `presets_to_json`, `LAST_SELECTION_KEY`)
- Produces: `class LoadPage(QWidget)` — `__init__(snapshot, state, actions, on_done: Callable[[bool], None], parent=None)` ; `on_done(True)` après un chargement qui a ajouté quelque chose (la fenêtre se ferme), `on_done(False)` sinon (la fenêtre se redessine) ; attributs testés : `_operator_buttons: dict[str, QPushButton]`, `_none_button`, `_selection`, `_suffix_box`, `_summary_label`, `_load_button`, `_presets_button` (QToolButton + QMenu) ; méthode `current_choice() -> UserPreset` (nom `""`).

Contenu, de haut en bas : ligne « Déjà dans le projet » (texte 1.9 `summary_text`, déplacé ici), message `state.message_key`, étape 1 Périmètre (un bouton checkable par opérateur de `state.operators` + `tr("home.none_operator")` « Aucun — couches communes »), étape 2 en-tête avec le menu « Mes presets ▾ » (presets de `snapshot.user_presets` + « Enregistrer ma sélection… » via `QInputDialog.getText`) et les tuiles du widget, étape 3 arbre + `home.show_expert`, ligne « Options » repliable (fonds de plan, styles, suffixe — masqué si aucun opérateur coché), pied : résumé `tr("home.load_summary", layers=n, basemaps=m)` + bouton `tr("home.btn_load")` « Charger ».

- [ ] **Step 1: Write the failing tests** (doublures `fakes_widgets`, `LayerSelectionWidget` réel sur `sel` ou factice selon le test) :
  - `test_perimeter_is_multi_and_none_is_exclusive` : clic Orange avec Wyre présélectionné → les deux cochés ; clic Aucun → aucun opérateur coché, `_selection` reçoit `set_operators(())`, suffixe masqué.
  - `test_unchecking_last_operator_switches_to_none` → bouton Aucun coché.
  - `test_load_button_reads_charger_and_never_names_an_operator` : `_load_button.text() == tr("home.btn_load")`.
  - `test_load_calls_action_with_operators_and_selection` : Wyre+Orange, tuile Zones → `actions.load` reçoit `(WYRE, ORANGE)`, une `LayerSelection` à 8 couches, suffixe `True` imposé ; succès → `on_done(True)` et `LAST_SELECTION_KEY` écrit (JSON relisible par `presets_from_json`).
  - `test_nothing_added_keeps_window_open` : `load` rend 0 → `on_done(False)`, rien d'écrit.
  - `test_last_selection_is_restored_on_open` : `snapshot.last_selection` (orange + zones + osiris) avec orange seul utilisable sur deux → Orange coché, tuiles Zones et OSIRIS « on ».
  - `test_save_preset_appends_and_saves` : `QInputDialog.getText` patché → `actions.save_presets` reçoit l'ancienne liste + le nouveau preset ; nom vide ou annulé → rien.
  - `test_choosing_a_preset_applies_it` : action du menu → périmètre et sélection appliqués (opérateurs non utilisables ignorés).
  - `test_offline_page_disables_everything_but_shows_message` → `_load_button.enabled False`, message `home.connect_to_see`.
  - `test_summary_counts_what_will_be_added`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** ; clés i18n `home.none_operator`, `home.step_perimeter` (« Périmètre »), `home.step_presets` (« Presets »), `home.step_layers` (« Couches »), `home.my_presets` (« Mes presets »), `home.save_preset` (« Enregistrer ma sélection… »), `home.save_preset_prompt` (« Nom du preset : »), `home.options` (« Options »), `home.load_summary` (« {layers} couches · {basemaps} fonds de plan »), `home.btn_load` (« Charger »).
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(bridge): page Charger les couches (périmètre, presets, résumé) (2.0)"`

---

### Task 6: Page Check-in et partages extraits de l'assistant

**Files:**
- Modify: `PKG/bridge_onboarding.py` (`_configure_resource_sharing` l. 691, `_configure_filtermate_sharing` l. 803 → fonctions de module ; les méthodes de l'assistant les appellent)
- Create: `PKG/bridge_home_checkin.py`
- Test: `TESTS/test_bridge20_checkin.py` ; `TESTS/test_bridge19_checkin.py` doit rester vert

**Interfaces:**
- Consumes: Task 3 (`CheckinState`, `HomeActions.diagnostic_action`, `configure_sharing`, `make_wizard`) ; `check_message`, `action_label` (`bridge_diagnostic_dialog`) ; `plugin_checks`
- Produces:
  - `configure_resource_sharing(settings=None) -> str` (message traduit, mêmes clés `onboard.action.rs_*` qu'aujourd'hui) ; `configure_filtermate_sharing(log: Callable[[str], None]) -> str` (mêmes clés `onboard.action.fm_*`)
  - `resource_sharing_configured(settings=None) -> Optional[bool]` (`None` si l'extension n'est ni disponible ni active ; sinon dépôt nommé `RESOURCE_SHARING_REPO_NAME` **et** URL `RESOURCE_SHARING_REPO_URL`) ; `filtermate_configured() -> Optional[bool]` (même règle, dépôt `FILTERMATE_REPO_NAME` dans la config FilterMate lue par l'API, à défaut le JSON — mêmes chemins que `_configure_filtermate_via_*`)
  - `class CheckinPage(QWidget)` : `__init__(snapshot, actions, parent=None, start_wizard: bool = False)` ; `on_change: Optional[Callable[[], None]]` (redessin de la fenêtre / pastille) ; attributs `_wizard_button`, `_rows`, `_wizard` (assistant hébergé ou `None`)

Contenu : profil (login, e-mail si connu, sinon `tr("home.checkin_profile_offline")`), une ligne par vérification d'extension (`snapshot` → `actions.diagnostic_inputs()[1]`, filtrées sur `kind == "plugin"`) avec son bouton d'action (`actions.diagnostic_action`), ligne Resource Sharing et ligne FilterMate (état + bouton `tr("home.configure")` → `actions.configure_sharing(kind)` puis rafraîchissement), bouton `tr("home.checkin_full")` « Refaire le check-in complet » → `actions.make_wizard(self)`, `wizard.setWindowFlags(Qt.WindowType.Widget)`, ajouté au layout à la place des lignes ; à `finished`, lignes rafraîchies et `on_change()`.

- [ ] **Step 1: Write the failing tests** :
  - `test_resource_sharing_configured_reads_settings` (fausses `QgsSettings` : dépôt présent / URL différente / absent / extension absente → `True`, `False`, `False`, `None`).
  - `test_configure_resource_sharing_is_the_wizard_code` : la méthode de l'assistant délègue (même message, même écriture de réglages qu'en 1.9 — reprendre les assertions de `test_bridge19_checkin.py`).
  - `test_page_lists_plugins_with_actions_and_sharing_rows`.
  - `test_configure_button_calls_action_then_refreshes`.
  - `test_full_checkin_hosts_the_wizard_in_the_page` : `make_wizard` reçoit la page ; `setWindowFlags(Widget)` appelé ; `finished` → `on_change` appelé, assistant retiré.
  - `test_start_wizard_opens_it_immediately` (`start_wizard=True`).
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** ; clés `home.checkin_title`, `home.checkin_profile`, `home.checkin_profile_offline`, `home.checkin_plugins`, `home.checkin_sharing`, `home.rs_configured`, `home.rs_missing`, `home.fm_configured`, `home.fm_missing`, `home.sharing_na` (« extension non installée »), `home.configure`, `home.checkin_full`.
- [ ] **Step 4: Run** the new file + `test_bridge19_checkin.py` + full suite — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(bridge): page Check-in (état, actions, assistant hébergé) (2.0)"`

---

### Task 7: Diagnostic en panneau

**Files:**
- Modify: `PKG/bridge_diagnostic_dialog.py` (`DiagnosticDialog` → `DiagnosticPanel(QWidget)`)
- Modify: `TESTS/test_bridge19_diagnostic.py` (tests du dialogue réécrits sur le panneau)

**Interfaces:**
- Consumes: `HomeActions.diagnostic_inputs`, `diagnostic_action` (Task 3)
- Produces: `class DiagnosticPanel(QWidget)` : `__init__(status_text: str, local_checks: list, network_args: dict, on_action: Callable[[Check], list], parent=None)` ; `restart() -> None` (relance la sonde réseau, lignes réseau repassées « … ») ; `close_panel() -> None` (équivalent de `done` : résultat tardif ignoré) ; `_PENDING_TASKS`, `check_message`, `action_label` inchangés. `DiagnosticDialog` supprimé.

- [ ] **Step 1: Adapt the tests** : tous les tests actuels de `DiagnosticDialog` portés sur `DiagnosticPanel` (construction, actions, rendu après action, tâche gardée), plus :
  - `test_restart_runs_a_new_network_task` ;
  - `test_late_network_result_after_close_is_ignored` : `close_panel()` puis `on_finished` de la tâche → aucune méthode de widget appelée (doublure qui lève si touchée), tâche relâchée de `_PENDING_TASKS`.
- [ ] **Step 2: Run** `python3 -m pytest TESTS/test_bridge19_diagnostic.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** — même logique, sans `QDialogButtonBox` ; bouton `tr("diag.restart")` « Relancer ».
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "refactor(bridge): Diagnostic en panneau hébergeable, bouton Relancer (2.0)"`

---

### Task 8: Page Projets

**Files:**
- Create: `PKG/bridge_home_projects.py`
- Modify: `PKG/bridge_plugin.py` (`_on_load_project` l. 4000 : la partie après le choix devient `_open_db_project(schema: str, name: str) -> bool` ; le `QInputDialog` disparaît)
- Test: `TESTS/test_bridge20_projects.py` ; adapter `TESTS/test_bridge19_browser_projects.py` si elle appelle `_on_load_project`

**Interfaces:**
- Consumes: `HomeActions.list_projects`, `open_project` (Task 3)
- Produces: `class ProjectsPage(QWidget)` : `__init__(actions, connected: bool, labels: dict, on_open: Callable[[], None], parent=None)` ; `_search: QLineEdit`, `_tree: QTreeWidget` (un groupe par schéma, libellé opérateur via *labels*, `public` → `tr("home.projects_common")`), `_open_button` ; `on_open()` est appelé **avant** `actions.open_project` (la fenêtre se ferme d'abord, D11). Section chantier 3 : aucune.

- [ ] **Step 1: Write the failing tests** :
  - `test_projects_grouped_by_operator_with_search` : trois projets (wyre ×2, public ×1) → deux groupes ; filtre « ixe » ne garde que le projet correspondant (nom ou description, insensible à la casse et aux accents).
  - `test_open_closes_window_first_then_opens` : ordre du journal `["on_open", ("open_project", "wyre", "Ixelles")]`.
  - `test_open_button_disabled_without_selection`.
  - `test_offline_shows_message_and_never_lists` : `list_projects` doublé qui lève s'il est appelé.
  - `test_list_error_or_empty_shows_message` (`None` → `tr("project.none_found")` ou message d'erreur déjà journalisé par le plugin).
  - côté plugin : `test_open_db_project_reports_success_and_failure` (messages `project.loaded` / `project.load_error` repris de 1.9).
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** ; clés `home.projects_title`, `home.projects_search`, `home.projects_open`, `home.projects_common`, `home.projects_offline`.
- [ ] **Step 4: Run** — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(bridge): page Projets enregistrés (groupes, recherche) (2.0)"`

---

### Task 9: Fenêtre à barre latérale et câblage du plugin

**Files:**
- Modify: `PKG/bridge_home.py` (réécrit : `HomeDialog`)
- Modify: `PKG/bridge_plugin.py` (`_on_home` l. 3821, `_home_actions` l. 3836, `home_snapshot` l. 3858, menus l. 1040–1085, `_run_onboarding` l. 4296, `_on_onboarding`, `_on_diagnostic`, `_on_change_language`)
- Modify: `TESTS/test_bridge19_home.py` (section HomeDialog et câblage plugin réécrite ; retirer les `skip` posés en Task 3)
- Test: `TESTS/test_bridge20_home.py`

**Interfaces:**
- Consumes: Tasks 3, 5, 6, 7, 8
- Produces:
  - `class HomeDialog(QDialog)` : `__init__(actions: HomeActions, parent=None, page: str = "load", start_wizard: bool = False)` ; `PAGES = ("load", "projects", "checkin", "diagnostic")` ; `show_page(name: str) -> None` ; `render() -> None` (reconstruit depuis `actions.snapshot()` en gardant la page courante et, pour Charger, `LoadPage.current_choice()`) ; attributs `_sidebar: QListWidget`, `_stack: QStackedWidget`, `_pages: dict[str, QWidget]` (construites à la demande), `_lang_buttons: dict[str, QPushButton]`, `_connect_button`
  - Barre latérale : libellés `tr("home.nav_load")`, `tr("home.nav_projects")`, `tr("home.nav_checkin")` (+ `"  ⚠ {n}"` si `state.checkin_badge`), `tr("home.nav_diagnostic")` ; bas de barre : point d'état + `snapshot.header` ou `tr("home.not_connected")`, bouton `tr("home.connect")` hors connexion, boutons FR · EN · PT (`actions.set_language(code)` puis `render()`). Fermeture : `DiagnosticPanel.close_panel()` appelé.
  - Plugin : `_on_home(page: str = "load", start_wizard: bool = False)` ; menus : Check-in → `_on_home("checkin")`, Statut et diagnostic → `_on_home("diagnostic")`, Charger un projet → `_on_home("projects")`, Langue → `_on_home("load")` ; ouverture automatique au premier setup (`_connect` l. ~2269 et `_on_initialization_completed` l. ~1607) → `_on_home("checkin", start_wizard=True)` avec les gardes I-3 / I13 inchangées ; `home_snapshot()` remplit `last_selection` (`presets_from_json` sur `LAST_SELECTION_KEY`, premier élément), `user_presets` (`USER_PRESETS_KEY`), `checkin=CheckinState(plugin_summary, resource_sharing_configured(), filtermate_configured())` ; `_home_actions()` câble `_load_selection`, `_list_db_projects`, `_open_db_project`, `diagnostic_inputs` (`_status_text()`, `_diagnostic_local_checks()`, arguments réseau de l'actuel `_on_diagnostic`), `_run_diagnostic_action`, `configure_sharing`, `make_wizard` (fabrique `OnboardingWizard` comme `_run_onboarding`, `parent` = page), `set_language` (corps de `_on_change_language` sans `QInputDialog`), `save_presets` (`QgsSettings` + `presets_to_json`).
  - Taille : `setMinimumSize(980, 640)`, `resize(1100, 720)`.

- [ ] **Step 1: Write the failing tests** (`test_bridge20_home.py`, doublures + pages factices enregistreuses) :
  - `test_sidebar_has_four_pages_and_opens_on_requested_page` (`page="diagnostic"` → `_stack` courant = panneau diagnostic).
  - `test_checkin_badge_in_sidebar` (`checkin_badge == 2` → libellé se terminant par `⚠ 2`).
  - `test_pages_are_built_lazily` (Projets non construite tant que non affichée → `list_projects` jamais appelé).
  - `test_offline_footer_offers_connect_and_connect_rerenders`.
  - `test_language_change_keeps_page_and_selection` : sur Charger avec Orange + Zones, clic EN → `set_language("en")`, `render()`, page toujours « load », `current_choice()` identique.
  - `test_closing_window_closes_diagnostic_panel`.
  - `test_load_success_closes_window`, `test_load_nothing_rerenders`.
  - plugin : `test_menu_entries_open_home_on_their_page` (Check-in, Statut et diagnostic, Charger un projet, Langue) ; `test_first_setup_opens_home_on_checkin_with_wizard` ; `test_home_snapshot_reads_last_selection_presets_and_checkin`.
  - Réécrire les tests 1.9 de `HomeDialog`/plugin (`test_bridge19_home.py` à partir de « HomeDialog ») sur la nouvelle forme : conserver chaque règle encore valable (hors connexion sans base touchée, suffixe mémorisé seulement si changé par la personne, fermeture avant projet enregistré, fenêtre détruite après exec).
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** ; clés `home.nav_load`, `home.nav_projects`, `home.nav_checkin`, `home.nav_diagnostic`.
- [ ] **Step 4: Run** `python3 -m pytest -q` (suite complète, aucun `skip` restant de Task 3) — Expected: PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(bridge): fenêtre à barre latérale, entrées de menu vers les pages (2.0)"`

---

### Task 10: Setup non rejoué, nettoyage i18n, version 2.0.0

**Files:**
- Modify: `PKG/bridge_plugin.py` (l. 1097–1106 : détection install/mise à jour)
- Modify: `PKG/i18n/translations.py` (clés obsolètes retirées), `PKG/metadata.txt` (version, changelog)
- Create: `TESTS/test_bridge20_i18n.py` ; Modify: `TESTS/test_bridge19_i18n.py` (listes `KEYS_19`/orphelines alignées)
- Test: `TESTS/test_bridge20_setup.py`

**Interfaces:**
- Produces: `ONBOARDING_CATCHUP_KEY = "constructel_bridge/onboarding_catchup_2_0"` (dans `bridge_plugin`).

- [ ] **Step 1: Write the failing tests** :
  - `test_update_no_longer_clears_onboarding_done` : `plugin_version="1.9.0"`, `onboarding_done=True` → après `initGui`, toujours `True`, `plugin_version == "2.0.0"`.
  - `test_catchup_marks_setup_done_once_for_existing_install` : `plugin_version="1.9.0"`, pas de `onboarding_done` → `True` et `ONBOARDING_CATCHUP_KEY` posé ; second démarrage sans effet supplémentaire.
  - `test_fresh_install_still_gets_the_wizard` : aucune `plugin_version` → `onboarding_done` absent, l'assistant s'ouvre à la connexion (via `_on_home("checkin", start_wizard=True)`).
  - `test_new_user_still_gets_the_wizard_even_if_done`.
  - `test_bridge20_i18n.py` : toutes les clés `home.*` / `diag.restart` ajoutées par les tâches 2–9 présentes en FR/EN/PT avec les mêmes `{variables}` ; modules 2.0 (`bridge_presets.py`, `bridge_layer_selection.py`, `bridge_home_load.py`, `bridge_home_checkin.py`, `bridge_home_projects.py`, `bridge_home.py`, `bridge_home_model.py`) sans clé dynamique ; aucune nouvelle orpheline ; `metadata.txt` en `version=2.0.0` avec une entrée de changelog 2.0.0.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** : supprimer `settings.remove("constructel_bridge/onboarding_done")`, ajouter le rattrapage ; retirer les clés devenues orphelines (`home.btn_init`, `home.btn_add`, `home.tile_load`, `home.operator_label`, `home.no_operator`, `home.tile_*`, `init.btn_init`, `init.btn_add`, `init.group_template`, `init.custom_select`, `init.custom_desc`, `init.select_all`, `init.select_none` — vérifier chacune par `grep` avant de retirer) et les sortir de `KEYS_19` ; `metadata.txt` `version=2.0.0` + changelog (FR, style des entrées 1.9.0 : barre latérale, tuiles cumulables, multi-opérateur, communes sans opérateur, Mes presets, setup non rejoué).
- [ ] **Step 4: Run** `python3 -m pytest -q` — Expected: PASS (suite complète).
- [ ] **Step 5: Commit** — `git commit -m "feat(bridge): setup non rejoué après mise à jour, i18n et version 2.0.0"`

- [ ] **Step 6: Recette manuelle (Simon, QGIS Windows réel — hors CI)** : thème clair et sombre ; 1366×768 ; Wyre + Orange zones seules ; « Aucun » + OSIRIS ; preset perso enregistré puis réappliqué ; check-in complet hébergé ; Diagnostic fermé pendant la sonde ; projet enregistré ouvert ; changement de langue fenêtre ouverte ; mise à jour depuis 1.9.0 sans réapparition de l'assistant.
