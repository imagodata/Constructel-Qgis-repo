#!/usr/bin/env bash
# Throwaway CA + server + client certificate, for Bridge 1-0 spike ONLY.
# Never reused outside this spike; destroy with cleanup (run_spike.sh trap /
# Step 6) when done.
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
