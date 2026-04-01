#!/bin/bash
# Initialise les volumes Docker avec les données existantes des repos.
# À exécuter une seule fois après le premier `docker compose up`.
#
# Usage: ./scripts/docker-init.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONTAINER="qgis-repo"

echo "=== Initialisation des volumes Docker QGIS Repo ==="

# Vérifier que le container tourne
if ! docker inspect "$CONTAINER" &>/dev/null; then
    echo "Erreur: le container '$CONTAINER' n'existe pas."
    echo "Lancez d'abord: docker compose up -d"
    exit 1
fi

# Copier le plugin-repo
echo "Copie de plugin-repo..."
docker cp "$PROJECT_DIR/plugin-repo/." "$CONTAINER:/data/plugin-repo/"

# Copier le resource-repo
echo "Copie de resource-repo..."
docker cp "$PROJECT_DIR/resource-repo/." "$CONTAINER:/data/resource-repo/"

echo ""
echo "Volumes initialisés avec succès."
echo "  Plugin repo:   http://localhost:8080/plugin-repo/plugins.xml"
echo "  Resource repo: http://localhost:8080/resource-repo/metadata.ini"
