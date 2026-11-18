# -*- coding: utf-8 -*-
"""
Constructel Bridge - tuiles, selection de couches et presets, sans Qt
(2.0, plan 2026-11-18 tache 1, spec § 6.2, § 8.1).

Fondation de l'accueil v2 : quelles couches (cles de LAYER_CATALOG) recouvre
chaque tuile, ce qu'une selection de tuiles donne par operateur et en commun,
l'etat d'une tuile compte tenu de ce qui est deja charge, et les presets
utilisateur (QgsSettings, serialises en JSON). Aucun import qgis / Qt a
l'execution : teste sans QGIS (test_bridge20_presets.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

from .bridge_operators import is_safe_schema

# Tuiles lues dans le schema de chaque operateur, puis tuiles communes
# (chargees une fois, dans « Commun »).
OPERATOR_TILES = ("zones", "genie_civil", "cables", "demand_points")
COMMON_TILES = ("chantier", "osiris", "cadastre", "urbanisme")

TILE_LAYERS = {
    "zones": ("zone_mro", "zone_pop", "zone_distribution", "zone_drop"),
    "genie_civil": ("structures", "ducts", "trench_segments", "duct_progress", "subducts"),
    "cables": ("cables",),
    "demand_points": ("demand_points",),
    "chantier": ("interventions", "incidents", "permis_voirie", "planning_facades",
                 "plaintes", "interventions_chantier", "synergies"),
    "osiris": ("osiris_frozen", "osiris_worksites", "osiris_autorises", "osiris_phases",
               "osiris_hypercoord", "osiris_deviations", "osiris_events"),
    "cadastre": ("wfs_buildings", "wfs_parcels", "wfs_blocks", "wfs_municipalities"),
    "urbanisme": ("wfs_protection", "wfs_heritage"),
}

# Couches « expert » : dans une tuile seulement sur demande (expert=True).
EXPERT_KEYS = frozenset({"subducts", "planning_facades"})
# Toujours chargee, quelle que soit la selection (listes de formulaires).
ALWAYS_KEYS = frozenset({"v_form_lists"})
# Chargee avec chaque operateur du plan, sans tuile ni compte dans la selection.
OPERATOR_AUTO_KEYS = frozenset({"docs_elements"})

LAST_SELECTION_KEY = "constructel_bridge/last_selection"
USER_PRESETS_KEY = "constructel_bridge/user_presets"

STATE_ON = "on"
STATE_OFF = "off"
STATE_PARTIAL = "partial"
STATE_DONE = "done"
STATE_DISABLED = "disabled"


def tile_keys(tile: str, expert: bool = False) -> frozenset:
    """Cles de couches d'une tuile ; les couches expert n'y sont qu'avec
    ``expert=True``."""
    keys = TILE_LAYERS[tile]
    return frozenset(keys if expert else (k for k in keys if k not in EXPERT_KEYS))


@dataclass(frozen=True)
class LayerSelection:
    """Couches a charger : cles operateur par schema, cles communes. Normalise
    a la construction (frozensets, schemas sans couche ecartes) pour que deux
    selections equivalentes soient egales ; l'ordre des schemas est conserve
    (le premier recoit les couches communes dans load_plan)."""
    per_operator: Mapping[str, frozenset]
    common: frozenset

    def __post_init__(self):
        per_operator = {s: frozenset(keys) for s, keys in dict(self.per_operator).items() if keys}
        object.__setattr__(self, "per_operator", per_operator)
        object.__setattr__(self, "common", frozenset(self.common))

    def is_empty(self) -> bool:
        return not self.per_operator and not self.common

    def layer_count(self) -> int:
        """Couches choisies, hors ALWAYS_KEYS / OPERATOR_AUTO_KEYS (jamais
        montrees a l'utilisateur comme un choix)."""
        hidden = ALWAYS_KEYS | OPERATOR_AUTO_KEYS
        return (sum(len(keys - hidden) for keys in self.per_operator.values())
                + len(self.common - hidden))

    def load_plan(self) -> list:
        """[(schema ou None, cles)] dans l'ordre de chargement. Les couches
        communes suivent le premier operateur ; sans operateur elles forment
        l'entree ``None``. ALWAYS_KEYS et OPERATOR_AUTO_KEYS accompagnent
        chaque entree operateur (ALWAYS_KEYS seul pour ``None``)."""
        if not self.per_operator:
            return [(None, self.common | ALWAYS_KEYS)] if self.common else []
        plan = []
        for index, (schema, keys) in enumerate(self.per_operator.items()):
            entry = keys | ALWAYS_KEYS | OPERATOR_AUTO_KEYS
            if index == 0:
                entry |= self.common
            plan.append((schema, entry))
        return plan


def _loaded(existing: Mapping[Optional[str], set], schema: Optional[str]) -> set:
    return set(existing.get(schema) or ())


def selection_from_tiles(tiles: Iterable[str], schemas: Sequence[str],
                         existing: Mapping[Optional[str], set]) -> LayerSelection:
    """Selection issue des tuiles cochees. ``existing[None]`` : cles communes
    deja chargees ; ``existing[schema]`` : cles operateur deja chargees (elles
    sont exclues)."""
    tiles = set(tiles)
    operator_keys = frozenset().union(*(tile_keys(t) for t in OPERATOR_TILES if t in tiles))
    common_keys = frozenset().union(*(tile_keys(t) for t in COMMON_TILES if t in tiles))
    per_operator = {schema: operator_keys - _loaded(existing, schema) for schema in schemas}
    return LayerSelection(per_operator, common_keys - _loaded(existing, None))


def tile_state(tile: str, selection: LayerSelection, schemas: Sequence[str],
               existing: Mapping[Optional[str], set]) -> str:
    """Etat d'une tuile : ``done`` (tout est deja charge, pour chaque
    operateur le cas echeant), ``on`` / ``partial`` / ``off`` (part des
    couches restant a charger qui est selectionnee), ``disabled`` (tuile
    operateur sans operateur)."""
    keys = tile_keys(tile)
    if tile in OPERATOR_TILES:
        if not schemas:
            return STATE_DISABLED
        targets = [(keys - _loaded(existing, s), selection.per_operator.get(s, frozenset())) for s in schemas]
    else:
        targets = [(keys - _loaded(existing, None), selection.common)]
    todo = sum(len(remaining) for remaining, _ in targets)
    if not todo:
        return STATE_DONE
    chosen = sum(len(remaining & picked) for remaining, picked in targets)
    if chosen == todo:
        return STATE_ON
    return STATE_PARTIAL if chosen else STATE_OFF


@dataclass(frozen=True)
class UserPreset:
    """Preset nomme : operateurs et selection memorises."""
    name: str
    schemas: tuple
    selection: LayerSelection


def presets_to_json(presets: Sequence[UserPreset]) -> str:
    return json.dumps([
        {"name": p.name,
         "schemas": list(p.schemas),
         "per_operator": {s: sorted(keys) for s, keys in p.selection.per_operator.items()},
         "common": sorted(p.selection.common)}
        for p in presets
    ], ensure_ascii=False)


def _str_list(value) -> Optional[list]:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    return None


def _preset_from_entry(entry) -> Optional[UserPreset]:
    """Un preset lu du JSON, None si l'entree est inexploitable (nom vide,
    types errones, schema qui n'est pas un identifiant sur)."""
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    schemas = _str_list(entry.get("schemas"))
    common = _str_list(entry.get("common", []))
    per_operator = entry.get("per_operator", {})
    if not isinstance(name, str) or not name or schemas is None or common is None:
        return None
    if not isinstance(per_operator, dict) or not all(is_safe_schema(s) for s in list(per_operator) + schemas):
        return None
    parsed = {}
    for schema, keys in per_operator.items():
        keys = _str_list(keys)
        if keys is None:
            return None
        parsed[schema] = frozenset(keys)
    return UserPreset(name, tuple(schemas), LayerSelection(parsed, frozenset(common)))


def presets_from_json(raw) -> list:
    """Presets lus de QgsSettings ; entree illisible -> [], entree isolee
    inexploitable ignoree."""
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return []
    if not isinstance(raw, str):
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    return [p for p in (_preset_from_entry(e) for e in data) if p is not None]


def restrict_preset(preset: UserPreset, usable: Iterable[str]) -> UserPreset:
    """Preset limite aux operateurs utilisables (perimetre de la session) ; la
    part commune est conservee."""
    usable = set(usable)
    per_operator = {s: keys for s, keys in preset.selection.per_operator.items() if s in usable}
    return UserPreset(preset.name, tuple(s for s in preset.schemas if s in usable),
                      LayerSelection(per_operator, preset.selection.common))
