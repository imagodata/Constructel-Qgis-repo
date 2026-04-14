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

    # -- Reference (toujours charge, cache dans groupe Ref) ---------------
    ("v_form_lists",       None,              "ref",   "v_form_lists",        None,  "rid", "Listes formulaires"),
]


# =====================================================================
# TEMPLATES — presets de selection
# =====================================================================

TEMPLATES = {
    "infra": {
        "label": "Infrastructure + Listes",
        "description": "Couches infra de base : zones, structures, cables, conduites, DP + listes ref",
        "layers": {
            "zone_mro", "zone_pop", "zone_distribution", "zone_drop",
            "structures", "ducts", "subducts", "cables", "splices",
            "demand_points", "topo_violations", "v_form_lists",
        },
        "basemap": True,
    },
    "infra_chantier": {
        "label": "Infrastructure + Chantier",
        "description": "Infra complet + couches chantier (interventions, permis, incidents)",
        "layers": {
            "zone_mro", "zone_pop", "zone_distribution", "zone_drop",
            "structures", "ducts", "subducts", "cables", "splices",
            "demand_points", "topo_violations",
            "interventions", "incidents", "permis_voirie", "plaintes",
            "interventions_chantier", "synergies",
            "v_form_lists",
        },
        "basemap": True,
    },
    "infra_osiris": {
        "label": "Infrastructure + OSIRIS",
        "description": "Infra complet + couches OSIRIS Brussels (zones gelees, chantiers, coordination)",
        "layers": {
            "zone_mro", "zone_pop", "zone_distribution", "zone_drop",
            "structures", "ducts", "subducts", "cables", "splices",
            "demand_points", "topo_violations",
            "osiris_frozen", "osiris_worksites", "osiris_autorises",
            "osiris_phases", "osiris_hypercoord", "osiris_deviations", "osiris_events",
            "v_form_lists",
        },
        "basemap": True,
    },
    "complet": {
        "label": "Projet complet",
        "description": "Toutes les couches : infra + chantier + OSIRIS",
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

    # Splices
    ("structures",     "splices",            "structure_id",         "splices_to_structure"),
    ("cables",         "splices",            "cable_id",             "splices_to_cable"),

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
    # -- Stadia Maps (Stamen) --
    {
        "key": "stamen_toner",
        "name": "Stamen Toner",
        "group": "Stadia Maps",
        "source": (
            "type=xyz"
            "&url=https://tiles.stadiamaps.com/tiles/stamen_toner/{z}/{x}/{y}.png"
            "&zmax=19&zmin=0"
        ),
        "provider": "wms",
        "default": False,
    },
    {
        "key": "stamen_toner_lite",
        "name": "Stamen Toner Lite",
        "group": "Stadia Maps",
        "source": (
            "type=xyz"
            "&url=https://tiles.stadiamaps.com/tiles/stamen_toner_lite/{z}/{x}/{y}.png"
            "&zmax=19&zmin=0"
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

# Donnees cadastrales WFS UrbIS
WFS_URL = "https://geoservices-vector.irisnet.be/geoserver/urbisvector/wfs"
WFS_SRS = "EPSG:31370"
WFS_VERSION = "2.0.0"

CADASTRAL_WFS = [
    {
        "key": "wfs_parcels",
        "name": "Parcelles cadastrales",
        "typename": "urbisvector:Capa",
        "tr_key": "init.wfs_parcels",
        "default": False,
    },
    {
        "key": "wfs_buildings",
        "name": "Batiments",
        "typename": "urbisvector:Bu",
        "tr_key": "init.wfs_buildings",
        "default": False,
    },
]


def _log(msg, level=Qgis.Info):
    QgsMessageLog.logMessage(msg, TAG, level=level)


# =====================================================================
# DIALOG — selection des couches avec templates
# =====================================================================

class InitProjectDialog(QDialog):
    """Dialog de selection des couches avec templates pre-configures."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("init.title"))
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

            item = QTreeWidgetItem(self._group_items[group], [f"{label}  ({schema}.{table})"])
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

        # Cadastre WFS — couches individuelles
        cadastre_label = QLabel(tr("init.cadastre_header"))
        cadastre_label.setStyleSheet("font-weight: bold; margin-top: 4px;")
        basemap_layout.addWidget(cadastre_label)

        self._cadastre_items = {}
        for wfs in CADASTRAL_WFS:
            chk = QCheckBox(tr(wfs["tr_key"]))
            chk.setChecked(wfs.get("default", False))
            basemap_layout.addWidget(chk)
            self._cadastre_items[wfs["key"]] = chk

        layout.addWidget(basemap_box)

        # -- Options ----------------------------------------------------------
        self._chk_styles = QCheckBox(tr("init.apply_styles"))
        self._chk_styles.setChecked(True)
        layout.addWidget(self._chk_styles)

        # -- Buttons ----------------------------------------------------------
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.Ok).setText(tr("init.btn_init"))
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

    def selected_cadastre(self) -> set[str]:
        """Retourne les keys des couches cadastrales selectionnees."""
        return {k for k, chk in self._cadastre_items.items() if chk.isChecked()}

    def want_cadastre(self) -> bool:
        return bool(self.selected_cadastre())

    def want_styles(self) -> bool:
        return self._chk_styles.isChecked()


# =====================================================================
# INIT PROJECT — logique principale
# =====================================================================

def init_project(conn_params: dict, password: str, selected: set[str],
                 add_basemap: bool = True, apply_styles: bool = True,
                 selected_basemaps: set[str] | None = None,
                 add_cadastre: bool = False,
                 selected_cadastre: set[str] | None = None) -> int:
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
    for group_name in ("Demand Points", "Infrastructure", "Zones",
                       "Topologie", "Chantier", "OSIRIS"):
        if group_name not in needed_groups:
            continue
        existing = root.findGroup(group_name)
        groups[group_name] = existing or root.addGroup(group_name)

    # -- Charger les couches ----------------------------------------------
    loaded = {}  # key → QgsVectorLayer
    count = 0

    for key in selected:
        entry = catalog.get(key)
        if not entry:
            continue
        _, group_name, schema, table, geom_col, pk, label = entry

        uri = _build_uri(conn_params, password, schema, table, geom_col, pk)
        layer = QgsVectorLayer(uri.uri(False), table, "postgres")
        if not layer.isValid():
            _log(f"Couche invalide: {schema}.{table}", Qgis.Warning)
            continue

        project.addMapLayer(layer, False)

        if group_name and group_name in groups:
            groups[group_name].addLayer(layer)
        else:
            root.addLayer(layer)

        loaded[key] = layer
        count += 1
        _log(f"  + {schema}.{table}")

    _log(f"{count} couche(s) chargee(s)")

    # -- Styles -----------------------------------------------------------
    if apply_styles:
        _apply_styles_from_db(conn_params, password, loaded)

    # -- Relations --------------------------------------------------------
    relation_manager = project.relationManager()
    rel_count = 0
    for parent_key, child_key, fk_field, rel_name in RELATION_DEFS:
        parent = loaded.get(parent_key)
        child = loaded.get(child_key)
        if not parent or not child:
            continue
        if relation_manager.relation(rel_name).isValid():
            continue

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
        _log(f"{rel_count} relation(s) creee(s)")

    # -- Basemaps ---------------------------------------------------------
    if add_basemap and selected_basemaps:
        _add_basemaps(root, selected_basemaps)

    # -- Cadastre WFS -----------------------------------------------------
    if add_cadastre and selected_cadastre:
        _add_cadastre(root, selected_cadastre)

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


def _add_basemaps(root, selected_keys: set[str]):
    """Ajoute les fonds de carte selectionnes en bas du layer tree."""
    project = QgsProject.instance()
    existing_names = {ly.name() for ly in project.mapLayers().values()}

    basemap_by_key = {bm["key"]: bm for bm in BASEMAPS}

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
            root.addLayer(layer)
            _log(f"Basemap '{name}' ajoute")
        else:
            _log(f"Basemap '{name}' invalide", Qgis.Warning)


def _add_cadastre(root, selected_keys: set[str]):
    """Ajoute les couches cadastrales WFS UrbIS selectionnees."""
    project = QgsProject.instance()
    existing_names = {ly.name() for ly in project.mapLayers().values()}
    wfs_by_key = {wfs["key"]: wfs for wfs in CADASTRAL_WFS}

    for key in selected_keys:
        cfg = wfs_by_key.get(key)
        if not cfg:
            continue
        name = cfg["name"]
        if name in existing_names:
            _log(f"Cadastre '{name}' deja present")
            continue

        source = (
            f"pagingEnabled='true' "
            f"preferCoordinatesForWfsT11='false' "
            f"restrictToRequestBBOX='1' "
            f"srsname='{WFS_SRS}' "
            f"typename='{cfg['typename']}' "
            f"url='{WFS_URL}' "
            f"version='{WFS_VERSION}'"
        )
        layer = QgsVectorLayer(source, name, "WFS")
        if layer.isValid():
            project.addMapLayer(layer, False)
            root.addLayer(layer)
            _log(f"Cadastre '{name}' ajoute")
        else:
            _log(f"Cadastre '{name}' invalide", Qgis.Warning)


def _apply_styles_from_db(conn_params: dict, password: str, loaded: dict):
    """Charge les styles QML par defaut depuis public.layer_styles."""
    try:
        import psycopg2
    except ImportError:
        _log("psycopg2 indisponible — styles non appliques", Qgis.Warning)
        return

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
        return

    styled = 0
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
                "AND f_geometry_column = %s AND useasdefault = true "
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
                styled += 1
            os.unlink(tmp_path)
        except Exception:
            pass

    conn.close()

    if styled:
        _log(f"{styled} style(s) applique(s) depuis public.layer_styles")
