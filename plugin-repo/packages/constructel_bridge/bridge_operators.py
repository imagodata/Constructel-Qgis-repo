"""Pure logic for the operator choice of the home screen (Bridge 1.9, plan
2026-11-12 task 1, spec § 6.2).

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

import re
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

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
