# -*- coding: utf-8 -*-
"""
Constructel Bridge — Traductions des alias de champs par couche.

Structure: FIELD_ALIASES[table_name][field_name] = {lang: alias}

Les tables ref.* utilisent ``label_fr``, ``label_en``, ``label_pt``.
Le mapping VALUE_RELATION_COLUMNS indique quelle colonne afficher
dans les widgets ValueRelation selon la langue.
"""

# =====================================================================
# Champs communs reutilises dans plusieurs couches
# =====================================================================
_COMMON = {
    "id":                  {"fr": "ID",                   "en": "ID",                    "pt": "ID"},
    "zone_pop_id":         {"fr": "Zone POP",             "en": "POP Zone",               "pt": "Zona POP"},
    "zone_mro_id":         {"fr": "Zone MRO",             "en": "MRO Zone",               "pt": "Zona MRO"},
    "marlin_id":           {"fr": "ID Marlin",            "en": "Marlin ID",              "pt": "ID Marlin"},
    "nomenclature":        {"fr": "Nomenclature",         "en": "Nomenclature",           "pt": "Nomenclatura"},
    "status":              {"fr": "Statut",               "en": "Status",                 "pt": "Estado"},
    "transition_source":   {"fr": "Source transition",    "en": "Transition source",      "pt": "Fonte transicao"},
    "source_data":         {"fr": "Source donnees",        "en": "Data source",            "pt": "Fonte dados"},
    "doc_count":           {"fr": "Nb documents",         "en": "Doc count",              "pt": "Nr documentos"},
    "doc_folder_url":      {"fr": "Dossier SharePoint",   "en": "SharePoint folder",      "pt": "Pasta SharePoint"},
    "created_at":          {"fr": "Cree le",              "en": "Created at",             "pt": "Criado em"},
    "updated_at":          {"fr": "Modifie le",           "en": "Updated at",             "pt": "Atualizado em"},
    "planned_date":        {"fr": "Date planification",   "en": "Planned date",           "pt": "Data planeamento"},
    "completion_date":     {"fr": "Date realisation",     "en": "Completion date",        "pt": "Data conclusao"},
    "validation_date":     {"fr": "Date validation",      "en": "Validation date",        "pt": "Data validacao"},
    "geom":                {"fr": "Geometrie",            "en": "Geometry",               "pt": "Geometria"},
}

_ZONE_STATS = {
    "area":                    {"fr": "Surface (m2)",         "en": "Area (m2)",              "pt": "Area (m2)"},
    "dp_sum_total":            {"fr": "DP Total",             "en": "DP Total",               "pt": "DP Total"},
    "dp_sum_hp":               {"fr": "DP HP",                "en": "DP HP",                  "pt": "DP HP"},
    "dp_sum_nhp":              {"fr": "DP N-HP",              "en": "DP N-HP",                "pt": "DP N-HP"},
    "dp_sum_le":               {"fr": "DP LE",                "en": "DP LE",                  "pt": "DP LE"},
    "dp_sum_pd":               {"fr": "DP PD",                "en": "DP PD",                  "pt": "DP PD"},
    "dp_progress_percentage":  {"fr": "% Avancement DP",      "en": "DP progress %",          "pt": "% Progresso DP"},
}

# =====================================================================
# FIELD_ALIASES — par table (nom PostgreSQL sans schema)
# =====================================================================

FIELD_ALIASES: dict[str, dict[str, dict[str, str]]] = {

    # -----------------------------------------------------------------
    # infra.structures
    # -----------------------------------------------------------------
    "structures": {
        **_COMMON,
        "structure_type":          {"fr": "Type",                "en": "Type",                   "pt": "Tipo"},
        "label":                   {"fr": "Label",               "en": "Label",                  "pt": "Descricao"},
        "is_splice_closure":       {"fr": "Boitier d'epissurage","en": "Splice closure",         "pt": "Caixa de emenda"},
        "nearest_demand_point_id": {"fr": "Point demande",       "en": "Demand point",           "pt": "Ponto procura"},
        "nearest_address":         {"fr": "Adresse proche",      "en": "Nearest address",        "pt": "Morada proxima"},
    },

    # -----------------------------------------------------------------
    # infra.cables
    # -----------------------------------------------------------------
    "cables": {
        **_COMMON,
        "name":                {"fr": "Nom",                "en": "Name",                   "pt": "Nome"},
        "model":               {"fr": "Modele",             "en": "Model",                  "pt": "Modelo"},
        "cable_type":          {"fr": "Type cable",         "en": "Cable type",             "pt": "Tipo cabo"},
        "breakout_letter":     {"fr": "Breakout",           "en": "Breakout",               "pt": "Breakout"},
        "start_point_id":      {"fr": "UUID debut",         "en": "Start point UUID",       "pt": "UUID inicio"},
        "end_point_id":        {"fr": "UUID fin",           "en": "End point UUID",         "pt": "UUID fim"},
        "length_m":            {"fr": "Longueur (m)",       "en": "Length (m)",             "pt": "Comprimento (m)"},
        "pose_type":           {"fr": "Type pose",          "en": "Laying type",            "pt": "Tipo instalacao"},
        "blowing_date":        {"fr": "Date soufflage",     "en": "Blowing date",           "pt": "Data sopragem"},
        "measurement_date":    {"fr": "Date mesure",        "en": "Measurement date",       "pt": "Data medicao"},
        "otdr_measurements":   {"fr": "Mesures OTDR",       "en": "OTDR measurements",      "pt": "Medicoes OTDR"},
    },

    # -----------------------------------------------------------------
    # infra.ducts
    # -----------------------------------------------------------------
    "ducts": {
        **_COMMON,
        "model":               {"fr": "Modele",             "en": "Model",                  "pt": "Modelo"},
        "start_point_id":      {"fr": "UUID debut",         "en": "Start point UUID",       "pt": "UUID inicio"},
        "end_point_id":        {"fr": "UUID fin",           "en": "End point UUID",         "pt": "UUID fim"},
        "length_m":            {"fr": "Longueur (m)",       "en": "Length (m)",             "pt": "Comprimento (m)"},
        "subduct_count":       {"fr": "Nb sous-fourreaux",  "en": "Subduct count",          "pt": "Nr subductos"},
    },

    # -----------------------------------------------------------------
    # infra.subducts
    # -----------------------------------------------------------------
    "subducts": {
        **_COMMON,
        "duct_id":             {"fr": "Conduite parent",    "en": "Parent duct",            "pt": "Ducto principal"},
        "model":               {"fr": "Modele",             "en": "Model",                  "pt": "Modelo"},
        "cable_id":            {"fr": "Cable",              "en": "Cable",                  "pt": "Cabo"},
        "start_structure_id":  {"fr": "Structure debut",    "en": "Start structure",        "pt": "Estrutura inicio"},
        "end_structure_id":    {"fr": "Structure fin",      "en": "End structure",          "pt": "Estrutura fim"},
    },

    # -----------------------------------------------------------------
    # infra.demand_points
    # -----------------------------------------------------------------
    "demand_points": {
        **_COMMON,
        "zone_drop_id":            {"fr": "Zone Drop",          "en": "Drop Zone",              "pt": "Zona Drop"},
        "zone_distribution_id":    {"fr": "Zone Distribution",  "en": "Distribution Zone",      "pt": "Zona Distribuicao"},
        "agg_id":                  {"fr": "ID Aggregation",     "en": "Aggregation ID",         "pt": "ID Agregacao"},
        "identifier":              {"fr": "Identifiant",        "en": "Identifier",             "pt": "Identificador"},
        "full_address":            {"fr": "Adresse complete",   "en": "Full address",           "pt": "Morada completa"},
        "street":                  {"fr": "Rue",                "en": "Street",                 "pt": "Rua"},
        "street_number":           {"fr": "Numero",             "en": "Number",                 "pt": "Numero"},
        "postal_code":             {"fr": "Code postal",        "en": "Postal code",            "pt": "Codigo postal"},
        "city":                    {"fr": "Ville",              "en": "City",                   "pt": "Cidade"},
        "homecount":               {"fr": "Nb logements",       "en": "Home count",             "pt": "Nr habitacoes"},
        "planning_date":           {"fr": "Date planification", "en": "Planning date",          "pt": "Data planeamento"},
        "connection_date":         {"fr": "Date raccordement",  "en": "Connection date",        "pt": "Data ligacao"},
    },

    # -----------------------------------------------------------------
    # infra.topology_violations
    # -----------------------------------------------------------------
    "topology_violations": {
        "id":                    {"fr": "ID",                  "en": "ID",                     "pt": "ID"},
        "violation_type":        {"fr": "Type violation",      "en": "Violation type",         "pt": "Tipo violacao"},
        "severity":              {"fr": "Severite",            "en": "Severity",               "pt": "Severidade"},
        "element_type":          {"fr": "Type element",        "en": "Element type",           "pt": "Tipo elemento"},
        "element_id":            {"fr": "ID element",          "en": "Element ID",             "pt": "ID elemento"},
        "related_element_type":  {"fr": "Type element lie",    "en": "Related element type",   "pt": "Tipo elemento rel."},
        "related_element_id":    {"fr": "ID element lie",      "en": "Related element ID",     "pt": "ID elemento rel."},
        "description":           {"fr": "Description",         "en": "Description",            "pt": "Descricao"},
        "metric_value":          {"fr": "Valeur metrique",     "en": "Metric value",           "pt": "Valor metrico"},
        "metric_unit":           {"fr": "Unite",               "en": "Unit",                   "pt": "Unidade"},
        "geom":                  {"fr": "Geometrie",           "en": "Geometry",               "pt": "Geometria"},
        "detected_at":           {"fr": "Detecte le",          "en": "Detected at",            "pt": "Detetado em"},
        "resolved_at":           {"fr": "Resolu le",           "en": "Resolved at",            "pt": "Resolvido em"},
        "resolved_by":           {"fr": "Resolu par",          "en": "Resolved by",            "pt": "Resolvido por"},
        "notes":                 {"fr": "Notes",               "en": "Notes",                  "pt": "Notas"},
    },

    # -----------------------------------------------------------------
    # infra.zone_mro
    # -----------------------------------------------------------------
    "zone_mro": {
        **_COMMON,
        **_ZONE_STATS,
        "name":                {"fr": "Nom",                "en": "Name",                   "pt": "Nome"},
        "description":         {"fr": "Description",        "en": "Description",            "pt": "Descricao"},
    },

    # -----------------------------------------------------------------
    # infra.zone_pop
    # -----------------------------------------------------------------
    "zone_pop": {
        **_COMMON,
        **_ZONE_STATS,
        "esid":                    {"fr": "ESID",               "en": "ESID",                   "pt": "ESID"},
        "code":                    {"fr": "Code",               "en": "Code",                   "pt": "Codigo"},
        "name":                    {"fr": "Nom",                "en": "Name",                   "pt": "Nome"},
        "mro_code":                {"fr": "Code MRO",           "en": "MRO code",               "pt": "Codigo MRO"},
        "pop_code":                {"fr": "Code POP",           "en": "POP code",               "pt": "Codigo POP"},
        "hierarchy_level":         {"fr": "Niveau hierarchie",  "en": "Hierarchy level",        "pt": "Nivel hierarquia"},
        "client":                  {"fr": "Client",             "en": "Client",                 "pt": "Cliente"},
        "entrepreneur":            {"fr": "Entrepreneur",       "en": "Contractor",             "pt": "Empreiteiro"},
        "city":                    {"fr": "Ville",              "en": "City",                   "pt": "Cidade"},
        "address":                 {"fr": "Adresse",            "en": "Address",                "pt": "Morada"},
        "postal_code":             {"fr": "Code postal",        "en": "Postal code",            "pt": "Codigo postal"},
        "total_structures":        {"fr": "Total structures",   "en": "Total structures",       "pt": "Total estruturas"},
        "total_cables":            {"fr": "Total cables",       "en": "Total cables",           "pt": "Total cabos"},
        "total_breakouts":         {"fr": "Total breakouts",    "en": "Total breakouts",        "pt": "Total breakouts"},
        "nb_distribution_clusters":{"fr": "Nb clusters distrib","en": "Distribution clusters",  "pt": "Clusters distrib"},
        "planned_start_date":      {"fr": "Debut planifie",     "en": "Planned start",          "pt": "Inicio planeado"},
        "planned_end_date":        {"fr": "Fin planifiee",      "en": "Planned end",            "pt": "Fim planeado"},
        "actual_start_date":       {"fr": "Debut reel",         "en": "Actual start",           "pt": "Inicio real"},
        "actual_end_date":         {"fr": "Fin reelle",         "en": "Actual end",             "pt": "Fim real"},
        "reception_date":          {"fr": "Date reception",     "en": "Reception date",         "pt": "Data rececao"},
        "commissioning_date":      {"fr": "Date mise en service","en": "Commissioning date",    "pt": "Data comissionamento"},
        "nb_hp_sent":              {"fr": "Nb HP envoyes",      "en": "HP sent count",          "pt": "Nr HP enviados"},
        "smartwork_reference":     {"fr": "Ref SmartWork",      "en": "SmartWork ref",          "pt": "Ref SmartWork"},
        "sous_traitant":           {"fr": "Sous-traitant",      "en": "Subcontractor",          "pt": "Subempreiteiro"},
        "splicing_pct":            {"fr": "% Epissurage",       "en": "Splicing %",             "pt": "% Emenda"},
    },

    # -----------------------------------------------------------------
    # infra.zone_distribution
    # -----------------------------------------------------------------
    "zone_distribution": {
        **_COMMON,
        **_ZONE_STATS,
        "agg_id":                  {"fr": "ID Aggregation",     "en": "Aggregation ID",         "pt": "ID Agregacao"},
        "breakout_letter":         {"fr": "Breakout",           "en": "Breakout",               "pt": "Breakout"},
        "occupied":                {"fr": "Occupe",             "en": "Occupied",               "pt": "Ocupado"},
        "zone_type":               {"fr": "Type zone",          "en": "Zone type",              "pt": "Tipo zona"},
        "installation_date":       {"fr": "Date installation",  "en": "Installation date",      "pt": "Data instalacao"},
        "splice_date":             {"fr": "Date epissurage",    "en": "Splice date",            "pt": "Data emenda"},
        "measurement_date":        {"fr": "Date mesure",        "en": "Measurement date",       "pt": "Data medicao"},
        "address":                 {"fr": "Adresse",            "en": "Address",                "pt": "Morada"},
        "city":                    {"fr": "Ville",              "en": "City",                   "pt": "Cidade"},
        "postal_code":             {"fr": "Code postal",        "en": "Postal code",            "pt": "Codigo postal"},
    },

    # -----------------------------------------------------------------
    # infra.zone_drop
    # -----------------------------------------------------------------
    "zone_drop": {
        **_COMMON,
        **_ZONE_STATS,
        "zone_distribution_id":    {"fr": "Zone Distribution",  "en": "Distribution Zone",      "pt": "Zona Distribuicao"},
        "agg_id":                  {"fr": "ID Aggregation",     "en": "Aggregation ID",         "pt": "ID Agregacao"},
        "address":                 {"fr": "Adresse",            "en": "Address",                "pt": "Morada"},
        "city":                    {"fr": "Ville",              "en": "City",                   "pt": "Cidade"},
        "postal_code":             {"fr": "Code postal",        "en": "Postal code",            "pt": "Codigo postal"},
    },
}


# =====================================================================
# LAYER NAMES — nom QGIS → clé FIELD_ALIASES
# =====================================================================
# Permet de matcher un nom de couche QGIS au bon dict de traductions.
# Si le layer.name() match une clé de FIELD_ALIASES directement, ce
# mapping n'est pas nécessaire. Sinon on peut ajouter des alias ici.

LAYER_NAME_MAP: dict[str, str] = {
    # "nom affiché dans QGIS": "clé dans FIELD_ALIASES"
    # Par défaut le nom == la clé, ces entrées sont pour les exceptions
}


# =====================================================================
# LABEL_EXPRESSIONS — expressions d'etiquettes multilingues
# =====================================================================
# Clé : table PostgreSQL
# Valeur : {lang: expression QGIS}
#
# Seules les couches dont les etiquettes contiennent du texte
# hardcode a traduire sont listees ici. Les autres (nomenclature,
# code, homecount…) affichent des donnees brutes sans traduction.

LABEL_EXPRESSIONS: dict[str, dict[str, str]] = {
    "zone_distribution": {
        "fr": (
            "COALESCE(\"nomenclature\", \"breakout_letter\") || '\\n' || "
            "ROUND(COALESCE(\"dp_progress_percentage\", 0), 1) || '% avancement'"
        ),
        "en": (
            "COALESCE(\"nomenclature\", \"breakout_letter\") || '\\n' || "
            "ROUND(COALESCE(\"dp_progress_percentage\", 0), 1) || '% progress'"
        ),
        "pt": (
            "COALESCE(\"nomenclature\", \"breakout_letter\") || '\\n' || "
            "ROUND(COALESCE(\"dp_progress_percentage\", 0), 1) || '% progresso'"
        ),
    },
    "zone_drop": {
        "fr": (
            "COALESCE(\"nomenclature\", 'ZD' || \"id\") || '\\n' || "
            "ROUND(COALESCE(\"dp_progress_percentage\", 0), 1) || '% avancement'"
        ),
        "en": (
            "COALESCE(\"nomenclature\", 'ZD' || \"id\") || '\\n' || "
            "ROUND(COALESCE(\"dp_progress_percentage\", 0), 1) || '% progress'"
        ),
        "pt": (
            "COALESCE(\"nomenclature\", 'ZD' || \"id\") || '\\n' || "
            "ROUND(COALESCE(\"dp_progress_percentage\", 0), 1) || '% progresso'"
        ),
    },
}


# VALUE_RELATION_COLUMNS — bascule colonne Value des dropdowns selon la langue
# =====================================================================
# Clé: nom de la couche de référence (LayerName dans le widget config)
# Valeur: {lang: colonne à utiliser comme Value}
#
# v4.0: ref.v_form_lists expose label_fr, label_en, label_pt.
# Le plugin bascule la colonne selon la langue active.
# Fallback QML: expression map_get(@wyre_language) si plugin absent.

VALUE_RELATION_COLUMNS: dict[str, dict[str, str]] = {
    "v_form_lists":  {"fr": "label_fr", "en": "label_en", "pt": "label_pt"},
}


# =====================================================================
# GROUP NAMES — traductions des noms de groupes du Layer Tree
# =====================================================================

GROUP_NAMES: dict[str, dict[str, str]] = {
    "Zones":           {"fr": "Zones",               "en": "Zones",               "pt": "Zonas"},
    "Infrastructure":  {"fr": "Infrastructure",      "en": "Infrastructure",      "pt": "Infraestrutura"},
    "Demand Points":   {"fr": "Points de demande",   "en": "Demand Points",       "pt": "Pontos de procura"},
    "Listes":          {"fr": "Listes",              "en": "Lists",               "pt": "Listas"},
    "Topologie":       {"fr": "Topologie",           "en": "Topology",            "pt": "Topologia"},
}


# =====================================================================
# LAYER DISPLAY NAMES — traductions des noms de couches
# =====================================================================

# =====================================================================
# FORM_CONTAINERS — traductions des onglets (Tab) et groupes (GroupBox)
# =====================================================================
# Clé : nom FR actuel dans le QML (avec emojis).
# Les noms sont partagés entre couches — un même nom traduit partout.
#
# Pour les containers qui apparaissent dans plusieurs couches avec le
# même sens, on utilise un dict commun. Les noms spécifiques à une
# couche sont ajoutés dans le dict de la couche dans FORM_CONTAINERS_PER_LAYER.

_FORM_COMMON: dict[str, dict[str, str]] = {
    # --- Tabs communs ---
    "🎯 Principal":          {"fr": "🎯 Principal",          "en": "🎯 Main",                "pt": "🎯 Principal"},
    "🔧 Technique":          {"fr": "🔧 Technique",          "en": "🔧 Technical",           "pt": "🔧 Tecnico"},
    "🔗 Liens":              {"fr": "🔗 Liens",              "en": "🔗 Links",               "pt": "🔗 Ligacoes"},
    "🏷️ Identification":    {"fr": "🏷️ Identification",    "en": "🏷️ Identification",     "pt": "🏷️ Identificacao"},
    "ℹ️ Info":               {"fr": "ℹ️ Info",               "en": "ℹ️ Info",                "pt": "ℹ️ Info"},
    "Documents":              {"fr": "Documents",              "en": "Documents",               "pt": "Documentos"},
    "📍 Localisation":       {"fr": "📍 Localisation",       "en": "📍 Location",            "pt": "📍 Localizacao"},
    "📅 Planning":           {"fr": "📅 Planning",           "en": "📅 Planning",            "pt": "📅 Planeamento"},
    "📊 Métriques":          {"fr": "📊 Métriques",          "en": "📊 Metrics",             "pt": "📊 Metricas"},
    "📐 Surface":            {"fr": "📐 Surface",            "en": "📐 Area",                "pt": "📐 Area"},
    "🏠 Adresse":            {"fr": "🏠 Adresse",            "en": "🏠 Address",             "pt": "🏠 Morada"},

    # --- GroupBoxes communs ---
    "⚡ Actions Terrain":    {"fr": "⚡ Actions Terrain",    "en": "⚡ Field Actions",        "pt": "⚡ Acoes Terreno"},
    "📅 Dates":              {"fr": "📅 Dates",              "en": "📅 Dates",               "pt": "📅 Datas"},
    "📅 Dates clés":         {"fr": "📅 Dates clés",         "en": "📅 Key Dates",           "pt": "📅 Datas chave"},
    "📅 Dates Workflow":     {"fr": "📅 Dates Workflow",     "en": "📅 Workflow Dates",      "pt": "📅 Datas Workflow"},
    "🏷️ Nommage":           {"fr": "🏷️ Nommage",           "en": "🏷️ Naming",             "pt": "🏷️ Nomenclatura"},
    "🔑 Identifiant":       {"fr": "🔑 Identifiant",       "en": "🔑 Identifier",          "pt": "🔑 Identificador"},
    "💾 Source":             {"fr": "💾 Source",             "en": "💾 Source",               "pt": "💾 Fonte"},
    "💾 Sources":            {"fr": "💾 Sources",            "en": "💾 Sources",              "pt": "💾 Fontes"},
    "📊 Audit":              {"fr": "📊 Audit",              "en": "📊 Audit",               "pt": "📊 Auditoria"},
    "📊 Metrics":            {"fr": "📊 Metrics",            "en": "📊 Metrics",             "pt": "📊 Metricas"},
    "🗺️ Zones":             {"fr": "🗺️ Zones",             "en": "🗺️ Zones",              "pt": "🗺️ Zonas"},
    "📍 Zones":              {"fr": "📍 Zones",              "en": "📍 Zones",               "pt": "📍 Zonas"},
    "📍 Résumé":             {"fr": "📍 Résumé",             "en": "📍 Summary",             "pt": "📍 Resumo"},
    "📍 Connexions":         {"fr": "📍 Connexions",         "en": "📍 Connections",         "pt": "📍 Conexoes"},
    "🎯 IDs Externes":      {"fr": "🎯 IDs Externes",      "en": "🎯 External IDs",        "pt": "🎯 IDs Externos"},
    "🎯 Identifiants Externes": {"fr": "🎯 Identifiants Externes", "en": "🎯 External Identifiers", "pt": "🎯 Identificadores Externos"},
    "🔗 ID Externe":        {"fr": "🔗 ID Externe",        "en": "🔗 External ID",         "pt": "🔗 ID Externo"},
    "Resume documentaire":    {"fr": "Resume documentaire",    "en": "Document summary",       "pt": "Resumo documental"},
    "Lien dossier SharePoint":{"fr": "Lien dossier SharePoint","en": "SharePoint folder link",  "pt": "Link pasta SharePoint"},
    "Liens documents (clic pour ouvrir)": {
        "fr": "Liens documents (clic pour ouvrir)",
        "en": "Document links (click to open)",
        "pt": "Links documentos (clicar para abrir)",
    },
    "📏 Dimensions":         {"fr": "📏 Dimensions",         "en": "📏 Dimensions",          "pt": "📏 Dimensoes"},
    "📦 Modèle":             {"fr": "📦 Modèle",             "en": "📦 Model",               "pt": "📦 Modelo"},
    "📦 Classification":     {"fr": "📦 Classification",     "en": "📦 Classification",      "pt": "📦 Classificacao"},
    "📅 Planning":           {"fr": "📅 Planning",           "en": "📅 Planning",            "pt": "📅 Planeamento"},
}

# Containers specifiques à certaines couches
FORM_CONTAINERS_PER_LAYER: dict[str, dict[str, dict[str, str]]] = {

    "structures": {
        "🔧 Technique":              {"fr": "🔧 Technique",              "en": "🔧 Technical",            "pt": "🔧 Tecnico"},
        "🏠 Adresse Proche":         {"fr": "🏠 Adresse Proche",         "en": "🏠 Nearest Address",      "pt": "🏠 Morada Proxima"},
        "Soudures":                    {"fr": "Soudures",                    "en": "Splices",                  "pt": "Emendas"},
        "Progression soudure":         {"fr": "Progression soudure",         "en": "Splice progress",          "pt": "Progresso emenda"},
        "Câbles départ (Start)":      {"fr": "Câbles départ (Start)",      "en": "Outgoing cables (Start)",  "pt": "Cabos saida (Start)"},
        "Câbles arrivée (End)":       {"fr": "Câbles arrivée (End)",       "en": "Incoming cables (End)",    "pt": "Cabos entrada (End)"},
    },

    "cables": {
        "📊 Mesures OTDR":           {"fr": "📊 Mesures OTDR",           "en": "📊 OTDR Measurements",    "pt": "📊 Medicoes OTDR"},
    },

    "ducts": {
        "🔀 Extrémités":            {"fr": "🔀 Extrémités",            "en": "🔀 Endpoints",            "pt": "🔀 Extremidades"},
        "🏷️ Type &amp; Modèle":    {"fr": "🏷️ Type & Modèle",        "en": "🏷️ Type & Model",        "pt": "🏷️ Tipo & Modelo"},
        "🔤 Nomenclature":           {"fr": "🔤 Nomenclature",           "en": "🔤 Nomenclature",         "pt": "🔤 Nomenclatura"},
    },

    "subducts": {
        "🚧 Conduite":              {"fr": "🚧 Conduite",              "en": "🚧 Duct",                 "pt": "🚧 Ducto"},
    },

    "demand_points": {
        "📍 Adresse Complète":       {"fr": "📍 Adresse Complète",       "en": "📍 Full Address",         "pt": "📍 Morada Completa"},
        "🏷️ Composants":            {"fr": "🏷️ Composants",            "en": "🏷️ Components",          "pt": "🏷️ Componentes"},
        "🏢 Identifiant":            {"fr": "🏢 Identifiant",            "en": "🏢 Identifier",           "pt": "🏢 Identificador"},
        "📊 Données DP":             {"fr": "📊 Données DP",             "en": "📊 DP Data",              "pt": "📊 Dados DP"},
        "📶 Fibres":                  {"fr": "📶 Fibres",                  "en": "📶 Fibres",               "pt": "📶 Fibras"},
        "📊 Budget Optique":          {"fr": "📊 Budget Optique",          "en": "📊 Optical Budget",       "pt": "📊 Orcamento Optico"},
        "🗺️ Zones Principales":     {"fr": "🗺️ Zones Principales",     "en": "🗺️ Main Zones",          "pt": "🗺️ Zonas Principais"},
        "📦 Zones Distribution":      {"fr": "📦 Zones Distribution",      "en": "📦 Distribution Zones",   "pt": "📦 Zonas Distribuicao"},
        "🏠 Compteurs":               {"fr": "🏠 Compteurs",               "en": "🏠 Counters",             "pt": "🏠 Contadores"},
    },

    "zone_mro": {
        "📍 Zone MRO":               {"fr": "📍 Zone MRO",               "en": "📍 MRO Zone",             "pt": "📍 Zona MRO"},
    },

    "zone_pop": {
        "🏷️ POP":                   {"fr": "🏷️ POP",                   "en": "🏷️ POP",                 "pt": "🏷️ POP"},
        "🏢 Organisation":           {"fr": "🏢 Organisation",           "en": "🏢 Organization",         "pt": "🏢 Organizacao"},
        "📊 Infrastructure":          {"fr": "📊 Infrastructure",          "en": "📊 Infrastructure",       "pt": "📊 Infraestrutura"},
        "🗺️ Zone":                   {"fr": "🗺️ Zone",                   "en": "🗺️ Zone",                "pt": "🗺️ Zona"},
        "📍 Adresse":                 {"fr": "📍 Adresse",                 "en": "📍 Address",              "pt": "📍 Morada"},
    },

    "zone_distribution": {
        "📶 Capacité":                {"fr": "📶 Capacité",                "en": "📶 Capacity",             "pt": "📶 Capacidade"},
    },

    "zone_drop": {
        "📐 Surface":                 {"fr": "📐 Surface",                 "en": "📐 Area",                 "pt": "📐 Area"},
    },

}


LAYER_DISPLAY_NAMES: dict[str, dict[str, str]] = {
    "structures":         {"fr": "Structures",           "en": "Structures",           "pt": "Estruturas"},
    "cables":             {"fr": "Cables",               "en": "Cables",               "pt": "Cabos"},
    "ducts":              {"fr": "Conduites",            "en": "Ducts",                "pt": "Ductos"},
    "subducts":           {"fr": "Sous-fourreaux",       "en": "Subducts",             "pt": "Subductos"},
    "demand_points":      {"fr": "Points de demande",    "en": "Demand points",        "pt": "Pontos de procura"},
    "zone_mro":           {"fr": "Zones MRO",            "en": "MRO Zones",            "pt": "Zonas MRO"},
    "zone_pop":           {"fr": "Zones POP",            "en": "POP Zones",            "pt": "Zonas POP"},
    "zone_distribution":  {"fr": "Zones Distribution",   "en": "Distribution Zones",   "pt": "Zonas Distribuicao"},
    "zone_drop":          {"fr": "Zones Drop",           "en": "Drop Zones",           "pt": "Zonas Drop"},
    "topology_violations": {"fr": "Violations topologie", "en": "Topology violations",  "pt": "Violacoes topologia"},
}
