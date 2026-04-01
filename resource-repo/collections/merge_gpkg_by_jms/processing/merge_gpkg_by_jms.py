"""
Fusion GPKG par JMS - QgsProcessingAlgorithm
=============================================================================
Script Processing pour QGIS : fusionne les couches measured + tables GPS
regroupees par numero JMS (extrait du nom de fichier avant le '+').

Produit :
  - Un GPKG par JMS (optionnel)
  - Un GPKG global avec colonne jms_number (optionnel)

Apparait dans : Processing > Constructel > Fusion GPKG par JMS
"""

import os
import sqlite3
from collections import defaultdict

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    QgsApplication,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterBoolean,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransformContext,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsWkbTypes,
    QgsSingleSymbolRenderer,
    QgsCategorizedSymbolRenderer,
    QgsRendererCategory,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsProject,
)


# =====================================================================
# Recherche des fichiers QML de style
# =====================================================================
# Les scripts processing sont copies dans .../processing/scripts/ par
# QGIS Resource Sharing, tandis que les QML restent dans
# .../resource_sharing/collections/<collection>/style/.
# On cherche dans plusieurs emplacements ; si aucun QML n'est trouve,
# on applique un style programmatique en fallback.

_COLLECTION_NAME = 'merge_gpkg_by_jms'

_STYLE_FILES = {
    'measured_pxs_fo_duct_segment_infra':     'measured_duct_segment.qml',
    'measured_pxs_fo_branch_enclosure_infra': 'measured_branch_enclosure.qml',
    'measured_pxs_fo_manhole_infra':          'measured_manhole.qml',
}


def _find_style_dir():
    """Localise le dossier style/ de la collection, ou None."""
    # 1. Chemin relatif (execution directe depuis le repo ou la collection)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    local_style = os.path.join(os.path.dirname(script_dir), 'style')
    if os.path.isdir(local_style):
        return local_style

    # 2. Dossier Resource Sharing du profil QGIS actif
    try:
        profile_dir = QgsApplication.qgisSettingsDirPath()
        rs_style = os.path.join(
            profile_dir, 'resource_sharing', 'collections',
            _COLLECTION_NAME, 'style',
        )
        if os.path.isdir(rs_style):
            return rs_style
    except Exception:
        pass

    return None


def _resolve_style_qml(layer_name):
    """Retourne le chemin absolu du QML pour une couche, ou None."""
    qml_file = _STYLE_FILES.get(layer_name)
    if not qml_file:
        return None
    style_dir = _find_style_dir()
    if not style_dir:
        return None
    path = os.path.join(style_dir, qml_file)
    return path if os.path.isfile(path) else None


# =====================================================================
# Styles programmatiques (fallback si QML introuvables)
# =====================================================================

ENCLOSURE_COLORS = {
    'PXS_DTP-X':              QColor(0, 100, 255),
    'PXS_DTP-X400 HANDHOLE':  QColor(34, 180, 34),
    'PXS_T-BRANCH SRV':       QColor(255, 140, 0),
}
MANHOLE_COLORS = {
    'PXS_SMALL BAC ZTTH-4 CONCRETE':   QColor(180, 0, 180),
    'PXS_MOD BAC 1615X750X950':         QColor(0, 150, 130),
    'PXS_SMALL BAC MOD 1615X450X950':   QColor(100, 60, 150),
    'PXS_BIG BAC MOD 1600X750X950':     QColor(200, 80, 0),
    'PXS_SMALL BAC MONO 1615X450X950':  QColor(0, 120, 200),
}
FALLBACK_COLORS = [
    QColor(227, 26, 28),
    QColor(152, 78, 163),
    QColor(166, 86, 40),
    QColor(247, 129, 191),
    QColor(153, 153, 153),
    QColor(0, 210, 210),
]


def _apply_segment_style(layer):
    symbol = QgsLineSymbol.createSimple({
        'color': '220,30,30,255',
        'width': '0.6',
        'capstyle': 'round',
        'joinstyle': 'round',
    })
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))


def _apply_categorized_style(layer, color_map, marker_shape='circle',
                             marker_size='3.5'):
    field_name = 'feature_name'
    idx = layer.fields().indexOf(field_name)
    if idx < 0:
        return
    unique_values = sorted(
        v for v in layer.uniqueValues(idx) if v is not None and str(v).strip()
    )
    categories = []
    fallback_idx = 0
    for val in unique_values:
        val_str = str(val)
        if val_str in color_map:
            color = color_map[val_str]
        else:
            color = FALLBACK_COLORS[fallback_idx % len(FALLBACK_COLORS)]
            fallback_idx += 1
        symbol = QgsMarkerSymbol.createSimple({
            'name': marker_shape,
            'color': color.name(),
            'size': marker_size,
            'outline_color': 'black',
            'outline_width': '0.3',
        })
        categories.append(QgsRendererCategory(val_str, symbol, val_str))
    renderer = QgsCategorizedSymbolRenderer(field_name, categories)
    layer.setRenderer(renderer)


# =====================================================================
# Fonctions utilitaires
# =====================================================================

def list_gpkg_layers(gpkg_path):
    """Retourne la liste des noms de couches dans un GPKG via sqlite3."""
    try:
        conn = sqlite3.connect(gpkg_path)
        cursor = conn.execute(
            "SELECT table_name FROM gpkg_contents"
        )
        layers = [row[0] for row in cursor.fetchall()]
        conn.close()
        return layers
    except Exception:
        return []


def get_jms_number(filename):
    base = os.path.splitext(filename)[0]
    if '+' in base:
        return base.split('+')[0]
    return None


def scan_and_group_gpkg(source_dir):
    groups = defaultdict(list)
    for f in sorted(os.listdir(source_dir)):
        if f.upper().endswith('.GPKG'):
            jms = get_jms_number(f)
            if jms is not None:
                groups[jms].append(os.path.join(source_dir, f))
    return dict(sorted(groups.items()))


def _is_gpkg_autofid(vlayer, field_index):
    if field_index not in set(vlayer.primaryKeyAttributes()):
        return False
    field = vlayer.fields().field(field_index)
    return field.type() in (QVariant.Int, QVariant.LongLong)


def remap_fields(vlayer):
    new_fields = QgsFields()
    mapping = {}
    out_idx = 0
    for i in range(vlayer.fields().count()):
        if _is_gpkg_autofid(vlayer, i):
            continue
        field = vlayer.fields().field(i)
        if field.name().lower() == 'fid':
            renamed = QgsField('source_id', field.type(), field.typeName(),
                               field.length(), field.precision())
            new_fields.append(renamed)
        else:
            new_fields.append(field)
        mapping[out_idx] = field.name()
        out_idx += 1
    return new_fields, mapping


def write_features_to_gpkg(features, out_fields, geom_type, crs, path,
                           layer_name, append=False):
    if not append and os.path.exists(path):
        os.remove(path)

    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = layer_name
    opts.fileEncoding = "UTF-8"
    if append and os.path.exists(path):
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer

    writer = QgsVectorFileWriter.create(
        path, out_fields, geom_type, crs,
        QgsCoordinateTransformContext(), opts,
    )

    if writer.hasError() != QgsVectorFileWriter.NoError:
        return False

    for feat in features:
        writer.addFeature(feat)
    del writer
    return True


def collect_features(gpkg_files, layer_name):
    all_features = []
    out_fields = None
    field_mapping = None
    ref_crs = QgsCoordinateReferenceSystem()
    ref_geom_type = QgsWkbTypes.NoGeometry
    skipped = []

    for gpkg_path in gpkg_files:
        uri = f"{gpkg_path}|layername={layer_name}"
        vlayer = QgsVectorLayer(uri, "temp", "ogr")

        if not vlayer.isValid():
            skipped.append(os.path.basename(gpkg_path))
            continue
        if vlayer.featureCount() == 0:
            skipped.append(os.path.basename(gpkg_path) + " (vide)")
            continue

        if out_fields is None:
            out_fields, field_mapping = remap_fields(vlayer)
            ref_geom_type = vlayer.wkbType()
            if vlayer.crs().isValid():
                ref_crs = vlayer.crs()

        for feat in vlayer.getFeatures():
            new_feat = QgsFeature(out_fields)
            if ref_geom_type != QgsWkbTypes.NoGeometry:
                new_feat.setGeometry(feat.geometry())
            for new_idx, old_name in field_mapping.items():
                src_idx = feat.fields().indexOf(old_name)
                if src_idx >= 0:
                    new_feat.setAttribute(new_idx, feat.attribute(src_idx))
            all_features.append(new_feat)

    return all_features, out_fields, field_mapping, ref_geom_type, ref_crs, skipped


def merge_layer_to_gpkg(gpkg_files, layer_name, output_path, append=False):
    features, out_fields, _, geom_type, crs, skipped = collect_features(
        gpkg_files, layer_name
    )
    if not features or out_fields is None:
        return 0, False, skipped
    ok = write_features_to_gpkg(features, out_fields, geom_type, crs,
                                output_path, layer_name, append=append)
    if not ok:
        return 0, False, skipped
    return len(features), True, skipped


def _get_user_field_names(vlayer):
    names = []
    for i in range(vlayer.fields().count()):
        if _is_gpkg_autofid(vlayer, i):
            continue
        names.append(vlayer.fields().field(i).name())
    return names


def _build_merged_fields(vlayer):
    user_field_names = _get_user_field_names(vlayer)
    merged = QgsFields()
    merged.append(QgsField('jms_number', QVariant.String, 'QString', 10))
    for fname in user_field_names:
        idx = vlayer.fields().indexOf(fname)
        merged.append(vlayer.fields().field(idx))
    return merged, user_field_names


def create_merged_from_sources(groups, all_layers, output_path, feedback=None):
    if os.path.exists(output_path):
        os.remove(output_path)

    first_layer = True
    global_total = 0

    for layer_name in all_layers:
        all_features = []
        merged_fields = None
        user_field_names = None
        ref_crs = QgsCoordinateReferenceSystem()
        ref_geom_type = QgsWkbTypes.NoGeometry

        for jms, files in sorted(groups.items()):
            if feedback and feedback.isCanceled():
                return None
            for gpkg_path in files:
                uri = f"{gpkg_path}|layername={layer_name}"
                vlayer = QgsVectorLayer(uri, "temp", "ogr")
                if not vlayer.isValid() or vlayer.featureCount() == 0:
                    continue
                if merged_fields is None:
                    merged_fields, user_field_names = _build_merged_fields(vlayer)
                    ref_geom_type = vlayer.wkbType()
                    if vlayer.crs().isValid():
                        ref_crs = vlayer.crs()
                for feat in vlayer.getFeatures():
                    new_feat = QgsFeature(merged_fields)
                    if ref_geom_type != QgsWkbTypes.NoGeometry:
                        new_feat.setGeometry(feat.geometry())
                    new_feat.setAttribute(
                        merged_fields.indexOf('jms_number'), jms
                    )
                    for fname in user_field_names:
                        src_idx = feat.fields().indexOf(fname)
                        dst_idx = merged_fields.indexOf(fname)
                        if src_idx >= 0 and dst_idx >= 0:
                            new_feat.setAttribute(dst_idx, feat.attribute(src_idx))
                    all_features.append(new_feat)

        if all_features and merged_fields:
            ok = write_features_to_gpkg(
                all_features, merged_fields, ref_geom_type, ref_crs,
                output_path, layer_name, append=not first_layer
            )
            if ok:
                if feedback:
                    feedback.pushInfo(
                        f"  {layer_name}: {len(all_features)} entite(s)"
                    )
                global_total += len(all_features)
                first_layer = False

    return output_path if global_total > 0 else None


def apply_default_style(layer, layer_name):
    """Applique le style QML si disponible, sinon fallback programmatique."""
    # 1. Tenter le QML externe
    qml_path = _resolve_style_qml(layer_name)
    if qml_path:
        msg, ok = layer.loadNamedStyle(qml_path)
        if ok:
            layer.triggerRepaint()
            return

    # 2. Fallback programmatique
    if 'duct_segment' in layer_name:
        _apply_segment_style(layer)
    elif 'branch_enclosure' in layer_name:
        _apply_categorized_style(layer, ENCLOSURE_COLORS, 'circle', '3.5')
    elif 'manhole' in layer_name:
        _apply_categorized_style(layer, MANHOLE_COLORS, 'square', '4.0')
    layer.triggerRepaint()


def add_layers_to_group(gpkg_path, layer_names, group, prefix=""):
    """Ajoute les couches d'un GPKG dans un groupe du projet avec style."""
    project = QgsProject.instance()
    loaded = []
    for lname in layer_names:
        uri = f"{gpkg_path}|layername={lname}"
        display = f"{prefix}_{lname}" if prefix else lname
        layer = QgsVectorLayer(uri, display, "ogr")
        if not layer.isValid() or layer.featureCount() == 0:
            continue
        apply_default_style(layer, lname)
        project.addMapLayer(layer, False)
        group.addLayer(layer)
        loaded.append(lname)
    return loaded


# =====================================================================
# QgsProcessingAlgorithm
# =====================================================================

class MergeGpkgByJms(QgsProcessingAlgorithm):

    INPUT_DIR = 'INPUT_DIR'
    OUTPUT_DIR = 'OUTPUT_DIR'
    SEGMENTS = 'SEGMENTS'
    CHAMBRES = 'CHAMBRES'
    MANHOLES = 'MANHOLES'
    TABLE_POINT = 'TABLE_POINT'
    TABLE_MEASURE = 'TABLE_MEASURE'
    OUTPUT_PER_JMS = 'OUTPUT_PER_JMS'
    OUTPUT_GLOBAL = 'OUTPUT_GLOBAL'

    def name(self):
        return 'merge_gpkg_by_jms'

    def displayName(self):
        return 'Fusion GPKG par JMS'

    def group(self):
        return 'Constructel'

    def groupId(self):
        return 'constructel'

    def shortHelpString(self):
        return (
            "Fusionne les fichiers GPKG regroupes par numero JMS.\n\n"
            "Le numero JMS est extrait du nom de fichier (partie avant le '+').\n"
            "Ex: 612150+abc.gpkg -> JMS 612150\n\n"
            "Produit un GPKG par JMS et/ou un GPKG global avec colonne jms_number."
        )

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def createInstance(self):
        return MergeGpkgByJms()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFile(
            self.INPUT_DIR,
            'Dossier source (contenant les GPKG)',
            behavior=QgsProcessingParameterFile.Folder,
        ))
        self.addParameter(QgsProcessingParameterFolderDestination(
            self.OUTPUT_DIR,
            'Dossier de sortie',
        ))

        # Couches geometriques
        self.addParameter(QgsProcessingParameterBoolean(
            self.SEGMENTS,
            'Segments (measured_pxs_fo_duct_segment_infra)',
            defaultValue=True,
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.CHAMBRES,
            'Chambres (measured_pxs_fo_branch_enclosure_infra)',
            defaultValue=True,
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.MANHOLES,
            'Manholes (measured_pxs_fo_manhole_infra)',
            defaultValue=True,
        ))

        # Tables attributaires
        self.addParameter(QgsProcessingParameterBoolean(
            self.TABLE_POINT,
            'Table Point (GPS bruts)',
            defaultValue=False,
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.TABLE_MEASURE,
            'Table Measure (liaison point-element)',
            defaultValue=False,
        ))

        # Modes de sortie
        self.addParameter(QgsProcessingParameterBoolean(
            self.OUTPUT_PER_JMS,
            'Un GPKG par JMS',
            defaultValue=True,
        ))
        self.addParameter(QgsProcessingParameterBoolean(
            self.OUTPUT_GLOBAL,
            'Un GPKG global (ALL_JMS_measured_infra.gpkg)',
            defaultValue=True,
        ))

    def processAlgorithm(self, parameters, context, feedback):
        source_dir = self.parameterAsString(parameters, self.INPUT_DIR, context)
        output_dir = self.parameterAsString(parameters, self.OUTPUT_DIR, context)
        os.makedirs(output_dir, exist_ok=True)

        # Construire la liste des couches demandees
        all_layers = []
        if self.parameterAsBool(parameters, self.SEGMENTS, context):
            all_layers.append('measured_pxs_fo_duct_segment_infra')
        if self.parameterAsBool(parameters, self.CHAMBRES, context):
            all_layers.append('measured_pxs_fo_branch_enclosure_infra')
        if self.parameterAsBool(parameters, self.MANHOLES, context):
            all_layers.append('measured_pxs_fo_manhole_infra')
        if self.parameterAsBool(parameters, self.TABLE_POINT, context):
            all_layers.append('Point')
        if self.parameterAsBool(parameters, self.TABLE_MEASURE, context):
            all_layers.append('Measure')

        if not all_layers:
            feedback.reportError("Aucune couche selectionnee.")
            return {}

        do_per_jms = self.parameterAsBool(parameters, self.OUTPUT_PER_JMS, context)
        do_global = self.parameterAsBool(parameters, self.OUTPUT_GLOBAL, context)

        if not do_per_jms and not do_global:
            feedback.reportError("Selectionnez au moins un mode de sortie.")
            return {}

        # 1. Scanner les GPKG
        groups = scan_and_group_gpkg(source_dir)
        feedback.pushInfo(f"JMS trouves: {len(groups)}")
        for jms, files in groups.items():
            feedback.pushInfo(f"  JMS {jms}: {len(files)} fichier(s)")

        # Diagnostic: lister les couches du premier GPKG trouve
        first_files = next(iter(groups.values()), [])
        if first_files:
            sample = first_files[0]
            layers_in_gpkg = list_gpkg_layers(sample)
            feedback.pushInfo(
                f"\n--- DIAGNOSTIC ---\n"
                f"Fichier exemple: {os.path.basename(sample)}\n"
                f"Couches trouvees: {layers_in_gpkg}\n"
                f"Couches attendues: {all_layers}\n"
            )

        if not groups:
            feedback.reportError(
                "Aucun fichier GPKG avec numero JMS trouve dans le dossier."
            )
            return {}

        total_jms = len(groups)
        jms_layers = {}
        total_features = 0
        total_jms_ok = 0

        # 2. GPKG par JMS
        if do_per_jms:
            feedback.pushInfo("\n--- FUSION PAR JMS ---")
            for step, (jms, files) in enumerate(groups.items()):
                if feedback.isCanceled():
                    return {}

                output_gpkg = os.path.join(
                    output_dir, f"{jms}_measured_infra.gpkg"
                )
                feedback.pushInfo(f"\n[JMS {jms}] {len(files)} fichier(s)")

                jms_has_data = False
                for idx, layer_name in enumerate(all_layers):
                    append = (idx > 0 and jms_has_data)
                    count, success, skipped = merge_layer_to_gpkg(
                        files, layer_name, output_gpkg, append=append
                    )
                    if success:
                        feedback.pushInfo(f"  {layer_name}: {count}")
                        total_features += count
                        jms_has_data = True
                    elif skipped:
                        feedback.pushInfo(
                            f"  {layer_name}: 0 (ignores: {', '.join(skipped)})"
                        )
                    else:
                        feedback.pushInfo(f"  {layer_name}: 0")

                if jms_has_data:
                    jms_layers[jms] = output_gpkg
                    total_jms_ok += 1

                feedback.setProgress(int((step + 1) / total_jms * 50))

        # 3. GPKG global
        merged_gpkg = None
        if do_global:
            feedback.pushInfo("\n--- GPKG GLOBAL ---")
            merged_path = os.path.join(output_dir, "ALL_JMS_measured_infra.gpkg")

            if do_per_jms and jms_layers:
                # Fusionner depuis les GPKG par JMS deja produits
                if os.path.exists(merged_path):
                    os.remove(merged_path)
                first_layer = True
                global_total = 0
                for layer_name in all_layers:
                    all_features = []
                    merged_fields = None
                    user_field_names = None
                    ref_crs = QgsCoordinateReferenceSystem()
                    ref_geom_type = QgsWkbTypes.NoGeometry

                    for jms_number, gpkg_path in sorted(jms_layers.items()):
                        if feedback.isCanceled():
                            return {}
                        uri = f"{gpkg_path}|layername={layer_name}"
                        vlayer = QgsVectorLayer(uri, "temp", "ogr")
                        if not vlayer.isValid() or vlayer.featureCount() == 0:
                            continue
                        if merged_fields is None:
                            merged_fields, user_field_names = _build_merged_fields(vlayer)
                            ref_geom_type = vlayer.wkbType()
                            if vlayer.crs().isValid():
                                ref_crs = vlayer.crs()
                        for feat in vlayer.getFeatures():
                            new_feat = QgsFeature(merged_fields)
                            if ref_geom_type != QgsWkbTypes.NoGeometry:
                                new_feat.setGeometry(feat.geometry())
                            new_feat.setAttribute(
                                merged_fields.indexOf('jms_number'), jms_number
                            )
                            for fname in user_field_names:
                                src_idx = feat.fields().indexOf(fname)
                                dst_idx = merged_fields.indexOf(fname)
                                if src_idx >= 0 and dst_idx >= 0:
                                    new_feat.setAttribute(
                                        dst_idx, feat.attribute(src_idx)
                                    )
                            all_features.append(new_feat)

                    if all_features and merged_fields:
                        ok = write_features_to_gpkg(
                            all_features, merged_fields, ref_geom_type, ref_crs,
                            merged_path, layer_name, append=not first_layer
                        )
                        if ok:
                            feedback.pushInfo(
                                f"  {layer_name}: {len(all_features)} entite(s)"
                            )
                            global_total += len(all_features)
                            first_layer = False

                if global_total > 0:
                    merged_gpkg = merged_path
            else:
                # Fusionner directement depuis les sources
                merged_gpkg = create_merged_from_sources(
                    groups, all_layers, merged_path, feedback
                )

            feedback.setProgress(90)

        # 4. Charger les couches dans le projet avec groupes
        root = QgsProject.instance().layerTreeRoot()

        if do_per_jms and jms_layers:
            feedback.pushInfo("\n--- CHARGEMENT PROJET ---")
            for jms_number, gpkg_path in sorted(jms_layers.items()):
                if not os.path.exists(gpkg_path):
                    continue
                group = root.addGroup(f"JMS {jms_number}")
                loaded = add_layers_to_group(
                    gpkg_path, all_layers, group, prefix=jms_number
                )
                if loaded:
                    feedback.pushInfo(
                        f"  Groupe JMS {jms_number}: {', '.join(loaded)}"
                    )
                else:
                    root.removeChildNode(group)

        if merged_gpkg:
            merged_group = root.insertGroup(0, "ALL JMS (global)")
            loaded = add_layers_to_group(
                merged_gpkg, all_layers, merged_group, prefix="ALL"
            )
            if loaded:
                feedback.pushInfo(
                    f"  Groupe global: {', '.join(loaded)}"
                )
            else:
                root.removeChildNode(merged_group)

        # Resume
        feedback.pushInfo("\n=== TERMINE ===")
        if do_per_jms:
            feedback.pushInfo(f"  JMS traites  : {total_jms_ok}/{total_jms}")
            feedback.pushInfo(f"  Total entites: {total_features}")
        if merged_gpkg:
            feedback.pushInfo(
                f"  GPKG global  : {os.path.basename(merged_gpkg)}"
            )

        feedback.setProgress(100)

        results = {self.OUTPUT_DIR: output_dir}
        return results
