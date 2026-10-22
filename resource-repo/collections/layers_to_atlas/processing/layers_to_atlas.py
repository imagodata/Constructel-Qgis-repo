"""Atlas PDF générique autonome pour la boîte à outils Processing QGIS.

Les entités déterminent le périmètre ; les couches cartographiées gardent leurs
styles et leur contexte. Aucun accès SQL/réseau propre ni dépendance à un autre
script Processing. Le découpage conserve la grille et les intérieurs polygonaux.
"""

import math
import os
import shutil
import tempfile
import unicodedata
from datetime import date

try:
    from qgis.core import (
        QgsCoordinateTransform,
        QgsFeature,
        QgsFeatureRequest,
        QgsField,
        QgsGeometry,
        QgsLayerTree,
        QgsLayerTreeModel,
        QgsLayoutExporter,
        QgsLayoutItemLabel,
        QgsLayoutItemLegend,
        QgsLayoutItemMap,
        QgsLayoutItemPage,
        QgsLayoutItemPicture,
        QgsLayoutItemScaleBar,
        QgsLayoutItemShape,
        QgsLayoutObject,
        QgsLayoutPoint,
        QgsLayoutSize,
        QgsLayoutUtils,
        QgsLegendRenderer,
        QgsLegendStyle,
        QgsMapLayerLegendUtils,
        QgsPalLayerSettings,
        QgsPointXY,
        QgsPrintLayout,
        QgsProcessing,
        QgsProcessingAlgorithm,
        QgsProcessingException,
        QgsProcessingParameterDefinition,
        QgsProcessingParameterBoolean,
        QgsProcessingParameterCrs,
        QgsProcessingParameterEnum,
        QgsProcessingParameterExtent,
        QgsProcessingParameterFile,
        QgsProcessingParameterFileDestination,
        QgsProcessingParameterMultipleLayers,
        QgsProcessingParameterNumber,
        QgsProcessingParameterString,
        QgsProcessingParameterVectorLayer,
        QgsProperty,
        QgsRasterLayer,
        QgsRectangle,
        QgsRuleBasedRenderer,
        QgsScaleBarSettings,
        QgsTextFormat,
        QgsUnitTypes,
        QgsVectorFileWriter,
        QgsVectorLayer,
        QgsVectorLayerSimpleLabeling,
        QgsWkbTypes,
    )
    from qgis.PyQt import sip
    from qgis.PyQt.QtCore import Qt, QUrl, QVariant
    from qgis.PyQt.QtGui import QColor, QDesktopServices, QFont, QImage
    from qgis.PyQt.QtSvg import QSvgRenderer

    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False

MAX_CELLS = 10000
MAX_VISITS = 200000
SCRIPT_VERSION = "1.2.0"
LEGEND_WIDTH_MM = 54
DEFAULT_LOGO = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "svg", "constructel.svg"))


def _default_index_path(pdf_path):
    """Choisit un nouvel index sans écraser un GPKG ou sa copie de logo."""
    stem = os.path.splitext(pdf_path)[0] + "_plans"
    path, suffix = stem + ".gpkg", 2
    while os.path.exists(path) or any(
        os.path.exists(os.path.splitext(path)[0] + "_logo" + extension)
        for extension in (".svg", ".png", ".jpg", ".jpeg")
    ):
        path, suffix = f"{stem}_{suffix}.gpkg", suffix + 1
    return path


def page_geometry(paper, sidebar=True):
    pw, ph = {"A3": (420, 297), "A4": (297, 210)}[paper]
    return pw, ph, pw - (74 if sidebar else 16), ph - 55


def _literal_label_text(value):
    """Préserve les titres contenant [% expression %] comme du texte utilisateur."""
    escaped = value.replace("'", "''").replace("%", "' || char(37) || '")
    return "[% '" + escaped + "' %]"


def _bounds_union(a, b):
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def _check_cancel(canceled):
    if canceled and canceled():
        raise ValueError("Génération annulée.")


def wrap_legend_text(text, width, measure):
    """Wrap even unspaced identifiers, without abbreviating legend content.

    ``measure`` returns a text width in millimeters. Existing newlines remain;
    only whitespace at a newly introduced line break is removed.
    """
    if not math.isfinite(width) or width <= 0:
        raise ValueError("Largeur de texte de légende positive requise.")
    lines = []
    for paragraph in str(text).split("\n"):
        remainder = paragraph
        while remainder and measure(remainder) > width:
            low, high = 1, len(remainder)
            while low < high:
                middle = (low + high + 1) // 2
                if measure(remainder[:middle]) <= width:
                    low = middle
                else:
                    high = middle - 1
            # At least one character ensures progress, even with an oversized glyph.
            stop = low
            for position in reversed(range(1, low + 1)):
                if remainder[position - 1].isspace():
                    stop = position
                    break
            lines.append(remainder[:stop].rstrip())
            remainder = remainder[stop:].lstrip()
        if remainder or not paragraph:
            lines.append(remainder)
    return "\n".join(lines)


def legend_profiles():
    """One configuration must fit ALL pages; never reduce text below 7 pt."""
    return ((8, 1), (7, 1), (8, 2), (7, 2))


def legend_overflow_message(page_id, required, available):
    width, height = required
    max_width, max_height = available
    return (
        f"Légende trop grande — page {page_id} : {width:.1f} × {height:.1f} mm "
        f"nécessaires, {max_width:.1f} × {max_height:.1f} mm disponibles, "
        "après essais à 8/7 pt et sur 1/2 colonnes. "
        "Réduire les couches/classes de légende ou désactiver la légende. "
        "A3 augmente la hauteur disponible, pas la largeur de la légende. "
        "Aucun export final n'a été écrit."
    )


def grid_spec(bounds, width, height, overlap=10):
    """Grille ancrée au sud-ouest ; le recouvrement ne réduit jamais la couverture."""
    if len(bounds) != 4 or any(not math.isfinite(v) for v in bounds):
        raise ValueError("Emprise finie requise.")
    if bounds[2] < bounds[0] or bounds[3] < bounds[1]:
        raise ValueError("Bornes de l'emprise inversées.")
    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
        raise ValueError("Dimensions de carte positives et finies requises.")
    if not math.isfinite(overlap) or not 0 <= overlap <= 40:
        raise ValueError("Recouvrement entre 0 et 40 % requis.")
    sx, sy = width * (1 - overlap / 100), height * (1 - overlap / 100)
    nx = max(1, math.ceil((bounds[2] - bounds[0]) / sx))
    ny = max(1, math.ceil((bounds[3] - bounds[1]) / sy))
    return sx, sy, nx, ny


def cell_extent(key, origin, width, height, overlap=10):
    sx, sy = width * (1 - overlap / 100), height * (1 - overlap / 100)
    x = origin[0] + key[0] * sx - (width - sx) / 2
    y = origin[1] + key[1] * sy - (height - sy) / 2
    return x, y, x + width, y + height


def extent_plans(bounds, width, height, overlap=10, canceled=None):
    _, _, nx, ny = grid_spec(bounds, width, height, overlap)
    if nx * ny > MAX_CELLS:
        raise ValueError("Plus de 10 000 plans : réduire l'emprise ou augmenter l'échelle.")
    plans = []
    for y in reversed(range(ny)):
        _check_cancel(canceled)
        for x in range(nx):
            plans.append(cell_extent((x, y), bounds, width, height, overlap))
    return plans


if HAS_QGIS:

    def _legend_labels(legend):
        model = legend.model()
        return [
            (
                node,
                node.name(),
                [str(item.data(Qt.ItemDataRole.DisplayRole) or "") for item in model.layerOriginalLegendNodes(node)],
            )
            for node in model.rootGroup().findLayers()
        ]

    def _apply_legend_profile(legend, labels, font_size, columns):
        """Change only the layout's private tree, never source names or styles."""
        font = QFont("Sans Serif", font_size)
        legend.setStyleFont(QgsLegendStyle.Style.Title, QFont("Sans Serif", 9, QFont.Weight.Bold))
        for component in (
            QgsLegendStyle.Style.Group,
            QgsLegendStyle.Style.Subgroup,
            QgsLegendStyle.Style.SymbolLabel,
        ):
            legend.setStyleFont(component, font)
        legend.setColumnCount(columns)
        legend.setSplitLayer(columns > 1)
        legend.setColumnSpace(2)
        legend.setBoxSpace(1)
        # Reserve space for symbols, their left margin, and rounding differences.
        text_width = (LEGEND_WIDTH_MM - 2 - (columns - 1) * 2) / columns - 12
        legend.setAutoWrapLinesAfter(text_width)

        def measure(text):
            return QgsLayoutUtils.textWidthMM(font, text)

        for node, name, entries in labels:
            node.setUseLayerName(False)
            node.setName(wrap_legend_text(name, text_width, measure))
            for index, label in enumerate(entries):
                QgsMapLayerLegendUtils.setLegendNodeUserLabel(
                    node, index, wrap_legend_text(label, text_width, measure)
                )
            legend.model().refreshLayerLegend(node)

    def _fit_atlas_legend(layout, options, page_height, feedback):
        legend = layout.itemById("atlas_legend")
        if legend is None:
            return
        labels = _legend_labels(legend)
        atlas = layout.atlas()
        available_height = page_height - (
            95 if options["SHOW_NORTH"] else 70 if options["SHOW_SCALEBAR"] else 54
        )
        if not atlas.beginRender():
            raise QgsProcessingException("Impossible de préparer la légende de l'atlas.")
        overflow = None
        try:
            for font_size, columns in legend_profiles():
                _check_cancel(feedback.isCanceled)
                _apply_legend_profile(legend, labels, font_size, columns)
                overflow = None
                for index in range(atlas.count()):
                    _check_cancel(feedback.isCanceled)
                    if not atlas.seekTo(index):
                        raise QgsProcessingException(f"Impossible de préparer la page {index + 1}.")
                    page = layout.reportContext().feature()
                    if page["page_type"] == "cover" or not (
                        options["OVERVIEW_SHOW_LEGEND"] if page["overview"] else options["SHOW_LEGEND"]
                    ):
                        continue
                    legend.updateFilterByMap()
                    # updateFilterByMap defers the hit-test until paint. Measure the
                    # synchronous filtered model now, before writing any final file.
                    if options["LEGEND_FILTER_BY_MAP"]:
                        map_item = layout.itemById("atlas_map")
                        pixel_size = map_item.rect().size() * (200 / 25.4)
                        settings = map_item.mapSettings(map_item.extent(), pixel_size, 200, True)
                        settings.setExpressionContext(legend.createExpressionContext())
                        legend.model().setLayerStyleOverrides(map_item.layerStyleOverrides())
                        legend.model().setLegendFilterByMap(settings)
                        _check_cancel(feedback.isCanceled)
                    else:
                        legend.model().setLegendFilterByMap(None)
                    required = QgsLegendRenderer(legend.model(), legend.legendSettings()).minimumSize()
                    if required.width() > LEGEND_WIDTH_MM or required.height() > available_height:
                        # Only report the synthetic page number, not private layer labels.
                        overflow = legend_overflow_message(
                            index + 1,
                            (required.width(), required.height()),
                            (LEGEND_WIDTH_MM, available_height),
                        )
                        break
                if overflow is None:
                    legend.adjustBoxSize()
                    legend.setCustomProperty("map_atlas/legend_font_pt", font_size)
                    legend.setCustomProperty("map_atlas/legend_columns", columns)
                    feedback.pushInfo(
                        f"Légende validée sur toutes les pages : {font_size} pt, {columns} colonne(s)."
                    )
                    return
            raise QgsProcessingException(overflow)
        except ValueError as exc:
            raise QgsProcessingException(str(exc)) from exc
        finally:
            atlas.endRender()

    def _is_project_background(layer, node):
        """Rasters ou fonds volontairement désignés, jamais des couches métier au hasard."""
        marker = str(layer.customProperty("map_atlas/background", False)).lower()
        if isinstance(layer, QgsRasterLayer) or marker in ("true", "1", "yes"):
            return True
        groups = {
            "fond",
            "fonds",
            "fond de plan",
            "fonds de plan",
            "fonds de plans",
            "fond de carte",
            "fonds de carte",
            "basemap",
            "basemaps",
            "base map",
            "base maps",
            "background",
            "backgrounds",
        }
        parent = node.parent() if node is not None else None
        while parent is not None:
            name = unicodedata.normalize("NFKD", parent.name()).casefold()
            name = "".join(char for char in name if not unicodedata.combining(char))
            name = " ".join(name.replace("_", " ").replace("-", " ").split())
            if name in groups:
                return True
            parent = parent.parent()
        return False

    def _map_layers(project, selected, include_backgrounds):
        tree = project.layerTreeRoot()
        order = tree.layerOrder()
        # Même source native que QgsLayoutItemMap : groupes rendus comme une
        # couche, visibilité des parents et ordre personnalisé sont respectés.
        visible = [
            layer for layer in project.mapThemeCollection().masterVisibleLayers()
            if not layer.customProperty("map_atlas/index", False)
            and not layer.customProperty("gofiber/atlas_index", False)
        ]
        if not selected:
            return visible
        chosen = {layer.id(): layer for layer in selected}
        if include_backgrounds:
            chosen.update(
                {layer.id(): layer for layer in visible
                 if _is_project_background(layer, tree.findLayer(layer.id()))}
            )
        # Même un choix explicite respecte l'ordre du projet, fonds compris.
        ordered = [chosen.pop(layer.id()) for layer in order if layer.id() in chosen]
        return ordered + list(chosen.values())

    def _follow_project(layout):
        """Le rendu natif QGIS suit le projet aussi après sauvegarde/réouverture."""
        map_item = layout.itemById("atlas_map")
        # setKeepLayerSet(False) est un drapeau GUI : vider aussi la liste stockée.
        map_item.setLayers([])
        map_item.setKeepLayerSet(False)
        map_item.setKeepLayerStyles(False)
        map_item.setLayerStyleOverrides({})
        legend = layout.itemById("atlas_legend")
        if legend is not None:
            # Le modèle automatique appartient au projet : ne jamais y appliquer
            # les réécritures de libellés réservées à l'arbre privé d'export.
            legend.setAutoUpdateModel(True)
        map_item.refresh()

    def _open_pdf_folder(pdf_path, feedback):
        """Ouvre le dossier sur le poste QGIS, uniquement après un export réussi."""
        try:
            from qgis.utils import iface

            if iface is None:
                feedback.pushInfo("PDF créé sans interface : dossier non ouvert.")
                return
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(pdf_path)))
            if not opened:
                feedback.pushWarning("PDF créé, mais le dossier de sortie n'a pas pu être ouvert.")
        except Exception as exc:
            feedback.pushWarning(f"PDF créé, mais ouverture du dossier impossible : {exc}")

    def geometry_plans(geometries, width, height, overlap=10, canceled=None):
        """Compare quatre origines sans fusionner les cellules ni perdre les intérieurs.

        La subdivision GEOS ignore les vides des lignes et des multiparties,
        puis le décalage comptant le moins de plans est retenu. L'optimisation
        est heuristique, sans prétention de minimum absolu.
        """
        bounds = None
        for geometry in geometries:
            box = geometry.boundingBox()
            candidate = box.xMinimum(), box.yMinimum(), box.xMaximum(), box.yMaximum()
            bounds = candidate if bounds is None else _bounds_union(bounds, candidate)
        if bounds is None:
            raise ValueError("Aucune géométrie dans le périmètre choisi.")
        sx, sy, _, _ = grid_spec(bounds, width, height, overlap)
        padx = (sx - (bounds[2] - bounds[0]) % sx) / 2
        pady = (sy - (bounds[3] - bounds[1]) % sy) / 2
        origins = (
            (bounds[0] - padx, bounds[1] - pady),
            (bounds[0], bounds[1]),
            (bounds[0] - sx / 2, bounds[1]),
            (bounds[0], bounds[1] - sy / 2),
        )
        best = None
        failures = []
        for origin in origins:
            _check_cancel(canceled)
            shifted = origin[0], origin[1], bounds[2], bounds[3]
            try:
                plans = _geometry_grid(geometries, shifted, width, height, overlap, canceled)
            except ValueError as exc:
                _check_cancel(canceled)
                failures.append(str(exc))
                continue
            if best is None or len(plans) < len(best):
                best = plans
        if best is None:
            raise ValueError(failures[0])
        return best

    def _geometry_grid(geometries, bounds, width, height, overlap, canceled):
        sx, sy, nx, ny = grid_spec(bounds, width, height, overlap)
        occupied = set()
        visits = 0
        for geometry in geometries:
            engine = QgsGeometry.createGeometryEngine(geometry.constGet())
            engine.prepareGeometry()
            stack = [(0, 0, nx, ny)]
            while stack:
                _check_cancel(canceled)
                visits += 1
                if visits > MAX_VISITS:
                    raise ValueError(
                        "Découpage trop complexe (200 000 tests) : filtrer la couche ou augmenter l'échelle."
                    )
                x0, y0, x1, y1 = stack.pop()
                rect = QgsRectangle(bounds[0] + x0 * sx, bounds[1] + y0 * sy, bounds[0] + x1 * sx, bounds[1] + y1 * sy)
                candidate = QgsGeometry.fromRect(rect)
                if not engine.intersects(candidate.constGet()):
                    continue
                if x1 - x0 == 1 and y1 - y0 == 1:
                    occupied.add((x0, y0))
                    if len(occupied) > MAX_CELLS:
                        raise ValueError("Plus de 10 000 plans : filtrer la couche ou augmenter l'échelle.")
                elif x1 - x0 >= y1 - y0:
                    middle = (x0 + x1) // 2
                    stack.extend([(x0, y0, middle, y1), (middle, y0, x1, y1)])
                else:
                    middle = (y0 + y1) // 2
                    stack.extend([(x0, y0, x1, middle), (x0, middle, x1, y1)])
        if not occupied:
            raise ValueError("Aucune cellule intersectant les géométries.")
        return [
            cell_extent(key, bounds, width, height, overlap) for key in sorted(occupied, key=lambda k: (-k[1], k[0]))
        ]

    def _style_index(layer, show_grid=False, overview_grid=True):
        # Le cadre général ne masque pas les plans ; la grille se règle par type de page.
        from qgis.core import QgsFillSymbol

        symbol = QgsFillSymbol.createSimple(
            {"color": "transparent", "outline_color": "40,55,75,180", "outline_width": "0.3"}
        )
        root = QgsRuleBasedRenderer.Rule(None)
        index_filter = '"overview" = 0'
        index_filter += (
            " AND CASE WHEN coalesce(attribute(@atlas_feature, 'overview'), 1) = 1 THEN "
            + ("TRUE" if overview_grid else "FALSE")
            + " ELSE "
            + ("TRUE" if show_grid else "FALSE")
            + " END"
        )
        root.appendChild(QgsRuleBasedRenderer.Rule(symbol, 0, 0, index_filter, "Plans"))
        layer.setRenderer(QgsRuleBasedRenderer(root))
        labels = QgsPalLayerSettings()
        labels.fieldName = f'CASE WHEN {index_filter} THEN "plan_id" END'
        labels.isExpression = True
        fmt = QgsTextFormat()
        fmt.setFont(QFont("Sans Serif", 9, QFont.Weight.Bold))
        fmt.setSize(9)
        fmt.setColor(QColor("#26374b"))
        from qgis.core import QgsTextBufferSettings

        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(1)
        buffer.setColor(QColor("white"))
        fmt.setBuffer(buffer)
        labels.setFormat(fmt)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(labels))
        layer.setLabelsEnabled(True)

    def _layout(
        project, coverage, layers, name, title, paper, scale, overview, logo, reference, author, company, options
    ):
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName(name)
        page = layout.pageCollection().pages()[0]
        page.setPageSize(paper, QgsLayoutItemPage.Orientation.Landscape)
        pw, ph, mw, mh = page_geometry(paper, options["SIDEBAR"])
        map_item = QgsLayoutItemMap(layout)
        layout.addLayoutItem(map_item)
        map_item.setId("atlas_map")
        map_item.attemptMove(QgsLayoutPoint(8, 24))
        map_item.attemptResize(QgsLayoutSize(mw, mh))
        map_item.setCrs(coverage.crs())
        map_item.setLayers([coverage] + layers)
        map_item.setKeepLayerSet(True)
        map_item.setKeepLayerStyles(False)
        map_item.zoomToExtent(QgsRectangle(*overview))
        map_item.setFrameEnabled(True)
        map_item.setAtlasDriven(True)
        map_item.setAtlasScalingMode(QgsLayoutItemMap.AtlasScalingMode.Fixed)
        map_item.dataDefinedProperties().setProperty(QgsLayoutObject.DataDefinedProperty.MapScale, QgsProperty.fromExpression('"scale"'))
        atlas = layout.atlas()
        atlas.setEnabled(True)
        atlas.setCoverageLayer(coverage)
        atlas.setHideCoverage(False)
        atlas.setSortFeatures(True)
        atlas.setSortExpression('"page_no"')
        atlas.setSortAscending(True)
        atlas.setPageNameExpression('"plan_id"')
        atlas.setFilenameExpression('"plan_id"')
        if not options["SHOW_DETAILS"]:
            atlas.setFilterFeatures(True)
            atlas.setFilterExpression("\"page_type\" <> 'detail'")

        def label(text, x, y, w, h, size=9, bold=False, identifier=None, literal=False, compact=False):
            item = QgsLayoutItemLabel(layout)
            font = QFont("Sans Serif")
            font.setPointSizeF(size)
            font.setBold(bold)
            if compact:
                fitted = " ".join(text.split())
                available = w - 2
                if QgsLayoutUtils.textWidthMM(font, fitted) > available:
                    low, high = 0, len(fitted)
                    while low < high:
                        middle = (low + high + 1) // 2
                        if QgsLayoutUtils.textWidthMM(font, fitted[:middle].rstrip() + "…") <= available:
                            low = middle
                        else:
                            high = middle - 1
                    fitted = fitted[:low].rstrip() + "…"
                item.setCustomProperty("map_atlas/full_text", text)
                item.setCustomProperty("map_atlas/display_text", fitted)
                item.setCustomProperty("map_atlas/truncated", fitted.endswith("…") and fitted != text)
                text = fitted
            item.setText(_literal_label_text(text) if literal else text)
            item.setFont(font)
            item.setMargin(0.5)
            if identifier:
                item.setId(identifier)
            layout.addLayoutItem(item)
            item.attemptMove(QgsLayoutPoint(x, y))
            item.attemptResize(QgsLayoutSize(w, h))
            return item

        def visibility(item, expression):
            item.dataDefinedProperties().setProperty(
                QgsLayoutObject.DataDefinedProperty.ExcludeFromExports, QgsProperty.fromExpression("NOT (" + expression + ")")
            )
            item.dataDefinedProperties().setProperty(
                QgsLayoutObject.DataDefinedProperty.Opacity, QgsProperty.fromExpression("CASE WHEN " + expression + " THEN 100 ELSE 0 END")
            )
            return item

        def rectangle(x, y, w, h, color="white", outline="#26374b"):
            from qgis.core import QgsFillSymbol

            item = QgsLayoutItemShape(layout)
            item.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
            item.setSymbol(
                QgsFillSymbol.createSimple(
                    {
                        "color": color,
                        "outline_color": outline,
                        "outline_style": "solid" if outline else "no",
                        "outline_width": "0.2",
                    }
                )
            )
            layout.addLayoutItem(item)
            item.attemptMove(QgsLayoutPoint(x, y))
            item.attemptResize(QgsLayoutSize(w, h))
            return item

        label(title, 8, 4, pw - 16, 10, 14, True, "atlas_title", literal=True, compact=True)
        label(
            "[% CASE WHEN \"overview\" = 1 THEN 'Carte générale — index des plans' ELSE 'Plan ' || \"plan_id\" END %]",
            8,
            15,
            mw,
            7,
            9,
            identifier="atlas_page_caption",
        )
        sidebar_x = pw - 62
        if options["SHOW_LEGEND"] or options["OVERVIEW_SHOW_LEGEND"]:
            legend = QgsLayoutItemLegend(layout)
            legend.setId("atlas_legend")
            legend.setTitle("LÉGENDE")
            legend.setLinkedMap(map_item)
            legend.setAutoUpdateModel(False)
            # Le calcul des entrées visibles doit être terminé avant la garde de taille.
            # Les versions récentes utilisent sinon un hit-test asynchrone.
            if hasattr(QgsLayerTreeModel, "UseThreadedHitTest"):
                legend.model().setFlag(QgsLayerTreeModel.Flag.UseThreadedHitTest, False)
            tree = QgsLayerTree()
            for layer in layers:
                tree.addLayer(layer)
            tree.setParent(legend.model())
            legend.model().setRootGroup(tree)
            legend.setLegendFilterByMapEnabled(options["LEGEND_FILTER_BY_MAP"])
            legend.setStyleFont(QgsLegendStyle.Style.Title, QFont("Sans Serif", 9, QFont.Weight.Bold))
            for component in (QgsLegendStyle.Style.Group, QgsLegendStyle.Style.Subgroup, QgsLegendStyle.Style.SymbolLabel):
                legend.setStyleFont(component, QFont("Sans Serif", 8))
            if hasattr(legend, "setAutoWrapLinesAfter"):
                legend.setAutoWrapLinesAfter(48)
            layout.addLayoutItem(legend)
            legend.attemptMove(QgsLayoutPoint(sidebar_x, 24))
            legend.adjustBoxSize()
            visibility(
                legend,
                '"page_type" <> \'cover\' AND CASE WHEN "overview" = 1 THEN '
                + ("TRUE" if options["OVERVIEW_SHOW_LEGEND"] else "FALSE")
                + " ELSE "
                + ("TRUE" if options["SHOW_LEGEND"] else "FALSE")
                + " END",
            )
        if options["SHOW_NORTH"]:
            label("N ↑", sidebar_x + 18, ph - 67, 28, 12, 14, True, "atlas_north")
        if options["SHOW_SCALEBAR"]:
            bar = QgsLayoutItemScaleBar(layout)
            bar.setId("atlas_scalebar")
            bar.setStyle("Single Box")
            bar.setLinkedMap(map_item)
            bar.setUnits(QgsUnitTypes.DistanceUnit.DistanceMeters)
            bar.setUnitsPerSegment(max(1, round(scale / 50)))
            bar.setSegmentSizeMode(QgsScaleBarSettings.SegmentSizeMode.SegmentSizeFitWidth)
            bar.setMinimumBarWidth(35)
            bar.setMaximumBarWidth(46)
            bar.setNumberOfSegments(2)
            bar.setNumberOfSegmentsLeft(0)
            bar.setUnitLabel("m")
            layout.addLayoutItem(bar)
            bar.attemptMove(QgsLayoutPoint(sidebar_x, ph - 41))

        # Bande inférieure réservée : le même cartouche figure sur chaque page.
        # Les dimensions de la carte et du découpage excluent cette bande.
        y = ph - 26
        middle_x = 56
        metadata_x = pw - 111
        middle_w = metadata_x - middle_x
        rectangle(8, y, 48, 18)
        rectangle(middle_x, y, middle_w, 18)
        rectangle(metadata_x, y, 103, 18)
        rectangle(metadata_x, y, 103, 9)
        rectangle(metadata_x + 54, y, 49, 9)
        rectangle(metadata_x + 54, y + 9, 49, 9)
        if logo:
            picture = QgsLayoutItemPicture(layout)
            picture.setId("atlas_constructel_logo")
            picture.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
            layout.addLayoutItem(picture)
            picture.attemptMove(QgsLayoutPoint(10, y + 1))
            picture.attemptResize(QgsLayoutSize(44, 11))
            picture.setPicturePath(logo)
        else:
            label(company, 10, y + 2, 44, 9, 9, True, literal=True, compact=True)
        label(company if logo else "ATLAS CARTOGRAPHIQUE", 10, y + 13, 44, 4, 6, literal=True, compact=True)
        label(title, middle_x + 2, y + 1, middle_w - 4, 6, 9, True, "atlas_cartouche_title", literal=True, compact=True)
        label("ATLAS CARTOGRAPHIQUE", middle_x + 2, y + 7, middle_w - 4, 4, 6)
        details = "  |  ".join(
            value
            for value in ("Réf. : " + reference if reference else "", "Auteur : " + author if author else "")
            if value
        )
        label(
            details,
            middle_x + 2,
            y + 11,
            middle_w - 4,
            6,
            6.5,
            identifier="atlas_reference_author",
            literal=True,
            compact=True,
        )
        label("PLAN", metadata_x + 1, y + 0.5, 52, 3, 5)
        label('[% "plan_id" %]', metadata_x + 1, y + 3.5, 52, 5, 8, True, "atlas_plan")
        label("ÉCHELLE", metadata_x + 55, y + 0.5, 47, 3, 5)
        label(
            "[% CASE WHEN \"page_type\" = 'cover' THEN '—' ELSE '1:' || format_number(map_get(item_variables('atlas_map'),'map_scale'), 0) END %]",
            metadata_x + 55,
            y + 3.5,
            47,
            5,
            8,
            True,
            "atlas_scale",
        )
        label("DATE D'ÉDITION", metadata_x + 1, y + 9.5, 52, 3, 5)
        label(date.today().strftime("%d/%m/%Y"), metadata_x + 1, y + 12.5, 52, 5, 8, identifier="atlas_date")
        label("PAGE", metadata_x + 55, y + 9.5, 47, 3, 5)
        label(
            "[% @atlas_featurenumber || ' / ' || @atlas_totalfeatures %]",
            metadata_x + 55,
            y + 12.5,
            47,
            5,
            8,
            identifier="atlas_page",
        )
        visibility(map_item, "\"page_type\" <> 'cover'")
        for identifier in ("atlas_title", "atlas_page_caption", "atlas_north", "atlas_scalebar"):
            item = layout.itemById(identifier)
            if item:
                visibility(item, "\"page_type\" <> 'cover'")
        if options["SHOW_COVER"]:
            visibility(
                label(title, 20, ph * 0.35, pw - 40, 40, 24, True, "atlas_cover_title", literal=True),
                "\"page_type\" = 'cover'",
            )
            visibility(
                label(
                    options["COVER_SUBTITLE"],
                    20,
                    ph * 0.35 + 46,
                    pw - 40,
                    16,
                    13,
                    identifier="atlas_cover_subtitle",
                    literal=True,
                ),
                "\"page_type\" = 'cover'",
            )
            visibility(
                label(company, 20, ph * 0.35 + 66, pw - 40, 12, 12, identifier="atlas_cover_company", literal=True),
                "\"page_type\" = 'cover'",
            )
            if logo:
                picture = QgsLayoutItemPicture(layout)
                picture.setId("atlas_cover_logo")
                picture.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
                layout.addLayoutItem(picture)
                picture.attemptMove(QgsLayoutPoint(20, 28))
                picture.attemptResize(QgsLayoutSize(80, 30))
                picture.setPicturePath(logo)
                visibility(picture, "\"page_type\" = 'cover'")
        return layout

    class LayersToAtlasAlgorithm(QgsProcessingAlgorithm):
        def name(self):
            return "layers_to_atlas"

        def displayName(self):
            return "Layers to Atlas"

        def group(self):
            return "Constructel"

        def groupId(self):
            return "constructel"

        def createInstance(self):
            return LayersToAtlasAlgorithm()

        def flags(self):
            return super().flags() | QgsProcessingAlgorithm.Flag.FlagNoThreading

        def shortHelpString(self):
            return (
                "Par défaut, l'atlas reprend les couches visibles du projet ouvert, dans leur ordre "
                "de rendu, avec leurs styles, étiquettes, filtres et règles d'échelle. Les fonds "
                "suivent leur visibilité ; aucun fond masqué n'est ajouté. Le périmètre par défaut "
                "est le canevas ; sélection, couche entière ou emprise sont également disponibles. "
                "Une sélection limite le découpage, pas les entités rendues dans les cartes. "
                "Choisir le format A3/A4 paysage, l'échelle, le titre et le PDF. L'index GeoPackage "
                "est créé à côté du PDF, avec un nouveau nom numéroté si nécessaire. "
                "Le dossier du PDF s'ouvre après réussite sur le poste QGIS. "
                "Les options avancées regroupent le choix explicite de couches, le chemin d'index, "
                "la légende, la grille, les pages, le cartouche, le logo et la résolution. "
                "Un choix explicite fixe la liste des couches dans l'ordre du projet au lancement, "
                "avec leurs styles courants. Sans choix, la mise en page suit le projet, même après "
                "sauvegarde et réouverture. L'index ajouté au projet fournit la grille ; sa visibilité "
                "suit ensuite le panneau Couches. La légende de cette mise en page suit aussi le projet. "
                "Le PDF initial est validé avec une légende adaptée à toutes ses pages (8/7 pt, "
                "1/2 colonnes). Après modification du projet, vérifier la légende avant de réexporter "
                "manuellement la mise en page, ou relancer le script pour refaire la validation. "
                "Le CRS du projet est repris par défaut et doit être projeté en mètres. Dans les options avancées, "
                "choisir un CRS métrique si le projet utilise des degrés. Canevas tourné : emprise englobante, plans au nord vertical. "
                "Sans interface, utiliser Emprise ; aucun dossier n'est ouvert. "
                "Un PDF existant est préservé en cas d'échec. 10 000 plans maximum. "
                "Enregistrer le projet et conserver l'index, le logo et les données sources."
            )

        def initAlgorithm(self, config=None):
            self.addParameter(
                QgsProcessingParameterEnum(
                    "MODE",
                    "Périmètre des plans",
                    ["Sélection d'entités", "Couche entière", "Canevas courant", "Emprise"],
                    defaultValue=2,
                )
            )
            self.addParameter(
                QgsProcessingParameterVectorLayer(
                    "INPUT",
                    "Couche du périmètre (sélection / couche entière)",
                    [QgsProcessing.SourceType.TypeVectorAnyGeometry],
                    optional=True,
                )
            )
            self.addParameter(QgsProcessingParameterExtent("EXTENT", "Emprise (mode Emprise)", optional=True))
            self.addParameter(
                QgsProcessingParameterMultipleLayers(
                    "LAYERS",
                    "Couches de la carte (vide = couches visibles du projet)",
                    QgsProcessing.SourceType.TypeMapLayer,
                    optional=True,
                )
            )
            self.addParameter(
                QgsProcessingParameterBoolean(
                    "INCLUDE_PROJECT_BACKGROUNDS", "Ajouter les fonds visibles à un choix explicite de couches", False
                )
            )
            self.addParameter(QgsProcessingParameterEnum("PAPER", "Format paysage", ["A3", "A4"], defaultValue=0))
            self.addParameter(
                QgsProcessingParameterNumber(
                    "SCALE",
                    "Échelle des détails (1000 = 1:1000)",
                    QgsProcessingParameterNumber.Type.Double,
                    1000,
                    minValue=100,
                    maxValue=100000,
                )
            )
            self.addParameter(
                QgsProcessingParameterNumber(
                    "OVERLAP",
                    "Recouvrement des plans (%)",
                    QgsProcessingParameterNumber.Type.Double,
                    10,
                    minValue=0,
                    maxValue=40,
                )
            )
            self.addParameter(
                QgsProcessingParameterNumber(
                    "DPI", "Résolution PDF (dpi)", QgsProcessingParameterNumber.Type.Integer, 200, minValue=72, maxValue=600
                )
            )
            self.addParameter(QgsProcessingParameterCrs("CRS", "CRS projeté en mètres (défaut : projet)", "ProjectCrs"))
            self.addParameter(QgsProcessingParameterString("TITLE", "Titre du dossier", "Atlas cartographique"))
            self.addParameter(
                QgsProcessingParameterString("COMPANY", "Entreprise / organisation", "Constructel", optional=True)
            )
            self.addParameter(QgsProcessingParameterString("REFERENCE", "Référence du dossier", optional=True))
            self.addParameter(QgsProcessingParameterString("AUTHOR", "Auteur du plan", optional=True))
            self.addParameter(
                QgsProcessingParameterFile(
                    "LOGO",
                    "Logo (vider pour aucun logo)",
                    behavior=QgsProcessingParameterFile.Behavior.File,
                    defaultValue=DEFAULT_LOGO if os.path.isfile(DEFAULT_LOGO) else None,
                    optional=True,
                    fileFilter="Images (*.svg *.png *.jpg *.jpeg)",
                )
            )
            self.addParameter(
                QgsProcessingParameterEnum(
                    "PAGE_TYPES",
                    "Types de pages",
                    ["Accueil / page de garde", "Carte générale indexée", "Plans détaillés"],
                    allowMultiple=True,
                    defaultValue=[1, 2],
                )
            )
            self.addParameter(
                QgsProcessingParameterString("COVER_SUBTITLE", "Sous-titre de la page d'accueil", optional=True)
            )
            for key, label in (
                ("SHOW_LEGEND", "Afficher la légende QGIS"),
                ("LEGEND_FILTER_BY_MAP", "Filtrer la légende au contenu de chaque carte"),
                ("SHOW_NORTH", "Afficher le nord"),
                ("SHOW_SCALEBAR", "Afficher la barre d'échelle"),
                ("SHOW_GRID", "Afficher la grille et les numéros sur les plans de détail"),
            ):
                self.addParameter(QgsProcessingParameterBoolean(key, label, True))
            self.addParameter(
                QgsProcessingParameterBoolean(
                    "OVERVIEW_SHOW_LEGEND", "Afficher la légende sur la carte générale", False
                )
            )
            self.addParameter(
                QgsProcessingParameterBoolean("OVERVIEW_SHOW_GRID", "Afficher la grille sur la carte générale", True)
            )
            self.addParameter(
                QgsProcessingParameterFileDestination(
                    "ZONES", "Index des plans (vide = à côté du PDF)", "GeoPackage (*.gpkg)", optional=True, createByDefault=False
                )
            )
            self.addParameter(QgsProcessingParameterFileDestination("PDF", "Atlas PDF", "PDF (*.pdf)"))
            self.addParameter(
                QgsProcessingParameterBoolean("OPEN_OUTPUT_FOLDER", "Ouvrir le dossier du PDF après création", True)
            )
            basic = {"MODE", "INPUT", "EXTENT", "PAPER", "SCALE", "TITLE", "PDF"}
            for parameter in self.parameterDefinitions():
                if parameter.name() not in basic:
                    parameter.setFlags(parameter.flags() | QgsProcessingParameterDefinition.Flag.FlagAdvanced)

        def processAlgorithm(self, parameters, context, feedback):
            feedback.pushInfo(f"Layers to Atlas — version {SCRIPT_VERSION}")
            project = context.project()
            if project is None:
                raise QgsProcessingException("Un projet QGIS est requis.")
            crs = self.parameterAsCrs(parameters, "CRS", context)
            if not crs.isValid() or crs.isGeographic() or crs.mapUnits() != QgsUnitTypes.DistanceUnit.DistanceMeters:
                raise QgsProcessingException("Choisir un CRS projeté en mètres (EPSG:31370 en Belgique).")
            mode = self.parameterAsEnum(parameters, "MODE", context)
            if mode not in (0, 1, 2, 3):
                raise QgsProcessingException("Mode de périmètre invalide.")
            paper_number = self.parameterAsEnum(parameters, "PAPER", context)
            if paper_number not in (0, 1):
                raise QgsProcessingException("Format A3 ou A4 requis.")
            paper = ("A3", "A4")[paper_number]
            scale = self.parameterAsDouble(parameters, "SCALE", context)
            overlap = self.parameterAsDouble(parameters, "OVERLAP", context)
            if not math.isfinite(scale) or not 100 <= scale <= 100000:
                raise QgsProcessingException("Échelle finie entre 100 et 100 000 requise.")
            options = {
                key: self.parameterAsBool(parameters, key, context)
                for key in (
                    "SHOW_LEGEND",
                    "LEGEND_FILTER_BY_MAP",
                    "SHOW_NORTH",
                    "SHOW_SCALEBAR",
                    "SHOW_GRID",
                    "OVERVIEW_SHOW_LEGEND",
                    "OVERVIEW_SHOW_GRID",
                )
            }
            if "PAGE_TYPES" in parameters and parameters["PAGE_TYPES"] in (None, "", []):
                raise QgsProcessingException("Choisir au moins un type de page.")
            page_types = self.parameterAsEnums(parameters, "PAGE_TYPES", context)
            if not page_types or any(value not in (0, 1, 2) for value in page_types):
                raise QgsProcessingException("Choisir au moins un type de page valide.")
            options.update(
                SHOW_COVER=0 in page_types,
                SHOW_OVERVIEW=1 in page_types,
                SHOW_DETAILS=2 in page_types,
                COVER_SUBTITLE=self.parameterAsString(parameters, "COVER_SUBTITLE", context),
            )
            options["SIDEBAR"] = (
                options["SHOW_LEGEND"]
                or options["OVERVIEW_SHOW_LEGEND"]
                or options["SHOW_NORTH"]
                or options["SHOW_SCALEBAR"]
            )
            pw, ph, mw, mh = page_geometry(paper, options["SIDEBAR"])
            width, height = mw * scale / 1000, mh * scale / 1000
            geometries = []
            zero_length_count = 0
            try:
                if mode in (0, 1):
                    source = self.parameterAsVectorLayer(parameters, "INPUT", context)
                    if source is None:
                        mode_name = "Sélection" if mode == 0 else "Couche entière"
                        raise QgsProcessingException(
                            f"Mode « {mode_name} » : renseigner la couche du périmètre (INPUT). "
                            "Pour utiliser la vue de la carte sans couche de périmètre, choisir Canevas courant."
                        )
                    if not source.isValid() or not source.crs().isValid():
                        raise QgsProcessingException("Choisir une couche vectorielle spatiale avec un CRS valide.")
                    if mode == 0 and source.selectedFeatureCount() == 0:
                        raise QgsProcessingException(
                            "Sélection vide : sélectionner des entités ou choisir Couche entière."
                        )
                    transform = QgsCoordinateTransform(source.crs(), crs, project)
                    # L'itérateur applique le filtre du fournisseur, y compris à la sélection.
                    request = QgsFeatureRequest()
                    request.setSubsetOfAttributes([])
                    if mode == 0:
                        request.setFilterFids(source.selectedFeatureIds())
                    for feature in source.getFeatures(request):
                        _check_cancel(feedback.isCanceled)
                        geom = QgsGeometry(feature.geometry())
                        if geom.isNull() or geom.isEmpty():
                            raise QgsProcessingException(f"Géométrie vide pour l'entité {feature.id()}.")
                        if not geom.isGeosValid():
                            box = geom.boundingBox()
                            if (
                                geom.type() == QgsWkbTypes.GeometryType.LineGeometry
                                and geom.length() == 0
                                and box.width() == 0
                                and box.height() == 0
                            ):
                                point = next(geom.vertices(), None)
                                if point is None:
                                    raise QgsProcessingException(f"Ligne dégénérée vide pour l'entité {feature.id()}.")
                                # Certains exports représentent un segment nul par deux sommets
                                # identiques. Le découpage utilise son point, sans modifier la source.
                                geom = QgsGeometry.fromPointXY(QgsPointXY(point.x(), point.y()))
                                zero_length_count += 1
                            else:
                                raise QgsProcessingException(
                                    f"Géométrie invalide pour l'entité {feature.id()} : corriger avant export."
                                )
                        geom.transform(transform)
                        if any(not math.isfinite(v) for point in geom.vertices() for v in (point.x(), point.y())):
                            raise QgsProcessingException(f"Coordonnées non finies pour l'entité {feature.id()}.")
                        geometries.append(geom)
                    extents = geometry_plans(geometries, width, height, overlap, feedback.isCanceled)
                    if zero_length_count:
                        feedback.pushWarning(
                            f"{zero_length_count} ligne(s) de longueur nulle avec sommets confondus traitée(s) comme points pour le découpage ; sources inchangées."
                        )
                else:
                    if mode == 2:
                        from qgis.utils import iface

                        if iface is None or iface.mapCanvas() is None:
                            raise QgsProcessingException(
                                "Canevas indisponible sans interface QGIS : utiliser le mode Emprise."
                            )
                        canvas = iface.mapCanvas()
                        source_crs = canvas.mapSettings().destinationCrs()
                        if not source_crs.isValid():
                            raise QgsProcessingException("Le canevas doit avoir un CRS valide.")
                        transform = QgsCoordinateTransform(source_crs, crs, project)
                        extent = transform.transformBoundingBox(canvas.extent())
                    else:
                        if not parameters.get("EXTENT"):
                            raise QgsProcessingException("Renseigner l'emprise dans le mode Emprise.")
                        extent = self.parameterAsExtent(parameters, "EXTENT", context, crs)
                    if extent.isEmpty() or extent.width() <= 0 or extent.height() <= 0:
                        raise QgsProcessingException("Emprise vide : choisir une boîte englobante de surface positive.")
                    bounds = extent.xMinimum(), extent.yMinimum(), extent.xMaximum(), extent.yMaximum()
                    extents = extent_plans(bounds, width, height, overlap, feedback.isCanceled)
            except QgsProcessingException:
                raise
            except Exception as exc:
                raise QgsProcessingException(f"Découpage impossible : {exc}") from exc
            selected_layers = self.parameterAsLayerList(parameters, "LAYERS", context)
            layers = _map_layers(
                project,
                selected_layers,
                self.parameterAsBool(parameters, "INCLUDE_PROJECT_BACKGROUNDS", context),
            )
            if not layers or any(not layer.isValid() for layer in layers):
                raise QgsProcessingException(
                    "Choisir au moins une couche de carte valide ou afficher des couches dans le projet."
                )
            logo = (
                ""
                if "LOGO" in parameters and not parameters["LOGO"]
                else self.parameterAsFile(parameters, "LOGO", context)
            )
            if logo and (
                not os.path.isfile(logo)
                or (not QSvgRenderer(logo).isValid() if logo.lower().endswith(".svg") else QImage(logo).isNull())
            ):
                raise QgsProcessingException(f"Logo introuvable ou image illisible : {logo}")
            pdf_path = os.path.abspath(self.parameterAsFileOutput(parameters, "PDF", context))
            if parameters.get("ZONES"):
                zone_path = os.path.abspath(self.parameterAsFileOutput(parameters, "ZONES", context))
            else:
                zone_path = _default_index_path(pdf_path)
            if os.path.exists(zone_path):
                raise QgsProcessingException("Le GeoPackage existe déjà : choisir un nouveau nom.")
            if not zone_path.lower().endswith(".gpkg") or not pdf_path.lower().endswith(".pdf"):
                raise QgsProcessingException("Sorties attendues : .gpkg et .pdf.")
            if not all(os.path.isdir(os.path.dirname(path)) for path in (zone_path, pdf_path)):
                raise QgsProcessingException("Les dossiers de sortie doivent exister.")
            persisted_logo = (
                os.path.splitext(zone_path)[0] + "_logo" + os.path.splitext(logo)[1].lower() if logo else ""
            )
            if persisted_logo and os.path.exists(persisted_logo):
                raise QgsProcessingException("La copie du logo existe déjà : choisir un nouveau nom de GeoPackage.")
            feedback.pushInfo(f"{len(extents)} plans à 1:{scale:g} ; {len(layers)} couches cartographiées.")
            feedback.setProgress(30)
            all_bounds = extents[0]
            for bounds in extents[1:]:
                all_bounds = _bounds_union(all_bounds, bounds)
            cx, cy = (all_bounds[0] + all_bounds[2]) / 2, (all_bounds[1] + all_bounds[3]) / 2
            overview_scale = max((all_bounds[2] - all_bounds[0]) / mw, (all_bounds[3] - all_bounds[1]) / mh) * 1100
            ow, oh = mw * overview_scale / 1000, mh * overview_scale / 1000
            overview = cx - ow / 2, cy - oh / 2, cx + ow / 2, cy + oh / 2
            coverage = QgsVectorLayer("Polygon", "Atlas — Index des plans", "memory")
            coverage.setCrs(crs)
            provider = coverage.dataProvider()
            provider.addAttributes(
                [
                    QgsField("page_no", QVariant.Int),
                    QgsField("plan_id", QVariant.String),
                    QgsField("overview", QVariant.Int),
                    QgsField("scale", QVariant.Double),
                    QgsField("page_type", QVariant.String),
                ]
            )
            coverage.updateFields()
            rows = [(overview, "ACCUEIL", 1, overview_scale, "cover")] if options["SHOW_COVER"] else []
            rows += [(overview, "GENERAL", 1, overview_scale, "overview")] if options["SHOW_OVERVIEW"] else []
            rows += [(bounds, f"P{i:03d}", 0, scale, "detail") for i, bounds in enumerate(extents, 1)]
            features = []
            for page_no, (bounds, plan_id, general, denominator, page_type) in enumerate(rows, 1):
                feature = QgsFeature(coverage.fields())
                feature.setGeometry(QgsGeometry.fromRect(QgsRectangle(*bounds)))
                feature.setAttributes([page_no, plan_id, general, denominator, page_type])
                features.append(feature)
            if not provider.addFeatures(features)[0]:
                raise QgsProcessingException("Impossible de créer les plans.")
            coverage.updateExtents()
            _style_index(coverage, options["SHOW_GRID"], options["OVERVIEW_SHOW_GRID"])
            coverage.setCustomProperty("map_atlas/index", True)
            base_name = "Atlas — " + self.parameterAsString(parameters, "TITLE", context)
            name, suffix = base_name, 2
            while project.layoutManager().layoutByName(name):
                name, suffix = f"{base_name} ({suffix})", suffix + 1
            layout = _layout(
                project,
                coverage,
                layers,
                name,
                self.parameterAsString(parameters, "TITLE", context),
                paper,
                scale,
                overview,
                logo,
                self.parameterAsString(parameters, "REFERENCE", context),
                self.parameterAsString(parameters, "AUTHOR", context),
                self.parameterAsString(parameters, "COMPANY", context),
                options,
            )
            if any(
                item.customProperty("map_atlas/truncated", False)
                for item in layout.items()
                if isinstance(item, QgsLayoutItemLabel)
            ):
                feedback.pushWarning(
                    "Des textes longs sont abrégés par … dans le titre/cartouche ; leur valeur complète est conservée dans les propriétés des éléments de la mise en page."
                )
            # One persistent legend configuration must fit every exported map.
            _fit_atlas_legend(layout, options, ph, feedback)
            settings = QgsLayoutExporter.PdfExportSettings()
            dpi = self.parameterAsInt(parameters, "DPI", context)
            if not 72 <= dpi <= 600:
                raise QgsProcessingException("Résolution PDF entre 72 et 600 dpi requise.")
            settings.dpi = dpi
            temporary = None
            zone_created = logo_created = outputs_committed = False
            memory = coverage
            try:
                _check_cancel(feedback.isCanceled)
                with tempfile.NamedTemporaryFile(
                    prefix=".atlas_", suffix=".pdf", dir=os.path.dirname(pdf_path), delete=False
                ) as tmp:
                    temporary = tmp.name
                status, error = QgsLayoutExporter.exportToPdf(layout.atlas(), temporary, settings, feedback)
                if status != QgsLayoutExporter.ExportResult.Success or feedback.isCanceled():
                    raise QgsProcessingException(f"Export PDF impossible ou annulé (code {status}) : {error}")
                with tempfile.TemporaryDirectory(prefix=".atlas_", dir=os.path.dirname(zone_path)) as tmp_dir:
                    zone_tmp = os.path.join(tmp_dir, "plans.gpkg")
                    writer = QgsVectorFileWriter.SaveVectorOptions()
                    writer.driverName = "GPKG"
                    writer.layerName = "atlas_plans"
                    result = QgsVectorFileWriter.writeAsVectorFormatV2(
                        memory, zone_tmp, context.transformContext(), writer
                    )
                    if result[0] != QgsVectorFileWriter.WriterError.NoError:
                        raise QgsProcessingException(f"Écriture des plans impossible : {result[1]}")
                    _check_cancel(feedback.isCanceled)
                    os.replace(zone_tmp, zone_path)
                    zone_created = True
                coverage = QgsVectorLayer(zone_path + "|layername=atlas_plans", memory.name(), "ogr")
                if not coverage.isValid():
                    raise QgsProcessingException("Index des plans illisible après écriture.")
                _style_index(coverage, options["SHOW_GRID"], options["OVERVIEW_SHOW_GRID"])
                coverage.setCustomProperty("map_atlas/index", True)
                layout.atlas().setCoverageLayer(coverage)
                layout.itemById("atlas_map").setLayers([coverage] + layers)
                if persisted_logo:
                    with open(logo, "rb") as original, open(persisted_logo, "xb") as copied:
                        logo_created = True
                        shutil.copyfileobj(original, copied)
                    layout.itemById("atlas_constructel_logo").setPicturePath(persisted_logo)
                    if layout.itemById("atlas_cover_logo"):
                        layout.itemById("atlas_cover_logo").setPicturePath(persisted_logo)
                _check_cancel(feedback.isCanceled)
                os.replace(temporary, pdf_path)
                temporary = None
                outputs_committed = True
            except (OSError, ValueError) as exc:
                raise QgsProcessingException(f"Finalisation impossible : {exc}") from exc
            finally:
                if not outputs_committed:
                    if zone_created and coverage is not memory:
                        layout.atlas().setCoverageLayer(memory)
                        layout.itemById("atlas_map").setLayers([memory] + layers)
                        sip.delete(coverage)
                    owned = (
                        [temporary] + ([persisted_logo] if logo_created else []) + ([zone_path] if zone_created else [])
                    )
                    for path in owned:
                        if path and os.path.exists(path):
                            os.unlink(path)
            project.addMapLayer(coverage)
            project.layoutManager().addLayout(layout)
            if not selected_layers:
                _follow_project(layout)
            if self.parameterAsBool(parameters, "OPEN_OUTPUT_FOLDER", context):
                _open_pdf_folder(pdf_path, feedback)
            feedback.setProgress(100)
            feedback.pushInfo("PDF créé. Enregistrer le projet et conserver les sources, l'index et la copie du logo.")
            return {"PDF": pdf_path, "ZONES": zone_path}
