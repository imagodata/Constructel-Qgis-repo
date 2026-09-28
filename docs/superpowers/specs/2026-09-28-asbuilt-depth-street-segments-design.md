# Segments d'axe de rue par profondeur As-Built (`geofiber_asbuilt_depth_segments`) — chantier 3

## Contexte

Le script Processing QGIS `geocode_asbuilt_depth` (dépôt `qgis_repo`,
`resource-repo/collections/asbuilt_depth_geocoder.zip` →
`processing/geocode_asbuilt_depth.py`) géocode les rapports As-Built GeoFiber
et produit une couche de **points** colorés par profondeur de pose (feu
tricolore + gris « manquante »), avec seuils **paramétrables** par
l'utilisateur (4 `QgsProcessingParameterNumber`, défauts 60/55/50/10 cm) et
upsert vers `public.geofiber_asbuilt_depth_points` (mig Farois 335) via la
connexion QGIS `be` (rôle `bureau_etudes`, accès strictement limité au schéma
`public` — invariant de sécurité de la mig 335, aucun accès à
`ref`/`infra`/`osiris`/`chantier`/`audit`/`esb`/`staging`).

Le plugin Constructel Bridge expose **deux** connexions PostgreSQL distinctes
(cf. `docs/superpowers/specs/2026-07-30-connexions-wyre-be-design.md`) :
`wyre` (rôle `ftth_editor`, accès complet dont `ref`) et `be` (rôle
`bureau_etudes`, `public` uniquement). `ref.osm_roads` (mig Farois 093b,
colonnes `name`/`name_fr`/`name_nl`/`geom LineString 31370`, index GIST) sert
déjà de référentiel de voirie à plusieurs fonctions de snap dans `chantier.*`
(ex. `fn_snap_segment_to_road`, mig 297, via `ST_LineLocatePoint`/
`ST_LineSubstring`) — bon patron pour la projection orthogonale, mais aucune
de ces fonctions ne fait ce dont ce chantier a besoin (chaîner deux points
consécutifs le long d'une même rue).

Besoins accumulés pour ce chantier 3, tous liés au même pipeline
géocodage → catégorisation → visualisation :

1. Simplifier la catégorisation (moins de classes, plus de paramètres UI)
2. Générer des segments d'axe de rue entre points consécutifs, colorés
   moitié/moitié, pointillés si longs
3. Persister les adresses non géocodées en base (pas seulement CSV)
4. Synchroniser les styles (points ET segments) vers `layer_styles`, avec
   flag « style par défaut »

## Objectif

Étendre `geocode_asbuilt_depth.py` et la base `farois_ftth` pour :

- remplacer les 4 seuils paramétrables par 3 classes fixes (rouge/orange/vert)
- ajouter une couche + une table `public.geofiber_asbuilt_depth_segments`
  matérialisant, pour chaque paire de points géocodés consécutifs sur la même
  rue, un segment en 2 moitiés colorées par catégorie de profondeur
- ajouter une table `public.geofiber_asbuilt_ungeocoded`
- synchroniser les styles points + segments vers `layer_styles`
  (`useAsDefault=True`)

## Design

### 1. Seuils : suppression des paramètres UI

`DepthThresholds` perd ses champs `yellow`/`green`/`orange` configurables :
remplacés par des constantes module-niveau (`THRESHOLD_ORANGE_CM = 50.0`,
`THRESHOLD_VERT_CM = 55.0`, `THRESHOLD_MISSING_CM = 10.0` — celui-ci reste
nécessaire pour distinguer « manquante », inchangé). `categorize_depth` passe
à 4 branches (manquante/rouge/orange/vert). Suppression de :
`THRESHOLD_GREEN`, `THRESHOLD_YELLOW`, `THRESHOLD_ORANGE` dans
`initAlgorithm`/`processAlgorithm`. `DEPTH_COLORS`, `DEPTH_SUMMARY_ORDER`,
`depth_category_labels`, `_build_depth_renderer`, `_relabel_depth_renderer`
et `style/depth_category.qml` perdent la catégorie « jaune ». Tests
`test_migration_*` et pytest purs (`categorize_depth`, `depth_category_labels`)
mis à jour en conséquence.

### 2. Style en base pour les deux couches

Aujourd'hui `_apply_depth_style` charge le `.qml` en local
(`loadNamedStyle`) mais n'écrit **jamais** dans `layer_styles` — trou
constaté, pas une régression. Nouvelle fonction `_sync_style_to_db(layer,
name, description, feedback)` appelée juste après application du style, pour
la couche points ET la couche segments :

```python
ok, err = layer.saveStyleToDatabase(name, description, True, "")
```

`useAsDefault=True` couvre l'exigence « style par défaut ». Best-effort non
bloquant (même politique que `_apply_depth_style` et `_upsert_geocoded_records`
: un échec loggue une info/warning, ne fait jamais échouer le run). Ne
fonctionne que si `layer` est bien connectée en direct sur postgres (c'est le
cas : `layer` upsertée vient de `QgsVectorLayer(ds_uri.uri(False), ...,
"postgres")`).

### 3. Table non-géocodés (`public.geofiber_asbuilt_ungeocoded`)

Nouvelle migration Farois **432** (bundle avec la table segments, §4 —
même patron que 335 : un seul fichier, plusieurs objets liés). Colonnes
calquées 1:1 sur `UNGEOCODED_CSV_HEADER` :

```sql
CREATE TABLE IF NOT EXISTS public.geofiber_asbuilt_ungeocoded (
    intervention_id TEXT PRIMARY KEY,
    work_order      TEXT,
    address_raw     TEXT,
    postal_code     TEXT,
    place           TEXT,
    depth_raw       TEXT,
    geocode_query   TEXT,
    source_message  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

PK = `intervention_id` (même clé de dédoublonnage que la table points —
upsert `ON CONFLICT` côté script, nouvelle méthode `_upsert_ungeocoded_records`
calquée sur `_upsert_geocoded_records`, même connexion `be`, même politique
best-effort). Le CSV existant (`UNGEOCODED` param) est **conservé tel quel** —
la table est un ajout, pas un remplacement (le CSV round-trip vers
ré-import manuel reste utile hors QGIS). Aucun nouveau GRANT requis : la
mig 335 a déjà posé `ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT,
INSERT, UPDATE ON TABLES TO bureau_etudes`, qui couvre toute nouvelle table.

### 4. Segments d'axe de rue

**Une seule connexion, `be`, comme le reste du script** (demande explicite —
pas de `wyre` dans ce chantier). `bureau_etudes` n'a et ne doit garder AUCUN
accès direct à `ref` (invariant de sécurité mig 335, non négociable). La
fonction de snap est donc **`SECURITY DEFINER`**, possédée par `ftth_admin`
(qui a accès à `ref`) : elle s'exécute avec les droits de son propriétaire,
pas de son appelant — `bureau_etudes` peut l'appeler sans jamais avoir SELECT
sur `ref.osm_roads`. Patron standard Postgres pour exposer un accès en lecture
étroit et contrôlé sans élargir les GRANT de table.

**Nouvelle fonction SQL** `public.fn_asbuilt_locate_on_road(p_point geometry,
p_street_name text, p_search_radius numeric DEFAULT 40.0)` — définie DANS la
migration 432 (même fichier que les tables §3/§4, pas un fichier séparé dans
`sql/30_functions/` : ce dossier est le socle post-intégration, cf.
`docs/superpowers/...socle-integration-harness` — une fonction neuve part en
migration numérotée, comme `fn_snap_segment_to_road` en mig 297, et ne
rejoint `30_functions/` qu'au prochain passage d'intégration socle).
Schéma `public`, `SECURITY DEFINER`, `OWNER TO ftth_admin`,
`REVOKE ALL ... FROM PUBLIC` puis `GRANT EXECUTE ... TO bureau_etudes`
explicite — même rigueur que les GRANT de la mig 335 :

- filtre `ref.osm_roads` par `ST_DWithin(geom, p_point, p_search_radius)`
  **et** correspondance normalisée (`unaccent`+`lower`) sur `name`/`name_fr`/
  `name_nl` vs `p_street_name` — c'est le garde-fou « nom de rue adresse pour
  valider le segment » : sans lui, `ORDER BY geom <-> p_point LIMIT 1` peut
  accrocher une rue parallèle proche (cas fréquent en zone dense)
- si plusieurs tronçons du même nom matchent dans le rayon (rue coupée à
  chaque carrefour), les fusionne (`ST_LineMerge(ST_Collect(geom))`) avant de
  localiser, pour une abscisse curviligne cohérente sur toute la rue et pas
  juste un tronçon entre deux carrefours
- retourne `(road_key text, position_m numeric, projected_point geometry,
  road_length_m numeric, road_start geometry, road_end geometry)` —
  `road_key` = nom normalisé (clé de regroupement des points côté script),
  `position_m` = abscisse curviligne en mètres sur la ligne fusionnée,
  `projected_point` = point orthogonal sur l'axe (`ST_LineInterpolatePoint`),
  `road_length_m`/`road_start`/`road_end` = longueur totale et vertex de
  départ/arrivée de la ligne fusionnée (`ST_StartPoint`/`ST_EndPoint`) —
  invariants pour un même `road_key`, redondants entre lignes mais évite un
  second aller-retour DB ; nécessaires aux segments de bout de route (§4.8)
- `NULL` si aucun tronçon nommé ne matche dans le rayon → le point reste
  affiché (couche points) mais ne participe à aucun segment (traité comme
  s'il était isolé, sans casser la chaîne des autres points de la même rue)

**Appariement côté script — recalcul complet à CHAQUE run, pas seulement sur
le lot du run courant.** Demande explicite : les segments doivent rester
synchronisés avec la couche de points dans son ÉTAT COMPLET, y compris les
points géocodés lors de runs précédents. Séquence, après l'upsert des points
de ce run (§ existant, `_upsert_geocoded_records`, inchangé) :

1. relire l'intégralité de `public.geofiber_asbuilt_depth_points` via `be`
   (SELECT déjà accordé par la mig 335 — pas seulement `geocoded_for_db` de
   ce run) : c'est l'ensemble de points sur lequel les segments sont
   recalculés, garantissant la synchro points↔segments même si ce run n'a
   géocodé aucune nouvelle adresse (ré-exécution volontaire pour
   resynchroniser après un correctif de seuils par ex.)
2. pour chaque point catégorie ≠ « manquante », appeler
   `fn_asbuilt_locate_on_road` via `be` (`SECURITY DEFINER`, cf. ci-dessus —
   adresse déjà connue, nom de rue extrait du champ `address_raw` — réutilise
   le parsing existant du texte d'adresse, pas de nouvelle dépendance)
3. regrouper par `road_key`, trier chaque groupe par `position_m`
4. chaque paire de points **adjacents** dans ce tri devient un segment —
   ligne entre les deux `projected_point` (pas les points géocodés bruts :
   ça garantit un tracé propre sur l'axe, cf. demande initiale « projection
   orthogonale »)
5. les points « manquante » (gris) sont exclus de l'étape 2 donc absents du
   tri : un point gris entre A et C n'empêche pas le segment A↔C de se
   former (ignoré, pas un trou dans la chaîne)
6. chaque paire produit **2 features** (moitié côté A = point milieu du
   segment via `ST_LineSubstring`/interpolation, catégorie = celle de A ;
   moitié côté B, catégorie = celle de B) — réutilise directement le
   renderer catégorisé existant sur `depth_category`, aucun nouveau
   mécanisme de style « bicolore »
7. `is_long = ST_Length(segment) >= 100.0` (mètres, CRS 31370 = déjà
   métrique) → symbologie pointillée sur les 2 moitiés si vrai ; porté comme
   colonne `is_long boolean` sur chaque moitié (le `.qml` distingue via une
   règle `is_long = true` → `penstyle: dash`)
8. **points en bout de route** : le premier et le dernier point (par
   `position_m`) de chaque groupe `road_key` reçoivent EN PLUS un segment
   vers le dernier vertex de la route (borne 0 ou borne max de la ligne
   fusionnée, cf. `fn_asbuilt_locate_on_road`) — une seule moitié (pas de
   point B réel), catégorie = celle du point. `point_b_intervention_id` ne
   peut pas être NULL (colonne PK, cf. §table) : on utilise un sentinel
   textuel dédié, `'__ROAD_START__'` / `'__ROAD_END__'`, jamais une valeur
   d'`intervention_id` réelle (identifiants source = numériques, cf.
   `_INTERVENTION_RE`, donc aucune collision possible). Couvre le cas d'un
   point isolé sans voisin mesuré : il reçoit alors 2 segments de bout de
   route (un vers chaque extrémité, deux lignes de PK différentes grâce au
   sentinel différent). La règle pointillé ≥100m s'applique identiquement —
   c'est elle qui signale visuellement un segment de bout de route
   anormalement long (route très longue, un seul point mesuré dessus), pas
   une borne artificielle supplémentaire.
9. **synchro complète** : l'ensemble des paires fraîchement calculé remplace
   l'état de `public.geofiber_asbuilt_depth_segments` — upsert
   (`ON CONFLICT`) des paires présentes, puis `DELETE` de toute ligne dont la
   clé `(point_a_id, point_b_id, half)` n'est plus dans le lot recalculé (un
   point qui change de rue/position lors d'un re-géocodage, ou qui devient
   « manquante », doit faire disparaître ses anciens segments, pas les
   laisser orphelins). Best-effort, même politique que le reste : un échec
   loggue une info/warning sans faire échouer le run.

**Nouvelle table** `public.geofiber_asbuilt_depth_segments` (même
migration 432) :

```sql
CREATE TABLE IF NOT EXISTS public.geofiber_asbuilt_depth_segments (
    point_a_intervention_id TEXT NOT NULL,
    -- Segment de bout de route (§4.8) : sentinel '__ROAD_START__'/'__ROAD_END__'
    -- au lieu d'un vrai intervention_id (jamais de collision : ces derniers
    -- sont numeriques, cf. _INTERVENTION_RE).
    point_b_intervention_id TEXT NOT NULL,
    half                     TEXT NOT NULL CHECK (half IN ('a','b')),
    depth_category           TEXT,
    is_long                  BOOLEAN NOT NULL DEFAULT FALSE,
    length_m                 DOUBLE PRECISION,
    road_key                 TEXT,
    geom                     GEOMETRY(LineString, 31370),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (point_a_intervention_id, point_b_intervention_id, half)
);
```

PK composite (confirmé) : `(point_a_id, point_b_id, half)` — cohérent avec la
clé de dédoublonnage des points, upsert `ON CONFLICT` symétrique à
`_upsert_geocoded_records`. Nouvelle méthode `_upsert_segment_records`, même
connexion `be`, même politique best-effort ligne par ligne. Index GIST sur
`geom`, trigger `updated_at` (même patron que 335).

**Nouvelle sortie du script** : paramètre `OUTPUT_SEGMENTS`
(`QgsProcessingParameterFeatureSink`, optionnel) + chargement automatique en
couche dans le projet (même mécanisme que `OUTPUT`), stylée via un nouveau
`style/depth_segments.qml` (renderer catégorisé sur `depth_category`, règle
pointillée sur `is_long`).

## Compatibilité / risques

- **Rétro-compatibilité seuils** : les runs existants avec des .qml/valeurs
  personnalisées de seuils perdent ce réglage (passage en dur). Acceptable —
  demande explicite de l'utilisateur, pas une régression accidentelle.
- **Connexion `be` absente/injoignable** : même politique qu'aujourd'hui —
  avertissement, section points ET segments ignorées, le reste du run
  (géocodage, OUTPUT, CSV) continue normalement. Plus de dépendance à une
  seconde connexion `wyre` : un seul point de défaillance DB, pas deux.
- **`GRANT EXECUTE` oublié sur `fn_asbuilt_locate_on_road`** : sans lui,
  `bureau_etudes` ne peut pas exécuter la fonction malgré `SECURITY DEFINER`
  — à vérifier explicitement dans la migration (bloc de vérification hors
  transaction, même patron que la mig 335).
- **Rues non nommées dans `ref.osm_roads`** (`name` NULL — voiries
  secondaires/service) : `fn_asbuilt_locate_on_road` renvoie NULL sur ces
  troncons, point traité comme isolé (cf. §4.4).
- **Performance** : `fn_asbuilt_locate_on_road` appelée une fois par point
  valide, requête indexée (GIST + btree sur `name`) — volume attendu
  (quelques centaines de points par rapport) ne pose pas de problème.
- **`layer_styles`** : `saveStyleToDatabase` avec `useAsDefault=True` écrase
  le style par défaut existant de la couche à chaque run — c'est voulu
  (source de vérité = le `.qml` livré avec le script), mais à documenter dans
  le `shortHelpString` pour ne pas surprendre un utilisateur qui aurait
  personnalisé le style en base entretemps.

## Testing

- Fonctions pures (`categorize_depth` 4 branches, `depth_category_labels`) :
  pytest existants étendus, pas de nouvelle dépendance QGIS
- `fn_asbuilt_locate_on_road` : `tests/sql/` façon mig 431/430 (cas nominal
  1 tronçon, cas fusion multi-tronçons même nom, cas nom non matché → NULL,
  cas rayon dépassé → NULL)
- Migration 432 : `tests/unit/test_migration_432_static.py` façon mig 430/431
  (structure SQL, pas d'exécution live)
- Appariement/tri par `road_key`+`position_m` et découpage moitié A/B :
  fonctions pures côté script (extraire la logique de groupement/tri dans
  une fonction testable hors QGIS, même politique que le reste du fichier)

## Hors périmètre

- Ne couvre pas les rues composées de tronçons `ref.osm_roads` de noms
  différents à cause d'un import OSM incohérent (ex. faute de frappe) — pas
  observé, pas traité préventivement
- Pas de gestion des points sur des rues différentes mais géographiquement
  proches (carrefour) au-delà de ce que `fn_asbuilt_locate_on_road` fait déjà
  via le filtre nom
- Pas de ré-écriture du CSV non-géocodés existant (conservé en parallèle de
  la nouvelle table, cf. §3)
