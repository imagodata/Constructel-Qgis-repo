# Constructel Bridge — PR Bridge 1 (mTLS / Auth Manager) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the plugin the ability to open a PostgreSQL connection that presents a nominative client certificate (`sslmode=verify-full`) alongside the existing shared `ftth_editor` password, in a way QGIS's Auth Manager can actually sustain — and prove the pattern works against a real (throwaway, local) mTLS-enabled Postgres before writing a line of plugin code that depends on it.

**Architecture:** A new `bridge_mtls.py` module (pure functions, mirroring `bridge_identity.py`'s testability pattern from PR Bridge 0) handles certificate validation and the two pieces of connection configuration this PR introduces: a QGIS Auth Manager "PKI-Paths" config (certificate + key only, Auth-Manager-encrypted) and a `.pgpass` line (password only, OS-permission-protected). `bridge_plugin.py`'s connection setup is then wired to use both together instead of the current single "Basic" authcfg. This split exists because of a confirmed, currently-open QGIS bug (see Global Constraints) — not by design preference.

**Tech Stack:** Python 3.10+, `pytest`, stdlib only for `bridge_mtls.py` (`subprocess` to shell out to `openssl` for certificate inspection — no new third-party dependency added to a plugin that has none today). Spike task uses Docker + OpenSSL directly on the dev/ops host, not inside the plugin.

**Spec:** `docs/superpowers/specs/2026-09-22-constructel-bridge-mtls-design.md` — read its "État réel du terrain" section: the backend PKI (`pki_manager.sh`, `pg_hba_mtls.conf`) has never been activated in Farois, and the mTLS program as a whole is paused pending coordination with Marco on the SEC-04 backlog. **This plan proceeds anyway, on Simon's explicit instruction (2026-09-23)**, scoped so that everything it builds is genuinely usable once that coordination happens — nothing here reactivates or depends on Farois production PKI.

## Global Constraints

- `sslmode=verify-full` only — never `require`. Never disable server certificate/hostname validation.
- The client private key must be Auth-Manager-protected (QGIS "PKI-Paths" method) — never written to QSettings, a project file, a URI string, or a log line, in any form.
- **Confirmed bug, binding on the design:** QGIS issue [#58179](https://github.com/qgis/QGIS/issues/58179) (open, unresolved as of this writing) — when a connection's authcfg is a "Basic" (username/password) config, its certificate configuration is dropped when the config expands into a plain user/password pair; client certs are not transmitted to libpq. **Consequence: the shared `ftth_editor` password must NOT go through a "Basic" authcfg on any connection that also needs a client certificate.** Confirmed working alternative, from QGIS's own test suite (`tests/src/python/test_authmanager_pki_postgres.py`): `QgsDataSourceUri.setConnection(host, port, dbname, user, password, SslMode.SslVerifyFull, authcfg)` — pass `user`/`password` as plain connection parameters and reserve the `authcfg` slot for a "PKI-Paths" config carrying only `certpath`/`keypath`. This plan uses `.pgpass` (not a plain-password URI field, and not `savePassword=True`) to keep the password itself out of QSettings — see Task 2.
- No mini-PKI in the plugin. Certificate issuance/revocation/renewal is Farois/Constructel runbook territory (per spec) — this plan consumes certificates, it does not provision them for real users. The one exception is the throwaway spike CA in Task 1, explicitly never used outside that task's isolated environment.
- Never fall back to the old unattested connection silently. Every error path in `bridge_mtls.py` returns a distinct, named failure — no bare `except: pass`.
- `qgisMinimumVersion=3.28` (`metadata.txt:3`) stays the floor; nothing added here assumes a newer QGIS API.
- **Untestable-in-this-environment constraint:** this work happens over SSH on a headless Ubuntu server with no QGIS GUI. Task 1 (the spike) is fully verifiable here because it stays at the libpq/psycopg2 level. Everything that touches real `QgsAuthManager`/`QgsDataSourceUri` behavior can only be unit-tested against the Bridge-0-style stub (behavior asserted, not QGIS-verified) — genuine QGIS-level verification requires a manual recette run by a human with a real QGIS install (Task 5 produces that recette; it is not optional, it is this plan's substitute for integration tests per the spec's own fallback clause).
- Work happens on branch `feat/bridge1-mtls-auth-manager`, in the isolated worktree `.worktrees/feat-bridge1-mtls-auth-manager/` — never commit directly to `main`.

---

## File Structure

```
plugin-repo/packages/constructel_bridge/
├── bridge_mtls.py                          # NEW — pure logic: cert validation, PKI-Paths
│                                            #   authcfg config dict, .pgpass line builder
└── (bridge_plugin.py wiring — Task 5, deferred to end of this plan; not touched by Tasks 1-4)

plugin-repo/packages/constructel_bridge_tests/
├── test_bridge_mtls.py                     # NEW — unit tests for bridge_mtls.py
└── spike/
    ├── generate_spike_pki.sh               # NEW — throwaway CA + server + client cert
    ├── spike_compose.yml                   # NEW — isolated test Postgres, mTLS pg_hba
    ├── run_spike.sh                        # NEW — end-to-end proof script
    └── README.md                           # NEW — what this proves, how to re-run it, how to destroy it

docs/superpowers/specs/
└── 2026-09-23-bridge1-spike-results.md     # NEW — real spike output (Task 1's deliverable),
                                             #   the exact pg_hba.conf line and connection
                                             #   parameters this proved work
```

**Explicit, named gap this plan does NOT resolve (per spec's own "n'invente pas un endpoint" instruction):** nothing in the Farois or qgis_repo repos defines where a real (non-spike) client certificate is supposed to land on a user's machine after Constructel/Farois issues it — `pki_manager.sh`'s `create-client <name>` was never run, so there's no example artifact to inspect. `bridge_mtls.py`'s cert-discovery function therefore takes a **directory path as a parameter**, not a hardcoded convention. Task 4 documents this as a required decision for the Farois/PKI side before Bridge 1 can ship to real users — it is listed explicitly, not invented.

---

### Task 1: Bridge 1-0 spike — prove the .pgpass + PKI-Paths pattern against a real mTLS Postgres

**Files:**
- Create: `plugin-repo/packages/constructel_bridge_tests/spike/generate_spike_pki.sh`
- Create: `plugin-repo/packages/constructel_bridge_tests/spike/spike_compose.yml`
- Create: `plugin-repo/packages/constructel_bridge_tests/spike/run_spike.sh`
- Create: `plugin-repo/packages/constructel_bridge_tests/spike/README.md`
- Create: `docs/superpowers/specs/2026-09-23-bridge1-spike-results.md`

**Interfaces:**
- Produces: a written, dated proof (with real terminal output) of the exact `pg_hba.conf` line and libpq connection parameters that make mTLS + shared-password auth work together — this is what Task 2/5's code targets. No code interface (this task produces evidence, not a library).

- [ ] **Step 1: Write the CA + certificate generator**

Create `plugin-repo/packages/constructel_bridge_tests/spike/generate_spike_pki.sh`:

```bash
#!/usr/bin/env bash
# Throwaway CA + server + client certificate, for Bridge 1-0 spike ONLY.
# Never reused outside this spike; destroy with cleanup.sh when done.
set -euo pipefail
cd "$(dirname "$0")"
OUT=pki
rm -rf "$OUT"
mkdir -p "$OUT"
cd "$OUT"

# CA (1 day validity — this is a throwaway, not production material)
openssl req -new -x509 -days 1 -nodes \
  -subj "/CN=bridge1-spike-ca" \
  -keyout ca.key -out ca.crt

# Server cert (CN must match the hostname the client connects to)
openssl req -new -nodes -subj "/CN=localhost" -keyout server.key -out server.csr
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -days 1 -out server.crt
chmod 600 server.key

# Client cert (CN = the throwaway "person" this spike simulates)
openssl req -new -nodes -subj "/CN=spike_test_user" -keyout client.key -out client.csr
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -days 1 -out client.crt
chmod 600 client.key

echo "Spike PKI generated in $(pwd)"
```

- [ ] **Step 2: Write the isolated test Postgres compose file**

Create `plugin-repo/packages/constructel_bridge_tests/spike/spike_compose.yml`:

```yaml
# Isolated, throwaway Postgres for the Bridge 1-0 spike. Port 5433 (not
# 5432 — never touches the real ftth-postgres). No named volume: destroying
# the container destroys all data, by design.
services:
  spike-postgres:
    image: postgres:17
    environment:
      POSTGRES_PASSWORD: spike_test_password
      POSTGRES_USER: spike_test_user
      POSTGRES_DB: spike_db
    ports:
      - "127.0.0.1:5433:5432"
    volumes:
      - ./pki/server.crt:/etc/postgresql-certs/server.crt:ro
      - ./pki/server.key:/etc/postgresql-certs/server.key:ro
      - ./pki/ca.crt:/etc/postgresql-certs/ca.crt:ro
      - ./spike_pg_hba.conf:/etc/postgresql-certs/pg_hba.conf:ro
    command: >
      postgres
      -c ssl=on
      -c ssl_cert_file=/etc/postgresql-certs/server.crt
      -c ssl_key_file=/etc/postgresql-certs/server.key
      -c ssl_ca_file=/etc/postgresql-certs/ca.crt
      -c hba_file=/etc/postgresql-certs/pg_hba.conf
```

Create `plugin-repo/packages/constructel_bridge_tests/spike/spike_pg_hba.conf`:

```
# Spike pg_hba.conf — requires BOTH a CA-signed client certificate AND the
# scram-sha-256 password. This is the exact pattern Bridge 1 depends on:
# the certificate's CN is NOT used as the Postgres role (the role stays
# the shared spike_test_user, mirroring ftth_editor in production) — it's
# a TLS-layer gate on top of normal password auth, not a replacement for it.
hostssl all all 0.0.0.0/0 scram-sha-256 clientcert=verify-full
hostnossl all all 0.0.0.0/0 reject
```

- [ ] **Step 3: Write the proof script**

Create `plugin-repo/packages/constructel_bridge_tests/spike/run_spike.sh`:

```bash
#!/usr/bin/env bash
# Proves: (a) cert+password together succeeds, (b) password alone (no
# client cert) fails, (c) wrong/no password with a valid cert also fails
# (clientcert=verify-full is a TLS gate, not itself an auth method here).
set -euo pipefail
cd "$(dirname "$0")"

./generate_spike_pki.sh
docker compose -f spike_compose.yml up -d
trap 'docker compose -f spike_compose.yml down -v' EXIT

echo "Waiting for spike-postgres to be ready..."
for i in $(seq 1 30); do
  docker compose -f spike_compose.yml exec -T spike-postgres pg_isready -U spike_test_user && break
  sleep 1
done

echo
echo "=== (a) cert + password: EXPECT SUCCESS ==="
PGSSLCERT=pki/client.crt PGSSLKEY=pki/client.key PGSSLROOTCERT=pki/ca.crt \
  PGPASSWORD=spike_test_password \
  psql "host=127.0.0.1 port=5433 dbname=spike_db user=spike_test_user sslmode=verify-full" \
  -c "SELECT 'spike connection OK, cert CN=' || ssl_client_dn();" \
  && echo "RESULT: SUCCESS (as expected)" || echo "RESULT: FAILED (unexpected — investigate)"

echo
echo "=== (b) password alone, NO client cert: EXPECT FAILURE ==="
PGPASSWORD=spike_test_password \
  psql "host=127.0.0.1 port=5433 dbname=spike_db user=spike_test_user sslmode=require" \
  -c "SELECT 1;" \
  && echo "RESULT: SUCCESS (UNEXPECTED — cert requirement not enforced, investigate)" \
  || echo "RESULT: FAILED (as expected — no cert)"

echo
echo "=== (c) valid cert, WRONG password: EXPECT FAILURE ==="
PGSSLCERT=pki/client.crt PGSSLKEY=pki/client.key PGSSLROOTCERT=pki/ca.crt \
  PGPASSWORD=wrong_password \
  psql "host=127.0.0.1 port=5433 dbname=spike_db user=spike_test_user sslmode=verify-full" \
  -c "SELECT 1;" \
  && echo "RESULT: SUCCESS (UNEXPECTED — password not actually checked, investigate)" \
  || echo "RESULT: FAILED (as expected — cert alone does not bypass password)"
```

- [ ] **Step 4: Run the spike, capture real output**

Run: `bash plugin-repo/packages/constructel_bridge_tests/spike/run_spike.sh`

Expected: case (a) prints a row with `spike connection OK, cert CN=CN=spike_test_user` and "RESULT: SUCCESS"; cases (b) and (c) both print "RESULT: FAILED (as expected...)". Capture the full real terminal output — this is the evidence, not a description of expected behavior.

- [ ] **Step 5: Write up the results**

Create `docs/superpowers/specs/2026-09-23-bridge1-spike-results.md` with: the date, the exact `pg_hba.conf` line proven to work (`hostssl all all 0.0.0.0/0 scram-sha-256 clientcert=verify-full`), the exact connection parameter set proven to work (`sslmode=verify-full` + `PGSSLCERT`/`PGSSLKEY`/`PGSSLROOTCERT` + a separate password channel), the full real output from Step 4, and an explicit statement that the CA/certs/container were destroyed after the run (confirm via `docker compose -f spike_compose.yml ps` returning empty and `rm -rf plugin-repo/packages/constructel_bridge_tests/spike/pki`).

- [ ] **Step 6: Clean up and verify nothing throwaway survives**

Run: `docker compose -f plugin-repo/packages/constructel_bridge_tests/spike/spike_compose.yml down -v && rm -rf plugin-repo/packages/constructel_bridge_tests/spike/pki plugin-repo/packages/constructel_bridge_tests/spike/*.srl`
Expected: no `spike-postgres` container in `docker ps -a`, no `pki/` directory left on disk. Do NOT commit the `pki/` directory or any `.crt`/`.key` file, even throwaway ones — commit only the scripts, the compose file, `spike_pg_hba.conf`, and the results write-up.

- [ ] **Step 7: Commit**

```bash
git add plugin-repo/packages/constructel_bridge_tests/spike/ docs/superpowers/specs/2026-09-23-bridge1-spike-results.md
git commit -m "spike(bridge1): prove .pgpass + PKI-Paths pattern against throwaway mTLS Postgres"
```

---

### Task 2: `bridge_mtls.py` — certificate validation + connection-config builders

**Files:**
- Create: `plugin-repo/packages/constructel_bridge/bridge_mtls.py`
- Test: `plugin-repo/packages/constructel_bridge_tests/test_bridge_mtls.py`

**Interfaces:**
- Consumes: `subprocess` (to shell out to `openssl`), `pathlib`, `datetime` — stdlib only.
- Produces (used by Task 5): `validate_client_certificate(cert_path: str, key_path: str, ca_path: str) -> CertValidationResult` (a small dataclass: `ok: bool`, `reason: str | None` — one of `"cert_missing"`, `"key_missing"`, `"chain_invalid"`, `"expired"`, `"not_yet_valid"`, `"missing_client_auth_eku"`, or `None` when `ok=True`), `build_pki_paths_authcfg_config(name: str, cert_path: str, key_path: str) -> dict` (the `QgsAuthMethodConfig`-shaped dict: `{"method": "PKI-Paths", "name": ..., "config": {"certpath": ..., "keypath": ...}}`), `build_pgpass_line(host: str, port: int, dbname: str, username: str, password: str) -> str` (the exact `.pgpass` line format: `hostname:port:database:username:password`, with `:` and `\` in any field escaped per the [libpq `.pgpass` format](https://www.postgresql.org/docs/current/libpq-pgpass.html)).

- [ ] **Step 1: Write the failing tests**

Create `plugin-repo/packages/constructel_bridge_tests/test_bridge_mtls.py`:

```python
"""Unit tests for bridge_mtls.py (PR Bridge 1, 2026-09-23).

No QGIS import required. Certificate validation tests use real, small,
throwaway certs generated into a pytest tmp_path fixture — not mocks —
since openssl's own exit codes and stderr text are exactly what the
function under test parses.
"""
import subprocess
from pathlib import Path

import pytest

from constructel_bridge.bridge_mtls import (
    build_pgpass_line,
    build_pki_paths_authcfg_config,
    validate_client_certificate,
)


def _run(*args):
    subprocess.run(args, check=True, capture_output=True)


@pytest.fixture
def valid_cert_bundle(tmp_path):
    """A real CA + client cert with clientAuth EKU, valid for 1 day."""
    ca_key = tmp_path / "ca.key"
    ca_crt = tmp_path / "ca.crt"
    client_key = tmp_path / "client.key"
    client_csr = tmp_path / "client.csr"
    client_crt = tmp_path / "client.crt"
    ext_file = tmp_path / "client_ext.cnf"
    ext_file.write_text("extendedKeyUsage = clientAuth\n")

    _run("openssl", "req", "-new", "-x509", "-days", "1", "-nodes",
         "-subj", "/CN=test-ca", "-keyout", str(ca_key), "-out", str(ca_crt))
    _run("openssl", "req", "-new", "-nodes", "-subj", "/CN=test_person",
         "-keyout", str(client_key), "-out", str(client_csr))
    _run("openssl", "x509", "-req", "-in", str(client_csr), "-CA", str(ca_crt),
         "-CAkey", str(ca_key), "-CAcreateserial", "-days", "1",
         "-extfile", str(ext_file), "-out", str(client_crt))
    return {"cert": str(client_crt), "key": str(client_key), "ca": str(ca_crt)}


def test_validate_client_certificate_accepts_valid_cert(valid_cert_bundle):
    result = validate_client_certificate(
        valid_cert_bundle["cert"], valid_cert_bundle["key"], valid_cert_bundle["ca"]
    )
    assert result.ok is True
    assert result.reason is None


def test_validate_client_certificate_missing_cert_file(tmp_path, valid_cert_bundle):
    result = validate_client_certificate(
        str(tmp_path / "does_not_exist.crt"), valid_cert_bundle["key"], valid_cert_bundle["ca"]
    )
    assert result.ok is False
    assert result.reason == "cert_missing"


def test_validate_client_certificate_missing_key_file(tmp_path, valid_cert_bundle):
    result = validate_client_certificate(
        valid_cert_bundle["cert"], str(tmp_path / "does_not_exist.key"), valid_cert_bundle["ca"]
    )
    assert result.ok is False
    assert result.reason == "key_missing"


def test_validate_client_certificate_wrong_ca_rejects_chain(tmp_path, valid_cert_bundle):
    # A second, unrelated CA — the client cert was NOT signed by it.
    other_ca_key = tmp_path / "other_ca.key"
    other_ca_crt = tmp_path / "other_ca.crt"
    _run("openssl", "req", "-new", "-x509", "-days", "1", "-nodes",
         "-subj", "/CN=other-ca", "-keyout", str(other_ca_key), "-out", str(other_ca_crt))
    result = validate_client_certificate(
        valid_cert_bundle["cert"], valid_cert_bundle["key"], str(other_ca_crt)
    )
    assert result.ok is False
    assert result.reason == "chain_invalid"


def test_validate_client_certificate_expired(tmp_path):
    ca_key = tmp_path / "ca.key"
    ca_crt = tmp_path / "ca.crt"
    client_key = tmp_path / "client.key"
    client_csr = tmp_path / "client.csr"
    client_crt = tmp_path / "client.crt"
    _run("openssl", "req", "-new", "-x509", "-days", "1", "-nodes",
         "-subj", "/CN=test-ca", "-keyout", str(ca_key), "-out", str(ca_crt))
    _run("openssl", "req", "-new", "-nodes", "-subj", "/CN=expired_person",
         "-keyout", str(client_key), "-out", str(client_csr))
    # -days -1: already expired at issuance.
    _run("openssl", "x509", "-req", "-in", str(client_csr), "-CA", str(ca_crt),
         "-CAkey", str(ca_key), "-CAcreateserial", "-days", "-1",
         "-out", str(client_crt))
    result = validate_client_certificate(str(client_crt), str(client_key), str(ca_crt))
    assert result.ok is False
    assert result.reason == "expired"


def test_validate_client_certificate_missing_client_auth_eku(tmp_path):
    # A cert signed by the CA but WITHOUT the clientAuth extended key
    # usage — openssl's verify with -purpose sslclient must reject this.
    ca_key = tmp_path / "ca.key"
    ca_crt = tmp_path / "ca.crt"
    client_key = tmp_path / "client.key"
    client_csr = tmp_path / "client.csr"
    client_crt = tmp_path / "client.crt"
    _run("openssl", "req", "-new", "-x509", "-days", "1", "-nodes",
         "-subj", "/CN=test-ca", "-keyout", str(ca_key), "-out", str(ca_crt))
    _run("openssl", "req", "-new", "-nodes", "-subj", "/CN=no_eku_person",
         "-keyout", str(client_key), "-out", str(client_csr))
    # No -extfile: no extendedKeyUsage at all.
    _run("openssl", "x509", "-req", "-in", str(client_csr), "-CA", str(ca_crt),
         "-CAkey", str(ca_key), "-CAcreateserial", "-days", "1",
         "-out", str(client_crt))
    result = validate_client_certificate(str(client_crt), str(client_key), str(ca_crt))
    assert result.ok is False
    assert result.reason == "missing_client_auth_eku"


def test_build_pki_paths_authcfg_config():
    config = build_pki_paths_authcfg_config("bridge_mtls_cert", "/path/to/cert.pem", "/path/to/key.pem")
    assert config == {
        "method": "PKI-Paths",
        "name": "bridge_mtls_cert",
        "config": {"certpath": "/path/to/cert.pem", "keypath": "/path/to/key.pem"},
    }


def test_build_pgpass_line_simple():
    line = build_pgpass_line("db.example.internal", 5432, "farois_ftth", "ftth_editor", "s3cr3t")
    assert line == "db.example.internal:5432:farois_ftth:ftth_editor:s3cr3t"


def test_build_pgpass_line_escapes_colon_and_backslash():
    # Per https://www.postgresql.org/docs/current/libpq-pgpass.html :
    # ":" and "\" in any field must be escaped with a preceding "\".
    line = build_pgpass_line("db.example.internal", 5432, "farois_ftth", "ftth_editor", "p:a\\ss")
    assert line == "db.example.internal:5432:farois_ftth:ftth_editor:p\\:a\\\\ss"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/sdadmin/.venvs/bridge0-tests/bin/pytest plugin-repo/packages/constructel_bridge_tests/test_bridge_mtls.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'constructel_bridge.bridge_mtls'`

- [ ] **Step 3: Write `bridge_mtls.py`**

```python
"""Certificate validation and connection-config builders for mTLS
(PR Bridge 1, 2026-09-23).

Side-effect-free except for shelling out to `openssl` (read-only
inspection, never writes/generates keys here — key generation is a
Farois/Constructel runbook responsibility, not this plugin's). No qgis
import: bridge_plugin.py consumes these functions, this module does not
depend on it or on QGIS being importable.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CertValidationResult:
    ok: bool
    reason: str | None  # None when ok=True; one of the named reasons below otherwise


def validate_client_certificate(cert_path: str, key_path: str, ca_path: str) -> CertValidationResult:
    """Validates a client certificate is usable for mTLS: present, chains
    to the given CA, not expired/not-yet-valid, and carries the clientAuth
    extended key usage. Does not check the key matches the cert (libpq
    itself will refuse to connect if they don't — this is a pre-flight UX
    check, not the security boundary).
    """
    if not Path(cert_path).is_file():
        return CertValidationResult(ok=False, reason="cert_missing")
    if not Path(key_path).is_file():
        return CertValidationResult(ok=False, reason="key_missing")

    # -purpose sslclient checks both chain validity AND clientAuth EKU in
    # one openssl invocation; its stderr distinguishes the two failure
    # modes by message, since it returns a single non-zero exit either way.
    verify = subprocess.run(
        ["openssl", "verify", "-purpose", "sslclient", "-CAfile", ca_path, cert_path],
        capture_output=True, text=True,
    )
    if verify.returncode != 0:
        if "unable to get local issuer certificate" in verify.stderr or "certificate signature failure" in verify.stderr:
            return CertValidationResult(ok=False, reason="chain_invalid")
        if "certificate has expired" in verify.stderr:
            return CertValidationResult(ok=False, reason="expired")
        if "certificate is not yet valid" in verify.stderr:
            return CertValidationResult(ok=False, reason="not_yet_valid")
        if "unhandled critical extension" in verify.stderr or "unsupported certificate purpose" in verify.stderr:
            return CertValidationResult(ok=False, reason="missing_client_auth_eku")
        return CertValidationResult(ok=False, reason="chain_invalid")

    return CertValidationResult(ok=True, reason=None)


def build_pki_paths_authcfg_config(name: str, cert_path: str, key_path: str) -> dict:
    """Shape of a QGIS QgsAuthMethodConfig("PKI-Paths") — certificate and
    key ONLY, never a password (see Global Constraints: bug #58179 means
    the password must never travel through an authcfg on a cert-bearing
    connection). bridge_plugin.py turns this dict into a real
    QgsAuthMethodConfig via .setConfig() calls, mirroring
    _store_password_encrypted()'s existing pattern for the "Basic" method.
    """
    return {
        "method": "PKI-Paths",
        "name": name,
        "config": {"certpath": cert_path, "keypath": key_path},
    }


def build_pgpass_line(host: str, port: int, dbname: str, username: str, password: str) -> str:
    """Builds one line of a libpq .pgpass file. Escapes ':' and '\\' in
    every field per https://www.postgresql.org/docs/current/libpq-pgpass.html
    — the password field is where this matters in practice, but all
    fields are escaped for correctness.
    """
    def esc(field: str) -> str:
        return str(field).replace("\\", "\\\\").replace(":", "\\:")

    return f"{esc(host)}:{esc(port)}:{esc(dbname)}:{esc(username)}:{esc(password)}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/sdadmin/.venvs/bridge0-tests/bin/pytest plugin-repo/packages/constructel_bridge_tests/test_bridge_mtls.py -v`
Expected: PASS — 9 passed. (If `missing_client_auth_eku` doesn't trigger the expected openssl stderr text on this server's OpenSSL 3.0.2, read the actual `verify.stderr` the test run prints and adjust the string match in Step 3 to what OpenSSL 3.0.2 genuinely emits — do not guess the message, read the real one.)

- [ ] **Step 5: Commit**

```bash
git add plugin-repo/packages/constructel_bridge/bridge_mtls.py plugin-repo/packages/constructel_bridge_tests/test_bridge_mtls.py
git commit -m "feat(bridge1): add bridge_mtls.py — cert validation + PKI-Paths/.pgpass config builders"
```

---

### Task 3: legacy connection recognition (pure logic)

**Files:**
- Modify: `plugin-repo/packages/constructel_bridge/bridge_mtls.py`
- Modify: `plugin-repo/packages/constructel_bridge_tests/test_bridge_mtls.py`

**Interfaces:**
- Produces (used by Task 5): `needs_mtls_migration(connection_settings: dict) -> bool` — given a dict snapshot of an existing QGIS PG connection's settings (`sslmode`, `authcfg`, `password` presence), returns `True` if it's an old-style connection (password-only, `sslmode` numeric code `"3"` i.e. `require`, or a "Basic" authcfg) that needs migrating to the cert+`.pgpass` pattern, `False` if it's already migrated (an existing "PKI-Paths" authcfg present) or genuinely unrelated (different host).

- [ ] **Step 1: Write the failing tests**

Add to `test_bridge_mtls.py`:

```python
from constructel_bridge.bridge_mtls import needs_mtls_migration


def test_needs_migration_old_basic_authcfg_password_connection():
    settings = {"host": "db.example.internal", "sslmode": "3", "authcfg": "basic_cfg_id", "savePassword": False}
    assert needs_mtls_migration(settings) is True


def test_needs_migration_already_migrated_pki_connection():
    settings = {"host": "db.example.internal", "sslmode": "5", "authcfg": "pki_cfg_id", "savePassword": False}
    assert needs_mtls_migration(settings) is False


def test_needs_migration_no_authcfg_at_all():
    settings = {"host": "db.example.internal", "sslmode": "3", "authcfg": "", "savePassword": False}
    assert needs_mtls_migration(settings) is True
```

*(Note: `needs_mtls_migration`'s exact discrimination between a "Basic" and a "PKI-Paths" authcfg requires looking up the authcfg's stored method — Step 3 below takes an `authcfg_method: str | None` parameter for this rather than guessing it from the `authcfg` id string alone, since QGIS doesn't encode the method in the id. Adjust the test fixtures above to pass `authcfg_method` explicitly once you're implementing Step 3 — the tests above sketch the property being tested; write the real signature to match what Step 3 needs, then update these three tests to call it correctly before moving to Step 2.)*

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/sdadmin/.venvs/bridge0-tests/bin/pytest plugin-repo/packages/constructel_bridge_tests/test_bridge_mtls.py -v -k needs_migration`
Expected: FAIL — `ImportError: cannot import name 'needs_mtls_migration'`

- [ ] **Step 3: Implement `needs_mtls_migration`**

Add to `bridge_mtls.py`:

```python
def needs_mtls_migration(connection_settings: dict, authcfg_method: str | None) -> bool:
    """True if an existing QGIS PG connection needs migrating to the
    cert+.pgpass pattern: no authcfg at all, or an authcfg whose method
    is "Basic" (the pre-Bridge-1 pattern). False if it already has a
    "PKI-Paths" authcfg (already migrated).
    """
    authcfg = connection_settings.get("authcfg", "")
    if not authcfg:
        return True
    return authcfg_method != "PKI-Paths"
```

Update the three tests written in Step 1 to pass `authcfg_method` explicitly (`"Basic"` for the two "needs migration" cases, `"PKI-Paths"` for the "already migrated" case) matching this real signature.

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/sdadmin/.venvs/bridge0-tests/bin/pytest plugin-repo/packages/constructel_bridge_tests/test_bridge_mtls.py -v`
Expected: PASS — 12 passed (9 from Task 2 + 3 from this task).

- [ ] **Step 5: Commit**

```bash
git add plugin-repo/packages/constructel_bridge/bridge_mtls.py plugin-repo/packages/constructel_bridge_tests/test_bridge_mtls.py
git commit -m "feat(bridge1): add needs_mtls_migration for legacy connection detection"
```

---

### Task 4: document the remaining Farois/PKI dependencies (spec deliverable, no code)

**Files:**
- Modify: `docs/superpowers/specs/2026-09-22-constructel-bridge-mtls-design.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Append a dated section to the spec's "État réel du terrain"**

Add, after the existing 2026-09-22 findings:

```markdown
### Suite du 2026-09-23 — Bridge 1 : dépendances Farois/PKI restantes

Bridge 1 (cette PR) livre : validation de certificat client, config PKI-Paths,
construction de ligne `.pgpass`, détection de migration — tout testé, sans
dépendance à une PKI Farois réelle (preuve empirique contre une CA/Postgres
jetables, voir `docs/superpowers/specs/2026-09-23-bridge1-spike-results.md`).

**Ce qui reste bloquant avant un déploiement réel (hors scope de cette PR,
côté Farois/ops) :**

1. **Convention de livraison du certificat.** Aucun endroit du dépôt ne
   définit où un certificat client réel atterrit sur le poste d'un
   utilisateur après émission. `pki_manager.sh create-client <name>` n'a
   jamais été exécuté — pas d'exemple d'artefact à inspecter. Le code de
   `bridge_mtls.py` prend un chemin de répertoire en paramètre plutôt que
   de supposer une convention ; il faut décider ce chemin avec les ops
   avant que le plugin puisse chercher un certificat automatiquement.
2. **PKI réelle jamais activée.** `docker/postgres/pg_hba_mtls.conf` et
   `ssl_ca_file` restent inactifs en prod — cette PR ne les active pas et
   ne le pourrait pas de toute façon (aucune CA Farois n'existe).
3. **`pg_hba.conf` de prod est baked dans l'image Docker**, pas monté en
   volume live — toute activation future nécessitera un rebuild/redeploy
   de `ftth-postgres`, en plus de la CA elle-même.
4. **Pas d'identité Azure AD/LDAP encore branchée** (Bridge 2) — le
   « connecté comme … » de la spec reste, pour cette PR, dérivé du CN du
   certificat uniquement, jamais validé contre un annuaire.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-09-22-constructel-bridge-mtls-design.md
git commit -m "docs(bridge1): document remaining Farois/PKI dependencies before real deployment"
```

---

### Task 5: manual QGIS recette (no automated verification possible from this environment)

**Files:**
- Create: `docs/guides/RECETTE_BRIDGE1_MTLS_MANUELLE.md`

**Interfaces:** none (a procedure document for a human to follow on a machine with real QGIS — this plan's substitute for an integration test, per the spec's own explicit fallback clause: *"Si la CI ne peut pas démarrer PostgreSQL avec mTLS, fournis... un script ou procédure de recette manuelle sans secret versionné."*).

- [ ] **Step 1: Write the recette**

Create `docs/guides/RECETTE_BRIDGE1_MTLS_MANUELLE.md` with these sections, each with concrete, copy-pasteable steps referencing this plan's actual artifacts:

```markdown
# Recette manuelle Bridge 1 — mTLS Constructel Bridge

À exécuter par une personne disposant d'un vrai poste QGIS (>= 3.28).
Objectif : vérifier, avec de vrais objets QGIS (`QgsAuthManager`,
`QgsDataSourceUri`), ce que la Console Python de QGIS peut prouver et que
cette session SSH headless ne peut pas.

## Prérequis
- Rejouer `plugin-repo/packages/constructel_bridge_tests/spike/run_spike.sh`
  sur un serveur accessible depuis votre poste QGIS (le spike Bridge 1-0 est
  jetable et destructeur en sortie — ne PAS le pointer sur `ftth-postgres` de
  prod). Notez l'IP/port exposés et gardez les fichiers `pki/client.crt` et
  `pki/client.key` générés (normalement supprimés par `run_spike.sh` — pour
  cette recette, commentez temporairement l'étape de nettoyage, le temps du
  test, puis nettoyez manuellement ensuite).

## Étape 1 — Config PKI-Paths dans le Console Python QGIS

```python
from qgis.core import QgsApplication, QgsAuthMethodConfig
auth_mgr = QgsApplication.authManager()
config = QgsAuthMethodConfig("PKI-Paths")
config.setName("bridge1_recette_test")
config.setConfig("certpath", "/chemin/vers/pki/client.crt")
config.setConfig("keypath", "/chemin/vers/pki/client.key")
auth_mgr.storeAuthenticationConfig(config)
print(config.id())  # notez cet id
```
Attendu : pas d'exception, un id non vide imprimé.

## Étape 2 — Connexion combinant authcfg PKI + user/password directs

```python
from qgis.core import QgsDataSourceUri
uri = QgsDataSourceUri()
uri.setConnection(
    "<IP du spike>", "5433", "spike_db",
    "spike_test_user", "spike_test_password",
    QgsDataSourceUri.SslMode.SslVerifyFull,
    "<id noté à l'étape 1>",
)
from qgis.core import QgsVectorLayer
layer = QgsVectorLayer(uri.uri(False), "recette_test", "postgres")
print(layer.isValid())
```
Attendu : `True`. Si `False`, inspecter `layer.dataProvider().error()` et
comparer au résultat du spike (Task 1) — toute divergence est un écart
réel entre le comportement QGIS et libpq nu, à documenter ici.

## Étape 3 — Confirmer que le bug #58179 est bien contourné

Répéter l'étape 2 mais avec un authcfg "Basic" portant le mot de passe
au lieu du couple user/password direct de l'étape 2 — la couche doit
échouer à charger le certificat (c'est le bug documenté). Ceci confirme
que la conception retenue (user/password directs + authcfg PKI-Paths
séparé) est bien nécessaire, pas une précaution superflue.

## Étape 4 — Nettoyage

- `auth_mgr.removeAuthenticationConfig("<id de l'étape 1>")`
- Supprimer `pki/client.crt`/`pki/client.key` du poste de test.
- Sur le serveur : relancer `run_spike.sh` jusqu'au bout (nettoyage inclus)
  ou `docker compose -f spike_compose.yml down -v` manuellement.

## Résultat à consigner

Date, version QGIS exacte utilisée, résultat de chaque étape (succès/échec
avec message exact), toute divergence avec le comportement prouvé côté
serveur (Task 1). Coller ce résultat dans le ledger d'exécution de ce plan
ou dans un commentaire de PR — c'est la preuve d'intégration qui manque à
la CI.
```

- [ ] **Step 2: Commit**

```bash
git add docs/guides/RECETTE_BRIDGE1_MTLS_MANUELLE.md
git commit -m "docs(bridge1): manual QGIS recette — substitute for integration tests this environment can't run"
```

---

## Self-Review

**Spec coverage** (against the spec's "PR Bridge 1 — mTLS/Auth Manager : certificat, verify-full, migration idempotente, diagnostics"):
- *certificat* → Task 2 (`validate_client_certificate`, `build_pki_paths_authcfg_config`).
- *verify-full* → Global Constraints binding, proven empirically in Task 1's spike (`sslmode=verify-full` is the exact mode tested).
- *migration idempotente* → Task 3 (`needs_mtls_migration`) — detection logic only; the actual idempotent rewrite of a QGIS connection's settings is explicitly deferred (see below).
- *diagnostics* → `CertValidationResult`'s named `reason` values (Task 2) are the building block for the spec's required distinct error messages; the actual QGIS-facing error UI (message boxes, translated strings) is deferred.

**Explicitly deferred, not silently dropped:** wiring these functions into `bridge_plugin.py`'s actual `_connect`/`_setup_qgis_pg_connection` flow, the cert-selection UX (detect/list/choose among multiple admissible certs), and the translated diagnostic messages are **not** tasks in this plan. This plan stops at "the pure logic exists, is tested, and is proven against a real mTLS Postgres" — wiring it into the live plugin is real, further work that should be its own follow-up plan once (a) the cert-delivery convention from Task 4's write-up is actually decided with Farois/ops, and (b) Task 5's manual recette has been run for real by someone with QGIS and its results fed back. Shipping the wiring blind, without either of those, would violate the spec's own instruction to "arrêter l'activation plutôt que de dégrader la sécurité."

**Placeholder scan:** no `TODO`/`TBD` in executable code. Task 3's tests are deliberately written as a sketch with an explicit instruction to adjust once the real signature is written (Step 3) — this is flagged inline as intentional, not a hidden placeholder, and Step 4 requires them passing for real before commit.

**Type consistency:** `CertValidationResult` (Task 2) is a frozen dataclass with `ok: bool`, `reason: str | None`; every test checks both fields explicitly. `needs_mtls_migration` (Task 3) takes `authcfg_method: str | None` as a second positional argument, consistent between its Step 3 implementation and the Step 1 tests once corrected per the Step 1 note.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-23-bridge1-mtls-auth-manager.md`. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach?
