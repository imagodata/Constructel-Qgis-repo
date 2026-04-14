# -*- coding: utf-8 -*-
"""
Constructel Bridge — Initialisation de projet QGIS WYRE FTTH.

Dialog de selection de couches avec templates pre-configures,
puis chargement des couches, styles, relations et basemaps.
"""

import os
import tempfile

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
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

from .i18n import tr

TAG = "Constructel Bridge"

# Identifiant operateur et version — stockes comme variables projet QGIS
# pour detecter qu'un projet a ete initialise par ce plugin.
WYRE_OPERATOR = "wyre"
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

    Retourne True si la variable projet ``bridge_operator`` est renseignee.
    """
    val, _ = QgsProject.instance().readEntry("bridge", "operator", "")
    if val:
        return True
    # Fallback: variable projet QGIS (accessible via @bridge_operator)
    scope = QgsProject.instance().customVariables()
    return bool(scope.get("bridge_operator", ""))


def stamp_project():
    """Ecrit les variables d'identification dans le projet courant.

    Variables projet QGIS (accessibles dans les expressions via @):
      - @bridge_operator : identifiant operateur (ex: "wyre")
      - @bridge_version  : version schema/projet (ex: "4.0.0")
      - @bridge_plugin   : version du plugin Bridge ayant initialise le projet

    L'operateur identifie le client/deploiement (wyre, orange, proximus, etc.).
    Le plugin peut ainsi detecter les projets qu'il gere.
    """
    project = QgsProject.instance()
    from qgis.core import QgsExpressionContextUtils
    QgsExpressionContextUtils.setProjectVariable(project, "bridge_operator", WYRE_OPERATOR)
    QgsExpressionContextUtils.setProjectVariable(project, "bridge_version", WYRE_PROJECT_VERSION)
    QgsExpressionContextUtils.setProjectVariable(project, "bridge_plugin", _plugin_version())
    # Aussi via writeEntry pour lecture rapide sans contexte d'expression
    project.writeEntry("bridge", "operator", WYRE_OPERATOR)
    project.writeEntry("bridge", "version", WYRE_PROJECT_VERSION)


# =====================================================================
# CATALOGUE COMPLET DES COUCHES
# (key, group, schema, table, geom_col, pk, label_fr)
# =====================================================================

LAYER_CATALOG = [
    # -- Demand Points ----------------------------------------------------
    ("demand_points",      "Demand Points",   "infra", "demand_points",      "geom", "id",  "Points de demande"),

    # -- Infrastructure ---------------------------------------------------
    ("structures",         "Infrastructure",  "infra", "structures",         "geom", "id",  "Structures"),
    ("cables",             "Infrastructure",  "infra", "cables",             "geom", "id",  "Cables"),
    ("subducts",           "Infrastructure",  "infra", "subducts",           "geom", "id",  "Sous-fourreaux"),
    ("ducts",              "Infrastructure",  "infra", "ducts",              "geom", "id",  "Conduites"),
    ("splices",            "Infrastructure",  "infra", "structure_cable_splices", None, "id", "Soudures"),

    # -- Zones ------------------------------------------------------------
    ("zone_drop",          "Zones",           "infra", "zone_drop",          "geom", "id",  "Zones Drop"),
    ("zone_distribution",  "Zones",           "infra", "zone_distribution",  "geom", "id",  "Zones Distribution"),
    ("zone_pop",           "Zones",           "infra", "zone_pop",           "geom", "id",  "Zones POP"),
    ("zone_mro",           "Zones",           "infra", "zone_mro",           "geom", "id",  "Zones MRO"),

    # -- Topologie --------------------------------------------------------
    ("topo_violations",    "Topologie",       "infra", "topology_violations","geom", "id",  "Violations topologie"),

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

# Mapping key → fichier QML embarque dans le plugin (dossier styles/)
EMBEDDED_STYLES = {
    # Infra
    "demand_points":    "demand_points.qml",
    "structures":       "structures.qml",
    "cables":           "cables.qml",
    "subducts":         "subducts.qml",
    "ducts":            "ducts.qml",
    # Zones
    "zone_drop":        "zone_drop.qml",
    "zone_distribution":"zone_distribution.qml",
    "zone_pop":         "zone_pop.qml",
    "zone_mro":         "zone_mro.qml",
    # Topologie
    "topo_violations":  "topology_violations.qml",
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
_INFRA_BASE = {
    "zone_mro", "zone_pop", "zone_distribution", "zone_drop",
    "structures", "ducts", "subducts", "cables", "splices",
    "demand_points", "topo_violations",
    "docs_elements", "v_form_lists",
}

TEMPLATES = {
    "infra": {
        "label": "Infrastructure",
        "description": "Couches infra : zones, structures, cables, conduites, DP, topologie",
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
        "description": "Infra complet + couches chantier (interventions, permis, incidents, synergies)",
        "layers": _INFRA_BASE | {
            "interventions", "incidents", "permis_voirie", "plaintes",
            "interventions_chantier", "synergies", "planning_facades",
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
        "layers": {k for k, *_ in LAYER_CATALOG},
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

    # Splices
    ("structures",     "splices",            "structure_id",         "splices_to_structure"),
    ("cables",         "splices",            "cable_id",             "splices_to_cable"),

    # Documents → Infrastructure (relation editors dans onglet Documentos)
    ("structures",     "docs_elements",      "element_id",           "docs_element_structure"),
    ("cables",         "docs_elements",      "element_id",           "docs_element_cable"),
    ("ducts",          "docs_elements",      "element_id",           "docs_element_duct"),
    ("demand_points",  "docs_elements",      "element_id",           "docs_element_demand_point"),
    ("zone_pop",       "docs_elements",      "element_id",           "docs_element_zone_pop"),

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


def _log(msg, level=Qgis.Info):
    QgsMessageLog.logMessage(msg, TAG, level=level)


# =====================================================================
# DIALOG — selection des couches avec templates
# =====================================================================

def _detect_existing_layers():
    """Detecte les couches deja presentes dans le projet."""
    existing = set()
    project = QgsProject.instance()
    for ly in project.mapLayers().values():
        if not isinstance(ly, QgsVectorLayer):
            continue
        prov = ly.dataProvider()
        if not prov:
            continue
        if prov.name() == "postgres":
            uri = prov.uri()
            existing.add(f"{uri.schema()}.{uri.table()}")
        elif prov.name() == "WFS":
            src = prov.uri().uri()
            for entry in LAYER_CATALOG:
                if entry[2] == "wfs" and entry[3] in src:
                    existing.add(entry[3])
    # Map catalog keys to existing
    result = set()
    for key, _grp, schema, table, *_ in LAYER_CATALOG:
        table_id = table if key in WFS_KEYS else f"{schema}.{table}"
        if table_id in existing:
            result.add(key)
    return result


class InitProjectDialog(QDialog):
    """Dialog de selection des couches avec templates pre-configures."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._existing = _detect_existing_layers()
        has_layers = bool(self._existing - {"v_form_lists", "docs_elements"})
        self.setWindowTitle(
            tr("init.title_add") if has_layers else tr("init.title")
        )
        self.setMinimumWidth(560)
        self.setMinimumHeight(620)
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

        # -- Layer tree (checkable) -------------------------------------------
        layers_box = QGroupBox(tr("init.group_layers"))
        layers_layout = QVBoxLayout(layers_box)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)

        # Build tree from catalog
        self._items = {}  # key → QTreeWidgetItem
        self._group_items = {}  # group_name → QTreeWidgetItem

        for key, group, schema, table, geom, pk, label in LAYER_CATALOG:
            if group is None:
                # Reference layers — always included, not shown
                continue

            if group not in self._group_items:
                gi = QTreeWidgetItem(self._tree, [group])
                gi.setFlags(gi.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                gi.setCheckState(0, Qt.Unchecked)
                gi.setExpanded(True)
                self._group_items[group] = gi

            already = key in self._existing
            suffix = "  ✔" if already else ""
            item = QTreeWidgetItem(
                self._group_items[group],
                [f"{label}  ({schema}.{table}){suffix}"],
            )
            if already:
                # Deja charge — cocher et desactiver (non modifiable)
                item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked)
                item.setToolTip(0, tr("init.already_loaded"))
                item.setDisabled(True)
            else:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Unchecked)
            item.setData(0, Qt.UserRole, key)
            self._items[key] = item

        layers_layout.addWidget(self._tree)

        # Select all / none buttons
        btn_layout = QHBoxLayout()
        btn_all = QPushButton(tr("init.select_all"))
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none = QPushButton(tr("init.select_none"))
        btn_none.clicked.connect(lambda: self._set_all(False))
        btn_layout.addWidget(btn_all)
        btn_layout.addWidget(btn_none)
        btn_layout.addStretch()
        layers_layout.addLayout(btn_layout)

        layout.addWidget(layers_box)

        # -- Fonds de carte ---------------------------------------------------
        basemap_box = QGroupBox(tr("init.group_basemaps"))
        basemap_layout = QVBoxLayout(basemap_box)

        self._basemap_tree = QTreeWidget()
        self._basemap_tree.setHeaderHidden(True)
        self._basemap_tree.setRootIsDecorated(True)
        self._basemap_tree.setMaximumHeight(160)

        self._basemap_items = {}  # key → QTreeWidgetItem
        basemap_groups = {}  # group → QTreeWidgetItem

        for bm in BASEMAPS:
            grp_name = bm.get("group", "Autres")
            if grp_name not in basemap_groups:
                gi = QTreeWidgetItem(self._basemap_tree, [grp_name])
                gi.setFlags(gi.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                gi.setCheckState(0, Qt.Unchecked)
                gi.setExpanded(True)
                basemap_groups[grp_name] = gi

            item = QTreeWidgetItem(basemap_groups[grp_name], [bm["name"]])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if bm.get("default") else Qt.Unchecked)
            item.setData(0, Qt.UserRole, bm["key"])
            self._basemap_items[bm["key"]] = item

        basemap_layout.addWidget(self._basemap_tree)

        layout.addWidget(basemap_box)

        # -- Options ----------------------------------------------------------
        self._chk_styles = QCheckBox(tr("init.apply_styles"))
        self._chk_styles.setChecked(True)
        layout.addWidget(self._chk_styles)

        # -- Buttons ----------------------------------------------------------
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        has_layers = bool(self._existing - {"v_form_lists", "docs_elements"})
        buttons.button(QDialogButtonBox.Ok).setText(
            tr("init.btn_add") if has_layers else tr("init.btn_init")
        )
        layout.addWidget(buttons)

        # Pre-select first template
        self._combo.setCurrentIndex(1)

    def _on_template_changed(self, idx):
        key = self._combo.currentData()
        if key == "custom":
            self._desc_label.setText(tr("init.custom_desc"))
            return

        tmpl = TEMPLATES.get(key, {})
        self._desc_label.setText(tmpl.get("description", ""))

        # Apply template selection
        for layer_key, item in self._items.items():
            item.setCheckState(
                0,
                Qt.Checked if layer_key in tmpl.get("layers", set()) else Qt.Unchecked,
            )

    def _set_all(self, checked):
        state = Qt.Checked if checked else Qt.Unchecked
        for item in self._items.values():
            item.setCheckState(0, state)
        self._combo.setCurrentIndex(0)  # switch to custom

    def selected_layers(self) -> set[str]:
        """Retourne les keys des couches selectionnees."""
        result = {"v_form_lists"}  # toujours inclus
        for key, item in self._items.items():
            if item.checkState(0) == Qt.Checked:
                result.add(key)
        return result

    def selected_basemaps(self) -> set[str]:
        """Retourne les keys des basemaps selectionnees."""
        result = set()
        for key, item in self._basemap_items.items():
            if item.checkState(0) == Qt.Checked:
                result.add(key)
        return result

    def want_basemap(self) -> bool:
        return bool(self.selected_basemaps())

    def want_styles(self) -> bool:
        return self._chk_styles.isChecked()


# =====================================================================
# RELATIONS — creation/recreation dynamique
# =====================================================================

def ensure_relations(loaded: dict[str, QgsVectorLayer] | None = None):
    """Cree ou recree les relations QGIS definies dans RELATION_DEFS.

    Appelee par init_project() et par _on_project_read() pour garantir
    que les relations existent toujours avec les bons layer IDs.
    Si ``loaded`` est None, decouvre les couches depuis le projet courant
    en matchant par table_name.
    """
    project = QgsProject.instance()

    # Auto-decouverte des couches si pas de dict fourni
    if loaded is None:
        loaded = {}
        catalog_tables = {key: f"{schema}.{table}" for key, _grp, schema, table, *_ in LAYER_CATALOG}
        for layer in project.mapLayers().values():
            if not isinstance(layer, QgsVectorLayer):
                continue
            prov = layer.dataProvider()
            if prov and prov.name() == "postgres":
                uri = QgsDataSourceUri(prov.dataSourceUri())
                table_id = f"{uri.schema()}.{uri.table()}"
                for key, tid in catalog_tables.items():
                    if tid == table_id and key not in loaded:
                        loaded[key] = layer
                        break

    relation_manager = project.relationManager()
    rel_count = 0
    for parent_key, child_key, fk_field, rel_name in RELATION_DEFS:
        parent = loaded.get(parent_key)
        child = loaded.get(child_key)
        if not parent or not child:
            continue

        # Supprimer toute relation existante (possiblement cassee par QML)
        existing = relation_manager.relation(rel_name)
        if existing.id():
            relation_manager.removeRelation(rel_name)

        rel = QgsRelation()
        rel.setId(rel_name)
        rel.setName(rel_name)
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
                 selected_basemaps: set[str] | None = None) -> int:
    """Initialise le projet QGIS avec les couches selectionnees.

    Returns
    -------
    int
        Nombre de couches ajoutees.
    """
    project = QgsProject.instance()
    catalog = {entry[0]: entry for entry in LAYER_CATALOG}

    # -- CRS projet -------------------------------------------------------
    crs = QgsCoordinateReferenceSystem("EPSG:31370")
    project.setCrs(crs)
    _log("CRS projet: EPSG:31370 (Belgium Lambert 72)")

    # -- Creer les groupes necessaires ------------------------------------
    root = project.layerTreeRoot()
    groups = {}
    needed_groups = {catalog[k][1] for k in selected if k in catalog and catalog[k][1]}
    # Référence est exclu ici — sera cree apres les basemaps
    for group_name in ("Demand Points", "Infrastructure", "Zones",
                       "Topologie", "Chantier", "OSIRIS",
                       "Cadastre UrbIS", "Urbanisme"):
        if group_name not in needed_groups:
            continue
        existing = root.findGroup(group_name)
        groups[group_name] = existing or root.addGroup(group_name)

    # -- Detecter les couches deja presentes dans le projet -----------------
    existing_tables = set()
    for ly in project.mapLayers().values():
        if not isinstance(ly, QgsVectorLayer):
            continue
        prov = ly.dataProvider()
        if not prov:
            continue
        if prov.name() == "postgres":
            uri = prov.uri()
            existing_tables.add(f"{uri.schema()}.{uri.table()}")
        elif prov.name() == "WFS":
            # Identifier par le typename dans la source
            src = prov.uri().uri()
            for wfs_entry in LAYER_CATALOG:
                if wfs_entry[2] == "wfs" and wfs_entry[3] in src:
                    existing_tables.add(wfs_entry[3])

    # -- Charger les couches (dans l'ordre du catalogue) -------------------
    loaded = {}  # key → QgsVectorLayer
    count = 0
    skipped = 0

    # Iterer dans l'ordre du catalogue, pas dans l'ordre du set
    for entry in LAYER_CATALOG:
        key = entry[0]
        if key not in selected:
            continue
        _, group_name, schema, table, geom_col, pk, label = entry

        # Eviter les doublons
        table_id = table if key in WFS_KEYS else f"{schema}.{table}"
        if table_id in existing_tables:
            # Retrouver la couche existante pour les relations
            for ly in project.mapLayers().values():
                if not isinstance(ly, QgsVectorLayer):
                    continue
                prov = ly.dataProvider()
                if not prov:
                    continue
                if prov.name() == "postgres":
                    uri = prov.uri()
                    if f"{uri.schema()}.{uri.table()}" == table_id:
                        loaded[key] = ly
                        break
                elif prov.name() == "WFS" and table in prov.uri().uri():
                    loaded[key] = ly
                    break
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
            _log(f"Couche invalide: {table}", Qgis.Warning)
            continue

        if not group_name:
            # Couche de reference (sans groupe) — ajouter au projet
            # sans l'afficher dans le layer tree
            project.addMapLayer(layer, False)
        else:
            project.addMapLayer(layer, False)
            if group_name in groups:
                groups[group_name].addLayer(layer)
            else:
                root.addLayer(layer)

        loaded[key] = layer
        count += 1

    if skipped:
        _log(f"{skipped} couche(s) deja presente(s) — ignoree(s)")
    _log(f"{count} couche(s) chargee(s)")

    # -- Relations --------------------------------------------------------
    # Les relations doivent exister AVANT l'application des styles,
    # sinon les relation editors dans les QML (Documents, Splices)
    # ne trouvent pas leurs relations et restent vides.
    ensure_relations(loaded)

    # -- Styles -----------------------------------------------------------
    # 1. Styles par defaut depuis la BDD (prioritaires)
    db_styled: set[str] = set()
    if apply_styles:
        db_styled = _apply_styles_from_db(conn_params, password, loaded)
    # 2. Styles embarques uniquement pour les couches sans style BDD
    fallback = {k: v for k, v in loaded.items() if k not in db_styled}
    if fallback:
        _apply_embedded_styles(fallback)


    # -- Basemaps ---------------------------------------------------------
    if add_basemap and selected_basemaps:
        basemap_group = _add_basemaps(root, selected_basemaps)
        groups["Basemaps"] = basemap_group

    # -- Groupe Référence (en bas, apres les basemaps) --------------------
    if "Référence" in needed_groups:
        ref_group = root.findGroup("Référence") or root.addGroup("Référence")
        groups["Référence"] = ref_group
        # Deplacer les couches ref dans ce groupe
        for entry in LAYER_CATALOG:
            key = entry[0]
            if key not in loaded or entry[1] != "Référence":
                continue
            layer = loaded[key]
            node = root.findLayer(layer.id())
            if node and node.parent() != ref_group:
                clone = node.clone()
                ref_group.addChildNode(clone)
                node.parent().removeChildNode(node)
        ref_group.setExpanded(False)
        ref_group.setItemVisibilityChecked(False)

    # -- Nettoyer les couches fantomes a la racine -------------------------
    _cleanup_ghost_layers(root, groups)

    # -- Tamponner le projet avec operateur/version ------------------------
    stamp_project()
    _log(f"Projet identifie: operator={WYRE_OPERATOR} version={WYRE_PROJECT_VERSION} plugin={_plugin_version()}")

    return count


# =====================================================================
# Helpers
# =====================================================================

def _build_uri(conn_params, password, schema, table, geom_col, pk):
    uri = QgsDataSourceUri()
    uri.setConnection(
        conn_params.get("host", "localhost"),
        str(conn_params.get("port", 5432)),
        conn_params.get("dbname", "wyre_ftth"),
        conn_params.get("user", "ftth_editor"),
        password,
    )
    sslmode_val = conn_params.get("sslmode", "require")
    if sslmode_val:
        uri.setSslMode(
            QgsDataSourceUri.SslRequire
            if sslmode_val == "require"
            else QgsDataSourceUri.SslPrefer
        )
    uri.setDataSource(schema, table, geom_col, "", pk)
    uri.setParam("estimatedmetadata", "true")
    uri.setParam("checkPrimaryKeyUnicity", "0")
    return uri


def _cleanup_ghost_layers(root, groups):
    """Supprime les couches fantomes a la racine du layer tree.

    Les styles QML contiennent des references de relations qui peuvent
    pousser QGIS a creer des couches fantomes (sans groupe, a la racine).
    On les detecte et les supprime.
    """
    group_set = set(groups.values())
    removed = 0
    for child in list(root.children()):
        # Ne toucher qu'aux couches directement a la racine (pas dans un groupe)
        if child in group_set:
            continue
        if hasattr(child, "layerId"):
            # C'est un noeud de couche a la racine — c'est un fantome
            root.removeChildNode(child)
            removed += 1
    if removed:
        _log(f"{removed} couche(s) fantome(s) supprimee(s) de la racine")


def _apply_embedded_styles(loaded: dict):
    """Applique les styles QML embarques dans le plugin."""
    styles_dir = os.path.join(os.path.dirname(__file__), "styles")
    styled = 0
    for key, layer in loaded.items():
        qml_file = EMBEDDED_STYLES.get(key)
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
    """Ajoute les fonds de carte dans un groupe Basemaps."""
    project = QgsProject.instance()
    existing_names = {ly.name() for ly in project.mapLayers().values()}

    basemap_group = root.findGroup("Basemaps") or root.addGroup("Basemaps")
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
            basemap_group.addLayer(layer)
            added += 1
        else:
            _log(f"Basemap '{name}' invalide", Qgis.Warning)

    if added:
        _log(f"{added} basemap(s) ajoute(s)")

    return basemap_group



def _apply_styles_from_db(conn_params: dict, password: str, loaded: dict) -> set[str]:
    """Charge les styles QML par defaut depuis public.layer_styles.

    Returns
    -------
    set[str]
        Cles des couches pour lesquelles un style DB a ete applique.
    """
    styled_keys: set[str] = set()
    try:
        import psycopg2
    except ImportError:
        _log("psycopg2 indisponible — styles non appliques", Qgis.Warning)
        return styled_keys

    try:
        conn = psycopg2.connect(
            host=conn_params.get("host", "localhost"),
            port=conn_params.get("port", 5432),
            dbname=conn_params.get("dbname", "wyre_ftth"),
            user=conn_params.get("user", "ftth_editor"),
            password=password,
        )
        cur = conn.cursor()
    except Exception as exc:
        _log(f"Connexion styles impossible: {exc}", Qgis.Warning)
        return styled_keys

    for key, layer in loaded.items():
        provider = layer.dataProvider()
        if not provider:
            continue
        src_uri = QgsDataSourceUri(provider.uri().uri())
        schema = src_uri.schema() or "infra"
        table = src_uri.table()
        geom_col = src_uri.geometryColumn() or ""

        try:
            cur.execute(
                'SELECT styleqml::text FROM public.layer_styles '
                "WHERE f_table_schema = %s AND f_table_name = %s "
                "AND COALESCE(f_geometry_column, '') = %s AND useasdefault = true "
                "AND \"styleName\" = 'default' LIMIT 1",
                (schema, table, geom_col),
            )
            row = cur.fetchone()
        except Exception:
            continue

        if not row or not row[0]:
            continue

        try:
            fd, tmp_path = tempfile.mkstemp(suffix=".qml")
            with os.fdopen(fd, "w", encoding="utf-8") as tmp:
                tmp.write(row[0])
            msg, ok = layer.loadNamedStyle(tmp_path)
            if ok:
                layer.triggerRepaint()
                styled_keys.add(key)
            os.unlink(tmp_path)
        except Exception:
            pass

    conn.close()

    if styled_keys:
        _log(f"{len(styled_keys)} style(s) applique(s) depuis public.layer_styles")
    return styled_keys
