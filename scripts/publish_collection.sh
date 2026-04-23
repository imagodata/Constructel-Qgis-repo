#!/bin/bash
# Publish a local collection directory to the Constructel Resource Sharing
# git repo. Intended to run from a user workstation inside the internal
# network (192.168.160.0/24).
#
# Usage:
#   publish_collection.sh <local-collection-dir> <collection-name> \
#       [--repo http://192.168.160.31:9082/] [--message "msg"]
#
# Example:
#   publish_collection.sh ~/my_sketches sketchy_sketches
#
# The script will:
#   1. Clone the bare repo into a temp directory
#   2. Rsync <local-collection-dir>/ into collections/<collection-name>/
#   3. Commit and push
#
# Requires: git, rsync. Network access to the repo URL.

set -euo pipefail

REPO_URL="http://192.168.160.31:9082/"
MESSAGE=""
POSITIONAL=()

while [ $# -gt 0 ]; do
    case "$1" in
        --repo)
            REPO_URL="$2"; shift 2 ;;
        --message|-m)
            MESSAGE="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,20p' "$0"; exit 0 ;;
        *)
            POSITIONAL+=("$1"); shift ;;
    esac
done

if [ "${#POSITIONAL[@]}" -lt 2 ]; then
    echo "usage: $(basename "$0") <local-collection-dir> <collection-name> [--repo URL] [--message MSG]" >&2
    exit 1
fi

LOCAL_DIR="${POSITIONAL[0]}"
COLLECTION_NAME="${POSITIONAL[1]}"

if [ ! -d "$LOCAL_DIR" ]; then
    echo "error: local collection dir not found: $LOCAL_DIR" >&2
    exit 1
fi

# Sanitize name (alphanumerics, underscore, hyphen)
if ! [[ "$COLLECTION_NAME" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "error: collection name must match [A-Za-z0-9_-]+" >&2
    exit 1
fi

TMP="$(mktemp -d -t qgis-publish.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

echo ">> cloning $REPO_URL"
git clone "$REPO_URL" "$TMP/work"

cd "$TMP/work"
DEFAULT_BRANCH="$(git symbolic-ref --short HEAD)"

TARGET_DIR="collections/$COLLECTION_NAME"
mkdir -p "$TARGET_DIR"

echo ">> copying $LOCAL_DIR/ into $TARGET_DIR/"
rsync -a --delete \
    --exclude='.git/' \
    --exclude='*.zip' \
    "$LOCAL_DIR"/ "$TARGET_DIR"/

git add -A

if git diff --cached --quiet; then
    echo ">> no changes to publish"
    exit 0
fi

if [ -z "$MESSAGE" ]; then
    MESSAGE="publish: update collection $COLLECTION_NAME"
fi

git commit -m "$MESSAGE"
echo ">> pushing to $REPO_URL ($DEFAULT_BRANCH)"
git push origin "$DEFAULT_BRANCH"

echo ">> published. Server will rebuild ZIPs automatically."
echo ">> note: metadata.ini must be updated separately to list a new collection."
