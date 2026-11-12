"""Doublures du plan Bridge 1.9 (tache 2 ; etendues par les taches 3, 4 et 6) :
arbre de couches, projet, couches et relations. Aucun QGIS requis.

Fideles a QGIS sur ce que le plugin utilise :
  * ``FakeGroup.findGroup`` et ``findLayer`` sont RECURSIFS, comme
    ``QgsLayerTreeGroup`` : un groupe homonyme plus bas dans l'arbre serait
    trouve (d'ou ``find_child_group`` pour les sous-groupes) ;
  * ``clone()`` est profond et garde les identifiants de couche ;
  * ``insertChildNode`` / ``addChildNode`` refusent un noeud qui a deja un
    parent (QGIS l'ignore en silence ; ici une erreur, pour ne rien masquer) ;
    un index hors bornes ajoute en fin, comme QGIS ;
  * ``readEntry`` rend ``(valeur, trouvee)`` ;
  * ``FakeRelationManager.relation(id)`` rend une relation d'identifiant vide
    quand elle n'existe pas, et ``addRelation`` ignore une relation invalide.

``install_fake_project(module, monkeypatch)`` branche un ``FakeProject`` neuf
dans le module vise (``QgsProject.instance()`` le rend) et y remplace les
classes de couches, de relation et de CRS ; les styles (base et embarques)
sont neutralises dans bridge_project_init.
"""
from __future__ import annotations

import itertools
import re
import sys

from constructel_bridge.bridge_operators import OperatorInfo

WYRE = OperatorInfo("WYRE", "Wyre", "wyre")
ORANGE = OperatorInfo("ORANGE", "Orange", "orange")

# Jetons key='v', key="schema"."table" ou key=v (meme forme que le stub
# QgsDataSourceUri) ; la colonne geometrique suit la table : table="s"."t" (geom).
_TOKEN_RE = re.compile(r"(\w+)=('([^']*)'|(\"[^\"]*\"(?:\.\"[^\"]*\")?)|(\S+))")
_GEOM_RE = re.compile(r"\btable=\S+\s+\((\w+)\)")
_layer_ids = itertools.count(1)


def _parse_source(source):
    params = {}
    for match in _TOKEN_RE.finditer(source or ""):
        value = match.group(3)
        if value is None:
            value = match.group(4)
        if value is None:
            value = match.group(5)
        params[match.group(1)] = value
    return params


class FakeUri:
    """Sous-ensemble de QgsDataSourceUri lu sur la source d'une couche."""

    def __init__(self, source):
        self._source = source
        self._params = _parse_source(source)

    def uri(self, *_args):
        return self._source

    def param(self, key):
        return self._params.get(key, "")

    def schema(self):
        table = self.param("table")
        return table.split('"."')[0].strip('"') if '"."' in table else ""

    def table(self):
        table = self.param("table")
        return table.split('"."')[1].strip('"') if '"."' in table else table.strip('"')

    def geometryColumn(self):
        match = _GEOM_RE.search(self._source)
        return match.group(1) if match else self.param("geom")


class _FakeProvider:
    def __init__(self, layer):
        self._layer = layer

    def name(self):
        return self._layer.providerType()

    def uri(self):
        return FakeUri(self._layer.source())

    def dataSourceUri(self, *_args):
        return self._layer.source()


class _Properties:
    """customProperty / setCustomProperty / removeCustomProperty."""

    def _props(self):
        return self.__dict__.setdefault("_properties", {})

    def customProperty(self, key, default=None):
        return self._props().get(key, default)

    def setCustomProperty(self, key, value):
        self._props()[key] = value

    def removeCustomProperty(self, key):
        self._props().pop(key, None)


class FakeEditorWidgetSetup:
    """QgsEditorWidgetSetup(type, config)."""

    def __init__(self, widget_type="", config=None):
        self._type = widget_type
        self._config = dict(config or {})

    def type(self):
        return self._type

    def config(self):
        return dict(self._config)


class _FakeField:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _FakeFields:
    def __init__(self, names):
        self._names = list(names)

    def count(self):
        return len(self._names)

    def at(self, index):
        return _FakeField(self._names[index])

    def indexOf(self, name):
        return self._names.index(name) if name in self._names else -1


class FakeLayer(_Properties):
    """Couche vectorielle construite comme ``QgsVectorLayer(source, name,
    provider)`` : PostgreSQL (``"postgres"``) ou WFS (``"WFS"``).
    L'identifiant est fixe a la creation (un renommage ne le change pas)."""

    def __init__(self, source="", name="", provider="postgres"):
        self._source = source
        self._name = name
        self._provider_name = provider
        self._id = f"{name or 'layer'}_{next(_layer_ids)}"
        self.valid = True
        self._field_names = []
        self._setups = {}
        self._map_tip = ""
        self._display_expression = ""
        self._read_only = False
        self.loaded_styles = []    # chemins passes a loadNamedStyle
        self.imported_styles = []  # documents passes a importNamedStyle
        self.repaints = 0

    @classmethod
    def pg(cls, schema, table, name=None, *, key="id", geom="geom", fields=()):
        """Couche PostgreSQL de ``schema.table``, cle primaire *key*,
        colonne geometrique *geom* (None : table sans geometrie), nommee
        *name* (par defaut la table, comme init_project), champs *fields*.
        Source au format QGIS : ``... key='id' ... table="s"."t" (geom)``."""
        table_part = f'table="{schema}"."{table}"' + (f" ({geom})" if geom else "")
        source = (f"dbname='farois_ftth' host=test-host.invalid port=5432 sslmode=verify-full "
                  f"key='{key}' checkPrimaryKeyUnicity='0' {table_part}")
        layer = cls(source, table if name is None else name, "postgres")
        layer._field_names = list(fields)
        return layer

    # -- identite -----------------------------------------------------------
    def id(self):
        return self._id

    def name(self):
        return self._name

    def setName(self, name):
        self._name = name

    def source(self):
        return self._source

    def providerType(self):
        return self._provider_name

    def isValid(self):
        return self.valid

    def dataProvider(self):
        return _FakeProvider(self) if self.valid else None

    # -- formulaire -----------------------------------------------------------
    def fields(self):
        return _FakeFields(self._field_names)

    def editorWidgetSetup(self, index):
        return self._setups.get(index, FakeEditorWidgetSetup("TextEdit", {}))

    def setEditorWidgetSetup(self, index, setup):
        self._setups[index] = setup

    def mapTipTemplate(self):
        return self._map_tip

    def setMapTipTemplate(self, template):
        self._map_tip = template

    def displayExpression(self):
        return self._display_expression

    def setDisplayExpression(self, expression):
        self._display_expression = expression

    # -- edition et styles ------------------------------------------------------
    def isReadOnly(self):
        return self._read_only

    def setReadOnly(self, read_only=True):
        self._read_only = bool(read_only)
        return True

    def loadNamedStyle(self, path, *_args):
        self.loaded_styles.append(path)
        return "", True

    def importNamedStyle(self, doc, *_args):
        self.imported_styles.append(doc)
        return True, ""

    def triggerRepaint(self, *_args):
        self.repaints += 1

    def __repr__(self):
        return f"FakeLayer({self._name!r}, {self._id!r})"


class FakeRasterLayer:
    """``QgsRasterLayer(source, name, provider)`` (fonds de plan)."""

    def __init__(self, source="", name="", provider="wms"):
        self._source = source
        self._name = name
        self._provider_name = provider
        self._id = f"{name or 'raster'}_{next(_layer_ids)}"
        self.valid = True

    def id(self):
        return self._id

    def name(self):
        return self._name

    def source(self):
        return self._source

    def providerType(self):
        return self._provider_name

    def isValid(self):
        return self.valid


class _Node(_Properties):
    def __init__(self):
        self._parent = None
        self._expanded = True
        self._visible = True

    def parent(self):
        return self._parent

    def setExpanded(self, expanded):
        self._expanded = bool(expanded)

    def isExpanded(self):
        return self._expanded

    def setItemVisibilityChecked(self, checked):
        self._visible = bool(checked)

    def itemVisibilityChecked(self):
        return self._visible

    def _copy_state(self, clone):
        clone._expanded, clone._visible = self._expanded, self._visible
        clone._properties = dict(self._props())
        return clone


class FakeLayerNode(_Node):
    """Noeud de couche (QgsLayerTreeLayer) : nom = nom de la couche."""

    def __init__(self, layer):
        super().__init__()
        self._layer = layer

    def layerId(self):
        return self._layer.id()

    def layer(self):
        return self._layer

    def name(self):
        return self._layer.name()

    def clone(self):
        return self._copy_state(FakeLayerNode(self._layer))

    def __repr__(self):
        return f"FakeLayerNode({self.name()!r})"


class FakeGroup(_Node):
    """Groupe de l'arbre de couches (QgsLayerTreeGroup ; la racine est un
    groupe sans nom)."""

    def __init__(self, name=""):
        super().__init__()
        self._name = name
        self._children = []

    def name(self):
        return self._name

    def setName(self, name):
        self._name = name

    def children(self):
        return list(self._children)

    # -- insertion / retrait ------------------------------------------------------
    def insertChildNode(self, index, node):
        if node._parent is not None:
            raise ValueError(f"{node!r} a deja un parent : QGIS ne l'insere pas")
        if index < 0 or index > len(self._children):
            index = len(self._children)
        node._parent = self
        self._children.insert(index, node)

    def addChildNode(self, node):
        self.insertChildNode(len(self._children), node)

    def removeChildNode(self, node):
        self._children.remove(node)
        node._parent = None

    def insertGroup(self, index, name):
        group = FakeGroup(name)
        self.insertChildNode(index, group)
        return group

    def addGroup(self, name):
        return self.insertGroup(len(self._children), name)

    def insertLayer(self, index, layer):
        node = FakeLayerNode(layer)
        self.insertChildNode(index, node)
        return node

    def addLayer(self, layer):
        return self.insertLayer(len(self._children), layer)

    # -- recherche (recursive, comme QGIS) ------------------------------------
    def findGroup(self, name):
        for child in self._children:
            if isinstance(child, FakeGroup):
                if child.name() == name:
                    return child
                found = child.findGroup(name)
                if found is not None:
                    return found
        return None

    def findLayer(self, layer_or_id):
        layer_id = layer_or_id if isinstance(layer_or_id, str) else layer_or_id.id()
        for child in self._children:
            if isinstance(child, FakeLayerNode):
                if child.layerId() == layer_id:
                    return child
            else:
                found = child.findLayer(layer_id)
                if found is not None:
                    return found
        return None

    def clone(self):
        clone = self._copy_state(FakeGroup(self._name))
        for child in self._children:
            clone.addChildNode(child.clone())
        return clone

    def __repr__(self):
        return f"FakeGroup({self._name!r})"


class FakeRelation:
    """QgsRelation : valide quand identifiant, deux couches et une paire de
    champs sont poses."""

    def __init__(self):
        self._id = ""
        self._name = ""
        self._referencing = ""
        self._referenced = ""
        self._pairs = {}

    def setId(self, rel_id):
        self._id = rel_id

    def id(self):
        return self._id

    def setName(self, name):
        self._name = name

    def name(self):
        return self._name

    def setReferencingLayer(self, layer_id):
        self._referencing = layer_id

    def referencingLayerId(self):
        return self._referencing

    def setReferencedLayer(self, layer_id):
        self._referenced = layer_id

    def referencedLayerId(self):
        return self._referenced

    def addFieldPair(self, referencing_field, referenced_field):
        self._pairs[referencing_field] = referenced_field

    def fieldPairs(self):
        return dict(self._pairs)

    def isValid(self):
        return bool(self._id and self._referencing and self._referenced and self._pairs)


class FakeRelationManager:
    def __init__(self):
        self._relations = {}

    def relations(self):
        return dict(self._relations)

    def relation(self, rel_id):
        return self._relations.get(rel_id) or FakeRelation()

    def addRelation(self, relation):
        if relation.isValid():
            self._relations[relation.id()] = relation

    def removeRelation(self, relation):
        rel_id = relation if isinstance(relation, str) else relation.id()
        self._relations.pop(rel_id, None)


class FakeCrs:
    """QgsCoordinateReferenceSystem("EPSG:31370")."""

    def __init__(self, definition=""):
        self._definition = definition

    def authid(self):
        return self._definition


def _pg_identity(layer):
    """(schema, table) d'une couche PostgreSQL, sinon None."""
    if not isinstance(layer, FakeLayer) or layer.providerType() != "postgres":
        return None
    uri = FakeUri(layer.source())
    return uri.schema(), uri.table()


class FakeProject:
    """QgsProject : couches, arbre, relations, entrees et variables.
    ``events`` enregistre ``("add", id_couche)`` et ``("entry", cle)``."""

    def __init__(self):
        self._layers = {}
        self._root = FakeGroup("")
        self._relations = FakeRelationManager()
        self._entries = {}
        self._variables = {}
        self._crs = None
        self.events = []

    # -- couches --------------------------------------------------------------
    def addMapLayer(self, layer, add_to_legend=True):
        self._layers[layer.id()] = layer
        self.events.append(("add", layer.id()))
        if add_to_legend:
            self._root.addLayer(layer)
        return layer

    def mapLayers(self):
        return dict(self._layers)

    def mapLayer(self, layer_id):
        return self._layers.get(layer_id)

    def mapLayersByName(self, name):
        return [ly for ly in self._layers.values() if ly.name() == name]

    def layerTreeRoot(self):
        return self._root

    def relationManager(self):
        return self._relations

    # -- identite du projet -----------------------------------------------------
    def readEntry(self, scope, key, default=""):
        if (scope, key) in self._entries:
            return self._entries[(scope, key)], True
        return default, False

    def writeEntry(self, scope, key, value):
        self._entries[(scope, key)] = str(value)
        self.events.append(("entry", key))
        return True

    def customVariables(self):
        return dict(self._variables)

    def setCustomVariables(self, variables):
        self._variables = dict(variables)

    # -- divers -----------------------------------------------------------------
    def setCrs(self, crs):
        self._crs = crs

    def crs(self):
        return self._crs

    # -- aides de test ------------------------------------------------------------
    def add_pg(self, schema, table, name=None, *, group=None, key="id", geom="geom"):
        """Ajoute une couche PostgreSQL au projet, dans *group* (par defaut la
        racine de l'arbre)."""
        layer = FakeLayer.pg(schema, table, name, key=key, geom=geom)
        self.addMapLayer(layer, False)
        (group or self._root).addLayer(layer)
        return layer

    def pg_layers(self, schema, table):
        return [ly for ly in self._layers.values() if _pg_identity(ly) == (schema, table)]

    def layer(self, schema, table):
        layers = self.pg_layers(schema, table)
        return layers[0] if layers else None

    def count_pg(self, schema, table):
        return len(self.pg_layers(schema, table))

    def schema_of(self, layer_id):
        identity = _pg_identity(self._layers.get(layer_id))
        return identity[0] if identity else None


def _set_project_variable(project, name, value):
    # Comme QgsExpressionContextUtils.setProjectVariable : fusion dans
    # customVariables() du projet vise.
    variables = project.customVariables()
    variables[name] = value
    project.setCustomVariables(variables)


def install_fake_project(module, monkeypatch) -> FakeProject:
    """Branche un FakeProject neuf dans *module* et le rend. Remplace, quand
    le module les a : QgsVectorLayer, QgsRasterLayer, QgsRelation,
    QgsCoordinateReferenceSystem, _apply_styles_from_db (-> set()) et
    _apply_embedded_styles (-> rien). QgsExpressionContextUtils.setProjectVariable
    du stub qgis.core ecrit dans les variables du projet passe."""
    project = FakeProject()
    monkeypatch.setattr(module, "QgsProject",
                        type("QgsProject", (), {"instance": staticmethod(lambda: project)}))
    optional = {
        "QgsVectorLayer": FakeLayer,
        "QgsRasterLayer": FakeRasterLayer,
        "QgsRelation": FakeRelation,
        "QgsCoordinateReferenceSystem": FakeCrs,
        "_apply_styles_from_db": lambda *_args, **_kwargs: set(),
        "_apply_embedded_styles": lambda *_args, **_kwargs: None,
    }
    for name, value in optional.items():
        if hasattr(module, name):
            monkeypatch.setattr(module, name, value)
    utils = getattr(sys.modules.get("qgis.core"), "QgsExpressionContextUtils", None)
    if utils is not None:
        monkeypatch.setattr(utils, "setProjectVariable", staticmethod(_set_project_variable))
    return project
