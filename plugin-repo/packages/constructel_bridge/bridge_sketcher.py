# -*- coding: utf-8 -*-
"""
Constructel Bridge — Sketcher i18n.

Applique dynamiquement les traductions multilingues sur les couches QGIS:
  1. Alias de champs (formulaires d'attributs)
  2. Noms de couches dans le Layer Tree
  3. Noms de groupes dans le Layer Tree
  4. Colonnes Value des widgets ValueRelation (label_fr / label_en / label_pt)
  5. Couches cibles des ValueRelation, infobulles et expressions d'affichage :
     toujours celles du meme operateur (Bridge 1.9, retarget_operator_references)

Aucune dependance locale (styles, QML) — tout passe par l'API QGIS.
Compatible avec les projets stockes en base PostgreSQL.
"""

from __future__ import annotations

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

from .bridge_operators import (
    COMMON_ROOT,
    GROUP_KIND_PROPERTY,
    GROUP_SCHEMA_PROPERTY,
    OPERATOR_TABLES,
    OPERATOR_TEMPLATE_SCHEMA,
    canonical_group,
    operator_layer_name,
    parse_operator_labels,
    parse_project_operators,
    parse_suffix_flag,
    retarget_get_feature,
    retarget_layer_source,
    split_operator_suffix,
    suffix_applies,
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


def _log(msg, level=Qgis.MessageLevel.Info):
    QgsMessageLog.logMessage(msg, TAG, level=level)


def _pg_uri(layer: QgsVectorLayer):
    """QgsDataSourceUri de la source d'une couche PostgreSQL, None pour une
    autre source."""
    provider = layer.dataProvider()
    if provider and provider.name() == "postgres":
        return QgsDataSourceUri(layer.source())
    return None


def _resolve_table_key(layer: QgsVectorLayer) -> str | None:
    """Identifie la cle dans FIELD_ALIASES a partir du data source.

    Priorite: URI PostgreSQL table name > layer name > LAYER_NAME_MAP.
    """
    # 1. Depuis l'URI PostgreSQL
    uri = _pg_uri(layer)
    table = uri.table() if uri is not None else None
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

def project_operator_naming(project) -> tuple[dict[str, str], bool]:
    """Identite du projet pour le nommage : ``(libelles, suffixe actif)``.

    *libelles* : ``bridge/operator_labels`` (schema -> libelle ; ``{}`` pour un
    projet 1.8, qui n'est donc jamais suffixe). Suffixe actif : au moins deux
    operateurs dans ``bridge/operator``, ou ``bridge/operator_suffix`` coche
    (une entree absente vaut non coche)."""
    labels = parse_operator_labels(project.readEntry("bridge", "operator_labels", "")[0])
    operators = parse_project_operators(project.readEntry("bridge", "operator", "")[0])
    opted_in, found = project.readEntry("bridge", "operator_suffix", "")
    return labels, suffix_applies(operators, parse_suffix_flag(opted_in if found else ""))


def _layer_schema(layer: QgsVectorLayer) -> str:
    """Schema PostgreSQL de la source de la couche, "" pour une autre source."""
    uri = _pg_uri(layer)
    return uri.schema() if uri is not None else ""


def apply_layer_name(layer: QgsVectorLayer, lang: str | None = None, naming=None):
    """Renomme la couche dans le Layer Tree selon la langue.

    Le nom est toujours recalcule depuis LAYER_DISPLAY_NAMES, jamais depuis le
    nom courant : le suffixe de l'operateur (« Cables · Wyre ») ne s'empile
    donc pas, meme apres un second « Ajouter » ou un changement de langue. Il
    est ajoute apres la traduction quand la table est une table d'operateur,
    que le schema de la source a un libelle dans ``bridge/operator_labels`` et
    que ``project_operator_naming`` l'active ; sinon il est retire.
    *naming* : resultat de ``project_operator_naming``, a fournir quand on
    traite toutes les couches d'affilee."""
    lang = lang or get_language()
    table_key = _resolve_table_key(layer)
    if not table_key:
        return False

    names = LAYER_DISPLAY_NAMES.get(table_key)
    if not names:
        return False

    new_name = names.get(lang) or names.get("en", "")
    if new_name and table_key in OPERATOR_TABLES:
        labels, suffixed = naming or project_operator_naming(QgsProject.instance())
        label = labels.get(_layer_schema(layer))
        if suffixed and label:
            new_name = operator_layer_name(new_name, label)
    if new_name and layer.name() != new_name:
        layer.setName(new_name)
        return True
    return False


# =====================================================================
# 4. Noms de groupes
# =====================================================================

def _is_group(node) -> bool:
    return not hasattr(node, "layerId")


def _rename_group(group, lang: str) -> bool:
    """Traduit *group* : d'abord par sa propriete GROUP_KIND_PROPERTY (le nom
    a pu etre modifie a la main), puis par son nom actuel. Le groupe d'un
    operateur (GROUP_SCHEMA_PROPERTY) porte son libelle : jamais renomme."""
    if group.customProperty(GROUP_SCHEMA_PROPERTY):
        return False
    kind = group.customProperty(GROUP_KIND_PROPERTY)
    canonical = kind if kind in GROUP_NAMES else canonical_group(group.name(), GROUP_NAMES)
    if canonical is None:
        return False
    tr_dict = GROUP_NAMES[canonical]
    new_name = tr_dict.get(lang) or tr_dict.get("en", group.name())
    if new_name == group.name():
        return False
    group.setName(new_name)
    return True


def apply_group_names(lang: str | None = None):
    """Renomme les groupes du Layer Tree selon la langue.

    Parcourt les enfants de la racine et ceux des groupes d'operateur
    (GROUP_SCHEMA_PROPERTY) et de « Commun » (GROUP_KIND_PROPERTY == Commun) ;
    les groupes personnels et leur contenu ne sont pas touches."""
    lang = lang or get_language()
    root = QgsProject.instance().layerTreeRoot()
    renamed = 0

    for child in root.children():
        if not _is_group(child):
            continue
        if _rename_group(child, lang):
            renamed += 1
        if child.customProperty(GROUP_SCHEMA_PROPERTY) or child.customProperty(GROUP_KIND_PROPERTY) == COMMON_ROOT:
            for sub in child.children():
                if _is_group(sub) and _rename_group(sub, lang):
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
    uri = _pg_uri(layer)
    pg_table = uri.table() if uri is not None else None
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
# ValueRelation et get_feature — meme operateur (Bridge 1.9, plan D4)
# =====================================================================
# Les styles Farois designent la couche cible par son nom de table
# (LayerName "zone_pop", get_feature('zone_pop', ...)) et figent le schema
# modele wyre dans LayerSource. Avec plusieurs operateurs, chaque couche doit
# viser la couche de SON operateur : la cible est cherchee par (schema de la
# source, table) et designee par son identifiant, jamais par son nom affiche.

def _display_name_tables() -> dict[str, str]:
    """Nom traduit (FR/EN/PT) -> table. Un nom partage par deux tables est
    ignore plutot que devine."""
    names: dict[str, str] = {}
    ambiguous: set[str] = set()
    for table, translations in LAYER_DISPLAY_NAMES.items():
        for translated in translations.values():
            if names.setdefault(translated, table) != table:
                ambiguous.add(translated)
    for translated in ambiguous:
        names.pop(translated, None)
    return names


_DISPLAY_NAME_TABLES = _display_name_tables()


class _ProjectLayers:
    """Couches vectorielles du projet dans l'ordre de ``project.mapLayers()``,
    indexees par identifiant, par nom et par source PostgreSQL (schema, table)."""

    def __init__(self, project):
        self.layers = [ly for ly in project.mapLayers().values() if isinstance(ly, QgsVectorLayer)]
        self.by_id: dict = {}
        self.by_name: dict = {}
        self.by_source: dict = {}
        self._sources: dict = {}
        for layer in self.layers:
            self.by_id[layer.id()] = layer
            self.by_name.setdefault(layer.name(), []).append(layer)
            uri = _pg_uri(layer)
            table = uri.table() if uri is not None else ""
            if table:
                key = (uri.schema(), table)
                self._sources[layer.id()] = key
                self.by_source.setdefault(key, []).append(layer)
        self.tables = {table for _schema, table in self.by_source}
        self._labels = project_operator_naming(project)[0]
        self._targets: dict = {}

    def source(self, layer):
        """(schema, table) de la source PostgreSQL, None pour une autre source."""
        return self._sources.get(layer.id())

    def first(self, schema: str, table: str):
        layers = self.by_source.get((schema, table))
        return layers[0] if layers else None

    def _table_of(self, layer):
        source = self.source(layer)
        return source[1] if source else None

    def designated(self, config):
        """``(table, couches)`` qu'une ValueRelation designe : ``Layer``
        (identifiant d'une couche du projet), sinon ``LayerName`` (nom exact
        d'une couche du projet, nom de table, nom traduit avec ou sans
        suffixe). Le suffixe ne sert qu'a retrouver la table, jamais
        l'operateur. *couches* : celles que la reference designe deja
        (vide pour un nom de table ou un nom perime)."""
        layer = self.by_id.get(config.get("Layer") or "")
        if layer is not None:
            return self._table_of(layer), [layer]
        name = config.get("LayerName") or ""
        if not name:
            return None, []
        named = self.by_name.get(name)
        if named:
            return self._table_of(named[0]), named
        if name in self.tables or name in OPERATOR_TABLES:
            return name, []
        table = _DISPLAY_NAME_TABLES.get(name) or _DISPLAY_NAME_TABLES.get(split_operator_suffix(name)[0])
        return table, []

    def targets(self, schema: str) -> dict:
        """Premier argument de get_feature -> identifiant de la couche de
        (schema, t), pour chaque table operateur t chargee dans *schema* :
        t, ses noms traduits avec et sans chaque suffixe connu
        (``bridge/operator_labels``), noms et identifiants des couches de t
        des autres schemas. Une cle qui designerait deux tables est ignoree."""
        if schema in self._targets:
            return self._targets[schema]
        targets: dict = {}
        ambiguous: set = set()
        for (layer_schema, table), layers in self.by_source.items():
            if layer_schema != schema or table not in OPERATOR_TABLES:
                continue
            target_id = layers[0].id()
            keys = {table}
            for translated in LAYER_DISPLAY_NAMES.get(table, {}).values():
                keys.add(translated)
                keys.update(operator_layer_name(translated, label) for label in self._labels.values())
            for (other_schema, other_table), others in self.by_source.items():
                if other_table == table and other_schema != schema:
                    for other in others:
                        keys.update((other.name(), other.id()))
            for key in keys:
                if targets.setdefault(key, target_id) != target_id:
                    ambiguous.add(key)
        for key in ambiguous:
            targets.pop(key, None)
        self._targets[schema] = targets
        return targets


def _value_relations(layer):
    """(index du champ, copie de la configuration) de chaque ValueRelation."""
    fields = layer.fields()
    for i in range(fields.count()):
        setup = layer.editorWidgetSetup(i)
        if setup.type() == "ValueRelation":
            yield i, dict(setup.config())


def _retarget_value_relation(config: dict, schema: str, index: _ProjectLayers) -> bool:
    """Oriente la ValueRelation *config* (modifiee en place) vers la couche de
    (*schema*, t). Table t non operateur : rien. Couche deja designee de
    (schema, t) (copie filtree comprise) : gardee, ``Layer`` et ``LayerName``
    resynchronises sur elle ; sinon la premiere couche de (schema, t) ; aucune :
    rien, jamais la couche d'un autre operateur. ``LayerSource`` (s'il existe)
    passe dans *schema*. True si *config* a change."""
    table, designated = index.designated(config)
    if table not in OPERATOR_TABLES:
        return False
    target = next((ly for ly in designated if index.source(ly) == (schema, table)), None)
    if target is None:
        target = index.first(schema, table)
    if target is None:
        return False
    wanted = {"Layer": target.id(), "LayerName": target.name()}
    layer_source = config.get("LayerSource") or ""
    if layer_source:
        wanted["LayerSource"] = retarget_layer_source(layer_source, schema)
    changed = {key: value for key, value in wanted.items() if config.get(key) != value}
    config.update(changed)
    return bool(changed)


def _style_schema(config: dict) -> str:
    """Schema que le ``LayerSource`` d'une ValueRelation designe, tel que le
    style l'a defini (K7) ; sans source lisible, le schema modele des QML
    Farois (wyre)."""
    from .bridge_nominatif import datasource_param

    table = datasource_param(config.get("LayerSource") or "", "table") or ""
    schema, sep, _table = table.partition(".")
    return schema if sep and schema else OPERATOR_TEMPLATE_SCHEMA


def _retarget_operator_layers(index: _ProjectLayers) -> int:
    """Corps de retarget_operator_references sur un index deja construit."""
    modified = 0
    for layer in index.layers:
        source = index.source(layer)
        if source is None or source[1] not in OPERATOR_TABLES:
            continue
        schema = source[0]
        targets = index.targets(schema)
        changed = False
        for i, config in _value_relations(layer):
            dirty = _retarget_value_relation(config, schema, index)
            value = config.get("Value") or ""
            new_value = retarget_get_feature(value, targets)
            if new_value != value:
                config["Value"] = new_value
                dirty = True
            if dirty:
                layer.setEditorWidgetSetup(i, QgsEditorWidgetSetup("ValueRelation", config))
                changed = True
        tip = layer.mapTipTemplate()
        new_tip = retarget_get_feature(tip, targets)
        if new_tip != tip:
            layer.setMapTipTemplate(new_tip)
            changed = True
        display = layer.displayExpression()
        new_display = retarget_get_feature(display, targets)
        if new_display != display:
            layer.setDisplayExpression(new_display)
            changed = True
        modified += changed
    return modified


def retarget_operator_references(project) -> int:
    """Chaque couche operateur (QgsVectorLayer PostgreSQL d'une table de
    OPERATOR_TABLES ; operateur = schema de sa source) vise les couches de
    son propre operateur :

    - ses ValueRelation vers une table operateur : ``Layer`` (identifiant),
      ``LayerName`` (nom courant) et ``LayerSource`` (schema reecrit) de la
      premiere couche du meme schema, une copie filtree deja designee etant
      gardee ; cible absente de ce schema : rien, jamais un autre operateur ;
    - le premier argument de get_feature dans le ``Value`` de ses
      ValueRelation, son infobulle (``mapTipTemplate``) et son expression
      d'affichage (``displayExpression``) : identifiant de la couche du meme
      schema (voir ``_ProjectLayers.targets``).

    Idempotent. Retourne le nombre de couches modifiees."""
    return _retarget_operator_layers(_ProjectLayers(project))


def _sync_value_relation_layer_names(project):
    """Recible les ValueRelation (LayerName, Layer, LayerSource) et les
    get_feature() apres renommage des couches (traduction, suffixe de
    l'operateur) ou rechargement des styles, qui designent la couche cible
    par son nom de table (zone_pop -> « Zones POP · Orange »).

    - Couche operateur -> table operateur : retarget_operator_references
      (meme schema que la couche source, par identifiant).
    - Couche commune (chantier...) -> table operateur : le schema est celui
      que le LayerSource de la liste designe, tel que le style le definit
      (K7) ; couche absente de ce schema : rien. Jamais « dernier gagnant »,
      jamais un autre operateur.
    - Toute couche -> table commune : LayerName remappe sur le nom courant
      seulement s'il ne se resout pas (une couche qui porte deja ce nom est
      la bonne : copie filtree, couche personnelle homonyme), get_feature
      sur le nom courant.

    Retourne le nombre de couches operateur et de widgets modifies.
    """
    index = _ProjectLayers(project)
    if not index.by_source:
        return 0
    patched = _retarget_operator_layers(index)

    # Tables communes : chargees une fois (la premiere couche l'emporte).
    common_names: dict[str, str] = {}
    for (_schema, table), layers in index.by_source.items():
        if table not in OPERATOR_TABLES:
            common_names.setdefault(table, layers[0].name())

    for layer in index.layers:
        source = index.source(layer)
        operator_layer = source is not None and source[1] in OPERATOR_TABLES
        for i, config in _value_relations(layer):
            dirty = False
            value = config.get("Value") or ""
            if not operator_layer:
                schema = _style_schema(config)
                dirty = _retarget_value_relation(config, schema, index)
                value = retarget_get_feature(value, index.targets(schema))
            ref_name = config.get("LayerName") or ""
            if ref_name in common_names and ref_name not in index.by_name:
                config["LayerName"] = common_names[ref_name]
                dirty = True
            value = retarget_get_feature(value, common_names)
            if value != (config.get("Value") or ""):
                config["Value"] = value
                dirty = True
            if dirty:
                layer.setEditorWidgetSetup(i, QgsEditorWidgetSetup("ValueRelation", config))
                patched += 1

    return patched


def rewrite_value_relation_sources(project, login: str, authcfg_id: str, hosts) -> int:
    """Rattache le ``LayerSource`` des ValueRelation pointant sur nos
    serveurs a l'identite nominative du poste (Bridge 1.8, B9).

    Les QML Farois (embarques et en base) figent ``user='ftth_editor'
    sslmode=require`` dans LayerSource. QGIS ne consulte cette source que
    si la couche cible n'est ni dans le projet (Layer) ni resolvable par
    LayerName ; il ouvrirait alors une connexion avec un identifiant dont
    un poste nominatif n'a plus le mot de passe (invite bloquante, ou
    identifiant partage apres la cloture). Reecriture :
    ``sslmode=verify-full user='<login>' authcfg=<id>``, sans mot de
    passe, serveurs tiers ignores. Retourne le nombre de widgets corriges.
    """
    from .bridge_nominatif import datasource_param, rewrite_datasource_nominal

    known_hosts = {h for h in hosts if h}
    patched = 0
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        fields = layer.fields()
        for i in range(fields.count()):
            setup = layer.editorWidgetSetup(i)
            if setup.type() != "ValueRelation":
                continue
            config = dict(setup.config())
            source = config.get("LayerSource", "")
            # Revue 2 (M7) : hote compare exactement, pas par sous-chaine.
            if not source or datasource_param(source, "host") not in known_hosts:
                continue
            new_source = rewrite_datasource_nominal(source, login, authcfg_id)
            if new_source == source:
                continue
            config["LayerSource"] = new_source
            layer.setEditorWidgetSetup(i, QgsEditorWidgetSetup("ValueRelation", config))
            patched += 1
    return patched


def value_relations_use_form_lists(project) -> bool:
    """True si au moins une liste de valeurs du projet cible
    ``ref.v_form_lists`` (par LayerName ou par LayerSource) -- seule raison
    de charger cette couche cachee (revue 29/10, I7)."""
    from .bridge_nominatif import datasource_param

    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        fields = layer.fields()
        for i in range(fields.count()):
            setup = layer.editorWidgetSetup(i)
            if setup.type() != "ValueRelation":
                continue
            config = setup.config()
            if config.get("LayerName") == "v_form_lists":
                return True
            if datasource_param(config.get("LayerSource") or "", "table") == "ref.v_form_lists":
                return True
    return False


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
    naming = project_operator_naming(project)

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
        apply_layer_name(layer, lang, naming)

    # Apres renommage des couches, recibler les ValueRelation (et les
    # get_feature) sur les couches du meme operateur pour que les FK
    # affichent nom/code, pas UUID
    vr_synced = _sync_value_relation_layer_names(project)

    groups_renamed = apply_group_names(lang)

    # Variable projet accessible via @wyre_language dans les expressions QGIS
    # (QGIS n'evalue pas d'expression dans le Value d'une ValueRelation : les
    # styles affichent label_fr et apply_value_relation_columns bascule la langue)
    QgsExpressionContextUtils.setProjectVariable(project, "wyre_language", lang)

    _log(
        f"i18n [{lang}]: {layers_translated} couche(s) traduites, "
        f"{vr_switched} ValueRelation basculee(s), "
        f"{vr_synced} reference(s) de couche synchronisee(s), "
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
    # Sync les LayerName des VR de toutes les couches qui pourraient
    # referencer cette couche nouvellement renommee
    _sync_value_relation_layer_names(QgsProject.instance())
