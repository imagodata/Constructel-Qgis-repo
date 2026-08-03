# Upsert profondeur de pose (`geofiber_asbuilt_depth_points`) — volet script du chantier 2

**Date** : 2026-08-03
**Statut** : proposé
**Périmètre** : `resource-repo/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`
(collection QGIS Resource Sharing, dépôt bare `resource-repo.git`)

## Contexte

Le chantier 1 (`docs/superpowers/specs/2026-07-30-connexions-wyre-be-design.md`) est
terminé et déployé en production depuis le 2026-07-30 : la connexion QGIS `be`
(schéma `public` uniquement), le rôle Postgres `bureau_etudes` (SELECT/INSERT/UPDATE,
pas de DELETE) et la table `public.geofiber_asbuilt_depth_points` existent et sont
vérifiés en base `farois_ftth`. Le plugin `constructel_bridge` est en version 1.5.1,
publié et servi.

Ce chantier 1 esquissait un « chantier 2 » plus large : lecture automatique des mails
As-Built (OAuth Microsoft Graph), géocodage, upsert, réponse automatique, classement
du mail. **Ce document ne couvre qu'une sous-partie de ce chantier 2** : brancher
`geocode_asbuilt_depth.py` sur la table pour qu'il y écrive (upsert) directement,
quel que soit le déclencheur du run (aujourd'hui : exécution manuelle depuis la boîte
à outils Processing de QGIS). L'automatisation OAuth / boîte mail reste hors
périmètre, non cadrée par ce document.

Le script existe déjà et est publié (10 commits d'historique dans
`resource-repo.git`, dernière itération sur le parsing/l'export CSV). Il produit
aujourd'hui une couche de points (sink Processing générique `OUTPUT`) mais n'écrit
jamais dans la table Postgres : le rejouer sur un `intervention_id` déjà présent en
base échouerait (conflit de clé primaire) puisqu'aucune logique d'upsert n'existe.

## Objectif

1. Après géocodage, upserter chaque intervention **géocodée avec succès** dans
   `public.geofiber_asbuilt_depth_points` via la connexion QGIS `be` déjà configurée
   par `constructel_bridge` — sans dupliquer ni lire aucun secret dans le script.
2. Conserver la production de la couche `OUTPUT` (et des sorties `SUMMARY` /
   `UNGEOCODED` existantes) inchangée : le push DB s'ajoute, ne remplace rien.
3. Publier la nouvelle version de la collection sur `resource-repo.git`.

## Design

### Résolution de la connexion `be`

Nouvelles constantes en tête de fichier, à côté de `OUTPUT_CRS` :

```python
BE_CONNECTION_NAME = "be"
BE_TABLE_SCHEMA = "public"
BE_TABLE_NAME = "geofiber_asbuilt_depth_points"
```

Résolution via l'API provider QGIS (aucun accès à `credentials.json` ni au code du
plugin `constructel_bridge`) :

```python
md = QgsProviderRegistry.instance().providerMetadata("postgres")
be_connection = md.findConnection(BE_CONNECTION_NAME)  # None si absente
```

Si `be_connection` est `None` (plugin absent/désactivé, connexion `be` désactivée
côté `credentials.json`) : `feedback.pushWarning(...)` explicite, la section DB
entière est sautée, le reste du run (OUTPUT/SUMMARY/UNGEOCODED) n'est pas affecté.
Même traitement si l'ouverture de la couche échoue (hôte injoignable, etc.).

### Point d'accroche dans `processAlgorithm`

Ajout d'un post-traitement après la boucle existante qui écrit dans le sink
`OUTPUT` (autour de `sink.addFeature(...)`). Cette boucle est étendue pour
accumuler, pour chaque intervention **géocodée avec succès** uniquement (celles déjà
écrites dans OUTPUT ; les échecs restent uniquement dans `UNGEOCODED`, non
poussés en base), les valeurs nécessaires à l'upsert dans une liste
`geocoded_for_db`.

Une fois la liste connue et la connexion `be` résolue, `_upsert_geocoded_records()`
est appelée avec `geocoded_for_db` et le `feedback` de l'algorithme.

### Logique d'upsert

Ouverture de la table cible comme `QgsVectorLayer` via l'URI fournie par la
connexion `be` (`be_connection.tableUri(BE_TABLE_SCHEMA, BE_TABLE_NAME)`), ce qui
réutilise automatiquement l'authcfg déjà configuré — aucune manipulation de mot de
passe dans le script.

Pour chaque intervention de `geocoded_for_db` :

1. Recherche par `intervention_id` via une expression construite avec
   `QgsExpression.quotedColumnRef()` / `quotedValue()` (jamais de SQL concaténé à la
   main → pas de risque d'injection).
2. Trouvée → écrase **toutes** les colonnes (`work_order`, `address_raw`,
   `postal_code`, `place`, `depth_cm`, `depth_category`, `geocode_query`,
   `geocode_status`, `source_message`, `geom`) via `changeAttributeValues` /
   `changeGeometry`. Choix assumé : un rapport rejoué remplace intégralement
   l'enregistrement existant, y compris la géométrie.
3. Absente → `addFeature`.
4. **Un cycle `startEditing()` / stage / `commitChanges()` par intervention**, pas un
   seul edit buffer pour tout le lot : un `commitChanges()` PostgreSQL est
   transactionnel, donc le regrouper ferait qu'un échec sur une ligne pourrait
   affecter les autres. Volumes en jeu (rapports périodiques, dizaines/centaines de
   lignes) : le coût de N petites transactions est négligeable.
5. Échec de `commitChanges()` → `feedback.reportError(msg, fatalError=False)`,
   `layer.rollBack()`, compteur d'échecs incrémenté, la boucle continue (pas d'arrêt
   du run).

À la fin : `feedback.pushInfo("Base 'be' : N créée(s), M mise(s) à jour, K échec(s),
J ignorée(s) (non géocodées)")`.

La construction du dictionnaire d'attributs à écrire (`_build_upsert_attributes`)
est factorisée en fonction pure, sans dépendance PyQGIS, testable via pytest — dans
le même esprit que le reste du fichier. Seuls les appels
`addFeature`/`changeAttributeValues`/`commitChanges` restent un mince wrapper
PyQGIS non testé unitairement.

### Publication de la collection

Pas de script dédié à créer : le flux déjà utilisé pour les 10 commits précédents
sur cette collection s'applique tel quel — cloner `resource-repo.git`, éditer
`collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py`, bumper
`version=` dans `metadata.ini` (racine du dépôt, section
`[asbuilt_depth_geocoder]`, convention `AAAA.MM.JJ.N` déjà en place — c'est ce champ
qui déclenche la détection de mise à jour côté client QGIS Resource Sharing), commit,
push sur `master`. Le hook `post-receive` du bare repo resynchronise automatiquement
`resource-repo/` (dossier servi en HTTP) et reconstruit le zip de la collection —
déjà vérifié actif (marqueur `.sync-enabled` présent, contenu servi identique au
`HEAD` du bare au moment de l'audit).

## Compatibilité / risques

- Dépend entièrement du chantier 1, déjà déployé et vérifié en prod (connexion
  `be`, rôle `bureau_etudes`, table) — aucun changement requis côté plugin ou base.
- Écrasement complet en cas de conflit (choix validé) : un rapport rejoué avec une
  adresse dégradée par erreur écrasera un géocodage précédemment correct, y compris
  sa géométrie. Trade-off assumé, pas de protection prévue.
- Pas de verrou applicatif si deux personnes lancent le script simultanément sur le
  même rapport : usage aujourd'hui manuel et ponctuel, pas un flux concurrent
  automatisé — risque jugé négligeable, à revisiter si le chantier 2 (automatisation
  email) est un jour cadré.
- Best-effort par ligne (pas de transaction globale) : un run interrompu en cours de
  route peut laisser la table partiellement mise à jour. Acceptable car le
  ré-exécution est idempotente (upsert) et rattrape les lignes manquées.

## Testing

- Pur (pytest, hors QGIS) : `_build_upsert_attributes()` sur des `InterventionRecord`
  géocodés avec succès, vérifie le mapping complet des colonnes.
- Manuel (QGIS, après implémentation) :
  1. Rapport avec un `intervention_id` inédit → une nouvelle ligne apparaît dans
     `public.geofiber_asbuilt_depth_points` (SELECT direct en base).
  2. Rapport avec un `intervention_id` déjà présent → la ligne existante est mise à
     jour, `updated_at` avancé (trigger déjà en place, vérifié au chantier 1).
  3. Une adresse non géocodable → absente de la base, présente uniquement dans la
     sortie `UNGEOCODED`.
  4. Connexion `be` désactivée/absente → `OUTPUT` toujours produit, avertissement
     explicite dans le journal, aucune exception remontée à l'utilisateur.
  5. Après publication : `version=` incrémenté visible dans
     `resource-repo/metadata.ini` servi en HTTP, zip de la collection reconstruit.

## Hors périmètre

- Automatisation complète du chantier 2 esquissée au chantier 1 : lecture des mails
  As-Built (OAuth Microsoft Graph), réponse automatique, classement des mails
  traités. Reste à cadrer séparément si ce besoin est confirmé.
- Toute évolution du schéma de `geofiber_asbuilt_depth_points` (déjà figé au
  chantier 1).
