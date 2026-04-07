# -*- coding: utf-8 -*-
"""
Constructel Bridge — Traductions des alias de champs par couche.

Structure: FIELD_ALIASES[table_name][field_name] = {lang: alias}

Les tables ref.* utilisent ``label`` (FR) et ``label_en`` (EN).
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
# VALUE_RELATION_COLUMNS — bascule label FR/EN dans les dropdowns
# =====================================================================
# Clé: nom de la couche de référence (LayerName dans le widget config)
# Valeur: {lang: colonne à utiliser comme Value}
#
# Les tables ref.* ont ``label`` (FR) + ``label_en`` (EN).
# Pour PT on utilise label_en (anglais comme fallback).

VALUE_RELATION_COLUMNS: dict[str, dict[str, str]] = {
    "structure_types":   {"fr": "label", "en": "label_en", "pt": "label_en"},
    "cable_types":       {"fr": "label", "en": "label_en", "pt": "label_en"},
    "duct_models":       {"fr": "label", "en": "label_en", "pt": "label_en"},
    "pose_types":        {"fr": "label", "en": "label_en", "pt": "label_en"},
    "v_valid_statuses":  {"fr": "status_label", "en": "status_value", "pt": "status_value"},
}


# =====================================================================
# GROUP NAMES — traductions des noms de groupes du Layer Tree
# =====================================================================

GROUP_NAMES: dict[str, dict[str, str]] = {
    "Zones":           {"fr": "Zones",               "en": "Zones",               "pt": "Zonas"},
    "Infrastructure":  {"fr": "Infrastructure",      "en": "Infrastructure",      "pt": "Infraestrutura"},
    "Demand Points":   {"fr": "Points de demande",   "en": "Demand Points",       "pt": "Pontos de procura"},
    "Autres":          {"fr": "Autres",              "en": "Other",               "pt": "Outros"},
}


# =====================================================================
# LAYER DISPLAY NAMES — traductions des noms de couches
# =====================================================================

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
}
