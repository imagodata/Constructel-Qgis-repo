#!/bin/sh
# Container entrypoint: start fcgiwrap (for git-http-backend) then nginx.
set -e

SOCKET=/tmp/fcgiwrap.sock
rm -f "$SOCKET"

echo "[entrypoint] starting fcgiwrap on $SOCKET"
fcgiwrap -f -c 4 -s "unix:$SOCKET" &
FCGIWRAP_PID=$!

# Wait briefly for the socket to become available
for i in 1 2 3 4 5 6 7 8 9 10; do
    [ -S "$SOCKET" ] && break
    sleep 0.2
done

if [ ! -S "$SOCKET" ]; then
    echo "[entrypoint] fcgiwrap failed to create socket" >&2
    exit 1
fi

# If fcgiwrap dies, bring the container down so Docker restarts it.
( wait "$FCGIWRAP_PID"; echo "[entrypoint] fcgiwrap exited" >&2; kill 1 ) &

echo "[entrypoint] starting nginx"
exec nginx -g 'daemon off;'
