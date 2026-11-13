# -*- coding: utf-8 -*-
"""
Constructel Bridge — Initialisation de projet QGIS WYRE FTTH.

Widget de selection de couches avec templates pre-configures (grande tuile
de l'ecran d'accueil, Bridge 1.9), puis chargement des couches, styles,
relations et basemaps.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtXml import QDomDocument
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsDataSourceUri,
    QgsMessageLog,
    QgsProject,
    QgsRasterLayer,
    QgsRelation,
    QgsVectorLayer,
)

from .bridge_operators import (
    COMMON_GROUPS,
    COMMON_ROOT,
    GROUP_KIND_PROPERTY,
    GROUP_SCHEMA_PROPERTY,
    OPERATOR_GROUPS,
    OPERATOR_KEYS,
    OPERATOR_TABLES,
    OPERATOR_TEMPLATE_SCHEMA,
    OperatorInfo,
    base_key,
    canonical_group,
    format_operator_labels,
    format_project_operators,
    is_safe_schema,
    layer_key,
    parse_operator_labels,
    parse_project_operators,
    relation_id,
    style_sources,
)
from .i18n import get_language, tr
from .i18n.layer_translations import GROUP_NAMES

TAG = "Constructel Bridge"

# Version schema/projet — stockee comme variable projet QGIS pour detecter
# qu'un projet a ete initialise par ce plugin. Les operateurs charges sont
# dans bridge/operator (Bridge 1.9 : liste, voir stamp_project).
WYRE_PROJECT_VERSION = "4.0.0"


def _plugin_version() -> str:
    """Lit la version du plugin depuis metadata.txt."""
    meta = os.path.join(os.path.dirname(__file__), "metadata.txt")
    try:
        with open(meta) as f:
            for line in f:
                if line.startswith("version="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


def is_bridge_project() -> bool:
    """Detecte si le projet QGIS courant a ete initialise par le plugin Bridge.

    Retourne True si ``bridge_operator`` ou ``bridge_version`` est renseignee
    (via writeEntry ou customVariables).
    """
    project = QgsProject.instance()
    # Lecture rapide via writeEntry
    op, _ = project.readEntry("bridge", "operator", "")
    ver, _ = project.readEntry("bridge", "version", "")
    if op or ver:
        return True
    # Fallback: variables projet QGIS (accessibles via @bridge_operator / @bridge_version)
    scope = project.customVariables()
    return bool(scope.get("bridge_operator", "") or scope.get("bridge_version", ""))


def _read_suffix(raw, found: bool) -> bool | None:
    """bridge/operator_suffix : "1" -> True, "0" -> False ; None si l'entree
    est absente ou illisible (le projet n'a pas encore fait de choix)."""
    value = str(raw).strip().lower() if found else ""
    if value in ("1", "true"):
        return True
    if value in ("0", "false"):
        return False
    return None


def get_bridge_info() -> dict:
    """Retourne les metadonnees Bridge du projet courant.

    Cles :
      - operator : chaine brute de bridge/operator (ou @bridge_operator),
        "wyre,orange" ; "wyre" pour un projet 1.8 ;
      - operators : schemas des operateurs dans l'ordre de chargement ;
      - operator_labels : schema -> libelle ({} pour un projet 1.8) ;
      - operator_suffix : True / False, None si l'entree est absente ;
      - version, plugin.
    Valeurs vides si absentes.
    """
    project = QgsProject.instance()
    scope = project.customVariables()
    op, _ = project.readEntry("bridge", "operator", "")
    ver, _ = project.readEntry("bridge", "version", "")
    labels, _ = project.readEntry("bridge", "operator_labels", "")
    suffix, has_suffix = project.readEntry("bridge", "operator_suffix", "")
    operator = op or scope.get("bridge_operator", "")
    return {
        "operator": operator,
        "operators": parse_project_operators(operator),
        "operator_labels": parse_operator_labels(labels),
        "operator_suffix": _read_suffix(suffix, has_suffix),
        "version": ver or scope.get("bridge_version", ""),
        "plugin": scope.get("bridge_plugin", ""),
    }


def stamp_project(operator: OperatorInfo, suffix: bool | None = None) -> None:
    """Ecrit l'identite Bridge du projet courant (spec § 7, plan D5).

    - bridge/operator et @bridge_operator (meme chaine) : schemas des
      operateurs charges, dans l'ordre de chargement ("wyre,orange") ;
      *operator* est ajoute s'il manque (un projet 1.8 "wyre" se relit
      ["wyre"]) ;
    - bridge/operator_labels : JSON schema -> libelle, fusionne ;
    - bridge/operator_suffix : "1" / "0", seulement si *suffix* n'est pas
      None (sinon le choix deja enregistre est garde) ;
    - bridge/version, @bridge_version, @bridge_plugin.

    init_project l'appelle juste AVANT le premier addMapLayer d'une couche
    operateur de *operator* (le suffixe des noms de couches, tache 3, est
    pose sur layersAdded et lit cette identite), ou sur une couche operateur
    deja presente ; jamais si aucune n'est ajoutee ni presente (T2-c3).
    """
    project = QgsProject.instance()
    from qgis.core import QgsExpressionContextUtils
    info = get_bridge_info()
    operators = info["operators"]
    if operator.schema not in operators:
        operators.append(operator.schema)
    labels = dict(info["operator_labels"])
    labels[operator.schema] = operator.label
    operators_text = format_project_operators(operators)
    # writeEntry pour une lecture rapide sans contexte d'expression
    project.writeEntry("bridge", "operator", operators_text)
    project.writeEntry("bridge", "operator_labels", format_operator_labels(labels))
    if suffix is not None:
        project.writeEntry("bridge", "operator_suffix", "1" if suffix else "0")
    # Variable projet QGIS (expressions : @bridge_operator)
    QgsExpressionContextUtils.setProjectVariable(project, "bridge_operator", operators_text)
    _stamp_version(project)


def _stamp_version(project) -> None:
    """bridge/version, @bridge_version et @bridge_plugin : ecrits a chaque
    chargement, avec ou sans couche operateur (is_bridge_project)."""
    from qgis.core import QgsExpressionContextUtils
    project.writeEntry("bridge", "version", WYRE_PROJECT_VERSION)
    QgsExpressionContextUtils.setProjectVariable(project, "bridge_version", WYRE_PROJECT_VERSION)
    QgsExpressionContextUtils.setProjectVariable(project, "bridge_plugin", _plugin_version())


# =====================================================================
# CATALOGUE COMPLET DES COUCHES
# (key, group, schema, table, geom_col, pk, label_fr)
# =====================================================================

LAYER_CATALOG = [
    # -- Demand Points ----------------------------------------------------
    ("demand_points",      "Demand Points",   "wyre", "demand_points",      "geom", "id",  "Points de demande"),

    # -- Infrastructure ---------------------------------------------------
    ("structures",         "Infrastructure",  "wyre", "structures",         "geom", "id",  "Structures"),
    ("cables",             "Infrastructure",  "wyre", "cables",             "geom", "id",  "Cables"),
    ("subducts",           "Infrastructure",  "wyre", "subducts",           "geom", "id",  "Sous-fourreaux"),
    ("ducts",              "Infrastructure",  "wyre", "ducts",              "geom", "id",  "Conduites"),
    # Segments de tranchee (migration Farois 475) : calcules depuis les
    # fourreaux par ref.fn_trench_segments_rebuild ; seuls status et
    # completion_date sont modifiables (droits colonne de ftth_editor).
    ("trench_segments",    "Infrastructure",  "wyre", "trench_segments",    "geom", "id",  "Segments de tranchee"),
    # Avancement des fourreaux (migration Farois 480) : vue wyre.v_duct_progress
    # (ducts + duct_progress, calculee par ref.fn_duct_progress_refresh), en
    # lecture seule : vue non modifiable, SELECT seul pour ftth_editor.
    # Cle "duct_progress" comme dans Farois ; i18n indexee par la table.
    ("duct_progress",      "Infrastructure",  "wyre", "v_duct_progress",    "geom", "id",  "Avancement des fourreaux"),

    # -- Zones ------------------------------------------------------------
    ("zone_drop",          "Zones",           "wyre", "zone_drop",          "geom", "id",  "Zones Drop"),
    ("zone_distribution",  "Zones",           "wyre", "zone_distribution",  "geom", "id",  "Zones Distribution"),
    ("zone_pop",           "Zones",           "wyre", "zone_pop",           "geom", "id",  "Zones POP"),
    ("zone_mro",           "Zones",           "wyre", "zone_mro",           "geom", "id",  "Zones MRO"),


    # -- Chantier ---------------------------------------------------------
    ("interventions",      "Chantier",        "chantier", "interventions",      "geom", "id",  "Interventions"),
    ("incidents",          "Chantier",        "chantier", "incidents",          "geom", "id",  "Incidents"),
    ("permis_voirie",      "Chantier",        "chantier", "permis_voirie",      "geom", "id",  "Permis de voirie"),
    ("planning_facades",   "Chantier",        "chantier", "planning_facades",   None,   "id",  "Planning facades"),
    ("plaintes",           "Chantier",        "chantier", "plaintes",           "geom", "id",  "Plaintes"),
    ("interventions_chantier", "Chantier",    "chantier", "interventions_chantier", "geom", "id", "Interventions chantier"),
    ("synergies",          "Chantier",        "chantier", "synergies",          "geom", "id",  "Synergies"),

    # -- OSIRIS -----------------------------------------------------------
    ("osiris_frozen",      "OSIRIS",          "osiris", "frozen_zones",            "geom", "ogc_fid", "Zones gelees"),
    ("osiris_worksites",   "OSIRIS",          "osiris", "worksites",               "geom", "ogc_fid", "Chantiers OSIRIS"),
    ("osiris_autorises",   "OSIRIS",          "osiris", "chantiers_autorises",     "geom", "ogc_fid", "Chantiers autorises"),
    ("osiris_phases",      "OSIRIS",          "osiris", "phases_in_progress",      "geom", "ogc_fid", "Phases en cours"),
    ("osiris_hypercoord",  "OSIRIS",          "osiris", "hypercoordination_zones", "geom", "ogc_fid", "Hypercoordination"),
    ("osiris_deviations",  "OSIRIS",          "osiris", "deviations",              "geom", "ogc_fid", "Deviations"),
    ("osiris_events",      "OSIRIS",          "osiris", "events",                  "geom", "ogc_fid", "Evenements"),

    # -- Cadastre UrbIS (WFS) ------------------------------------------------
    ("wfs_buildings",      "Cadastre UrbIS",  "wfs",  "urbisvector:Buildings",        "geom", None, "Batiments"),
    ("wfs_parcels",        "Cadastre UrbIS",  "wfs",  "urbisvector:CadastralParcels", "geom", None, "Parcelles cadastrales"),
    ("wfs_blocks",         "Cadastre UrbIS",  "wfs",  "urbisvector:Blocks",           "geom", None, "Ilots"),
    ("wfs_municipalities", "Cadastre UrbIS",  "wfs",  "urbisvector:Municipalities",   "geom", None, "Municipalites"),

    # -- Urbanisme Brussels (WFS) --------------------------------------------
    ("wfs_protection",     "Urbanisme",       "wfs",  "URBAN_DCH_IBH:Protection_area", "geom", None, "Zones protegees"),
    ("wfs_heritage",       "Urbanisme",       "wfs",  "URBAN_DCH_IBH:Heritage",        "geom", None, "Patrimoine"),

    # -- Référence (visible dans groupe Référence, en bas après basemaps) --
    ("docs_elements",      "Référence",       "docs",  "v_element_documents_list", None, "link_id", "Documents elements"),
    ("v_form_lists",       "Référence",       "ref",   "v_form_lists",        None,  "rid", "Listes formulaires"),
]

# Cles des couches WFS (chargees via WFS, pas PostgreSQL)
WFS_KEYS = {
    "wfs_municipalities", "wfs_blocks", "wfs_parcels", "wfs_buildings",
    "wfs_protection", "wfs_heritage",
}


def catalog_for(schema: str) -> list[tuple]:
    """LAYER_CATALOG lu dans le schema d'un operateur (spec § 6.3) : les
    entrees des groupes operateur (OPERATOR_GROUPS) prennent *schema*, les
    entrees communes sont inchangees. LAYER_CATALOG garde le schema modele
    OPERATOR_TEMPLATE_SCHEMA (plan D1)."""
    if not is_safe_schema(schema):
        raise ValueError(f"Schema operateur invalide : {schema!r}")
    return [
        (entry[0], entry[1], schema) + tuple(entry[3:]) if entry[1] in OPERATOR_GROUPS else entry
        for entry in LAYER_CATALOG
    ]


# Mapping key → fichier QML embarque dans le plugin (dossier styles/)
EMBEDDED_STYLES = {
    # Infra
    "demand_points":    "demand_points.qml",
    "structures":       "structures.qml",
    "cables":           "cables.qml",
    "subducts":         "subducts.qml",
    "ducts":            "ducts.qml",
    "trench_segments":  "trench_segments.qml",
    "duct_progress":    "duct_progress.qml",
    # Zones
    "zone_drop":        "zone_drop.qml",
    "zone_distribution":"zone_distribution.qml",
    "zone_pop":         "zone_pop.qml",
    "zone_mro":         "zone_mro.qml",
    # OSIRIS
    "osiris_frozen":    "osiris_frozen_zones.qml",
    "osiris_worksites": "osiris_worksites.qml",
    "osiris_autorises": "osiris_chantiers_autorises.qml",
    "osiris_phases":    "osiris_phases_in_progress.qml",
    "osiris_hypercoord":"osiris_hypercoordination.qml",
    "osiris_deviations":"osiris_deviations.qml",
    "osiris_events":    "osiris_events.qml",
    # Cadastre UrbIS WFS
    "wfs_municipalities":"wfs_municipalities.qml",
    "wfs_blocks":       "wfs_blocks.qml",
    "wfs_parcels":      "wfs_parcels.qml",
    "wfs_buildings":    "wfs_buildings.qml",
    # Urbanisme WFS
    "wfs_protection":   "wfs_protection.qml",
    "wfs_heritage":     "wfs_heritage.qml",
    # Documents
    "docs_elements":    "docs_v_element_documents_list.qml",
}


# =====================================================================
# TEMPLATES — presets de selection
# =====================================================================

# Couches infra de base (reutilise dans les templates)
# NB: subducts est volontairement exclu — decoche par defaut dans tous les profils
# NB: trench_segments est cochee dans tous les profils (demande Simon 04/11)
# NB: duct_progress, suivi de construction superpose aux conduites, n'est
#     cochee que dans les profils "Infrastructure + Chantier" et "Projet complet"
_INFRA_BASE = {
    "zone_mro", "zone_pop", "zone_distribution", "zone_drop",
    "structures", "ducts", "cables", "trench_segments",
    "demand_points", "topo_violations",
    "docs_elements", "v_form_lists",
}

TEMPLATES = {
    "infra": {
        "label": "Infrastructure",
        "description": "Couches infra : zones, structures, cables, conduites, segments de tranchee, DP, topologie",
        "layers": _INFRA_BASE,
        "basemap": True,
    },
    "infra_cadastre": {
        "label": "Infrastructure + Cadastre",
        "description": "Infra complet + parcelles cadastrales, batiments, municipalites et ilots UrbIS",
        "layers": _INFRA_BASE | {
            "wfs_municipalities", "wfs_blocks", "wfs_parcels", "wfs_buildings",
        },
        "basemap": True,
    },
    "infra_urbanisme": {
        "label": "Infrastructure + Urbanisme",
        "description": "Infra complet + cadastre + zones protegees et patrimoine Brussels",
        "layers": _INFRA_BASE | {
            "wfs_municipalities", "wfs_blocks", "wfs_parcels", "wfs_buildings",
            "wfs_protection", "wfs_heritage",
        },
        "basemap": True,
    },
    "infra_chantier": {
        "label": "Infrastructure + Chantier",
        "description": "Infra complet + couches chantier (interventions, permis, incidents, synergies, segments de tranchee, avancement des fourreaux)",
        "layers": _INFRA_BASE | {
            "interventions", "incidents", "permis_voirie", "plaintes",
            "interventions_chantier", "synergies", "planning_facades",
            "trench_segments", "duct_progress",
        },
        "basemap": True,
    },
    "infra_osiris": {
        "label": "Infrastructure + OSIRIS",
        "description": "Infra complet + couches OSIRIS Brussels (zones gelees, chantiers, coordination)",
        "layers": _INFRA_BASE | {
            "osiris_frozen", "osiris_worksites", "osiris_autorises",
            "osiris_phases", "osiris_hypercoord", "osiris_deviations", "osiris_events",
        },
        "basemap": True,
    },
    "complet": {
        "label": "Projet complet",
        "description": "Toutes les couches : infra + chantier + OSIRIS + cadastre + urbanisme",
        "layers": {k for k, *_ in LAYER_CATALOG} - {"subducts"},
        "basemap": True,
    },
}


# =====================================================================
# RELATIONS QGIS (parent_key, child_key, fk_field, rel_name)
# Les keys correspondent aux cles du LAYER_CATALOG
# =====================================================================

RELATION_DEFS = [
    # Zone hierarchy
    ("zone_mro",       "zone_pop",           "zone_mro_id",          "zone_pop_to_mro"),
    ("zone_pop",       "zone_distribution",  "zone_pop_id",          "zone_dist_to_pop"),
    ("zone_pop",       "zone_drop",          "zone_pop_id",          "zone_drop_to_pop"),
    ("zone_distribution", "zone_drop",       "zone_distribution_id", "zone_drop_to_dist"),

    # Infra → Zones
    ("zone_pop",       "structures",         "zone_pop_id",          "structures_to_pop"),
    ("zone_pop",       "cables",             "zone_pop_id",          "cables_to_pop"),
    ("zone_pop",       "ducts",              "zone_pop_id",          "ducts_to_pop"),
    ("zone_pop",       "subducts",           "zone_pop_id",          "subducts_to_pop"),
    ("zone_pop",       "trench_segments",    "zone_pop_id",          "trench_segments_to_pop"),
    ("zone_pop",       "duct_progress",      "zone_pop_id",          "duct_progress_to_pop"),
    ("zone_pop",       "demand_points",      "zone_pop_id",          "dp_to_pop"),
    ("zone_drop",      "demand_points",      "zone_drop_id",         "dp_to_drop"),
    ("zone_distribution", "demand_points",   "zone_distribution_id", "dp_to_dist"),

    # Ducts → Subducts
    ("ducts",          "subducts",           "duct_id",              "subducts_to_duct"),

    # Cables ↔ Structures (start/end points)
    ("structures",     "cables",             "start_point_id",       "rel_cables_from_start"),
    ("structures",     "cables",             "end_point_id",         "rel_cables_from_end"),

    # Subducts → Structures
    ("structures",     "subducts",           "start_structure_id",   "rel_subducts_from_start"),
    ("structures",     "subducts",           "end_structure_id",     "rel_subducts_from_end"),

    # Subducts → Cables
    ("cables",         "subducts",           "cable_id",             "rel_subducts_to_cable"),

    # Documents → Infrastructure (relation editors dans onglet Documentos)
    ("structures",     "docs_elements",      "element_id",           "docs_element_structure"),
    ("cables",         "docs_elements",      "element_id",           "docs_element_cable"),
    ("ducts",          "docs_elements",      "element_id",           "docs_element_duct"),
    ("demand_points",  "docs_elements",      "element_id",           "docs_element_demand_point"),
    ("zone_pop",       "docs_elements",      "element_id",           "docs_element_zone_pop"),
    ("zone_mro",       "docs_elements",      "element_id",           "docs_element_zone_mro"),

    # Chantier → Zones
    ("zone_pop",       "permis_voirie",      "zone_pop_id",          "permis_to_pop"),
    ("zone_pop",       "interventions_chantier", "zone_pop_id",      "ic_to_pop"),

]


# =====================================================================
# BASEMAPS & OVERLAYS
# =====================================================================

BASEMAPS = [
    # -- UrbIS Brussels WMTS --
    {
        "key": "urbis_fr",
        "name": "UrbIS FR",
        "group": "UrbIS Brussels",
        "source": (
            "crs=EPSG:31370&dpiMode=7&featureCount=10&format=image/png"
            "&layers=urbisFR&styles=&tileMatrixSet=EPSG:31370&tilePixelRatio=0"
            "&url=https://geoservices-urbis.irisnet.be/geowebcache/service/wmts"
            "?service%3DWMTS%26request%3DGetCapabilities%26version%3D1.0.0"
        ),
        "provider": "wms",
        "default": True,
    },
    {
        "key": "urbis_fr_gray",
        "name": "UrbIS FR Gray",
        "group": "UrbIS Brussels",
        "source": (
            "crs=EPSG:31370&dpiMode=7&featureCount=10&format=image/png"
            "&layers=urbisFRGray&styles=&tileMatrixSet=EPSG:31370&tilePixelRatio=0"
            "&url=https://geoservices-urbis.irisnet.be/geowebcache/service/wmts"
            "?service%3DWMTS%26request%3DGetCapabilities%26version%3D1.0.0"
        ),
        "provider": "wms",
        "default": True,
    },
    # -- OpenStreetMap --
    {
        "key": "osm",
        "name": "OpenStreetMap",
        "group": "OpenStreetMap",
        "source": (
            "type=xyz"
            "&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            "&zmax=19&zmin=0"
        ),
        "provider": "wms",
        "default": True,
    },
    # -- Google --
    {
        "key": "google_satellite",
        "name": "Google Satellite",
        "group": "Google",
        "source": (
            "type=xyz"
            "&url=https://mt1.google.com/vt/lyrs%3Ds%26x%3D{x}%26y%3D{y}%26z%3D{z}"
            "&zmax=20&zmin=0"
        ),
        "provider": "wms",
        "default": False,
    },
    {
        "key": "google_hybrid",
        "name": "Google Hybrid",
        "group": "Google",
        "source": (
            "type=xyz"
            "&url=https://mt1.google.com/vt/lyrs%3Dy%26x%3D{x}%26y%3D{y}%26z%3D{z}"
            "&zmax=20&zmin=0"
        ),
        "provider": "wms",
        "default": False,
    },
    {
        "key": "google_roads",
        "name": "Google Roads",
        "group": "Google",
        "source": (
            "type=xyz"
            "&url=https://mt1.google.com/vt/lyrs%3Dm%26x%3D{x}%26y%3D{y}%26z%3D{z}"
            "&zmax=20&zmin=0"
        ),
        "provider": "wms",
        "default": False,
    },
    # -- CartoDB --
    {
        "key": "carto_positron",
        "name": "CartoDB Positron",
        "group": "CartoDB",
        "source": (
            "type=xyz"
            "&url=https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"
            "&zmax=19&zmin=0"
        ),
        "provider": "wms",
        "default": False,
    },
    {
        "key": "carto_dark",
        "name": "CartoDB Dark Matter",
        "group": "CartoDB",
        "source": (
            "type=xyz"
            "&url=https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"
            "&zmax=19&zmin=0"
        ),
        "provider": "wms",
        "default": False,
    },
    # -- Google Streetview Coverage --
    {
        "key": "streetview",
        "name": "Streetview Coverage",
        "group": "Google",
        "source": (
            "type=xyz"
            "&url=https://mts2.google.com/mapslt"
            "?lyrs%3Dsvv%26x%3D{x}%26y%3D{y}%26z%3D{z}"
            "%26w%3D256%26h%3D256%26hl%3Den%26style%3D40,18"
            "&zmax=19&zmin=0"
        ),
        "provider": "wms",
        "default": False,
    },
]

# Sources WFS — URL par workspace
WFS_SOURCES = {
    "urbisvector": {
        "url": "https://geoservices-vector.irisnet.be/geoserver/urbisvector/wfs",
        "srs": "EPSG:31370",
        "version": "auto",
    },
    "URBAN_DCH_IBH": {
        "url": "https://gis.urban.brussels/geoserver/wfs",
        "srs": "EPSG:31370",
        "version": "auto",
    },
}


def _log(msg, level=Qgis.MessageLevel.Info):
    QgsMessageLog.logMessage(msg, TAG, level=level)


# =====================================================================
# DEJA CHARGE — couches et fonds de plan presents dans le projet
# =====================================================================

def _catalog_table_id(entry) -> str:
    """Identifiant « deja chargee » d'une entree du catalogue : typename
    pour une couche WFS, sinon schema.table."""
    return entry[3] if entry[0] in WFS_KEYS else f"{entry[2]}.{entry[3]}"


def _layer_table_ids(layer) -> list[str]:
    """Identifiants « deja chargee » d'une couche : schema.table pour une
    couche PostgreSQL, typename(s) du catalogue contenus dans la source d'une
    couche WFS ; [] pour le reste (raster, couche sans fournisseur...)."""
    if not isinstance(layer, QgsVectorLayer):
        return []
    prov = layer.dataProvider()
    if not prov:
        return []
    if prov.name() == "postgres":
        uri = prov.uri()
        return [f"{uri.schema()}.{uri.table()}"]
    if prov.name() == "WFS":
        src = prov.uri().uri()
        return [entry[3] for entry in LAYER_CATALOG if entry[2] == "wfs" and entry[3] in src]
    return []


def _existing_layer_index(project) -> dict:
    """Couches vectorielles du projet par identifiant « deja chargee »
    (schema.table PostgreSQL, typename WFS du catalogue). La premiere couche
    trouvee l'emporte."""
    index = {}
    for ly in project.mapLayers().values():
        for table_id in _layer_table_ids(ly):
            index.setdefault(table_id, ly)
    return index


def _detect_existing_layers(schema: str = OPERATOR_TEMPLATE_SCHEMA) -> set[str]:
    """Cles du catalogue (simples) deja presentes dans le projet pour
    l'operateur de *schema* : une couche operateur ne compte que dans son
    schema, une couche commune compte pour tous les operateurs."""
    index = _existing_layer_index(QgsProject.instance())
    return {entry[0] for entry in catalog_for(schema) if _catalog_table_id(entry) in index}


def _loaded_layer_names(project) -> set[str]:
    """Noms des couches du projet (arbre ou non) : un fond de plan de ce nom
    est deja charge (regle unique de _add_basemaps et de l'ecran, D12)."""
    return {ly.name() for ly in project.mapLayers().values()}


def _detect_existing_basemaps() -> set[str]:
    """Cles de BASEMAPS deja chargees dans le projet courant, selon la regle
    de nom de _add_basemaps (qui ne les ajouterait pas une seconde fois)."""
    names = _loaded_layer_names(QgsProject.instance())
    return {bm["key"] for bm in BASEMAPS if bm["name"] in names}


# Couches techniques du catalogue : jamais comptees comme couches de travail.
_TECHNICAL_KEYS = frozenset({"v_form_lists", "docs_elements"})


@dataclass(frozen=True)
class LoadedCounts:
    per_operator: dict   # schema -> couches operateur presentes dans l'arbre de couches
    common: int          # couches communes de travail (hors v_form_lists, docs_elements)
    basemaps: int        # fonds de plan de BASEMAPS presents (chacun compte une fois)


def count_loaded_layers(project, known: Optional[Iterable[str]] = None) -> LoadedCounts:
    """Ce que le projet contient deja, pour l'ecran d'accueil (§ 6.2) : seules
    les couches qui ont un noeud dans l'arbre comptent (les couches fantomes
    creees par les relations des QML n'en ont pas). *per_operator* suit
    l'ordre de l'arbre. *known* (schemas operateur connus, voir
    known_operator_schemas) : une table operateur d'un autre schema (copie
    dans public...) ne fait pas naitre d'operateur ; None = tout schema."""
    known = None if known is None else set(known)
    common_ids = {_catalog_table_id(e) for e in LAYER_CATALOG
                  if e[1] not in OPERATOR_GROUPS and e[0] not in _TECHNICAL_KEYS}
    basemap_names = {bm["name"] for bm in BASEMAPS}
    per_operator: dict[str, int] = {}
    common = 0
    basemaps: set[str] = set()
    seen: set[str] = set()
    for node in project.layerTreeRoot().findLayers():
        layer = node.layer()
        if layer is None or layer.id() in seen:
            continue
        seen.add(layer.id())
        if layer.name() in basemap_names:
            basemaps.add(layer.name())
        for table_id in _layer_table_ids(layer):
            schema, dot, table = table_id.partition(".")
            if table_id in common_ids:
                common += 1
            elif dot and table in OPERATOR_TABLES and (known is None or schema in known):
                per_operator[schema] = per_operator.get(schema, 0) + 1
    return LoadedCounts(per_operator, common, len(basemaps))


# =====================================================================
# GROUPES — un groupe par operateur, « Commun » pour le reste (§ 6.4)
# Ordre a la racine (§ 9.1) : operateurs (ordre de chargement) < Commun
# < Basemaps < Reference ; les groupes de la personne ne bougent pas.
# =====================================================================

_BASEMAPS_GROUP = "Basemaps"
_REFERENCE_GROUP = "Référence"
_ROOT_RANKS = {COMMON_ROOT: 1, _BASEMAPS_GROUP: 2, _REFERENCE_GROUP: 3}


def _is_group(node) -> bool:
    return not hasattr(node, "layerId")


def _root_rank(node):
    """Rang d'un enfant de la racine : 0 groupe d'operateur, 1 Commun,
    2 Basemaps, 3 Reference ; None pour le reste."""
    if not _is_group(node):
        return None
    if node.customProperty(GROUP_SCHEMA_PROPERTY):
        return 0
    kind = (node.customProperty(GROUP_KIND_PROPERTY)
            or canonical_group(node.name(), GROUP_NAMES) or node.name())
    return _ROOT_RANKS.get(kind)


def _insert_root_group(root, name: str, before_ranks):
    """Nouveau groupe racine avant le premier enfant dont le rang est dans
    *before_ranks*, sinon en fin."""
    children = root.children()
    index = next((i for i, c in enumerate(children) if _root_rank(c) in before_ranks), len(children))
    return root.insertGroup(index, name)


def find_child_group(parent, canonical: str):
    """Sous-groupe DIRECT de *parent* pour le groupe canonique *canonical*
    (plan D17) : d'abord la propriete GROUP_KIND_PROPERTY, puis n'importe
    quelle traduction de GROUP_NAMES, puis le nom exact. Un groupe qui porte
    une autre propriete Bridge (autre type, groupe d'operateur) n'est jamais
    pris. Jamais findGroup : il est recursif dans QGIS."""
    candidates = [c for c in parent.children()
                  if _is_group(c) and not c.customProperty(GROUP_SCHEMA_PROPERTY)]
    for child in candidates:
        if child.customProperty(GROUP_KIND_PROPERTY) == canonical:
            return child
    unmarked = [c for c in candidates if not c.customProperty(GROUP_KIND_PROPERTY)]
    for child in unmarked:
        if canonical_group(child.name(), GROUP_NAMES) == canonical:
            return child
    for child in unmarked:
        if child.name() == canonical:
            return child
    return None


def _ensure_child_group(parent, canonical: str):
    group = find_child_group(parent, canonical)
    if group is None:
        group = parent.addGroup(canonical)
        group.setCustomProperty(GROUP_KIND_PROPERTY, canonical)
    return group


def ensure_operator_group(root, operator: OperatorInfo):
    """Groupe racine de *operator* (propriete GROUP_SCHEMA_PROPERTY = son
    schema), sinon cree au libelle de l'operateur avant Commun / Basemaps /
    Reference (sinon en fin)."""
    for child in root.children():
        if _is_group(child) and child.customProperty(GROUP_SCHEMA_PROPERTY) == operator.schema:
            return child
    group = _insert_root_group(root, operator.label, (1, 2, 3))
    group.setCustomProperty(GROUP_SCHEMA_PROPERTY, operator.schema)
    return group


def ensure_common_group(root):
    """Groupe racine « Commun » (propriete, traduction ou nom), sinon cree
    avant Basemaps / Reference (sinon en fin)."""
    group = find_child_group(root, COMMON_ROOT)
    if group is None:
        group = _insert_root_group(root, COMMON_ROOT, (2, 3))
        group.setCustomProperty(GROUP_KIND_PROPERTY, COMMON_ROOT)
    return group


def _layer_group(root, operator: OperatorInfo, group_name: str):
    """Groupe de destination d'une couche du catalogue (cree a la demande :
    jamais de groupe vide)."""
    if group_name in OPERATOR_GROUPS:
        return _ensure_child_group(ensure_operator_group(root, operator), group_name)
    return _ensure_child_group(ensure_common_group(root), group_name)


# =====================================================================
# PROJETS 1.8 — reorganisation au clic « Ajouter des couches » (§ 6.5)
# Ouvrir un projet 1.8 ne le modifie jamais : seul _load_operator_layers
# appelle reorganize_legacy_tree.
# =====================================================================

_LEGACY_KINDS = frozenset(OPERATOR_GROUPS) | frozenset(COMMON_GROUPS)


def _legacy_kind(node) -> str | None:
    """Groupe canonique du catalogue d'un groupe RACINE herite de 1.8 (sans
    aucune propriete Bridge) : « Infrastructure » pour « Infraestrutura »,
    « Chantier » pour « Chantier » (les groupes communs gardent leur nom).
    None pour une couche, un groupe Bridge 1.9 ou un groupe hors catalogue."""
    if (not _is_group(node) or node.customProperty(GROUP_SCHEMA_PROPERTY)
            or node.customProperty(GROUP_KIND_PROPERTY)):
        return None
    kind = canonical_group(node.name(), GROUP_NAMES) or node.name()
    return kind if kind in _LEGACY_KINDS else None


def known_operator_schemas(project, registry: Mapping[str, OperatorInfo]) -> set[str]:
    """Schemas qu'un groupe herite peut designer : operateurs du registre,
    de l'identite du projet (bridge/operator et bridge/operator_labels) et
    ``wyre`` (seul operateur de 1.8). Un autre schema (public, chantier...)
    ne fait jamais naitre d'operateur."""
    labels = parse_operator_labels(project.readEntry("bridge", "operator_labels", "")[0])
    operators = parse_project_operators(project.readEntry("bridge", "operator", "")[0])
    return {*registry, *labels, *operators, OPERATOR_TEMPLATE_SCHEMA}


def _legacy_group_schema(group, known) -> str | None:
    """Schema de la premiere couche PostgreSQL d'une table operateur
    contenue (recursivement) dans *group*, a condition qu'il soit dans
    *known* ; None s'il n'y en a pas (groupe vide, couches non chargees ou
    non PostgreSQL, table d'un schema inconnu comme public.structures)."""
    for node in group.findLayers():
        layer = node.layer()
        provider = layer.dataProvider() if layer is not None else None
        if provider is None or provider.name() != "postgres":
            continue
        uri = provider.uri()
        if uri.table() in OPERATOR_TABLES and uri.schema() in known:
            return uri.schema()
    return None


def _movable(node, known) -> bool:
    """Groupe racine a ranger : groupe commun herite, ou groupe operateur
    herite dont on connait l'operateur. Un groupe operateur sans couche
    operateur connue reste en place."""
    kind = _legacy_kind(node)
    if kind is None:
        return False
    return kind not in OPERATOR_GROUPS or _legacy_group_schema(node, known) is not None


def needs_reorganization(root, known=()) -> bool:
    """True si la racine porte un groupe du catalogue a la mode 1.8 a ranger
    (Demand Points, Infrastructure, Zones, Chantier, OSIRIS, Cadastre UrbIS,
    Urbanisme, sous n'importe quelle traduction). Un groupe operateur ne
    compte que si le schema de ses couches est dans *known* (+ wyre ;
    known_operator_schemas)."""
    known = {*known, OPERATOR_TEMPLATE_SCHEMA}
    return any(_movable(child, known) for child in root.children())


def _legacy_operator(schema: str, registry: Mapping[str, OperatorInfo], labels: Mapping[str, str]) -> OperatorInfo:
    """Operateur d'un groupe herite : celui du registre, sinon (utilisateur
    sans ce scope, D7) un operateur non lisible au libelle memorise dans
    bridge/operator_labels, a defaut au schema capitalise."""
    known = registry.get(schema)
    if known is not None:
        return known
    return OperatorInfo(schema.upper(), labels.get(schema) or schema.capitalize(), schema, readable=False)


def _move_group(group, target, kind: str) -> None:
    """Deplace *group* sous *target* (clone : identifiants de couche
    inchanges) avec la propriete GROUP_KIND_PROPERTY ; fusionne dans le
    sous-groupe existant du meme type plutot que de le doubler."""
    existing = find_child_group(target, kind)
    if existing is None:
        clone = group.clone()
        clone.setCustomProperty(GROUP_KIND_PROPERTY, kind)
        target.addChildNode(clone)
    else:
        for child in group.children():
            existing.addChildNode(child.clone())
    group.parent().removeChildNode(group)


def reorganize_legacy_tree(project, registry: Mapping[str, OperatorInfo]) -> list[OperatorInfo]:
    """Range les groupes racine d'un projet 1.8 dans la structure 1.9 (§ 6.5) :
    Demand Points / Infrastructure / Zones dans le groupe de l'operateur de
    leurs couches, les groupes communs dans « Commun ». Un groupe operateur
    sans couche PostgreSQL d'une table operateur d'un schema connu
    (known_operator_schemas) reste en place a la racine : aucun operateur
    n'est invente pour lui.

    Les groupes sont reconnus sous leur nom FR / EN / PT et gardent leur nom.
    Les couches, groupes et couches personnels de la racine ne sont pas
    touches. Retourne les operateurs concernes, dans l'ordre d'apparition ;
    un second appel retourne [] et ne change rien."""
    root = project.layerTreeRoot()
    labels = parse_operator_labels(project.readEntry("bridge", "operator_labels", "")[0])
    known = known_operator_schemas(project, registry)
    touched: list[OperatorInfo] = []
    for child in root.children():
        if not _movable(child, known):
            continue
        kind = _legacy_kind(child)
        if kind in OPERATOR_GROUPS:
            operator = _legacy_operator(_legacy_group_schema(child, known), registry, labels)
            if operator not in touched:
                touched.append(operator)
            target = ensure_operator_group(root, operator)
        else:
            target = ensure_common_group(root)
        _move_group(child, target, kind)
    return touched


class LayerSelectionWidget(QWidget):
    """Selection des couches de la grande tuile de l'ecran d'accueil (spec
    § 6.1), ex-InitProjectDialog dont elle garde toutes les capacites (§ 4) :
    modeles et « Selection manuelle » avec leur description, arbre par
    groupe, couches deja chargees grisees, Tout / Rien, arbre des fonds de
    plan, « Appliquer les styles de la base ».

    set_operator() est obligatoire avant usage : il remplit l'arbre avec les
    couches de l'operateur choisi (couches operateur grisees pour ce seul
    operateur, couches communes deja chargees toujours grisees). Une couche
    deja chargee est grisee ET decochee (decision T9-c2b) : un modele, Tout
    ou Rien ne la cochent jamais, et selected_layers() ne la rend jamais,
    quel que soit l'etat de sa case (en Qt, ItemIsAutoTristate propage
    l'etat d'un groupe a ses enfants desactives). Idem pour les fonds de
    plan deja charges (meme regle de nom que _add_basemaps, D12) et
    selected_basemaps().
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._schema = OPERATOR_TEMPLATE_SCHEMA
        self._label = ""
        self._existing: set[str] = set()
        self._items = {}  # key → QTreeWidgetItem
        self._basemap_items = {}  # key → QTreeWidgetItem
        self._existing_basemaps = _detect_existing_basemaps()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # -- Template selector ------------------------------------------------
        tmpl_box = QGroupBox(tr("init.group_template"))
        tmpl_layout = QVBoxLayout(tmpl_box)

        self._combo = QComboBox()
        self._combo.addItem(tr("init.custom_select"), "custom")
        for key, tmpl in TEMPLATES.items():
            self._combo.addItem(tmpl["label"], key)
        self._combo.currentIndexChanged.connect(self._on_template_changed)
        tmpl_layout.addWidget(self._combo)

        self._desc_label = QLabel("")
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet("color: #666; font-style: italic;")
        tmpl_layout.addWidget(self._desc_label)

        layout.addWidget(tmpl_box)

        # -- Couches de travail | fonds de plan et styles (maquette v3) ------
        columns = QHBoxLayout()

        layers_box = QGroupBox(tr("init.group_layers"))
        layers_layout = QVBoxLayout(layers_box)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        layers_layout.addWidget(self._tree)

        # Select all / none buttons
        btn_layout = QHBoxLayout()
        self._btn_all = QPushButton(tr("init.select_all"))
        self._btn_all.clicked.connect(lambda _checked=False: self._set_all(True))
        self._btn_none = QPushButton(tr("init.select_none"))
        self._btn_none.clicked.connect(lambda _checked=False: self._set_all(False))
        btn_layout.addWidget(self._btn_all)
        btn_layout.addWidget(self._btn_none)
        btn_layout.addStretch()
        layers_layout.addLayout(btn_layout)
        columns.addWidget(layers_box, 3)

        side = QVBoxLayout()
        basemap_box = QGroupBox(tr("init.group_basemaps"))
        basemap_layout = QVBoxLayout(basemap_box)
        self._basemap_tree = QTreeWidget()
        self._basemap_tree.setHeaderHidden(True)
        self._basemap_tree.setRootIsDecorated(True)
        self._fill_basemaps()
        basemap_layout.addWidget(self._basemap_tree)
        side.addWidget(basemap_box)

        # -- Options ----------------------------------------------------------
        self._chk_styles = QCheckBox(tr("init.apply_styles"))
        self._chk_styles.setChecked(True)
        side.addWidget(self._chk_styles)
        side.addStretch()
        columns.addLayout(side, 2)

        layout.addLayout(columns)

        # Pre-select first template (arbre rempli par set_operator)
        self._combo.setCurrentIndex(1)

    def _group_caption(self, group: str) -> str:
        """Nom du groupe dans la langue courante ; badge de l'operateur sur
        un groupe operateur, mention « commun » sur un groupe commun."""
        name = GROUP_NAMES.get(group, {}).get(get_language(), group)
        if group in OPERATOR_GROUPS:
            return f"{name}  [{self._label}]"
        if group in COMMON_GROUPS:
            return f"{name}  ({tr('home.common_tag')})"
        return name

    def _fill_layers(self):
        """(Re)construit l'arbre des couches pour l'operateur courant."""
        self._tree.clear()
        self._items = {}
        group_items = {}  # group_name → QTreeWidgetItem
        for key, group, schema, table, _geom, _pk, label in catalog_for(self._schema):
            if group not in group_items:
                gi = QTreeWidgetItem(self._tree, [self._group_caption(group)])
                gi.setFlags(gi.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                gi.setCheckState(0, Qt.CheckState.Unchecked)
                gi.setExpanded(True)
                group_items[group] = gi

            already = key in self._existing
            suffix = "  ✔" if already else ""
            item = QTreeWidgetItem(group_items[group], [f"{label}  ({schema}.{table}){suffix}"])
            if already:
                # Deja chargee — grisee et decochee, jamais selectionnee (T9-c2b)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked)
                item.setToolTip(0, tr("init.already_loaded"))
                item.setDisabled(True)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            self._items[key] = item

    def _fill_basemaps(self):
        basemap_groups = {}  # group → QTreeWidgetItem
        for bm in BASEMAPS:
            grp_name = bm.get("group", "Autres")
            if grp_name not in basemap_groups:
                gi = QTreeWidgetItem(self._basemap_tree, [grp_name])
                gi.setFlags(gi.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                gi.setCheckState(0, Qt.CheckState.Unchecked)
                gi.setExpanded(True)
                basemap_groups[grp_name] = gi

            already = bm["key"] in self._existing_basemaps
            item = QTreeWidgetItem(basemap_groups[grp_name], [bm["name"] + ("  ✔" if already else "")])
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

    def set_operator(self, schema: str, label: str) -> None:
        """Couches de l'operateur *schema* (libelle *label* sur le badge des
        groupes operateur). Le modele choisi est reapplique ; en « Selection
        manuelle », les couches cochees a la main le restent."""
        manual = {key for key, item in self._items.items()
                  if key not in self._existing and item.checkState(0) == Qt.CheckState.Checked}
        self._schema, self._label = schema, label
        self._existing = _detect_existing_layers(schema)
        self._fill_layers()
        key = self._combo.currentData()
        if key == "custom":
            for item_key in manual - self._existing:
                if item_key in self._items:
                    self._items[item_key].setCheckState(0, Qt.CheckState.Checked)
        else:
            self._apply_template(key)

    def _on_template_changed(self, idx):
        key = self._combo.currentData()
        if key == "custom":
            self._desc_label.setText(tr("init.custom_desc"))
            return

        tmpl = TEMPLATES.get(key, {})
        self._desc_label.setText(tmpl.get("description", ""))
        self._apply_template(key)

    def _apply_template(self, key):
        layers = TEMPLATES.get(key, {}).get("layers", set())
        for item_key, item in self._items.items():
            if item_key in self._existing:
                continue  # deja chargee : jamais cochee (T9-c2b)
            item.setCheckState(0, Qt.CheckState.Checked if item_key in layers else Qt.CheckState.Unchecked)

    def _set_all(self, checked):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for item_key, item in self._items.items():
            if item_key not in self._existing:
                item.setCheckState(0, state)
        self._combo.setCurrentIndex(0)  # switch to custom

    def selected_layers(self) -> set[str]:
        """Cles simples des couches cochees, jamais celles deja chargees
        (T9-c2b : filtre sur _existing, pas sur la case) ; v_form_lists
        toujours incluse."""
        result = {"v_form_lists"}  # toujours inclus
        for key, item in self._items.items():
            if key not in self._existing and item.checkState(0) == Qt.CheckState.Checked:
                result.add(key)
        return result

    def selected_basemaps(self) -> set[str]:
        """Cles des fonds de plan coches, sans ceux deja charges."""
        result = set()
        for key, item in self._basemap_items.items():
            if key not in self._existing_basemaps and item.checkState(0) == Qt.CheckState.Checked:
                result.add(key)
        return result

    def want_basemap(self) -> bool:
        return bool(self.selected_basemaps())

    def want_styles(self) -> bool:
        return self._chk_styles.isChecked()


# =====================================================================
# RELATIONS — creation/recreation dynamique
# =====================================================================

def _discover_catalog_layers(project) -> dict:
    """Couches PostgreSQL du projet par cle de couche (layer_key) : une table
    operateur dans n'importe quel schema ("cables@orange"), une table commune
    dans son schema ("interventions"). La premiere couche trouvee l'emporte
    (une copie filtree ajoutee apres l'originale est ignoree)."""
    operator_keys = {e[3]: e[0] for e in LAYER_CATALOG if e[0] in OPERATOR_KEYS}
    common_keys = {_catalog_table_id(e): e[0] for e in LAYER_CATALOG
                   if e[0] not in OPERATOR_KEYS and e[0] not in WFS_KEYS}
    loaded = {}
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        prov = layer.dataProvider()
        if not prov or prov.name() != "postgres":
            continue
        uri = QgsDataSourceUri(prov.dataSourceUri())
        schema, table = uri.schema(), uri.table()
        if table in operator_keys:
            key = layer_key(operator_keys[table], schema)
        else:
            key = common_keys.get(f"{schema}.{table}")
        if key and key not in loaded:
            loaded[key] = layer
    return loaded


def ensure_relations(loaded: dict | None = None, primary_schema: str | None = None) -> int:
    """Cree ou recree les relations QGIS de RELATION_DEFS, par operateur
    (plan D3).

    Appelee par init_project() et par _on_project_read() pour garantir
    que les relations existent toujours avec les bons layer IDs.
    *loaded* : cle de couche (layer_key : "cables@orange", "interventions")
    -> couche ; None : couches decouvertes dans le projet courant.
    Pour chaque schema present (cles "@schema"), les deux bouts d'une
    relation se resolvent par layer_key(cle, schema) : une cle commune donne
    la couche commune (Documents, permis). L'operateur principal
    (*primary_schema*, sinon le premier de l'identite du projet, sinon wyre)
    garde les identifiants historiques cites par les QML ; les autres
    recoivent "<relation>__<schema>".
    """
    project = QgsProject.instance()
    if loaded is None:
        loaded = _discover_catalog_layers(project)
    if primary_schema is None:
        operators = get_bridge_info()["operators"]
        primary_schema = operators[0] if operators else OPERATOR_TEMPLATE_SCHEMA
    schemas = list(dict.fromkeys(key.partition("@")[2] for key in loaded if "@" in key))

    relation_manager = project.relationManager()
    rel_count = 0
    for schema in schemas:
        for parent_key, child_key, fk_field, rel_name in RELATION_DEFS:
            parent = loaded.get(layer_key(parent_key, schema))
            child = loaded.get(layer_key(child_key, schema))
            if not parent or not child:
                continue
            rel_id = relation_id(rel_name, schema, primary_schema)

            # Supprimer toute relation existante (possiblement cassee par QML)
            existing = relation_manager.relation(rel_id)
            if existing.id():
                relation_manager.removeRelation(rel_id)

            rel = QgsRelation()
            rel.setId(rel_id)
            rel.setName(rel_id)
            rel.setReferencingLayer(child.id())
            rel.setReferencedLayer(parent.id())
            rel.addFieldPair(fk_field, "id")

            if rel.isValid():
                relation_manager.addRelation(rel)
                rel_count += 1

    if rel_count:
        _log(f"{rel_count} relation(s) creee(s)/recreee(s)")
    return rel_count


# =====================================================================
# INIT PROJECT — logique principale
# =====================================================================

def init_project(conn_params: dict, password: str, selected: set[str],
                 add_basemap: bool = True, apply_styles: bool = True,
                 selected_basemaps: set[str] | None = None, *,
                 operator: OperatorInfo, suffix: bool | None = None) -> int:
    """Charge les couches selectionnees (cles simples du catalogue) pour
    *operator* (spec § 6.3, § 6.4).

    Les entrees operateur sont lues dans operator.schema et rangees dans le
    groupe de l'operateur ; les entrees communes, chargees une seule fois
    quel que soit le nombre d'operateurs, dans « Commun ». Une couche deja
    presente (meme schema.table, meme typename WFS) est reprise telle quelle :
    jamais restylee (decision T9-c2b, les retouches de symbologie sont
    gardees), mais les couches du catalogue deja presentes pour cet operateur
    et les couches communes presentes entrent dans les relations, pour
    qu'une couche nouvelle soit reliee a une couche deja la.
    L'operateur n'entre dans l'identite du projet (stamp_project) que si
    une de ses couches operateur est ajoutee (juste avant son addMapLayer)
    ou deja presente ; version et plugin sont toujours ecrits.

    Returns
    -------
    int
        Nombre de couches ajoutees.
    """
    project = QgsProject.instance()
    catalog = catalog_for(operator.schema)

    # -- CRS projet -------------------------------------------------------
    crs = QgsCoordinateReferenceSystem("EPSG:31370")
    project.setCrs(crs)
    _log("CRS projet: EPSG:31370 (Belgium Lambert 72)")

    # -- Version et plugin : toujours (projet Bridge reconnu) ----------------
    _stamp_version(project)

    root = project.layerTreeRoot()
    groups = {}
    existing = _existing_layer_index(project)
    # Couches deja a la racine avant l'appel (couches personnelles...) : le
    # nettoyage des fantomes ne retire que les noeuds apparus pendant l'appel.
    root_layers_before = _root_layer_ids(root)

    # Couches du catalogue deja presentes pour cet operateur et couches
    # communes presentes : reliees, jamais restylees (T9-c2b).
    present = {}
    for entry in catalog:
        layer = existing.get(_catalog_table_id(entry))
        if layer is not None:
            present[layer_key(entry[0], entry[2])] = layer
    stamped = False
    if any(base_key(key) in OPERATOR_KEYS for key in present):
        # Deja presente : l'operateur est dans le projet (T2-c3) ; avant tout
        # addMapLayer, l'ordre n'est pas en jeu.
        stamp_project(operator, suffix)
        stamped = True

    # -- Charger les couches (dans l'ordre du catalogue) -------------------
    loaded = {}  # layer_key ("cables@orange", "interventions") → couche
    added = {}   # couches ajoutees par cet appel : les seules restylees
    count = 0
    skipped = 0

    # Iterer dans l'ordre du catalogue, pas dans l'ordre du set
    for entry in catalog:
        key = entry[0]
        if key not in selected:
            continue
        _, group_name, schema, table, geom_col, pk, label = entry
        lkey = layer_key(key, schema)

        # Eviter les doublons : reprendre la couche existante (relations)
        if lkey in present:
            loaded[lkey] = present[lkey]
            skipped += 1
            continue

        if key in WFS_KEYS:
            layer = _build_wfs_layer(table, label)
        else:
            uri = _build_uri(conn_params, password, schema, table, geom_col, pk)
            # Toujours utiliser le nom de table comme nom QGIS
            # (requis pour les ValueRelation qui referencent par LayerName)
            layer = QgsVectorLayer(uri.uri(False), table, "postgres")

        if not layer or not layer.isValid():
            _log(f"Couche invalide: {schema}.{table}", Qgis.MessageLevel.Warning)
            continue

        if key in OPERATOR_KEYS and not stamped:
            # Identite AVANT le premier addMapLayer d'une couche operateur
            # (suffixe pose sur layersAdded, tache 3) ; un operateur sans
            # couche ajoutee ni deja presente n'y entre jamais (T2-c3).
            stamp_project(operator, suffix)
            stamped = True

        # Sans groupe : au projet seulement, hors arbre de couches.
        project.addMapLayer(layer, False)
        if group_name == _REFERENCE_GROUP:
            # Rangee dans Reference apres les fonds de plan (plus bas)
            root.addLayer(layer)
        elif group_name:
            group = _layer_group(root, operator, group_name)
            groups[(schema, group_name)] = group
            group.addLayer(layer)

        loaded[lkey] = layer
        added[lkey] = layer
        count += 1

    if skipped:
        _log(f"{skipped} couche(s) deja presente(s) — ignoree(s)")
    _log(f"{count} couche(s) chargee(s)")
    _log(f"Projet identifie: operators={get_bridge_info()['operator'] or '-'} "
         f"version={WYRE_PROJECT_VERSION} plugin={_plugin_version()}")

    # -- Relations --------------------------------------------------------
    # Couches nouvelles ET deja presentes : subducts ajoutee se relie a
    # ducts deja la (T9-c2b).
    related = {**present, **loaded}
    ensure_relations(related)

    # -- Styles (couches ajoutees seulement, T9-c2b) ------------------------
    # 1. Styles par defaut depuis la BDD (prioritaires)
    db_styled: set[str] = set()
    if apply_styles and added:
        db_styled = _apply_styles_from_db(conn_params, password, added)
    # 2. Styles embarques uniquement pour les couches sans style BDD
    fallback = {k: v for k, v in added.items() if k not in db_styled}
    if fallback:
        _apply_embedded_styles(fallback)

    # Les styles QML contiennent des relation editors (Documents, Splices).
    # Apres le chargement des styles, recreer les relations pour que QGIS
    # les lie correctement aux widgets du formulaire.
    ensure_relations(related)

    # -- Basemaps ---------------------------------------------------------
    if add_basemap and selected_basemaps:
        basemap_group = _add_basemaps(root, selected_basemaps)
        if basemap_group is not None:
            groups[_BASEMAPS_GROUP] = basemap_group

    # -- Groupe Référence (en bas, apres les basemaps) --------------------
    # Seulement pour des couches presentes dans l'arbre (v_form_lists ajoutee
    # cachee par le plugin n'a pas de noeud) : jamais de groupe vide. Couches
    # ajoutees ET deja presentes (related) : une couche Documents deja a la
    # racine, jamais recochee (T9-c2b), y est rangee aussi.
    ref_nodes = []
    for entry in catalog:
        layer = related.get(layer_key(entry[0], entry[2])) if entry[1] == _REFERENCE_GROUP else None
        node = root.findLayer(layer.id()) if layer is not None else None
        if node is not None:
            ref_nodes.append(node)
    if ref_nodes:
        ref_group = root.findGroup(_REFERENCE_GROUP) or root.addGroup(_REFERENCE_GROUP)
        groups[_REFERENCE_GROUP] = ref_group
        # Deplacer les couches ref dans ce groupe
        for node in ref_nodes:
            if node.parent() != ref_group:
                clone = node.clone()
                ref_group.addChildNode(clone)
                node.parent().removeChildNode(node)
        ref_group.setExpanded(False)
        ref_group.setItemVisibilityChecked(False)

    # -- Nettoyer les couches fantomes a la racine -------------------------
    _cleanup_ghost_layers(root, groups, keep=root_layers_before)

    return count


# =====================================================================
# Helpers
# =====================================================================

_SSL_MODES = {
    "require": "SslRequire",
    "verify-ca": "SslVerifyCa",
    "verify-full": "SslVerifyFull",
}


def _build_uri(conn_params, password, schema, table, geom_col, pk):
    # Mode SSL passe a setConnection() : setSslMode() n'existe qu'a partir de
    # QGIS 3.42 environ (AttributeError -> init projet en echec avant).
    sslmode = getattr(
        QgsDataSourceUri.SslMode,
        _SSL_MODES.get(conn_params.get("sslmode", "require"), "SslPrefer"),
        QgsDataSourceUri.SslMode.SslPrefer,
    )
    # Bridge 1.8 : session nominative = config Auth Manager a id fixe
    # (authcfg) et AUCUN mot de passe dans la datasource ; sans authcfg,
    # chemin 1.7.x (identifiant partage en clair, appel inchange).
    authcfg = conn_params.get("authcfg", "")
    uri = QgsDataSourceUri()
    connection = [
        conn_params.get("host", "localhost"),
        str(conn_params.get("port", 5432)),
        conn_params.get("dbname", "farois_ftth"),
        conn_params.get("user", "ftth_editor"),
        "" if authcfg else password,
        sslmode,
    ]
    if authcfg:
        connection.append(authcfg)
    uri.setConnection(*connection)
    uri.setDataSource(schema, table, geom_col, "", pk)
    uri.setParam("estimatedmetadata", "true")
    uri.setParam("checkPrimaryKeyUnicity", "0")
    return uri


def _root_layer_ids(root) -> set[str]:
    """Identifiants des couches posees directement a la racine de l'arbre."""
    return {child.layerId() for child in root.children() if hasattr(child, "layerId")}


def _cleanup_ghost_layers(root, groups, keep=frozenset()):
    """Supprime les couches fantomes a la racine du layer tree.

    Les styles QML contiennent des references de relations qui peuvent
    pousser QGIS a creer des couches fantomes (sans groupe, a la racine).
    On les detecte et les supprime. Les couches de *keep* (identifiants des
    couches deja a la racine avant le chargement : couches personnelles)
    ne sont jamais des fantomes : retirer leur noeud retirerait la couche du
    projet, editions comprises (relecture finale I1).
    """
    group_set = set(groups.values())
    removed = 0
    for child in list(root.children()):
        # Ne toucher qu'aux couches directement a la racine (pas dans un groupe)
        if child in group_set:
            continue
        if hasattr(child, "layerId") and child.layerId() not in keep:
            # Noeud de couche apparu a la racine pendant l'appel : un fantome
            root.removeChildNode(child)
            removed += 1
    if removed:
        _log(f"{removed} couche(s) fantome(s) supprimee(s) de la racine")


def _apply_embedded_styles(loaded: dict):
    """Applique les styles QML embarques dans le plugin (*loaded* indexe
    par cle de couche : "cables@orange" prend le style de "cables")."""
    styles_dir = os.path.join(os.path.dirname(__file__), "styles")
    styled = 0
    for key, layer in loaded.items():
        qml_file = EMBEDDED_STYLES.get(base_key(key))
        if not qml_file:
            continue
        qml_path = os.path.join(styles_dir, qml_file)
        if not os.path.exists(qml_path):
            continue
        msg, ok = layer.loadNamedStyle(qml_path)
        if ok:
            layer.triggerRepaint()
            styled += 1
    if styled:
        _log(f"{styled} style(s) embarque(s) applique(s)")


def _build_wfs_layer(typename: str, label: str):
    """Cree une couche WFS a partir du typename (workspace:layer)."""
    workspace = typename.split(":")[0] if ":" in typename else typename
    cfg = WFS_SOURCES.get(workspace, {})
    url = cfg.get("url", "")
    srs = cfg.get("srs", "EPSG:31370")
    version = cfg.get("version", "auto")

    source = (
        f"pagingEnabled='default' "
        f"preferCoordinatesForWfsT11='false' "
        f"restrictToRequestBBOX='1' "
        f"srsname='{srs}' "
        f"typename='{typename}' "
        f"url='{url}' "
        f"version='{version}'"
    )
    return QgsVectorLayer(source, label, "WFS")


def _add_basemaps(root, selected_keys: set[str]):
    """Ajoute les fonds de carte dans un groupe Basemaps, cree au premier
    fond ajoute (jamais de groupe vide). Retourne le groupe, ou None."""
    project = QgsProject.instance()
    existing_names = _loaded_layer_names(project)

    basemap_group = root.findGroup(_BASEMAPS_GROUP)
    basemap_by_key = {bm["key"]: bm for bm in BASEMAPS}
    added = 0

    for key in selected_keys:
        bm = basemap_by_key.get(key)
        if not bm:
            continue
        name = bm["name"]
        if name in existing_names:
            _log(f"Basemap '{name}' deja present")
            continue

        layer = QgsRasterLayer(bm["source"], name, bm["provider"])
        if layer.isValid():
            project.addMapLayer(layer, False)
            if basemap_group is None:
                # Juste au-dessus de Reference (ordre § 9.1)
                basemap_group = _insert_root_group(root, _BASEMAPS_GROUP, (3,))
            basemap_group.addLayer(layer)
            added += 1
        else:
            _log(f"Basemap '{name}' invalide", Qgis.MessageLevel.Warning)

    if added:
        _log(f"{added} basemap(s) ajoute(s)")

    return basemap_group



def _apply_styles_from_db(conn_params: dict, password: str, loaded: dict) -> set[str]:
    """Charge les styles QML par defaut depuis public.layer_styles.

    Sources essayees dans l'ordre de style_sources : le style de la table
    dans le schema de la couche, puis, pour une table operateur d'un autre
    schema, le style wyre de la meme table (spec § 9.3) ; la premiere ligne
    trouvee l'emporte.

    Returns
    -------
    set[str]
        Cles des couches pour lesquelles un style DB a ete applique.
    """
    styled_keys: set[str] = set()
    try:
        import psycopg2
    except ImportError:
        _log("psycopg2 indisponible — styles non appliques", Qgis.MessageLevel.Warning)
        return styled_keys

    # Bridge 1.8 : session nominative = verify-full avec les CA du paquet
    # (sslrootcert fourni par l'appelant) ; identifiant partage = connexion
    # 1.7.x a l'identique, defaut libpq (revue 29/10, D-TLS-2).
    ssl_kwargs = {}
    if conn_params.get("sslrootcert"):
        ssl_kwargs["sslmode"] = conn_params.get("sslmode", "verify-full")
        ssl_kwargs["sslrootcert"] = conn_params["sslrootcert"]

    conn = None
    try:
        conn = psycopg2.connect(
            host=conn_params.get("host", "localhost"),
            port=conn_params.get("port", 5432),
            dbname=conn_params.get("dbname", "farois_ftth"),
            user=conn_params.get("user", "ftth_editor"),
            password=password,
            **ssl_kwargs,
        )
        cur = conn.cursor()

        for key, layer in loaded.items():
            provider = layer.dataProvider()
            if not provider:
                continue
            src_uri = QgsDataSourceUri(provider.uri().uri())
            schema = src_uri.schema() or OPERATOR_TEMPLATE_SCHEMA
            table = src_uri.table()
            geom_col = src_uri.geometryColumn() or ""

            row = None
            try:
                for style_schema, style_table in style_sources(schema, table):
                    cur.execute(
                        'SELECT styleqml::text FROM public.layer_styles '
                        "WHERE f_table_schema = %s AND f_table_name = %s "
                        "AND COALESCE(f_geometry_column, '') = %s AND useasdefault = true "
                        "AND stylename = 'default' LIMIT 1",
                        (style_schema, style_table, geom_col),
                    )
                    row = cur.fetchone()
                    if row and row[0]:
                        break
            except psycopg2.Error:
                continue

            if not row or not row[0]:
                continue

            try:
                doc = QDomDocument()
                doc.setContent(row[0])
                was_read_only = layer.isReadOnly()
                ok, _error = layer.importNamedStyle(doc)  # (succes, message)
                if not was_read_only and layer.isReadOnly():
                    # Bridge 1.8, revue 2 (I-2) : readOnly="1" d'un style par
                    # defaut n'est pas une regle de style (verrou de session
                    # enregistre par megarde) -> ignore.
                    layer.setReadOnly(False)
                    _log(f"Style {key} : readOnly=1 ignore", Qgis.MessageLevel.Warning)
                if ok:
                    layer.triggerRepaint()
                    styled_keys.add(key)
            except Exception:
                pass

        cur.close()
    except psycopg2.Error as exc:
        _log(f"Connexion styles impossible: {exc}", Qgis.MessageLevel.Warning)
        return styled_keys
    finally:
        if conn is not None:
            conn.close()

    if styled_keys:
        _log(f"{len(styled_keys)} style(s) applique(s) depuis public.layer_styles")
    return styled_keys
