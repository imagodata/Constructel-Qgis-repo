"""Pure logic for the operator choice of the home screen (Bridge 1.9, plan
2026-11-12 task 1, spec § 6.2), and for the operator catalogue, the layer
keys and the project identity (task 2, spec § 6.3, § 6.4, § 7).

Side-effect-free: no qgis, no psycopg2, no file IO. bridge_plugin.py consumes
these functions; this module never imports it. Everything here is unit-tested
without a QGIS runtime (test_bridge19_operators.py), same pattern as
bridge_nominatif.py.

Server facts encoded here:
  * an operator is usable when ``ref.operateurs`` lists it as active, its
    schema is instantiated and the session may read it
    (``has_schema_privilege(schema, 'USAGE')``);
  * when ``public.current_gis_operator_codes(false)`` returns a non-empty
    array, only the intersection with those codes is kept; NULL (ADMIN /
    MANAGER), ``{}`` (rescue account) or a function the login cannot execute
    leave the "readable schema" filter alone.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

# LAYER_CATALOG keeps ``wyre`` as the template schema of the operator entries;
# later tasks substitute the chosen operator schema at load time.
OPERATOR_TEMPLATE_SCHEMA = "wyre"
# QgsSettings key: schema of the last operator loaded on this workstation.
LAST_OPERATOR_KEY = "constructel_bridge/last_operator"

# A schema name read from ref.operateurs ends up in SQL identifiers and in
# datasources: only plain lower-case identifiers are accepted.
SCHEMA_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


@dataclass(frozen=True)
class OperatorInfo:
    code: str
    label: str
    schema: str
    readable: bool = True


# Loading fallback when the operator list could not be read at all (1.8.4
# behaviour, controller decision T2-c4). A list read without any usable
# operator never falls back (spec § 6.2).
FALLBACK_OPERATOR = OperatorInfo("WYRE", "Wyre", OPERATOR_TEMPLATE_SCHEMA)


OPERATORS_QUERY = """\
SELECT o.code::text, o.label::text, o.schema_name::text,
       COALESCE(has_schema_privilege(to_regnamespace(o.schema_name)::oid, 'USAGE'), false)
  FROM ref.operateurs o
 WHERE o.active IS TRUE
   AND o.schema_name IS NOT NULL
   AND to_regnamespace(o.schema_name) IS NOT NULL
 ORDER BY o.code
"""

SCOPE_CODES_QUERY = "SELECT public.current_gis_operator_codes(false)::text[]"


def is_safe_schema(name) -> bool:
    """True for a plain lower-case identifier (``fullmatch``: a trailing
    newline would slip through ``$``)."""
    return isinstance(name, str) and SCHEMA_NAME_RE.fullmatch(name) is not None


def parse_operator_rows(rows: Iterable[Sequence]) -> list[OperatorInfo]:
    """OPERATORS_QUERY rows -> registry, query order kept. Rows whose schema
    is missing or not a safe identifier are dropped."""
    registry = []
    for code, label, schema, readable in rows:
        if not is_safe_schema(schema):
            continue
        registry.append(OperatorInfo(
            code=str(code),
            label=str(label) if label else str(code),
            schema=schema,
            readable=bool(readable),
        ))
    return registry


def usable_operators(registry: Sequence[OperatorInfo], scope_codes) -> list[OperatorInfo]:
    """Readable operators, intersected with *scope_codes* when that is a
    non-empty list (None / empty = no scope restriction)."""
    usable = [op for op in registry if op.readable]
    if scope_codes:
        codes = set(scope_codes)
        usable = [op for op in usable if op.code in codes]
    return usable


def preselect_operator(operators: Sequence[OperatorInfo], last_schema: str) -> Optional[OperatorInfo]:
    """The operator last loaded on this workstation if still usable, else
    the first one (``code`` order), else None."""
    for op in operators:
        if last_schema and op.schema == last_schema:
            return op
    return operators[0] if operators else None


# --- Operator catalogue (task 2, spec § 6.3) -----------------------------------
# Catalogue groups read in the schema of the chosen operator; every other
# working group is loaded once, in « Commun ». Literal copies of
# bridge_project_init.LAYER_CATALOG (this module never imports qgis), kept in
# step by test_bridge19_catalog.py.
OPERATOR_GROUPS = ("Demand Points", "Infrastructure", "Zones")
COMMON_GROUPS = ("Chantier", "OSIRIS", "Cadastre UrbIS", "Urbanisme")
COMMON_ROOT = "Commun"
OPERATOR_KEYS = frozenset({
    "demand_points", "structures", "cables", "subducts", "ducts", "trench_segments",
    "duct_progress", "zone_drop", "zone_distribution", "zone_pop", "zone_mro",
})
OPERATOR_TABLES = frozenset({
    "demand_points", "structures", "cables", "subducts", "ducts", "trench_segments",
    "v_duct_progress", "zone_drop", "zone_distribution", "zone_pop", "zone_mro",
})

# Custom properties of the layer tree groups created by the plugin (plan D17):
# schema on an operator root group, canonical name on any other group.
GROUP_SCHEMA_PROPERTY = "constructel_bridge/operator_schema"
GROUP_KIND_PROPERTY = "constructel_bridge/group"

_KEY_SEP = "@"


def layer_key(key: str, schema: str) -> str:
    """Key of a loaded layer (plan D2): ``"cables@orange"`` for an operator
    entry, the catalogue key unchanged for a common entry."""
    return f"{key}{_KEY_SEP}{schema}" if key in OPERATOR_KEYS else key


def base_key(layer_key: str) -> str:
    """Catalogue key of a loaded-layer key (``"cables@orange"`` -> ``"cables"``)."""
    return layer_key.split(_KEY_SEP, 1)[0]


def relation_id(rel_name: str, schema: str, primary_schema: str) -> str:
    """Relation id (plan D3): the historical id, cited by the QML relation
    editors, for the primary operator; ``f"{rel_name}__{schema}"`` otherwise."""
    return rel_name if schema == primary_schema else f"{rel_name}__{schema}"


# --- Project identity (plan D5) -------------------------------------------------

def parse_project_operators(raw) -> list[str]:
    """``bridge/operator`` -> schemas in load order: ``"wyre,orange"`` ->
    ``["wyre", "orange"]``, ``"wyre"`` (1.8) -> ``["wyre"]``. Blanks,
    duplicates and names that are not safe identifiers are dropped."""
    schemas = []
    for part in str(raw or "").split(","):
        name = part.strip()
        if is_safe_schema(name) and name not in schemas:
            schemas.append(name)
    return schemas


def format_project_operators(schemas: Iterable[str]) -> str:
    """Schemas -> ``"wyre,orange"`` (order kept, duplicates dropped)."""
    return ",".join(dict.fromkeys(s for s in schemas if s))


def parse_operator_labels(raw) -> dict[str, str]:
    """``bridge/operator_labels`` (JSON schema -> label) -> dict; anything
    unreadable gives ``{}`` (a 1.8 project has no such entry)."""
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def format_operator_labels(labels: Mapping[str, str]) -> str:
    return json.dumps(dict(labels), ensure_ascii=False, sort_keys=True)


def canonical_group(name: str, group_names: Mapping[str, Mapping[str, str]]) -> Optional[str]:
    """Canonical key of a group named *name* in *group_names*
    (``{canonical: {lang: translated}}``, i.e. ``GROUP_NAMES``): the key
    itself or any of its translations. None for a name it does not know."""
    for canonical, translations in group_names.items():
        if name == canonical or name in translations.values():
            return canonical
    return None


# --- Suffixe de l'operateur sur les noms de couches (task 3, spec § 6.4, § 9.5) ----
# « Cables · Wyre » : un seul operateur dans le projet -> suffixe facultatif
# (case decochee par defaut) ; au moins deux -> obligatoire. Les couches
# communes n'en recoivent jamais.
SUFFIX_SEP = " · "
# QgsSettings key: default of the "suffix" box of the home screen on this
# workstation (the project keeps its own choice in bridge/operator_suffix).
SUFFIX_SETTINGS_KEY = "constructel_bridge/operator_suffix"


def parse_suffix_flag(raw) -> bool:
    """``bridge/operator_suffix`` -> opted in: ``"1"`` / ``"true"`` (any case,
    surrounding blanks ignored) -> True; anything else, absent included,
    -> False."""
    return str(raw if raw is not None else "").strip().lower() in ("1", "true")


def suffix_applies(operators: Iterable[str], opted_in: bool) -> bool:
    """True when layer names carry the operator suffix: at least two distinct
    operators in the project (mandatory), or the option is ticked. Zero
    operator (common layers loaded alone) follows the option."""
    return bool(opted_in) or len(set(operators)) >= 2


def operator_layer_name(base: str, label: str) -> str:
    """``("Cables", "Wyre")`` -> ``"Cables · Wyre"``."""
    return f"{base}{SUFFIX_SEP}{label}"


def split_operator_suffix(name: str) -> tuple[str, Optional[str]]:
    """``"Zones POP · Orange"`` -> ``("Zones POP", "Orange")``; cut at the LAST
    separator. A name without separator (or with an empty side) is returned
    whole with ``None``."""
    base, sep, label = name.rpartition(SUFFIX_SEP)
    if sep and base and label:
        return base, label
    return name, None
