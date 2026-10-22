#!/bin/sh
# Lance les suites pytest et le test de fumée (scripts/qgis_smoke.py) dans
# les images QGIS officielles, Qt6 (QGIS 4) comme Qt5 (QGIS 3).
#
# Usage : scripts/test_qgis_matrix.sh [image ...]
#   défaut : qgis/qgis:stable (4.x, Qt6) et qgis/qgis:ltr (3.x, Qt5)
#   ex.    : scripts/test_qgis_matrix.sh qgis/qgis:release-3_28
#
# Nécessite Docker et les images en local (pas de docker pull sur le serveur).
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
IMAGES=${*:-"qgis/qgis:stable qgis/qgis:ltr"}
rc=0
for image in $IMAGES; do
  echo "===== $image"
  docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp -e USER=qgis \
    -e QT_QPA_PLATFORM=offscreen -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$ROOT":/repo -w /repo "$image" sh -c '
      timeout 600 python3 -m pytest -p no:cacheprovider -q \
        plugin-repo/packages/constructel_bridge_tests \
        plugins/farois_audit_rollback/tests \
        resource-repo/tests
      tests=$?
      cd /tmp && timeout 300 python3 /repo/scripts/qgis_smoke.py
      smoke=$?
      [ "$tests" -eq 0 ] && [ "$smoke" -eq 0 ]' || rc=1
done
exit $rc
