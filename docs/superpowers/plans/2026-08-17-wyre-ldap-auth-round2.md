# Authentification LDAP wyre — Round 2 (post-revue finale) — Implementation Plan Addendum

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this addendum task-by-task, continuing the SAME ledger as the original plan (`.superpowers/sdd/2026-08-17-wyre-ldap-auth/progress.md`).

**Goal:** Apply the 7 decisions from `docs/superpowers/specs/2026-08-17-wyre-ldap-auth-addendum1.md` — a dedicated `wyre_ldap_users` marker role, cron scheduling for the role sync, an in-memory credentials cache to close the double-prompt/disconnected-session gap, stripping `be`'s password from the distributed zip, and fixing the 9 `.qml` style files that still hardcode `user='ftth_editor'`.

**Spec:** `docs/superpowers/specs/2026-08-17-wyre-ldap-auth-design.md` + `docs/superpowers/specs/2026-08-17-wyre-ldap-auth-addendum1.md`

**Base plan:** `docs/superpowers/plans/2026-08-17-wyre-ldap-auth.md` (Tasks 1-10). This addendum's tasks amend the already-implemented, already-reviewed-clean output of Tasks 2, 3, 5, 7+8 in place (nothing has been merged or deployed — safe to amend in the same worktrees).

## Global Constraints (carried forward, unchanged)

Same as the base plan: worktree isolation, no password in a versioned file, migrations under `ftth_admin` never `postgres` — **with one explicit, documented exception**: the one-time `GRANT ftth_editor TO ftth_admin WITH ADMIN OPTION, INHERIT FALSE;` bootstrap step is executed under `postgres`, outside any numbered migration, exactly once, before the amended migration 375 is applied (same family as `deploy_roles.sh`'s existing precedent of superuser-executed administrative bootstrap outside the migration runner).

---

## Farois (worktree `~/projects/Farois-wyre-ldap`, branch `feat/wyre-ldap-auth`)

### Task 11: Amend migration 375 — add `wyre_ldap_users` marker role + ADMIN OPTION guard

**Files:**
- Modify: `sql/migrations/375_ftth_editor_nologin.sql`
- Modify: `sql/migrations/375r_rollback_ftth_editor_nologin.sql`
- Modify: `tests/unit/test_migration_375_static.py`

**Interfaces:**
- Produces: role `wyre_ldap_users` (NOLOGIN group role), consumed by Task 12 (pg_hba target) and Task 13 (pg_role_sync's membership target).

- [ ] **Step 1: Rewrite the forward migration**

Replace the full content of `sql/migrations/375_ftth_editor_nologin.sql` with:

```sql
-- ============================================================================
-- 375_ftth_editor_nologin.sql
-- ============================================================================
-- NE PAS DEPLOYER SANS VALIDATION EXPLICITE DE SIMON.
--
-- Chantier "Authentification LDAP wyre"
-- (docs/superpowers/specs/2026-08-17-wyre-ldap-auth-design.md +
-- addendum1.md, qgis_repo).
--
-- Cree le role groupe wyre_ldap_users (NOLOGIN) : c'est CE role, pas
-- ftth_editor directement, que pg_hba.conf cible (+wyre_ldap_users) et que
-- pg_role_sync.py gere (creation/desactivation des roles individuels).
-- Decouple entierement l'authentification LDAP et la synchro des roles de
-- ftth_editor lui-meme -- evite qu'un membre inattendu de ftth_editor
-- (ex. ftth_admin, une fois l'ADMIN OPTION posee ci-dessous) soit desactive
-- par erreur par pg_role_sync.
--
-- Retire aussi LOGIN de ftth_editor, qui redevient un role groupe pur.
--
-- PREREQUIS OBLIGATOIRE (geste manuel, hors migration, execute UNE SEULE
-- FOIS sous postgres -- cf. Task 10) :
--   GRANT ftth_editor TO ftth_admin WITH ADMIN OPTION, INHERIT FALSE;
-- Sans ce prerequis, ftth_admin n'a pas l'ADMIN OPTION necessaire pour
-- alterer ftth_editor (PostgreSQL 16+) ni pour GRANT son appartenance a
-- quiconque (pg_role_sync en aura besoin a chaque synchro) -- la migration
-- ci-dessous verifie ce prerequis explicitement et echoue avec un message
-- clair plutot qu'une erreur de permission cryptique si absent.
-- ============================================================================

\set ON_ERROR_STOP on
BEGIN;

\echo ''
\echo '=== Migration 375 : wyre_ldap_users + ftth_editor -> role groupe (NOLOGIN) ==='
\echo ''

-- Garde-fou : verifier l'ADMIN OPTION avant de tenter quoi que ce soit sur
-- ftth_editor, pour un message d'erreur explicite plutot qu'une erreur
-- Postgres brute ("must have admin option on role").
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_auth_members m
        JOIN pg_roles g ON g.oid = m.roleid AND g.rolname = 'ftth_editor'
        JOIN pg_roles u ON u.oid = m.member AND u.rolname = 'ftth_admin'
        WHERE m.admin_option
    ) THEN
        RAISE EXCEPTION 'ftth_admin n''a pas l''ADMIN OPTION sur ftth_editor. '
            'Executer d''abord, sous postgres (prerequis manuel, cf. Task 10) : '
            'GRANT ftth_editor TO ftth_admin WITH ADMIN OPTION, INHERIT FALSE;';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'wyre_ldap_users') THEN
        CREATE ROLE wyre_ldap_users NOLOGIN;
        RAISE NOTICE 'OK: wyre_ldap_users cree';
    ELSE
        RAISE NOTICE 'SKIP: wyre_ldap_users existe deja';
    END IF;
END $$;

COMMENT ON ROLE wyre_ldap_users IS 'Role marqueur (NOLOGIN) -- cible de pg_hba.conf (+wyre_ldap_users) et de pg_role_sync.py. Decouple de ftth_editor : n''accorde aucun privilege par lui-meme, sert uniquement au routage auth LDAP et a la synchro AD.';

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ftth_editor' AND rolcanlogin) THEN
        ALTER ROLE ftth_editor NOLOGIN;
        RAISE NOTICE 'OK: ftth_editor - LOGIN retire';
    ELSE
        RAISE NOTICE 'SKIP: ftth_editor deja NOLOGIN (ou absent)';
    END IF;
END $$;

COMMENT ON ROLE ftth_editor IS 'Role groupe (edition donnees metier infra/osiris) - individus membres via GRANT (heritage des privileges), authentifies via leur appartenance a wyre_ldap_users (pg_hba.conf)';

\echo ''
\echo 'Verification :'
SELECT rolname, rolcanlogin FROM pg_roles WHERE rolname IN ('ftth_editor', 'wyre_ldap_users');

\echo ''
\echo '  375_ftth_editor_nologin OK'
COMMIT;
```

- [ ] **Step 2: Rewrite the rollback**

Replace the full content of `sql/migrations/375r_rollback_ftth_editor_nologin.sql` with:

```sql
-- ============================================================================
-- 375r_rollback_ftth_editor_nologin.sql
-- ============================================================================
-- Restaure LOGIN sur ftth_editor et supprime wyre_ldap_users.
--
-- IMPORTANT : ce rollback a lui SEUL NE restaure PAS le flux d'authentification
-- partage pre-migration. Tant que la ligne pg_hba.conf 'ldap' pour
-- +wyre_ldap_users reste active, elle ne concerne plus ftth_editor (ce role
-- n'est plus membre de wyre_ldap_users apres ce rollback), donc une tentative
-- de connexion en ftth_editor retombe sur la regle scram-sha-256 generique
-- -- ce qui FONCTIONNE de nouveau avec le mot de passe partage existant
-- (ALTER ROLE ... NOLOGIN puis LOGIN ne touche jamais au mot de passe). Rien
-- d'autre a faire cote pg_hba pour ce rollback specifiquement : contrairement
-- a la version precedente de ce commentaire, +wyre_ldap_users ne matchait
-- QUE les membres de wyre_ldap_users, jamais ftth_editor lui-meme -- la
-- decouplage introduit par ce chantier rend ce rollback suffisant a lui seul
-- pour restaurer le login partage.
-- ============================================================================

\set ON_ERROR_STOP on
BEGIN;

\echo 'Rollback 375 : restauration LOGIN sur ftth_editor, suppression wyre_ldap_users'

ALTER ROLE ftth_editor LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT CONNECTION LIMIT 50;

COMMENT ON ROLE ftth_editor IS 'Edition donnees metier FTTH (infra, osiris) - acces complet lecture/ecriture sauf DDL';

DROP ROLE IF EXISTS wyre_ldap_users;

\echo '  375r rollback OK'
COMMIT;
```

- [ ] **Step 3: Update the static test file**

Add these test functions to `tests/unit/test_migration_375_static.py` (keep all existing tests, they still apply — `test_role_created_without_password`-style checks aren't present here but the existing 9 tests from the previous round remain valid against the new content):

```python
def test_creates_wyre_ldap_users_role():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    assert re.search(r"CREATE\s+ROLE\s+wyre_ldap_users\s+NOLOGIN", sql, re.IGNORECASE)


def test_wyre_ldap_users_creation_is_idempotent():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    assert "SELECT FROM pg_roles WHERE rolname = 'wyre_ldap_users'" in sql


def test_checks_admin_option_prerequisite():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    assert "pg_auth_members" in sql
    assert "admin_option" in sql
    assert "RAISE EXCEPTION" in sql


def test_admin_option_check_precedes_alter_role_ftth_editor():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    check_pos = sql.find("admin_option")
    alter_pos = sql.find("ALTER ROLE ftth_editor NOLOGIN")
    assert check_pos != -1 and alter_pos != -1
    assert check_pos < alter_pos, (
        "Le garde-fou ADMIN OPTION doit s'executer AVANT la tentative "
        "d'ALTER ROLE ftth_editor, pour un message d'erreur clair"
    )


def test_no_password_touched():
    sql = _strip_sql_comments(_read(MIGRATION_PATH))
    assert not re.search(r"\bPASSWORD\b", sql, re.IGNORECASE)


def test_rollback_drops_wyre_ldap_users():
    sql = _strip_sql_comments(_read(ROLLBACK_PATH))
    assert "DROP ROLE IF EXISTS wyre_ldap_users" in sql
```

(Note: `test_no_password_touched` already exists from round 1 — if it's already present verbatim, skip re-adding it; otherwise the check above must still hold against the new content, since `admin_option`/`PASSWORD` don't collide.)

- [ ] **Step 4: Run the test harness**

Same `python3 -` heredoc pattern used throughout this chantier (pytest not installed). Expect all tests (9 from round 1 + up to 6 new = ~14-15, exact count depends on whether `test_no_password_touched` was already present) to PASS, `0 echec(s)`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add sql/migrations/375_ftth_editor_nologin.sql sql/migrations/375r_rollback_ftth_editor_nologin.sql tests/unit/test_migration_375_static.py
git commit -m "fix(sql): migration 375 - ajoute le role marqueur wyre_ldap_users + garde ADMIN OPTION (post-revue finale)"
```

---

### Task 12: Amend `pg_hba.conf` — target `+wyre_ldap_users` instead of `+ftth_editor`

**Files:**
- Modify: `docker/postgres/pg_hba.conf`
- Modify: `tests/unit/test_pg_hba_ldap_wyre.py`

- [ ] **Step 1**

In the LDAP line added in Task 3, change `+ftth_editor` to `+wyre_ldap_users` (only the group name in the USER column changes — host, method, all the `ldap*` options stay identical). Update the surrounding comment to reflect that this line now targets the marker role, not `ftth_editor` directly (one sentence explaining why, referencing the addendum).

- [ ] **Step 2**

Update `tests/unit/test_pg_hba_ldap_wyre.py`: every reference to `+ftth_editor` in the test's regexes/assertions becomes `+wyre_ldap_users` (the test names/docstrings can stay, just the matched string changes).

- [ ] **Step 3: Run tests, expect 4/4 PASS as before.**

- [ ] **Step 4: Commit**

```bash
git add docker/postgres/pg_hba.conf tests/unit/test_pg_hba_ldap_wyre.py
git commit -m "fix(postgres): pg_hba cible +wyre_ldap_users au lieu de +ftth_editor (post-revue finale)"
```

---

### Task 13: Amend `pg_role_sync.py` — marker-role semantics

**Files:**
- Modify: `farois/cron/pg_role_sync.py`
- Modify: `tests/unit/cron/test_pg_role_sync.py`

**Interfaces:**
- `GROUP_ROLE` renamed/repurposed: the role `pg_role_sync` manages membership of (create/disable target, `current` query scope) becomes `wyre_ldap_users`. A new constant `INHERIT_ROLE = "ftth_editor"` is the role individual accounts get `GRANT`ed for privilege inheritance, granted once at creation time, never touched again by disable/reactivate logic.

- [ ] **Step 1: Update constants**

```python
GROUP_ROLE = "wyre_ldap_users"
INHERIT_ROLE = "ftth_editor"
```

- [ ] **Step 2: Update `_apply_plan`**

The CREATE branch (currently 3 sub-branches: role absent / role exists+member / role exists+not-member from the earlier security fix) now grants BOTH roles on genuine creation, but only `GROUP_ROLE` matters for the membership-conflict check (since `INHERIT_ROLE` membership is a one-way privilege grant, not something pg_role_sync ever revokes or re-checks):

```python
def _apply_plan(cur, plan: SyncPlan) -> None:
    for username in plan.to_create:
        ident = _quote_ident(username)
        cur.execute(
            "SELECT pg_has_role(r.oid, %s, 'MEMBER') FROM pg_roles r WHERE r.rolname = %s",
            (GROUP_ROLE, username),
        )
        row = cur.fetchone()
        if row is None:
            cur.execute(f"CREATE ROLE {ident} LOGIN")
            cur.execute(f"GRANT {GROUP_ROLE} TO {ident}")
            cur.execute(f"GRANT {INHERIT_ROLE} TO {ident}")
            logger.info("pg_role_sync: role %s cree (membre de %s + %s)", username, GROUP_ROLE, INHERIT_ROLE)
        elif row[0]:
            cur.execute(f"ALTER ROLE {ident} LOGIN")
            logger.info("pg_role_sync: role %s reactive (LOGIN)", username)
        else:
            logger.warning(
                "pg_role_sync: role %s existe deja et n'est pas membre de "
                "%s -- IGNORE (conflit, intervention manuelle requise)",
                username, GROUP_ROLE,
            )
    for rolname in plan.to_disable:
        cur.execute(f"ALTER ROLE {_quote_ident(rolname)} NOLOGIN")
        logger.info("pg_role_sync: role %s desactive (NOLOGIN)", rolname)
```

(Note: `GROUP_ROLE` here is now `wyre_ldap_users`, so the `current` query built in `run()` — the one joining `pg_auth_members`/`pg_roles` on `g.rolname = %s` with `GROUP_ROLE` — automatically scopes to `wyre_ldap_users` membership without further changes, since it already parameterizes on the constant. Verify this is actually true by reading `run()`'s query construction — if it hardcoded `'ftth_editor'` as a literal anywhere instead of using the `GROUP_ROLE` constant, fix that too.)

- [ ] **Step 3: Update tests**

Update the existing mock-based tests (`test_apply_plan_creates_genuinely_new_role`, `test_apply_plan_reactivates_role_already_member`, `test_apply_plan_refuses_to_adopt_conflicting_nonmember_role`) so their expected SQL statement lists include the new `GRANT ftth_editor TO ...` statement in the creation-branch test (the create branch now issues 4 statements: `CREATE ROLE`, `GRANT wyre_ldap_users`, `GRANT ftth_editor`, in that order — update the `len(sql) == 3` assertion to `== 4` and add the new statement's exact-text assertion). The other two branches (reactivate, conflict) are unaffected by this change — only creation touches `INHERIT_ROLE` now.

- [ ] **Step 4: Run tests via the harness** (bare python3 fails on `ldap3` import — use the `docker exec -i farois-worker` fallback established earlier in this chantier). Expect all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add farois/cron/pg_role_sync.py tests/unit/cron/test_pg_role_sync.py
git commit -m "fix(cron): pg_role_sync cible wyre_ldap_users (marqueur) + GRANT ftth_editor separe pour l'heritage (post-revue finale)"
```

---

### Task 14: New migration — seed `pg_role_sync` into the cron registry

**Files:**
- Create: `sql/migrations/376_seed_pg_role_sync_cron_job.sql`
- Create: `tests/unit/test_migration_376_static.py`

**Interfaces:** consumes nothing new; mirrors `sql/migrations/289_seed_ldap_sync_cron_job.sql`'s exact pattern (read that file first for the precise conventions — header format, `\echo` style — and match it).

- [ ] **Step 1: Read the reference migration**

```bash
cat sql/migrations/289_seed_ldap_sync_cron_job.sql
```
Use this as the exact template for header format, transactionality, and `\echo` conventions.

- [ ] **Step 2: Write the new migration**

`sql/migrations/376_seed_pg_role_sync_cron_job.sql` — same header/structure conventions as 289, with:

```sql
INSERT INTO esb.farois_cron_jobs (name, description, command, cron_expression, enabled)
VALUES (
    'pg_role_sync',
    'Synchronisation des roles Postgres individuels wyre (wyre_ldap_users) depuis un groupe AD (chantier auth LDAP wyre)',
    'python3 -m farois.cron.pg_role_sync',
    '25 4 * * *',
    FALSE
)
ON CONFLICT (name) DO NOTHING;
```
`enabled = FALSE` (repo convention — an admin enables it manually after a validated dry-run, per every other seed job in this table). No rollback content needed beyond a `DELETE FROM esb.farois_cron_jobs WHERE name = 'pg_role_sync';` rollback file if 289's own rollback (if it has one) follows that pattern — check and mirror.

- [ ] **Step 3: Write a static test** mirroring whatever test pattern (if any) covers migration 289 — if none exists, write one matching this chantier's established static-test style: file exists, `ON CONFLICT (name) DO NOTHING` present (idempotent), `enabled` is `FALSE`, no password/secret in the file.

- [ ] **Step 4: Run tests, commit.**

```bash
git add sql/migrations/376_seed_pg_role_sync_cron_job.sql tests/unit/test_migration_376_static.py
git commit -m "feat(sql): migration 376 - seed pg_role_sync dans le registre cron (disabled par defaut)"
```

(Add the matching rollback file too if the 289 pattern has one — follow precedent exactly.)

---

## qgis_repo (worktree `~/projects/qgis_repo-wyre-ldap`, branch `feat/wyre-ldap-auth`)

### Task 15: In-memory credentials cache + reactive connect-on-native-success

**Files:**
- Modify: `plugin-repo/packages/constructel_bridge/bridge_plugin.py`

**Interfaces:** `_BridgeCredentials` gains a reference to the plugin instance so it can trigger the plugin's own connect flow when the native dialog succeeds for a wyre realm.

This is the highest-risk task in this round — same file, same credential-handling core that's already had multiple hotfix rounds. Read the CURRENT state of `_BridgeCredentials.__init__`, `request()`, and `_connect()` in full before editing (line numbers have shifted since the original plan was written — locate by content, not by remembered line numbers).

- [ ] **Step 1: Give `_BridgeCredentials` a back-reference to the plugin**

In `initGui()`, change:
```python
self._bridge_credentials = _BridgeCredentials(self._orig_credentials)
```
to:
```python
self._bridge_credentials = _BridgeCredentials(self._orig_credentials, self)
```

In `_BridgeCredentials.__init__`, add the parameter and store it:
```python
def __init__(self, fallback, plugin):
    self._fallback = fallback
    self._plugin = plugin
    super().__init__()
```

- [ ] **Step 2: Intercept successful native-dialog results for the wyre realm**

In `_BridgeCredentials.request()`, after the existing `_credentials_for` branch (which still handles `be` exactly as before — do not touch that part), extend the fallback branch so that when the native dialog succeeds for a wyre-realm request, the result is cached in-memory AND the plugin's connect flow is triggered:

```python
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
            self.put(realm, user, pwd)
            return True, user, pwd
        # Realm inconnu (ou wyre, qui n'a plus de reponse automatique) ->
        # deleguer au handler QGIS par defaut (dialogue natif).
        if self._fallback:
            ok, user, pwd = self._fallback.request(realm, username, password, message)
            if ok and DEFAULT_HOST in realm:
                # La personne vient de saisir SON mot de passe AD dans le
                # dialogue natif QGIS. On le met en cache RAM (jamais sur
                # disque, meurt avec le process) pour eviter une seconde
                # invite dans la meme session, et on declenche le flux de
                # connexion habituel du plugin (hooks de commit,
                # enregistrement ref.users) s'il n'est pas deja actif --
                # sans cela, une personne qui ouvre un projet et tape son
                # mot de passe au dialogue natif reste "deconnectee" cote
                # plugin (pas d'attribution d'edition).
                self.put(realm, user, pwd)
                if not self._plugin._connected:
                    self._plugin._connect(pwd, silent=True)
            return ok, user, pwd
        return False, username, password
```

- [ ] **Step 3: Verify no infinite recursion / re-entrancy risk**

`self._plugin._connect(pwd, silent=True)` internally calls `self._setup_qgis_pg_connection(password, use_authcfg=False)`, which writes QGIS connection settings but does NOT itself trigger a new credentials `request()` call (it's a settings write, not a connection attempt) — confirm this by reading `_setup_qgis_pg_connection`'s body once more; if you find any path where calling `_connect()` from inside `request()` could re-trigger `request()` itself (re-entrant call), STOP and report BLOCKED — do not guess a fix for re-entrancy, that's exactly the kind of subtle bug this file's hotfix history is made of.

- [ ] **Step 4: Verify `python3 -m py_compile` succeeds.**

- [ ] **Step 5: Self-review against the addendum's stated goal** — read `docs/superpowers/specs/2026-08-17-wyre-ldap-auth-addendum1.md` section 4, confirm your implementation matches: no persisted storage (RAM cache only, dies with process), the person only gets prompted once per session regardless of which path (native dialog vs plugin's own dialog) they hit first, and the plugin reaches its normal connected state (hooks, `ref.users`) via either path.

- [ ] **Step 6: Commit**

```bash
git add plugin-repo/packages/constructel_bridge/bridge_plugin.py
git commit -m "feat(constructel_bridge): cache credentials en memoire + connexion plugin reactive apres succes du dialogue natif (post-revue finale)"
```

Note: this cannot be tested outside a real QGIS session (consistent with the rest of this file) — Task 10's manual verification checklist will need a new step for this specific behavior (open a project with a wyre layer, type the password in the NATIVE dialog first, confirm the plugin shows "connected" state and does NOT re-prompt when the plugin's own "Status" action is checked). Note this explicitly in your report as a residual manual-verification item for Task 10.

---

### Task 16: `release.py` — strip `be`'s secret from the distributed zip

**Files:**
- Modify: `plugin-repo/packages/constructel_bridge/release.py`

**Interfaces:** consumes the worktree's on-disk `credentials.json` (unchanged, `be` block complete); produces a zip whose embedded `credentials.json` has `be.user`/`be.password` removed.

- [ ] **Step 1: Read `release.py` in full** to understand how it currently builds the zip (likely a straightforward `zipfile.write`/`rglob` over the plugin directory).

- [ ] **Step 2: Modify the zip-building logic** so that when it reaches `credentials.json`, instead of writing the file's raw bytes verbatim into the archive, it writes a MODIFIED version: parse the JSON, remove `be.user` and `be.password` keys if present (leave everything else — `wyre`'s already-stripped block, `be`'s remaining non-secret fields — untouched), re-serialize with the same formatting style as the source file (indent=4, matching the existing file's style — check by reading the current file), and write THAT content into the zip archive instead of the raw file bytes. The on-disk `credentials.json` in the worktree itself must remain UNCHANGED (still has `be`'s full block) — only the zip's embedded copy is modified.

- [ ] **Step 3: Re-run the release build**

```bash
cd plugin-repo/packages/constructel_bridge && python3 release.py 1.6.0
```
(Same version — this is a build-process correction, not a new feature release.)

- [ ] **Step 4: Verify**

```bash
cd plugin-repo/packages && python3 -c "
import json, zipfile
z = zipfile.ZipFile('constructel_bridge.zip')
raw = json.loads(z.read('constructel_bridge/credentials.json'))
assert 'user' not in raw['be'] and 'password' not in raw['be'], raw['be']
assert set(raw['be']) == {'host', 'port', 'dbname', 'sslmode'}, raw['be']
assert 'user' not in raw['wyre'] and 'password' not in raw['wyre'], raw['wyre']
print('ZIP OK - be secret stripped, wyre already stripped, both non-secret fields intact')"
```
Also verify the ON-DISK (not zipped) `credentials.json` in the worktree is unchanged (still has `be.user`/`be.password`) — `cat plugin-repo/packages/constructel_bridge/credentials.json`.

- [ ] **Step 5: Commit**

```bash
git add plugin-repo/packages/constructel_bridge/release.py plugin-repo/packages/constructel_bridge/metadata.txt plugin-repo/plugins.xml plugin-repo/packages/constructel_bridge.zip
git commit -m "fix(release): retirer le mot de passe be du credentials.json embarque dans le zip distribue (post-revue finale)"
```

Note in your report: after this change, a fresh install from this zip has `be` disabled (`BE_ENABLED` false, already-existing graceful degradation) until an admin manually completes `be.user`/`be.password` in the installed `credentials.json` — this is the intended new behavior (out-of-band secret distribution), not a bug. Document this clearly as a residual manual step for whoever runs Task 10 / distributes this release.

---

### Task 17: Audit and fix the 9 `.qml` style files' hardcoded `user='ftth_editor'`

**Files:**
- Investigate: `plugin-repo/packages/constructel_bridge/styles/*.qml` (9 files: zone_pop, ducts, subducts, zone_drop, demand_points, cables, zone_distribution, zone_mro, structures)
- Modify: whichever of the 9 actually need it, per your investigation

**Interfaces:** each affected file has (typically 2) occurrences of a `LayerSource` option value containing `... user='ftth_editor' sslmode=require ... table="ref"."v_form_lists"` — a static, pre-baked ValueRelation widget datasource for the same hidden reference layer that `_ensure_ref_layers()` creates live at runtime.

- [ ] **Step 1: Investigate whether this static value is actually consumed**

Read how QGIS resolves a ValueRelation widget's `LayerSource`/`LayerName` option when the style file is applied to a layer (check `bridge_sketcher.py` and any style-application code in `bridge_plugin.py` for how `.qml` styles get loaded — search for `loadNamedStyle` or similar). Determine: when a `.qml` style with this option is applied AFTER `_ensure_ref_layers()` has already added the live `ref.v_form_lists` layer to the project, does QGIS's ValueRelation widget resolve by LAYER ID (in which case the embedded LayerSource string might only be a fallback/never actually reconnected-to) or does it re-establish its OWN connection using the embedded LayerSource verbatim? This determines whether the string is genuinely load-bearing or effectively dead weight.

- [ ] **Step 2: Fix per your finding**

- If the embedded `LayerSource` is genuinely used to establish a live connection (not just a label): remove `user='ftth_editor'` (and nothing else — do not touch `sslmode`, `table=`, `key=`, etc.) from the `LayerSource` value in every occurrence across all 9 files, so QGIS falls back to resolving the connection via its normal provider/connection-settings resolution instead of a hardcoded (now-dead) username. Use a careful, exact string replacement — do NOT use a broad regex that could touch unrelated content in these XML files; grep each occurrence first (`grep -n "user='ftth_editor'" styles/*.qml`) and edit each one precisely.
- If your investigation shows the embedded value is NOT actually used at runtime (superseded by the live layer QGIS already has open by ID/name before the style's ValueRelation config is evaluated): document this finding clearly in your report with the code evidence, and leave the files UNCHANGED — do not make a speculative change to something you've determined is inert. Either way, defer to what the code actually shows, not to assumption.

- [ ] **Step 3: If files were modified, verify each is still well-formed XML**

```bash
for f in plugin-repo/packages/constructel_bridge/styles/*.qml; do python3 -c "import xml.etree.ElementTree as ET; ET.parse('$f')" && echo "OK: $f"; done
```

- [ ] **Step 4: Commit** (or, if no files needed changes, write your investigation findings into the report and skip the commit — report DONE either way, this task's job is to resolve the question, not necessarily to produce a diff)

```bash
git add plugin-repo/packages/constructel_bridge/styles/
git commit -m "fix(constructel_bridge): retire user='ftth_editor' des LayerSource figees dans les styles .qml (post-revue finale)"
```

---

## Notes for whoever runs the eventual Task 10

This addendum changes Task 10's runbook (from the base plan) in these ways — do not execute the base plan's Task 10 text verbatim, cross-reference against this list first:
1. **New prerequisite before applying migration 375**: `GRANT ftth_editor TO ftth_admin WITH ADMIN OPTION, INHERIT FALSE;`, run once under `postgres`.
2. Migration 375 now also creates `wyre_ldap_users` — Task 10's dry-run/apply steps should mention both role names in their expected output, not just `ftth_editor`.
3. `pg_hba.conf`'s applied line now reads `+wyre_ldap_users`, not `+ftth_editor` — update any verification command that greps for the old string.
4. A new migration 376 (cron seed, `enabled=FALSE`) ships alongside 375 — Task 10's dry-run should expect 3 pending migrations if run together (or however many are actually pending at execution time), not 1.
5. After the plugin zip is distributed, `be` needs its `user`/`password` completed manually in each installed `credentials.json` — decide and document the out-of-band distribution channel before publishing.
6. Add a manual verification step for Task 15's reactive-connect behavior (see Task 15's note above).
7. Rollout sequencing stays as originally planned (hard cutover, migration 375 before wide plugin adoption) — Simon's explicit choice, no plan change needed here, just confirming it wasn't silently altered by this addendum.
