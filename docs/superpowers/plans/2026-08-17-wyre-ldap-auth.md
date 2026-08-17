# Authentification LDAP pour la connexion QGIS `wyre` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer l'identifiant Postgres partagé `ftth_editor` de la connexion QGIS `wyre` par une authentification LDAP individuelle (même annuaire AD que Farois), avec un mot de passe jamais stocké et un rôle Postgres par personne.

**Architecture:** PostgreSQL délègue la vérification du mot de passe à l'AD via `pg_hba.conf` (méthode `ldap`, search+bind, groupe Postgres `ftth_editor`). Les rôles Postgres individuels (un par `sAMAccountName`) sont créés/désactivés par un script de synchronisation contre un groupe AD, réutilisant `farois/ui/auth/ldap_ad.py` déjà utilisé par Farois. Le plugin `constructel_bridge` n'embarque plus aucun identifiant/mot de passe pour `wyre` et laisse QGIS demander le mot de passe à chaque session. `be` (`bureau_etudes`) reste inchangé.

**Tech Stack:** PostgreSQL 17 + PostGIS (conteneur `ftth-postgres`, base `farois_ftth`), migrations Farois (`psql`, jouées sous `ftth_admin` via `farois deploy migrate`), Python 3 / `ldap3` (`farois/ui/auth/ldap_ad.py`, réutilisé), Plugin QGIS Python 3 / PyQGIS (`QgsSettings`, `QgsCredentials`, `QgsAuthMethodConfig`). `pytest` n'est disponible ni sur le VPS ni dans `farois-worker` — tous les tests Python de ce plan s'exécutent via le harnais `python3` (import direct du module de test + appel de chaque `test_*`), pattern déjà utilisé au chantier du 2026-07-30.

**Spec:** `docs/superpowers/specs/2026-08-17-wyre-ldap-auth-design.md` (dépôt `qgis_repo`)

## Global Constraints

1. **Worktree isolée obligatoire pour `~/projects/Farois`** — dépôt partagé très actif, jamais de commit sur le working tree partagé.
2. **Worktree pour `~/projects/qgis_repo` aussi** — dépôt SERVI en direct (`:9080`), le merge dans `main` EST l'acte de publication.
3. **Rien appliqué en prod sans GO explicite de Simon** — migration jouée, `pg_hba.conf` rechargé, script de synchro des rôles exécuté, merges/push : tout attend la Task 10 (GATE).
4. **Aucun mot de passe dans un fichier versionné** — SQL, `pg_hba.conf`, scripts. Les rôles individuels créés par ce chantier n'ont d'ailleurs jamais de mot de passe côté Postgres (auth déléguée à l'AD).
5. **Migrations Farois jouées sous `ftth_admin`, jamais sous `postgres`** (`docs/workflow_migrations_sql.md`). Le script de synchro des rôles (Task 6) se connecte lui aussi en `ftth_admin`, jamais via la connexion applicative bas-privilège utilisée par les autres jobs cron.
6. **Dépendance externe non résolue** : le nom du groupe AD à synchroniser (`LDAP_GROUP_WYRE_PG_USERS`) n'est pas encore fourni par l'IT. Les Tasks 1-9 ne dépendent pas de sa valeur (code paramétré par variable d'env, testé avec des noms de groupe arbitraires) ; seule l'exécution réelle en Task 10 est bloquée tant qu'il manque.

---

## Farois (dépôt `~/projects/Farois`)

### Task 1: Worktree Farois

**Files:** aucun — opération git uniquement.

**Interfaces:** Produit une worktree `~/projects/Farois-wyre-ldap` sur une nouvelle branche `feat/wyre-ldap-auth`, consommée par les Tasks 3, 4, 5, 6.

- [ ] **Step 1: Créer la worktree isolée**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/Farois && git worktree add -b feat/wyre-ldap-auth ~/projects/Farois-wyre-ldap main'
```

Résultat attendu : `Preparing worktree (new branch 'feat/wyre-ldap-auth')`, puis `HEAD is now at ...`.

- [ ] **Step 2: Vérifier l'isolation**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/Farois && git status --short && git worktree list'
```

Résultat attendu : `git status` vide sur le tree partagé (`main` inchangé) ; `git worktree list` fait apparaître `~/projects/Farois-wyre-ldap [feat/wyre-ldap-auth]` en plus de `~/projects/Farois [main]`.

---

### Task 2: Migration 375 — `ftth_editor` devient un rôle groupe (`NOLOGIN`)

**Files:**
- Create: `~/projects/Farois-wyre-ldap/sql/migrations/375_ftth_editor_nologin.sql`
- Create: `~/projects/Farois-wyre-ldap/sql/migrations/375r_rollback_ftth_editor_nologin.sql`
- Test: `~/projects/Farois-wyre-ldap/tests/unit/test_migration_375_static.py`

**Interfaces:**
- Consomme de Task 1 : la worktree `~/projects/Farois-wyre-ldap`.
- Produit : le nom de migration `375_ftth_editor_nologin`, consommé par Task 10 (application en prod).

- [ ] **Step 1: Écrire la migration forward**

`~/projects/Farois-wyre-ldap/sql/migrations/375_ftth_editor_nologin.sql` :

```sql
-- ============================================================================
-- 375_ftth_editor_nologin.sql
-- ============================================================================
-- NE PAS DEPLOYER SANS VALIDATION EXPLICITE DE SIMON.
--
-- Chantier "Authentification LDAP wyre"
-- (docs/superpowers/specs/2026-08-17-wyre-ldap-auth-design.md, qgis_repo) :
-- ftth_editor devient un role GROUPE pur. Les personnes se connectent
-- desormais avec un role individuel (nomme sur leur sAMAccountName AD),
-- authentifie via pg_hba.conf (methode ldap, search+bind), membre de
-- ftth_editor -- ses grants existants sur infra/osiris sont herites sans
-- etre dupliques.
--
-- PREREQUIS : la ligne pg_hba.conf 'ldap' pour le groupe ftth_editor doit
-- deja etre active EN PROD avant cette migration, sinon plus personne ne
-- peut se connecter en ftth_editor entre le retrait de LOGIN et la mise a
-- jour de pg_hba.conf (cf. Task 10, ordre des etapes).
-- ============================================================================

\set ON_ERROR_STOP on
BEGIN;

\echo ''
\echo '=== Migration 375 : ftth_editor -> role groupe (NOLOGIN) ==='
\echo ''

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ftth_editor' AND rolcanlogin) THEN
        ALTER ROLE ftth_editor NOLOGIN;
        RAISE NOTICE 'OK: ftth_editor - LOGIN retire';
    ELSE
        RAISE NOTICE 'SKIP: ftth_editor deja NOLOGIN (ou absent)';
    END IF;
END $$;

COMMENT ON ROLE ftth_editor IS 'Role groupe (edition donnees metier infra/osiris) - individus membres via GRANT, authentifies par LDAP (pg_hba.conf)';

\echo ''
\echo 'Verification :'
SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = 'ftth_editor';

\echo ''
\echo '  375_ftth_editor_nologin OK'
COMMIT;
```

- [ ] **Step 2: Écrire le rollback**

`~/projects/Farois-wyre-ldap/sql/migrations/375r_rollback_ftth_editor_nologin.sql` :

```sql
-- ============================================================================
-- 375r_rollback_ftth_editor_nologin.sql
-- ============================================================================
-- Restaure LOGIN sur ftth_editor (retour au compte partage pre-migration).
-- Le mot de passe pose par scripts/deploy/deploy_roles.sh (FTTH_EDITOR_PASSWORD)
-- n'est jamais efface par ALTER ROLE ... NOLOGIN : aucune action necessaire
-- ici pour le restaurer, il redevient utilisable des que LOGIN est remis.
-- ============================================================================

\set ON_ERROR_STOP on
BEGIN;

\echo 'Rollback 375 : restauration LOGIN sur ftth_editor'

ALTER ROLE ftth_editor LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT CONNECTION LIMIT 50;

COMMENT ON ROLE ftth_editor IS 'Edition donnees metier FTTH (infra, osiris) - acces complet lecture/ecriture sauf DDL';

\echo '  375r rollback OK'
COMMIT;
```

- [ ] **Step 3: Écrire le test statique**

`~/projects/Farois-wyre-ldap/tests/unit/test_migration_375_static.py` :

```python
"""Tests statiques pour la migration 375 (ftth_editor -> role groupe NOLOGIN).

Chantier "Authentification LDAP wyre" : ftth_editor perd LOGIN et devient un
role groupe pur ; les individus se connectent via des roles LDAP dedies
(cf. farois/cron/pg_role_sync.py) membres de ftth_editor.

Verifications statiques (sans Docker, sans base) :
- Les 2 fichiers 375 (migration + rollback) existent.
- Avertissement explicite "ne pas deployer sans validation Simon" en tete.
- La migration retire LOGIN de facon idempotente (garde pg_roles).
- Aucun mot de passe manipule (ALTER ROLE ... NOLOGIN ne touche jamais au
  mot de passe existant).
- Le forward est transactionnel (BEGIN/COMMIT) et n'insere pas lui-meme
  dans esb.applied_migrations (convention runner).
- Le rollback restaure reellement LOGIN (pas un no-op).
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = ROOT / "sql" / "migrations"
MIGRATION_PATH = MIGRATIONS_DIR / "375_ftth_editor_nologin.sql"
ROLLBACK_PATH = MIGRATIONS_DIR / "375r_rollback_ftth_editor_nologin.sql"


def _read(path: pathlib.Path) -> str:
    assert path.exists(), f"Fichier introuvable : {path}"
    return path.read_text(encoding="utf-8")


def _strip_sql_comments(text: str) -> str:
    lines = [re.sub(r"--.*$", "", ln) for ln in text.splitlines()]
    return "\n".join(lines)


def test_files_exist():
    assert MIGRATION_PATH.exists(), f"Migration manquante : {MIGRATION_PATH}"
    assert ROLLBACK_PATH.exists(), f"Rollback manquant : {ROLLBACK_PATH}"


def test_warns_manual_validation_required():
    content = _read(MIGRATION_PATH)
    assert "NE PAS DEPLOYER SANS VALIDATION" in content.upper()


def test_migration_sets_nologin():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    assert re.search(r"ALTER\s+ROLE\s+ftth_editor\s+NOLOGIN", sql, re.IGNORECASE)


def test_migration_is_idempotent():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    assert "SELECT FROM pg_roles WHERE rolname = 'ftth_editor' AND rolcanlogin" in sql


def test_no_password_touched():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    assert not re.search(r"PASSWORD", sql, re.IGNORECASE)


def test_forward_is_transactional():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    assert re.search(r"^BEGIN;", sql, flags=re.MULTILINE)
    assert re.search(r"^COMMIT;", sql, flags=re.MULTILINE)


def test_no_self_insert_into_applied_migrations():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    assert "applied_migrations" not in sql


def test_rollback_restores_login():
    sql = _strip_sql_comments(_read(ROLLBACK_PATH))
    assert re.search(r"ALTER\s+ROLE\s+ftth_editor\s+LOGIN\b", sql, re.IGNORECASE)
```

- [ ] **Step 4: Exécuter le test via le harnais `python3`**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-wyre-ldap && python3 - <<PY
import importlib.util, sys
spec = importlib.util.spec_from_file_location("t375", "tests/unit/test_migration_375_static.py")
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

Résultat attendu : 7 lignes `PASS`, puis `--- 0 echec(s)`, code de sortie 0.

- [ ] **Step 5: Commit (sans push)**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-wyre-ldap && git add sql/migrations/375_ftth_editor_nologin.sql sql/migrations/375r_rollback_ftth_editor_nologin.sql tests/unit/test_migration_375_static.py && git commit -m "feat(sql): migration 375 - ftth_editor devient role groupe (NOLOGIN)"'
```

Résultat attendu : `3 files changed, ... insertions(+)`.

---

### Task 3: `pg_hba.conf` — authentification LDAP pour le groupe `ftth_editor`

**Files:**
- Modify: `~/projects/Farois-wyre-ldap/docker/postgres/pg_hba.conf`
- Test: `~/projects/Farois-wyre-ldap/tests/unit/test_pg_hba_ldap_wyre.py`

**Interfaces:**
- Consomme de Task 1 : la worktree.
- Produit : le placeholder `__LDAP_BIND_PASSWORD_PLACEHOLDER__`, consommé par Task 4 (substitution au démarrage).

- [ ] **Step 1: Insérer la ligne LDAP avant les lignes génériques `scram-sha-256`**

Dans `~/projects/Farois-wyre-ldap/docker/postgres/pg_hba.conf`, localiser :

```
# -----------------------------------------------------------------------------
# CONNEXIONS RÉSEAU DOCKER (SSL REQUIS)
# -----------------------------------------------------------------------------

# Réseau Docker bridge (172.x.x.x)
hostssl all             all             172.0.0.0/8             scram-sha-256
```

Insérer juste avant ce bloc (donc juste après le bloc "CONNEXIONS LOCALES") :

```
# -----------------------------------------------------------------------------
# AUTH LDAP — role groupe ftth_editor (chantier auth LDAP wyre, 2026-08-17)
# -----------------------------------------------------------------------------
# Les membres du role groupe ftth_editor (un role LOGIN individuel par
# personne, cf. migration 375 + farois/cron/pg_role_sync.py) s'authentifient
# par bind LDAPS contre l'AD constructelbe.corp, meme annuaire que Farois
# (farois/ui/auth/ldap_ad.py). Le mot de passe n'est JAMAIS stocke cote
# Postgres. Cette ligne DOIT precéder toute regle generique "all" ci-dessous
# (premiere ligne qui matche = utilisee).
#
# ldapbindpasswd est un PLACEHOLDER : substitue au demarrage du conteneur
# par farois-entrypoint.sh a partir de la variable d'environnement
# LDAP_BIND_PASSWORD (jamais commitee en clair ici, cf. .env.secrets).
hostssl farois_ftth     +ftth_editor    192.168.0.0/16          ldap ldapserver=dc01be.constructelbe.corp ldapport=636 ldapscheme=ldaps ldapbasedn="OU=Utilisateurs,OU=SI,DC=constructelbe,DC=corp" ldapsearchattribute=sAMAccountName ldapbinddn="CN=farois ldaps,OU=Utilisateurs SI,OU=SI,DC=constructelbe,DC=corp" ldapbindpasswd=__LDAP_BIND_PASSWORD_PLACEHOLDER__

```

- [ ] **Step 2: Écrire le test statique**

`~/projects/Farois-wyre-ldap/tests/unit/test_pg_hba_ldap_wyre.py` :

```python
"""Tests statiques pour la ligne LDAP pg_hba.conf du groupe ftth_editor.

Chantier "Authentification LDAP wyre" : verifie que la ligne d'auth LDAP est
presente, correctement ordonnee (avant tout catch-all scram-sha-256, sinon
elle ne serait jamais atteinte), et qu'aucun mot de passe en clair n'a
remplace le placeholder dans le fichier VERSIONNE.
"""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
PG_HBA_PATH = ROOT / "docker" / "postgres" / "pg_hba.conf"
PLACEHOLDER = "__LDAP_BIND_PASSWORD_PLACEHOLDER__"


def _lines() -> list[str]:
    assert PG_HBA_PATH.exists(), f"Fichier introuvable : {PG_HBA_PATH}"
    return PG_HBA_PATH.read_text(encoding="utf-8").splitlines()


def test_file_exists():
    assert PG_HBA_PATH.exists()


def test_ldap_line_present_for_ftth_editor_group():
    content = "\n".join(_lines())
    assert re.search(r"hostssl\s+farois_ftth\s+\+ftth_editor\b.*\bldap\b", content), (
        "Ligne hostssl farois_ftth +ftth_editor ... ldap introuvable"
    )


def test_ldap_line_precedes_generic_scram_catchall():
    lines = _lines()
    ldap_idx = next(
        i for i, l in enumerate(lines) if "+ftth_editor" in l and " ldap " in l
    )
    scram_catchall_idxs = [
        i for i, l in enumerate(lines)
        if re.match(r"\s*hostssl\s+all\s+all\s+\S+\s+scram-sha-256", l)
    ]
    assert scram_catchall_idxs, "Aucune ligne catch-all scram-sha-256 trouvee"
    assert all(ldap_idx < i for i in scram_catchall_idxs), (
        "La ligne ldap ftth_editor doit preceder toutes les lignes "
        "catch-all scram-sha-256 (premiere regle qui matche = utilisee)"
    )


def test_no_password_in_clear_only_placeholder():
    content = "\n".join(_lines())
    m = re.search(r"ldapbindpasswd=(\S+)", content)
    assert m is not None, "ldapbindpasswd attendu sur la ligne ldap"
    assert m.group(1) == PLACEHOLDER, (
        f"ldapbindpasswd doit rester le placeholder {PLACEHOLDER!r} dans le "
        f"fichier versionne, trouve : {m.group(1)!r}"
    )
```

- [ ] **Step 3: Exécuter le test via le harnais `python3`**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-wyre-ldap && python3 - <<PY
import importlib.util, sys
spec = importlib.util.spec_from_file_location("thba", "tests/unit/test_pg_hba_ldap_wyre.py")
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

Résultat attendu : 4 lignes `PASS`, puis `--- 0 echec(s)`, code de sortie 0.

- [ ] **Step 4: Commit (sans push)**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-wyre-ldap && git add docker/postgres/pg_hba.conf tests/unit/test_pg_hba_ldap_wyre.py && git commit -m "feat(postgres): auth LDAP search+bind pour le groupe ftth_editor dans pg_hba.conf"'
```

Résultat attendu : `2 files changed, ... insertions(+)`.

---

### Task 4: `farois-entrypoint.sh` — substitution du mot de passe LDAP au démarrage

**Files:**
- Modify: `~/projects/Farois-wyre-ldap/docker/postgres/farois-entrypoint.sh`

**Interfaces:**
- Consomme de Task 3 : le placeholder `__LDAP_BIND_PASSWORD_PLACEHOLDER__` dans `pg_hba.conf`.
- Consomme de l'environnement : `LDAP_BIND_PASSWORD` (déjà présent dans `docker/.env.secrets`, réutilisé de Farois — aucun nouveau secret à créer).
- Produit : `/etc/postgresql/pg_hba.conf.sample` avec le mot de passe substitué, lu ensuite par `10_install_farois.sh` (premier init) ou déjà en place pour un redémarrage (Task 10 gère la mise à jour manuelle d'un serveur déjà installé).

Ce fichier est un script bash glue (comme `healthcheck.sh`/`generate-ssl-certs.sh`, non couverts par des tests automatisés dans ce dépôt) : vérification par exécution directe de la logique extraite, pas de suite pytest.

- [ ] **Step 1: Lire le fichier actuel pour repérer le point d'insertion**

```bash
ssh sdadmin@192.168.160.31 'cat ~/projects/Farois-wyre-ldap/docker/postgres/farois-entrypoint.sh'
```

Repérer la dernière ligne : `exec /usr/local/bin/docker-entrypoint.sh "$@"`.

- [ ] **Step 2: Insérer la substitution juste avant cette ligne**

Remplacer :

```bash
# Delegue a l'entrypoint officiel postgres (signaux propages via exec)
exec /usr/local/bin/docker-entrypoint.sh "$@"
```

par :

```bash
# --- LDAP bind password templating (chantier auth LDAP wyre, 2026-08-17) ---
# pg_hba.conf.sample (versionne dans docker/postgres/pg_hba.conf) contient un
# PLACEHOLDER pour ldapbindpasswd : aucun mot de passe ne doit etre commite
# dans ce fichier. On substitue le placeholder dans le SAMPLE, en place, a
# CHAQUE demarrage du conteneur -- AVANT que quoi que ce soit (10_install_farois.sh
# au premier init, ou ce meme wrapper aux demarrages suivants d'un futur
# redeploiement) ne copie le sample vers PGDATA. Une rotation du mot de passe
# ne demande donc qu'un redemarrage du conteneur, pas une reinstallation.
# Idempotent : re-substituer un fichier deja substitue serait un no-op (le
# placeholder n'existe plus), donc inoffensif de le faire a chaque boot.
PG_HBA_SAMPLE="/etc/postgresql/pg_hba.conf.sample"
if [ -f "$PG_HBA_SAMPLE" ]; then
    if [ -n "${LDAP_BIND_PASSWORD:-}" ]; then
        # Echappement sed standard : backslash, slash (delimiteur) et
        # esperluette (speciale en remplacement) sont prefixes d'un
        # backslash, pour supporter un mot de passe contenant ces
        # caracteres sans casser la substitution.
        esc_pw=$(printf '%s' "$LDAP_BIND_PASSWORD" | sed -e 's/[\/&]/\\&/g')
        sed -i "s/__LDAP_BIND_PASSWORD_PLACEHOLDER__/${esc_pw}/g" "$PG_HBA_SAMPLE"
        echo "[entrypoint-hba] Mot de passe LDAP substitue dans pg_hba.conf.sample"
    else
        echo "[entrypoint-hba] LDAP_BIND_PASSWORD non defini — placeholder non substitue (auth ldap echouera tant que non defini)"
    fi
fi

# Delegue a l'entrypoint officiel postgres (signaux propages via exec)
exec /usr/local/bin/docker-entrypoint.sh "$@"
```

- [ ] **Step 3: Vérifier la logique de substitution hors conteneur (fixture locale)**

```bash
ssh sdadmin@192.168.160.31 '
set -e
tmpdir=$(mktemp -d)
cp ~/projects/Farois-wyre-ldap/docker/postgres/pg_hba.conf "$tmpdir/sample"
LDAP_BIND_PASSWORD="te/st&pw\\d"
esc_pw=$(printf "%s" "$LDAP_BIND_PASSWORD" | sed -e "s/[\\/&]/\\\\&/g")
sed -i "s/__LDAP_BIND_PASSWORD_PLACEHOLDER__/${esc_pw}/g" "$tmpdir/sample"
echo "occurrences placeholder restantes: $(grep -c __LDAP_BIND_PASSWORD_PLACEHOLDER__ "$tmpdir/sample" || true)"
grep -F "te/st&pw\\d" "$tmpdir/sample" && echo "MOT DE PASSE SUBSTITUE OK"
rm -rf "$tmpdir"
'
```

Résultat attendu : `occurrences placeholder restantes: 0` puis `MOT DE PASSE SUBSTITUE OK` — confirme que la substitution fonctionne même avec un mot de passe contenant `/`, `&` et `\`.

- [ ] **Step 4: Commit (sans push)**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-wyre-ldap && git add docker/postgres/farois-entrypoint.sh && git commit -m "feat(postgres): templating du mot de passe LDAP dans pg_hba.conf au demarrage du conteneur"'
```

Résultat attendu : `1 file changed, ... insertions(+)`.

---

### Task 5: `farois/cron/pg_role_sync.py` — synchronisation des rôles Postgres individuels

**Files:**
- Create: `~/projects/Farois-wyre-ldap/farois/cron/pg_role_sync.py`
- Test: `~/projects/Farois-wyre-ldap/tests/unit/cron/test_pg_role_sync.py`

**Interfaces:**
- Consomme : `farois.ui.auth.ldap_ad` (`LdapConfig.from_env()`, `service_connection(cfg)`, `list_group_members(conn, cfg, group_name) -> list[LdapUser]` — `LdapUser.username`/`.disabled`), module déjà existant, inchangé.
- Consomme l'environnement : `LDAP_GROUP_WYRE_PG_USERS` (nom du groupe AD à synchroniser — vide par défaut, cf. Global Constraint 6), `DB_HOST`, `DB_PORT`, `DB_NAME`, `FTTH_ADMIN_PASSWORD`.
- Produit : `compute_plan(desired_usernames, current) -> SyncPlan`, `run(dry_run=False, cfg=None) -> SyncPlan`, consommés par Task 10 (exécution manuelle en prod).

- [ ] **Step 1: Écrire le script**

`~/projects/Farois-wyre-ldap/farois/cron/pg_role_sync.py` :

```python
"""Synchronisation des roles PostgreSQL individuels membres de ftth_editor
depuis un groupe AD (chantier "Authentification LDAP wyre", 2026-08-17).

Modele (docs/superpowers/specs/2026-08-17-wyre-ldap-auth-design.md) :
  - Un role LOGIN individuel par membre du groupe AD (sAMAccountName),
    membre de ftth_editor (GRANT ftth_editor TO "<personne>") -- heritage
    des grants existants, aucun mot de passe stocke (auth deleguee a
    pg_hba.conf, methode ldap).
  - create/disable UNIQUEMENT (jamais de DROP ROLE) : un role absent du
    groupe AD perd sa capacite de connexion (NOLOGIN) mais reste trace.
    Meme philosophie que farois/cron/ldap_sync.py pour ref.users.
  - Garde anti-mass-disable : enumeration AD vide -> aucune desactivation.
  - Pas de reactivation automatique d'un role deja desactive.
  - Nom du groupe AD source : LDAP_GROUP_WYRE_PG_USERS (env). Vide -> le
    script refuse de tourner (RuntimeError), meme garde que ldap_sync pour
    AZURE_GROUP_<ROLE>.
  - Connexion Postgres en ftth_admin (CREATEROLE) -- jamais postgres,
    jamais la connexion applicative bas-privilege des autres jobs cron
    (Contrainte globale 5 du plan).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from farois.ui.auth import ldap_ad

logger = logging.getLogger(__name__)

GROUP_ENV_VAR = "LDAP_GROUP_WYRE_PG_USERS"
GROUP_ROLE = "ftth_editor"


@dataclass
class SyncPlan:
    to_create: list[str] = field(default_factory=list)
    to_disable: list[str] = field(default_factory=list)
    guard_tripped: bool = False


def compute_plan(desired_usernames: set[str], current: dict[str, bool]) -> SyncPlan:
    """Calcule create/disable a partir du desire (AD) et du courant (DB).

    `desired_usernames` : sAMAccountName des membres actuels du groupe AD.
    `current` : {rolname: rolcanlogin} des roles deja membres de
    ftth_editor en base.

    Regles :
      - username desire absent de `current`               -> CREATE ;
      - rolname present, rolcanlogin=True, absent du desire -> DISABLE
        (NOLOGIN, jamais DROP) ;
      - present des deux cotes (LOGIN ou non)              -> NO-OP (pas
        de reactivation automatique d'un role deja desactive) ;
      - garde : desired vide -> AUCUNE desactivation calculee.
    """
    plan = SyncPlan()
    for username in desired_usernames:
        if username not in current:
            plan.to_create.append(username)
    if not desired_usernames:
        plan.guard_tripped = True
        return plan
    for rolname, can_login in current.items():
        if rolname not in desired_usernames and can_login:
            plan.to_disable.append(rolname)
    return plan


def collect_desired_usernames(conn, cfg, group: str) -> set[str]:
    """Enumere les membres actifs du groupe AD -> {sAMAccountName}."""
    return {
        m.username for m in ldap_ad.list_group_members(conn, cfg, group)
        if not m.disabled and m.username
    }


def _quote_ident(name: str) -> str:
    """Echappe un identifiant SQL (double les guillemets doubles)."""
    return '"' + name.replace('"', '""') + '"'


def _apply_plan(cur, plan: SyncPlan) -> None:
    for username in plan.to_create:
        ident = _quote_ident(username)
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (username,))
        if cur.fetchone() is None:
            cur.execute(f"CREATE ROLE {ident} LOGIN")
            logger.info("pg_role_sync: role %s cree", username)
        else:
            cur.execute(f"ALTER ROLE {ident} LOGIN")
            logger.info("pg_role_sync: role %s reactive (LOGIN)", username)
        cur.execute(f"GRANT {GROUP_ROLE} TO {ident}")
    for rolname in plan.to_disable:
        cur.execute(f"ALTER ROLE {_quote_ident(rolname)} NOLOGIN")
        logger.info("pg_role_sync: role %s desactive (NOLOGIN)", rolname)


def run(dry_run: bool = False, cfg=None) -> SyncPlan:
    """Point d'entree : connexion ftth_admin, enumeration AD, plan, application."""
    import psycopg2

    group = os.getenv(GROUP_ENV_VAR, "").strip()
    if not group:
        raise RuntimeError(f"{GROUP_ENV_VAR} non defini")

    cfg = cfg or ldap_ad.LdapConfig.from_env()
    svc = ldap_ad.service_connection(cfg)
    desired = collect_desired_usernames(svc, cfg, group)

    conn = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "farois_ftth"),
        user="ftth_admin",
        password=os.environ["FTTH_ADMIN_PASSWORD"],
    )
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT r.rolname, r.rolcanlogin FROM pg_roles r "
                "JOIN pg_auth_members m ON m.member = r.oid "
                "JOIN pg_roles g ON g.oid = m.roleid AND g.rolname = %s",
                (GROUP_ROLE,),
            )
            current = {row[0]: row[1] for row in cur.fetchall()}
            plan = compute_plan(desired, current)
            if plan.guard_tripped:
                logger.error(
                    "pg_role_sync: enumeration AD vide -> AUCUNE desactivation "
                    "(garde anti-mass-disable)"
                )
            if dry_run:
                conn.rollback()
                logger.info("pg_role_sync DRY-RUN: %s", plan)
                return plan
            _apply_plan(cur, plan)
            conn.commit()
        logger.info("pg_role_sync OK: %s", plan)
        return plan
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="Synchronisation groupe AD -> roles Postgres ftth_editor")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    print(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Écrire les tests (logique pure, pas de DB ni LDAP réels)**

`~/projects/Farois-wyre-ldap/tests/unit/cron/test_pg_role_sync.py` :

```python
from farois.cron import pg_role_sync as s


def test_creates_new_and_disables_missing():
    desired = {"jdupont", "asmith"}
    current = {"asmith": True, "bold": True}
    plan = s.compute_plan(desired, current)
    assert plan.to_create == ["jdupont"]
    assert plan.to_disable == ["bold"]
    assert not plan.guard_tripped


def test_existing_active_role_not_touched():
    desired = {"asmith"}
    current = {"asmith": True}
    plan = s.compute_plan(desired, current)
    assert plan.to_create == []
    assert plan.to_disable == []


def test_already_disabled_role_not_redisabled():
    desired = {"asmith"}
    current = {"asmith": False}
    plan = s.compute_plan(desired, current)
    assert plan.to_create == []
    assert plan.to_disable == []  # rolcanlogin deja False -> pas de re-disable


def test_guard_blocks_disable_when_ad_group_empty():
    desired = set()
    current = {"asmith": True, "bold": True}
    plan = s.compute_plan(desired, current)
    assert plan.guard_tripped
    assert plan.to_disable == []
    assert plan.to_create == []


def test_quote_ident_escapes_double_quotes():
    assert s._quote_ident('a"b') == '"a""b"'


def test_quote_ident_wraps_plain_name():
    assert s._quote_ident("jdupont") == '"jdupont"'
```

- [ ] **Step 3: Exécuter les tests via le harnais `python3`**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-wyre-ldap && PYTHONPATH=. python3 - <<PY
import importlib.util, sys
spec = importlib.util.spec_from_file_location("tpgrs", "tests/unit/cron/test_pg_role_sync.py")
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

Résultat attendu : 6 lignes `PASS`, puis `--- 0 echec(s)`, code de sortie 0. Si `ModuleNotFoundError: ldap3` apparaît (import de `farois.ui.auth.ldap_ad` en tête de `pg_role_sync.py`), relancer la même commande via `docker exec farois-worker` à la place de `python3` nu (l'environnement du conteneur a `ldap3` installé) :

```bash
ssh sdadmin@192.168.160.31 'docker cp ~/projects/Farois-wyre-ldap/farois/cron/pg_role_sync.py farois-worker:/opt/farois/farois/cron/pg_role_sync.py && docker cp ~/projects/Farois-wyre-ldap/tests/unit/cron/test_pg_role_sync.py farois-worker:/tmp/test_pg_role_sync.py && docker exec -w /opt/farois farois-worker python3 - <<PY
import importlib.util, sys
spec = importlib.util.spec_from_file_location("tpgrs", "/tmp/test_pg_role_sync.py")
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

- [ ] **Step 4: Commit (sans push)**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/Farois-wyre-ldap && git add farois/cron/pg_role_sync.py tests/unit/cron/test_pg_role_sync.py && git commit -m "feat(cron): script de synchro roles Postgres individuels <- groupe AD (ftth_editor)"'
```

Résultat attendu : `2 files changed, ... insertions(+)`.

---

## `qgis_repo` (dépôt `~/projects/qgis_repo`)

### Task 6: Worktree qgis_repo

**Files:** aucun — opération git uniquement.

**Interfaces:** Produit une worktree `~/projects/qgis_repo-wyre-ldap` sur une nouvelle branche `feat/wyre-ldap-auth`, consommée par les Tasks 7, 8, 9.

- [ ] **Step 1: Créer la worktree isolée**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo && git worktree add -b feat/wyre-ldap-auth ~/projects/qgis_repo-wyre-ldap main'
```

Résultat attendu : `Preparing worktree (new branch 'feat/wyre-ldap-auth')`.

- [ ] **Step 2: Vérifier l'isolation**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo && git status --short && git worktree list'
```

Résultat attendu : `git status` vide sur le tree partagé ; `git worktree list` fait apparaître les deux entrées.

---

### Task 7: `credentials.json` + résolution de l'identité AD (`DEFAULT_USER`)

**Files:**
- Modify: `~/projects/qgis_repo-wyre-ldap/plugin-repo/packages/constructel_bridge/credentials.json`
- Modify: `~/projects/qgis_repo-wyre-ldap/plugin-repo/packages/constructel_bridge/bridge_plugin.py:1,90-91,938-953`

**Interfaces:**
- Produit : `DEFAULT_USER` (module-level, maintenant l'identité AD de la personne), `_resolve_os_username()` (nouvelle fonction module-level), consommés par Task 8 et par `_get_qgis_username()` existant.

- [ ] **Step 1: Retirer `user`/`password` du bloc `wyre` de `credentials.json`**

Remplacer le contenu actuel :

```json
{
    "wyre": {
        "host": "192.168.160.31",
        "port": 5432,
        "dbname": "farois_ftth",
        "user": "ftth_editor",
        "password": "aXQ0RG9BNXV6aHZjZk9OWVVsUWNXQT09",
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
        "password": "Nlk1c1E4eGVuOHRoNVpBcUZ3MUFLQW8z",
        "sslmode": "require"
    }
}
```

par :

```json
{
    "wyre": {
        "host": "192.168.160.31",
        "port": 5432,
        "dbname": "farois_ftth",
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
        "password": "Nlk1c1E4eGVuOHRoNVpBcUZ3MUFLQW8z",
        "sslmode": "require"
    }
}
```

(le bloc `be` ne change pas.)

- [ ] **Step 2: Extraire la résolution du nom d'utilisateur en fonction module-level**

Dans `bridge_plugin.py`, la méthode existante (vers la ligne 938) :

```python
    def _get_qgis_username(self) -> str:
        """Recupere le nom d'utilisateur depuis les settings QGIS ou l'OS."""
        settings = QgsSettings()

        explicit = settings.value("constructel_bridge/username", "")
        if explicit:
            return explicit

        try:
            profile = QgsApplication.instance().userProfileManager().userProfile()
            if profile and profile.name() and profile.name() != "default":
                return profile.name()
        except Exception:
            pass

        import getpass
        return getpass.getuser()
```

devient (extraction en fonction libre + méthode réduite à un simple appel, comportement externe inchangé pour les appelants existants de `self._get_qgis_username()`) :

```python
def _resolve_os_username() -> str:
    """Determine l'identifiant OS/QGIS de la personne courante.

    Attendu = sAMAccountName AD sur un poste joint au domaine (chantier
    "Authentification LDAP wyre") -- a valider empiriquement (cf. Task 10,
    verification QGIS n1). Utilisee a la fois pour DEFAULT_USER (identite
    de connexion PG "wyre") et pour l'enregistrement dans ref.users.
    """
    settings = QgsSettings()

    explicit = settings.value("constructel_bridge/username", "")
    if explicit:
        return explicit

    try:
        profile = QgsApplication.instance().userProfileManager().userProfile()
        if profile and profile.name() and profile.name() != "default":
            return profile.name()
    except Exception:
        pass

    import getpass
    return getpass.getuser()
```

et, dans la classe du plugin :

```python
    def _get_qgis_username(self) -> str:
        """Recupere le nom d'utilisateur depuis les settings QGIS ou l'OS."""
        return _resolve_os_username()
```

Placer la fonction libre `_resolve_os_username()` juste avant la définition de la classe principale du plugin (avant sa première utilisation par `DEFAULT_USER`, donc physiquement plus haut dans le fichier que la ligne 90 — un simple déplacement de définition, `QgsSettings`/`QgsApplication` sont déjà importés en tête de fichier).

- [ ] **Step 3: Remplacer `DEFAULT_USER` et supprimer `_DEFAULT_PW`**

Ligne ~90-91, remplacer :

```python
DEFAULT_USER = _WYRE_CREDS["user"]
_DEFAULT_PW = base64.b64decode(_WYRE_CREDS["password"]).decode()
```

par :

```python
DEFAULT_USER = _resolve_os_username()
```

(`_DEFAULT_PW` disparaît complètement — Task 8 traite tous ses points de consommation.)

- [ ] **Step 4: Vérification manuelle — pas de crash à l'import**

Pas de suite pytest pour ce module (dépend de l'API PyQGIS, non mockable simplement hors QGIS) : vérification par relecture + `python3 -m py_compile` pour la syntaxe, et test QGIS réel en Task 9.

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-wyre-ldap && python3 -m py_compile plugin-repo/packages/constructel_bridge/bridge_plugin.py && echo "SYNTAXE OK"'
```

Résultat attendu : `SYNTAXE OK`.

- [ ] **Step 5: Commit (sans push)**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-wyre-ldap && git add plugin-repo/packages/constructel_bridge/credentials.json plugin-repo/packages/constructel_bridge/bridge_plugin.py && git commit -m "feat(constructel_bridge): DEFAULT_USER derive de l identite AD/OS, retrait user/password wyre de credentials.json"'
```

Résultat attendu : `2 files changed, ... insertions(+), ... deletions(-)`.

---

### Task 8: Retrait du mot de passe par défaut partagé (`_DEFAULT_PW`) sur tous les chemins de connexion `wyre`

**Files:**
- Modify: `~/projects/qgis_repo-wyre-ldap/plugin-repo/packages/constructel_bridge/bridge_plugin.py` (tous les points listés ci-dessous)
- Modify: `~/projects/qgis_repo-wyre-ldap/plugin-repo/packages/constructel_bridge/bridge_dialog.py`

**Interfaces:**
- Consomme de Task 7 : `DEFAULT_USER` (identité AD), suppression de `_DEFAULT_PW`.
- Produit : plus aucun mot de passe `wyre` stocké (Auth Manager ou settings) ; QGIS affiche son dialogue natif de saisie pour `wyre` à chaque session non authentifiée. `be` reste inchangé (toujours `use_authcfg=True`, mot de passe partagé issu de `credentials.json`).

Ce fichier a déjà subi 4 rounds de hotfix sur ce chemin exact de code (fuite du mot de passe `wyre` via les identités connues des couches sauvegardées) — chaque sous-étape ci-dessous est délibérément exhaustive et doit être appliquée intégralement, pas partiellement.

- [ ] **Step 1: `_BridgeCredentials` — ne plus répondre pour le realm `wyre`**

Remplacer (vers la ligne 181-224) :

```python
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

        Le repli sur simple correspondance de *username* est ANCRE sur
        BE_HOST (pas DEFAULT_HOST) : `_BridgeCredentials` est installe
        comme le singleton QgsCredentials actif pour toute la session
        QGIS, donc sans cet ancrage une demande d'authentification vers
        un serveur PG TIERS ou le username serait egalement
        `bureau_etudes` recevrait par erreur le mot de passe `be` —
        fuite de credentials vers un serveur externe. On ancre sur
        BE_HOST (pas DEFAULT_HOST) car credentials.json expose des
        overrides BE_DB_HOST/BE_DB_NAME independants de wyre : si `be`
        est un jour reconfigure sur un autre serveur, l'ancrage doit
        suivre SA propre configuration, pas celle de `wyre`. Aujourd'hui
        BE_HOST == DEFAULT_HOST donc le comportement est identique.

        Retourne None si le realm ne nous concerne pas.
        """
        if BE_ENABLED and BE_HOST in realm and (f"user='{BE_USER}'" in realm or username == BE_USER):
            return BE_USER, _BE_PW
        if DEFAULT_HOST in realm:
            return self._username, self._password
        return None
```

par :

```python
    def __init__(self, fallback):
        self._fallback = fallback
        super().__init__()  # appelle setInstance(self) en interne

    def _credentials_for(self, realm, username):
        """Resout le couple (utilisateur, mot de passe) pour un realm.

        Seul `be` est fourni automatiquement (mot de passe partage,
        issu de credentials.json). `wyre` n'a plus de mot de passe
        connu a l'avance (auth LDAP individuelle) : toute demande pour
        son realm est deleguee au dialogue QGIS natif via `request()`.

        Retourne None si le realm ne nous concerne pas (ou concerne
        `wyre`, qui doit toujours passer par le dialogue natif).
        """
        if BE_ENABLED and BE_HOST in realm and (f"user='{BE_USER}'" in realm or username == BE_USER):
            return BE_USER, _BE_PW
        return None
```

(`update_password()` disparaît — plus aucun appelant après le Step 4 ci-dessous.)

- [ ] **Step 2: `_precache_pg_credentials()` — ne plus pré-cacher `wyre`**

Remplacer (vers la ligne 262-290) :

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

par :

```python
def _precache_pg_credentials():
    """Pre-cache les credentials PG de `be` (bureau d'etudes).

    `wyre` n'a plus de mot de passe par defaut (authentification LDAP,
    saisie a chaque session) : rien a pre-cacher pour cette connexion,
    QGIS doit demander le mot de passe nativement.
    """
    if not BE_ENABLED:
        return
    creds = QgsCredentials.instance()
    for realm in (
        f"dbname='{BE_DBNAME}' host={BE_HOST} port={BE_PORT} user='{BE_USER}'",
        f"dbname='{BE_DBNAME}' host={BE_HOST} port={BE_PORT} sslmode={BE_SSLMODE} user='{BE_USER}'",
    ):
        creds.put(realm, BE_USER, _BE_PW)
```

- [ ] **Step 3: `_auto_connect()` — ne plus se connecter silencieusement sans mot de passe connu**

Remplacer (vers la ligne 760) :

```python
    def _auto_connect(self):
        """Tente une connexion silencieuse au demarrage du plugin.

        Utilise le mot de passe stocke dans Auth Manager, ou a defaut
        le mot de passe par defaut du fichier credentials.json.
        En cas d'echec, aucune erreur n'est affichee — l'utilisateur
        pourra se connecter manuellement via le menu.
        """
        if self._connected:
            return
        password = _retrieve_password_encrypted() or _DEFAULT_PW
        self._connect(password, silent=True)
```

par :

```python
    def _auto_connect(self):
        """Tente une connexion silencieuse au demarrage, UNIQUEMENT si un
        mot de passe a deja ete memorise (Auth Manager, session precedente
        avant ce chantier).

        Depuis le passage en auth LDAP, `wyre` n'a plus de mot de passe
        par defaut ni de sauvegarde automatique (cf. Step 4 ci-dessous) :
        si rien n'est disponible, on n'affiche PAS de dialogue ici — la
        personne doit cliquer Connecter (menu / bouton), qui ouvre le
        dialogue de saisie natif.
        """
        if self._connected:
            return
        password = _retrieve_password_encrypted()
        if not password:
            self._log(
                "Auto-connexion 'wyre' ignoree (aucun mot de passe memorise) "
                "— connexion manuelle requise.",
                Qgis.Info,
            )
            return
        self._connect(password, silent=True)
```

- [ ] **Step 4: `_on_connect()` / `ConstructelConnectDialog` — dialogue sans mot de passe par défaut ni case "mémoriser"**

Dans `bridge_dialog.py`, remplacer :

```python
class ConstructelConnectDialog(QDialog):
    """Dialogue simple pour saisir le mot de passe ftth_editor."""

    def __init__(self, parent=None, host="localhost", port=5432, dbname="farois_ftth", default_password=""):
```

par :

```python
class ConstructelConnectDialog(QDialog):
    """Dialogue simple pour saisir le mot de passe AD (auth LDAP wyre)."""

    def __init__(self, parent=None, host="localhost", port=5432, dbname="farois_ftth", user=""):
```

remplacer :

```python
        self._user_edit = QLineEdit("ftth_editor")
        self._user_edit.setReadOnly(True)
        form.addRow(tr("dialog.role"), self._user_edit)

        # Password field with show/hide toggle
        pw_layout = QHBoxLayout()
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.Password)
        self._password_edit.setPlaceholderText(tr("dialog.password_placeholder"))
        if default_password:
            self._password_edit.setText(default_password)
        pw_layout.addWidget(self._password_edit)
```

par :

```python
        self._user_edit = QLineEdit(user)
        self._user_edit.setReadOnly(True)
        form.addRow(tr("dialog.role"), self._user_edit)

        # Password field with show/hide toggle
        pw_layout = QHBoxLayout()
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.Password)
        self._password_edit.setPlaceholderText(tr("dialog.password_placeholder"))
        pw_layout.addWidget(self._password_edit)
```

et supprimer entièrement (case "mémoriser le mot de passe", devenue sans effet — plus aucun appelant ne stocke de mot de passe `wyre`) :

```python
        self._save_check = QCheckBox(tr("dialog.save_password"))
        self._save_check.setChecked(True)
        form.addRow("", self._save_check)
```

et supprimer la méthode :

```python
    def save_password(self) -> bool:
        return self._save_check.isChecked()
```

(le `QCheckBox` de l'import `from qgis.PyQt.QtWidgets import (QCheckBox, ...)` devient inutilisé dans ce fichier — retirer `QCheckBox` de la liste d'imports.)

Dans `bridge_plugin.py`, remplacer (vers la ligne 817-829) :

```python
    def _on_connect(self):
        """Action manuelle: dialogue de connexion."""
        from .bridge_dialog import ConstructelConnectDialog

        dlg = ConstructelConnectDialog(
            self.iface.mainWindow(),
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            dbname=DEFAULT_DBNAME,
            default_password=_DEFAULT_PW,
        )
        if dlg.exec_() == QDialog.Accepted:
            password = dlg.password() or _DEFAULT_PW
            if dlg.save_password():
                _store_password_encrypted(password)
            self._connect(password)
```

par :

```python
    def _on_connect(self):
        """Action manuelle: dialogue de connexion (mot de passe AD, jamais memorise)."""
        from .bridge_dialog import ConstructelConnectDialog

        dlg = ConstructelConnectDialog(
            self.iface.mainWindow(),
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            dbname=DEFAULT_DBNAME,
            user=DEFAULT_USER,
        )
        if dlg.exec_() == QDialog.Accepted:
            self._connect(dlg.password())
```

- [ ] **Step 5: `_connect()` — ne plus référencer `_bridge_credentials.update_password` ni stocker en Auth Manager**

Remplacer (vers la ligne 831-888), les deux extraits suivants dans `_connect()` :

```python
        self._password = password
        # Mettre a jour le handler de credentials avec le mot de passe courant
        if hasattr(self, "_bridge_credentials"):
            self._bridge_credentials.update_password(password)
        qgis_user = self._get_qgis_username()
```

par :

```python
        self._password = password
        qgis_user = self._get_qgis_username()
```

et :

```python
        try:
            self._setup_qgis_pg_connection(password, use_authcfg=True)
        except Exception as exc:
            self._log(f"QGIS PG config failed: {exc}", Qgis.Warning)
```

par :

```python
        try:
            self._setup_qgis_pg_connection(password, use_authcfg=False)
        except Exception as exc:
            self._log(f"QGIS PG config failed: {exc}", Qgis.Warning)
```

(la branche d'échec de connexion, quelques lignes plus haut dans la même méthode, appelait déjà `use_authcfg=False` — les deux chemins, succès et échec, sont désormais cohérents : `wyre` n'utilise plus jamais Auth Manager.)

- [ ] **Step 6: Remplacer les 5 usages restants de `getattr(self, "_password", None) or _DEFAULT_PW`**

Ces 5 sites suivent tous le même pattern mécanique — remplacer `or _DEFAULT_PW` par `or ""` (chaîne vide : si la session n'a pas encore de mot de passe connu, QGIS retombera sur son dialogue natif au moment de charger la couche concernée, exactement comme pour un realm inconnu de `_BridgeCredentials`) :

1. `_strip_authcfg_from_dom` (vers la ligne 704) :
   ```python
   password = getattr(self, "_password", None) or _DEFAULT_PW
   ```
   → `password = getattr(self, "_password", None) or ""`

2. `_fix_layer_credentials` (vers la ligne 1032) : même remplacement.

3. `_ensure_ref_layers` (vers la ligne 1197) — charge la couche cachée `ref.v_form_lists` utilisée par les listes déroulantes ValueRelation des formulaires :
   ```python
   password = getattr(self, "_password", None) or _DEFAULT_PW
   uri = QgsDataSourceUri()
   uri.setConnection(
       DEFAULT_HOST, str(DEFAULT_PORT), DEFAULT_DBNAME,
       DEFAULT_USER, password, DEFAULT_SSLMODE,
   )
   ```
   → même remplacement (`or ""`), le reste de la fonction est inchangé.

4. `_on_init_project` (vers la ligne 1730) : même remplacement.

5. `_read_and_clean_project` (vers la ligne 1850) : même remplacement.

- [ ] **Step 6bis: Vérification exhaustive par grep — plus aucune occurrence oubliée**

```bash
ssh sdadmin@192.168.160.31 "grep -n '_DEFAULT_PW' ~/projects/qgis_repo-wyre-ldap/plugin-repo/packages/constructel_bridge/bridge_plugin.py"
```

Résultat attendu : **aucune ligne** (grep retourne un statut non-zéro / liste vide). Si une ligne apparaît encore malgré les 5 sites ci-dessus (le fichier a pu évoluer depuis l'écriture de ce plan), l'appliquer avec le même remplacement `or _DEFAULT_PW` → `or ""` avant de continuer — ne jamais laisser une occurrence résiduelle, chacune est un chemin où l'ancien mot de passe partagé pourrait encore être utilisé.

- [ ] **Step 7: Vérification syntaxique**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-wyre-ldap && python3 -m py_compile plugin-repo/packages/constructel_bridge/bridge_plugin.py plugin-repo/packages/constructel_bridge/bridge_dialog.py && echo "SYNTAXE OK"'
```

Résultat attendu : `SYNTAXE OK`.

- [ ] **Step 8: Grep de non-régression — plus aucune référence à `_DEFAULT_PW` ni `save_password`**

```bash
ssh sdadmin@192.168.160.31 "grep -rn -E '_DEFAULT_PW|save_password|default_password' ~/projects/qgis_repo-wyre-ldap/plugin-repo/packages/constructel_bridge/*.py"
```

Résultat attendu : aucune ligne.

- [ ] **Step 9: Commit (sans push)**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-wyre-ldap && git add plugin-repo/packages/constructel_bridge/bridge_plugin.py plugin-repo/packages/constructel_bridge/bridge_dialog.py && git commit -m "fix(constructel_bridge): wyre ne stocke plus jamais de mot de passe (authcfg retire, dialogue natif a chaque session)"'
```

Résultat attendu : `2 files changed, ... insertions(+), ... deletions(-)`.

---

### Task 9: Version bump + reconstruction du zip

**Files:**
- Modify: `~/projects/qgis_repo-wyre-ldap/plugin-repo/packages/constructel_bridge/metadata.txt`

**Interfaces:**
- Consomme de Task 7 + Task 8 : le code source mis à jour.
- Produit : `constructel_bridge.zip` reconstruit, consommé par Task 10 (publication).

- [ ] **Step 1: Insérer l'entrée de changelog dans `metadata.txt`**

`release.py` ne touche pas au champ `changelog=` (constaté au chantier du 2026-07-30) — l'écrire à la main. Insérer cette ligne juste après `changelog=`, avant l'entrée `v1.5.3` existante :

```
changelog=v1.6.0 - fix(security): la connexion wyre n'utilise plus un mot de passe partage embarque dans credentials.json. Authentification individuelle par mot de passe AD (meme annuaire que Farois), jamais memorisee, saisie a chaque session. Necessite : migration Farois 375 (ftth_editor -> role groupe) + pg_hba.conf auth LDAP + roles Postgres individuels synchronises depuis un groupe AD.
```

- [ ] **Step 2: Lancer la release depuis le répertoire du plugin**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-wyre-ldap/plugin-repo/packages/constructel_bridge && python3 release.py 1.6.0'
```

Résultat attendu :
```
Releasing constructel_bridge v1.6.0
  metadata.txt -> 1.6.0
  plugins.xml  -> 1.6.0
  constructel_bridge.zip rebuilt (... KB)
Done.
```

- [ ] **Step 3: Vérifier que le zip embarque le code à jour (plus de mot de passe wyre, plus de `_DEFAULT_PW`)**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-wyre-ldap/plugin-repo/packages && python3 -c "
import json, zipfile
z = zipfile.ZipFile(\"constructel_bridge.zip\")
raw = json.loads(z.read(\"constructel_bridge/credentials.json\"))
assert \"user\" not in raw[\"wyre\"] and \"password\" not in raw[\"wyre\"], raw[\"wyre\"]
assert raw[\"be\"][\"user\"] == \"bureau_etudes\"
src = z.read(\"constructel_bridge/bridge_plugin.py\").decode()
assert \"_DEFAULT_PW\" not in src
meta = z.read(\"constructel_bridge/metadata.txt\").decode()
assert \"version=1.6.0\" in meta
print(\"ZIP OK - version 1.6.0, wyre sans user/password, _DEFAULT_PW absent\")"'
```

Résultat attendu : `ZIP OK - version 1.6.0, wyre sans user/password, _DEFAULT_PW absent`.

- [ ] **Step 4: Vérifier que l'arbre servi n'a pas bougé (publication pas encore faite)**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo && grep -n "^version=" plugin-repo/packages/constructel_bridge/metadata.txt && git status --short plugin-repo/ | wc -l'
```

Résultat attendu : `version=1.5.3` et `0`.

- [ ] **Step 5: Commit (sans push)**

```bash
ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo-wyre-ldap && git add plugin-repo/packages/constructel_bridge/metadata.txt plugin-repo/plugins.xml plugin-repo/packages/constructel_bridge.zip && git commit -m "release(constructel_bridge): 1.6.0 - authentification LDAP individuelle wyre"'
```

Résultat attendu : `3 files changed, ...`.

---

## Intégration

### Task 10: GATE — Vérification bout-en-bout et publication

**Files:**
- Modify (VPS, non versionné) : `PGDATA/pg_hba.conf` du conteneur `ftth-postgres` (application manuelle, cf. Step 3).
- Modify : `~/projects/Farois` (merge de `feat/wyre-ldap-auth`) et `~/projects/qgis_repo` (merge de `feat/wyre-ldap-auth`) — **uniquement après GO de Simon**.

**Interfaces:**
- Consomme de Task 2 : `375_ftth_editor_nologin`.
- Consomme de Task 3 + 4 : la ligne `pg_hba.conf` + le templating du mot de passe.
- Consomme de Task 5 : `farois/cron/pg_role_sync.py`.
- Consomme de Task 9 : `constructel_bridge.zip` v1.6.0 (ou version choisie).

**Steps**

- [ ] **GATE — GO explicite de Simon requis** pour l'ensemble des étapes suivantes (application en base, rechargement de `pg_hba.conf`, exécution du script de synchro, merges/push, publication du plugin). Ne pas enchaîner sans.

- [ ] **Pré-requis bloquant à vérifier avant tout le reste** : le nom du groupe AD (`LDAP_GROUP_WYRE_PG_USERS`) doit avoir été obtenu de l'IT et ajouté à `docker/.env` sur le VPS. Si absent, **STOP** — les étapes suivantes peuvent quand même appliquer la migration 375 et `pg_hba.conf` (elles ne dépendent pas du groupe), mais aucun rôle individuel ne pourra être créé tant que ce nom manque.

- [ ] **Appliquer `pg_hba.conf` AVANT la migration 375** (ordre impératif — cf. avertissement dans la migration : sinon coupure d'accès entre le retrait de `LOGIN` et l'activation de l'auth LDAP). Copier le fichier substitué dans le conteneur en cours d'exécution (pas de rebuild d'image nécessaire pour ce déploiement initial) :
  ```bash
  ssh sdadmin@192.168.160.31 '
  set -a; . ~/projects/Farois/docker/.env.secrets; set +a
  esc_pw=$(printf "%s" "$LDAP_BIND_PASSWORD" | sed -e "s/[\\/&]/\\\\&/g")
  sed "s/__LDAP_BIND_PASSWORD_PLACEHOLDER__/${esc_pw}/g" ~/projects/Farois-wyre-ldap/docker/postgres/pg_hba.conf > /tmp/pg_hba_substituted.conf
  docker cp /tmp/pg_hba_substituted.conf ftth-postgres:/var/lib/postgresql/data/pgdata/pg_hba.conf
  docker exec ftth-postgres chown postgres:postgres /var/lib/postgresql/data/pgdata/pg_hba.conf
  docker exec ftth-postgres chmod 600 /var/lib/postgresql/data/pgdata/pg_hba.conf
  rm /tmp/pg_hba_substituted.conf
  '
  ```
  Résultat attendu : aucune erreur, le `docker cp` réussit silencieusement.

- [ ] Recharger la configuration Postgres (pas de restart nécessaire, `pg_hba.conf` se recharge à chaud) :
  ```bash
  ssh sdadmin@192.168.160.31 'set -a; . ~/projects/Farois/docker/.env.secrets; set +a; docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" ftth-postgres psql -U postgres -d farois_ftth -c "SELECT pg_reload_conf();"'
  ```
  Résultat attendu : `pg_reload_conf` → `t`.

- [ ] Vérifier qu'aucune erreur de parsing n'est survenue :
  ```bash
  ssh sdadmin@192.168.160.31 'docker logs --tail 30 ftth-postgres 2>&1 | grep -i -E "hba|error" || echo "aucune erreur hba"'
  ```
  Résultat attendu : pas de ligne `FATAL`/`invalid` liée à `pg_hba.conf`.

- [ ] Lister ce qui sera appliqué (dry-run de la migration) — **il ne doit y avoir QUE la 375** :
  ```bash
  ssh sdadmin@192.168.160.31 'docker exec farois-worker farois --dry-run deploy migrate 2>&1 | grep -v WARNING'
  ```
  Résultat attendu : `1 migration(s) en attente:` puis `  - 375_ftth_editor_nologin`. Si d'autres migrations apparaissent, **STOP** et remonter à Simon.

- [ ] Copier la migration dans le conteneur worker (même geste que pour la 328 au chantier précédent — le `sql/` est baké dans l'image, pas de bind mount) :
  ```bash
  ssh sdadmin@192.168.160.31 'docker cp ~/projects/Farois-wyre-ldap/sql/migrations/375_ftth_editor_nologin.sql farois-worker:/opt/farois/sql/migrations/ && docker exec farois-worker ls -l /opt/farois/sql/migrations/375_ftth_editor_nologin.sql'
  ```

- [ ] Appliquer la migration :
  ```bash
  ssh sdadmin@192.168.160.31 'docker exec farois-worker farois deploy migrate 2>&1 | grep -v "WARNING - farois.env_compat"'
  ```
  Résultat attendu : le banner `375 - ...`, `NOTICE: OK: ftth_editor - LOGIN retire`, puis `375_ftth_editor_nologin OK` et `1 migration(s) appliquee(s)`.

- [ ] Vérification SQL — `ftth_editor` est bien `NOLOGIN` :
  ```bash
  ssh sdadmin@192.168.160.31 'set -a; . ~/projects/Farois/docker/.env.secrets; set +a; docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" ftth-postgres psql -U postgres -d farois_ftth -c "SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname = \x27ftth_editor\x27;"'
  ```
  Résultat attendu : `ftth_editor | f`.

- [ ] Vérification réseau — un test de connexion `ftth_editor` par mot de passe échoue désormais (coupure nette voulue) :
  ```bash
  ssh sdadmin@192.168.160.31 'set -a; . ~/projects/Farois/docker/.env.secrets; set +a; docker exec -e PGPASSWORD="$FTTH_EDITOR_PASSWORD" ftth-postgres psql "host=192.168.160.31 port=5432 dbname=farois_ftth user=ftth_editor sslmode=require" -c "SELECT 1;" 2>&1'
  ```
  Résultat attendu : `FATAL: role "ftth_editor" is not permitted to log in`.

- [ ] Ajouter `LDAP_GROUP_WYRE_PG_USERS=<nom fourni par l'IT>` à `docker/.env` sur le serveur, puis exécuter le script de synchro en dry-run d'abord :
  ```bash
  ssh sdadmin@192.168.160.31 'docker cp ~/projects/Farois-wyre-ldap/farois/cron/pg_role_sync.py farois-worker:/opt/farois/farois/cron/pg_role_sync.py && docker exec -w /opt/farois farois-worker python3 -m farois.cron.pg_role_sync --dry-run'
  ```
  Résultat attendu : liste des rôles à créer (nouveaux membres du groupe AD), aucun à désactiver au premier passage.

- [ ] Exécuter le script de synchro pour de vrai :
  ```bash
  ssh sdadmin@192.168.160.31 'docker exec -w /opt/farois farois-worker python3 -m farois.cron.pg_role_sync'
  ```
  Résultat attendu : `pg_role_sync OK: SyncPlan(to_create=[...], to_disable=[], guard_tripped=False)`.

- [ ] Vérification SQL — un rôle individuel créé hérite bien des grants `ftth_editor` :
  ```bash
  ssh sdadmin@192.168.160.31 'set -a; . ~/projects/Farois/docker/.env.secrets; set +a; docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" ftth-postgres psql -U postgres -d farois_ftth -c "SELECT rolname, rolcanlogin, pg_has_role(rolname, \x27ftth_editor\x27, \x27USAGE\x27) FROM pg_roles WHERE pg_has_role(rolname, \x27ftth_editor\x27, \x27MEMBER\x27) AND rolname != \x27ftth_editor\x27;"'
  ```
  Résultat attendu : au moins une ligne, `rolcanlogin = t`, `pg_has_role = t`.

- [ ] Vérification réseau — connexion réelle par LDAP pour une personne du groupe (avec son propre mot de passe AD, saisi manuellement pour ce test, jamais scripté) :
  ```bash
  ssh sdadmin@192.168.160.31 'docker exec -it ftth-postgres psql "host=192.168.160.31 port=5432 dbname=farois_ftth user=<samaccountname_test> sslmode=require" -c "SELECT count(*) FROM infra.structures;"'
  ```
  (prompt de mot de passe interactif — Simon ou la personne testée saisit son mot de passe AD réel). Résultat attendu : le `count` s'affiche (accès `infra` hérité de `ftth_editor`), sans erreur d'authentification.

- [ ] Vérification réseau — un mauvais mot de passe est refusé par l'AD (pas par un mécanisme Postgres local) :
  ```bash
  ssh sdadmin@192.168.160.31 'docker exec ftth-postgres psql "host=192.168.160.31 port=5432 dbname=farois_ftth user=<samaccountname_test> sslmode=require password=mauvais_mot_de_passe" -c "SELECT 1;" 2>&1'
  ```
  Résultat attendu : `FATAL: LDAP authentication failed for user ...` (ou équivalent — pas un simple `password authentication failed` scram).

- [ ] Récupérer le zip sur le poste Windows de Simon, puis l'installer dans QGIS via *Extensions > Installer/Gérer les extensions > Installer depuis un ZIP* :
  ```bash
  scp sdadmin@192.168.160.31:~/projects/qgis_repo-wyre-ldap/plugin-repo/packages/constructel_bridge.zip .
  ```

- [ ] Vérification QGIS n°1 — redémarrer QGIS. Résultat attendu : **aucune connexion silencieuse** à `wyre` au démarrage (Journal des messages > Constructel Bridge affiche `Auto-connexion 'wyre' ignoree`). Cliquer *Constructel Bridge > Connexion base de données* : un dialogue s'affiche avec le rôle affiché = l'identifiant AD de la personne (pas `ftth_editor`), champ mot de passe vide, **aucune case "mémoriser"**.

- [ ] Vérification QGIS n°2 — saisir le mot de passe AD réel, valider. Résultat attendu : connexion réussie, `infra`/`osiris` accessibles comme avant. Fermer et rouvrir QGIS : le mot de passe est de nouveau demandé (pas de connexion silencieuse) — confirme l'absence de stockage.

- [ ] Vérification QGIS n°3 (non-régression `be`) — dans l'Explorateur, `be > public` reste accessible sans invite (comportement `authcfg` inchangé).

- [ ] Vérification QGIS n°4 (non-régression) — ouvrir un projet `.qgz` existant créé avant ce chantier. Résultat attendu : après saisie du mot de passe `wyre`, toutes les couches PG se chargent sans dialogue « couches inutilisables » ni reconfiguration manuelle.

- [ ] **Publication Farois** — merger dans le working tree partagé, puis pousser :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois && git merge --no-ff feat/wyre-ldap-auth -m "merge: authentification LDAP wyre - migration 375 + pg_hba + sync roles" && git log --oneline -3'
  ```

- [ ] **Publication plugin** — merger dans l'arbre servi (rend la nouvelle version visible sur `http://192.168.160.31:9080/`) :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/qgis_repo && git merge --no-ff feat/wyre-ldap-auth -m "merge: authentification LDAP wyre (constructel_bridge)" && grep -n "^version=" plugin-repo/packages/constructel_bridge/metadata.txt'
  ```

- [ ] Vérifier que le dépôt de plugins sert bien la nouvelle version :
  ```bash
  ssh sdadmin@192.168.160.31 'curl -s http://192.168.160.31:9080/plugin-repo/plugins.xml | grep -o "name=\"Constructel Bridge\" version=\"[0-9.]*\""'
  ```

- [ ] Supprimer les worktrees devenues inutiles :
  ```bash
  ssh sdadmin@192.168.160.31 'cd ~/projects/Farois && git worktree remove ~/projects/Farois-wyre-ldap && cd ~/projects/qgis_repo && git worktree remove ~/projects/qgis_repo-wyre-ldap && git worktree list'
  ```
