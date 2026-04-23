#!/bin/bash
# One-time bootstrap: align resource-repo.git (bare) with the live
# resource-repo/ working tree, then enable the post-receive sync marker.
#
# Run this once before turning on HTTP push. After that, resource-repo/
# is automatically refreshed by the post-receive hook on every push.
#
# What it does:
#   1. Stages the current content of resource-repo/ into the bare repo
#      via a temporary clone.
#   2. Commits and pushes back as "bootstrap sync from live working tree".
#   3. Creates resource-repo/.sync-enabled so the post-receive hook will
#      take over from now on.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BARE="$REPO_ROOT/resource-repo.git"
WORK="$REPO_ROOT/resource-repo"
MARKER="$BARE/.sync-enabled"
LEGACY_MARKER="$WORK/.sync-enabled"

if [ ! -d "$BARE" ]; then
    echo "error: bare repo not found: $BARE" >&2
    exit 1
fi
if [ ! -d "$WORK" ]; then
    echo "error: working tree not found: $WORK" >&2
    exit 1
fi

DEFAULT_BRANCH=master
if git --git-dir="$BARE" show-ref --verify --quiet refs/heads/main; then
    DEFAULT_BRANCH=main
fi

TMP="$(mktemp -d -t qgis-bare-sync.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

echo ">> cloning bare repo into $TMP"
git clone --branch "$DEFAULT_BRANCH" "$BARE" "$TMP/work" >/dev/null

echo ">> mirroring $WORK/ into clone (excluding generated .zip and marker)"
rsync -a --delete \
    --exclude='*.zip' \
    --exclude='.sync-enabled' \
    --exclude='.git/' \
    "$WORK"/ "$TMP/work"/

cd "$TMP/work"

if git diff --quiet && git diff --cached --quiet && [ -z "$(git status --porcelain)" ]; then
    echo ">> bare repo already in sync with working tree - nothing to commit"
else
    git add -A
    git -c user.name="qgis-repo-sync" -c user.email="sig@constructel.fr" \
        commit -m "bootstrap: sync bare repo from live resource-repo/ working tree"
    echo ">> pushing to bare repo"
    git push origin "$DEFAULT_BRANCH"
fi

cd "$REPO_ROOT"

if [ ! -f "$MARKER" ]; then
    echo ">> creating $MARKER (enables post-receive worktree sync)"
    printf 'Auto-managed by scripts/sync_bare_from_worktree.sh.\nRemove to disable post-receive worktree sync.\n' > "$MARKER"
fi

# Legacy marker inside work tree is fragile (git clean removes it). Migrate if present.
if [ -f "$LEGACY_MARKER" ]; then
    echo ">> removing legacy marker $LEGACY_MARKER (new location: $MARKER)"
    rm -f "$LEGACY_MARKER"
fi

echo ">> done. Future pushes to $BARE will auto-refresh $WORK and rebuild ZIPs."
