# Adresse mail de l'auteur sur chaque modification QGIS — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** chaque modification faite depuis QGIS enregistre l'adresse mail de son auteur dans l'audit Farois, sans jamais bloquer une édition.

**Architecture:** Constructel Bridge 1.5.10 pose la variable d'environnement libpq `PGOPTIONS="-c app.current_user=<email>"` dans le processus QGIS avant le chargement des couches. Toutes les connexions ouvertes ensuite, celles du fournisseur PostgreSQL de QGIS comprises, portent alors l'adresse. Le trigger d'audit existant (Farois `025:796`, mig 443) la recopie dans `audit.transactions`. Une migration Farois 453, déployée d'abord, élargit `audit.status_history.source` (VARCHAR(30) → VARCHAR(255)), où le trigger `universal_trigger_before` écrit aussi cette valeur.

**Tech Stack:** Python 3 (QGIS 3.28–3.99, PyQGIS), psycopg2, pytest + stubs `qgis` existants ; PostgreSQL 17 / PostGIS (image `ftth-postgres:17.3.5-farois`), psql, bash.

**Spec:** `qgis_repo` branche `feat/bridge-audit-email`, `docs/superpowers/specs/2026-10-15-bridge-audit-email-design.md` (commit `cd413d6`).

## Global Constraints

- Serveur : `ssh -i ~/.ssh/id_ed25519 sdadmin@192.168.160.31` ; shell distant **zsh** (citer les globs).
- Worktree Bridge : `/home/sdadmin/projects/qgis_repo/.worktrees/feat-bridge-audit-email` (branche `feat/bridge-audit-email`, déjà créée). Ne **jamais** modifier le working tree principal `~/projects/qgis_repo` hors Task 7 : il est servi en direct sur `:9080`.
- Worktree Farois : `/home/sdadmin/projects/Farois/.worktrees/feat-453-status-history-source` (créé en Task 2). Le dépôt `~/projects/Farois` est partagé et vivant : ne rien committer dans son working tree principal.
- Tests Bridge : `/home/sdadmin/.venvs/bridge0-tests/bin/pytest`, lancé depuis la racine du worktree Bridge (le `pytest.ini` y pointe `testpaths`). Relire soi-même la sortie : ne jamais se fier au seul compte rendu d'un sous-agent.
- Version Bridge : **1.5.10** (pas de 1.6.x).
- Migration : numéro **453**, fichiers `453_audit_status_history_source_email.sql` et `453r_rollback_audit_status_history_source_email.sql`. Cible : `VARCHAR(255)`. Le retour arrière ne tronque jamais.
- Clés QgsSettings : `constructel_bridge/audit_email` (adresse en cache) et `constructel_bridge/audit_email_pgoptions` (interrupteur, vrai par défaut).
- Adresse valide : `^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$`, longueur ≤ 255.
- Bridge ne pose **jamais** `app.user_id`. L'adresse est déclarée : `identity_verified` reste `false` (traçabilité seulement).
- Une adresse absente ou invalide, ou l'interrupteur à faux, ne bloque **jamais** une édition ni une connexion.
- Accès DB prod : uniquement avec le feu vert explicite de Simon pour chaque écriture. Mot de passe : extraire **seulement** la ligne `POSTGRES_PASSWORD` de `~/projects/Farois/docker/.env.secrets` (le fichier n'est pas sourçable en shell).
- **GATE** de publication de Bridge 1.5.10 : (a) 453 appliquée en prod et vérifiée, (b) spike Task 1 réussi, (c) Tasks 3–5 vertes et relues.

## Review Focus

- `PGOPTIONS` déjà présent sur un poste (`-c search_path=…`) : conservé, seule l'option `app.current_user` est ajoutée ou remplacée → test dans Task 3.
- Adresse modifiée dans l'assistant d'accueil pendant la session : la nouvelle adresse est reposée pour les connexions suivantes → test dans Task 4.
- Utilisateur Bridge sans adresse, ou avec une adresse invalide, dans `ref.users` : aucun `PGOPTIONS`, avertissement journalisé, connexion et édition intactes → test dans Task 4.
- Interrupteur stocké par QGIS sous la chaîne `"false"` : respecté → test dans Task 4.
- En prod, une vue dépendante portant un droit par colonne, une vue imbriquée ou un trigger inattendu : la migration doit **échouer et tout annuler**, jamais perdre un droit en silence → tests dans Task 2.

---

### Task 1 : Spike PGOPTIONS sur QGIS Windows (jetable)

But : prouver qu'un `PGOPTIONS` posé par `os.environ` depuis le Python de QGIS 3.44.6 Windows atteint une **nouvelle** connexion du fournisseur PostgreSQL. Aucun code n'est conservé ; seul le compte rendu l'est.

**Files:**
- Create (jetable, hors dépôts) : `C:\Users\SimonDucorneau\AppData\Local\Temp\spike_pgoptions\spike_pgoptions.py` (vu depuis WSL : `/mnt/c/Users/SimonDucorneau/AppData/Local/Temp/spike_pgoptions/`)
- Create (Task 1 Step 7) : `docs/superpowers/specs/2026-10-15-bridge-audit-email-spike-results.md` dans le worktree Bridge

**Interfaces:**
- Consumes : rien.
- Produces : le verdict « réussi / échoué » requis par le GATE (b).

- [ ] **Step 1 : Démarrer un PostgreSQL jetable sur le PC (WSL)**

L'image est déjà en cache sur le PC (`docker images` → `ftth-postgres:17.3.5-farois`). Aucun port exposé au réseau : liaison sur `127.0.0.1` uniquement.

```bash
docker run -d --rm --name spike-pgoptions -p 127.0.0.1:5433:5432 \
  -e POSTGRES_PASSWORD=spike -e POSTGRES_DB=spike \
  -e FAROIS_AUTO_INSTALL=false -e WYRE_AUTO_INSTALL=false \
  ftth-postgres:17.3.5-farois
docker exec spike-pgoptions pg_isready -U postgres -d spike
```
Attendu : `accepting connections` (relancer `pg_isready` jusqu'à ce résultat).

- [ ] **Step 2 : Activer SSL si besoin et créer le schéma de test**

```bash
docker exec spike-pgoptions psql -U postgres -d spike -tAc "SHOW ssl"
```
Si la réponse est `off` :
```bash
docker exec -u postgres spike-pgoptions sh -c 'openssl req -new -x509 -days 1 -nodes -subj /CN=localhost -keyout /var/lib/postgresql/spike.key -out /var/lib/postgresql/spike.crt && chmod 600 /var/lib/postgresql/spike.key'
docker exec spike-pgoptions psql -U postgres -d spike -c "ALTER SYSTEM SET ssl = on" -c "ALTER SYSTEM SET ssl_cert_file = '/var/lib/postgresql/spike.crt'" -c "ALTER SYSTEM SET ssl_key_file = '/var/lib/postgresql/spike.key'" -c "SELECT pg_reload_conf()"
docker exec spike-pgoptions psql -U postgres -d spike -tAc "SHOW ssl"
```
Attendu : `on`.

Puis :
```bash
docker exec -i spike-pgoptions psql -U postgres -d spike -v ON_ERROR_STOP=1 <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE ROLE spike_editor LOGIN PASSWORD 'spike';
CREATE TABLE public.spike_edit (id serial PRIMARY KEY, label text, geom geometry(Point, 31370));
INSERT INTO public.spike_edit (label, geom) VALUES
  ('a', ST_SetSRID(ST_MakePoint(150000, 170000), 31370)),
  ('b', ST_SetSRID(ST_MakePoint(150010, 170010), 31370));
CREATE TABLE public.spike_log (
  at timestamptz DEFAULT clock_timestamp(), pid int, label text,
  app_user text, app_name text, ssl bool);
CREATE FUNCTION public.spike_capture() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO public.spike_log (pid, label, app_user, app_name, ssl)
  VALUES (pg_backend_pid(), NEW.label, current_setting('app.current_user', true),
          current_setting('application_name', true),
          (SELECT s.ssl FROM pg_stat_ssl s WHERE s.pid = pg_backend_pid()));
  RETURN NEW;
END $$;
CREATE TRIGGER spike_capture BEFORE UPDATE ON public.spike_edit
  FOR EACH ROW EXECUTE FUNCTION public.spike_capture();
GRANT SELECT, UPDATE ON public.spike_edit TO spike_editor;
GRANT INSERT, SELECT ON public.spike_log TO spike_editor;
GRANT USAGE ON SEQUENCE public.spike_edit_id_seq TO spike_editor;
SQL
```

- [ ] **Step 3 : Écrire le script PyQGIS du spike**

Profil QGIS **temporaire** : ni les réglages ni la base d'authentification réels de Simon ne sont touchés.

```python
# spike_pgoptions.py — jetable, Task 1 du plan 2026-10-15-bridge-audit-email
import os
import sys
import tempfile

from qgis.core import (
    QgsApplication, QgsAuthMethodConfig, QgsDataSourceUri, QgsVectorLayer,
)

PROFILE = tempfile.mkdtemp(prefix="spike_pgoptions_profile_")
EMAIL = "spike.user@constructel.be"


def uri(sslmode, authcfg=None):
    u = QgsDataSourceUri()
    if authcfg:
        u.setConnection("localhost", "5433", "spike", "", "", sslmode, authcfg)
    else:
        u.setConnection("localhost", "5433", "spike", "spike_editor", "spike", sslmode)
    u.setDataSource("public", "spike_edit", "geom", "", "id")
    return u.uri(False)


def edit(name, layer_uri, label):
    lyr = QgsVectorLayer(layer_uri, name, "postgres")
    if not lyr.isValid():
        print(f"{name}: COUCHE INVALIDE {lyr.error().summary()}")
        return None
    feat = next(lyr.getFeatures())
    lyr.startEditing()
    lyr.changeAttributeValue(feat.id(), lyr.fields().indexOf("label"), label)
    ok = lyr.commitChanges()
    print(f"{name}: commit={ok} {'' if ok else lyr.commitErrors()}")
    return lyr


app = QgsApplication([], False, PROFILE)
app.initQgis()
os.environ.pop("PGOPTIONS", None)

# Cas 1 : connexion ouverte AVANT la pose de PGOPTIONS (attendu : NULL).
keep = edit("cas1_avant", uri(QgsDataSourceUri.SslDisable), "cas1")

os.environ["PGOPTIONS"] = f"-c app.current_user={EMAIL}"

# Cas 2 : même conninfo que le cas 1 -> pool QGIS, connexion réutilisée ? (à documenter)
edit("cas2_meme_conninfo", uri(QgsDataSourceUri.SslDisable), "cas2")
# Cas 3 : conninfo différent (sslmode=require) -> nouvelle connexion (attendu : EMAIL).
edit("cas3_ssl_require", uri(QgsDataSourceUri.SslRequire), "cas3")

# Cas 4 : authcfg Basic + sslmode=require (attendu : EMAIL).
am = QgsApplication.authManager()
am.setMasterPassword("spike", True)
cfg = QgsAuthMethodConfig("Basic")
cfg.setName("spike_basic")
cfg.setConfig("username", "spike_editor")
cfg.setConfig("password", "spike")
am.storeAuthenticationConfig(cfg)
edit("cas4_authcfg_require", uri(QgsDataSourceUri.SslRequire, cfg.id()), "cas4")

app.exitQgis()
print("SPIKE_DONE")
sys.exit(0)
```

Le copier dans `/mnt/c/Users/SimonDucorneau/AppData/Local/Temp/spike_pgoptions/spike_pgoptions.py`.

- [ ] **Step 4 : Lancer le script avec le Python de QGIS Windows**

```bash
cd /mnt/c/Users/SimonDucorneau/AppData/Local/Temp/spike_pgoptions
cmd.exe /c '"C:\Program Files\QGIS 3.44.6\bin\python-qgis.bat" spike_pgoptions.py'
```
Attendu : 4 lignes `casN_…: commit=True`, puis `SPIKE_DONE`. Si `localhost:5433` est injoignable depuis Windows, remplacer `localhost` par l'IP WSL (`hostname -I | cut -d' ' -f1`) dans `uri()` et relancer. Pour le cas 3, `sslmode=require` ne vérifie pas le nom du certificat.

- [ ] **Step 5 : Lire le verdict côté serveur**

```bash
docker exec spike-pgoptions psql -U postgres -d spike -c "SELECT label, app_user, app_name, ssl, pid FROM public.spike_log ORDER BY at"
```
Réussite : `cas3` **et** `cas4` ont `app_user = spike.user@constructel.be`. Le résultat de `cas2` est consigné tel quel (comportement du pool QGIS).
Échec : `cas3` ou `cas4` à NULL. Dans ce cas, **STOP** : ne pas commencer Task 3, revenir en conception avec Simon (piste de repli : fichier de service `pg_service.conf` avec `options=`).

- [ ] **Step 6 : Nettoyer**

```bash
docker stop spike-pgoptions
rm -rf /mnt/c/Users/SimonDucorneau/AppData/Local/Temp/spike_pgoptions
```
Le profil temporaire `spike_pgoptions_profile_*` se trouve sous `%TEMP%`. Le supprimer :
```bash
rm -rf /mnt/c/Users/SimonDucorneau/AppData/Local/Temp/spike_pgoptions_profile_*
```

- [ ] **Step 7 : Consigner et committer le résultat**

Écrire `docs/superpowers/specs/2026-10-15-bridge-audit-email-spike-results.md` dans le worktree Bridge : date, version QGIS, sortie brute des Steps 4 et 5, verdict par cas, conséquence pour la conception (cas 2 : les couches ouvertes avant la pose gardent une connexion sans adresse jusqu'au redémarrage de QGIS ; c'est ce que couvre le cache `constructel_bridge/audit_email`).

```bash
cd /home/sdadmin/projects/qgis_repo/.worktrees/feat-bridge-audit-email
git add docs/superpowers/specs/2026-10-15-bridge-audit-email-spike-results.md
git commit -m "docs(spike): PGOPTIONS transmis par le fournisseur PostgreSQL QGIS Windows

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2 : Migration Farois 453 + retour arrière + test jetable

**Files:**
- Create : `sql/migrations/453_audit_status_history_source_email.sql`
- Create : `sql/migrations/453r_rollback_audit_status_history_source_email.sql`
- Create : `sql/99_validation/tests/099m_453_views_fingerprint.sql` (empreinte des 3 vues, réutilisée en prod en Task 6)
- Create : `sql/99_validation/tests/099m_test_453_jetable.sh`
(tous dans le worktree Farois `/home/sdadmin/projects/Farois/.worktrees/feat-453-status-history-source`)

**Interfaces:**
- Consumes : rien.
- Produces : `audit.status_history.source` de type `character varying(255)` ; les 3 vues dépendantes identiques (définition, options, propriétaire, ACL, commentaires).

- [ ] **Step 1 : Créer le worktree Farois et confirmer le numéro**

```bash
cd /home/sdadmin/projects/Farois
git fetch origin
git worktree add .worktrees/feat-453-status-history-source -b feat/453-status-history-source origin/main
git ls-tree --name-only origin/main sql/migrations/ | sed 's#.*/##' | grep -E '^45[0-9]_'
```
Attendu : la plus haute est `452_…`. Si un `453_` existe déjà, prendre le prochain numéro libre et le reporter partout dans ce plan.

- [ ] **Step 2 : Écrire l'empreinte et le test jetable (il échouera tant que les migrations n'existent pas)**

`sql/99_validation/tests/099m_453_views_fingerprint.sql` (lecture seule ; une ligne : md5 de la définition, des options, du propriétaire, de l'ACL complète avec grantor et des commentaires des 3 vues) :

```sql
SELECT md5(COALESCE(string_agg(line, E'\n' ORDER BY line), '')) FROM (
  SELECT concat_ws('|', n.nspname, c.relname, pg_get_viewdef(c.oid), c.reloptions::text,
         pg_get_userbyid(c.relowner), obj_description(c.oid, 'pg_class'),
         (SELECT string_agg(e, ',' ORDER BY e) FROM (
            SELECT concat_ws(':', pg_get_userbyid(a.grantee), a.privilege_type, a.is_grantable,
                             pg_get_userbyid(a.grantor)) AS e
              FROM aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) a) acl),
         (SELECT string_agg(concat_ws('=', att.attname, col_description(c.oid, att.attnum)), ',' ORDER BY att.attnum)
            FROM pg_attribute att WHERE att.attrelid = c.oid AND att.attnum > 0
             AND col_description(c.oid, att.attnum) IS NOT NULL)) AS line
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE c.relkind = 'v'
     AND c.relname IN ('v_beon_status_changes', 'v_status_history_scoped', 'v_dp_retenus_recul_manuel')) x;
```

`sql/99_validation/tests/099m_test_453_jetable.sh` :

```bash
#!/usr/bin/env bash
# Base JETABLE uniquement (installation Farois complète). REPO pointe sur le
# dossier sql/ lu par la commande PSQL.
# Usage : ALLOW_DESTRUCTIVE=1 REPO=/opt/farois/sql PSQL='psql -U postgres -d farois_jetable453' bash ce_fichier.sh
set -euo pipefail
if [ "${ALLOW_DESTRUCTIVE:-0}" != "1" ]; then
    echo 'ERREUR : ALLOW_DESTRUCTIVE=1 obligatoire, base jetable uniquement' >&2
    exit 3
fi
: "${PSQL:?Commande psql isolée requise}"
: "${REPO:?Dossier sql contenant migrations/ requis}"
q() { $PSQL -X -v ON_ERROR_STOP=1 -qAt -c "$1"; }
run() { $PSQL -X -v ON_ERROR_STOP=1 -v op=wyre -f "$REPO/migrations/$1"; }
fail() { echo "TEST 453 KO: $*" >&2; exit 1; }
DB=$(q 'SELECT current_database()')
case "$DB" in farois_ftth|farois_ftth_prod|postgres) fail 'base métier refusée';; esac
FWD=453_audit_status_history_source_email.sql
RBK=453r_rollback_audit_status_history_source_email.sql
VIEWS="'v_beon_status_changes','v_status_history_scoped','v_dp_retenus_recul_manuel'"

col_type() {
q "SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid='audit.status_history'::regclass AND attname='source'"
}
views_fp() { $PSQL -X -v ON_ERROR_STOP=1 -qAt -f "$REPO/99_validation/tests/099m_453_views_fingerprint.sql"; }
[ "$(q "SELECT count(*) FROM pg_class WHERE relkind='v' AND relname IN ($VIEWS)")" = 3 ] || fail '3 vues attendues dans la base jetable'

# Base de référence : état 30 caractères (l'installation a pu appliquer 453).
run "$RBK" > /tmp/t453_initial_rollback.log 2>&1 || fail 'rollback initial'
[ "$(col_type)" = 'character varying(30)' ] || fail "type de base inattendu: $(col_type)"
BASE_VIEWS=$(views_fp)

# Aller.
run "$FWD" > /tmp/t453_forward.log 2>&1 || fail 'migration 453'
[ "$(col_type)" = 'character varying(255)' ] || fail "type après 453: $(col_type)"
[ "$(views_fp)" = "$BASE_VIEWS" ] || fail 'vues modifiées par 453 (définition/options/ACL/commentaires)'

# Rejeu idempotent.
run "$FWD" > /tmp/t453_replay.log 2>&1 || fail 'rejeu 453'
[ "$(col_type)" = 'character varying(255)' ] || fail 'type après rejeu'
[ "$(views_fp)" = "$BASE_VIEWS" ] || fail 'vues modifiées par le rejeu'

# Une adresse de 35 caractères passe.
q "SET session_replication_role = replica; INSERT INTO audit.status_history (id, entity_type, entity_id, new_status, source) VALUES (gen_random_uuid(), 'test453', gen_random_uuid(), 'TODO', 'prenom.nom-tres-long@constructel.be')" > /dev/null || fail 'insertion adresse 35 car.'

# Le retour arrière refuse de tronquer.
if run "$RBK" > /tmp/t453_rollback_refus.log 2>&1; then fail 'rollback accepté malgré une valeur > 30'; fi
[ "$(col_type)" = 'character varying(255)' ] || fail 'rollback refusé a quand même modifié le type'
q "DELETE FROM audit.status_history WHERE entity_type = 'test453'" > /dev/null

# Garde : droit par colonne sur une vue dépendante -> échec complet, rien ne change.
VSCHEMA=$(q "SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relname='v_status_history_scoped' AND c.relkind='v'")
run "$RBK" > /tmp/t453_rbk_before_guards.log 2>&1 || fail 'rollback avant gardes'
q "GRANT SELECT (source) ON \"$VSCHEMA\".v_status_history_scoped TO ftth_editor" > /dev/null
if run "$FWD" > /tmp/t453_guard_colacl.log 2>&1; then fail 'droit par colonne non détecté'; fi
[ "$(col_type)" = 'character varying(30)' ] || fail 'garde colonne : type modifié malgré échec'
q "REVOKE SELECT (source) ON \"$VSCHEMA\".v_status_history_scoped FROM ftth_editor" > /dev/null

# Garde : vue imbriquée inattendue -> échec complet.
q "CREATE VIEW public.t453_nested AS SELECT * FROM \"$VSCHEMA\".v_status_history_scoped" > /dev/null
if run "$FWD" > /tmp/t453_guard_nested.log 2>&1; then fail 'vue imbriquée non détectée'; fi
[ "$(col_type)" = 'character varying(30)' ] || fail 'garde imbriquée : type modifié malgré échec'
q "DROP VIEW public.t453_nested" > /dev/null
[ "$(views_fp)" = "$BASE_VIEWS" ] || fail 'vues altérées par les tests de garde'

# Retour arrière exact puis réapplication.
run "$FWD" > /tmp/t453_reapply.log 2>&1 || fail 'réapplication'
run "$RBK" > /tmp/t453_rollback.log 2>&1 || fail 'rollback final'
[ "$(col_type)" = 'character varying(30)' ] || fail 'type après rollback'
[ "$(views_fp)" = "$BASE_VIEWS" ] || fail 'vues modifiées par le rollback'
run "$FWD" > /tmp/t453_final.log 2>&1 || fail 'application finale'
echo 'TEST 453 OK : type 255, vues identiques, idempotence, refus de troncature, gardes'
```

- [ ] **Step 3 : Monter une base Farois jetable et constater l'échec du test**

```bash
cd /home/sdadmin/projects/Farois/.worktrees/feat-453-status-history-source
docker run -d --rm --name farois-jetable453 \
  -e POSTGRES_PASSWORD=jetable -e POSTGRES_DB=farois_jetable453 \
  -e FAROIS_OPERATOR_SCHEMA=wyre -e FAROIS_AUTO_INSTALL=true \
  -v "$PWD/sql:/opt/farois/sql:ro" \
  ftth-postgres:17.3.5-farois
```
Attendre la fin de l'installation complète (plusieurs minutes ; surveiller avec Monitor) :
```bash
docker exec farois-jetable453 psql -U postgres -d farois_jetable453 -tAc \
  "SELECT count(*) FROM pg_class WHERE relkind='v' AND relname IN ('v_beon_status_changes','v_status_history_scoped','v_dp_retenus_recul_manuel')"
```
Attendu à terme : `3`. Rappel mémoire : après l'installation, l'entrypoint redémarre PostgreSQL ; attendre que `pg_isready` réponde de nouveau. Note : 451 échouera pendant l'installation (refus en présence de 442) ; c'est sans rapport avec ce test.

```bash
docker cp sql/99_validation/tests/099m_test_453_jetable.sh farois-jetable453:/tmp/
docker exec -e ALLOW_DESTRUCTIVE=1 -e REPO=/opt/farois/sql -e PSQL='psql -U postgres -d farois_jetable453' farois-jetable453 bash /tmp/099m_test_453_jetable.sh
```
Attendu : `TEST 453 KO: rollback initial` (fichiers absents).

- [ ] **Step 4 : Écrire la migration 453**

`sql/migrations/453_audit_status_history_source_email.sql` :

```sql
-- Migration 453 : audit.status_history.source VARCHAR(30) -> VARCHAR(255).
-- Prérequis de « adresse mail de l'auteur sur chaque modification QGIS »
-- (qgis_repo docs/superpowers/specs/2026-10-15-bridge-audit-email-design.md) :
-- Constructel Bridge pose app.current_user=<email> sur les connexions QGIS et
-- universal_trigger_before l'écrit dans source. 5 adresses actives dépassent
-- 30 caractères : sans cette migration, leurs changements de statut échouent.
-- Les vues dépendantes sont capturées depuis le catalogue puis recréées à
-- l'identique (définition, options, propriétaire, ACL, commentaires). Toute
-- forme non gérée (droit par colonne, défaut, trigger, règle, dépendant
-- imbriqué) fait échouer la migration entière : jamais de perte silencieuse.
-- N+1 vérifié contre origin/main (452) le 2026-10-15. Idempotente.
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
SET LOCAL search_path = pg_catalog, pg_temp;

CREATE TEMP TABLE _453_views ON COMMIT DROP AS
SELECT c.oid, n.nspname AS schema_name, c.relname AS view_name,
       pg_get_viewdef(c.oid) AS definition, c.reloptions, c.relowner,
       pg_get_userbyid(c.relowner) AS owner_name,
       obj_description(c.oid, 'pg_class') AS view_comment,
       COALESCE(c.relacl, acldefault('r', c.relowner)) AS acl
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE c.relkind = 'v'
   AND c.oid IN (
       SELECT r.ev_class FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid
        WHERE d.refobjid = 'audit.status_history'::regclass
          AND d.refobjsubid = (SELECT attnum FROM pg_attribute
                                WHERE attrelid = 'audit.status_history'::regclass
                                  AND attname = 'source')
          AND r.ev_class <> 'audit.status_history'::regclass);

CREATE TEMP TABLE _453_col_comments ON COMMIT DROP AS
SELECT v.oid, a.attname, col_description(v.oid, a.attnum) AS col_comment
  FROM _453_views v JOIN pg_attribute a ON a.attrelid = v.oid
 WHERE a.attnum > 0 AND col_description(v.oid, a.attnum) IS NOT NULL;

DO $$
DECLARE v record;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_attribute a JOIN _453_views v ON a.attrelid = v.oid
                WHERE a.attacl IS NOT NULL) THEN
        RAISE EXCEPTION '453 : droit par colonne sur une vue dépendante, non géré';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_attrdef d JOIN _453_views v ON d.adrelid = v.oid) THEN
        RAISE EXCEPTION '453 : valeur par défaut sur une vue dépendante, non gérée';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_trigger t JOIN _453_views v ON t.tgrelid = v.oid) THEN
        RAISE EXCEPTION '453 : trigger sur une vue dépendante, non géré';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_rewrite r JOIN _453_views v ON r.ev_class = v.oid
                WHERE r.rulename <> '_RETURN') THEN
        RAISE EXCEPTION '453 : règle sur une vue dépendante, non gérée';
    END IF;
    -- Pas de CASCADE : un dépendant imbriqué fait échouer le DROP, donc la migration.
    FOR v IN SELECT * FROM _453_views LOOP
        EXECUTE format('DROP VIEW %I.%I', v.schema_name, v.view_name);
    END LOOP;
END $$;

ALTER TABLE audit.status_history ALTER COLUMN source TYPE VARCHAR(255);

DO $$
DECLARE v record; g record; c record; target regclass;
BEGIN
    FOR v IN SELECT * FROM _453_views ORDER BY schema_name, view_name LOOP
        EXECUTE format('CREATE VIEW %I.%I%s AS %s', v.schema_name, v.view_name,
            CASE WHEN v.reloptions IS NULL THEN ''
                 ELSE ' WITH (' || array_to_string(v.reloptions, ', ') || ')' END,
            v.definition);
        target := format('%I.%I', v.schema_name, v.view_name)::regclass;
        EXECUTE format('ALTER VIEW %s OWNER TO %I', target, v.owner_name);
        -- Retirer ce que les privilèges par défaut auraient ajouté, puis
        -- reposer exactement l'ACL capturée.
        FOR g IN
            SELECT a.grantee, a.privilege_type
              FROM pg_class pc, aclexplode(COALESCE(pc.relacl, acldefault('r', pc.relowner))) a
             WHERE pc.oid = target
            EXCEPT
            SELECT a.grantee, a.privilege_type FROM aclexplode(v.acl) a
        LOOP
            EXECUTE format('REVOKE %s ON %s FROM %s', g.privilege_type, target,
                CASE WHEN g.grantee = 0 THEN 'PUBLIC' ELSE quote_ident(pg_get_userbyid(g.grantee)) END);
        END LOOP;
        FOR g IN SELECT a.grantee, a.privilege_type, a.is_grantable FROM aclexplode(v.acl) a LOOP
            EXECUTE format('GRANT %s ON %s TO %s%s', g.privilege_type, target,
                CASE WHEN g.grantee = 0 THEN 'PUBLIC' ELSE quote_ident(pg_get_userbyid(g.grantee)) END,
                CASE WHEN g.is_grantable THEN ' WITH GRANT OPTION' ELSE '' END);
        END LOOP;
        IF v.view_comment IS NOT NULL THEN
            EXECUTE format('COMMENT ON VIEW %s IS %L', target, v.view_comment);
        END IF;
        FOR c IN SELECT * FROM _453_col_comments WHERE oid = v.oid LOOP
            EXECUTE format('COMMENT ON COLUMN %s.%I IS %L', target, c.attname, c.col_comment);
        END LOOP;
    END LOOP;

    IF (SELECT format_type(atttypid, atttypmod) FROM pg_attribute
         WHERE attrelid = 'audit.status_history'::regclass AND attname = 'source')
       <> 'character varying(255)' THEN
        RAISE EXCEPTION '453 : contrôle final, type inattendu';
    END IF;
    IF EXISTS (
        SELECT 1 FROM _453_views v
         WHERE NOT EXISTS (
             SELECT 1 FROM pg_class pc JOIN pg_namespace pn ON pn.oid = pc.relnamespace
              WHERE pn.nspname = v.schema_name AND pc.relname = v.view_name AND pc.relkind = 'v'
                AND pc.relowner = v.relowner
                AND pc.reloptions IS NOT DISTINCT FROM v.reloptions
                AND ARRAY(SELECT (a.grantee, a.privilege_type, a.is_grantable)::text
                            FROM aclexplode(COALESCE(pc.relacl, acldefault('r', pc.relowner))) a ORDER BY 1)
                  = ARRAY(SELECT (a.grantee, a.privilege_type, a.is_grantable)::text
                            FROM aclexplode(v.acl) a ORDER BY 1))) THEN
        RAISE EXCEPTION '453 : contrôle final, une vue recréée diffère (propriétaire, options ou ACL)';
    END IF;
END $$;

COMMENT ON COLUMN audit.status_history.source IS
'Source du changement de statut : BEON, AUTO, login PostgreSQL ou adresse mail de l''auteur (app.current_user). Élargie à 255 par la mig 453.';
COMMIT;
```

Note : le commentaire de colonne posé en fin de fichier est voulu (documentation) ; le rollback le retire.

- [ ] **Step 5 : Écrire le retour arrière 453r**

`sql/migrations/453r_rollback_audit_status_history_source_email.sql` : **même fichier que 453**, avec exactement ces différences :
1. En-tête :
```sql
-- Rollback 453 : audit.status_history.source VARCHAR(255) -> VARCHAR(30).
-- Refuse (RAISE) si une valeur dépasse 30 caractères : jamais de troncature.
-- Mêmes gardes et même recréation à l'identique des vues dépendantes que 453.
```
2. Juste après `SET LOCAL search_path = pg_catalog, pg_temp;`, ajouter :
```sql
DO $$
DECLARE n bigint;
BEGIN
    SELECT count(*) INTO n FROM audit.status_history WHERE length(source) > 30;
    IF n > 0 THEN
        RAISE EXCEPTION '453r : % valeur(s) de source dépassent 30 caractères, retour arrière refusé (aucune troncature)', n;
    END IF;
END $$;
```
3. `ALTER TABLE audit.status_history ALTER COLUMN source TYPE VARCHAR(30);`
4. Contrôle final : `<> 'character varying(30)'` et messages préfixés `453r :` au lieu de `453 :`.
5. Remplacer le `COMMENT ON COLUMN … IS '…'` final par :
```sql
COMMENT ON COLUMN audit.status_history.source IS NULL;
```

Écrire le fichier **en entier** (pas de `\i` vers 453) : le runner joue chaque fichier isolément.

- [ ] **Step 6 : Relancer le test jetable**

```bash
docker cp sql/99_validation/tests/099m_test_453_jetable.sh farois-jetable453:/tmp/
docker exec -e ALLOW_DESTRUCTIVE=1 -e REPO=/opt/farois/sql -e PSQL='psql -U postgres -d farois_jetable453' farois-jetable453 bash /tmp/099m_test_453_jetable.sh
```
Le volume `sql/` est monté en lecture seule et reflète les fichiers du worktree en direct.
Attendu : `TEST 453 OK : type 255, vues identiques, idempotence, refus de troncature, gardes`. En cas d'échec, lire le `/tmp/t453_*.log` correspondant dans le conteneur (`docker exec farois-jetable453 cat /tmp/t453_forward.log`).

- [ ] **Step 7 : Arrêter la base jetable et committer**

```bash
docker stop farois-jetable453
git add sql/migrations/453_audit_status_history_source_email.sql \
        sql/migrations/453r_rollback_audit_status_history_source_email.sql \
        sql/99_validation/tests/099m_453_views_fingerprint.sql \
        sql/99_validation/tests/099m_test_453_jetable.sh
git commit -m "feat(audit): mig 453 élargit audit.status_history.source à 255 (adresse mail auteur QGIS)

Vues dépendantes recréées à l'identique depuis le catalogue ; gardes qui font
échouer la migration sur toute forme non gérée ; 453r refuse de tronquer.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3 : Fonctions pures `is_valid_audit_email` et `build_pgoptions`

**Files:**
- Modify : `plugin-repo/packages/constructel_bridge/bridge_identity.py` (import `re` en tête ; nouvelles fonctions en fin de fichier)
- Test : `plugin-repo/packages/constructel_bridge_tests/test_bridge_identity.py`

**Interfaces:**
- Consumes : rien.
- Produces :
  - `AUDIT_EMAIL_MAX_LEN: int = 255`
  - `is_valid_audit_email(email: object) -> bool`
  - `build_pgoptions(existing: str | None, email: object) -> str | None`

- [ ] **Step 1 : Écrire les tests qui échouent**

En tête de `test_bridge_identity.py` : ajouter `import pytest` sous `import base64`, et ajouter `build_pgoptions` et `is_valid_audit_email` à l'import `from constructel_bridge.bridge_identity import (...)` (liste alphabétique existante). Puis en fin de fichier :

```python
# --- is_valid_audit_email / build_pgoptions (2026-10-15) ----------------


@pytest.mark.parametrize("email", [
    "simonducourneau@constructel.be",
    "Jean.Dupont+qgis@constructel.be",
    "a_b-c%d@sub.example.org",
])
def test_is_valid_audit_email_accepts(email):
    assert is_valid_audit_email(email) is True


@pytest.mark.parametrize("email", [
    None, "", "nobody", "x@y", "a b@constructel.be", "o'brien@constructel.be",
    "a\\b@constructel.be", "a,b@constructel.be", 'a"b@constructel.be',
    "a" * 250 + "@constructel.be", 42,
])
def test_is_valid_audit_email_rejects(email):
    assert is_valid_audit_email(email) is False


EMAIL = "simonducourneau@constructel.be"


def test_build_pgoptions_from_nothing():
    assert build_pgoptions(None, EMAIL) == f"-c app.current_user={EMAIL}"
    assert build_pgoptions("", EMAIL) == f"-c app.current_user={EMAIL}"


def test_build_pgoptions_keeps_existing_options():
    assert build_pgoptions("-c search_path=wyre", EMAIL) == (
        f"-c search_path=wyre -c app.current_user={EMAIL}"
    )


def test_build_pgoptions_replaces_previous_app_user():
    existing = "-c app.current_user=old@constructel.be -c statement_timeout=0"
    assert build_pgoptions(existing, EMAIL) == (
        f"-c statement_timeout=0 -c app.current_user={EMAIL}"
    )


def test_build_pgoptions_replaces_compact_and_long_forms():
    assert build_pgoptions("-capp.current_user=old@x.be", EMAIL) == f"-c app.current_user={EMAIL}"
    assert build_pgoptions("--app.current_user=old@x.be", EMAIL) == f"-c app.current_user={EMAIL}"


def test_build_pgoptions_invalid_email_leaves_existing_untouched():
    assert build_pgoptions("-c search_path=wyre", "pas une adresse") == "-c search_path=wyre"
    assert build_pgoptions(None, None) is None


def test_build_pgoptions_is_idempotent():
    once = build_pgoptions("-c search_path=wyre", EMAIL)
    assert build_pgoptions(once, EMAIL) == once
```

- [ ] **Step 2 : Lancer les tests, constater l'échec**

```bash
cd /home/sdadmin/projects/qgis_repo/.worktrees/feat-bridge-audit-email
/home/sdadmin/.venvs/bridge0-tests/bin/pytest plugin-repo/packages/constructel_bridge_tests/test_bridge_identity.py -q
```
Attendu : erreur d'import `cannot import name 'build_pgoptions'`.

- [ ] **Step 3 : Implémenter**

Dans `bridge_identity.py`, ajouter `import re` sous `import base64`, puis en fin de fichier :

```python
AUDIT_EMAIL_MAX_LEN = 255
_AUDIT_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
# Any previous app.current_user option, in libpq's "-c name=value",
# "-cname=value" or "--name=value" forms.
_PGOPTIONS_APP_USER_RE = re.compile(r"(?<!\S)(?:-c\s*|--)app\.current_user=\S*")


def is_valid_audit_email(email) -> bool:
    """True if *email* may be passed verbatim in libpq PGOPTIONS.

    Whitelist only: no whitespace, quote, comma or backslash can reach the
    libpq options parser (which splits on whitespace and treats backslash
    as an escape). The address is DECLARED by the workstation: traceability
    only, never a proof of identity (spec 2026-10-15).
    """
    return (
        isinstance(email, str)
        and 0 < len(email) <= AUDIT_EMAIL_MAX_LEN
        and _AUDIT_EMAIL_RE.fullmatch(email) is not None
    )


def build_pgoptions(existing, email):
    """Return the PGOPTIONS value carrying ``app.current_user=<email>``.

    Keeps every option already set on the workstation, drops any previous
    app.current_user option so values never pile up, and appends the new
    one. An invalid or missing *email* returns *existing* unchanged
    (possibly None): an invalid address is never sent.
    """
    if not is_valid_audit_email(email):
        return existing
    kept = " ".join(_PGOPTIONS_APP_USER_RE.sub(" ", existing or "").split())
    option = f"-c app.current_user={email}"
    return f"{kept} {option}" if kept else option
```

- [ ] **Step 4 : Relancer les tests**

```bash
/home/sdadmin/.venvs/bridge0-tests/bin/pytest plugin-repo/packages/constructel_bridge_tests/test_bridge_identity.py -q
```
Attendu : tout passe (anciens tests compris).

- [ ] **Step 5 : Committer**

```bash
git add plugin-repo/packages/constructel_bridge/bridge_identity.py plugin-repo/packages/constructel_bridge_tests/test_bridge_identity.py
git commit -m "feat(bridge): build_pgoptions + is_valid_audit_email (adresse mail auteur)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4 : Câblage dans `bridge_plugin.py`

**Files:**
- Modify : `plugin-repo/packages/constructel_bridge/bridge_plugin.py`
  - import `.bridge_identity` (ligne ~44)
  - constantes après `MTLS_AUTH_CFG_NAME` (ligne ~56)
  - fonctions de module après `PLUGIN_VERSION = _get_plugin_version()` (ligne ~651)
  - `ConstructelBridgePlugin.__init__` (ligne ~656)
  - `initGui` (ligne ~669)
  - `_register_bridge_user` (lignes ~1276-1319)
  - `_on_before_commit` (lignes ~1994-2023)
  - `_run_onboarding` (lignes ~2461-2472)
- Create : `plugin-repo/packages/constructel_bridge_tests/test_bridge_audit_email.py`

**Interfaces:**
- Consumes (Task 3) : `build_pgoptions(existing, email)`, `is_valid_audit_email(email)`.
- Produces :
  - `AUDIT_EMAIL_KEY = "constructel_bridge/audit_email"`, `AUDIT_EMAIL_SWITCH_KEY = "constructel_bridge/audit_email_pgoptions"`
  - `_apply_audit_identity(email, log) -> bool` (fonction de module ; `log(message, level)`)
  - `_apply_cached_audit_identity(log) -> bool` (fonction de module)
  - attribut `ConstructelBridgePlugin._bridge_user_email: Optional[str]`
  - méthode `ConstructelBridgePlugin._refresh_audit_identity() -> None`

- [ ] **Step 1 : Écrire les tests qui échouent**

`test_bridge_audit_email.py` :

```python
"""Stub-level tests: Bridge sets PGOPTIONS so that every NEW libpq
connection of the QGIS process carries app.current_user=<email>
(spec 2026-10-15-bridge-audit-email-design.md). No real QGIS.

Same fixture pattern as test_bridge1b_wiring.py: the stub package lives in
constructel_bridge_tests/stubs/ and each test re-imports bridge_plugin so
the stub's shared QgsSettings store starts empty.
"""
import base64
import importlib
import inspect
import json
import os
import sys
import types
from pathlib import Path

import pytest

STUBS_DIR = Path(__file__).resolve().parent / "stubs"
PLUGIN_DIR = Path(__file__).resolve().parent.parent / "constructel_bridge"
CREDENTIALS_PATH = PLUGIN_DIR / "credentials.json"
_FIXTURE_CREDENTIALS = {
    "wyre": {
        "host": "test-host.invalid",
        "port": 5432,
        "dbname": "test_db",
        "user": "test_user",
        "password": base64.b64encode(b"test").decode(),
    }
}
EMAIL = "simonducourneau@constructel.be"


@pytest.fixture
def bp(monkeypatch):
    if str(STUBS_DIR) not in sys.path:
        sys.path.insert(0, str(STUBS_DIR))
    pre_existing = CREDENTIALS_PATH.exists()
    if not pre_existing:
        CREDENTIALS_PATH.write_text(json.dumps(_FIXTURE_CREDENTIALS))
    # setenv puis delenv : monkeypatch mémorise l'état initial et le restaure à
    # la fin du test, même si le code testé écrit os.environ directement.
    monkeypatch.setenv("PGOPTIONS", "placeholder")
    monkeypatch.delenv("PGOPTIONS")
    for mod_name in list(sys.modules):
        if mod_name == "constructel_bridge.bridge_plugin" or mod_name.startswith("qgis"):
            del sys.modules[mod_name]
    module = importlib.import_module("constructel_bridge.bridge_plugin")
    yield module
    if not pre_existing:
        CREDENTIALS_PATH.unlink()


class _Log:
    def __init__(self):
        self.records = []

    def __call__(self, message, level=0):
        self.records.append((message, level))


class _FakeCursor:
    """Answers the queries of _register_bridge_user / _refresh_audit_identity."""

    def __init__(self, existing_row, inserted_row=None, refreshed_email=None):
        self.existing_row = existing_row
        self.inserted_row = inserted_row
        self.refreshed_email = refreshed_email
        self.executed = []
        self._next = None

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if "FROM ref.users WHERE username" in sql:
            self._next = self.existing_row
        elif "INSERT INTO ref.users" in sql:
            self._next = self.inserted_row
        elif "SELECT email FROM ref.users WHERE id" in sql:
            self._next = (self.refreshed_email,)
        else:
            self._next = None

    def fetchone(self):
        return self._next

    def close(self):
        pass


class _FakeConn:
    closed = False

    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def _fake_plugin(bp, cursor, username="SimonDucourneau"):
    plugin = types.SimpleNamespace(
        _conn=_FakeConn(cursor), _bridge_user=None, _bridge_user_id=None,
        _bridge_user_email=None, _log=_Log(),
    )
    plugin._get_qgis_username = lambda: username
    plugin._set_app_user = lambda value: plugin.__dict__.setdefault("app_user_set", value)
    return plugin


# --- _apply_audit_identity ---------------------------------------------

def test_apply_sets_pgoptions_and_caches_email(bp):
    from qgis.core import QgsSettings
    log = _Log()
    assert bp._apply_audit_identity(EMAIL, log) is True
    import os
    assert os.environ["PGOPTIONS"] == f"-c app.current_user={EMAIL}"
    assert QgsSettings().value(bp.AUDIT_EMAIL_KEY) == EMAIL


def test_apply_preserves_workstation_pgoptions(bp, monkeypatch):
    import os
    monkeypatch.setenv("PGOPTIONS", "-c search_path=wyre")
    assert bp._apply_audit_identity(EMAIL, _Log()) is True
    assert os.environ["PGOPTIONS"] == f"-c search_path=wyre -c app.current_user={EMAIL}"


@pytest.mark.parametrize("bad", [None, "", "pas une adresse", "a b@constructel.be"])
def test_apply_invalid_email_sets_nothing_and_warns(bp, bad):
    import os
    from qgis.core import Qgis, QgsSettings
    log = _Log()
    assert bp._apply_audit_identity(bad, log) is False
    assert "PGOPTIONS" not in os.environ
    assert QgsSettings().value(bp.AUDIT_EMAIL_KEY) is None
    assert any(level == Qgis.Warning for _, level in log.records)


@pytest.mark.parametrize("off", [False, "false"])
def test_switch_off_is_respected_bool_or_string(bp, off):
    import os
    from qgis.core import QgsSettings
    QgsSettings().setValue(bp.AUDIT_EMAIL_SWITCH_KEY, off)
    assert bp._apply_audit_identity(EMAIL, _Log()) is False
    assert "PGOPTIONS" not in os.environ


def test_cached_identity_applied_at_startup(bp):
    import os
    from qgis.core import QgsSettings
    assert bp._apply_cached_audit_identity(_Log()) is False  # rien en cache
    QgsSettings().setValue(bp.AUDIT_EMAIL_KEY, EMAIL)
    assert bp._apply_cached_audit_identity(_Log()) is True
    assert os.environ["PGOPTIONS"] == f"-c app.current_user={EMAIL}"


def test_initgui_applies_cache_before_anything_else(bp):
    src = inspect.getsource(bp.ConstructelBridgePlugin.initGui)
    first_call = src.index("_apply_cached_audit_identity(")
    assert first_call < src.index("init_language(")
    assert first_call < src.index("self._auto_connect(")


# --- _register_bridge_user ---------------------------------------------

def test_register_existing_user_applies_email(bp):
    import os
    cur = _FakeCursor(existing_row=("11111111-1111-1111-1111-111111111111", "SimonDucourneau", EMAIL))
    plugin = _fake_plugin(bp, cur)
    bp.ConstructelBridgePlugin._register_bridge_user(plugin)
    assert plugin._bridge_user_email == EMAIL
    assert os.environ["PGOPTIONS"] == f"-c app.current_user={EMAIL}"
    assert plugin.app_user_set == EMAIL


def test_register_new_user_applies_returned_email(bp):
    import os
    cur = _FakeCursor(existing_row=None,
                      inserted_row=("22222222-2222-2222-2222-222222222222", "newbie@constructel.be"))
    plugin = _fake_plugin(bp, cur, username="newbie")
    bp.ConstructelBridgePlugin._register_bridge_user(plugin)
    assert plugin._bridge_user_email == "newbie@constructel.be"
    assert os.environ["PGOPTIONS"] == "-c app.current_user=newbie@constructel.be"
    assert any("RETURNING id, email" in sql for sql, _ in cur.executed)


def test_register_user_without_email_does_not_block(bp):
    import os
    cur = _FakeCursor(existing_row=("33333333-3333-3333-3333-333333333333", "noemail", None))
    plugin = _fake_plugin(bp, cur, username="noemail")
    bp.ConstructelBridgePlugin._register_bridge_user(plugin)
    assert "PGOPTIONS" not in os.environ
    assert plugin.app_user_set == "noemail"  # repli historique : nom d'utilisateur
    assert plugin._bridge_user_id == "33333333-3333-3333-3333-333333333333"


# --- _refresh_audit_identity (après l'assistant d'accueil) ---------------

def test_refresh_after_onboarding_applies_new_email(bp):
    import os
    cur = _FakeCursor(existing_row=None, refreshed_email="nouvelle.adresse@constructel.be")
    plugin = _fake_plugin(bp, cur)
    plugin._bridge_user_id = "11111111-1111-1111-1111-111111111111"
    plugin._bridge_user_email = EMAIL
    bp.ConstructelBridgePlugin._refresh_audit_identity(plugin)
    assert plugin._bridge_user_email == "nouvelle.adresse@constructel.be"
    assert os.environ["PGOPTIONS"] == "-c app.current_user=nouvelle.adresse@constructel.be"


def test_run_onboarding_refreshes_identity_after_wizard(bp):
    src = inspect.getsource(bp.ConstructelBridgePlugin._run_onboarding)
    assert src.index("wizard.exec_()") < src.index("self._refresh_audit_identity()")


# --- _on_before_commit --------------------------------------------------

def test_before_commit_tags_bridge_connection_with_email(bp):
    src = inspect.getsource(bp.ConstructelBridgePlugin._on_before_commit)
    assert "self._bridge_user_email or self._bridge_user" in src
```

- [ ] **Step 2 : Lancer les tests, constater l'échec**

```bash
/home/sdadmin/.venvs/bridge0-tests/bin/pytest plugin-repo/packages/constructel_bridge_tests/test_bridge_audit_email.py -q
```
Attendu : échecs `AttributeError: module ... has no attribute '_apply_audit_identity'` (et assimilés).

- [ ] **Step 3 : Import et constantes**

Remplacer :
```python
from .bridge_identity import decode_password, derive_email
```
par :
```python
from .bridge_identity import build_pgoptions, decode_password, derive_email, is_valid_audit_email
```
Après `MTLS_AUTH_CFG_NAME = "constructel_bridge_mtls"`, ajouter :
```python

# Adresse mail de l'utilisateur posee dans PGOPTIONS (app.current_user) pour que
# l'audit Farois enregistre l'auteur des editions QGIS. Tracabilite seulement :
# adresse DECLAREE par le poste, jamais une preuve d'identite (spec 2026-10-15).
AUDIT_EMAIL_KEY = "constructel_bridge/audit_email"
AUDIT_EMAIL_SWITCH_KEY = "constructel_bridge/audit_email_pgoptions"
```

- [ ] **Step 4 : Fonctions de module**

Après `PLUGIN_VERSION = _get_plugin_version()` :
```python


def _apply_audit_identity(email, log) -> bool:
    """Pose PGOPTIONS pour que toute NOUVELLE connexion libpq du processus
    QGIS (fournisseur PostgreSQL compris) porte app.current_user=<email>.

    Les connexions deja ouvertes ne sont pas modifiees (pool QGIS). Ne bloque
    jamais : interrupteur a faux ou adresse invalide -> rien n'est pose, un
    message est journalise et la fonction renvoie False.
    """
    if not QgsSettings().value(AUDIT_EMAIL_SWITCH_KEY, True, type=bool):
        log("Adresse d'audit desactivee (constructel_bridge/audit_email_pgoptions = false)", Qgis.Info)
        return False
    if not is_valid_audit_email(email):
        log(f"Adresse d'audit absente ou invalide ({email!r}) : editions QGIS non attribuees", Qgis.Warning)
        return False
    os.environ["PGOPTIONS"] = build_pgoptions(os.environ.get("PGOPTIONS"), email)
    QgsSettings().setValue(AUDIT_EMAIL_KEY, email)
    log(f"Adresse d'audit posee pour les nouvelles connexions PostgreSQL : {email}", Qgis.Info)
    return True


def _apply_cached_audit_identity(log) -> bool:
    """Au demarrage, avant tout chargement de couche : reutilise l'adresse
    memorisee lors de la derniere connexion Bridge reussie."""
    cached = QgsSettings().value(AUDIT_EMAIL_KEY, "")
    if not cached:
        return False
    return _apply_audit_identity(cached, log)
```

- [ ] **Step 5 : `__init__` et `initGui`**

Dans `__init__`, après `self._bridge_user_id: Optional[str] = None` :
```python
        self._bridge_user_email: Optional[str] = None
```
Dans `initGui`, remplacer :
```python
        """Appele par QGIS au chargement du plugin."""
        init_language()
```
par :
```python
        """Appele par QGIS au chargement du plugin."""
        # Avant tout chargement de couche (projet ouvert au demarrage compris) :
        # les connexions PostgreSQL ouvertes ensuite porteront l'adresse d'audit.
        _apply_cached_audit_identity(self._log)
        init_language()
```

- [ ] **Step 6 : `_register_bridge_user`**

Remplacer le bloc `try:` existant (du premier `cur.execute(` jusqu'à `self._set_app_user(username)`) par :
```python
            cur.execute(
                "SELECT id, username, email FROM ref.users WHERE username = %s AND active = TRUE",
                (username,),
            )
            row = cur.fetchone()

            if row:
                self._bridge_user_id = str(row[0])
                self._bridge_user_email = row[2]
                self._log(tr("user.existing", username=username, user_id=self._bridge_user_id))
            else:
                cur.execute(
                    """
                    INSERT INTO ref.users (username, email, last_name, role)
                    VALUES (%s, %s, %s, 'OPERATOR')
                    ON CONFLICT (username) DO UPDATE
                        SET last_login = NOW(), active = TRUE
                    RETURNING id, email
                    """,
                    (username, derive_email(username), username),
                )
                new_row = cur.fetchone()
                self._bridge_user_id = str(new_row[0])
                self._bridge_user_email = new_row[1]
                self._log(tr("user.created", username=username, user_id=self._bridge_user_id))
                is_new = True

            cur.execute(
                "UPDATE ref.users SET last_login = NOW() WHERE id = %s::uuid",
                (self._bridge_user_id,),
            )
            # Avant _setup_qgis_pg_connection / chargement du projet (cf. _connect).
            _apply_audit_identity(self._bridge_user_email, self._log)
            self._set_app_user(self._bridge_user_email or username)
```

- [ ] **Step 7 : `_refresh_audit_identity` et `_run_onboarding`**

Ajouter la méthode juste après `_set_app_user` :
```python
    def _refresh_audit_identity(self):
        """Relit l'adresse dans ref.users (l'assistant d'accueil peut la
        modifier) et la repose pour les connexions suivantes."""
        if not self._conn or self._conn.closed or not self._bridge_user_id:
            return
        cur = self._conn.cursor()
        try:
            cur.execute("SELECT email FROM ref.users WHERE id = %s::uuid", (self._bridge_user_id,))
            row = cur.fetchone()
        except Exception as exc:
            self._log(f"Relecture de l'adresse d'audit impossible : {exc}", Qgis.Warning)
            return
        finally:
            cur.close()
        email = row[0] if row else None
        if email and email != self._bridge_user_email:
            self._bridge_user_email = email
            _apply_audit_identity(email, self._log)
            self._set_app_user(email)
```
Dans `_run_onboarding`, remplacer :
```python
        wizard.exec_()
```
par :
```python
        wizard.exec_()
        self._refresh_audit_identity()
```

- [ ] **Step 8 : `_on_before_commit`**

Remplacer :
```python
                    cur.execute("SELECT set_config('app.current_user', %s, true)", (self._bridge_user,))
```
par :
```python
                    cur.execute(
                        "SELECT set_config('app.current_user', %s, true)",
                        (self._bridge_user_email or self._bridge_user,),
                    )
```
et, dans la branche de repli, remplacer :
```python
                set_config_sql, app_name_sql = build_set_config_sql(self._bridge_user)
```
par :
```python
                set_config_sql, app_name_sql = build_set_config_sql(self._bridge_user_email or self._bridge_user)
```
Note : `application_name` y devient `constructel_bridge:<email>` dans la branche de repli seulement. La branche principale garde `constructel_bridge:{self._bridge_user}` : ne pas la toucher.

- [ ] **Step 9 : Relancer toute la suite**

```bash
/home/sdadmin/.venvs/bridge0-tests/bin/pytest -q
```
Attendu : tout passe, y compris `test_bridge_plugin_import.py`, `test_bridge1b_wiring.py` et `test_bridge_identity.py`. Relire la sortie brute.

- [ ] **Step 10 : Committer**

```bash
git add plugin-repo/packages/constructel_bridge/bridge_plugin.py plugin-repo/packages/constructel_bridge_tests/test_bridge_audit_email.py
git commit -m "feat(bridge): adresse mail de l'auteur posée dans PGOPTIONS pour l'audit Farois

Cache QgsSettings appliqué en tête d'initGui, adresse lue dans ref.users au
login et reposée après l'assistant d'accueil ; interrupteur
constructel_bridge/audit_email_pgoptions ; jamais bloquant.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5 : Métadonnées 1.5.10 et revue de branche

**Files:**
- Modify : `plugin-repo/packages/constructel_bridge/metadata.txt` (`version=` et tête de `changelog=`)

**Interfaces:**
- Consumes : Tasks 3 et 4.
- Produces : branche `feat/bridge-audit-email` prête à merger (le zip et `plugins.xml` sont faits en Task 7, sur `main`).

- [ ] **Step 1 : Version et changelog**

Dans `metadata.txt` : `version=1.5.9` → `version=1.5.10`. Puis, sur la ligne qui commence par `changelog=v1.5.9 - `, remplacer **uniquement** le préfixe `changelog=v1.5.9 - ` par les deux lignes suivantes (la seconde garde l'indentation de 4 espaces des entrées existantes ; tout le reste du texte v1.5.9 et des versions antérieures est inchangé) :
```
changelog=v1.5.10 - feat(plugin): adresse mail de l'auteur dans l'audit Farois -- au login, Bridge lit l'adresse de l'utilisateur dans ref.users et la pose dans PGOPTIONS (app.current_user) : toutes les connexions PostgreSQL ouvertes ensuite par QGIS la portent, et le journal d'audit Farois enregistre l'auteur des modifications. Adresse memorisee pour etre posee des le demarrage suivant, reposee apres l'assistant d'accueil. Tracabilite seulement (adresse declaree, identity_verified=false). Jamais bloquant ; interrupteur constructel_bridge/audit_email_pgoptions=false. Prerequis base : migration Farois 453.
    v1.5.9 - 
```
Contrôle : `grep -c '^    v1.5.9 - feat(plugin): controle au demarrage' metadata.txt` renvoie `1` et `grep -c '^version=1.5.10$' metadata.txt` renvoie `1`.

- [ ] **Step 2 : Suite complète + lint de syntaxe**

```bash
/home/sdadmin/.venvs/bridge0-tests/bin/pytest -q
python3 -m py_compile plugin-repo/packages/constructel_bridge/bridge_plugin.py plugin-repo/packages/constructel_bridge/bridge_identity.py
```
Attendu : tout passe, aucune erreur de compilation.

- [ ] **Step 3 : Committer**

```bash
git add plugin-repo/packages/constructel_bridge/metadata.txt
git commit -m "chore(bridge): 1.5.10 metadata + changelog

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4 : Revue de branche**

Revue adversariale du diff `main..feat/bridge-audit-email` (sous-agent `opus-reviewer`) : non-blocage en toute circonstance, aucune régression de `_connect` / mTLS / onboarding, aucune pose de `app.user_id`. Corriger puis recommitter jusqu'à approbation.

---

### Task 6 : Appliquer 453 en prod (GATE a) — feu vert de Simon requis

**Files:** aucun dans les dépôts ; sauvegardes dans `~/ops/backups/<date>_mig453/`.

**Interfaces:**
- Consumes : Task 2 mergée sur `origin/main` de Farois.
- Produces : `farois_ftth` avec `audit.status_history.source` en `character varying(255)` et `453_audit_status_history_source_email` dans `esb.applied_migrations`.

- [ ] **Step 1 : PR Farois et merge**

```bash
cd /home/sdadmin/projects/Farois/.worktrees/feat-453-status-history-source
git push -u origin feat/453-status-history-source
```
Ouvrir la PR depuis WSL (`gh` local) :
```bash
gh pr create -R imagodata/Farois --base main --head feat/453-status-history-source \
  --title "feat(audit): mig 453 élargit audit.status_history.source à 255" \
  --body "$(cat <<'EOF'
Prérequis de « adresse mail de l'auteur sur chaque modification QGIS » (spec qgis_repo
docs/superpowers/specs/2026-10-15-bridge-audit-email-design.md) : Constructel Bridge 1.5.10
pose app.current_user=<email> ; universal_trigger_before l'écrit dans
audit.status_history.source (VARCHAR(30)) et 5 adresses actives dépassent 30 caractères.

- 453 : VARCHAR(255), 3 vues dépendantes recréées à l'identique depuis le catalogue,
  gardes qui font échouer la migration sur toute forme non gérée.
- 453r : refuse de tronquer.
- Test jetable 099m (idempotence, ACL/définitions identiques, gardes).
- À appliquer À LA MAIN en prod : 451 est en attente et bloque l'auto-migration.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```
Merger après accord de Simon. Vérifier ensuite avec `gh api repos/imagodata/Farois/contents/sql/migrations/453_audit_status_history_source_email.sql?ref=main` : le dépôt bouge vite, les refs locales périment.

- [ ] **Step 2 : Ne PAS passer par l'auto-migration du worker**

`farois deploy migrate` joue les migrations en attente dans l'ordre et s'arrête au premier échec. `451_audit_undo_mvp` est en attente et échoue forcément, puisque 442 est en place. 453 s'applique donc **à la main**. Ne pas redémarrer `farois-worker` dans cette tâche.

- [ ] **Step 3 : Empreinte et sauvegarde avant**

```bash
B=~/ops/backups/$(date +%F)_mig453; mkdir -p $B
PW=$(grep -E '^POSTGRES_PASSWORD=' ~/projects/Farois/docker/.env.secrets | head -1 | cut -d= -f2- | sed -e "s/^[\"']//" -e "s/[\"']$//")
VIEWS=$(docker exec -e PGPASSWORD="$PW" ftth-postgres psql -X -U postgres -d farois_ftth -tAc "SELECT string_agg(format('-t %I.%I', n.nspname, c.relname), ' ') FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='v' AND c.relname IN ('v_beon_status_changes','v_status_history_scoped','v_dp_retenus_recul_manuel')")
docker exec -e PGPASSWORD="$PW" ftth-postgres pg_dump -U postgres -d farois_ftth -s -t audit.status_history $VIEWS > $B/schema_avant.sql
grep -c 'CREATE VIEW' $B/schema_avant.sql
git -C ~/projects/Farois show origin/main:sql/99_validation/tests/099m_453_views_fingerprint.sql > $B/fp.sql
docker exec -i -e PGPASSWORD="$PW" ftth-postgres psql -X -qAt -U postgres -d farois_ftth < $B/fp.sql | tee $B/fp_avant.txt
```
Attendu : `3`, puis un md5 enregistré dans `$B/fp_avant.txt`.

- [ ] **Step 4 : Appliquer (feu vert explicite de Simon)**

```bash
git -C ~/projects/Farois fetch -q origin
git -C ~/projects/Farois show origin/main:sql/migrations/453_audit_status_history_source_email.sql > $B/453.sql
docker exec -i -e PGPASSWORD="$PW" ftth-postgres psql -X -v ON_ERROR_STOP=1 -v op=wyre -U postgres -d farois_ftth < $B/453.sql
docker exec -e PGPASSWORD="$PW" ftth-postgres psql -X -U postgres -d farois_ftth -c "INSERT INTO esb.applied_migrations (migration_name) VALUES ('453_audit_status_history_source_email') ON CONFLICT DO NOTHING"
```
Attendu : `COMMIT`, puis `INSERT 0 1`.

- [ ] **Step 5 : Vérifier**

```bash
docker exec -e PGPASSWORD="$PW" ftth-postgres psql -X -U postgres -d farois_ftth -tAc "SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid='audit.status_history'::regclass AND attname='source'"
```
Attendu : `character varying(255)`. Puis :
```bash
docker exec -i -e PGPASSWORD="$PW" ftth-postgres psql -X -qAt -U postgres -d farois_ftth < $B/fp.sql > $B/fp_apres.txt
diff $B/fp_avant.txt $B/fp_apres.txt && echo VUES_IDENTIQUES
```
Attendu : `VUES_IDENTIQUES`.

---

### Task 7 : Publier Bridge 1.5.10 (GATE) — feu vert de Simon requis

**Files:**
- Modify (working tree principal `~/projects/qgis_repo`, servi en direct) : `plugin-repo/packages/constructel_bridge.zip`, `plugin-repo/plugins.xml`

**Interfaces:**
- Consumes : Tasks 1 (spike réussi), 3–5 (branche approuvée), 6 (453 en prod).
- Produces : Bridge 1.5.10 proposé à tous les postes par le gestionnaire d'extensions QGIS.

- [ ] **Step 1 : Contrôler le GATE**

Cocher explicitement, preuves à l'appui : (a) Task 6 Step 5 OK ; (b) verdict « réussi » dans `2026-10-15-bridge-audit-email-spike-results.md` ; (c) dernière sortie de `pytest -q` verte et revue Task 5 Step 4 approuvée. Si une condition manque : STOP.

- [ ] **Step 2 : Rejouer le rattrapage d'auteur (feu vert de Simon)**

Reprendre `~/ops/backups/2026-10-15_audit_attribution/backfill.sql` dans `~/ops/backups/$(date +%F)_audit_attribution/`, en remplaçant seulement `'attribution_le', '2026-10-15'` par la date du jour. Exporter d'abord les lignes visées en CSV, comme le 15/10, puis exécuter. Si aucune transaction sans auteur n'existe, le script s'arrête de lui-même (`nombre de cibles inattendu: 0`) : c'est le résultat normal.

- [ ] **Step 3 : Merger sur `main`**

```bash
cd ~/projects/qgis_repo
git status --short plugin-repo/packages/constructel_bridge/ plugin-repo/packages/constructel_bridge_tests/
git merge --ff-only feat/bridge-audit-email
```
Attendu : le premier `git status` est vide ; le merge réussit en fast-forward. Les autres modifications non commitées du working tree (`plugins.xml`, `resource-repo*`) ne sont pas touchées.

- [ ] **Step 4 : Construire le zip et la version dans `plugins.xml`**

```bash
python3 -c "import zipfile; print('\n'.join(sorted(zipfile.ZipFile('plugin-repo/packages/constructel_bridge.zip').namelist())))" > /tmp/bridge_zip_avant.txt
python3 plugin-repo/packages/constructel_bridge/release.py 1.5.10
python3 -c "import zipfile; print('\n'.join(sorted(zipfile.ZipFile('plugin-repo/packages/constructel_bridge.zip').namelist())))" > /tmp/bridge_zip_apres.txt
diff /tmp/bridge_zip_avant.txt /tmp/bridge_zip_apres.txt && echo ZIP_ENTREES_IDENTIQUES
python3 -c "import zipfile; z=zipfile.ZipFile('plugin-repo/packages/constructel_bridge.zip'); assert 'version=1.5.10' in z.read('constructel_bridge/metadata.txt').decode(); assert 'build_pgoptions' in z.read('constructel_bridge/bridge_identity.py').decode(); print('ZIP_OK')"
grep -c 'version="1.5.10"\|<version>1.5.10</version>' plugin-repo/plugins.xml
```
Attendu : `ZIP_ENTREES_IDENTIQUES` (51 entrées, `credentials.json` compris), `ZIP_OK`, puis `2`.

- [ ] **Step 5 : Committer seulement le bloc Bridge de `plugins.xml`**

Le working tree contient des entrées `farois_audit_rollback` non suivies dans `plugins.xml` : elles ne doivent pas entrer dans ce commit. Indexer la version `HEAD` + bump uniquement :
```bash
git show HEAD:plugin-repo/plugins.xml \
  | python3 -c "import re,sys; t=sys.stdin.read(); t,n1=re.subn(r'(<pyqgis_plugin\s+name=\"Constructel Bridge\"\s+version=\")[\d.]+(\")', r'\g<1>1.5.10\2', t); t,n2=re.subn(r'(name=\"Constructel Bridge\".*?<version>)[\d.]+(</version>)', r'\g<1>1.5.10\2', t, flags=re.S); assert (n1,n2)==(1,1), (n1,n2); sys.stdout.write(t)" > /tmp/plugins_head_1510.xml
BLOB=$(git hash-object -w /tmp/plugins_head_1510.xml)
git update-index --cacheinfo 100644,$BLOB,plugin-repo/plugins.xml
git add plugin-repo/packages/constructel_bridge.zip
git diff --cached --stat
git commit -m "release(constructel_bridge): 1.5.10 - adresse mail de l'auteur dans l'audit Farois

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git diff plugin-repo/plugins.xml | grep '^[+-]' | grep -v '^+++\|^---'
```
Attendu : `--cached --stat` liste uniquement `constructel_bridge.zip` et `plugins.xml`. Le dernier `diff` ne montre que les 2 lignes `farois_audit_rollback`, toujours non commitées.

- [ ] **Step 6 : Vérifier ce que servent `:9080` et le dépôt, puis pousser**

```bash
curl -s http://192.168.160.31:9080/plugin-repo/plugins.xml | grep -A3 'name="Constructel Bridge"' | head -4
git push origin main
```
Attendu : `version="1.5.10"` servi. Le push passe par l'assistant d'authentification `gh` déjà configuré.

---

### Task 8 : Vérification après publication

**Files:** aucun.

**Interfaces:**
- Consumes : Task 7.
- Produces : constat écrit dans le compte rendu final.

- [ ] **Step 1 : Sur le poste de Simon**

Gestionnaire d'extensions → mettre à jour Constructel Bridge vers 1.5.10 → **redémarrer QGIS** → se connecter → modifier un attribut d'un objet `wyre` → enregistrer. Le journal « Constructel Bridge » affiche `Adresse d'audit posee pour les nouvelles connexions PostgreSQL : simonducourneau@constructel.be`.

- [ ] **Step 2 : En base, lecture seule**

```sql
SELECT t.identity_source, t.constructel_email, t.identity_verified, t.app_user_id IS NULL AS sans_app_user_id,
       t.client_app, count(c.*) AS changements
  FROM audit.transactions t JOIN audit.changes c ON c.transaction_id = t.id
 WHERE t.started_at > now() - interval '1 hour'
 GROUP BY 1,2,3,4,5;
```
Attendu : `QGIS | simonducourneau@constructel.be | f | t | QGIS … desktop | ≥1`.

- [ ] **Step 3 : Aucun refus lié à la longueur**

```bash
docker logs --since 24h ftth-postgres 2>&1 | grep -c 'value too long for type character varying' || true
```
Attendu : `0`. Revérifier à J+1 et J+7 la part des transactions QGIS sans `constructel_email`. Elle doit tendre vers 0 à mesure que les postes passent en 1.5.10.
