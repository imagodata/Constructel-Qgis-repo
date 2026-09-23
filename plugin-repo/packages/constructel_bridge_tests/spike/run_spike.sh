#!/usr/bin/env bash
# Proves: (a) cert+password together succeeds, (b) password alone (no
# client cert) fails, (c) wrong/no password with a valid cert also fails
# (clientcert=verify-full is a TLS gate, not itself an auth method here).
#
# ENVIRONMENT NOTES (full rationale in spike_compose.yml -- none of this
# touches the security-relevant controls under test, i.e. the
# spike_pg_hba.conf rule or the SSL mode used in the connection strings):
#  - This host cannot `docker pull` fresh images and has no local `psql`
#    binary (and no passwordless sudo to install one). Every psql call
#    below therefore runs via `docker run --network host --entrypoint psql`
#    against the already-cached ftth-postgres:17.3.5-farois image, which
#    behaves identically to a locally-installed psql client here.
#  - Connections use `host=localhost`, not `host=127.0.0.1`. The server
#    cert's CN is `localhost` (see generate_spike_pki.sh), and
#    sslmode=verify-full checks the connection hostname string against
#    that CN -- "127.0.0.1" does not match "localhost" textually. This is
#    a correction to an internal inconsistency between the brief's own
#    generate_spike_pki.sh (CN=localhost) and its original run_spike.sh
#    snippet (host=127.0.0.1), not a security-relevant change.
#  - spike_pg_hba.conf (byte-for-byte as specified) is switched in via
#    `ALTER SYSTEM SET hba_file` + a container restart, after the default
#    bootstrap completes -- see spike_compose.yml note 3 for why.
set -euo pipefail
cd "$(dirname "$0")"

PSQL_IMAGE=ftth-postgres:17.3.5-farois
COMPOSE_FILE=spike_compose.yml

psql_docker() {
  # Wraps a dockerized psql client on the host network, mounting the
  # throwaway pki/ dir read-only. All args are forwarded to psql verbatim.
  docker run --rm --network host \
    -v "$(pwd)/pki:/certs:ro" \
    --entrypoint psql \
    "$@"
}

./generate_spike_pki.sh

echo
echo "=== fixing ownership of pki/server.key for the container's postgres user ==="
POSTGRES_UID=$(docker run --rm --entrypoint id "$PSQL_IMAGE" -u postgres)
echo "postgres uid inside $PSQL_IMAGE = $POSTGRES_UID"
docker run --rm -v "$(pwd)/pki:/pki" --entrypoint chown "$PSQL_IMAGE" \
  "${POSTGRES_UID}:${POSTGRES_UID}" /pki/server.key

docker compose -f "$COMPOSE_FILE" up -d
trap 'docker compose -f "$COMPOSE_FILE" down -v' EXIT

echo
echo "Waiting for spike-postgres to be ready (booting with the image's default pg_hba.conf, so bootstrap can use its local trust rule)..."
for i in $(seq 1 30); do
  docker compose -f "$COMPOSE_FILE" exec -T spike-postgres pg_isready -U spike_test_user && break
  sleep 1
done

echo
echo "=== switching to spike_pg_hba.conf (ALTER SYSTEM + restart -- see spike_compose.yml note 3) ==="
docker compose -f "$COMPOSE_FILE" exec -T spike-postgres \
  psql -U spike_test_user -d spike_db \
  -c "ALTER SYSTEM SET hba_file = '/etc/postgresql-certs/pg_hba.conf';"
docker compose -f "$COMPOSE_FILE" restart spike-postgres

echo
echo "=== waiting for spike-postgres to accept cert+password connections under spike_pg_hba.conf, and showing its effective config (proves our mounted files -- not the image's own defaults -- are what's active) ==="
SHOW_OUT=""
READY=0
for i in $(seq 1 30); do
  if SHOW_OUT=$(psql_docker \
      -e PGSSLCERT=/certs/client.crt -e PGSSLKEY=/certs/client.key -e PGSSLROOTCERT=/certs/ca.crt \
      -e PGPASSWORD=spike_test_password \
      "$PSQL_IMAGE" \
      "host=localhost port=5433 dbname=spike_db user=spike_test_user sslmode=verify-full" \
      -c "SHOW hba_file;" -c "SHOW ssl_cert_file;" -c "SHOW ssl_key_file;" -c "SHOW ssl_ca_file;" \
      -c "CREATE EXTENSION IF NOT EXISTS sslinfo;" 2>&1); then
    READY=1
    break
  fi
  sleep 1
done
echo "$SHOW_OUT"
if [ "$READY" -ne 1 ]; then
  echo "spike-postgres never became ready under spike_pg_hba.conf -- aborting." >&2
  exit 1
fi

echo
echo "=== (a) cert + password: EXPECT SUCCESS ==="
psql_docker \
  -e PGSSLCERT=/certs/client.crt -e PGSSLKEY=/certs/client.key -e PGSSLROOTCERT=/certs/ca.crt \
  -e PGPASSWORD=spike_test_password \
  "$PSQL_IMAGE" \
  "host=localhost port=5433 dbname=spike_db user=spike_test_user sslmode=verify-full" \
  -c "SELECT 'spike connection OK, cert CN=' || ssl_client_dn();" \
  && echo "RESULT: SUCCESS (as expected)" || echo "RESULT: FAILED (unexpected -- investigate)"

echo
echo "=== (b) password alone, NO client cert: EXPECT FAILURE ==="
psql_docker \
  -e PGPASSWORD=spike_test_password \
  "$PSQL_IMAGE" \
  "host=localhost port=5433 dbname=spike_db user=spike_test_user sslmode=require" \
  -c "SELECT 1;" \
  && echo "RESULT: SUCCESS (UNEXPECTED -- cert requirement not enforced, investigate)" \
  || echo "RESULT: FAILED (as expected -- no cert)"

echo
echo "=== (c) valid cert, WRONG password: EXPECT FAILURE ==="
psql_docker \
  -e PGSSLCERT=/certs/client.crt -e PGSSLKEY=/certs/client.key -e PGSSLROOTCERT=/certs/ca.crt \
  -e PGPASSWORD=wrong_password \
  "$PSQL_IMAGE" \
  "host=localhost port=5433 dbname=spike_db user=spike_test_user sslmode=verify-full" \
  -c "SELECT 1;" \
  && echo "RESULT: SUCCESS (UNEXPECTED -- password not actually checked, investigate)" \
  || echo "RESULT: FAILED (as expected -- cert alone does not bypass password)"
