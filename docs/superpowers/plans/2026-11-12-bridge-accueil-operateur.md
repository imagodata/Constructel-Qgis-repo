# Constructel Bridge 1.9.0 — écran d'accueil, choix d'opérateur et outils hors connexion : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** le clic principal du bouton Constructel Bridge ouvre un écran d'accueil utilisable connecté ou non, qui charge les couches d'un opérateur des scopes de la session (puis d'un deuxième), range chaque opérateur dans son groupe et le reste dans « Commun », et offre check-in, diagnostic et langue hors connexion.

**Architecture:** la logique sans QGIS va dans des modules purs testés sans runtime (`bridge_operators.py`, `bridge_home_model.py`, `bridge_diagnostic.py`, même patron que `bridge_nominatif.py`). `LAYER_CATALOG` garde `wyre` comme schéma modèle des entrées opérateur ; `catalog_for(schema)` le substitue au chargement et les couches chargées sont indexées par `cle@schema`. Tout ciblage « même opérateur » (relations, ValueRelation, `get_feature`, styles, verrou) passe par le **schéma de la source et l'identifiant de couche**, jamais par un nom affiché : avec un seul opérateur, les noms peuvent rester sans suffixe.

**Tech Stack:** PyQGIS 3.28 → 4.x (Qt5/Qt6), Python 3.9, psycopg2, pytest sur stubs (`uvx pytest`).

**Spec:** `docs/superpowers/specs/2026-11-12-bridge-accueil-operateur-design.md` (version avec « suffixe optionnel avec un seul opérateur », § 6.4, § 6.5, § 9.5) et la maquette `docs/superpowers/specs/2026-11-12-bridge-accueil-operateur-maquette.html` (version 3).

Conventions de ce plan : `P` = `plugin-repo/packages/constructel_bridge`, `T` = `plugin-repo/packages/constructel_bridge_tests`. Toutes les commandes se lancent à la racine du worktree (`~/projects/qgis_repo/.worktrees/feat-bridge-accueil-operateur`) après `export PATH="$HOME/.local/bin:$PATH"`.

## Global Constraints

- QGIS **3.28 minimum (Python 3.9)** jusqu'à 4.99, Qt5 **et** Qt6 : enums qualifiés comme le code actuel (`Qgis.MessageLevel.Warning`, `QDialog.DialogCode.Accepted`, `Qt.CheckState.Checked`, `Qt.ItemFlag.ItemIsUserCheckable`), `exec()` jamais `exec_()`.
- Python 3.9 : tout module créé ou modifié commence par `from __future__ import annotations` ; ni `match`, ni annotation `X | Y` évaluée à l'exécution, ni API 3.10+. Garde AST posée en tâche 1.
- Tous les textes visibles en **FR / EN / PT** dans `P/i18n/translations.py` (mêmes clés, mêmes `{variables}`), appelés par clé littérale `tr("...")` (relevée par `T/test_bridge18_i18n.py`). Chaque tâche ajoute ses clés dans son propre commit. Les noms de groupes traduits vont dans `P/i18n/layer_translations.py::GROUP_NAMES`.
- **Aucune modification côté serveur Farois** (SQL, API) : le plugin lit `ref.operateurs`, `public.current_gis_operator_codes(false)`, `has_schema_privilege`, `public.layer_styles` et les tables du catalogue. Un manque se signale, il ne se corrige pas ici.
- **Pas de release** : `release.py`, `plugin-repo/plugins.xml` et le zip ne sont pas touchés (geste séparé soumis à Simon). Seul `P/metadata.txt` change (version 1.9.0 et changelog, tâche 10).
- Suite verte à chaque commit : `uvx pytest -q` → 538 verts au départ, puis 538 + nouveaux, **0 échec**. Les assertions des tests existants ne changent pas ; seules leurs doublures peuvent gagner des méthodes (indiqué dans la tâche concernée).
- L'écran s'ouvre **au clic seulement**. Hors connexion, rien ne tente la base. Tout appel réseau du Diagnostic a un délai ≤ 3 s et tourne hors du fil de l'interface.
- Un opérateur hors des scopes n'apparaît **jamais** dans le sélecteur, même grisé ou barré.
- Le Diagnostic n'ouvre aucune session PostgreSQL (pas de bind AD) et ne lit aucun secret de l'Auth Manager (pas d'invite du mot de passe maître).
- Ciblage « même opérateur » par **schéma de la source et identifiant de couche**, jamais par nom affiché (suffixe optionnel avec un seul opérateur).
- Commits sur `feat/bridge-accueil-operateur`, messages `feat(bridge): … (1.9.0)`, terminés par la ligne d'attribution en vigueur ; pas de push.

## Review Focus

1. **Projet 1.8 enregistré en FR ou en PT** (« Points de demande », « Infraestrutura », « Zonas ») : la réorganisation reconnaît les noms traduits et ne crée aucun groupe en double. Test : tâche 6, `test_reorganizes_18_project_in_french` et `test_reorganize_portuguese_names`.
2. **Deuxième clic « Ajouter », ou projet déjà réorganisé rouvert** : aucun « Wyre » dans « Wyre », pas de second « Commun », pas de double suffixe « Câbles · Wyre · Wyre ». Test : tâche 6, `test_reorganize_is_idempotent` ; tâche 3, `test_suffix_is_never_doubled`.
3. **Changement de langue, y compris hors connexion, sur un projet à deux opérateurs** : le suffixe suit la langue et les ValueRelation / `get_feature` visent toujours le bon opérateur. Test : tâche 3, `test_offline_language_switch_keeps_suffix` ; tâche 4, `test_language_switch_keeps_own_operator_targets`.
4. **Projet contenant un opérateur hors des scopes de la session** (projet partagé) : jamais proposé dans le sélecteur, ses couches ne sont jamais réorientées vers un autre opérateur, le résumé le nomme quand même. Test : tâche 4, `test_no_cross_operator_fallback` ; tâche 9, `test_operator_outside_scopes_is_summarized_not_selectable`.
5. **Serveur qui accepte la connexion TCP sans jamais répondre** (filtrage, service figé) : le Diagnostic rend une erreur dans le délai court, sans bloquer QGIS. Test : tâche 8, `test_probe_server_silent_server_times_out`.

## Décisions prises dans ce plan (là où la spec laisse le choix)

- **D1 Catalogue** : `LAYER_CATALOG` est inchangé ; `wyre` y reste le schéma modèle des entrées opérateur (`OPERATOR_TEMPLATE_SCHEMA`). Les tests 1.7/1.8 qui vérifient `entry[1:6]` restent valides.
- **D2 Clés** : clé de couche chargée = `"cables@orange"` pour une entrée opérateur, clé simple pour une entrée commune (`layer_key`, `base_key`).
- **D3 Relations** : l'opérateur principal (premier de l'identité du projet, donc le premier chargé) garde les identifiants historiques (`zone_pop_to_mro`…), que les éditeurs de relations des QML citent ; les autres reçoivent `zone_pop_to_mro__orange`. Limite connue : dans un formulaire du deuxième opérateur, les éditeurs « câbles depuis/vers cette structure » listent les câbles du principal (liste vide). Les relations Documents restent justes (couche enfant commune, filtre par identifiant).
- **D4 Ciblage** : ValueRelation → clés `Layer` (identifiant), `LayerName` (nom courant de la couche du même schéma), `LayerSource` (schéma réécrit) ; premier argument de `get_feature` → identifiant de couche. Appliqué au `Value` des ValueRelation, aux infobulles (`mapTipTemplate`) et aux expressions d'affichage (`displayExpression`). La couche cible est cherchée par `(schéma de la source, table)`, jamais par nom.
- **D5 Identité du projet** : `bridge/operator` et `@bridge_operator` deviennent la liste des schémas dans l'ordre de chargement (`"wyre,orange"`) ; `"wyre"` (1.8) se relit `["wyre"]`. Nouvelles entrées : `bridge/operator_labels` (JSON schéma → libellé) et `bridge/operator_suffix` (`"1"`/`"0"`).
- **D6 Suffixe** (§ 6.4, § 9.5) : le suffixe s'applique si le projet a au moins deux opérateurs, ou si `bridge/operator_suffix` vaut `"1"`. Case de la tuile décochée par défaut, dernier choix mémorisé dans `QgsSettings` (`constructel_bridge/operator_suffix`). Un projet 1.8 ouvert n'a pas d'entrée `operator_labels` : aucun renommage à l'ouverture (§ 6.5).
- **D7 Registre** : une seule requête renvoie tous les opérateurs actifs instanciés avec un booléen `readable`. Utilisables = lisibles ∩ codes de scope (si non vide). Les autres ne servent qu'aux libellés (réorganisation d'un groupe `wyre` chez un utilisateur sans Wyre) et au verrou ; ils ne sont jamais affichés dans le sélecteur.
- **D8 SQL** : `has_schema_privilege(to_regnamespace(o.schema_name)::oid, 'USAGE')` (version oid : `NULL` au lieu d'une erreur si le schéma disparaît, aucune dépendance à l'ordre d'évaluation du `WHERE`).
- **D9 Verrou** : schémas verrouillables = `{"wyre"}` ∪ schémas du registre.
- **D10 Périmètre** : noms des MRO/POP résolus dans chaque schéma utilisable, fusionnés. L'en-tête vaut `login · _scope_text()` ; le « Wyre : 10 MRO » de la maquette est lu comme illustratif (pas de ventilation par opérateur).
- **D11 Écran** : l'écran se ferme après un chargement réussi (comme le dialogue actuel) et rouvre en mode ajout ; « Projet enregistré » ferme l'écran avant de charger. Check-in, Diagnostic, Langue et Se connecter le laissent ouvert et le redessinent. Le résumé « Déjà dans le projet » ne nomme pas le modèle utilisé (non mémorisé) : `✓ Wyre · 14 couches · 3 fonds de plan`.
- **D12 Fonds de plan déjà chargés grisés** : le mécanisme « déjà chargée » est étendu aux fonds de plan (même règle de nom que `_add_basemaps`).
- **D13 Diagnostic** : version lue par `urllib` (3 s) sur `http://192.168.160.31:9080/plugin-repo/plugins.xml` (surchargeable par `CONSTRUCTEL_PLUGIN_REPO_URL`) dans une `QgsTask` ; serveur = TCP + `SSLRequest` PostgreSQL + poignée de main TLS vérifiée (CA `certs/root-ca-bundle.pem`, nom d'hôte vérifié), sans login ; état des extensions lu dans le cache de l'installeur QGIS, sans téléchargement ; action « mise à jour du plugin » = gestionnaire d'extensions de QGIS.
- **D14 Check-in hors connexion** : la page Profil n'est pas affichée ; le résumé dit « Profil : disponible une fois connecté ».
- **D15 Menu** : « Initialiser projet » ouvre l'accueil (libellé « Accueil · charger les couches ») ; « Statut connexion » ouvre le Diagnostic (libellé « Statut et diagnostic »).
- **D16 Python 3.9** : `bridge_plugin.py`, `bridge_project_init.py` et `bridge_sketcher.py` utilisent déjà `X | None` sans `from __future__ import annotations` (TypeError à l'import sous un vrai 3.9) : l'import est ajouté et une garde AST l'impose.
- **D17 Groupes** : un groupe créé par le plugin porte une propriété personnalisée (schéma pour le groupe d'opérateur, nom canonique pour les autres) ; la recherche d'un sous-groupe accepte cette propriété ou n'importe quelle traduction de `GROUP_NAMES` (pas de doublon après un changement de langue). `apply_group_names` traduit aussi les enfants des groupes opérateur et de « Commun ».

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| Create `P/bridge_operators.py` | Pur : registre et filtre des opérateurs, constantes du catalogue opérateur, clés `cle@schema`, identité du projet, règle du suffixe, noms suffixés, sources de style, réécriture `get_feature` / `LayerSource`. |
| Create `P/bridge_home_model.py` | Pur : `HomeSnapshot`, `HomeState`, `HomeActions`, `home_state()`, `suffix_state()`. |
| Create `P/bridge_home.py` | Qt : `HomeDialog` (en-tête, grande tuile, tuiles secondaires). |
| Create `P/bridge_diagnostic.py` | Pur : vérifications, sonde serveur, lecture de `plugins.xml`. |
| Create `P/bridge_diagnostic_dialog.py` | Qt : `DiagnosticDialog`, `QgsTask` des vérifications réseau. |
| Modify `P/bridge_project_init.py` | `catalog_for`, détection par opérateur, groupes opérateur / Commun, `init_project(operator=…)`, relations par opérateur, identité, réorganisation, comptages, `LayerSelectionWidget` (remplace `InitProjectDialog`). |
| Modify `P/bridge_sketcher.py` | Suffixe, traduction des groupes imbriqués, `retarget_operator_references`. |
| Modify `P/bridge_nominatif.py` | `should_lock_layer(..., operator_schemas)`. |
| Modify `P/bridge_onboarding.py` | `include_profile`, `install_or_activate_plugin`. |
| Modify `P/bridge_plugin.py` | Chargement des opérateurs, `_load_operator_layers`, verrou et périmètre multi-schémas, accueil, diagnostic, check-in hors connexion. |
| Modify `P/i18n/translations.py`, `P/i18n/layer_translations.py` | Clés FR/EN/PT, `GROUP_NAMES["Commun"]`. |
| Modify `P/metadata.txt` | 1.9.0, changelog. |
| Create `T/fakes19.py` | Doublures d'arbre de couches, de projet, de couches et de relations. |
| Create `T/test_bridge19_*.py` | Tests de chaque tâche. |
| Modify `T/stubs/qgis/core.py` | `QgsProject.readEntry/writeEntry/customVariables`. |
| Modify `T/test_bridge18_connect.py`, `T/test_bridge_vr_layername_sync.py` | Doublures enrichies, assertions inchangées. |

---

### Task 1: Opérateurs utilisables par la session (§ 6.2)

**Files:**
- Create: `P/bridge_operators.py`
- Modify: `P/bridge_plugin.py` (`__init__` vers la ligne 900 ; `_connect` vers la ligne 2124, juste après `_register_bridge_user`, dans les deux modes ; nouvelle méthode `_load_operators`)
- Modify: `P/bridge_plugin.py`, `P/bridge_project_init.py`, `P/bridge_sketcher.py` : `from __future__ import annotations` en tête (D16)
- Modify: `T/test_bridge18_connect.py:114-155` (`_FakeCursor` : paramètres `operator_rows=(("WYRE", "Wyre", "wyre", True),)` et `operator_codes=None` ; une valeur `Exception` est levée par `execute`)
- Create: `T/test_bridge19_operators.py`, `T/test_bridge19_py39.py`

**Interfaces:**
- Produces (`bridge_operators.py`) :
  ```python
  OPERATOR_TEMPLATE_SCHEMA = "wyre"
  LAST_OPERATOR_KEY = "constructel_bridge/last_operator"
  SCHEMA_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
  @dataclass(frozen=True)
  class OperatorInfo:
      code: str
      label: str
      schema: str
      readable: bool = True
  OPERATORS_QUERY: str
  SCOPE_CODES_QUERY = "SELECT public.current_gis_operator_codes(false)::text[]"
  def is_safe_schema(name) -> bool
  def parse_operator_rows(rows) -> list[OperatorInfo]
  def usable_operators(registry: Sequence[OperatorInfo], scope_codes) -> list[OperatorInfo]
  def preselect_operator(operators: Sequence[OperatorInfo], last_schema: str) -> OperatorInfo | None
  ```
- Produces (`ConstructelBridgePlugin`) : `self._operators: list[OperatorInfo]` (utilisables, ordre `code`), `self._operator_registry: dict[str, OperatorInfo]` (schéma → opérateur, tous les actifs instanciés), `def _load_operators(self) -> None`.

`OPERATORS_QUERY` (texte exact) :
```sql
SELECT o.code::text, o.label::text, o.schema_name::text,
       COALESCE(has_schema_privilege(to_regnamespace(o.schema_name)::oid, 'USAGE'), false)
  FROM ref.operateurs o
 WHERE o.active IS TRUE
   AND o.schema_name IS NOT NULL
   AND to_regnamespace(o.schema_name) IS NOT NULL
 ORDER BY o.code
```

- [ ] **Step 1: Écrire les tests en échec** (`T/test_bridge19_operators.py`)

```python
ROWS = [("ORANGE", "Orange", "orange", True), ("PROXIMUS", "Proximus", "proximus", False),
        ("WYRE", "Wyre", "wyre", True)]

def test_parse_operator_rows_keeps_order_and_readability():
    reg = bo.parse_operator_rows(ROWS)
    assert [o.schema for o in reg] == ["orange", "proximus", "wyre"]
    assert reg[1] == bo.OperatorInfo("PROXIMUS", "Proximus", "proximus", False)

def test_parse_operator_rows_drops_unsafe_or_missing_schema():
    assert bo.parse_operator_rows([("X", "X", 'x"; drop', True), ("Y", "Y", None, True)]) == []

@pytest.mark.parametrize("codes", [None, []])
def test_without_scope_codes_only_readable_schemas(codes):
    assert [o.schema for o in bo.usable_operators(bo.parse_operator_rows(ROWS), codes)] == ["orange", "wyre"]

def test_scope_codes_intersect_readable():
    assert [o.schema for o in bo.usable_operators(bo.parse_operator_rows(ROWS), ["WYRE", "PROXIMUS"])] == ["wyre"]

def test_preselect_last_operator_else_first():
    ops = bo.usable_operators(bo.parse_operator_rows(ROWS), None)
    assert bo.preselect_operator(ops, "wyre").schema == "wyre"
    assert bo.preselect_operator(ops, "proximus").schema == "orange"
    assert bo.preselect_operator(ops, "").schema == "orange"
    assert bo.preselect_operator([], "wyre") is None

def test_operators_query_is_guarded():
    q = bo.OPERATORS_QUERY
    assert "o.active IS TRUE" in q and "to_regnamespace(o.schema_name) IS NOT NULL" in q
    assert "has_schema_privilege(to_regnamespace(o.schema_name)::oid, 'USAGE')" in q
    assert q.rstrip().endswith("ORDER BY o.code")
```
Côté plugin, avec `_make_plugin`, `_FakeCursor`, `_PgErr`, `_logs` importés de `test_bridge18_connect` :
```python
def test_connect_loads_usable_operators(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(operator_rows=ROWS, operator_codes=["WYRE"])
    plugin, *_ = _make_plugin(bp18, monkeypatch, tmp_path, [None], cursor=cur, stored_ad_pw="ad-pw")
    plugin._auto_connect()
    assert [o.schema for o in plugin._operators] == ["wyre"]
    assert set(plugin._operator_registry) == {"orange", "proximus", "wyre"}

def test_scope_codes_not_executable_falls_back_to_readable(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(operator_rows=ROWS, operator_codes=_PgErr("permission denied for function current_gis_operator_codes"))
    # … _auto_connect()
    assert [o.schema for o in plugin._operators] == ["orange", "wyre"]

def test_operators_query_failure_never_blocks_connection(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(operator_rows=_PgErr("permission denied for table operateurs"))
    # … _auto_connect()
    assert plugin._connected is True and plugin._operators == [] and plugin._operator_registry == {}
    assert any("Liste des operateurs indisponible" in m for m in _logs(Qgis.MessageLevel.Warning))
```
`T/test_bridge19_py39.py` :
```python
def test_pep604_annotations_need_future_import():
    # pour chaque P/*.py et P/i18n/*.py sans `from __future__ import annotations` :
    # aucune annotation (arguments, retour, AnnAssign) ne contient un ast.BinOp(op=ast.BitOr)
    assert offenders == {}
```

- [ ] **Step 2: Lancer les tests, constater l'échec**

Run: `uvx pytest -q T/test_bridge19_operators.py T/test_bridge19_py39.py`
Expected: FAIL (`ModuleNotFoundError: constructel_bridge.bridge_operators`, et la garde cite `bridge_plugin.py`, `bridge_project_init.py`, `bridge_sketcher.py`).

- [ ] **Step 3: Implémenter**

`bridge_operators.py` sans aucun import qgis ni psycopg2. `parse_operator_rows` écarte les lignes dont le schéma échoue à `is_safe_schema`. `usable_operators` : `readable` d'abord, puis intersection si `scope_codes` est une liste non vide. `_load_operators` : curseur de `self._conn`, `OPERATORS_QUERY` puis `SCOPE_CODES_QUERY` dans deux `try` séparés (connexion en autocommit) ; `fetchone()` qui rend `None` ou une exception sur la seconde requête = codes indisponibles (`None`). Un échec de la première requête laisse les deux attributs vides et journalise « Liste des operateurs indisponible : {exc} » (jamais le mot « illisible », filtré par un test 1.8.4). Jamais d'exception vers `_connect`. Ajouter `from __future__ import annotations` en tête des trois modules.

- [ ] **Step 4: Lancer les tests et la suite**

Run: `uvx pytest -q T/test_bridge19_operators.py T/test_bridge19_py39.py && uvx pytest -q`
Expected: PASS, suite entière verte.

- [ ] **Step 5: Commit**

```bash
git add P/bridge_operators.py P/bridge_plugin.py P/bridge_project_init.py P/bridge_sketcher.py T/test_bridge18_connect.py T/test_bridge19_operators.py T/test_bridge19_py39.py
git commit -m "feat(bridge): opérateurs utilisables par la session (1.9.0)"
```

---

### Task 2: Catalogue par schéma, groupes opérateur et Commun, identité du projet, relations par opérateur (§ 6.3, § 6.4, § 7)

**Files:**
- Modify: `P/bridge_operators.py`
- Modify: `P/bridge_project_init.py` (`stamp_project` l.93, `get_bridge_info` l.77, `_detect_existing_layers` l.487, `InitProjectDialog` l.514, `ensure_relations` l.704, `init_project` l.763) ; retirer `WYRE_OPERATOR`
- Modify: `P/bridge_plugin.py` (`_on_init_project` l.3633 : choix de l'opérateur ; nouvelle `_load_operator_layers` ; journal de `_on_project_read` l.1174)
- Modify: `P/i18n/layer_translations.py` (`GROUP_NAMES["Commun"] = {"fr": "Commun", "en": "Common", "pt": "Comum"}`), `P/i18n/translations.py` (`home.no_operator`)
- Modify: `T/stubs/qgis/core.py` (`QgsProject.readEntry(scope, key, default="") -> (str, bool)`, `writeEntry`, `customVariables() -> {}`)
- Create: `T/fakes19.py`, `T/test_bridge19_catalog.py`

**Interfaces:**
- Consumes: `OperatorInfo`, `OPERATOR_TEMPLATE_SCHEMA`, `LAST_OPERATOR_KEY`, `preselect_operator` (tâche 1).
- Produces (`bridge_operators.py`) :
  ```python
  OPERATOR_GROUPS = ("Demand Points", "Infrastructure", "Zones")
  COMMON_GROUPS = ("Chantier", "OSIRIS", "Cadastre UrbIS", "Urbanisme")
  COMMON_ROOT = "Commun"
  OPERATOR_KEYS: frozenset   # les 11 clés des groupes opérateur
  OPERATOR_TABLES: frozenset # leurs 11 tables (v_duct_progress compris)
  GROUP_SCHEMA_PROPERTY = "constructel_bridge/operator_schema"  # groupe racine d'un opérateur
  GROUP_KIND_PROPERTY = "constructel_bridge/group"              # nom canonique ("Commun", "Infrastructure"…)
  def layer_key(key: str, schema: str) -> str
  def base_key(layer_key: str) -> str
  def relation_id(rel_name: str, schema: str, primary_schema: str) -> str
  def parse_project_operators(raw: str) -> list[str]
  def format_project_operators(schemas) -> str
  def parse_operator_labels(raw: str) -> dict[str, str]
  def format_operator_labels(labels) -> str
  def canonical_group(name: str, group_names) -> str | None
  ```
- Produces (`bridge_project_init.py`) :
  ```python
  def catalog_for(schema: str) -> list[tuple]
  def _detect_existing_layers(schema: str = OPERATOR_TEMPLATE_SCHEMA) -> set[str]   # clés catalogue simples
  def find_child_group(parent, canonical: str)
  def ensure_operator_group(root, operator: OperatorInfo)
  def ensure_common_group(root)
  def stamp_project(operator: OperatorInfo, suffix: bool | None = None) -> None
  def get_bridge_info() -> dict   # + "operators": list[str], "operator_labels": dict, "operator_suffix": bool
  def ensure_relations(loaded: dict | None = None, primary_schema: str | None = None) -> int
  def init_project(conn_params, password, selected, add_basemap=True, apply_styles=True,
                   selected_basemaps=None, *, operator: OperatorInfo, suffix: bool | None = None) -> int
  class InitProjectDialog(QDialog):  # provisoire, supprimée en tâche 9
      def __init__(self, parent=None, operator: OperatorInfo = ...)
  ```
- Produces (plugin) : `def _load_operator_layers(self, operator, selected: set, basemaps: set, apply_styles: bool, suffix: bool | None = None) -> int` (ne lève jamais ; erreur → `init.error`, retour 0).
- Produces (`T/fakes19.py`) : `FakeProject`, `FakeGroup`, `FakeLayerNode`, `FakeLayer`, `FakeRasterLayer`, `FakeRelation`, `FakeRelationManager`, `install_fake_project(module, monkeypatch) -> FakeProject`, constantes `WYRE = OperatorInfo("WYRE", "Wyre", "wyre")`, `ORANGE = OperatorInfo("ORANGE", "Orange", "orange")`.

Règles à respecter :
- `layer_key("cables", "orange") == "cables@orange"`, clé commune inchangée ; `relation_id` rend `rel_name` pour le schéma principal, sinon `f"{rel_name}__{schema}"`.
- Ordre à la racine : groupes opérateur (ordre de chargement) < Commun < Basemaps < Référence (§ 9.1). `ensure_operator_group` cherche l'enfant racine dont `GROUP_SCHEMA_PROPERTY` vaut le schéma, sinon `insertGroup` avant le premier enfant Commun / Basemaps / Référence (sinon en fin), nommé `operator.label`. `ensure_common_group` : même principe, avant Basemaps / Référence. Création paresseuse : aucun groupe vide.
- Sous-groupes : `find_child_group(parent, canonical)` (enfants directs : propriété `GROUP_KIND_PROPERTY`, sinon n'importe quelle traduction de `GROUP_NAMES`, sinon nom exact), sinon `addGroup` avec la propriété posée. Ne jamais utiliser `findGroup` (récursif dans QGIS) pour un sous-groupe.
- `stamp_project(operator, suffix)` ajoute le schéma à `bridge/operator` s'il manque, fusionne le libellé dans `bridge/operator_labels`, écrit `bridge/operator_suffix` quand `suffix` n'est pas `None`, plus `bridge/version` et les variables `bridge_operator` (même chaîne), `bridge_version`, `bridge_plugin`. `init_project` l'appelle **avant** le premier `addMapLayer` (le renommage se fait sur `layersAdded`, tâche 3).
- `ensure_relations` : pour chaque schéma présent (clés `@schema` de `loaded`, ou couches découvertes dont la table est dans `OPERATOR_TABLES`), les deux bouts se résolvent par `layer_key(cle, schema)` (une clé commune donne la couche commune) ; principal = `primary_schema`, sinon premier de `get_bridge_info()["operators"]`, sinon `wyre`.
- `_on_init_project` (provisoire) : `preselect_operator(self._operators, QgsSettings().value(LAST_OPERATOR_KEY, ""))` ; `None` → `QMessageBox.warning(..., tr("home.no_operator"))`. `_load_operator_layers` reprend le corps actuel (init, traductions, `_rewrite_value_relation_sources`, `_hook_layers`, `_apply_scope_to_layers`, message `init.success`) et mémorise `LAST_OPERATOR_KEY = operator.schema`.

- [ ] **Step 1: Écrire les tests en échec** (`T/test_bridge19_catalog.py`, fixture `pi` importée de `test_bridge18_layers`)

```python
def test_catalog_for_substitutes_operator_schema_only(pi):
    cat = pi.catalog_for("orange")
    assert [e[0] for e in cat] == [e[0] for e in pi.LAYER_CATALOG]
    by_key = {e[0]: e for e in cat}
    assert by_key["cables"][2] == "orange" and by_key["duct_progress"][2:4] == ("orange", "v_duct_progress")
    assert by_key["interventions"][2] == "chantier" and by_key["v_form_lists"][2] == "ref"
    assert by_key["wfs_parcels"][2] == "wfs" and by_key["docs_elements"][2] == "docs"

def test_operator_constants_match_catalog(pi):
    op = [e for e in pi.LAYER_CATALOG if e[1] in bo.OPERATOR_GROUPS]
    assert {e[0] for e in op} == bo.OPERATOR_KEYS and {e[3] for e in op} == bo.OPERATOR_TABLES
    assert {e[1] for e in pi.LAYER_CATALOG} - set(bo.OPERATOR_GROUPS) - {"Référence"} == set(bo.COMMON_GROUPS)

def test_layer_keys_and_relation_ids():
    assert bo.layer_key("cables", "orange") == "cables@orange"
    assert bo.layer_key("interventions", "orange") == "interventions"
    assert bo.base_key("cables@orange") == "cables" and bo.base_key("interventions") == "interventions"
    assert bo.relation_id("zone_pop_to_mro", "wyre", "wyre") == "zone_pop_to_mro"
    assert bo.relation_id("zone_pop_to_mro", "orange", "wyre") == "zone_pop_to_mro__orange"

def test_project_identity_helpers():
    assert bo.parse_project_operators("wyre") == ["wyre"]
    assert bo.parse_project_operators(" wyre, orange ,wyre") == ["wyre", "orange"]
    assert bo.parse_project_operators("") == []
    assert bo.format_project_operators(["wyre", "orange", "wyre"]) == "wyre,orange"
    assert bo.parse_operator_labels(bo.format_operator_labels({"wyre": "Wyre"})) == {"wyre": "Wyre"}
    assert bo.parse_operator_labels("not json") == {} == bo.parse_operator_labels("")

def test_detect_existing_layers_is_per_operator(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    project.add_pg("wyre", "cables"); project.add_pg("chantier", "interventions")
    assert pi._detect_existing_layers("orange") == {"interventions"}
    assert {"cables", "interventions"} <= pi._detect_existing_layers("wyre")

def test_two_operators_one_common_tree(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    sel = {"cables", "zone_pop", "interventions", "v_form_lists"}
    pi.init_project({}, "", sel, selected_basemaps={"osm"}, operator=WYRE)
    pi.init_project({}, "", sel, selected_basemaps={"osm"}, operator=ORANGE)
    root = project.layerTreeRoot()
    assert [c.name() for c in root.children()] == ["Wyre", "Orange", "Commun", "Basemaps", "Référence"]
    assert [c.name() for c in root.children()[1].children()] == ["Infrastructure", "Zones"]
    assert [c.name() for c in root.children()[2].children()] == ["Chantier"]
    assert project.count_pg("chantier", "interventions") == 1
    assert project.count_pg("wyre", "cables") == project.count_pg("orange", "cables") == 1
    assert [l.name() for l in project.mapLayers().values()].count("OpenStreetMap") == 1

def test_add_mode_after_translation_reuses_subgroups(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    pi.init_project({}, "", {"demand_points"}, operator=WYRE)
    wyre = project.layerTreeRoot().children()[0]
    wyre.children()[0].setName("Points de demande")
    pi.init_project({}, "", {"demand_points", "cables"}, operator=WYRE)
    assert [c.name() for c in wyre.children()] == ["Points de demande", "Infrastructure"]

def test_stamp_accumulates_operators_before_first_layer(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    pi.init_project({}, "", {"cables"}, operator=WYRE)
    pi.init_project({}, "", {"cables"}, operator=ORANGE)
    info = pi.get_bridge_info()
    assert info["operators"] == ["wyre", "orange"] and info["operator"] == "wyre,orange"
    assert info["operator_labels"] == {"wyre": "Wyre", "orange": "Orange"}
    first_add = next(i for i, e in enumerate(project.events) if e[0] == "add")
    assert ("entry", "operator_labels") in project.events[:first_add]

def test_legacy_identity_still_read(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    project.writeEntry("bridge", "operator", "wyre")
    assert pi.get_bridge_info()["operators"] == ["wyre"] and pi.is_bridge_project()

def test_relations_are_built_per_operator(pi, monkeypatch):
    project = install_fake_project(pi, monkeypatch)
    for op in (WYRE, ORANGE):
        pi.init_project({}, "", {"cables", "zone_pop", "zone_mro"}, operator=op)
    rels = project.relationManager().relations()
    assert rels["zone_pop_to_mro"].referencedLayerId() == project.layer("wyre", "zone_mro").id()
    assert rels["zone_pop_to_mro__orange"].referencedLayerId() == project.layer("orange", "zone_mro").id()
    assert rels["cables_to_pop__orange"].referencingLayerId() == project.layer("orange", "cables").id()

def test_relation_discovery_pairs_same_operator(pi, monkeypatch):
    # projet avec les couches des deux opérateurs, puis pi.ensure_relations() sans argument
    assert rels["cables_to_pop__orange"].referencedLayerId() == project.layer("orange", "zone_pop").id()
```
Côté plugin :
```python
def test_load_operator_layers_passes_operator_and_remembers_it(bp18, monkeypatch):
    # bridge_project_init.init_project remplacé par un enregistreur, apply_all_translations neutralisé
    assert plugin._load_operator_layers(ORANGE, {"cables"}, set(), True) == 3
    assert calls[0]["operator"] == ORANGE
    assert QgsSettings().value(bo.LAST_OPERATOR_KEY) == "orange"

def test_init_menu_without_usable_operator_warns(bp18, monkeypatch):
    plugin._connected, plugin._operators = True, []
    plugin._on_init_project()
    assert warnings == [bp18.tr("home.no_operator")]
```

- [ ] **Step 2: Lancer les tests, constater l'échec**

Run: `uvx pytest -q T/test_bridge19_catalog.py`
Expected: FAIL (`AttributeError: catalog_for`, `init_project() got an unexpected keyword argument 'operator'`).

- [ ] **Step 3: Écrire `T/fakes19.py` puis implémenter**

`FakeGroup` imite QGIS : `findGroup` et `findLayer` **récursifs**, `addGroup`, `insertGroup(index, name)`, `addLayer(layer) -> FakeLayerNode`, `insertChildNode`, `addChildNode`, `removeChildNode`, `children`, `parent`, `name/setName`, `customProperty/setCustomProperty`, `clone` (profond, mêmes identifiants de couche), `setExpanded`, `setItemVisibilityChecked`. `FakeProject` enregistre `events` (`("add", id)`, `("entry", key)`), offre `add_pg(schema, table, name=None)`, `layer(schema, table)`, `count_pg(schema, table)`, `readEntry/writeEntry`, `relationManager()`, `layerTreeRoot()`, `mapLayersByName`, `setCrs`. `FakeLayer(source, name, provider)` a la signature de `QgsVectorLayer` (couches PostgreSQL et WFS) et porte aussi `fields/editorWidgetSetup/setEditorWidgetSetup`, `mapTipTemplate/setMapTipTemplate`, `displayExpression/setDisplayExpression`, `isReadOnly/setReadOnly`, `loadNamedStyle`, `importNamedStyle`, `triggerRepaint`, `customProperty`. `install_fake_project` remplace dans le module visé `QgsProject`, `QgsVectorLayer`, `QgsRasterLayer`, `QgsRelation`, `QgsCoordinateReferenceSystem`, `_apply_styles_from_db` (→ `set()`) et `_apply_embedded_styles` (→ rien). Ensuite, les fonctions selon les règles ci-dessus.

- [ ] **Step 4: Lancer les tests et la suite**

Run: `uvx pytest -q T/test_bridge19_catalog.py && uvx pytest -q`
Expected: PASS, suite verte (y compris `test_trench_segments_layer_in_catalog` et `test_duct_progress_layer_in_catalog`, catalogue inchangé).

- [ ] **Step 5: Commit**

```bash
git add P/bridge_operators.py P/bridge_project_init.py P/bridge_plugin.py P/i18n T/stubs/qgis/core.py T/fakes19.py T/test_bridge19_catalog.py
git commit -m "feat(bridge): catalogue par opérateur, groupes opérateur et Commun (1.9.0)"
```

---

### Task 3: Suffixe de l'opérateur et groupes traduits (§ 6.4, § 9.5)

**Files:**
- Modify: `P/bridge_operators.py`
- Modify: `P/bridge_sketcher.py` (`apply_layer_name` l.139, `apply_group_names` l.161, table des noms traduits de `_sync_value_relation_layer_names` l.336-345)
- Create: `T/test_bridge19_names.py`

**Interfaces:**
- Consumes: `OPERATOR_TABLES`, `GROUP_SCHEMA_PROPERTY`, `GROUP_KIND_PROPERTY`, `parse_project_operators`, `parse_operator_labels`, entrées `bridge/operator*` (tâche 2).
- Produces :
  ```python
  SUFFIX_SEP = " · "
  SUFFIX_SETTINGS_KEY = "constructel_bridge/operator_suffix"
  def suffix_applies(operators: Sequence[str], opted_in: bool) -> bool   # len(set(operators)) >= 2 or opted_in
  def operator_layer_name(base: str, label: str) -> str                  # f"{base} · {label}"
  def split_operator_suffix(name: str) -> tuple[str, str | None]         # coupe au dernier " · "
  # bridge_sketcher
  def project_operator_naming(project) -> tuple[dict[str, str], bool]    # (libellés, suffixe actif)
  ```

Règles : `apply_layer_name` calcule toujours le nom depuis `LAYER_DISPLAY_NAMES` (jamais depuis le nom courant, donc pas de double suffixe) puis ajoute `operator_layer_name(nom, libellé)` si la table est dans `OPERATOR_TABLES`, si le schéma de la source a un libellé dans `bridge/operator_labels` et si `suffix_applies(...)`. Un projet sans `operator_labels` (1.8) n'est jamais suffixé. Décocher la case dans un projet à un opérateur retire le suffixe au prochain passage. `apply_group_names` parcourt les enfants de la racine et ceux des groupes portant `GROUP_SCHEMA_PROPERTY` ou `GROUP_KIND_PROPERTY == "Commun"` ; il traduit d'abord par `GROUP_KIND_PROPERTY`, puis par le nom ; le groupe d'opérateur (libellé) n'est jamais renommé. La recherche par nom traduit de `_sync_value_relation_layer_names` passe d'abord le nom dans `split_operator_suffix`.

- [ ] **Step 1: Écrire les tests en échec** (fixture `sk` sur le modèle de `test_bridge_vr_layername_sync.py`, `sk.QgsProject` remplacé par un `FakeProject`)

```python
def test_name_helpers():
    assert bo.operator_layer_name("Cables", "Wyre") == "Cables · Wyre"
    assert bo.split_operator_suffix("Zones POP · Orange") == ("Zones POP", "Orange")
    assert bo.split_operator_suffix("Zones POP") == ("Zones POP", None)
    assert bo.suffix_applies(["wyre"], False) is False
    assert bo.suffix_applies(["wyre"], True) is True
    assert bo.suffix_applies(["wyre", "orange"], False) is True

def test_single_operator_without_opt_in_keeps_plain_names(sk, project):
    stamp(project, ["wyre"], {"wyre": "Wyre"}, suffix="0")
    sk.apply_layer_name(cables_wyre, "fr"); assert cables_wyre.name() == "Cables"

def test_single_operator_opt_in_adds_suffix(sk, project):
    stamp(project, ["wyre"], {"wyre": "Wyre"}, suffix="1")
    sk.apply_layer_name(cables_wyre, "fr"); assert cables_wyre.name() == "Cables · Wyre"

def test_second_operator_forces_suffix_on_both(sk, project):
    stamp(project, ["wyre", "orange"], {"wyre": "Wyre", "orange": "Orange"}, suffix="0")
    sk.apply_layer_name(cables_wyre, "en"); sk.apply_layer_name(cables_orange, "en")
    assert (cables_wyre.name(), cables_orange.name()) == ("Cables · Wyre", "Cables · Orange")

def test_suffix_is_never_doubled(sk, project):           # Review Focus 2
    stamp(project, ["wyre", "orange"], {...}, suffix="1")
    for lang in ("fr", "fr", "pt"):
        sk.apply_layer_name(cables_wyre, lang)
    assert cables_wyre.name() == "Cabos · Wyre"

def test_legacy_project_is_never_suffixed(sk, project):
    project.writeEntry("bridge", "operator", "wyre")       # 1.8 : pas d'operator_labels
    sk.apply_layer_name(cables_wyre, "fr"); assert cables_wyre.name() == "Cables"

def test_common_layer_never_suffixed(sk, project):
    stamp(project, ["wyre", "orange"], {...}, suffix="1")
    sk.apply_layer_name(FakeLayer.pg("chantier", "interventions", name="Interventions"), "fr")
    assert layer.name() == "Interventions"

def test_offline_language_switch_keeps_suffix(sk, project):   # Review Focus 3
    stamp(project, ["wyre", "orange"], {...}, suffix="0")
    sk.apply_all_translations("fr"); sk.apply_all_translations("en")
    assert cables_orange.name() == "Cables · Orange"

def test_groups_translated_inside_operator_and_common(sk, project):
    # racine : Wyre(prop schéma) > Demand Points(prop groupe) ; Commun(prop "Commun") > Chantier ;
    #          Mes couches > Zones (groupe personnel)
    sk.apply_group_names("fr")
    assert names(project) == ["Wyre", "Points de demande", "Commun", "Chantier", "Mes couches", "Zones"]
    sk.apply_group_names("pt")
    assert names(project) == ["Wyre", "Pontos de procura", "Comum", "Chantier", "Mes couches", "Zones"]

def test_sync_recognizes_stale_suffixed_name(sk, project):
    # couche chantier, LayerName "POP Zones · Wyre" ; la couche wyre.zone_pop s'appelle "Zones POP · Wyre"
    sk._sync_value_relation_layer_names(project)
    assert layer_name(chantier_layer) == "Zones POP · Wyre"
```

- [ ] **Step 2: Lancer les tests, constater l'échec**

Run: `uvx pytest -q T/test_bridge19_names.py`
Expected: FAIL (`AttributeError: operator_layer_name`, noms non suffixés).

- [ ] **Step 3: Implémenter selon les règles ci-dessus**

- [ ] **Step 4: Lancer les tests et la suite**

Run: `uvx pytest -q T/test_bridge19_names.py T/test_bridge_vr_layername_sync.py && uvx pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add P/bridge_operators.py P/bridge_sketcher.py T/test_bridge19_names.py
git commit -m "feat(bridge): suffixe de l'opérateur et groupes imbriqués traduits (1.9.0)"
```

---

### Task 4: Styles, ValueRelation et get_feature ciblent le même opérateur (§ 7, § 9.3)

**Files:**
- Modify: `P/bridge_operators.py`
- Modify: `P/bridge_project_init.py` (`_apply_styles_from_db` l.1060, `_apply_embedded_styles` l.988)
- Modify: `P/bridge_plugin.py` (`_apply_db_default_styles` l.2720)
- Modify: `P/bridge_sketcher.py` (nouvelle `retarget_operator_references` ; `_sync_value_relation_layer_names` lui délègue les paires source opérateur → cible opérateur)
- Modify: `T/test_bridge_vr_layername_sync.py` : `FakeLayer` gagne `id()` (`f"{name}@{table}"`), un argument `schema="wyre"`, `mapTipTemplate/setMapTipTemplate`, `displayExpression/setDisplayExpression` ; `FakeUri` gagne `schema()`. Aucune assertion modifiée.
- Create: `T/test_bridge19_retarget.py`

**Interfaces:**
- Consumes: `OPERATOR_TABLES`, `OPERATOR_TEMPLATE_SCHEMA`, `base_key` (tâche 2), `project_operator_naming`, `split_operator_suffix` (tâche 3), `bridge_nominatif.datasource_param`.
- Produces :
  ```python
  def style_sources(schema: str, table: str) -> list[tuple[str, str]]
  def retarget_get_feature(expr: str, targets: Mapping[str, str]) -> str
  def retarget_layer_source(ds: str, schema: str) -> str
  # bridge_sketcher
  def retarget_operator_references(project) -> int    # nombre de couches modifiées
  ```

Règles de `retarget_operator_references` :
- Couche opérateur = `QgsVectorLayer` postgres dont la table de la source est dans `OPERATOR_TABLES` ; son opérateur = schéma de la source. Index `(schéma, table) → couches`, dans l'ordre de `project.mapLayers()`.
- Pour chaque ValueRelation d'une couche opérateur L (schéma s) : la table cible t se lit dans `Layer` (identifiant d'une couche du projet), sinon dans `LayerName` (nom exact d'une couche du projet, nom de table, nom traduit avec ou sans suffixe). Si t n'est pas une table opérateur : rien. Si la référence désigne déjà une couche de `(s, t)` : rien (copie filtrée). Sinon, si une couche existe pour `(s, t)`, la première est posée dans `Layer` (identifiant), `LayerName` (nom courant) et `LayerSource` (`retarget_layer_source(src, s)`). Si aucune n'existe : rien, jamais un autre opérateur.
- Cibles de `get_feature` pour L : pour chaque table opérateur t ayant une couche dans s, les clés `t`, ses noms traduits FR/EN/PT avec et sans chaque suffixe connu, ainsi que les noms et identifiants des couches `(autre schéma, t)`, toutes vers l'identifiant de la couche de `(s, t)`. Appliqué au `Value` des ValueRelation, à `mapTipTemplate()` et à `displayExpression()`.
- `retarget_get_feature` remplace `get_feature(\s*'REF'\s*,` par `get_feature('<id>',` (premier argument entre apostrophes seulement, clés les plus longues d'abord).
- Styles : `style_sources("orange", "cables") == [("orange", "cables"), ("wyre", "cables")]` ; aucune source de repli pour `wyre` ni pour une table commune. Les deux requêtes de style essaient les sources dans l'ordre et s'arrêtent à la première ligne trouvée.

- [ ] **Step 1: Écrire les tests en échec**

```python
def test_style_sources():
    assert bo.style_sources("orange", "cables") == [("orange", "cables"), ("wyre", "cables")]
    assert bo.style_sources("wyre", "cables") == [("wyre", "cables")]
    assert bo.style_sources("chantier", "interventions") == [("chantier", "interventions")]

def test_retarget_get_feature():
    expr = "attribute(get_feature('zone_pop', 'id', zone_pop_id), 'code') || get_feature( 'Zones MRO · Wyre' ,'id',x)"
    out = bo.retarget_get_feature(expr, {"zone_pop": "zp_or", "Zones MRO · Wyre": "zm_or"})
    assert out == "attribute(get_feature('zp_or', 'id', zone_pop_id), 'code') || get_feature('zm_or','id',x)"
    assert bo.retarget_get_feature("get_feature('structures','id',1)", {}) == "get_feature('structures','id',1)"

def test_retarget_layer_source():
    ds = "dbname='farois_ftth' host=h key='id' table=\"wyre\".\"zone_pop\" (geom)"
    assert bo.retarget_layer_source(ds, "orange") == ds.replace('"wyre"', '"orange"')
    ref = "dbname='x' host=h key='rid' table=\"ref\".\"v_form_lists\""
    assert bo.retarget_layer_source(ref, "orange") == ref

def test_db_style_falls_back_to_wyre_style(pi, monkeypatch):
    # curseur : ligne seulement pour ("wyre", "cables", "geom")
    assert pi._apply_styles_from_db({}, "pw", {"cables@orange": orange_cables}) == {"cables@orange"}
    assert [p[:2] for p in cursor.params] == [("orange", "cables"), ("wyre", "cables")]

def test_embedded_style_found_by_base_key(pi, monkeypatch):
    pi._apply_embedded_styles({"cables@orange": layer})
    assert layer.loaded_styles[0].endswith("styles/cables.qml")

def test_plugin_default_styles_fall_back_to_wyre(bp18, monkeypatch):
    plugin._apply_db_default_styles()        # couche orange.cables, style en base pour wyre seulement
    assert events[0] == "style" and queried == [("orange", "cables"), ("wyre", "cables")]

def test_value_relations_target_own_operator(sk, project):
    # wyre : zone_pop « Zones POP », structures ; orange : zone_pop, zone_mro, structures, cables
    # cables orange : VR[0] LayerName "zone_pop", LayerSource table "wyre"."zone_pop",
    #   Value "coalesce(attribute(get_feature('zone_mro','id',zone_mro_id),'name'),'')" ;
    # VR[1] LayerName = nom courant de structures wyre
    sk.retarget_operator_references(project)
    cfg0, cfg1 = vr(cables_or, 0), vr(cables_or, 1)
    assert cfg0["Layer"] == zone_pop_or.id() and cfg0["LayerName"] == zone_pop_or.name()
    assert 'table="orange"."zone_pop"' in cfg0["LayerSource"]
    assert f"get_feature('{zone_mro_or.id()}'," in cfg0["Value"]
    assert cfg1["Layer"] == structures_or.id()

def test_targets_found_without_any_suffix(sk, project):
    # un seul opérateur, suffixe désactivé : deux couches « Zones POP » n'existent pas, mais la VR
    # d'une couche orange citant "Zones POP" (nom d'une couche wyre d'un projet partagé) est réorientée
    assert vr(cables_or, 0)["Layer"] == zone_pop_or.id()

def test_map_tip_and_display_expression_retargeted(sk, project):
    # zone_drop orange : mapTip "[% attribute(get_feature('zone_distribution','id',\"zone_distribution_id\"),'breakout_letter') %]"
    sk.retarget_operator_references(project)
    assert f"get_feature('{zone_distribution_or.id()}'," in zone_drop_or.mapTipTemplate()

def test_no_cross_operator_fallback(sk, project):        # Review Focus 4
    # cables orange, VR LayerName "zone_pop", seule wyre.zone_pop existe
    sk.retarget_operator_references(project)
    assert vr(cables_or, 0) == original_config

def test_filtered_copy_is_kept(sk, project):
    # ducts wyre, VR LayerName "Zones POP (copie)" = copie filtrée de wyre.zone_pop
    sk.retarget_operator_references(project)
    assert vr(ducts_w, 0)["LayerName"] == "Zones POP (copie)"

def test_language_switch_keeps_own_operator_targets(sk, project):   # Review Focus 3
    sk.apply_all_translations("fr"); sk.apply_all_translations("en")
    assert vr(cables_or, 0)["Layer"] == zone_pop_or.id()
    assert vr(cables_or, 0)["LayerName"] == "POP Zones · Orange"
```

- [ ] **Step 2: Lancer les tests, constater l'échec**

Run: `uvx pytest -q T/test_bridge19_retarget.py`
Expected: FAIL (`AttributeError: style_sources`, `retarget_operator_references`).

- [ ] **Step 3: Implémenter selon les règles ci-dessus ; enrichir les doublures de `test_bridge_vr_layername_sync.py`**

- [ ] **Step 4: Lancer les tests et la suite**

Run: `uvx pytest -q T/test_bridge19_retarget.py T/test_bridge_vr_layername_sync.py T/test_bridge_project_init.py && uvx pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add P/bridge_operators.py P/bridge_project_init.py P/bridge_plugin.py P/bridge_sketcher.py T/test_bridge_vr_layername_sync.py T/test_bridge19_retarget.py
git commit -m "feat(bridge): styles, listes de valeurs et get_feature ciblent le même opérateur (1.9.0)"
```

---

### Task 5: Lecture seule et périmètre sur tous les schémas opérateurs (O6, § 7)

**Files:**
- Modify: `P/bridge_nominatif.py` (`should_lock_layer` l.546)
- Modify: `P/bridge_plugin.py` (`_apply_scope_to_layers` l.3427, `_read_session_scope` l.2336 ; nouvelle `_operator_schemas`)
- Modify: `T/test_bridge18_connect.py` (`_FakeCursor` : `FROM <schéma>.zone_mro|zone_pop` pour tout schéma ; nouveaux paramètres `extra_names={schéma: (mro, pop)}` et `denied_schemas=()`)
- Create: `T/test_bridge19_scope.py`

**Interfaces:**
- Consumes: `self._operators`, `self._operator_registry`, `is_safe_schema` (tâche 1).
- Produces :
  ```python
  def should_lock_layer(schema: str, scope: SessionScope | None, operator_schemas: Collection[str] = ("wyre",)) -> bool
  def _operator_schemas(self) -> frozenset[str]   # {"wyre"} ∪ registre
  ```

Règles : `should_lock_layer` rend `schema in operator_schemas` pour une session nominative sans `network.write`, `False` sinon (défaut historique inchangé). `_read_session_scope` exécute, pour chaque schéma utilisable sûr (ordre de `self._operators`), `f"SELECT id::text, name FROM {schema}.zone_mro WHERE id = ANY(%s::uuid[])"` et l'équivalent `code` sur `zone_pop`, identifiant sans guillemets (texte identique à 1.8.4 pour `wyre`). Un échec par schéma est journalisé (« Noms des zones du perimetre illisibles : … ») et les autres schémas restent résolus. Les dictionnaires sont fusionnés. Aucune requête quand la dimension est vide.

- [ ] **Step 1: Écrire les tests en échec**

```python
def test_should_lock_layer_all_operator_schemas():
    ro = bn.parse_session_scope(("VIEWER", True, False, ["m1"], [], [], []))
    ops = {"wyre", "orange"}
    assert bn.should_lock_layer("orange", ro, ops) is True
    assert bn.should_lock_layer("chantier", ro, ops) is False
    assert bn.should_lock_layer("orange", ro) is False
    assert bn.should_lock_layer("orange", None, ops) is False

def test_viewer_locks_every_operator_schema(bp18, monkeypatch):
    plugin = _plugin(bp18, monkeypatch, VIEWER)                  # de test_bridge18_scope
    plugin._operator_registry = {"orange": ORANGE, "wyre": WYRE}
    # couches wyre.ducts, orange.ducts, chantier.permis_voirie
    assert plugin._apply_scope_to_layers() == 2

def test_scope_names_resolved_in_every_usable_schema(bp18, monkeypatch, tmp_path):
    cur = _FakeCursor(scope_row=("VIEWER", True, False, [M1, M2], [], [], []),
                      operator_rows=[("ORANGE", "Orange", "orange", True), ("WYRE", "Wyre", "wyre", True)],
                      mro_names=[(M1, "Anderlecht")], extra_names={"orange": ([(M2, "Gent")], [])})
    plugin._auto_connect()
    assert plugin._scope_names[0] == {M1: "Anderlecht", M2: "Gent"}
    assert [s for s in cur.sql() if ".zone_mro" in s] == [
        "SELECT id::text, name FROM orange.zone_mro WHERE id = ANY(%s::uuid[])",
        "SELECT id::text, name FROM wyre.zone_mro WHERE id = ANY(%s::uuid[])"]

def test_unreadable_schema_keeps_other_names(bp18, monkeypatch, tmp_path):
    # denied_schemas={"orange"}
    assert plugin._scope_names[0] == {M1: "Anderlecht"}
```

- [ ] **Step 2: Lancer les tests, constater l'échec**

Run: `uvx pytest -q T/test_bridge19_scope.py`
Expected: FAIL (`should_lock_layer() takes 2 positional arguments`, nom « Gent » absent).

- [ ] **Step 3: Implémenter selon les règles ci-dessus**

- [ ] **Step 4: Lancer les tests et la suite**

Run: `uvx pytest -q T/test_bridge19_scope.py T/test_bridge18_scope.py T/test_bridge_scope_message.py T/test_bridge_nominatif.py && uvx pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add P/bridge_nominatif.py P/bridge_plugin.py T/test_bridge18_connect.py T/test_bridge19_scope.py
git commit -m "feat(bridge): lecture seule et périmètre sur tous les schémas opérateurs (1.9.0)"
```

---

### Task 6: Réorganisation des projets 1.8 au clic « Ajouter » (§ 6.5)

**Files:**
- Modify: `P/bridge_project_init.py` (`needs_reorganization`, `reorganize_legacy_tree`)
- Modify: `P/bridge_plugin.py` (`_load_operator_layers` : réorganisation d'abord si nécessaire)
- Modify: `P/i18n/translations.py` (`home.reorganized`, variable `{operators}`)
- Create: `T/test_bridge19_reorganize.py`

**Interfaces:**
- Consumes: `ensure_operator_group`, `ensure_common_group`, `stamp_project`, `canonical_group`, `GROUP_*_PROPERTY` (tâche 2), `suffix_applies` (tâche 3).
- Produces :
  ```python
  def needs_reorganization(root) -> bool
  def reorganize_legacy_tree(project, registry: Mapping[str, OperatorInfo]) -> list[OperatorInfo]
  ```

Règles :
- Groupe hérité = enfant racine sans propriété Bridge dont `canonical_group(nom, GROUP_NAMES)` (n'importe quelle langue, ou nom exact pour les groupes communs) est dans `OPERATOR_GROUPS` ∪ `COMMON_GROUPS`.
- Groupe opérateur hérité : schéma = schéma de la première couche postgres de table opérateur qu'il contient (récursif), sinon `wyre`. Opérateur = `registry[schéma]`, sinon `OperatorInfo(schéma.upper(), libellé de bridge/operator_labels ou schéma.capitalize(), schéma, readable=False)`. Déplacé par `clone()` dans `ensure_operator_group`, propriété `GROUP_KIND_PROPERTY` posée, original retiré : identifiants de couche inchangés, ordre relatif conservé.
- Groupe commun hérité : déplacé dans `ensure_common_group`.
- Retour : opérateurs touchés, dans l'ordre d'apparition. Un second appel rend `[]` et ne change rien.
- `_load_operator_layers` : si `needs_reorganization(root)`, réorganise, appelle `stamp_project(op, suffix)` pour chaque opérateur rendu (suffixe : celui de la case, forcé à vrai si l'opérateur chargé diffère), pousse `tr("home.reorganized", operators=…)` (« Projet réorganisé par opérateur (groupes {operators} et Commun) : enregistre-le pour garder cette organisation »), puis charge. `_on_project_read` n'appelle jamais la réorganisation.

- [ ] **Step 1: Écrire les tests en échec**

```python
def test_reorganizes_18_project_in_french(pi, monkeypatch):     # Review Focus 1
    # racine : "Points de demande"(wyre.demand_points) "Infrastructure"(wyre.cables) "Zones"(wyre.zone_pop)
    #          "Chantier"(chantier.interventions) "Basemaps" "Référence" "Mes couches"
    assert pi.reorganize_legacy_tree(project, {"wyre": WYRE}) == [WYRE]
    assert [c.name() for c in root.children()] == ["Wyre", "Commun", "Basemaps", "Référence", "Mes couches"]
    assert [c.name() for c in root.children()[0].children()] == ["Points de demande", "Infrastructure", "Zones"]
    assert root.findLayer(cables.id()) is not None

def test_reorganize_portuguese_names(pi, monkeypatch):           # Review Focus 1
    # "Pontos de procura", "Infraestrutura", "Zonas"
    assert [c.name() for c in root.children()[0].children()] == ["Pontos de procura", "Infraestrutura", "Zonas"]

def test_reorganize_is_idempotent(pi, monkeypatch):              # Review Focus 2
    pi.reorganize_legacy_tree(project, {"wyre": WYRE})
    before = tree_names(project)
    assert pi.reorganize_legacy_tree(project, {"wyre": WYRE}) == []
    assert tree_names(project) == before and not pi.needs_reorganization(project.layerTreeRoot())

def test_wyre_group_label_without_wyre_scope(pi, monkeypatch):
    assert [o.label for o in pi.reorganize_legacy_tree(project, {})] == ["Wyre"]

def test_needs_reorganization_false_for_19_project(pi, monkeypatch):
    pi.init_project({}, "", {"cables"}, operator=WYRE)
    assert pi.needs_reorganization(project.layerTreeRoot()) is False

def test_adding_second_operator_reorganizes_and_forces_suffix(bp18, monkeypatch):
    plugin._load_operator_layers(ORANGE, {"cables"}, set(), True, suffix=False)
    info = get_bridge_info()
    assert info["operators"] == ["wyre", "orange"]
    assert messages[-2] == bp18.tr("home.reorganized", operators="Wyre")
    assert names_of_wyre_operator_layers() == ["Cables · Wyre"]   # suffixe reçu au clic « Ajouter »

def test_opening_legacy_project_never_reorganizes(bp18, monkeypatch):
    # reorganize_legacy_tree remplacée par une fonction qui lève ; plugin connecté, projet 1.8
    plugin._on_project_read(None)
    assert tree_names(project) == legacy_names
```

- [ ] **Step 2: Lancer les tests, constater l'échec**

Run: `uvx pytest -q T/test_bridge19_reorganize.py`
Expected: FAIL (`AttributeError: reorganize_legacy_tree`).

- [ ] **Step 3: Implémenter selon les règles ci-dessus**

- [ ] **Step 4: Lancer les tests et la suite**

Run: `uvx pytest -q T/test_bridge19_reorganize.py && uvx pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add P/bridge_project_init.py P/bridge_plugin.py P/i18n/translations.py T/test_bridge19_reorganize.py
git commit -m "feat(bridge): réorganisation des projets 1.8 au clic Ajouter (1.9.0)"
```

---

### Task 7: Check-in hors connexion (§ 6.6)

**Files:**
- Modify: `P/bridge_onboarding.py` (`OnboardingWizard.__init__` l.466, `_update_user_profile` l.527, `_install_selected_plugins` l.562)
- Modify: `P/bridge_plugin.py` (`_run_onboarding` l.3964, `_on_onboarding` l.3980)
- Modify: `P/i18n/translations.py` (`onboard.action.profile_offline`)
- Create: `T/test_bridge19_checkin.py`

**Interfaces:**
- Produces :
  ```python
  class OnboardingWizard(QWizard):
      def __init__(self, parent, username, user_id, is_new_user, db_conn=None, email_domain="", include_profile: bool = True)
  def install_or_activate_plugin(pid: str, upgrade: bool = False) -> str   # "active" | "activated" | "installed" | "updated" ; lève en cas d'échec
  # plugin
  def _run_onboarding(self, is_new_user: bool, include_profile: bool = True) -> None
  ```

Règles : sans profil, `PAGE_USER` n'est pas enregistrée et `setStartId(PAGE_PLUGINS)` ; `_update_user_profile` ajoute alors `tr("onboard.action.profile_offline")` (« Profil : disponible une fois connecté »). `install_or_activate_plugin` reprend la boucle de `_install_selected_plugins` pour une extension (`loadPlugin` + `startPlugin` si installée inactive, `installer.installPlugin(pid)` si absente ou si `upgrade`), réutilisée par le Diagnostic. `_on_onboarding` ne demande plus la connexion et passe `include_profile=self._connected` ; `db_conn` vaut `None` hors connexion.

- [ ] **Step 1: Écrire les tests en échec**

Le fixture installe `FakeWizard` / `FakeWizardPage` dans `qgis.PyQt.QtWidgets` et un module `qgis.utils` factice (`available_plugins`, `active_plugins`, `loadPlugin`, `startPlugin`) **avant** d'importer `bridge_onboarding` (la classe hérite de `QWizard` à l'import), puis remplace les six classes de page par des fabriques neutres.
```python
def test_checkin_opens_offline_without_profile(bp18, monkeypatch):
    plugin._connected = False
    plugin._on_onboarding()
    assert created[0]["include_profile"] is False and created[0]["db_conn"] is None

def test_checkin_connected_keeps_profile(bp18, monkeypatch):
    plugin._connected = True
    plugin._on_onboarding()
    assert created[0]["include_profile"] is True

def test_wizard_without_profile_skips_user_page(onb):
    w = onb.OnboardingWizard(None, "", "", False, include_profile=False)
    assert w.page_ids == [onb.OnboardingWizard.PAGE_PLUGINS, onb.OnboardingWizard.PAGE_RESOURCE_SHARING,
                          onb.OnboardingWizard.PAGE_FILTERMATE, onb.OnboardingWizard.PAGE_SERVICES,
                          onb.OnboardingWizard.PAGE_SUMMARY]
    assert w.start_id == onb.OnboardingWizard.PAGE_PLUGINS

def test_offline_summary_mentions_profile_later(onb):
    w._update_user_profile()
    assert w._actions_done == [onb.tr("onboard.action.profile_offline")]

def test_install_or_activate_plugin(onb, monkeypatch):
    # available = {"a", "b"}, active = {"a"}
    assert onb.install_or_activate_plugin("a") == "active"
    assert onb.install_or_activate_plugin("b") == "activated" and started == ["b"]
    assert onb.install_or_activate_plugin("c") == "installed" and installer.installed == ["c"]
    assert onb.install_or_activate_plugin("a", upgrade=True) == "updated"
```

- [ ] **Step 2: Lancer les tests, constater l'échec**

Run: `uvx pytest -q T/test_bridge19_checkin.py`
Expected: FAIL (`unexpected keyword argument 'include_profile'`).

- [ ] **Step 3: Implémenter selon les règles ci-dessus**

- [ ] **Step 4: Lancer les tests et la suite**

Run: `uvx pytest -q T/test_bridge19_checkin.py && uvx pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add P/bridge_onboarding.py P/bridge_plugin.py P/i18n/translations.py T/test_bridge19_checkin.py
git commit -m "feat(bridge): check-in utilisable hors connexion (1.9.0)"
```

---

### Task 8: Diagnostic (§ 6.6, § 7)

**Files:**
- Create: `P/bridge_diagnostic.py` (pur, aucun import qgis ni psycopg2)
- Create: `P/bridge_diagnostic_dialog.py`
- Modify: `P/bridge_plugin.py` (`_on_status` l.3994 remplacée par `_status_text` + `_on_diagnostic` ; `action_status` l.964 → `_on_diagnostic`)
- Modify: `P/i18n/translations.py` (clés `diag.*` ci-dessous ; texte de `menu.status` : « Statut et diagnostic » / « Status and diagnostics » / « Estado e diagnóstico »)
- Create: `T/test_bridge19_diagnostic.py`

**Interfaces:**
- Consumes: `RECOMMENDED_PLUGINS`, `install_or_activate_plugin` (tâche 7) ; `ca_bundle_path`, `normalize_login`, `NOMINAL_SETTINGS_KEYS` ; `_FIXED_AUTH_CFG_IDS["ad"]` (`nomin18`) et `["wyre"]` (`9i19s56`).
- Produces (`bridge_diagnostic.py`) :
  ```python
  LEVEL_OK, LEVEL_WARNING, LEVEL_ERROR = "ok", "warning", "error"
  @dataclass(frozen=True)
  class Check:
      key: str             # "version" | "plugin" | "server" | "identity"
      level: str
      message_key: str
      params: dict = field(default_factory=dict)
      action: str = ""     # "" | "plugin_manager" | "install" | "update" | "activate"
      target: str = ""     # identifiant d'extension
  PLUGIN_REPO_URL = os.environ.get("CONSTRUCTEL_PLUGIN_REPO_URL", "http://192.168.160.31:9080/plugin-repo/plugins.xml")
  NETWORK_TIMEOUT = 3.0
  def compare_versions(a: str, b: str) -> int
  def latest_published_version(xml_text: str, plugin_name: str = "Constructel Bridge") -> str | None
  def version_check(installed: str, latest: str | None, error: str = "") -> Check
  def plugin_checks(recommended, available, active, statuses) -> list[Check]
  def probe_server(host: str, port: int, cafile: str, timeout: float = NETWORK_TIMEOUT) -> tuple[str, str]
  def server_check(host: str, port: int, outcome: str, detail: str) -> Check
  def identity_check(memorized_login: str, derived_login: str, config_ids, ad_cfg_id: str, wyre_cfg_id: str) -> Check
  def fetch_latest_version(url: str = PLUGIN_REPO_URL, timeout: float = NETWORK_TIMEOUT) -> tuple[str | None, str]
  def run_network_checks(host: str, port: int, cafile: str, installed_version: str,
                         url: str = PLUGIN_REPO_URL, timeout: float = NETWORK_TIMEOUT) -> list[Check]   # [version, server]
  ```
- Produces (`bridge_diagnostic_dialog.py`) : `class DiagnosticDialog(QDialog): __init__(self, parent, status_text: str, local_checks: list[Check], network_args: dict, on_action: Callable[[Check], list[Check]])`.
- Produces (plugin) : `_status_text() -> str`, `_diagnostic_local_checks() -> list[Check]`, `_on_diagnostic() -> None`, `_run_diagnostic_action(check: Check) -> list[Check]`.

Correspondance des messages (clés littérales) :

| Cas | Niveau | Clé | Paramètres | Action |
|---|---|---|---|---|
| version à jour | ok | `diag.version_ok` | installed | |
| version plus récente publiée | warning | `diag.version_update` | installed, latest | `plugin_manager` |
| dépôt injoignable ou illisible | warning | `diag.version_unknown` | installed, error | |
| extension active (pas `upgradeable`) | ok | `diag.plugin_ok` | name | |
| statut `upgradeable` | warning | `diag.plugin_update` | name | `update` |
| installée inactive | warning | `diag.plugin_inactive` | name | `activate` |
| absente | warning | `diag.plugin_missing` | name | `install` |
| serveur joignable, certificat valide | ok | `diag.server_ok` | host, port | |
| injoignable ou sans réponse | error | `diag.server_unreachable` | host, port, error | |
| TLS refusé (réponse `N`) | error | `diag.server_tls_refused` | host, port | |
| certificat refusé | error | `diag.server_cert_invalid` | host, port, error | |
| login mémorisé, configs `nomin18` et `9i19s56` présentes | ok | `diag.identity_ok` | login | |
| login mémorisé, `nomin18` absente | warning | `diag.identity_no_password` | login | |
| login seulement déduit du poste | warning | `diag.identity_derived` | login | |
| aucun login utilisable | error | `diag.identity_none` | | |

Plus `diag.title`, `diag.running` (« Vérification en cours… »), `diag.section_connection`, `diag.action_install`, `diag.action_update`, `diag.action_activate`, `diag.action_plugin_manager`.

Sonde serveur (algorithme imposé, aucune authentification) :
```python
sock = socket.create_connection((host, port), timeout)      # OSError -> ("unreachable", str(exc))
sock.settimeout(timeout)
sock.sendall(struct.pack("!ii", 8, 80877103))               # SSLRequest PostgreSQL
answer = sock.recv(1)                                        # timeout ou b"" -> ("unreachable", …)
if answer != b"S": return ("tls_refused", repr(answer))
ctx = ssl.create_default_context(cafile=cafile)              # check_hostname=True, CERT_REQUIRED
ctx.wrap_socket(sock, server_hostname=host)                  # ssl.SSLCertVerificationError -> ("cert_invalid", …)
return ("ok", "")                                            # socket toujours fermé (finally)
```
Câblage : `_diagnostic_local_checks()` = `plugin_checks(RECOMMENDED_PLUGINS, available_plugins, active_plugins, statuses)` + `identity_check(normalize_login(QgsSettings pg_login), self._nominal_login(), authManager().configIds(), "nomin18", "9i19s56")`. `statuses` vient de `pyplugin_installer.installer_data.plugins.all()` (`{pid: p["status"]}`, cache seulement, `None` si indisponible ou vide). `configIds()` ne demande pas le mot de passe maître. Le dialogue lance `run_network_checks(DEFAULT_HOST, DEFAULT_PORT, str(ca_bundle_path(plugin_dir)), PLUGIN_VERSION)` dans `QgsTask.fromFunction`, garde une référence à la tâche et ignore le résultat si le dialogue est fermé. En tête du dialogue : `_status_text()` (message exact de l'ancien `_on_status`). Actions : `plugin_manager` → `self.iface.actionManagePlugins().trigger()` ; `install` / `update` / `activate` → `install_or_activate_plugin(target, upgrade=(action == "update"))`, puis les vérifications locales sont recalculées.

- [ ] **Step 1: Écrire les tests en échec**

```python
@pytest.mark.parametrize("a,b,expected", [("1.8.4", "1.9.0", -1), ("1.10.0", "1.9.9", 1),
                                          ("1.9", "1.9.0", 0), ("1.9.0", "1.9.0", 0)])
def test_compare_versions(a, b, expected):
    assert bd.compare_versions(a, b) == expected

XML = ('<plugins><pyqgis_plugin name="Constructel Bridge" version="1.8.3"/>'
       '<pyqgis_plugin name="Constructel Bridge" version="1.8.4"/><pyqgis_plugin name="Autre" version="9.9"/></plugins>')
def test_latest_published_version():
    assert bd.latest_published_version(XML) == "1.8.4"
    assert bd.latest_published_version("<oops") is None
    assert bd.latest_published_version("<plugins/>") is None

def test_version_check_levels():
    c = bd.version_check("1.8.4", "1.9.0")
    assert (c.level, c.message_key, c.action) == ("warning", "diag.version_update", "plugin_manager")
    assert bd.version_check("1.9.0", "1.9.0").level == "ok"
    u = bd.version_check("1.9.0", None, "timed out")
    assert (u.level, u.message_key, u.params["error"]) == ("warning", "diag.version_unknown", "timed out")

def test_plugin_checks():
    rec = [{"id": i, "name": i.upper()} for i in ("a", "b", "c", "d")]
    checks = bd.plugin_checks(rec, {"a", "b", "d"}, {"a", "d"}, {"d": "upgradeable"})
    assert [(c.target, c.level, c.action) for c in checks] == [
        ("a", "ok", ""), ("b", "warning", "activate"), ("c", "warning", "install"), ("d", "warning", "update")]

def test_probe_server_sends_ssl_request_and_reads_refusal():
    # serveur local en thread : lit 8 octets, répond b"N"
    assert received == struct.pack("!ii", 8, 80877103)
    assert bd.probe_server("127.0.0.1", port, "/nope.pem", timeout=1.0)[0] == "tls_refused"

def test_probe_server_silent_server_times_out():           # Review Focus 5
    # serveur local qui accepte puis ne répond jamais
    start = time.monotonic()
    assert bd.probe_server("127.0.0.1", port, "/nope.pem", timeout=0.5)[0] == "unreachable"
    assert time.monotonic() - start < 2.0

def test_probe_server_closed_port():
    assert bd.probe_server("127.0.0.1", free_port, "/nope.pem", timeout=0.5)[0] == "unreachable"

def test_identity_check():
    ids = {"nomin18", "9i19s56"}
    assert bd.identity_check("jdoe", "jdoe", ids, "nomin18", "9i19s56").message_key == "diag.identity_ok"
    assert bd.identity_check("jdoe", "jdoe", {"9i19s56"}, "nomin18", "9i19s56").message_key == "diag.identity_no_password"
    assert bd.identity_check("", "jdoe", set(), "nomin18", "9i19s56").message_key == "diag.identity_derived"
    assert bd.identity_check("", "", set(), "nomin18", "9i19s56").level == "error"

def test_diagnostic_module_is_pure():
    src = (PLUGIN_DIR / "bridge_diagnostic.py").read_text(encoding="utf-8")
    assert "psycopg2" not in src and "import qgis" not in src and "from qgis" not in src

def test_status_text_matches_previous_message(bp18, monkeypatch, tmp_path):
    # session nominative connectée
    assert plugin._status_text() == "\n".join([
        bp18.tr("status.connected_to", host=bp18.DEFAULT_HOST, port=bp18.DEFAULT_PORT, dbname=bp18.DEFAULT_DBNAME,
                user=LOGIN, bridge_user=plugin._bridge_user, bridge_user_id=plugin._bridge_user_id,
                hooks=plugin._layer_hooks_installed),
        bp18.tr("nominal.mode_nominal", login=LOGIN), plugin._scope_text()])
    plugin._connected = False
    assert plugin._status_text() == bp18.tr("status.not_connected")

def test_diagnostic_opens_offline_with_local_checks(bp18, monkeypatch):
    plugin._connected = False
    plugin._on_diagnostic()
    assert [c.key for c in dialogs[0].local_checks] == ["plugin"] * 6 + ["identity"]
    assert dialogs[0].network_args["host"] == bp18.DEFAULT_HOST

def test_status_menu_entry_opens_diagnostic(bp18, monkeypatch):
    iface = _initgui_ready(bp18, monkeypatch)                    # de test_bridge18_connect
    plugin.initGui()
    status = next(a for a in plugin._actions if a.text() == bp18.tr("menu.status"))
    assert status.triggered._slots == [plugin._on_diagnostic]
```

- [ ] **Step 2: Lancer les tests, constater l'échec**

Run: `uvx pytest -q T/test_bridge19_diagnostic.py`
Expected: FAIL (`ModuleNotFoundError: constructel_bridge.bridge_diagnostic`).

- [ ] **Step 3: Implémenter selon le tableau et l'algorithme ci-dessus**

`latest_published_version` : `xml.etree.ElementTree`, plus grande version (selon `compare_versions`) parmi les `pyqgis_plugin` dont l'attribut `name` vaut le nom demandé ; `ParseError` → `None`. `compare_versions` : comparaison des parties numériques, la partie manquante vaut 0, une partie non numérique compte pour 0. `fetch_latest_version` : `urllib.request.urlopen(url, timeout=timeout)` ; toute exception → `(None, str(exc))`.

- [ ] **Step 4: Lancer les tests et la suite**

Run: `uvx pytest -q T/test_bridge19_diagnostic.py && uvx pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add P/bridge_diagnostic.py P/bridge_diagnostic_dialog.py P/bridge_plugin.py P/i18n/translations.py T/test_bridge19_diagnostic.py
git commit -m "feat(bridge): diagnostic du poste utilisable hors connexion (1.9.0)"
```

---

### Task 9: Écran d'accueil (solution B) avec la sélection actuelle intégrée (§ 6.1, § 6.2, § 6.4, § 6.6)

**Files:**
- Create: `P/bridge_home_model.py`, `P/bridge_home.py`
- Modify: `P/bridge_project_init.py` : `InitProjectDialog` devient `LayerSelectionWidget(QWidget)` ; `_detect_existing_basemaps`, `count_loaded_layers`, `LoadedCounts`
- Modify: `P/bridge_plugin.py` : `_on_home`, `home_snapshot`, `_home_actions` ; `self._tool_button.clicked` (l.1016) → `_on_home` ; `action_init_project` (l.978) → `_on_home` ; `_on_init_project` supprimée
- Modify: `P/i18n/translations.py` (clés `home.*` ci-dessous ; texte de `menu.init_project` : « Accueil · charger les couches » / « Home · load layers » / « Início · carregar camadas »)
- Create: `T/test_bridge19_home.py`

**Interfaces:**
- Consumes: `OperatorInfo`, `preselect_operator`, `LAST_OPERATOR_KEY` (tâche 1) ; `_load_operator_layers` (tâches 2 et 6) ; `SUFFIX_SETTINGS_KEY`, `suffix_applies` (tâche 3) ; `_on_onboarding` (tâche 7) ; `_on_diagnostic`, `plugin_checks` (tâche 8) ; `_on_connect`, `_on_load_project`, `_on_change_language`, `_scope_text` (existants).
- Produces (`bridge_project_init.py`) :
  ```python
  @dataclass(frozen=True)
  class LoadedCounts:
      per_operator: dict   # schéma -> couches opérateur présentes dans l'arbre de couches
      common: int          # couches communes de travail (hors v_form_lists, docs_elements)
      basemaps: int
  def count_loaded_layers(project) -> LoadedCounts
  def _detect_existing_basemaps() -> set[str]
  class LayerSelectionWidget(QWidget):
      def set_operator(self, schema: str, label: str) -> None
      def selected_layers(self) -> set[str]       # clés simples, "v_form_lists" toujours incluse
      def selected_basemaps(self) -> set[str]     # sans les fonds déjà chargés
      def want_basemap(self) -> bool
      def want_styles(self) -> bool
  ```
- Produces (`bridge_home_model.py`) :
  ```python
  @dataclass(frozen=True)
  class HomeSnapshot:
      connected: bool
      header: str                  # "login · périmètre", "" hors connexion
      operators: tuple             # OperatorInfo utilisables
      counts: LoadedCounts
      labels: dict                 # schéma -> libellé (projet ∪ registre)
      last_schema: str
      project_suffix: bool | None  # bridge/operator_suffix du projet, None si absent
      last_suffix: bool            # QgsSettings SUFFIX_SETTINGS_KEY, défaut False
  @dataclass(frozen=True)
  class HomeState:
      selector: str                # "none" | "label" | "buttons"
      load_enabled: bool
      message_key: str             # "" | "home.connect_to_see" | "home.no_operator"
      preselected: OperatorInfo | None
      mode: str                    # "init" | "add"
      loaded_marks: frozenset      # schémas utilisables déjà chargés (✓ sur le bouton)
      summary: tuple               # ((libellé, nb couches), …) pour tout schéma chargé
      saved_project_enabled: bool
  @dataclass(frozen=True)
  class HomeActions:
      snapshot: Callable[[], HomeSnapshot]
      connect: Callable[[], None]
      load: Callable[[OperatorInfo, set, set, bool, bool], int]   # (opérateur, couches, fonds, styles, suffixe)
      open_saved_project: Callable[[], None]
      checkin: Callable[[], None]
      diagnostic: Callable[[], None]
      change_language: Callable[[], None]
  def home_state(snapshot: HomeSnapshot) -> HomeState
  def suffix_state(loaded_schemas, selected_schema: str, project_suffix: bool | None, last_suffix: bool) -> tuple[bool, bool]   # (cochée, modifiable)
  ```

Règles de `home_state` / `suffix_state` :
- Hors connexion : `selector="none"`, chargement désactivé, `home.connect_to_see` (« Connecte-toi pour voir les opérateurs auxquels tu as accès »), « Projet enregistré » désactivé.
- Connecté sans opérateur : `selector="none"`, chargement désactivé, `home.no_operator`.
- Un opérateur : `"label"`. Plusieurs : `"buttons"` (boutons exclusifs, ✓ sur les opérateurs déjà chargés, tous sélectionnables, § 9.2).
- Présélection : `preselect_operator(operators, last_schema)`.
- `mode="add"` dès que `counts.per_operator` ou `counts.common` est non vide.
- `summary` : tous les schémas de `counts.per_operator` (même hors scopes), libellé `labels.get(s, s.capitalize())`.
- `suffix_state` : si `set(loaded_schemas) | {selected_schema}` compte au moins deux schémas → `(True, False)` ; sinon `(project_suffix, True)` si le projet a déjà un choix, sinon `(last_suffix, True)`.

Écran (`HomeDialog(actions, parent)`, `render()` reconstruit tout depuis `actions.snapshot()`) :
- En-tête : `● {header}` ; hors connexion `tr("home.not_connected")` et un bouton `tr("home.connect")` → `actions.connect()` puis `render()`.
- Grande tuile `tr("home.tile_load")` : sélecteur (`tr("home.operator_label")`), `LayerSelectionWidget` (modèle et description, arbre, fonds de plan, styles, Tout/Rien), libellé des groupes opérateur avec le badge de l'opérateur, groupes communs suffixés de `tr("home.common_tag")`, case `tr("home.suffix_checkbox")` (« Ajouter le nom de l'opérateur aux couches ») pilotée par `suffix_state` et recalculée à chaque changement d'opérateur, résumé `tr("home.loaded_title")` + `tr("home.loaded_operator", operator=…, count=…)` + `tr("home.loaded_basemaps", count=…)`, bouton principal `tr("home.btn_init", operator=label)` (« Initialiser · Wyre ») ou `tr("home.btn_add", operator=label)` (« Ajouter les couches · Orange »).
- Clic principal : `actions.load(op, widget.selected_layers(), widget.selected_basemaps() if widget.want_basemap() else set(), widget.want_styles(), suffix_coché)` ; la case modifiable mémorise son état dans `SUFFIX_SETTINGS_KEY` ; écran fermé si le retour est > 0.
- Tuiles : `home.tile_project` (sous-titre `home.tile_project_sub`) → ferme l'écran puis `open_saved_project()` ; `home.tile_checkin` (`home.tile_checkin_sub`, `{active}/{total}`, plus `home.tile_checkin_updates`, `{count}`, si des mises à jour sont connues) ; `home.tile_diagnostic` (`home.tile_diagnostic_sub`, `{version}`) ; `home.tile_language` (`home.tile_language_sub`). Ces trois dernières laissent l'écran ouvert et appellent `render()`.
- `LayerSelectionWidget.set_operator` recalcule `_detect_existing_layers(schema)` : couches opérateur grisées pour ce seul opérateur, couches communes et fonds de plan déjà chargés toujours grisés (`init.already_loaded`).

- [ ] **Step 1: Écrire les tests en échec**

```python
def snap(**kw):
    base = dict(connected=True, header="jdoe · 10 MRO", operators=(WYRE, ORANGE), counts=LoadedCounts({}, 0, 0),
                labels={"wyre": "Wyre", "orange": "Orange"}, last_schema="", project_suffix=None, last_suffix=False)
    return hm.HomeSnapshot(**{**base, **kw})

def test_offline_state():
    s = hm.home_state(snap(connected=False, header="", operators=()))
    assert (s.selector, s.load_enabled, s.message_key, s.saved_project_enabled) == ("none", False, "home.connect_to_see", False)

def test_no_operator_state():
    s = hm.home_state(snap(operators=()))
    assert (s.selector, s.load_enabled, s.message_key) == ("none", False, "home.no_operator")

def test_one_operator_is_a_label_two_are_buttons():
    assert hm.home_state(snap(operators=(WYRE,))).selector == "label"
    assert hm.home_state(snap()).selector == "buttons"

def test_preselection_and_add_mode():
    s = hm.home_state(snap(last_schema="wyre", counts=LoadedCounts({"wyre": 14}, 0, 3)))
    assert s.preselected == WYRE and s.mode == "add"
    assert s.loaded_marks == frozenset({"wyre"}) and s.summary == (("Wyre", 14),)
    assert hm.home_state(snap()).mode == "init"

def test_operator_outside_scopes_is_summarized_not_selectable():   # Review Focus 4
    s = hm.home_state(snap(operators=(WYRE,), counts=LoadedCounts({"orange": 9}, 0, 0)))
    assert s.selector == "label" and s.preselected == WYRE
    assert s.summary == (("Orange", 9),) and s.loaded_marks == frozenset()

def test_suffix_state():
    assert hm.suffix_state([], "wyre", None, False) == (False, True)
    assert hm.suffix_state([], "wyre", None, True) == (True, True)
    assert hm.suffix_state(["wyre"], "wyre", False, True) == (False, True)
    assert hm.suffix_state(["wyre"], "orange", False, False) == (True, False)

def test_count_loaded_layers_ignores_layers_outside_the_tree(pi, monkeypatch):
    # wyre.cables dans l'arbre, wyre.zone_pop enregistrée sans nœud (couche fantôme d'un QML), un fond OSM
    assert pi.count_loaded_layers(project) == pi.LoadedCounts({"wyre": 1}, 0, 1)

def test_detect_existing_basemaps(pi, monkeypatch):
    # couche raster « OpenStreetMap » présente
    assert pi._detect_existing_basemaps() == {"osm"}

def test_home_opens_offline(bp18, monkeypatch):            # O1
    plugin._connected = False
    plugin._on_home()
    assert len(dialogs) == 1 and dialogs[0].actions.snapshot().connected is False

def test_home_snapshot_connected(bp18, monkeypatch):
    plugin._connected, plugin._operators = True, [WYRE]
    snapshot = plugin.home_snapshot()
    assert snapshot.operators == (WYRE,) and snapshot.header.startswith(LOGIN + " · ")

def test_home_actions_are_wired(bp18, monkeypatch):
    a = plugin._home_actions()
    assert a.connect == plugin._on_connect and a.checkin == plugin._on_onboarding
    assert a.diagnostic == plugin._on_diagnostic and a.change_language == plugin._on_change_language
    assert a.open_saved_project == plugin._on_load_project

def test_toolbar_click_and_init_menu_open_home(bp18, monkeypatch):
    iface = _initgui_ready(bp18, monkeypatch)
    plugin.initGui()
    assert plugin._tool_button.clicked._slots == [plugin._on_home]
    init = next(a for a in plugin._actions if a.text() == bp18.tr("menu.init_project"))
    assert init.triggered._slots == [plugin._on_home]
```

- [ ] **Step 2: Lancer les tests, constater l'échec**

Run: `uvx pytest -q T/test_bridge19_home.py`
Expected: FAIL (`ModuleNotFoundError: constructel_bridge.bridge_home_model`).

- [ ] **Step 3: Implémenter le modèle, le widget de sélection, l'écran et le câblage selon les règles ci-dessus**

`bridge_home_model.py` ne dépend que de `bridge_operators` et de `LoadedCounts`, qu'il importe sous `TYPE_CHECKING` pour rester sans Qt. `count_loaded_layers` ne compte que les couches qui ont un nœud dans l'arbre (`root.findLayer(id)`), ce qui écarte les couches fantômes créées par les relations des QML.

- [ ] **Step 4: Lancer les tests et la suite**

Run: `uvx pytest -q T/test_bridge19_home.py && uvx pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add P/bridge_home_model.py P/bridge_home.py P/bridge_project_init.py P/bridge_plugin.py P/i18n/translations.py T/test_bridge19_home.py
git commit -m "feat(bridge): écran d'accueil avec choix de l'opérateur (1.9.0)"
```

---

### Task 9b: Navigateur QGIS et projets enregistrés suivent les opérateurs utilisables (§ 6.7)

Ajout du 12/11, décision Simon : deux endroits codaient `wyre` en dur hors spec. La connexion `wyre` du navigateur QGIS restreinte à `wyre,osiris` (l'infra Orange n'y apparaît pas), et `_PROJECT_SCHEMAS = ("wyre", "public")` (un projet enregistré dans `orange.qgis_projects` n'est pas listé).

**Files:**
- Modify: `P/bridge_operators.py` (deux fonctions pures)
- Modify: `P/bridge_plugin.py`, aux endroits suivants :
  - `_PG_CONNECTIONS["wyre"]["schemas"]` vers la ligne 214 : reste la valeur de repli ;
  - les écritures de `{base}/schemas` vers les lignes 2982 et 3048 ;
  - `_PROJECT_SCHEMAS` vers la ligne 3758 et ses usages dans `_read_and_clean_project` (vers 3778) et `_list_db_projects` (vers 3913) ;
  - `_connect`, juste après l'appel `_load_operators` de la tâche 1.
- Test: `T/test_bridge19_browser_projects.py`

**Interfaces:**
- Consumes (tâche 1) : `OperatorInfo(code, label, schema)`, `self._operators: list[OperatorInfo]` (utilisables, ordre `code`, schémas déjà validés par `is_safe_schema`), `_load_operators()`. Constantes de test `WYRE`, `ORANGE` (`T/fakes19.py`, tâche 2).
- Produces (`bridge_operators.py`) :
  - `def browser_schemas(operators: Sequence[OperatorInfo]) -> str` : schémas des opérateurs dans l'ordre reçu, puis `osiris`, joints par des virgules ; `"wyre,osiris"` si la liste est vide ;
  - `def project_schemas(operators: Sequence[OperatorInfo]) -> tuple[str, ...]` : schémas des opérateurs puis `"public"` ; `("wyre", "public")` si la liste est vide.
- Produces (plugin) :
  - `def _project_schemas(self) -> tuple[str, ...]` : remplace tous les usages de la constante de classe `_PROJECT_SCHEMAS`, qui est supprimée ;
  - `def _refresh_browser_schemas(self) -> None` : réécrit `PostgreSQL/connections/<_PG_CONNECTIONS["wyre"]["name"]>/schemas` avec `browser_schemas(self._operators)` ; ne touche jamais l'entrée `be`.

- [ ] **Step 1 : écrire les tests en échec**

```python
def test_browser_schemas_operateurs_puis_osiris():
    assert bo.browser_schemas([WYRE, ORANGE]) == "wyre,orange,osiris"

def test_browser_schemas_vide_repli_historique():
    assert bo.browser_schemas([]) == "wyre,osiris"

def test_project_schemas_operateurs_puis_public():
    assert bo.project_schemas([WYRE, ORANGE]) == ("wyre", "orange", "public")
    assert bo.project_schemas([]) == ("wyre", "public")

def test_projet_dun_schema_non_utilisable_refuse(plugin):
    plugin._operators = [WYRE]
    assert plugin._read_and_clean_project(object(), "orange", "x") is False   # journal « Rejected invalid schema »

def test_liste_projets_parcourt_les_schemas_utilisables(plugin, fake_cursor):
    plugin._operators = [WYRE, ORANGE]
    plugin._list_db_projects()
    assert fake_cursor.schemas_probed == ["wyre", "orange", "public"]

def test_refresh_browser_schemas_ecrit_le_reglage_sans_toucher_be(plugin, settings):
    settings.setValue("PostgreSQL/connections/be/schemas", "public")
    plugin._operators = [WYRE, ORANGE]
    plugin._refresh_browser_schemas()
    assert settings.value("PostgreSQL/connections/wyre/schemas") == "wyre,orange,osiris"
    assert settings.value("PostgreSQL/connections/be/schemas") == "public"
```

- [ ] **Step 2 : lancer les tests et constater l'échec**

Run: `uvx pytest -q plugin-repo/packages/constructel_bridge_tests/test_bridge19_browser_projects.py`
Expected: FAIL (`browser_schemas` / `project_schemas` / `_project_schemas` absents)

- [ ] **Step 3 : implémenter**

Fonctions pures dans `bridge_operators.py`. Dans le plugin :
- `_project_schemas()` délègue à `project_schemas(self._operators)` ; `_operators` absent ou vide donne le repli `("wyre", "public")` ;
- la garde anti-injection de `_read_and_clean_project` porte désormais sur `self._project_schemas()` ;
- `_connect` appelle `_refresh_browser_schemas()` après `_load_operators()`, dans les deux modes (nominatif et repli) ;
- les écritures existantes de `{base}/schemas` pour `wyre` passent par `browser_schemas(getattr(self, "_operators", []))`, pour qu'une reconfiguration de la connexion ne revienne pas à `wyre,osiris`.

- [ ] **Step 4 : lancer les tests ciblés puis la suite complète**

Run: `uvx pytest -q`
Expected: tout vert (aucune régression sur les tests existants des projets en base et de la connexion `be`)

- [ ] **Step 5 : commit**

```bash
git add plugin-repo/packages/constructel_bridge/bridge_operators.py plugin-repo/packages/constructel_bridge/bridge_plugin.py plugin-repo/packages/constructel_bridge_tests/test_bridge19_browser_projects.py
git commit -m "feat(bridge): navigateur QGIS et projets enregistrés suivent les opérateurs utilisables (1.9.0)"
```

### Task 10: Revue i18n, metadata 1.9.0, changelog, recette QGIS

**Files:**
- Create: `T/test_bridge19_i18n.py`
- Modify: `P/metadata.txt` (`version=1.9.0`, entrée `v1.9.0` en tête de `changelog=`, ASCII comme les entrées précédentes)

**Interfaces:**
- Consumes: toutes les clés `home.*`, `diag.*`, `onboard.action.profile_offline` des tâches 2 à 9 ; `GROUP_NAMES["Commun"]`.

- [ ] **Step 1: Écrire le test**

```python
KEYS_19 = ["home.no_operator", "home.reorganized", "home.not_connected", "home.connect", "home.tile_load",
           "home.operator_label", "home.btn_init", "home.btn_add", "home.loaded_title", "home.loaded_operator",
           "home.loaded_basemaps", "home.common_tag", "home.connect_to_see", "home.suffix_checkbox",
           "home.tile_project", "home.tile_project_sub", "home.tile_checkin", "home.tile_checkin_sub",
           "home.tile_checkin_updates", "home.tile_diagnostic", "home.tile_diagnostic_sub",
           "home.tile_language", "home.tile_language_sub", "onboard.action.profile_offline",
           "diag.title", "diag.running", "diag.section_connection", "diag.version_ok", "diag.version_update",
           "diag.version_unknown", "diag.plugin_ok", "diag.plugin_update", "diag.plugin_inactive",
           "diag.plugin_missing", "diag.server_ok", "diag.server_unreachable", "diag.server_tls_refused",
           "diag.server_cert_invalid", "diag.identity_ok", "diag.identity_no_password", "diag.identity_derived",
           "diag.identity_none", "diag.action_install", "diag.action_update", "diag.action_activate",
           "diag.action_plugin_manager"]

@pytest.mark.parametrize("key", KEYS_19)
def test_bridge19_keys_present_in_three_languages(key):
    for lang in ("en", "fr", "pt"):
        assert TRANSLATIONS[lang][key].strip()

def test_common_group_translated():
    assert GROUP_NAMES["Commun"] == {"fr": "Commun", "en": "Common", "pt": "Comum"}

def test_metadata_is_190():
    meta = (PLUGIN_DIR / "metadata.txt").read_text(encoding="utf-8")
    assert "\nversion=1.9.0\n" in meta and "changelog=v1.9.0 - " in meta
```

- [ ] **Step 2: Lancer le test, constater l'échec sur `test_metadata_is_190`**

Run: `uvx pytest -q T/test_bridge19_i18n.py`
Expected: FAIL sur la seule version (les clés existent depuis leurs tâches).

- [ ] **Step 3: Mettre `version=1.9.0` et l'entrée de changelog**

Contenu : écran d'accueil au clic (connecté ou non) ; choix d'un opérateur parmi ceux de la session (schéma lisible, croisé avec les scopes), puis ajout d'un deuxième ; groupe par opérateur et groupe Commun ; suffixe de l'opérateur optionnel avec un seul opérateur, obligatoire dès le deuxième ; styles, listes de valeurs et infobulles visent les couches du même opérateur (style Wyre en repli) ; lecture seule et périmètre sur tous les schémas opérateurs ; réorganisation des projets 1.8 au clic « Ajouter » seulement ; check-in, diagnostic et langue hors connexion ; « Statut » ouvre le Diagnostic ; aucun nouveau prérequis serveur.

- [ ] **Step 4: Suite complète**

Run: `uvx pytest -q`
Expected: `N passed`, N > 538, 0 échec.

- [ ] **Step 5: Recette manuelle (QGIS 3.28 et une 4.x), consignée dans la PR**

Sans réseau : l'écran s'ouvre, Check-in sans page Profil, Diagnostic termine en ≤ 3 s par vérification avec « serveur injoignable », Langue OK. Connecté avec un seul scope : opérateur affiché en texte, case du suffixe décochée par défaut. Connecté avec deux scopes : boutons exclusifs, chargement Wyre puis Orange, groupes Wyre / Orange / Commun / Basemaps / Référence, couches communes et fonds non dupliqués, suffixes posés, formulaire d'un câble Orange qui liste les POP Orange, infobulle d'une zone drop Orange. Projet 1.8 : rien ne change à l'ouverture, réorganisation au clic « Ajouter ». Compte VIEWER : couches Orange en lecture seule.

- [ ] **Step 6: Commit**

```bash
git add P/metadata.txt T/test_bridge19_i18n.py
git commit -m "feat(bridge): Constructel Bridge 1.9.0, i18n et changelog"
```

---

## Self-review (faite à la rédaction)

- **Couverture de la spec** : O1 → T9 ; O2 → T7, T8, T9 (Langue existante) ; O3 → T1, T2, T9 ; O4 → T2, T6, T9 ; O5 → T2, T3 ; O6 → T5 ; § 4 anti-objectifs : capacités du dialogue conservées (T9, `LayerSelectionWidget`), opérateur hors scopes jamais montré (T1, T9), pas de doublon (T2, T9), interface non bloquante (T8) ; § 6.4 suffixe optionnel / obligatoire → T3, T6, T9 ; § 6.5 → T6 ; § 7 clés, identité, lecture seule, périmètre, styles, résolution par couche → T2 à T5 ; § 7 menu déroulant → T8, T9 ; § 9 points 1 à 6 → T2, T9, T4, T1, T3/T9, T10.
- **Cohérence des noms** : `OperatorInfo`, `layer_key`, `base_key`, `stamp_project(operator, suffix)`, `_load_operator_layers(operator, selected, basemaps, apply_styles, suffix)`, `install_or_activate_plugin(pid, upgrade)`, `LoadedCounts` sont identiques d'une tâche à l'autre.
- **Ordre** : chaque tâche n'utilise que des interfaces des tâches précédentes. Les tests existants gardent leurs assertions : les doublures enrichies sont listées (T1, T4, T5) et `LAYER_CATALOG` ne change pas.
- **Hors périmètre, signalé** : connexion du navigateur QGIS limitée à `wyre,osiris` (`_PG_CONNECTIONS`), `_PROJECT_SCHEMAS = ("wyre", "public")`, `search_path=wyre,public` de la connexion psycopg2 du plugin, éditeurs de relations d'un opérateur secondaire (D3).
