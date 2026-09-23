# Constructel Bridge — Bridge 1b (câblage mTLS) Implementation Plan

> **For agentic workers:** execute task-by-task, checkbox (`- [ ]`) tracking.
> Adapted process (no superpowers skill in this runtime): the controller
> implements inline from this fully-specified plan, one independent reviewer
> per code task, and the controller re-runs pytest personally before every
> review (method lesson 22-23/09: never trust subagent-reported test results).

**Goal:** Wire Bridge 1's pure mTLS logic into the live plugin so `wyre`
(and `be`) connect with a nominative client certificate
(`sslmode=verify-full`): cert via ONE shared QGIS Auth Manager "PKI-Paths"
config, shared password via `.pgpass` — safe by default: mTLS activates
automatically when a valid cert is configured, otherwise behavior stays
byte-identical to 1.5.5. A flag (`constructel_bridge/mtls_enabled`,
default ON) acts as a kill-switch (OFF forces legacy mode). Activation on
any real post requires the gates below.

**Architecture:** When the flag is on AND a valid cert is configured,
`_connect` passes `sslcert/sslkey/sslrootcert` + `sslmode=verify-full` to
psycopg2; `_setup_qgis_pg_connection` writes `sslmode=5` + the shared
PKI-Paths `authcfg` (never a Basic authcfg on a cert connection — QGIS bug
#58179); `_fix_layer_credentials` re-attaches our own PKI authcfg on
project load instead of password-only URIs. When the flag is on but no
(valid) cert is configured, behavior is byte-identical to 1.5.5 (legacy
password mode); setting the flag OFF forces legacy mode even with certs
present (kill-switch). Passwords still flow through the existing
`_BridgeCredentials` prompt handler + precache as fallback. Cert paths
come from EXPLICIT settings keys only — no guessed default directories
until ops decide the delivery convention (Farois track).

**Tech Stack:** Python 3.10+, `pytest` + Bridge-0 stub (extended, see Task 4),
stdlib only for new pure code (`os`, `pathlib`).

**Spec refs:** `docs/superpowers/specs/2026-09-22-constructel-bridge-mtls-design.md`
(§ "État réel du terrain" + "Suite du 2026-09-23"), Bridge 1 plan
Self-Review (this plan implements its "Explicitly deferred: wiring" item),
`docs/superpowers/specs/2026-09-23-bridge1-spike-results.md` (proven
`pg_hba` line + libpq parameter set this wiring targets).

## Global Constraints

- **GATE 1 — no ACTIVATION (setting cert paths on any real post) until the
  Farois track decides the cert-delivery convention.** Merge is allowed
  without it: the code is convention-agnostic (explicit paths only) and
  provably inert where no cert is configured.
- **GATE 2 — no ACTIVATION until a human runs the manual recette (Bridge 1
  steps + Task 5 wiring steps) on real QGIS and reports green.** Merge
  ideally follows the recette, since only it proves the mTLS branch works
  in real QGIS — but an unconfigured post cannot diverge from 1.5.5 either
  way. Per the spec: activate nothing blind.
- Flag default ON (automatic): with no (valid) cert configured, every code
  path behaves byte-for-byte as 1.5.5 (sslmode `require`/`3`, Basic authcfg,
  current `_fix_layer_credentials`). No behavior change for existing users
  until certs are deliberately configured. Flag OFF forces legacy mode even
  with certs present (kill-switch).
- `wyre` stays the configured operator: connection names (`wyre`, `be`),
  schema names, credential-block keys, `wyre_*` expression function names
  are NEVER renamed (Simon decision 23/09). Only user-visible display text
  was already renamed (1.5.5) — no further renames in this plan.
- Bug #58179 binding: on a cert-bearing connection the password NEVER goes
  through a Basic authcfg (not in `_setup_qgis_pg_connection`, not in
  `_fix_layer_credentials`, not in `_strip_authcfg_from_dom` output).
- Never fall back silently once ENGAGED: with a cert configured, every mTLS
  error path (invalid/expired cert, pgpass unwritable) surfaces a distinct
  translated diagnostic and aborts that connection setup — no quiet
  password-only downgrade. The only supported non-cert modes are: flag OFF,
  or no cert configured (both = legacy 1.5.5 behavior). Additionally,
  `_connect` maps the exact server-side rejection
  ("connection requires a valid client certificate") to a translated
  "certificat requis mais non configuré" diagnostic, so post-enforcement
  failures on uncertified posts are explicit, not raw libpq dumps.
- `.pgpass` hygiene: our lines keyed by `host:port:dbname:user`, user lines
  preserved byte-for-byte, file `0o600` on POSIX (libpq refuses looser),
  best-effort on Windows (`%APPDATA%\postgresql\pgpass.conf`, no perm check
  by libpq there). Tests never touch the real file (`tmp_path` only).
- `qgisMinimumVersion=3.28` stays the floor.
- Work happens on branch `feat/bridge1b-mtls-wiring`, in the isolated
  worktree `.worktrees/feat-bridge1b-mtls-wiring/` — never commit to `main`.

---

## File Structure

```
plugin-repo/packages/constructel_bridge/
├── bridge_mtls.py          # EXTEND — upsert_pgpass_entry(existing, line),
│                           #   pgpass_file_path(), MTLS_SETTINGS_KEYS
├── bridge_plugin.py        # WIRE — PKI authcfg lifecycle, _mtls_active(),
│                           #   _connect + _setup_qgis_pg_connection +
│                           #   _fix_layer_credentials mTLS branches
└── i18n/translations.py    # EXTEND — mtls.* keys (FR/EN/PT)

plugin-repo/packages/constructel_bridge_tests/
├── test_bridge_mtls.py     # EXTEND — pgpass upsert/path tests
└── test_bridge1b_wiring.py # NEW — stub-level wiring behavior tests

docs/guides/RECETTE_BRIDGE1_MTLS_MANUELLE.md  # EXTEND — wiring steps
```

**New settings keys** (all under `constructel_bridge/`):
`mtls_enabled` (bool, default `True` = automatic; `False` forces legacy),
`mtls_cert_path`, `mtls_key_path`, `mtls_ca_path` (strings, default `""`),
`mtls_authcfg_id` (PKI-Paths config id, managed by the plugin, mirrors
`_AUTH_CFG_ID_KEYS` pattern).

---

### Task 1: pgpass content manager (pure logic + tests)

**Files:**
- Modify: `plugin-repo/packages/constructel_bridge/bridge_mtls.py`
- Modify: `plugin-repo/packages/constructel_bridge_tests/test_bridge_mtls.py`

**Interfaces:**
- Produces: `upsert_pgpass_entry(existing_text: str, new_line: str) -> str`
  (replace the line with the same `host:port:dbname:user` key, else append
  with exactly one trailing newline; never touches other lines),
  `pgpass_file_path() -> Path` (`~/.pgpass` POSIX,
  `%APPDATA%\postgresql\pgpass.conf` on Windows via `APPDATA` env).

- [ ] **Step 1: Write the failing tests** (keyed replace, append, empty-file,
  comment/blank-line preservation, Windows path via monkeypatched
  `os.name`/`APPDATA`).
- [ ] **Step 2: Run tests to verify they fail** (`ImportError`, real pytest
  command, controller-run).
- [ ] **Step 3: Implement** (key = first 4 colon-separated fields, honoring
  backslash escapes when comparing; file IO + `0o600` chmod stay in
  `bridge_plugin.py`, NOT here).
- [ ] **Step 4: Run tests to verify they pass** (controller-run, full suite).
- [ ] **Step 5: Commit.**

### Task 2: PKI-Paths authcfg lifecycle + activation check

**Files:**
- Modify: `plugin-repo/packages/constructel_bridge/bridge_plugin.py`
- Test: new cases in `plugin-repo/packages/constructel_bridge_tests/test_bridge1b_wiring.py` (stub-level, see Task 4 for the stub extensions this needs — implement the minimal stub surface in this task if Task 4 has not landed).

**Interfaces:**
- Produces: `_store_pki_authcfg() -> str` (ONE shared "PKI-Paths" config
  named e.g. `constructel_bridge_mtls`, `certpath`/`keypath` only, id saved
  to `constructel_bridge/mtls_authcfg_id`; mirrors
  `_store_password_encrypted` update-or-create flow),
  `_remove_pki_authcfg()`, `_mtls_active() -> tuple[bool, str | None]`
  (`(True, None)` iff flag on + all three paths set + files validate via
  `validate_client_certificate`; else `(False, reason)` with the
  `CertValidationResult.reason`, `"disabled"`, or `"not_configured"`).
  Callers treat `(False, "disabled"|"not_configured")` as "legacy mode"
  (not a failure); a configured-but-invalid cert aborts loudly with
  diagnostics (Task 3) — never legacy.

- [ ] **Step 1: Write the failing stub tests** (store creates config with
  exact `build_pki_paths_authcfg_config` shape; re-store updates, no dup;
  `_mtls_active` truth table: flag off, paths missing, cert invalid with
  each named reason forwarded).
- [ ] **Step 2: Run tests to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests to verify they pass** (controller-run, full suite).
- [ ] **Step 5: Commit.**

### Task 3: wire `_connect`, `_setup_qgis_pg_connection`, `_fix_layer_credentials`

**Files:**
- Modify: `plugin-repo/packages/constructel_bridge/bridge_plugin.py`
- Modify: `plugin-repo/packages/constructel_bridge_tests/test_bridge1b_wiring.py`

**Interfaces:** behavior change only (active iff `_mtls_active()`):
- `_connect`: when active, `psycopg2.connect(..., sslmode="verify-full",
  sslcert=<cert>, sslkey=<key>, sslrootcert=<ca>)`; on failure, translated
  diagnostic including the validation reason (no raw libpq dump as the
  only message), plus mapping of the exact server-side `connection requires
  a valid client certificate` rejection to the
  `mtls.cert_required_by_server` diagnostic (covers uncertified posts after
  server-side enforcement). Inactive: byte-identical call as today.
- `_setup_qgis_pg_connection`: when active, `sslmode="5"`, `authcfg` = the
  shared PKI id, `username` saved, `savePassword=False`, NO `password`
  value written, and the legacy per-conn Basic authcfg (if any) REMOVED
  via `_remove_stored_password(conn)` (migration, idempotent: re-running
  converges). Inactive (flag off, or flag on with no cert configured):
  byte-identical behavior as today — existing Basic authcfgs untouched.
  Both `wyre` and `be` supported (same cert, per-conn pgpass line).
  Configured-but-invalid cert: abort loudly (diagnostic), never legacy.
- `_fix_layer_credentials`: when active and the layer targets our host,
  set `authcfg` = shared PKI id + username (no plaintext password in the
  URI); when active-but-engaged with an unavailable cert, SKIP the layer
  with a counted warning (same `still_bad` pattern) — never password-only
  downgrade. Inactive: current behavior untouched.
  `_strip_authcfg_from_dom` unchanged (still strips any authcfg on save —
  portability design holds; PKI ids never persist in shared projects).

- [ ] **Step 1: Write the failing stub tests** (settings capture: sslmode 5
  + PKI authcfg id + no password value; psycopg2 stub via `sys.modules`
  asserting SSL kwargs; `_fix` rewrite matrix incl. no-downgrade case;
  inactive-mode byte-identity cases).
- [ ] **Step 2: Run tests to verify they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run tests to verify they pass** (controller-run, full suite).
- [ ] **Step 5: Commit.**

### Task 4: translated diagnostics + stub test surface

**Files:**
- Modify: `plugin-repo/packages/constructel_bridge/i18n/translations.py`
- Modify: stub package + `plugin-repo/packages/constructel_bridge_tests/test_bridge1b_wiring.py`

**Interfaces:** `mtls.*` keys (FR/EN/PT) for the six
`CertValidationResult` reasons + `not_configured`,
`cert_required_by_server`, `pgpass_unwritable`, `activation_failed`; stub
extensions: `QgsAuthMethodConfig` capturing `setConfig` pairs + `id()`,
`QgsSettings` fake (dict-backed), `QgsApplication.authManager()`
returning a recording stub, `QgsDataSourceUri` authcfg/username accessors
as needed by Task 2-3 tests. (If Task 2 already added minimal stub
surface, extend — don't fork.)

- [ ] **Step 1: Write keys + tests** (every reason renders non-empty in all
  three languages; stub round-trips).
- [ ] **Step 2-4: red/green, controller-run.**
- [ ] **Step 5: Commit.**

### Task 5: recette wiring steps (docs, human gate)

**Files:**
- Modify: `docs/guides/RECETTE_BRIDGE1_MTLS_MANUELLE.md`

- [ ] **Step 1: Append wiring steps** (set cert paths on a real QGIS post,
  connect wyre, assert `sslmode=verify-full` + PKI authcfg in
  `PostgreSQL/connections/wyre`, load a layer, revoke-password check:
  with pgpass entry removed the layer must fail with the translated
  diagnostic, not silently; kill-switch check: flag OFF restores legacy).
  Mark the whole recette (Bridge 1 + 1b steps) as GATE 2, explicitly
  pending a dated human run.
- [ ] **Step 2: Commit.**

---

## Self-Review

**Coverage** (against Bridge 1 plan's "Explicitly deferred" list):
- wiring `_connect`/`_setup_qgis_pg_connection` → Tasks 2-3.
- idempotent rewrite of connection settings → Task 3 (setup always-writes
  + Basic-authcfg removal on migration; re-runnable).
- translated diagnostic messages → Task 4.
- cert-selection UX → SINGLE-cert assumption + explicit error (no picker
  UI in this plan — decided, see log below; revisit if ops deliver
  multi-cert directories).

**Placeholder scan:** no `TODO`/`TBD` in executable code; no guessed default
cert directories anywhere (grepable: `mtls_cert_path` default must be `""`).

**Type consistency:** `_mtls_active()` returns `(bool, str | None)` with
reasons drawn from Bridge 1's named set + `"disabled"`/`"not_configured"`;
`upsert_pgpass_entry` is total on strings (never raises on malformed input
lines — they are preserved, not parsed).

## Decision log (decided by Simon 23/09, via structured input)

1. Flag default ON = automatic mTLS when a valid cert is configured; OFF is
   a kill-switch forcing legacy mode. (Overrode the plan's initial OFF
   recommendation.)
2. Cert paths from explicit settings only — no conventional-directory
   probing until ops decide. (With plan recommendation.)
3. Single-cert assumption + explicit error (no picker UI in this plan).
   (With plan recommendation.)

## Execution Handoff

Inline execution (controller implements, reviewer per code task, pytest
re-run personally by controller). GATES 1+2 block ACTIVATION regardless of
review state; merge needs Simon's explicit order as usual (and ideally
follows a green recette).
