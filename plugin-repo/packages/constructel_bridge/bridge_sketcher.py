# -*- coding: utf-8 -*-
"""
Constructel Bridge — Sketcher i18n.

Applique dynamiquement les traductions multilingues sur les couches QGIS:
  1. Alias de champs (formulaires d'attributs)
  2. Noms de couches dans le Layer Tree
  3. Noms de groupes dans le Layer Tree
  4. Colonnes Value des widgets ValueRelation (label_fr / label_en / label_pt)

Aucune dependance locale (styles, QML) — tout passe par l'API QGIS.
Compatible avec les projets stockes en base PostgreSQL.
"""

from qgis.core import (
    Qgis,
    QgsAttributeEditorContainer,
    QgsDataSourceUri,
    QgsEditorWidgetSetup,
    QgsExpressionContextUtils,
    QgsMessageLog,
    QgsProject,
    QgsVectorLayer,
)

from .i18n import get_language
from .i18n.layer_translations import (
    FIELD_ALIASES,
    FORM_CONTAINERS_PER_LAYER,
    GROUP_NAMES,
    LABEL_EXPRESSIONS,
    LAYER_DISPLAY_NAMES,
    LAYER_NAME_MAP,
    VALUE_RELATION_COLUMNS,
    _FORM_COMMON,
)

TAG = "Constructel Bridge"


def _log(msg, level=Qgis.Info):
    QgsMessageLog.logMessage(msg, TAG, level=level)


def _resolve_table_key(layer: QgsVectorLayer) -> str | None:
    """Identifie la cle dans FIELD_ALIASES a partir du data source.

    Priorite: URI PostgreSQL table name > layer name > LAYER_NAME_MAP.
    """
    # 1. Depuis l'URI PostgreSQL
    provider = layer.dataProvider()
    if provider and provider.name() == "postgres":
        uri = QgsDataSourceUri(layer.source())
        table = uri.table()
        if table and table in FIELD_ALIASES:
            return table

    # 2. Depuis le nom de la couche
    name = layer.name()
    if name in FIELD_ALIASES:
        return name

    # 3. Depuis le mapping d'exceptions
    mapped = LAYER_NAME_MAP.get(name)
    if mapped and mapped in FIELD_ALIASES:
        return mapped

    return None


# =====================================================================
# 1. Alias de champs
# =====================================================================

def apply_field_aliases(layer: QgsVectorLayer, lang: str | None = None):
    """Applique les alias de champs traduits sur une couche."""
    lang = lang or get_language()
    table_key = _resolve_table_key(layer)
    if not table_key:
        return False

    aliases = FIELD_ALIASES[table_key]
    fields = layer.fields()
    applied = 0

    for i in range(fields.count()):
        field_name = fields.at(i).name()
        tr_dict = aliases.get(field_name)
        if tr_dict:
            alias = tr_dict.get(lang) or tr_dict.get("en", "")
            if alias:
                layer.setFieldAlias(i, alias)
                applied += 1

    return applied > 0


# =====================================================================
# 2. ValueRelation — bascule colonne Value (label/label_en)
# =====================================================================

def apply_value_relation_columns(layer: QgsVectorLayer, lang: str | None = None):
    """Bascule la colonne Value des widgets ValueRelation selon la langue.

    ref.v_form_lists expose ``label_fr``, ``label_en``, ``label_pt``.
    Cette fonction modifie dynamiquement quelle colonne est affichee
    dans les dropdowns.
    """
    lang = lang or get_language()
    fields = layer.fields()
    changed = 0

    for i in range(fields.count()):
        setup = layer.editorWidgetSetup(i)
        if setup.type() != "ValueRelation":
            continue

        config = dict(setup.config())
        ref_layer_name = config.get("LayerName", "")
        col_map = VALUE_RELATION_COLUMNS.get(ref_layer_name)
        if not col_map:
            continue

        new_value_col = col_map.get(lang) or col_map.get("en", "label_en")
        current_value_col = config.get("Value", "")

        if new_value_col != current_value_col:
            config["Value"] = new_value_col
            layer.setEditorWidgetSetup(i, QgsEditorWidgetSetup("ValueRelation", config))
            changed += 1

    return changed > 0


# =====================================================================
# 3. Noms de couches
# =====================================================================

def apply_layer_name(layer: QgsVectorLayer, lang: str | None = None):
    """Renomme la couche dans le Layer Tree selon la langue."""
    lang = lang or get_language()
    table_key = _resolve_table_key(layer)
    if not table_key:
        return False

    names = LAYER_DISPLAY_NAMES.get(table_key)
    if not names:
        return False

    new_name = names.get(lang) or names.get("en", "")
    if new_name and layer.name() != new_name:
        layer.setName(new_name)
        return True
    return False


# =====================================================================
# 4. Noms de groupes
# =====================================================================

def apply_group_names(lang: str | None = None):
    """Renomme les groupes du Layer Tree selon la langue."""
    lang = lang or get_language()
    root = QgsProject.instance().layerTreeRoot()
    renamed = 0

    # Construire un reverse lookup: n'importe quel nom traduit -> dict complet
    all_names = {}
    for canonical, tr_dict in GROUP_NAMES.items():
        for l, name in tr_dict.items():
            all_names[name] = (canonical, tr_dict)
        all_names[canonical] = (canonical, tr_dict)

    for child in root.children():
        if not hasattr(child, "name"):
            continue
        current_name = child.name()
        entry = all_names.get(current_name)
        if entry:
            _, tr_dict = entry
            new_name = tr_dict.get(lang) or tr_dict.get("en", current_name)
            if new_name != current_name:
                child.setName(new_name)
                renamed += 1

    return renamed


# =====================================================================
# 5. Etiquettes (labels sur la carte)
# =====================================================================

def apply_label_expressions(layer: QgsVectorLayer, lang: str | None = None):
    """Bascule l'expression d'etiquette selon la langue.

    Seules les couches listees dans LABEL_EXPRESSIONS sont modifiees.
    Les autres affichent des donnees brutes (nomenclature, code, etc.)
    qui ne necessitent pas de traduction.
    """
    from qgis.core import QgsPalLayerSettings, QgsVectorLayerSimpleLabeling

    lang = lang or get_language()
    table_key = _resolve_table_key(layer)
    if not table_key or table_key not in LABEL_EXPRESSIONS:
        return False

    expr_map = LABEL_EXPRESSIONS[table_key]
    new_expr = expr_map.get(lang) or expr_map.get("en", "")
    if not new_expr:
        return False

    labeling = layer.labeling()
    if not labeling:
        return False

    # Simple labeling (type le plus courant)
    if not isinstance(labeling, QgsVectorLayerSimpleLabeling):
        return False

    settings = labeling.settings()
    if settings.fieldName == new_expr:
        return False

    settings.fieldName = new_expr
    settings.isExpression = True
    labeling.setSettings(settings)
    layer.setLabeling(labeling)
    layer.triggerRepaint()
    return True


# =====================================================================
# 6. Containers de formulaires (onglets + groupes)
# =====================================================================

def _rename_containers_recursive(element, lookup, lang):
    """Parcourt recursivement les containers et renomme ceux trouves dans lookup."""
    renamed = 0
    if not isinstance(element, QgsAttributeEditorContainer):
        return 0

    current_name = element.name()
    tr_dict = lookup.get(current_name)
    if tr_dict:
        new_name = tr_dict.get(lang) or tr_dict.get("en", current_name)
        if new_name != current_name:
            element.setName(new_name)
            renamed += 1

    for child in element.children():
        renamed += _rename_containers_recursive(child, lookup, lang)

    return renamed


def apply_form_containers(layer: QgsVectorLayer, lang: str | None = None):
    """Renomme les onglets et groupes du formulaire d'attributs.

    Combine le dict commun (_FORM_COMMON) avec le dict specifique
    a la couche (FORM_CONTAINERS_PER_LAYER[table_key]).
    """
    lang = lang or get_language()
    table_key = _resolve_table_key(layer)

    # Construire le lookup : commun + specifique à la couche
    lookup = dict(_FORM_COMMON)
    if table_key and table_key in FORM_CONTAINERS_PER_LAYER:
        lookup.update(FORM_CONTAINERS_PER_LAYER[table_key])

    # Aussi ajouter le lookup via le nom PG de la table
    provider = layer.dataProvider()
    if provider and provider.name() == "postgres":
        uri = QgsDataSourceUri(layer.source())
        pg_table = uri.table()
        if pg_table and pg_table in FORM_CONTAINERS_PER_LAYER:
            lookup.update(FORM_CONTAINERS_PER_LAYER[pg_table])

    if not lookup:
        return False

    # Construire un reverse lookup: n'importe quelle traduction existante -> dict
    reverse = {}
    for canonical_name, tr_dict in lookup.items():
        reverse[canonical_name] = tr_dict
        for l, translated in tr_dict.items():
            reverse[translated] = tr_dict

    edit_form_config = layer.editFormConfig()
    root_container = edit_form_config.invisibleRootContainer()
    if not root_container:
        return False

    renamed = _rename_containers_recursive(root_container, reverse, lang)

    if renamed:
        layer.setEditFormConfig(edit_form_config)

    return renamed > 0


# =====================================================================
# API publique — applique tout
# =====================================================================

def apply_all_translations(lang: str | None = None):
    """Applique toutes les traductions i18n sur le projet courant.

    Appele au changement de langue et a la connexion.
    """
    lang = lang or get_language()
    project = QgsProject.instance()

    layers_translated = 0
    vr_switched = 0
    forms_translated = 0
    labels_switched = 0

    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        if apply_field_aliases(layer, lang):
            layers_translated += 1
        if apply_value_relation_columns(layer, lang):
            vr_switched += 1
        if apply_form_containers(layer, lang):
            forms_translated += 1
        if apply_label_expressions(layer, lang):
            labels_switched += 1
        apply_layer_name(layer, lang)

    groups_renamed = apply_group_names(lang)

    # Variable projet accessible via @wyre_language dans les expressions QGIS
    # (utilisee par le fallback map_get() dans les styles QML)
    QgsExpressionContextUtils.setProjectVariable(project, "wyre_language", lang)

    _log(
        f"i18n [{lang}]: {layers_translated} couche(s) traduites, "
        f"{vr_switched} ValueRelation basculee(s), "
        f"{forms_translated} formulaire(s) traduit(s), "
        f"{labels_switched} etiquette(s) basculee(s), "
        f"{groups_renamed} groupe(s) renomme(s)"
    )
    return layers_translated


def apply_to_layer(layer: QgsVectorLayer, lang: str | None = None):
    """Applique les traductions sur une seule couche (pour layersAdded)."""
    lang = lang or get_language()
    if not isinstance(layer, QgsVectorLayer):
        return
    apply_field_aliases(layer, lang)
    apply_value_relation_columns(layer, lang)
    apply_form_containers(layer, lang)
    apply_label_expressions(layer, lang)
    apply_layer_name(layer, lang)
