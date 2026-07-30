# Connexions QGIS `wyre` / `be` — Chantier 1

**Date** : 2026-07-30
**Statut** : proposé
**Périmètre** : plugin `constructel_bridge` (`plugin-repo/packages/constructel_bridge/`)

## Contexte

Le plugin `constructel_bridge` gère aujourd'hui une seule connexion PostgreSQL en
dur, chargée depuis `credentials.json` et enregistrée dans QGIS sous la clé de
settings fixe `PostgreSQL/connections/constructel_bridge` (schémas `infra,osiris`,
schéma par défaut `infra`). Un intercepteur `_BridgeCredentials(QgsCredentials)`
fournit automatiquement le mot de passe pour éviter le dialogue QGIS.

Ce chantier est le préalable à un chantier 2 (hors périmètre de ce document) qui
ajoutera une automatisation de géocodage (rapports As-Built reçus par email,
retraités via le script `geocode_asbuilt_depth` de la collection QGIS Resource
Sharing `resource-repo/collections/asbuilt_depth_geocoder/`, upsertés dans la
nouvelle table publique décrite ci-dessous, avec réponse email automatique). Le
chantier 2 dépend directement de la connexion `be` et de la table créées ici.

## Objectif

1. Renommer la connexion existante (liée à l'opérateur wyre_ftth) en **`wyre`**
   — comportement identique à l'existant, seul le libellé change.
2. Ajouter une seconde connexion nommée **`be`** (bureau d'études), limitée au
   schéma `public`, utilisable en usage mixte : accès QGIS interactif pour une
   personne du bureau d'études ET utilisée comme compte de service par
   l'automatisation du chantier 2. Identifiant Postgres **partagé** (pas de
   compte par personne).
3. Créer la table `public.geofiber_asbuilt_depth_points` qui recevra les points
   géocodés produits par le script de géocodage (chantier 2).

## Design

### Connexions QGIS (`bridge_plugin.py`)

- `_setup_qgis_pg_connection()` est généralisée pour accepter en paramètres :
  clé de connexion, host/port/dbname/user/password/sslmode, liste de schémas,
  schéma par défaut. Elle est appelée deux fois au chargement du plugin :
  - `wyre` : schémas `infra,osiris`, défaut `infra` (= comportement actuel).
  - `be` : schéma `public` uniquement, défaut `public`.
- `_BridgeCredentials` (intercepteur QgsCredentials) est étendu pour fournir le
  bon mot de passe selon la connexion demandée (`wyre` vs `be`).

### `credentials.json`

Passe d'un objet plat à deux blocs nommés :

```json
{
  "wyre": {
    "host": "...", "port": 5432, "dbname": "...", "user": "...",
    "password": "...", "sslmode": "...", "service_name": "...",
    "srid": "...", "email_domain": "constructel.be"
  },
  "be": {
    "host": "...", "port": 5432, "dbname": "...", "user": "...",
    "password": "...", "sslmode": "..."
  }
}
```

Les overrides d'environnement existants `WYRE_DB_HOST` / `WYRE_DB_NAME` sont
conservés pour `wyre`. Des overrides analogues `BE_DB_HOST` / `BE_DB_NAME` sont
ajoutés pour `be`.

**Migration** : les déploiements existants ont un `credentials.json` au format
plat actuel — il faudra le restructurer manuellement (ou via un petit script de
migration) sur chaque poste/serveur au moment du déploiement de cette version.

### Base de données (`wyre_ftth`)

Nouveau rôle Postgres `bureau_etudes` :

```sql
GRANT USAGE ON SCHEMA public TO bureau_etudes;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO bureau_etudes;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE ON TABLES TO bureau_etudes;
```

Aucun accès aux schémas `infra`, `osiris`, `ref`. Un seul identifiant Postgres
partagé (login `bureau_etudes` ou équivalent), pas de compte par personne.

Nouvelle table, colonnes reprises 1:1 des champs déjà produits par
`geocode_asbuilt_depth.py` (`_FIELD_SPECS`), plus deux colonnes d'audit :

```sql
CREATE TABLE public.geofiber_asbuilt_depth_points (
    intervention_id TEXT PRIMARY KEY,
    work_order      TEXT,
    address_raw     TEXT,
    postal_code     TEXT,
    place           TEXT,
    depth_cm        DOUBLE PRECISION,
    depth_category  TEXT,
    geocode_query   TEXT,
    geocode_status  TEXT,
    source_message  TEXT,
    geom            GEOMETRY(Point, 31370),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX geofiber_asbuilt_depth_points_geom_idx
  ON public.geofiber_asbuilt_depth_points USING GIST (geom);
```

`intervention_id` est la clé primaire — c'est déjà la clé unique de
dédoublonnage utilisée par `geocode_asbuilt_depth.py` (`COL_INTERVENTION` /
`dedupe_records()`), ce qui permettra au chantier 2 de faire un simple
`INSERT ... ON CONFLICT (intervention_id) DO UPDATE ...`.

## Compatibilité / risques

- Renommer la connexion `constructel_bridge` → `wyre` change le libellé affiché
  dans le panneau Parcourir / Data Source Manager de QGIS. Les couches déjà
  ajoutées à des projets `.qgz` existants stockent leurs propres paramètres de
  connexion (host/port/dbname) dans l'URI de la couche, pas une simple
  référence au nom de la connexion enregistrée — donc pas de casse attendue sur
  les projets existants. **À vérifier explicitement en test** avant diffusion
  (ouvrir un projet existant après mise à jour du plugin, confirmer que les
  couches se chargent sans reconfiguration).
- Le format de `credentials.json` change (objet à deux blocs au lieu d'un objet
  plat) — nécessite une migration manuelle des fichiers existants sur chaque
  déploiement.

## Testing

- Manuel : après installation du plugin mis à jour, les connexions `wyre` et
  `be` apparaissent toutes les deux dans le panneau Parcourir de QGIS, avec les
  bons schémas visibles/accessibles pour chacune.
- SQL : `\dp public.*` confirme que le rôle `bureau_etudes` a bien accès à
  `public` et n'a aucun grant sur `infra`/`osiris`/`ref`.
- Non-régression : un projet `.qgz` existant utilisant l'ancienne connexion se
  charge sans erreur après le renommage en `wyre`.

## Hors périmètre (chantier 2, à cadrer séparément)

- Authentification OAuth Microsoft Graph (app registration Entra ID à créer
  côté Azure par Simon — hors de portée de l'automatisation).
- Nouvelle action manuelle dans `constructel_bridge` qui : recherche les mails
  non lus avec pièce jointe As-Built dans la boîte dédiée, appelle
  `geocode_asbuilt_depth` (resté dans sa collection Resource Sharing, appelé
  via `processing.run()` — pas de déplacement/duplication de code), upsert le
  résultat dans `public.geofiber_asbuilt_depth_points`, répond « à tous » avec
  un modèle de texte fixe (à rédiger), puis marque le mail lu et le déplace
  dans un dossier « Traités ».
