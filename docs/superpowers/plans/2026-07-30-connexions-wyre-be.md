# Plan d'implémentation — Connexions QGIS `wyre` / `be` (chantier 1)

> **Pour les agents** : sous-skill requis `superpowers:subagent-driven-development` ou `superpowers:executing-plans`.

**Goal** — Faire cohabiter dans le plugin QGIS `constructel_bridge` deux connexions PostgreSQL nommées (`wyre`, comportement actuel inchangé, schémas `infra,osiris` ; `be`, bureau d'études, schéma `public` seul), adossées à un rôle Postgres `bureau_etudes` et à la table `public.geofiber_asbuilt_depth_points` créés par une migration Farois 328.

**Architecture** — Deux dépôts distincts sur le VPS `192.168.160.31` touchent la **même base de production** `farois_ftth` : `~/projects/Farois` en est propriétaire (migrations numérotées `sql/migrations/NNN_*.sql`, dernière appliquée 327) et `~/projects/qgis_repo` héberge le plugin QGIS qui s'y connecte. Le SQL (rôle + table + grants) va donc dans une migration Farois `328`, jamais dans un script ad hoc de `qgis_repo` ; le plugin, lui, se contente de lire un `credentials.json` restructuré en deux blocs et d'enregistrer deux entrées `PostgreSQL/connections/<nom>` dans les settings QGIS. Les deux connexions partageant host **et** base, la discrimination des mots de passe se fait sur le **nom d'utilisateur**, pas sur le realm.

**Tech Stack**
- PostgreSQL 17.5 + PostGIS (conteneur `ftth-postgres`, base `farois_ftth`, SRID 31370)
- Migrations Farois : fichiers `psql` (`\set ON_ERROR_STOP on`, `\echo`), joués par `farois deploy migrate` sous `$DB_USER = ftth_admin`, tracés dans `esb.applied_migrations`
- Tests Farois : `pytest` (`tests/unit/test_migration_NNN_static.py`) — **pytest n'est installé ni sur le VPS ni dans l'image `farois-worker`**, l'exécution locale se fait via le harnais `python3` fourni en tâche A4
- Plugin QGIS : Python 3 / PyQGIS (`QgsSettings`, `QgsCredentials`, `QgsAuthMethodConfig`), QGIS ≥ 3.28, packaging par `release.py` (metadata.txt + plugins.xml + zip)
- Aucun test automatisé côté `qgis_repo` : toutes les vérifications du groupe B sont manuelles et explicitées

## Global Constraints

1. **Identifiant Postgres partagé.** `bureau_etudes` est un compte unique, utilisé à la fois par les personnes du bureau d'études dans QGIS et (chantier 2) par l'automatisation. Pas de compte par personne, pas de dérivation par utilisateur.
2. **Cloisonnement strict.** `bureau_etudes` n'a accès qu'au schéma `public`. Aucun `GRANT` sur `infra`, `osiris`, `ref`, `chantier`, `audit`, `esb`, `staging`. Vérifié en base le 2026-07-30 : ces schémas n'ont pas d'entrée `=U/` dans `nspacl`, donc un nouveau rôle part de zéro — l'invariant tient tant qu'on n'ajoute rien.
3. **Worktree isolée obligatoire pour Farois.** `~/projects/Farois` est un dépôt partagé et très actif (branches créées/mergées/supprimées en minutes). On n'y crée **jamais** de commit depuis le working tree partagé : tout passe par `git worktree`.
4. **Ne jamais merger ni pousser la migration 328 sans validation explicite de Simon.** Le worker Farois rejoue `farois deploy migrate` à chaque boot en mode daemon (`docker/farois-worker/entrypoint.sh`, `run_pending_migrations()`), et il n'existe aucun mécanisme de gate. Le `sql/` étant **baké dans l'image** (aucun bind mount `sql` sur `farois-worker` — vérifié le 2026-07-30), un fichier posé dans le dépôt ne s'applique pas tout seul, mais un `docker compose build` le baquerait et le prochain boot l'appliquerait. La branche reste donc locale jusqu'au GO.
5. **`~/projects/qgis_repo` est le dépôt SERVI en direct.** `docker-compose.yml` monte `./plugin-repo` en lecture seule dans le conteneur `qgis-repo` (port 9080). Ce que consomment les clients QGIS, ce sont `plugin-repo/plugins.xml` et `plugin-repo/packages/constructel_bridge.zip` : **le merge dans `main` de l'arbre servi EST l'acte de publication**. Il est lui aussi soumis au GO de Simon.
6. **Aucun mot de passe dans le SQL versionné.** Convention `sql/00_core/003_roles.sql` : les rôles sont créés sans mot de passe ; celui-ci est posé hors SQL versionné via `scripts/deploy/deploy_roles.sh` et `docker/.env.secrets` (non commité).
7. **Migrations jouées sous `ftth_admin`, jamais sous `postgres`** (`docs/workflow_migrations_sql.md`) : sinon dérive d'ownership et `ALTER DEFAULT PRIVILEGES` posé avec le mauvais grantor.

---

# Groupe A — Migration Farois 328

## Tâche A1 — Worktree Farois isolée

**Files**
- Create: `~/projects/Farois-mig328/` (worktree git, branche `feat/mig328-bureau-etudes`)

**Interfaces**
- Produit pour A2–A6 : le chemin de travail `~/projects/Farois-mig328` et le nom de branche `feat/mig328-bureau-etudes`.

**Steps**

- [ ] Vérifier que le working tree partagé est sur `main` et noter son HEAD (on ne le modifiera pas) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois && git branch --show-current && git log --oneline -1'
  ```
  Résultat attendu : `main` puis un SHA + message. Si la branche courante n'est pas `main`, **STOP** et demander à Simon.

- [ ] Vérifier qu'aucune migration `328*` n'existe déjà (le dépôt est très actif, un autre chantier a pu prendre le numéro) :
  ```bash
  ssh sdadmin@192.168.160.31 'ls ~/projects/Farois/sql/migrations/ | grep -E "^32[89]|^33" || echo "AUCUNE"'
  ```
  Résultat attendu : `AUCUNE`. Sinon, prendre le premier numéro libre et l'utiliser partout dans les tâches A2–A6.

- [ ] Créer la worktree :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois && git worktree add ~/projects/Farois-mig328 -b feat/mig328-bureau-etudes main'
  ```
  Résultat attendu : `Preparing worktree (new branch 'feat/mig328-bureau-etudes')` puis `HEAD is now at <sha> ...`.

- [ ] Confirmer que le working tree partagé n'a pas bougé :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois && git branch --show-current && git status --short | head -5'
  ```
  Résultat attendu : toujours `main`, et la même sortie `git status` qu'avant l'étape 1.

---

## Tâche A2 — Migration forward 328

**Files**
- Create: `~/projects/Farois-mig328/sql/migrations/328_bureau_etudes_asbuilt_depth_points.sql`

**Interfaces**
- Consomme de A1 : la worktree `~/projects/Farois-mig328`.
- Produit pour A3/A4/C : le rôle `bureau_etudes`, la table `public.geofiber_asbuilt_depth_points` (PK `intervention_id`), l'index `idx_geofiber_asbuilt_depth_points_geom_gist`, la fonction `public.fn_geofiber_asbuilt_depth_points_updated_at()` et le trigger `trg_geofiber_asbuilt_depth_points_updated_at`.
- Produit pour B1 (plugin) : le nom d'utilisateur Postgres `bureau_etudes`.

**Steps**

- [ ] Écrire le fichier `~/projects/Farois-mig328/sql/migrations/328_bureau_etudes_asbuilt_depth_points.sql` avec exactement ce contenu :

```sql
-- ============================================================================
-- migrations/328_bureau_etudes_asbuilt_depth_points.sql
-- ============================================================================
-- Date: 2026-07-30
-- Auteur: Simon (chantier 1 - connexions QGIS wyre/be)
--
-- NE PAS DEPLOYER SANS VALIDATION EXPLICITE DE SIMON.
--   Cette migration cree un ROLE de connexion PostgreSQL. Elle doit etre
--   appliquee au moment choisi par Simon, conjointement a la pose du mot de
--   passe partage (scripts/deploy/deploy_roles.sh, variable
--   BUREAU_ETUDES_PASSWORD) : un role LOGIN sans mot de passe ne peut pas
--   s'authentifier sous scram-sha-256 et la connexion QGIS `be` echouerait.
--
-- CONTEXTE (chantier 1 ; spec dans le depot qgis_repo :
--   docs/superpowers/specs/2026-07-30-connexions-wyre-be-design.md) :
--   Le plugin QGIS `constructel_bridge` passe d'une a deux connexions
--   PostgreSQL : `wyre` (existant, schemas infra+osiris, role ftth_editor) et
--   `be` (bureau d'etudes, schema public uniquement, identifiant PARTAGE).
--   Cette migration cree cote base les deux objets dont `be` a besoin :
--     - le role de connexion `bureau_etudes` ;
--     - la table public.geofiber_asbuilt_depth_points, destinee aux points
--       geocodes produits par le script Processing `geocode_asbuilt_depth`
--       (chantier 2, hors perimetre ici).
--
-- SCOPE :
--   1. Role `bureau_etudes` (LOGIN, sans mot de passe - cf. 00_core/003_roles.sql)
--   2. Table public.geofiber_asbuilt_depth_points + index GIST + trigger
--      updated_at (modele : sql/10_tables/015_map_themes.sql - meme schema
--      public, meme consommateur : le plugin QGIS)
--   3. Droits de `bureau_etudes` : USAGE sur public + SELECT/INSERT/UPDATE sur
--      les tables de public, ET RIEN D'AUTRE.
--
-- INVARIANT DE SECURITE : `bureau_etudes` ne doit avoir AUCUN acces a
--   infra / osiris / ref / chantier / audit / esb / staging. Aucun GRANT n'est
--   emis sur ces schemas, et PUBLIC n'y a pas USAGE (verifie en base le
--   2026-07-30 : nspacl sans entree `=U/`), donc le role part de zero. La
--   verification est jouee en fin de fichier, hors transaction.
--
-- NOTE D'EXECUTION : le runner (`farois deploy migrate`) joue psql sous
--   $DB_USER = ftth_admin, proprietaire de la base donc du schema public (via
--   pg_database_owner). Consequence ATTENDUE et sans impact :
--   `GRANT ... ON ALL TABLES IN SCHEMA public` emet
--     WARNING:  no privileges were granted for "spatial_ref_sys"
--   (idem geometry_columns, geography_columns, v_layer_styles_summary), qui
--   appartiennent a `postgres`. Ces objets PostGIS sont deja lisibles par
--   PUBLIC (`=r/postgres`), donc QGIS peut parcourir la connexion `be` sans
--   eux. NE PAS "corriger" en rejouant sous postgres : cf.
--   docs/workflow_migrations_sql.md (derive d'ownership).
--
-- ROLLBACK : 328r_rollback_bureau_etudes_asbuilt_depth_points.sql
--   (a jouer sous le MEME role ftth_admin : le REVOKE des default privileges
--   ne vise que le grantor courant).
-- ============================================================================

\set ON_ERROR_STOP on

\echo ''
\echo '=========================================================================='
\echo '   328 - Role bureau_etudes + public.geofiber_asbuilt_depth_points'
\echo '=========================================================================='
\echo ''

BEGIN;

-- ── 1. Role de connexion du bureau d'etudes ────────────────────────────────
-- Meme pattern que sql/00_core/003_roles.sql : le role est cree SANS mot de
-- passe, celui-ci est pose hors SQL versionne (deploy_roles.sh).

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bureau_etudes') THEN
        CREATE ROLE bureau_etudes WITH
            LOGIN
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            INHERIT
            CONNECTION LIMIT 20;
        -- COMMENT ON ROLE exige CREATEROLE *et* ADMIN OPTION sur le role : on
        -- ne le pose que dans la branche ou c'est nous qui venons de le creer.
        -- Si le role preexiste (cree sous postgres par deploy_roles.sh),
        -- ftth_admin n'a pas ADMIN OPTION et un COMMENT inconditionnel
        -- avorterait la migration.
        COMMENT ON ROLE bureau_etudes IS 'Bureau d''etudes - identifiant PARTAGE (pas de compte par personne). Connexion QGIS `be` du plugin constructel_bridge + compte de service de l''automatisation As-Built (chantier 2). Schema public uniquement.';
        RAISE NOTICE '✓ Rôle bureau_etudes créé';
    ELSE
        RAISE NOTICE '○ Rôle bureau_etudes existe déjà';
    END IF;
END $$;

\echo '  role bureau_etudes en place (mot de passe : deploy_roles.sh)'

-- ── 2. Table des points de profondeur As-Built ─────────────────────────────
-- Colonnes 1:1 avec _FIELD_SPECS de
--   resource-repo/collections/asbuilt_depth_geocoder/processing/geocode_asbuilt_depth.py
-- (depot qgis_repo), plus 2 colonnes d'audit. PK = intervention_id : c'est
-- deja la cle de dedoublonnage du script (COL_INTERVENTION / dedupe_records()),
-- ce qui permettra au chantier 2 un simple
--   INSERT ... ON CONFLICT (intervention_id) DO UPDATE.

CREATE TABLE IF NOT EXISTS public.geofiber_asbuilt_depth_points (
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
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.geofiber_asbuilt_depth_points IS
    'Points de profondeur As-Built geocodes (rapports GeoFiber). Alimentee par le script Processing geocode_asbuilt_depth via l''automatisation du chantier 2, consultee dans QGIS via la connexion `be`. Cle de dedoublonnage = intervention_id.';

COMMENT ON COLUMN public.geofiber_asbuilt_depth_points.intervention_id IS
    'Identifiant d''intervention du rapport As-Built - cle de dedoublonnage (upsert ON CONFLICT).';
COMMENT ON COLUMN public.geofiber_asbuilt_depth_points.depth_cm IS
    'Profondeur relevee en centimetres. NULL si non parsable dans le rapport source.';
COMMENT ON COLUMN public.geofiber_asbuilt_depth_points.depth_category IS
    'Categorie de profondeur calculee par geocode_asbuilt_depth (seuils configurables cote script).';
COMMENT ON COLUMN public.geofiber_asbuilt_depth_points.geocode_status IS
    'Statut du geocodage Nominatim pour cette ligne.';
COMMENT ON COLUMN public.geofiber_asbuilt_depth_points.source_message IS
    'Reference du message .msg d''origine (tracabilite du rapport recu par email).';
COMMENT ON COLUMN public.geofiber_asbuilt_depth_points.geom IS
    'Point geocode en Lambert 72 (EPSG:31370). NULL si le geocodage a echoue.';

CREATE INDEX IF NOT EXISTS idx_geofiber_asbuilt_depth_points_geom_gist
    ON public.geofiber_asbuilt_depth_points USING GIST (geom);

-- Trigger updated_at (meme pattern que public.fn_map_themes_updated_at)
CREATE OR REPLACE FUNCTION public.fn_geofiber_asbuilt_depth_points_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_geofiber_asbuilt_depth_points_updated_at
    ON public.geofiber_asbuilt_depth_points;
CREATE TRIGGER trg_geofiber_asbuilt_depth_points_updated_at
    BEFORE UPDATE ON public.geofiber_asbuilt_depth_points
    FOR EACH ROW
    EXECUTE FUNCTION public.fn_geofiber_asbuilt_depth_points_updated_at();

-- Ownership explicite (cf. 015_map_themes.sql) : garantit que les migrations
-- suivantes, jouees sous ftth_admin, pourront ALTER/DROP ces objets meme si
-- ce fichier a ete rejoue a la main sous un autre role.
ALTER TABLE public.geofiber_asbuilt_depth_points OWNER TO ftth_admin;
ALTER FUNCTION public.fn_geofiber_asbuilt_depth_points_updated_at() OWNER TO ftth_admin;

\echo '  + public.geofiber_asbuilt_depth_points (PK intervention_id, GIST geom)'

-- ── 3. Droits du bureau d'etudes - schema public UNIQUEMENT ────────────────
-- Aucun GRANT sur infra/osiris/ref/chantier/audit/esb/staging : c'est
-- l'invariant de securite de ce chantier (cf. en-tete).
-- L'ordre compte : le GRANT ON ALL TABLES est emis APRES le CREATE TABLE
-- ci-dessus, il couvre donc la nouvelle table dans la meme transaction.

GRANT USAGE ON SCHEMA public TO bureau_etudes;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO bureau_etudes;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE ON TABLES TO bureau_etudes;

\echo '  droits bureau_etudes poses sur public (aucun sur infra/osiris/ref)'

COMMIT;

-- ── Verification (hors transaction) ────────────────────────────────────────

\echo ''
\echo 'Acces de bureau_etudes par schema (attendu : public=t, tous les autres=f) :'
SELECT n.nspname AS schema,
       has_schema_privilege('bureau_etudes', n.nspname, 'USAGE') AS usage
FROM pg_namespace n
WHERE n.nspname IN ('public','infra','osiris','ref','chantier','audit','esb','staging')
ORDER BY 1;

\echo ''
\echo 'Droits sur public.geofiber_asbuilt_depth_points (attendu : t | t | t | f) :'
SELECT has_table_privilege('bureau_etudes','public.geofiber_asbuilt_depth_points','SELECT') AS sel,
       has_table_privilege('bureau_etudes','public.geofiber_asbuilt_depth_points','INSERT') AS ins,
       has_table_privilege('bureau_etudes','public.geofiber_asbuilt_depth_points','UPDATE') AS upd,
       has_table_privilege('bureau_etudes','public.geofiber_asbuilt_depth_points','DELETE') AS del;

\echo ''
\echo '=== [mig 328] termine ==='
```

- [ ] Vérifier que le fichier est bien du SQL syntaxiquement parsable sans le jouer (les `\echo`/`\set` sont des méta-commandes psql, on ne peut pas utiliser `psql -c`), en contrôlant l'équilibre des blocs :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-mig328 && grep -c "^BEGIN;" sql/migrations/328_bureau_etudes_asbuilt_depth_points.sql && grep -c "^COMMIT;" sql/migrations/328_bureau_etudes_asbuilt_depth_points.sql && grep -c "\$\$" sql/migrations/328_bureau_etudes_asbuilt_depth_points.sql'
  ```
  Résultat attendu : `1`, `1`, `4` (deux paires `$$` : le DO block du rôle et la fonction trigger).

- [ ] Commiter dans la worktree (**sans push**) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-mig328 && git add sql/migrations/328_bureau_etudes_asbuilt_depth_points.sql && git commit -m "feat(sql): mig 328 - role bureau_etudes + public.geofiber_asbuilt_depth_points"'
  ```
  Résultat attendu : `1 file changed, ... insertions(+)`.

---

## Tâche A3 — Rollback 328r

**Files**
- Create: `~/projects/Farois-mig328/sql/migrations/328r_rollback_bureau_etudes_asbuilt_depth_points.sql`

**Interfaces**
- Consomme de A2 : les noms exacts `bureau_etudes`, `public.geofiber_asbuilt_depth_points`, `public.fn_geofiber_asbuilt_depth_points_updated_at()`, `trg_geofiber_asbuilt_depth_points_updated_at`.

**Steps**

- [ ] Écrire le fichier `~/projects/Farois-mig328/sql/migrations/328r_rollback_bureau_etudes_asbuilt_depth_points.sql` avec exactement ce contenu :

```sql
-- ============================================================================
-- migrations/328r_rollback_bureau_etudes_asbuilt_depth_points.sql
-- ============================================================================
-- Rollback de 328_bureau_etudes_asbuilt_depth_points.sql.
--
-- DESTRUCTIF : DROP TABLE public.geofiber_asbuilt_depth_points supprime les
--   points As-Built deja geocodes. Si la table contient des donnees, dumper
--   avant :
--     docker exec ftth-postgres pg_dump -U ftth_admin -d farois_ftth \
--       -t public.geofiber_asbuilt_depth_points > /tmp/asbuilt_before_rollback.sql
--
-- A JOUER SOUS ftth_admin, comme le forward. `ALTER DEFAULT PRIVILEGES ...
--   REVOKE` ne vise que les default privileges du role COURANT : joue sous
--   postgres, il ne retirerait pas ceux poses par ftth_admin et le DROP ROLE
--   echouerait ("cannot be dropped because some objects depend on it :
--   privileges for default privileges on new relations ...").
--
-- Ordre obligatoire : trigger + table + fonction AVANT le retrait des droits,
--   puis DROP OWNED BY (balaie les privileges residuels du role dans cette
--   base) et enfin DROP ROLE - un role ne peut pas etre supprime tant qu'il
--   detient des privileges.
-- ============================================================================

\set ON_ERROR_STOP on

\echo ''
\echo '=== [rollback 328] Role bureau_etudes + geofiber_asbuilt_depth_points ==='

BEGIN;

DROP TRIGGER IF EXISTS trg_geofiber_asbuilt_depth_points_updated_at
    ON public.geofiber_asbuilt_depth_points;
DROP TABLE IF EXISTS public.geofiber_asbuilt_depth_points;
DROP FUNCTION IF EXISTS public.fn_geofiber_asbuilt_depth_points_updated_at();

\echo '  table (index inclus), trigger et fonction updated_at supprimes'

-- EXECUTE plutot que des instructions directes : meme idiome que
-- sql/80_security/080_security_hardening.sql, et cela evite toute question de
-- parsing plpgsql sur ALTER DEFAULT PRIVILEGES / DROP OWNED BY.
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'bureau_etudes') THEN
        EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
             || 'REVOKE SELECT, INSERT, UPDATE ON TABLES FROM bureau_etudes';
        -- DROP OWNED BY revoque tous les privileges du role dans la base
        -- courante. bureau_etudes ne possede aucun objet (la table appartient
        -- a ftth_admin), rien de metier n'est donc supprime ici.
        EXECUTE 'DROP OWNED BY bureau_etudes';
        EXECUTE 'DROP ROLE bureau_etudes';
        RAISE NOTICE '✓ Rôle bureau_etudes supprimé';
    ELSE
        RAISE NOTICE '○ Rôle bureau_etudes absent';
    END IF;
END $$;

\echo '  role bureau_etudes et ses droits supprimes'

COMMIT;

\echo '=== [rollback 328] termine ==='
```

- [ ] Vérifier l'équilibre des blocs :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-mig328 && grep -c "^BEGIN;" sql/migrations/328r_rollback_bureau_etudes_asbuilt_depth_points.sql && grep -c "^COMMIT;" sql/migrations/328r_rollback_bureau_etudes_asbuilt_depth_points.sql'
  ```
  Résultat attendu : `1` et `1`.

- [ ] Vérifier que le rollback ne sera **pas** ramassé par le runner (le regex forward est `^\d+_`, `328r_` ne matche pas) :
  ```bash
  ssh sdadmin@192.168.160.31 'python3 -c "import re; print(bool(re.compile(r\"^\d+_\").match(\"328r_rollback_bureau_etudes_asbuilt_depth_points.sql\")), bool(re.compile(r\"^\d+_\").match(\"328_bureau_etudes_asbuilt_depth_points.sql\")))"'
  ```
  Résultat attendu : `False True`.

- [ ] Commiter (**sans push**) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-mig328 && git add sql/migrations/328r_rollback_bureau_etudes_asbuilt_depth_points.sql && git commit -m "feat(sql): mig 328r - rollback role bureau_etudes + table asbuilt"'
  ```
  Résultat attendu : `1 file changed, ... insertions(+)`.

---

## Tâche A4 — Test statique de la migration 328

**Files**
- Create: `~/projects/Farois-mig328/tests/unit/test_migration_328_static.py`
- Test: ce fichier EST le test (convention `tests/unit/test_migration_NNN_static.py`, cf. `test_migration_295_static.py`)

**Interfaces**
- Consomme de A2/A3 : les chemins `sql/migrations/328_bureau_etudes_asbuilt_depth_points.sql` et `sql/migrations/328r_rollback_bureau_etudes_asbuilt_depth_points.sql`, le nom de migration `328_bureau_etudes_asbuilt_depth_points`.

**Steps**

- [ ] Écrire `~/projects/Farois-mig328/tests/unit/test_migration_328_static.py` avec exactement ce contenu :

```python
"""Tests statiques pour la migration 328 (role bureau_etudes + table As-Built).

CONTEXTE :
  Chantier 1 "connexions QGIS wyre/be" : le plugin constructel_bridge ajoute
  une connexion `be` (bureau d'etudes) limitee au schema public. La migration
  328 cree cote base le role de connexion `bureau_etudes` et la table
  public.geofiber_asbuilt_depth_points destinee au geocodage As-Built.

Verifications statiques (sans Docker, sans base) :
- Les 2 fichiers 328 (migration + rollback) existent.
- Avertissement explicite "ne pas deployer sans validation Simon" en tete.
- INVARIANT DE SECURITE : aucun GRANT vers bureau_etudes sur un schema autre
  que public.
- Aucun mot de passe en dur (le role est cree sans PASSWORD, cf. 003_roles.sql).
- Idempotence : garde pg_roles pour le role, IF NOT EXISTS pour table et index.
- Le forward est transactionnel (BEGIN/COMMIT) et n'insere pas lui-meme dans
  esb.applied_migrations (convention runner).
- Le rollback est REEL (drop table + drop role), pas un no-op, et retire les
  default privileges avant DROP ROLE.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = ROOT / "sql" / "migrations"
MIGRATION_PATH = MIGRATIONS_DIR / "328_bureau_etudes_asbuilt_depth_points.sql"
ROLLBACK_PATH = MIGRATIONS_DIR / "328r_rollback_bureau_etudes_asbuilt_depth_points.sql"

MIGRATION_NAME = "328_bureau_etudes_asbuilt_depth_points"

FORBIDDEN_SCHEMAS = ("infra", "osiris", "ref", "chantier", "audit", "esb", "staging")


def _read(path: pathlib.Path) -> str:
    assert path.exists(), f"Fichier introuvable : {path}"
    return path.read_text(encoding="utf-8")


def _strip_sql_comments(text: str) -> str:
    lines = [re.sub(r"--.*$", "", ln) for ln in text.splitlines()]
    return "\n".join(lines)


# ─── Existence ──────────────────────────────────────────────────────────


def test_files_exist():
    assert MIGRATION_PATH.exists(), f"Migration manquante : {MIGRATION_PATH}"
    assert ROLLBACK_PATH.exists(), f"Rollback manquant : {ROLLBACK_PATH}"


# ─── Garde-fou humain : ne pas deployer sans Simon ──────────────────────


def test_warns_manual_validation_required():
    content = _read(MIGRATION_PATH)
    assert "NE PAS DEPLOYER SANS VALIDATION" in content.upper(), (
        "Avertissement explicite d'execution sur validation Simon attendu en tete"
    )


# ─── Invariant de securite : public et rien d'autre ─────────────────────


def test_no_grant_to_bureau_etudes_outside_public():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    for statement in re.findall(r"GRANT[^;]*;", sql, flags=re.IGNORECASE | re.DOTALL):
        if "bureau_etudes" not in statement:
            continue
        for schema in FORBIDDEN_SCHEMAS:
            assert not re.search(rf"\b{schema}\b", statement, flags=re.IGNORECASE), (
                f"GRANT vers bureau_etudes touchant le schema interdit '{schema}' :\n{statement}"
            )


def test_migration_checks_schema_isolation():
    content = _read(MIGRATION_PATH)
    assert "has_schema_privilege('bureau_etudes'" in content, (
        "La migration doit verifier en fin de fichier l'isolation du role"
    )


# ─── Pas de secret en dur ───────────────────────────────────────────────


def test_role_created_without_password():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    assert re.search(r"CREATE\s+ROLE\s+bureau_etudes", sql, flags=re.IGNORECASE), (
        "CREATE ROLE bureau_etudes attendu"
    )
    assert not re.search(r"PASSWORD", sql, flags=re.IGNORECASE), (
        "Aucun mot de passe ne doit figurer dans le SQL versionne "
        "(convention 00_core/003_roles.sql + deploy_roles.sh)"
    )


# ─── Idempotence ────────────────────────────────────────────────────────


def test_role_creation_is_idempotent():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    assert "NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bureau_etudes')" in sql, (
        "Garde pg_roles attendue avant CREATE ROLE (pattern 003_roles.sql)"
    )


def test_table_and_index_are_idempotent():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    assert "CREATE TABLE IF NOT EXISTS public.geofiber_asbuilt_depth_points" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_geofiber_asbuilt_depth_points_geom_gist" in sql
    assert "CREATE OR REPLACE FUNCTION public.fn_geofiber_asbuilt_depth_points_updated_at" in sql
    assert "DROP TRIGGER IF EXISTS trg_geofiber_asbuilt_depth_points_updated_at" in sql


# ─── Conventions du runner ──────────────────────────────────────────────


def test_forward_is_transactional():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    assert re.search(r"^BEGIN;", sql, flags=re.MULTILINE), "BEGIN; attendu"
    assert re.search(r"^COMMIT;", sql, flags=re.MULTILINE), "COMMIT; attendu"


def test_no_self_insert_into_applied_migrations():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    assert "applied_migrations" not in sql, (
        "Le tracking est fait par le runner (farois deploy migrate), "
        "pas par la migration elle-meme"
    )


# ─── Rollback reel ──────────────────────────────────────────────────────


def test_rollback_is_not_a_noop():
    sql = _strip_sql_comments(_read(ROLLBACK_PATH))
    assert "DROP TABLE IF EXISTS public.geofiber_asbuilt_depth_points" in sql
    assert "DROP ROLE bureau_etudes" in sql


def test_rollback_revokes_default_privileges_before_drop_role():
    sql = _strip_sql_comments(_read(ROLLBACK_PATH))
    revoke_pos = sql.find("ALTER DEFAULT PRIVILEGES")
    drop_pos = sql.find("DROP ROLE bureau_etudes")
    assert revoke_pos != -1, "ALTER DEFAULT PRIVILEGES ... REVOKE attendu dans le rollback"
    assert drop_pos != -1, "DROP ROLE bureau_etudes attendu dans le rollback"
    assert revoke_pos < drop_pos, (
        "Les default privileges doivent etre retires AVANT le DROP ROLE, "
        "sinon PostgreSQL refuse la suppression du role"
    )
```

- [ ] Exécuter le test. **`pytest` n'est disponible ni sur le VPS ni dans l'image `farois-worker`** (vérifié : `No module named pytest`) : utiliser ce harnais `python3` qui exécute les mêmes fonctions :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-mig328 && python3 - <<PY
import importlib.util, sys
spec = importlib.util.spec_from_file_location("t328", "tests/unit/test_migration_328_static.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
fails = []
for name in sorted(n for n in dir(mod) if n.startswith("test_")):
    try:
        getattr(mod, name)()
        print("PASS", name)
    except AssertionError as exc:
        fails.append(name)
        print("FAIL", name, "->", exc)
print("---", len(fails), "echec(s)")
sys.exit(1 if fails else 0)
PY'
  ```
  Résultat attendu : 12 lignes `PASS`, puis `--- 0 echec(s)`, code de sortie 0.

- [ ] Commiter (**sans push**) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-mig328 && git add tests/unit/test_migration_328_static.py && git commit -m "test(sql): tests statiques migration 328 (isolation bureau_etudes, idempotence, rollback)"'
  ```
  Résultat attendu : `1 file changed, ... insertions(+)`.

---

## Tâche A5 — Mot de passe partagé `bureau_etudes`

**Files**
- Modify: `~/projects/Farois-mig328/scripts/deploy/deploy_roles.sh` (bloc d'aide `--help` ~ligne 74-80 ; liste `_deploy_role_password` ~ligne 222-233)
- Modify (NON commité, sur le VPS seulement) : `~/projects/Farois/docker/.env.secrets`

**Interfaces**
- Consomme de A2 : le nom de rôle `bureau_etudes`.
- Produit pour B1 et C : la variable `BUREAU_ETUDES_PASSWORD` dans `docker/.env.secrets`, et sa forme base64 à injecter dans `credentials.json`.

**Steps**

- [ ] Dans `~/projects/Farois-mig328/scripts/deploy/deploy_roles.sh`, ajouter la ligne d'aide juste après celle de `FTTH_BACKUP_PASSWORD` :
  ```bash
            echo "  FTTH_BACKUP_PASSWORD  Mot de passe pour ftth_backup (optionnel)"
            echo "  BUREAU_ETUDES_PASSWORD Mot de passe pour bureau_etudes (optionnel)"
  ```

- [ ] Dans le même fichier, ajouter l'appel après celui de `ftth_backup` :
  ```bash
  _deploy_role_password "ftth_backup"   "${FTTH_BACKUP_PASSWORD:-}" \
      "NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT CONNECTION LIMIT 5"
  # Bureau d'etudes (chantier 1) : identifiant PARTAGE, schema public seulement.
  # Le role lui-meme est cree par la migration 328 ; cette ligne ne sert qu'a
  # poser/renouveler son mot de passe, comme pour les roles ftth_*.
  _deploy_role_password "bureau_etudes" "${BUREAU_ETUDES_PASSWORD:-}" \
      "NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT CONNECTION LIMIT 20"
  ```

- [ ] Vérifier que le script reste syntaxiquement valide :
  ```bash
  ssh sdadmin@192.168.160.31 'bash -n ~/projects/Farois-mig328/scripts/deploy/deploy_roles.sh && echo "SYNTAXE OK"'
  ```
  Résultat attendu : `SYNTAXE OK`.

- [ ] Commiter (**sans push**) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-mig328 && git add scripts/deploy/deploy_roles.sh && git commit -m "chore(deploy): BUREAU_ETUDES_PASSWORD dans deploy_roles.sh (chantier 1)"'
  ```
  Résultat attendu : `1 file changed, 6 insertions(+)`.

- [ ] Générer le mot de passe partagé et l'écrire dans `docker/.env.secrets` du dépôt **partagé** (fichier non versionné, donc édité là où la stack le lit) :
  ```bash
  ssh sdadmin@192.168.160.31 'PW=$(openssl rand -base64 24 | tr -d "/+=" | cut -c1-24); printf "BUREAU_ETUDES_PASSWORD=%s\n" "$PW" >> ~/projects/Farois/docker/.env.secrets; echo "ecrit"'
  ```
  Résultat attendu : `ecrit`.

- [ ] Vérifier que la variable est lisible et récupérer sa forme base64 (valeur à reporter en B1 dans `credentials.json`) :
  ```bash
  ssh sdadmin@192.168.160.31 'set -a; . ~/projects/Farois/docker/.env.secrets; set +a; printf "%s" "$BUREAU_ETUDES_PASSWORD" | base64 -w0; echo'
  ```
  Résultat attendu : une chaîne base64 d'environ 32 caractères. **La noter, elle est l'entrée de la tâche B1.**

---

## Tâche A6 — Point de contrôle : prêt, non poussé, non déployé

**Files**
- Aucun (tâche de vérification et de gate)

**Interfaces**
- Consomme de A2–A5 : les 4 commits de la branche `feat/mig328-bureau-etudes`.
- Produit pour C : l'autorisation explicite de Simon d'appliquer la migration en production.

**Steps**

- [ ] Vérifier que la branche contient bien les 4 commits attendus et **n'a aucun upstream** :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-mig328 && git log --oneline main..HEAD && echo "--- upstream ---" && (git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>&1 || true)'
  ```
  Résultat attendu : 4 lignes de commits, puis `fatal: no upstream configured for branch 'feat/mig328-bureau-etudes'`.

- [ ] Vérifier que le working tree partagé `~/projects/Farois` est intact (aucun fichier `328*` visible, branche inchangée) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois && git branch --show-current && ls sql/migrations/ | grep -c "^328" || echo 0'
  ```
  Résultat attendu : `main` puis `0`.

- [ ] Vérifier qu'aucun rebuild d'image n'a été déclenché entre-temps (l'image du worker ne doit pas contenir de migration 328) :
  ```bash
  ssh sdadmin@192.168.160.31 'docker exec farois-worker ls /opt/farois/sql/migrations/ | grep -c "^328" || echo 0'
  ```
  Résultat attendu : `0`.

- [ ] **GATE — arrêt obligatoire.** Présenter à Simon : le diff des 4 commits, le résultat du test statique A4, et la note d'exécution (`WARNING: no privileges were granted for "spatial_ref_sys"` attendu). Ne pas pousser la branche, ne pas la merger, ne pas rebuilder l'image `farois-worker`. Attendre un GO explicite avant la tâche C.
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-mig328 && git diff main..HEAD --stat'
  ```
  Résultat attendu : 4 fichiers (`sql/migrations/328_*.sql`, `sql/migrations/328r_*.sql`, `tests/unit/test_migration_328_static.py`, `scripts/deploy/deploy_roles.sh`).

---

# Groupe B — Plugin `constructel_bridge` (qgis_repo)

## Tâche B0 — Point de contrôle amont + worktree qgis_repo

**Files**
- Create: `~/projects/qgis_repo-chantier1/` (worktree git, branche `feat/connexions-wyre-be`)

**Interfaces**
- Produit pour B1–B6 : le chemin de travail `~/projects/qgis_repo-chantier1` et le chemin plugin `~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge/`.

**Steps**

- [ ] Vérifier l'état du diff en cours de Simon sur le plugin :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo && git status --short plugin-repo/'
  ```
  État connu au 2026-07-30 : `M plugin-repo/packages/constructel_bridge/bridge_plugin.py`, `M .../metadata.txt`, `M plugin-repo/packages/constructel_bridge.zip`, `M plugin-repo/plugins.xml` — c'est le travail v1.4.10 de Simon (pré-provisionnement pip `extract-msg`, méthodes `_resolve_python_executable` / `_ensure_extract_msg_available`).

- [ ] **GATE — arrêt obligatoire si la sortie ci-dessus n'est pas vide.** Ce chantier réécrit les mêmes zones de `bridge_plugin.py` ; une worktree partirait de `main` et perdrait le travail v1.4.10 au moment du merge. Demander à Simon de commiter son diff (l'entrée de changelog v1.4.10 est déjà rédigée dans `metadata.txt`, c'est une unité cohérente et livrable). Ne rien commiter ni stasher à sa place.

- [ ] Une fois le commit de Simon fait, re-vérifier et noter le HEAD de `main` :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo && git status --short plugin-repo/ && echo "--- head ---" && git log --oneline -1'
  ```
  Résultat attendu : aucune ligne pour `plugin-repo/`, puis le SHA du commit v1.4.10.

- [ ] Créer la worktree isolée (l'arbre servi sur `:9080` ne doit pas bouger pendant le développement) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo && git worktree add ~/projects/qgis_repo-chantier1 -b feat/connexions-wyre-be main'
  ```
  Résultat attendu : `Preparing worktree (new branch 'feat/connexions-wyre-be')` puis `HEAD is now at <sha> ...`.

- [ ] Vérifier que la version de départ est bien 1.4.10 et que les méthodes v1.4.10 de Simon sont présentes dans la worktree :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge && grep -n "^version=" metadata.txt && grep -c "_ensure_extract_msg_available" bridge_plugin.py'
  ```
  Résultat attendu : `version=1.4.10` et un compte ≥ 2.

- [ ] Relever les numéros de ligne réels dans la worktree (toutes les tâches suivantes s'y réfèrent) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge && grep -n "^TAG = \|^AUTH_CFG_NAME\|^_CREDENTIALS_PATH\|^def _load_credentials\|^_CREDS\|^DEFAULT_\|^_DEFAULT_PW\|^PG_SERVICE_NAME\|^EMAIL_DOMAIN\|^LANG_LABELS\|^class _BridgeCredentials\|^def _precache_pg_credentials\|^def _store_password_encrypted\|^def _retrieve_password_encrypted\|^def _remove_stored_password\|_precache_pg_credentials()\|def _setup_qgis_pg_connection" bridge_plugin.py'
  ```
  Résultat attendu (valeurs de référence relevées au 2026-07-30 sur le fichier avec le diff v1.4.10) : `TAG`=46, `AUTH_CFG_NAME`=47, `_CREDENTIALS_PATH`=52, `_load_credentials`=54, `_CREDS`=60, `DEFAULT_HOST`=62 → `EMAIL_DOMAIN`=70, `LANG_LABELS`=72, `_BridgeCredentials`=79, `_precache_pg_credentials`=133, `_store_password_encrypted`=167, `_retrieve_password_encrypted`=201, `_remove_stored_password`=222, appel `_precache_pg_credentials()`=382, `_setup_qgis_pg_connection`=988.

---

## Tâche B1 — `credentials.json` à deux blocs + constantes `BE_*`

**Files**
- Modify: `~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge/credentials.json` (fichier entier)
- Modify: `~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge/bridge_plugin.py` (lignes 52-70)

**Interfaces**
- Consomme de A5 : la forme base64 du mot de passe `bureau_etudes`.
- Consomme de A2 : le nom d'utilisateur `bureau_etudes`.
- Produit pour B2/B3/B4/B5 : les constantes module-level `BE_HOST`, `BE_PORT`, `BE_DBNAME`, `BE_USER`, `_BE_PW`, `BE_SSLMODE`, `BE_ENABLED`, et les dicts internes `_WYRE_CREDS` / `_BE_CREDS`. Les constantes `DEFAULT_*`, `_DEFAULT_PW`, `DEFAULT_SRID`, `DEFAULT_SSLMODE`, `PG_SERVICE_NAME`, `EMAIL_DOMAIN` gardent leurs noms et leurs valeurs.

**Steps**

- [ ] Récupérer la valeur base64 actuelle du mot de passe `wyre` (à recopier telle quelle, elle ne change pas) :
  ```bash
  ssh sdadmin@192.168.160.31 'python3 -c "import json;print(json.load(open(\"/home/sdadmin/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge/credentials.json\"))[\"password\"])"'
  ```
  Résultat attendu : une chaîne base64.

- [ ] Remplacer intégralement `credentials.json` par ce contenu, en substituant `<B64_WYRE>` par la valeur ci-dessus et `<B64_BE>` par la valeur produite en A5 :
  ```json
  {
      "wyre": {
          "host": "192.168.160.31",
          "port": 5432,
          "dbname": "farois_ftth",
          "user": "ftth_editor",
          "password": "<B64_WYRE>",
          "sslmode": "require",
          "srid": 31370,
          "service_name": "constructel_bridge",
          "email_domain": "constructel.be"
      },
      "be": {
          "host": "192.168.160.31",
          "port": 5432,
          "dbname": "farois_ftth",
          "user": "bureau_etudes",
          "password": "<B64_BE>",
          "sslmode": "require"
      }
  }
  ```

- [ ] Dans `bridge_plugin.py`, remplacer le bloc des lignes 52 à 70 (de `_CREDENTIALS_PATH = ...` jusqu'à `EMAIL_DOMAIN = ...` inclus) par :

```python
_CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")

def _load_credentials() -> dict:
    """Load connection parameters from credentials.json.

    Format attendu depuis la v1.5.0 : un objet par connexion,
    {"wyre": {...}, "be": {...}}. Les deploiements anterieurs ont un objet
    PLAT (host/port/... a la racine) : on le rattache alors a "wyre" et on
    laisse "be" vide, plutot que de lever une KeyError a l'import du module
    — ce qui empecherait le plugin de se charger DU TOUT, `wyre` compris.
    """
    import json
    with open(_CREDENTIALS_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    if "host" in raw:
        return {"wyre": raw, "be": {}}
    return raw

_CREDS = _load_credentials()
_WYRE_CREDS = _CREDS.get("wyre", {})
_BE_CREDS = _CREDS.get("be", {})

DEFAULT_HOST = os.getenv("WYRE_DB_HOST", "") or _WYRE_CREDS["host"]
DEFAULT_PORT = int(os.getenv("WYRE_DB_PORT", str(_WYRE_CREDS["port"])))
DEFAULT_DBNAME = os.getenv("WYRE_DB_NAME", "") or _WYRE_CREDS["dbname"]
DEFAULT_USER = _WYRE_CREDS["user"]
_DEFAULT_PW = base64.b64decode(_WYRE_CREDS["password"]).decode()
DEFAULT_SRID = _WYRE_CREDS.get("srid", 31370)
DEFAULT_SSLMODE = _WYRE_CREDS.get("sslmode", "require")
PG_SERVICE_NAME = _WYRE_CREDS.get("service_name", "constructel_bridge")
EMAIL_DOMAIN = _WYRE_CREDS.get("email_domain", "constructel.be")

# Connexion `be` (bureau d'etudes) — schema public uniquement, identifiant
# PostgreSQL PARTAGE (pas de compte par personne). Absente des
# credentials.json anterieurs a la v1.5.0 : toutes les constantes retombent
# alors sur des valeurs vides et BE_ENABLED est False.
BE_HOST = os.getenv("BE_DB_HOST", "") or _BE_CREDS.get("host", "")
BE_PORT = int(os.getenv("BE_DB_PORT", str(_BE_CREDS.get("port", 5432))))
BE_DBNAME = os.getenv("BE_DB_NAME", "") or _BE_CREDS.get("dbname", "")
BE_USER = _BE_CREDS.get("user", "")
_BE_PW = (
    base64.b64decode(_BE_CREDS["password"]).decode()
    if _BE_CREDS.get("password") else ""
)
BE_SSLMODE = _BE_CREDS.get("sslmode", "require")

# `wyre` et `be` pointent sur le MEME host et la MEME base : dans un realm
# QgsCredentials, seul l'utilisateur les distingue (cf.
# _BridgeCredentials._credentials_for). Un bloc `be` qui reutiliserait
# l'utilisateur de `wyre` rendrait la resolution ambigue et casserait
# l'authentification de `wyre` — on refuse alors d'activer la connexion.
BE_ENABLED = (
    bool(BE_HOST and BE_DBNAME and BE_USER and _BE_PW)
    and BE_USER != DEFAULT_USER
)
```

- [ ] Vérifier que le module se parse et que les constantes sont correctes, sans PyQGIS (on ne charge que le bloc de credentials) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge && python3 -m py_compile bridge_plugin.py && echo "COMPILE OK" && python3 -c "
import base64, json
raw = json.load(open(\"credentials.json\"))
assert set(raw) == {\"wyre\", \"be\"}, raw.keys()
assert raw[\"be\"][\"user\"] == \"bureau_etudes\"
assert raw[\"wyre\"][\"user\"] == \"ftth_editor\"
assert base64.b64decode(raw[\"be\"][\"password\"]).decode()
assert raw[\"be\"][\"user\"] != raw[\"wyre\"][\"user\"]
print(\"CREDENTIALS OK\")"'
  ```
  Résultat attendu : `COMPILE OK` puis `CREDENTIALS OK`.

- [ ] Commiter :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1 && git add plugin-repo/packages/constructel_bridge/credentials.json plugin-repo/packages/constructel_bridge/bridge_plugin.py && git commit -m "feat(plugin): credentials.json a deux blocs wyre/be + constantes BE_*"'
  ```
  Résultat attendu : `2 files changed`.

---

## Tâche B2 — Descripteurs de connexion + généralisation de `_setup_qgis_pg_connection`

**Files**
- Modify: `~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge/bridge_plugin.py` (insertion après le bloc `BE_ENABLED` de B1, avant `LANG_LABELS` ; remplacement de la méthode `_setup_qgis_pg_connection`)
- Modify: `~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge/i18n/translations.py` (clé `pg.configured`, 3 occurrences : ~63 en, ~319 fr, ~577 pt)

**Interfaces**
- Consomme de B1 : `DEFAULT_HOST/PORT/DBNAME/USER/SSLMODE`, `BE_HOST/PORT/DBNAME/USER/SSLMODE`.
- Produit pour B4/B5 : le dict `_PG_CONNECTIONS` (clés `"wyre"` / `"be"`, champs `name`, `host`, `port`, `dbname`, `user`, `sslmode`, `schemas`, `schema`), la constante `_LEGACY_PG_CONNECTION`, et la signature `_setup_qgis_pg_connection(self, password: str, use_authcfg: bool = False, conn: str = "wyre")`.

**Steps**

- [ ] Insérer, juste après le bloc `BE_ENABLED = (...)` et avant `LANG_LABELS = {...}` :

```python
# Connexions PostgreSQL enregistrees dans les settings QGIS (panneau
# Parcourir / Gestionnaire de sources de donnees).
#   name    : nom affiche = cle sous PostgreSQL/connections/<name>
#   schemas : valeur du champ "Restreindre aux schemas"
#   schema  : schema par defaut
_PG_CONNECTIONS = {
    "wyre": {
        "name": "wyre",
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "dbname": DEFAULT_DBNAME,
        "user": DEFAULT_USER,
        "sslmode": DEFAULT_SSLMODE,
        "schemas": "infra,osiris",
        "schema": "infra",
    },
    "be": {
        "name": "be",
        "host": BE_HOST,
        "port": BE_PORT,
        "dbname": BE_DBNAME,
        "user": BE_USER,
        "sslmode": BE_SSLMODE,
        "schemas": "public",
        "schema": "public",
    },
}

# Nom de la connexion QGIS avant la v1.5.0. Retire des settings a chaque
# enregistrement : sans ca, le navigateur QGIS afficherait a la fois
# l'ancienne entree et la nouvelle apres mise a jour du plugin.
_LEGACY_PG_CONNECTION = "PostgreSQL/connections/constructel_bridge"
```

- [ ] Remplacer intégralement la méthode `_setup_qgis_pg_connection` (bloc commençant à `def _setup_qgis_pg_connection(self, password: str, use_authcfg: bool = False):` et se terminant par `self._log(tr("pg.configured"))`) par :

```python
    def _setup_qgis_pg_connection(self, password: str, use_authcfg: bool = False,
                                  conn: str = "wyre"):
        """Enregistre une connexion PostgreSQL dans les settings QGIS.

        Always writes all values to ensure consistency and fix any
        leftover misconfiguration from previous plugin versions.

        *conn* est une cle de ``_PG_CONNECTIONS`` ("wyre" ou "be") : elle
        determine le nom affiche, les parametres serveur et les schemas
        exposes.  Le defaut "wyre" preserve le comportement des appelants
        historiques (_connect).

        When *use_authcfg* is True, stores credentials in Auth Manager
        and references the authcfg ID instead of storing the password
        in plaintext (equivalent to "Convertir en configuration").
        """
        params = _PG_CONNECTIONS[conn]
        settings = QgsSettings()
        base = f"PostgreSQL/connections/{params['name']}"

        settings.setValue(f"{base}/host", params["host"])
        settings.setValue(f"{base}/port", str(params["port"]))
        settings.setValue(f"{base}/database", params["dbname"])
        settings.setValue(f"{base}/username", params["user"])
        settings.setValue(f"{base}/sslmode", "3")
        settings.setValue(f"{base}/estimatedMetadata", True)
        settings.setValue(f"{base}/allowGeometrylessTables", False)
        settings.setValue(f"{base}/geometryColumnsOnly", True)
        settings.setValue(f"{base}/dontResolveType", False)
        settings.setValue(f"{base}/publicOnly", False)
        settings.setValue(f"{base}/projectsInDatabase", True)
        settings.setValue(f"{base}/metadataInDatabase", True)
        settings.setValue(f"{base}/schemas", params["schemas"])
        settings.setValue(f"{base}/schema", params["schema"])

        if use_authcfg:
            # Store credentials in Auth Manager (encrypted)
            store_ok = _store_password_encrypted(password, conn)
            auth_cfg_id = settings.value(_AUTH_CFG_ID_KEYS[conn], "")
            if store_ok and auth_cfg_id:
                settings.setValue(f"{base}/authcfg", auth_cfg_id)
                self._log(
                    f"PG connection '{params['name']}' configured with authcfg (encrypted)."
                )
            else:
                # Auth Manager not ready — clear any stale authcfg
                settings.remove(f"{base}/authcfg")
                self._log(
                    f"Auth Manager unavailable, PG connection '{params['name']}' "
                    "uses saved password.",
                    Qgis.Warning,
                )
        else:
            settings.remove(f"{base}/authcfg")

        # Only store username; password is handled by Auth Manager (encrypted).
        # Storing plaintext password in QgsSettings is a security risk.
        settings.setValue(f"{base}/saveUsername", True)
        settings.setValue(f"{base}/savePassword", False)
        settings.remove(f"{base}/password")

        # Renommage v1.5.0 : retirer l'entree historique "constructel_bridge".
        settings.remove(_LEGACY_PG_CONNECTION)

        self._log(tr("pg.configured", name=params["name"]))
```

- [ ] Dans `i18n/translations.py`, remplacer les 3 valeurs de `pg.configured` :
  - anglais : `"pg.configured": "QGIS connection '{name}' configured",`
  - français : `"pg.configured": "Connexion QGIS '{name}' configuree",`
  - portugais : `"pg.configured": "Ligacao QGIS '{name}' configurada",`

- [ ] Vérifier la compilation et le contenu de `_PG_CONNECTIONS` (`_AUTH_CFG_ID_KEYS` n'existe pas encore — il arrive en B4, la référence n'est évaluée qu'à l'appel) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge && python3 -m py_compile bridge_plugin.py i18n/translations.py && echo "COMPILE OK" && grep -n "\"schemas\": \"infra,osiris\"\|\"schemas\": \"public\"\|_LEGACY_PG_CONNECTION\|def _setup_qgis_pg_connection" bridge_plugin.py && grep -c "pg.configured\": \".*{name}" i18n/translations.py'
  ```
  Résultat attendu : `COMPILE OK`, les 4 lignes attendues, puis `3`.

- [ ] Commiter :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1 && git add plugin-repo/packages/constructel_bridge/bridge_plugin.py plugin-repo/packages/constructel_bridge/i18n/translations.py && git commit -m "feat(plugin): _PG_CONNECTIONS + _setup_qgis_pg_connection(conn=) et renommage constructel_bridge -> wyre"'
  ```
  Résultat attendu : `2 files changed`.

---

## Tâche B3 — Intercepteur de credentials bi-connexion

**Files**
- Modify: `~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge/bridge_plugin.py` (classe `_BridgeCredentials` et fonction `_precache_pg_credentials`)

**Interfaces**
- Consomme de B1 : `BE_ENABLED`, `BE_USER`, `_BE_PW`, `BE_HOST`, `BE_PORT`, `BE_DBNAME`, `BE_SSLMODE`, `DEFAULT_*`, `_DEFAULT_PW`.
- Produit : la méthode `_BridgeCredentials._credentials_for(self, realm, username)` renvoyant `(user, password)` ou `None`. `update_password(password)` continue de ne piloter que le mot de passe `wyre` (appelée par `_connect`).

**Steps**

- [ ] Remplacer le docstring et le corps de `_BridgeCredentials` (méthodes `__init__`, `update_password`, `request` inchangées en surface, ajout de `_credentials_for`) — remplacer le bloc de la classe jusqu'à `requestMasterPassword` inclus par :

```python
class _BridgeCredentials(QgsCredentials):
    """Fournit automatiquement les credentials pour nos connexions PG.

    Quand un projet contient des couches avec un authcfg d'un autre
    utilisateur, QGIS affiche un dialogue de saisie pour chaque couche.
    Ce handler intercepte ces demandes et fournit le mot de passe
    automatiquement si le realm correspond a notre serveur PG.
    Pour les autres realms, il delegue au handler original (dialogue).

    `wyre` et `be` pointent sur le MEME host et la MEME base : le realm
    seul ne les distingue pas, la discrimination se fait sur le nom
    d'utilisateur (cf. _credentials_for).
    """

    def __init__(self, fallback):
        self._fallback = fallback
        self._username = DEFAULT_USER
        self._password = _DEFAULT_PW
        super().__init__()  # appelle setInstance(self) en interne

    def update_password(self, password: str):
        self._password = password

    def _credentials_for(self, realm, username):
        """Resout le couple (utilisateur, mot de passe) pour un realm.

        `be` est teste EN PREMIER car c'est le cas le plus specifique : il
        n'est reconnu que si l'utilisateur du bureau d'etudes apparait
        explicitement, soit dans le realm (`user='...'` que QGIS y insere
        quand la connexion memorise son nom d'utilisateur), soit dans
        l'argument *username*. Tout autre realm de notre serveur retombe
        sur `wyre` — comportement historique preserve a l'identique.

        Retourne None si le realm ne nous concerne pas.
        """
        if BE_ENABLED and (f"user='{BE_USER}'" in realm or username == BE_USER):
            return BE_USER, _BE_PW
        if DEFAULT_HOST in realm:
            return self._username, self._password
        return None

    def request(self, realm, username, password, message=""):
        QgsMessageLog.logMessage(
            f"Credentials request intercepted — realm={realm!r}",
            TAG, level=Qgis.Info,
        )
        creds = self._credentials_for(realm, username)
        if creds is not None:
            user, pwd = creds
            QgsMessageLog.logMessage(
                f"Auto-providing credentials for {user}",
                TAG, level=Qgis.Info,
            )
            # Also cache via put() so subsequent get() calls skip request()
            self.put(realm, user, pwd)
            return True, user, pwd
        # Realm inconnu → deleguer au handler QGIS par defaut (dialogue)
        if self._fallback:
            return self._fallback.request(realm, username, password, message)
        return False, username, password

    def requestMasterPassword(self, password, stored=False):
        if self._fallback:
            return self._fallback.requestMasterPassword(password, stored)
        return False, password
```

- [ ] Remplacer la fonction `_precache_pg_credentials` par :

```python
def _precache_pg_credentials():
    """Pre-cache PG credentials pour eviter le dialogue de saisie.

    Insere dans le cache de QgsCredentials les credentials pour les
    variantes de realm les plus courantes.  Quand QGIS appelle get()
    pour une de ces realms, il trouve le cache et n'affiche pas de
    dialogue.  Le cache est consomme (take) par get(), donc on le
    re-remplit a chaque chargement de projet.
    """
    creds = QgsCredentials.instance()
    for realm in (
        f"dbname='{DEFAULT_DBNAME}' host={DEFAULT_HOST} port={DEFAULT_PORT}",
        f"dbname='{DEFAULT_DBNAME}' host={DEFAULT_HOST} port={DEFAULT_PORT} sslmode={DEFAULT_SSLMODE}",
        f"dbname='{DEFAULT_DBNAME}' host={DEFAULT_HOST}",
        DEFAULT_HOST,
    ):
        creds.put(realm, DEFAULT_USER, _DEFAULT_PW)

    if not BE_ENABLED:
        return
    # `be` partage host + base avec `wyre` : SEULES les variantes de realm
    # qui portent user='...' sont pre-cachees. Pre-cacher une variante sans
    # utilisateur ecraserait le cache de `wyre` avec le mot de passe du
    # bureau d'etudes et casserait la connexion principale.
    for realm in (
        f"dbname='{BE_DBNAME}' host={BE_HOST} port={BE_PORT} user='{BE_USER}'",
        f"dbname='{BE_DBNAME}' host={BE_HOST} port={BE_PORT} sslmode={BE_SSLMODE} user='{BE_USER}'",
    ):
        creds.put(realm, BE_USER, _BE_PW)
```

- [ ] Vérifier la logique de résolution hors QGIS, en reproduisant `_credentials_for` sur les cas limites :
  ```bash
  ssh sdadmin@192.168.160.31 'python3 - <<PY
DEFAULT_HOST, DEFAULT_USER, DEFAULT_PW = "192.168.160.31", "ftth_editor", "PW_WYRE"
BE_ENABLED, BE_USER, BE_PW = True, "bureau_etudes", "PW_BE"

def credentials_for(realm, username):
    if BE_ENABLED and (f"user=\x27{BE_USER}\x27" in realm or username == BE_USER):
        return BE_USER, BE_PW
    if DEFAULT_HOST in realm:
        return DEFAULT_USER, DEFAULT_PW
    return None

cases = [
    ("dbname=\x27farois_ftth\x27 host=192.168.160.31 port=5432 user=\x27bureau_etudes\x27", "", ("bureau_etudes","PW_BE")),
    ("dbname=\x27farois_ftth\x27 host=192.168.160.31 port=5432 user=\x27ftth_editor\x27", "ftth_editor", ("ftth_editor","PW_WYRE")),
    ("dbname=\x27farois_ftth\x27 host=192.168.160.31 port=5432", "", ("ftth_editor","PW_WYRE")),
    ("192.168.160.31", "", ("ftth_editor","PW_WYRE")),
    ("dbname=\x27farois_ftth\x27 host=192.168.160.31", "bureau_etudes", ("bureau_etudes","PW_BE")),
    ("dbname=\x27autre\x27 host=10.0.0.9 port=5432", "", None),
]
bad = 0
for realm, user, expected in cases:
    got = credentials_for(realm, user)
    ok = got == expected
    bad += 0 if ok else 1
    print("OK " if ok else "KO ", realm[:60], "|", user, "->", got)
print("---", bad, "echec(s)")
PY'
  ```
  Résultat attendu : 6 lignes `OK`, puis `--- 0 echec(s)`.

- [ ] Vérifier la compilation :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge && python3 -m py_compile bridge_plugin.py && echo "COMPILE OK"'
  ```
  Résultat attendu : `COMPILE OK`.

- [ ] Commiter :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1 && git add plugin-repo/packages/constructel_bridge/bridge_plugin.py && git commit -m "feat(plugin): _BridgeCredentials resout wyre/be par utilisateur + precache be"'
  ```
  Résultat attendu : `1 file changed`.

---

## Tâche B4 — Auth Manager par connexion

**Files**
- Modify: `~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge/bridge_plugin.py` (constantes `TAG`/`AUTH_CFG_NAME`, lignes 46-47 ; fonctions `_store_password_encrypted`, `_retrieve_password_encrypted`, `_remove_stored_password` ; appel ligne ~542)

**Interfaces**
- Consomme de B2 : `_PG_CONNECTIONS` (pour `["user"]`).
- Produit pour B2/B5 : `_AUTH_CFG_ID_KEYS` (dict `conn -> clé de settings`), `_AUTH_CFG_NAMES`, et les signatures `_store_password_encrypted(password: str, conn: str = "wyre") -> bool`, `_retrieve_password_encrypted(conn: str = "wyre") -> str`, `_remove_stored_password(conn: str = "wyre")`.

**Steps**

- [ ] Remplacer les lignes 46-47 par :

```python
TAG = "Constructel Bridge"
AUTH_CFG_NAME = "constructel_bridge_pw"
AUTH_CFG_NAME_BE = "constructel_bridge_be_pw"

# Cle de settings ou est memorise l'ID de configuration Auth Manager, par
# connexion. `wyre` CONSERVE la cle historique : la changer orphaniserait
# les configurations Auth Manager deja stockees sur les postes existants.
_AUTH_CFG_ID_KEYS = {
    "wyre": "constructel_bridge/auth_cfg_id",
    "be": "constructel_bridge/auth_cfg_id_be",
}
_AUTH_CFG_NAMES = {
    "wyre": AUTH_CFG_NAME,
    "be": AUTH_CFG_NAME_BE,
}
```

- [ ] Remplacer `_store_password_encrypted` par :

```python
def _store_password_encrypted(password: str, conn: str = "wyre") -> bool:
    """Store the password in QGIS Auth Manager (encrypted SQLite DB).

    *conn* est une cle de ``_PG_CONNECTIONS`` : chaque connexion a sa
    propre configuration Auth Manager et sa propre cle de settings, sinon
    `be` ecraserait celle de `wyre` (et inversement).

    Returns True on success.
    """
    if not _ensure_auth_manager_ready():
        QgsMessageLog.logMessage(
            "Auth Manager not available, cannot store encrypted password.",
            TAG, level=Qgis.Warning,
        )
        return False
    auth_mgr = QgsApplication.authManager()
    settings_key = _AUTH_CFG_ID_KEYS[conn]
    # Look for an existing config with our name
    cfg_id = QgsSettings().value(settings_key, "")
    if cfg_id and cfg_id in auth_mgr.configIds():
        # Update existing config
        config = QgsAuthMethodConfig()
        auth_mgr.loadAuthenticationConfig(cfg_id, config, True)
        config.setConfig("password", password)
        ok = auth_mgr.updateAuthenticationConfig(config)
    else:
        # Create new config
        config = QgsAuthMethodConfig("Basic")
        config.setName(_AUTH_CFG_NAMES[conn])
        config.setConfig("username", _PG_CONNECTIONS[conn]["user"])
        config.setConfig("password", password)
        ok = auth_mgr.storeAuthenticationConfig(config)
        if ok:
            QgsSettings().setValue(settings_key, config.id())
    # Remove legacy plaintext password if present
    QgsSettings().remove("constructel_bridge/password")
    return ok
```

- [ ] Remplacer `_retrieve_password_encrypted` par :

```python
def _retrieve_password_encrypted(conn: str = "wyre") -> str:
    """Retrieve the password from QGIS Auth Manager.

    Returns the password string, or empty string if not found.
    """
    if not _ensure_auth_manager_ready():
        return ""
    auth_mgr = QgsApplication.authManager()
    cfg_id = QgsSettings().value(_AUTH_CFG_ID_KEYS[conn], "")
    if not cfg_id or cfg_id not in auth_mgr.configIds():
        # Fallback: check legacy plaintext storage and migrate.
        # RESERVE a `wyre` : la cle historique constructel_bridge/password
        # ne contient que le mot de passe de la connexion d'origine ; la
        # renvoyer pour `be` fournirait un mot de passe faux.
        if conn == "wyre":
            legacy_pw = QgsSettings().value("constructel_bridge/password", "")
            if legacy_pw:
                _store_password_encrypted(legacy_pw, conn)
                return legacy_pw
        return ""
    config = QgsAuthMethodConfig()
    auth_mgr.loadAuthenticationConfig(cfg_id, config, True)
    return config.config("password", "")
```

- [ ] Remplacer `_remove_stored_password` par :

```python
def _remove_stored_password(conn: str = "wyre"):
    """Remove the stored password from Auth Manager and legacy settings."""
    auth_mgr = QgsApplication.authManager()
    settings_key = _AUTH_CFG_ID_KEYS[conn]
    cfg_id = QgsSettings().value(settings_key, "")
    if cfg_id and cfg_id in auth_mgr.configIds():
        auth_mgr.removeAuthenticationConfig(cfg_id)
    QgsSettings().remove(settings_key)
    QgsSettings().remove("constructel_bridge/password")
```

- [ ] Vérifier la compilation et l'absence de clé de settings encore codée en dur hors du dict :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge && python3 -m py_compile bridge_plugin.py && echo "COMPILE OK" && grep -n "constructel_bridge/auth_cfg_id" bridge_plugin.py'
  ```
  Résultat attendu : `COMPILE OK`, puis exactement 2 lignes, toutes deux à l'intérieur du dict `_AUTH_CFG_ID_KEYS`.

- [ ] Vérifier que les appelants historiques compilent toujours avec le défaut `"wyre"` :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge && grep -n "_retrieve_password_encrypted()\|_store_password_encrypted(password)\|_store_password_encrypted(password, conn)" bridge_plugin.py'
  ```
  Résultat attendu : 3 lignes — `_retrieve_password_encrypted()` dans `_auto_connect`, `_store_password_encrypted(password)` dans `_on_connect`, `_store_password_encrypted(password, conn)` dans `_setup_qgis_pg_connection`.

- [ ] Commiter :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1 && git add plugin-repo/packages/constructel_bridge/bridge_plugin.py && git commit -m "feat(plugin): configuration Auth Manager par connexion (cle wyre historique preservee)"'
  ```
  Résultat attendu : `1 file changed`.

---

## Tâche B5 — Enregistrement de la connexion `be` au chargement

**Files**
- Modify: `~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge/bridge_plugin.py` (`initGui`, immédiatement après l'appel `_precache_pg_credentials()`, ligne ~382)

**Interfaces**
- Consomme de B1 (`BE_ENABLED`, `_BE_PW`), B2 (`_setup_qgis_pg_connection(..., conn="be")`), B3 (precache `be`).
- Produit : l'entrée de settings `PostgreSQL/connections/be` présente dès le chargement du plugin, sans connexion psycopg2 ni enregistrement dans `ref.users`.

**Steps**

- [ ] Insérer, entre l'appel `_precache_pg_credentials()` et le commentaire `# Supprimer le dialogue "Traiter les couches inutilisables"` :

```python
        # Enregistrer la connexion `be` (bureau d'etudes, schema public).
        # SANS authcfg : _store_password_encrypted appellerait
        # _ensure_auth_manager_ready(), qui declenche le dialogue de mot de
        # passe maitre QGIS des le demarrage. Le mot de passe est fourni a
        # la volee par _BridgeCredentials et par le cache pre-rempli
        # ci-dessus. `be` n'a pas besoin du flux _connect complet (psycopg2,
        # ref.users, onboarding) : c'est une connexion de consultation.
        if BE_ENABLED:
            try:
                self._setup_qgis_pg_connection(_BE_PW, use_authcfg=False, conn="be")
            except Exception as exc:
                QgsMessageLog.logMessage(
                    f"BE connection setup failed: {exc}", TAG, level=Qgis.Warning,
                )
        else:
            QgsMessageLog.logMessage(
                "Connexion 'be' non configuree "
                "(bloc absent ou invalide dans credentials.json)",
                TAG, level=Qgis.Info,
            )
```

- [ ] Vérifier la compilation et le placement (l'appel doit se situer entre `_precache_pg_credentials()` et `_BridgeBadLayerHandler()`) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge && python3 -m py_compile bridge_plugin.py && echo "COMPILE OK" && grep -n "_precache_pg_credentials()$\|conn=\"be\"\|_BridgeBadLayerHandler()" bridge_plugin.py'
  ```
  Résultat attendu : `COMPILE OK`, puis 3 lignes dont les numéros sont strictement croissants dans cet ordre.

- [ ] Commiter :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1 && git add plugin-repo/packages/constructel_bridge/bridge_plugin.py && git commit -m "feat(plugin): enregistrement de la connexion be au chargement (sans authcfg)"'
  ```
  Résultat attendu : `1 file changed`.

---

## Tâche B6 — Release 1.5.0 dans la worktree

**Files**
- Modify: `~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge/metadata.txt` (ligne `changelog=` — ajout d'une entrée v1.5.0 en tête)
- Modify (par `release.py`) : `metadata.txt` (`version=`), `~/projects/qgis_repo-chantier1/plugin-repo/plugins.xml`, `~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge.zip`

**Interfaces**
- Consomme de B1–B5 : le code du plugin dans son état final.
- Produit pour C : le zip `~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge.zip` en version 1.5.0, installable dans QGIS.

**Steps**

- [ ] Dans `metadata.txt`, insérer cette ligne en première position du bloc `changelog=` (juste après `changelog=`, avant l'entrée `v1.4.10`) — noter que `release.py` ne touche PAS au changelog, il faut l'écrire à la main :
  ```
  changelog=v1.5.0 - feat(plugin): deux connexions PostgreSQL nommees. La connexion historique "constructel_bridge" est renommee "wyre" (schemas infra,osiris - comportement identique) et une seconde connexion "be" (bureau d'etudes, schema public uniquement) est ajoutee. credentials.json passe a deux blocs nommes {"wyre": {...}, "be": {...}} ; les anciens fichiers plats restent lisibles (rattaches a "wyre", "be" desactivee). Chaque connexion a sa propre configuration Auth Manager. Prerequis base : migration Farois 328 (role bureau_etudes + table public.geofiber_asbuilt_depth_points).
  ```

- [ ] Lancer la release depuis le répertoire du plugin dans la worktree :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge && python3 release.py 1.5.0'
  ```
  Résultat attendu :
  ```
  Releasing constructel_bridge v1.5.0
    metadata.txt -> 1.5.0
    plugins.xml  -> 1.5.0
    constructel_bridge.zip rebuilt (... KB)
  Done.
  ```

- [ ] Vérifier que le zip embarque bien le nouveau `credentials.json` à deux blocs (c'est ce fichier-là que les postes recevront) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1/plugin-repo/packages && python3 -c "
import json, zipfile
z = zipfile.ZipFile(\"constructel_bridge.zip\")
raw = json.loads(z.read(\"constructel_bridge/credentials.json\"))
assert set(raw) == {\"wyre\", \"be\"}, raw.keys()
assert raw[\"be\"][\"user\"] == \"bureau_etudes\"
meta = z.read(\"constructel_bridge/metadata.txt\").decode()
assert \"version=1.5.0\" in meta
print(\"ZIP OK - version 1.5.0, credentials wyre+be\")"'
  ```
  Résultat attendu : `ZIP OK - version 1.5.0, credentials wyre+be`.

- [ ] Vérifier que l'arbre **servi** n'a toujours pas bougé (la publication n'a pas encore eu lieu) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo && grep -n "^version=" plugin-repo/packages/constructel_bridge/metadata.txt && git status --short plugin-repo/ | wc -l'
  ```
  Résultat attendu : `version=1.4.10` et `0`.

- [ ] Commiter :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-chantier1 && git add plugin-repo/packages/constructel_bridge/metadata.txt plugin-repo/plugins.xml plugin-repo/packages/constructel_bridge.zip && git commit -m "release(constructel_bridge): 1.5.0 - connexions wyre + be"'
  ```
  Résultat attendu : `3 files changed`.

---

# Tâche C — Vérification bout-en-bout et publication

**Files**
- Modify (VPS, non versionné) : aucun fichier — application de la migration et pose du mot de passe
- Modify: `~/projects/Farois` (merge de `feat/mig328-bureau-etudes`) et `~/projects/qgis_repo` (merge de `feat/connexions-wyre-be`) — **uniquement après GO de Simon**

**Interfaces**
- Consomme de A2/A3 : `sql/migrations/328_bureau_etudes_asbuilt_depth_points.sql`
- Consomme de A5 : `BUREAU_ETUDES_PASSWORD` dans `docker/.env.secrets`
- Consomme de B6 : `constructel_bridge.zip` v1.5.0

**Steps**

- [ ] **GATE — GO explicite de Simon requis** pour l'ensemble des étapes suivantes (application en base, pose du mot de passe, publication du plugin). Ne pas enchaîner sans.

- [ ] Poser le mot de passe du rôle **après** application de la migration ? Non : le rôle n'existe pas encore. Appliquer d'abord la migration. Copier le fichier dans le conteneur worker (le `sql/` est baké dans l'image, il n'y a pas de bind mount ; cette copie est éphémère et c'est voulu — au prochain rebuild, la migration sera bakée et le runner la sautera car déjà tracée) :
  ```bash
  ssh sdadmin@192.168.160.31 'docker cp ~/projects/Farois-mig328/sql/migrations/328_bureau_etudes_asbuilt_depth_points.sql farois-worker:/opt/farois/sql/migrations/ && docker exec farois-worker ls -l /opt/farois/sql/migrations/328_bureau_etudes_asbuilt_depth_points.sql'
  ```
  Résultat attendu : une ligne `ls -l` sur le fichier copié.

- [ ] Lister ce qui sera appliqué (dry-run) — **il ne doit y avoir QUE la 328** :
  ```bash
  ssh sdadmin@192.168.160.31 'docker exec farois-worker farois --dry-run deploy migrate 2>&1 | grep -v WARNING'
  ```
  Résultat attendu : `1 migration(s) en attente:` puis `  - 328_bureau_etudes_asbuilt_depth_points` puis `[DRY-RUN] Aucune migration appliquee`. Si d'autres migrations apparaissent, **STOP** et remonter à Simon.

- [ ] Appliquer la migration (sous `ftth_admin`, via le runner officiel qui trace dans `esb.applied_migrations`) :
  ```bash
  ssh sdadmin@192.168.160.31 'docker exec farois-worker farois deploy migrate 2>&1 | grep -v "WARNING - farois.env_compat"'
  ```
  Résultat attendu : le banner `328 - Role bureau_etudes + ...`, `NOTICE: ✓ Rôle bureau_etudes créé`, les lignes `\echo` de la migration, **les `WARNING: no privileges were granted for "spatial_ref_sys" / "geometry_columns" / "geography_columns" / "v_layer_styles_summary"` (attendus, documentés dans l'en-tête)**, le tableau de vérification avec `public=t` et tous les autres schémas à `f`, le tableau `t | t | t | f`, puis `328_bureau_etudes_asbuilt_depth_points OK` et `1 migration(s) appliquee(s)`.

- [ ] Poser le mot de passe partagé sur le rôle (technique `psql -v` de `deploy_roles.sh`, sans rejouer le hardening complet) :
  ```bash
  ssh sdadmin@192.168.160.31 'set -a; . ~/projects/Farois/docker/.env.secrets; set +a; echo "ALTER ROLE bureau_etudes WITH PASSWORD :\x27pw\x27;" | docker exec -i -e PGPASSWORD="$POSTGRES_PASSWORD" ftth-postgres psql -U postgres -d farois_ftth -v "pw=$BUREAU_ETUDES_PASSWORD"'
  ```
  Résultat attendu : `ALTER ROLE`.

- [ ] Vérification SQL n°1 — attributs du rôle :
  ```bash
  ssh sdadmin@192.168.160.31 'set -a; . ~/projects/Farois/docker/.env.secrets; set +a; docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" ftth-postgres psql -U postgres -d farois_ftth -c "SELECT rolname, rolcanlogin, rolsuper, rolcreaterole, rolconnlimit FROM pg_roles WHERE rolname = \x27bureau_etudes\x27;"'
  ```
  Résultat attendu : une ligne `bureau_etudes | t | f | f | 20`.

- [ ] Vérification SQL n°2 — aucune table `infra`/`osiris`/`ref` lisible (invariant de cloisonnement du spec, §Testing) :
  ```bash
  ssh sdadmin@192.168.160.31 'set -a; . ~/projects/Farois/docker/.env.secrets; set +a; docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" ftth-postgres psql -U postgres -d farois_ftth -c "SELECT count(*) AS lisibles FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname IN (\x27infra\x27,\x27osiris\x27,\x27ref\x27,\x27chantier\x27) AND c.relkind IN (\x27r\x27,\x27v\x27,\x27m\x27,\x27p\x27) AND has_table_privilege(\x27bureau_etudes\x27, c.oid, \x27SELECT\x27);"'
  ```
  Résultat attendu : `lisibles = 0`.

- [ ] Vérification SQL n°3 — la table est enregistrée dans `geometry_columns` (condition pour que QGIS l'affiche avec `geometryColumnsOnly=True`) :
  ```bash
  ssh sdadmin@192.168.160.31 'set -a; . ~/projects/Farois/docker/.env.secrets; set +a; docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" ftth-postgres psql -U postgres -d farois_ftth -c "SELECT f_table_schema, f_table_name, f_geometry_column, coord_dimension, srid, type FROM geometry_columns WHERE f_table_name = \x27geofiber_asbuilt_depth_points\x27;"'
  ```
  Résultat attendu : `public | geofiber_asbuilt_depth_points | geom | 2 | 31370 | POINT`.

- [ ] Vérification SQL n°4 — connexion réelle sous `bureau_etudes` depuis le réseau (mêmes paramètres que la connexion QGIS `be`), lecture OK sur `public`, refus sur `infra` :
  ```bash
  ssh sdadmin@192.168.160.31 'set -a; . ~/projects/Farois/docker/.env.secrets; set +a; docker exec -e PGPASSWORD="$BUREAU_ETUDES_PASSWORD" ftth-postgres psql "host=192.168.160.31 port=5432 dbname=farois_ftth user=bureau_etudes sslmode=require" -c "SELECT count(*) FROM public.geofiber_asbuilt_depth_points;" -c "SELECT count(*) FROM infra.structures;"'
  ```
  Résultat attendu : `count = 0` pour la première requête, puis `ERROR: permission denied for schema infra` pour la seconde.

- [ ] Vérification SQL n°5 — le trigger `updated_at` fonctionne (upsert du chantier 2) :
  ```bash
  ssh sdadmin@192.168.160.31 'set -a; . ~/projects/Farois/docker/.env.secrets; set +a; docker exec -e PGPASSWORD="$BUREAU_ETUDES_PASSWORD" ftth-postgres psql "host=192.168.160.31 port=5432 dbname=farois_ftth user=bureau_etudes sslmode=require" -c "INSERT INTO public.geofiber_asbuilt_depth_points (intervention_id, depth_cm, geom) VALUES (\x27TEST-C1\x27, 60, ST_SetSRID(ST_MakePoint(150000, 170000), 31370));" -c "SELECT pg_sleep(1);" -c "INSERT INTO public.geofiber_asbuilt_depth_points (intervention_id, depth_cm) VALUES (\x27TEST-C1\x27, 75) ON CONFLICT (intervention_id) DO UPDATE SET depth_cm = EXCLUDED.depth_cm;" -c "SELECT intervention_id, depth_cm, (updated_at > created_at) AS updated_bumped FROM public.geofiber_asbuilt_depth_points WHERE intervention_id = \x27TEST-C1\x27;"'
  ```
  Résultat attendu : `TEST-C1 | 75 | t`.

- [ ] Nettoyer la ligne de test (`bureau_etudes` n'a pas `DELETE` — c'est voulu et confirmé par la vérification `t|t|t|f`, il faut donc passer par `postgres`) :
  ```bash
  ssh sdadmin@192.168.160.31 'set -a; . ~/projects/Farois/docker/.env.secrets; set +a; docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" ftth-postgres psql -U postgres -d farois_ftth -c "DELETE FROM public.geofiber_asbuilt_depth_points WHERE intervention_id = \x27TEST-C1\x27;"'
  ```
  Résultat attendu : `DELETE 1`.

- [ ] Récupérer le zip v1.5.0 sur le poste Windows de Simon, puis l'installer dans QGIS via *Extensions > Installer/Gérer les extensions > Installer depuis un ZIP* :
  ```bash
  scp sdadmin@192.168.160.31:~/projects/qgis_repo-chantier1/plugin-repo/packages/constructel_bridge.zip .
  ```
  Résultat attendu : le fichier est téléchargé ; QGIS confirme l'installation de « Constructel Bridge » 1.5.0.

- [ ] Vérification QGIS n°1 (spec §Testing) — redémarrer QGIS, ouvrir le panneau *Explorateur*, déplier *PostgreSQL*. Résultat attendu : **deux** entrées `wyre` et `be`, et **aucune** entrée `constructel_bridge`. Déplier `wyre` : les schémas `infra` et `osiris` apparaissent. Déplier `be` : seul le schéma `public` apparaît, contenant `geofiber_asbuilt_depth_points`. Aucun dialogue « Saisir les identifiants » ne s'affiche.

- [ ] Vérification QGIS n°2 — dans l'onglet *Journal des messages > Constructel Bridge*, vérifier la présence des deux lignes de configuration. Résultat attendu : `Connexion QGIS 'be' configuree` (émise depuis `initGui`) puis `Connexion QGIS 'wyre' configuree` (émise depuis `_connect` via l'auto-connexion), et aucune ligne `BE connection setup failed`.

- [ ] Vérification QGIS n°3 — double-cliquer sur `be > public > geofiber_asbuilt_depth_points` pour charger la couche. Résultat attendu : la couche s'ajoute (0 entité), sans dialogue de mot de passe, et son SCR est EPSG:31370.

- [ ] Vérification QGIS n°4 (non-régression, spec §Compatibilité/risques) — ouvrir un projet `.qgz` existant qui utilisait l'ancienne connexion. Résultat attendu : toutes les couches PostgreSQL se chargent, aucun dialogue « Traiter les couches inutilisables », aucune reconfiguration demandée. Vérifier ensuite que le bouton *Connexion base de données* du plugin fonctionne toujours et que l'utilisateur est bien annoncé (`Connecte en tant que <user>`).

- [ ] Vérification QGIS n°5 — vérifier que les deux configurations Auth Manager coexistent : *Préférences > Options > Authentification*. Résultat attendu : deux entrées, `constructel_bridge_pw` et `constructel_bridge_be_pw`, la première ayant conservé son ID (la connexion `wyre` n'a pas redemandé de mot de passe au premier lancement).

- [ ] **Publication Farois** — merger la branche dans le working tree partagé, puis pousser :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois && git merge --no-ff feat/mig328-bureau-etudes -m "merge: mig 328 bureau_etudes + table asbuilt (chantier 1)" && git log --oneline -3'
  ```
  Résultat attendu : le merge réussit et les 4 commits apparaissent. La migration étant **déjà tracée dans `esb.applied_migrations`**, un futur rebuild de l'image `farois-worker` la bakera sans la rejouer.

- [ ] **Publication plugin** — merger dans l'arbre servi (c'est ce merge qui rend la 1.5.0 visible sur `http://192.168.160.31:9080/`) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo && git merge --no-ff feat/connexions-wyre-be -m "merge: connexions QGIS wyre/be (chantier 1)" && grep -n "^version=" plugin-repo/packages/constructel_bridge/metadata.txt'
  ```
  Résultat attendu : le merge réussit et `version=1.5.0`.

- [ ] Vérifier que le dépôt de plugins sert bien la 1.5.0 :
  ```bash
  ssh sdadmin@192.168.160.31 'curl -s http://192.168.160.31:9080/plugin-repo/plugins.xml | grep -o "name=\"Constructel Bridge\" version=\"[0-9.]*\""'
  ```
  Résultat attendu : `name="Constructel Bridge" version="1.5.0"`.

- [ ] Supprimer les worktrees devenues inutiles :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois && git worktree remove ~/projects/Farois-mig328 && cd ~/projects/qgis_repo && git worktree remove ~/projects/qgis_repo-chantier1 && git worktree list'
  ```
  Résultat attendu : la liste ne contient plus que les arbres principaux.
