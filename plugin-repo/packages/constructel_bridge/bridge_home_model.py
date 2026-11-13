# -*- coding: utf-8 -*-
"""
Constructel Bridge - logique sans Qt de l'ecran d'accueil (1.9.0, plan
2026-11-12 tache 9, spec § 6.1, § 6.2, § 6.4, § 6.6).

Ce que l'ecran montre et permet, calcule depuis un instantane de la session
et du projet (HomeSnapshot, construit par le plugin) ; bridge_home.py le
dessine. Aucun import qgis / Qt a l'execution : teste sans QGIS
(test_bridge19_home.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable, Optional

from .bridge_operators import OperatorInfo, preselect_operator

if TYPE_CHECKING:  # annotations seulement : modules Qt / reseau
    from .bridge_diagnostic import PluginSummary
    from .bridge_project_init import LoadedCounts

SELECTOR_NONE = "none"        # aucun choix (hors connexion, aucun operateur)
SELECTOR_LABEL = "label"      # un seul operateur : affiche en texte
SELECTOR_BUTTONS = "buttons"  # plusieurs : boutons exclusifs
MODE_INIT = "init"
MODE_ADD = "add"
# Cles de message (tr litteral dans bridge_home, K11).
MESSAGE_CONNECT = "home.connect_to_see"
MESSAGE_NO_OPERATOR = "home.no_operator"


@dataclass(frozen=True)
class HomeSnapshot:
    """Etat lu a l'ouverture et a chaque redessin (aucun acces reseau)."""
    connected: bool
    header: str                  # "login · perimetre", "" hors connexion
    operators: tuple             # OperatorInfo utilisables ; () hors connexion
    counts: LoadedCounts         # couches et fonds deja dans le projet
    labels: dict                 # schema -> libelle (projet, registre, utilisables)
    last_schema: str             # QgsSettings LAST_OPERATOR_KEY
    project_suffix: Optional[bool]   # bridge/operator_suffix du projet, None si absent
    last_suffix: bool            # QgsSettings SUFFIX_SETTINGS_KEY, defaut False
    plugin_summary: Optional[PluginSummary] = None   # tuile Check-in (K3), None si illisible
    plugin_version: str = ""     # tuile Diagnostic (K3)
    project_operators: tuple = ()    # bridge/operator : operateurs de l'identite du projet


@dataclass(frozen=True)
class HomeState:
    selector: str                # SELECTOR_*
    load_enabled: bool
    message_key: str             # "" | MESSAGE_CONNECT | MESSAGE_NO_OPERATOR
    preselected: Optional[OperatorInfo]
    mode: str                    # MODE_INIT | MODE_ADD
    loaded_marks: frozenset      # schemas utilisables deja charges (✓ sur le bouton)
    summary: tuple               # ((libelle, nb couches), ...) pour tout schema charge
    saved_project_enabled: bool


@dataclass(frozen=True)
class HomeActions:
    snapshot: Callable[[], HomeSnapshot]
    connect: Callable[[], None]
    load: Callable[[OperatorInfo, set, set, bool, bool], int]   # (operateur, couches, fonds, styles, suffixe)
    open_saved_project: Callable[[], None]
    checkin: Callable[[], None]
    diagnostic: Callable[[], None]
    change_language: Callable[[], None]


def home_state(snapshot: HomeSnapshot) -> HomeState:
    """Regles de l'ecran (spec § 6.2, § 6.6) :

    - hors connexion : ni choix ni chargement (MESSAGE_CONNECT), « Projet
      enregistre » desactive ; une liste d'operateurs perimee n'est jamais
      proposee ;
    - connecte sans operateur utilisable : ni choix ni chargement
      (MESSAGE_NO_OPERATOR) ;
    - un operateur : texte ; plusieurs : boutons, tous selectionnables, ✓ sur
      ceux deja charges (§ 9.2) ;
    - presselection : dernier operateur du poste s'il est utilisable, sinon
      le premier ;
    - mode ajout des qu'une couche operateur ou commune est dans l'arbre ;
    - resume : tout schema charge, meme hors scopes (K14) ; jamais
      selectionnable pour autant.
    """
    counts = snapshot.counts
    operators = tuple(snapshot.operators) if snapshot.connected else ()
    usable = {op.schema for op in operators}
    mode = MODE_ADD if (counts.per_operator or counts.common) else MODE_INIT
    summary = tuple((snapshot.labels.get(schema, schema.capitalize()), count)
                    for schema, count in counts.per_operator.items())
    loaded_marks = frozenset(schema for schema in counts.per_operator if schema in usable)
    if not snapshot.connected:
        return HomeState(SELECTOR_NONE, False, MESSAGE_CONNECT, None, mode, loaded_marks, summary, False)
    if not operators:
        return HomeState(SELECTOR_NONE, False, MESSAGE_NO_OPERATOR, None, mode, loaded_marks, summary, True)
    selector = SELECTOR_LABEL if len(operators) == 1 else SELECTOR_BUTTONS
    preselected = preselect_operator(operators, snapshot.last_schema)
    return HomeState(selector, True, "", preselected, mode, loaded_marks, summary, True)


def suffix_state(loaded_schemas: Iterable[str], selected_schema: str, project_suffix: Optional[bool],
                 last_suffix: bool) -> tuple[bool, bool]:
    """Case « Ajouter le nom de l'operateur aux couches » : (cochee, modifiable).

    Au moins deux schemas entre ceux deja charges et celui choisi : suffixe
    obligatoire, case cochee et grisee (§ 6.4). Sinon choix libre : celui du
    projet s'il en a fait un, a defaut le dernier choix du poste (§ 9.5)."""
    if len(set(loaded_schemas) | {selected_schema}) >= 2:
        return True, False
    if project_suffix is not None:
        return bool(project_suffix), True
    return bool(last_suffix), True
