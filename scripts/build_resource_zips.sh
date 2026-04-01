#!/bin/bash
# Build ZIP archives for each Resource Sharing collection.
# The QGIS Resource Sharing plugin (HTTP mode) expects downloadable ZIPs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESOURCE_DIR="${SCRIPT_DIR}/../resource-repo"
COLLECTIONS_DIR="${RESOURCE_DIR}/collections"

if [ ! -d "$COLLECTIONS_DIR" ]; then
    echo "No collections directory found at $COLLECTIONS_DIR"
    exit 1
fi

python3 -c "
import zipfile, os, sys

collections_dir = sys.argv[1]
resource_dir = sys.argv[2]

os.chdir(collections_dir)
for d in sorted(os.listdir('.')):
    if not os.path.isdir(d):
        continue
    zipname = os.path.join(collections_dir, f'{d}.zip')
    print(f'Zipping collection: {d}')
    with zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(d):
            for f in files:
                if f == '.gitkeep':
                    continue
                filepath = os.path.join(root, f)
                arcname = os.path.relpath(filepath, d)
                zf.write(filepath, arcname)
                print(f'  + {arcname}')
    print(f'  -> {zipname}')
" "$COLLECTIONS_DIR" "$RESOURCE_DIR"

echo "Done. ZIP files are in $COLLECTIONS_DIR"
