# -*- coding: utf-8 -*-
"""Fonctions d'expression QGIS enregistrees par Constructel Bridge.

Expose des fonctions reutilisables dans les expressions QGIS (FilterExpression
ValueRelation, virtual fields, etc.) pour des besoins metier Wyre qui ne sont
pas couverts par le moteur natif.

Fonctions exposees:
  - wyre_selected_common(schema_table, field_name) : valeur commune d'un champ
    pour les features selectionnes d'une couche identifiee par son
    'schema.table' PostgreSQL. Retourne NULL si mixte ou aucune selection.
"""

from qgis.core import QgsExpression, QgsProject, qgsfunction


WYRE_GROUP = "Wyre"


@qgsfunction(args="auto", group=WYRE_GROUP, usesGeometry=False, referencedColumns=[])
def wyre_selected_common(schema_table, field_name, feature, parent):
    """Retourne la valeur commune d'un champ pour les features selectionnes.

    Identifie la couche par son nom 'schema.table' PostgreSQL (insensible au
    renommage du layer dans le projet QGIS).

    Retourne:
      - la valeur unique si tous les features selectionnes partagent la meme
      - NULL si valeurs mixtes, aucune selection, ou couche introuvable

    Usage typique (FilterExpression ValueRelation en multi-edit):
      "sub_type" = wyre_selected_common('infra.structures', 'structure_type')
    """
    try:
        schema, table = schema_table.split(".", 1)
    except ValueError:
        return None

    needle = f'table="{schema}"."{table}"'
    target = next(
        (l for l in QgsProject.instance().mapLayers().values() if needle in l.source()),
        None,
    )
    if target is None:
        return None

    selected = target.selectedFeatures()
    if not selected:
        return None

    values = set()
    for f in selected:
        values.add(f[field_name])
        if len(values) > 1:
            return None

    return values.pop() if values else None


_REGISTERED = [wyre_selected_common]


def register_expressions():
    """Enregistre les fonctions d'expression Wyre aupres de QGIS."""
    for fn in _REGISTERED:
        if not QgsExpression.isFunctionName(fn.name()):
            QgsExpression.registerFunction(fn)


def unregister_expressions():
    """Desenregistre les fonctions Wyre (appele lors du unload du plugin)."""
    for fn in _REGISTERED:
        if QgsExpression.isFunctionName(fn.name()):
            QgsExpression.unregisterFunction(fn.name())
