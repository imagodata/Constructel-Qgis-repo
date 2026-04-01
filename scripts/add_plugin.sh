#!/bin/bash
# Add a plugin ZIP to the repository and regenerate plugins.xml.
# Usage: ./add_plugin.sh /path/to/MyPlugin.1.0.zip [--base-url http://server:8080]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PACKAGES_DIR="${SCRIPT_DIR}/../plugin-repo/packages"

if [ -z "${1:-}" ]; then
    echo "Usage: $0 <plugin.zip> [--base-url URL]"
    exit 1
fi

ZIP_FILE="$1"
shift

if [ ! -f "$ZIP_FILE" ]; then
    echo "File not found: $ZIP_FILE"
    exit 1
fi

cp "$ZIP_FILE" "$PACKAGES_DIR/"
echo "Copied $(basename "$ZIP_FILE") to $PACKAGES_DIR/"

python3 "${SCRIPT_DIR}/update_plugin_repo.py" "$@"
