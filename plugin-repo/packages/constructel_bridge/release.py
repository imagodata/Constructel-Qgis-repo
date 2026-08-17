#!/usr/bin/env python3
"""Bump plugin version in metadata.txt + plugins.xml, then rebuild the zip.

Usage:
    python release.py 1.2.0
"""

import json
import re
import sys
import zipfile
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
PACKAGES_DIR = PLUGIN_DIR.parent
PLUGINS_XML = PACKAGES_DIR.parent / "plugins.xml"
METADATA_TXT = PLUGIN_DIR / "metadata.txt"
PLUGIN_NAME = PLUGIN_DIR.name  # constructel_bridge
ZIP_PATH = PACKAGES_DIR / f"{PLUGIN_NAME}.zip"
CREDENTIALS_JSON = PLUGIN_DIR / "credentials.json"

# Secret fields stripped from credentials.json's "be" block before it is
# embedded in the distributed zip. The on-disk file (used for local
# dev/testing) is never modified — only the copy written into the archive.
BE_SECRET_KEYS = ("user", "password")


def redacted_credentials_bytes() -> bytes:
    """Return credentials.json content with be.user/be.password stripped,
    re-serialized with the same formatting as the source file (indent=4,
    trailing newline). wyre's block and be's non-secret fields are left
    untouched.
    """
    data = json.loads(CREDENTIALS_JSON.read_text())
    be = data.get("be")
    if isinstance(be, dict):
        for key in BE_SECRET_KEYS:
            be.pop(key, None)
    return (json.dumps(data, indent=4) + "\n").encode("utf-8")


def bump_metadata(version: str):
    txt = METADATA_TXT.read_text()
    if not re.search(r"(?m)^version=", txt):
        sys.exit(f"ERROR: could not find 'version=...' in {METADATA_TXT}")
    new_txt = re.sub(r"(?m)^version=.*$", f"version={version}", txt)
    METADATA_TXT.write_text(new_txt)
    print(f"  metadata.txt -> {version}")


def bump_plugins_xml(version: str):
    txt = PLUGINS_XML.read_text()
    # Update both the attribute and the <version> element
    new_txt = re.sub(
        r'(<pyqgis_plugin\s+name="Constructel Bridge"\s+version=")[\d.]+(")',
        rf"\g<1>{version}\2",
        txt,
    )
    # Only update the <version> tag inside the Constructel Bridge block
    new_txt = re.sub(
        r"(name=\"Constructel Bridge\".*?<version>)[\d.]+(</version>)",
        rf"\g<1>{version}\2",
        new_txt,
        flags=re.DOTALL,
    )
    if "Constructel Bridge" not in txt:
        sys.exit(f"ERROR: could not find Constructel Bridge entry in {PLUGINS_XML}")
    PLUGINS_XML.write_text(new_txt)
    print(f"  plugins.xml  -> {version}")


def rebuild_zip():
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath in sorted(PLUGIN_DIR.rglob("*")):
            if fpath.name == "__pycache__" or "__pycache__" in fpath.parts:
                continue
            if fpath.suffix == ".pyc":
                continue
            if fpath.name == ZIP_PATH.name:
                continue
            arcname = f"{PLUGIN_NAME}/{fpath.relative_to(PLUGIN_DIR)}"
            if fpath == CREDENTIALS_JSON:
                # Never ship be's real secret in the distributed archive;
                # the on-disk file itself is left untouched.
                zf.writestr(arcname, redacted_credentials_bytes())
                continue
            zf.write(fpath, arcname)
    size_kb = ZIP_PATH.stat().st_size / 1024
    print(f"  {ZIP_PATH.name} rebuilt ({size_kb:.0f} KB)")


def main():
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} <version>")
    version = sys.argv[1]
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        sys.exit(f"ERROR: invalid version format '{version}' (expected X.Y.Z)")

    print(f"Releasing {PLUGIN_NAME} v{version}")
    bump_metadata(version)
    bump_plugins_xml(version)
    rebuild_zip()
    print("Done.")


if __name__ == "__main__":
    main()
