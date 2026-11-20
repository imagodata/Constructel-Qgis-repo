# -*- coding: utf-8 -*-
"""
Constructel Bridge - logique sans Qt de l'ecran d'accueil (2.0, plan
2026-11-18 tache 3, spec § 6.2, § 6.4, § 6.6).

Ce que l'ecran montre et permet, calcule depuis un instantane de la session
et du projet (HomeSnapshot, construit par le plugin) ; la fenetre l'affiche.
Perimetre d'operateurs multiple, couches communes chargeables sans operateur,
pastille du Check-in. Aucun import qgis / Qt a l'execution : teste sans QGIS
(test_bridge20_home_model.py).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Iterable, Optional, Sequence

from .bridge_projets import NO_CAPABILITIES, ProjetCapabilities, group_projets

if TYPE_CHECKING:  # annotations seulement : modules Qt / reseau
    from .bridge_diagnostic import PluginSummary
    from .bridge_operators import OperatorInfo
    from .bridge_presets import LayerSelection, UserPreset
    from .bridge_project_init import LoadedCounts
    from .bridge_qgis_projects import OpenedQgisProject, QgisProjectRow, SharePlan
    from .bridge_qgis_store import StoreOutcome

# Cles de message (tr litteral dans bridge_home_load, K11).
MESSAGE_CONNECT = "home.connect_to_see"
MESSAGE_COMMON_ONLY = "home.common_only"

# Disponibilite des projets QGIS (2.1, spec § 7.6) : "" = page 2.1 complete.
QGIS_OFFLINE = "offline"
QGIS_NOMINATIVE = "nominative"
QGIS_UNAVAILABLE = "unavailable"

# Visibilite choisie a la creation d'un projet QGIS (spec § 7.7).
VISIBILITY_PRIVATE = "private"
VISIBILITY_PROJET = "projet"
VISIBILITY_PEOPLE = "people"


@dataclass(frozen=True)
class CheckinState:
    """Extensions suivies par le Check-in ; ``None`` = extension absente,
    sans objet (ne compte pas dans la pastille)."""
    plugins: Optional[PluginSummary]
    resource_sharing: Optional[bool]
    filtermate: Optional[bool]


@dataclass(frozen=True)
class HomeSnapshot:
    """Etat lu a l'ouverture et a chaque redessin (aucun acces reseau)."""
    connected: bool
    header: str                  # "login · perimetre", "" hors connexion
    operators: tuple             # OperatorInfo utilisables ; () hors connexion
    counts: LoadedCounts         # couches et fonds deja dans le projet
    labels: dict                 # schema -> libelle (projet, registre, utilisables)
    last_selection: Optional[UserPreset]   # derniere selection du poste ; None a la premiere ouverture
    project_suffix: Optional[bool]   # bridge/operator_suffix du projet, None si absent
    last_suffix: bool            # QgsSettings SUFFIX_SETTINGS_KEY, defaut False
    plugin_summary: Optional[PluginSummary] = None   # extensions recommandees (K3), None si illisible
    plugin_version: str = ""     # tuile Diagnostic (K3)
    project_operators: tuple = ()    # bridge/operator : operateurs de l'identite du projet
    user_presets: tuple = ()     # UserPreset enregistres sur le poste
    checkin: Optional[CheckinState] = None   # pastille du Check-in, None tant que non calcule
    login: str = ""              # profil du Check-in ; "" hors connexion
    email: str = ""              # adresse d'audit de la session, "" si inconnue
    # 2.1 : projets metier et projets QGIS
    projets: tuple = ()          # ProjetInfo visibles (registre lu a la connexion)
    capabilities: ProjetCapabilities = NO_CAPABILITIES
    nominative: bool = False     # session au login nominatif (enregistrement possible)
    opened_qgis_project: Optional[OpenedQgisProject] = None
    operator_code_labels: tuple = ()   # ((code, libelle), ...) de tous les operateurs du registre


@dataclass(frozen=True)
class HomeState:
    load_enabled: bool
    message_key: str             # "" | MESSAGE_CONNECT | MESSAGE_COMMON_ONLY
    operators: tuple             # OperatorInfo proposes (() hors connexion ou sans operateur)
    preselected: tuple           # schemas coches a l'ouverture, dans l'ordre des operateurs
    loaded_marks: frozenset      # schemas utilisables deja charges (✓)
    summary: tuple               # ((libelle, nb couches), ...) pour tout schema charge
    saved_project_enabled: bool
    checkin_badge: int
    # 2.1
    projet_groups: tuple = ()    # ((operateur_code ou None, (ProjetInfo, ...)), ...)
    preselected_projets: tuple = ()   # codes recoches a l'ouverture, ordre d'affichage
    qgis_reason: str = ""        # "" | QGIS_OFFLINE | QGIS_NOMINATIVE | QGIS_UNAVAILABLE


@dataclass(frozen=True)
class SaveRequest:
    """Demande d'enregistrement du projet courant en projet QGIS."""
    name: str
    description: str
    projet_id: Optional[str]
    projet_code: Optional[str]
    visibility: str              # VISIBILITY_*
    people: tuple                # ((login, can_edit), ...)


@dataclass(frozen=True)
class CurrentProjectState:
    title: str
    layer_count: int
    login: str


@dataclass(frozen=True)
class QgisProjectActions:
    """Actions de la page Projets QGIS, fournies par le plugin (connecte)."""
    list_visible: Callable[[], Optional[list]]
    open: Callable[[QgisProjectRow], bool]
    save: Callable[[SaveRequest], StoreOutcome]
    overwrite: Callable[[SaveRequest], StoreOutcome]
    delete: Callable[[str], StoreOutcome]
    shares_list: Callable[[str], Optional[list]]
    apply_shares: Callable[[str, SharePlan], StoreOutcome]
    eligible_users: Callable[[Optional[str], str, Sequence[str]], Optional[list]]
    current_state: Callable[[], CurrentProjectState]


@dataclass(frozen=True)
class HomeActions:
    snapshot: Callable[[], HomeSnapshot]
    connect: Callable[[], None]
    # (operateurs, selection, fonds de plan, styles, suffixe) -> nombre de couches et fonds ajoutes
    load: Callable[[Sequence[OperatorInfo], LayerSelection, set, bool, Optional[bool]], int]
    list_projects: Callable[[], Optional[list]]      # [{name, schema, description, updated}] ; None si illisible
    open_project: Callable[[str, str], bool]         # (schema, nom) -> ouvert
    diagnostic_inputs: Callable[[], tuple]           # (texte d'etat, verifications locales, arguments reseau)
    diagnostic_action: Callable[[object], list]      # Check -> Checks apres l'action
    configure_sharing: Callable[[str], str]          # "resource_sharing" | "filtermate" -> message affiche
    make_wizard: Callable[[object], object]          # parent -> QWizard
    set_language: Callable[[str], None]
    save_presets: Callable[[list], None]             # list[UserPreset]
    qgis: Optional[QgisProjectActions] = None        # 2.1 ; None hors connexion ou doublures 2.0


def checkin_badge(state: Optional[CheckinState]) -> int:
    """Pastille du Check-in : mises a jour connues + extensions recommandees
    non actives + un point par partage (Resource Sharing, FilterMate) a
    configurer. ``None`` (absent) ne compte pas."""
    if state is None:
        return 0
    badge = 0
    if state.plugins is not None:
        badge += state.plugins.updates + (state.plugins.total - state.plugins.active)
    badge += sum(1 for shared in (state.resource_sharing, state.filtermate) if shared is False)
    return badge


def home_state(snapshot: HomeSnapshot) -> HomeState:
    """Etat 2.0 (_home_state_20) complete des champs 2.1 : groupes de projets
    metier (masques hors connexion ou sans registre), projets metier du
    dernier choix encore visibles, disponibilite des projets QGIS."""
    state = _home_state_20(snapshot)
    groups: tuple = ()
    if snapshot.connected and snapshot.capabilities.registry and snapshot.projets:
        usable_codes = [op.code for op in (snapshot.operators or ())]
        groups = tuple(group_projets(snapshot.projets, usable_codes, dict(snapshot.operator_code_labels)))
    preselected_projets: tuple = ()
    last = snapshot.last_selection
    if groups and last is not None:
        wanted = set(last.selection.projet)
        preselected_projets = tuple(p.code for _op, projets in groups for p in projets if p.code in wanted)
    if not snapshot.connected:
        reason = QGIS_OFFLINE
    elif not snapshot.capabilities.qgis_projects:
        reason = QGIS_UNAVAILABLE
    elif not snapshot.nominative:
        reason = QGIS_NOMINATIVE
    else:
        reason = ""
    return dataclasses.replace(state, projet_groups=groups, preselected_projets=preselected_projets,
                               qgis_reason=reason)


def _home_state_20(snapshot: HomeSnapshot) -> HomeState:
    """Regles de l'ecran (spec § 6.2, § 6.6) :

    - hors connexion : ni choix ni chargement (MESSAGE_CONNECT), « Projet
      enregistre » desactive ; une liste d'operateurs perimee n'est jamais
      proposee ;
    - connecte sans operateur utilisable : le chargement reste possible, pour
      les couches communes seules (MESSAGE_COMMON_ONLY) ;
    - preselection : operateurs de la derniere selection encore utilisables
      (dans l'ordre des utilisables, jamais hors de leur perimetre) ; une
      derniere selection sans operateur (communes seules) ne preselectionne
      rien ; premiere ouverture, ou derniers operateurs plus utilisables : le
      premier operateur ;
    - resume : tout schema charge, meme hors scopes (K14) ; jamais
      selectionnable pour autant.
    """
    counts = snapshot.counts
    operators = tuple(snapshot.operators) if snapshot.connected else ()
    usable = [op.schema for op in operators]
    summary = tuple((snapshot.labels.get(schema, schema.capitalize()), count)
                    for schema, count in counts.per_operator.items())
    loaded_marks = frozenset(schema for schema in counts.per_operator if schema in usable)
    badge = checkin_badge(snapshot.checkin)
    if not snapshot.connected:
        return HomeState(False, MESSAGE_CONNECT, (), (), loaded_marks, summary, False, badge)
    if not operators:
        return HomeState(True, MESSAGE_COMMON_ONLY, (), (), loaded_marks, summary, True, badge)
    last = snapshot.last_selection
    if last is None:
        preselected = (usable[0],)
    elif not last.schemas:
        preselected = ()
    else:
        wanted = set(last.schemas)
        preselected = tuple(s for s in usable if s in wanted) or (usable[0],)
    return HomeState(True, "", operators, preselected, loaded_marks, summary, True, badge)


def toggle_operator(current: Sequence[str], schema: str, order: Sequence[str]) -> tuple:
    """Coche / decoche *schema* ; le resultat suit l'ordre *order* (celui des
    operateurs utilisables), un schema hors de *order* est ignore."""
    chosen = set(current)
    chosen.symmetric_difference_update({schema})
    return tuple(s for s in order if s in chosen)


def select_none() -> tuple:
    """« Aucun » : couches communes seules."""
    return ()


def suffix_state(loaded_schemas: Iterable[str], selected_schemas: Iterable[str],
                 project_suffix: Optional[bool], last_suffix: bool) -> tuple:
    """Case « Ajouter le nom de l'operateur aux couches » : (cochee, modifiable).

    Au moins deux schemas entre ceux deja charges et ceux choisis : suffixe
    obligatoire, case cochee et grisee (§ 6.4). Sinon choix libre : celui du
    projet s'il en a fait un, a defaut le dernier choix du poste (§ 9.5)."""
    if len(set(loaded_schemas) | set(selected_schemas)) >= 2:
        return True, False
    if project_suffix is not None:
        return bool(project_suffix), True
    return bool(last_suffix), True
