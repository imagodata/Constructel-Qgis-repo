#!/usr/bin/env python3
"""Bump plugin version in metadata.txt + plugins.xml, then rebuild the zip.

Usage:
    python release.py 1.2.0
    python release.py 1.8.2 --cloture   # zip sans identifiant partage (AC12)
"""

import base64
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


CREDENTIALS_NAME = "credentials.json"
SHARED_KEYS = ("user", "password")


def strip_shared_credentials(raw: dict) -> dict:
    """credentials.json de la cloture 1.8.x : plus aucun identifiant partage.

    Retire ``user`` et ``password`` de chaque bloc de connexion (wyre, be) ;
    host/port/dbname/sslmode/... restent. Accepte aussi l'ancien format PLAT
    (host a la racine). Ne modifie pas *raw*.
    """
    clean = json.loads(json.dumps(raw))
    blocks = [clean] if "host" in clean else [b for b in clean.values() if isinstance(b, dict)]
    for block in blocks:
        for key in SHARED_KEYS:
            block.pop(key, None)
    return clean


def shared_secrets(raw: dict) -> list:
    """Mots de passe en clair (decodes) portes par credentials.json : ce que
    la cloture ne doit retrouver NULLE PART dans le zip."""
    blocks = [raw] if "host" in raw else [b for b in raw.values() if isinstance(b, dict)]
    secrets = []
    for block in blocks:
        encoded = block.get("password")
        if not encoded:
            continue
        secrets.append(encoded)
        try:
            secrets.append(base64.b64decode(encoded).decode())
        except Exception:  # noqa: BLE001 -- valeur non base64 : l'encodee suffit
            pass
    return [s for s in secrets if s]


def verify_cloture_zip(zip_path, secrets) -> None:
    """AC12 : le zip ne contient ni user/password dans credentials.json, ni
    aucun des *secrets* (brut ou base64) dans une quelconque entree.
    Leve AssertionError sinon."""
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.testzip() is None, "zip corrompu"
        creds = json.loads(zf.read(f"{PLUGIN_NAME}/{CREDENTIALS_NAME}"))
        blocks = [creds] if "host" in creds else [b for b in creds.values() if isinstance(b, dict)]
        for block in blocks:
            for key in SHARED_KEYS:
                assert key not in block, f"{key} present dans credentials.json du zip"
        for name in zf.namelist():
            data = zf.read(name)
            for secret in secrets:
                assert secret.encode() not in data, f"secret trouve dans {name}"


def rebuild_zip(cloture: bool = False):
    """Reconstruit le zip. *cloture* : credentials.json du zip est la version
    sans identifiant partage (le fichier du disque n'est pas modifie -- le
    retour arriere vers un zip a repli reste possible) puis le zip est
    controle (verify_cloture_zip)."""
    cred_path = PLUGIN_DIR / CREDENTIALS_NAME
    raw = json.loads(cred_path.read_text(encoding="utf-8")) if cloture else None
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath in sorted(PLUGIN_DIR.rglob("*")):
            if fpath.name == "__pycache__" or "__pycache__" in fpath.parts:
                continue
            if fpath.suffix == ".pyc":
                continue
            if fpath.name == ZIP_PATH.name:
                continue
            arcname = f"{PLUGIN_NAME}/{fpath.relative_to(PLUGIN_DIR)}"
            if cloture and fpath == cred_path:
                zf.writestr(arcname, json.dumps(strip_shared_credentials(raw), indent=4, ensure_ascii=False) + "\n")
                continue
            zf.write(fpath, arcname)
    if cloture:
        verify_cloture_zip(ZIP_PATH, shared_secrets(raw))
        print("  cloture : aucun identifiant partage dans le zip")
    size_kb = ZIP_PATH.stat().st_size / 1024
    print(f"  {ZIP_PATH.name} rebuilt ({size_kb:.0f} KB)")


def main():
    args = [a for a in sys.argv[1:] if a != "--cloture"]
    cloture = len(args) != len(sys.argv) - 1
    if len(args) != 1:
        sys.exit(f"Usage: {sys.argv[0]} <version> [--cloture]")
    version = args[0]
    if not re.match(r"^\d+\.\d+\.\d+$", version):
        sys.exit(f"ERROR: invalid version format '{version}' (expected X.Y.Z)")

    print(f"Releasing {PLUGIN_NAME} v{version}" + (" (cloture)" if cloture else ""))
    bump_metadata(version)
    bump_plugins_xml(version)
    rebuild_zip(cloture=cloture)
    print("Done.")


if __name__ == "__main__":
    main()
