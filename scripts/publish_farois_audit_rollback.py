#!/usr/bin/env python3
"""Publish only Farois assets, preserving all existing catalogue entries."""

import argparse
import configparser
import hashlib
from pathlib import Path
import shutil
import tempfile
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
import zipfile

PLUGIN = "farois_audit_rollback"
FIELDS = {
    "description": "description",
    "about": "about",
    "version": "version",
    "qgisMinimumVersion": "qgis_minimum_version",
    "qgisMaximumVersion": "qgis_maximum_version",
    "author": "author_name",
    "email": "email",
    "homepage": "homepage",
    "tracker": "tracker",
    "repository": "repository",
    "tags": "tags",
    "experimental": "experimental",
    "deprecated": "deprecated",
    "hasProcessingProvider": "has_processing_provider",
}


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def publish(package, repository_dir, base_url, dry_run=False):
    package, repository_dir = Path(package), Path(repository_dir)
    url = urlparse(base_url)
    if (
        url.scheme not in ("http", "https")
        or not url.netloc
        or url.username
        or url.password
    ):
        raise ValueError("Une URL HTTP(S) sans identifiants est requise.")
    if url.query or url.fragment:
        raise ValueError("L'URL de base ne doit pas contenir de requête ou fragment.")
    base_url = base_url.rstrip("/")
    with zipfile.ZipFile(package) as archive:
        for name in archive.namelist():
            parts = Path(name).parts
            if not parts or parts[0] != PLUGIN or ".." in parts or "\\" in name:
                raise ValueError(
                    "Le ZIP doit contenir uniquement le dossier du plugin."
                )
            if any(part.startswith(".env") or part == "__pycache__" for part in parts):
                raise ValueError("Le ZIP contient des fichiers exclus.")
        if archive.testzip() is not None:
            raise ValueError("ZIP invalide.")
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read_string(archive.read(f"{PLUGIN}/metadata.txt").decode("utf-8"))
        meta = cfg["general"]
        version = meta["version"]
        if not version or any(
            char not in "0123456789.-abcdefghijklmnopqrstuvwxyz" for char in version
        ):
            raise ValueError("Version invalide.")
        filename = f"{PLUGIN}.{version}.zip"  # id QGIS = file_name.partition(".")[0]
        icon_name = meta["icon"]
        if Path(icon_name).name != icon_name or not icon_name.endswith(".png"):
            raise ValueError("Icône PNG à la racine du plugin requise.")
        icon_bytes = archive.read(f"{PLUGIN}/{icon_name}")
    catalogue = repository_dir / "plugins.xml"
    original = catalogue.read_text(encoding="utf-8")
    root = ET.fromstring(original)
    if root.tag != "plugins":
        raise ValueError("Catalogue QGIS invalide.")
    download_url = f"{base_url}/plugin-repo/packages/{filename}"
    icon_file = f"{PLUGIN}_{version}.png"
    entry = ET.Element("pyqgis_plugin", name=meta["name"], version=version)
    for source, target in FIELDS.items():
        ET.SubElement(entry, target).text = meta.get(source, "")
    ET.SubElement(entry, "server").text = "False"
    ET.SubElement(entry, "icon").text = f"{base_url}/plugin-repo/icons/{icon_file}"
    ET.SubElement(entry, "file_name").text = filename
    ET.SubElement(entry, "download_url").text = download_url
    existing = [node for node in root if node.findtext("file_name") == filename]
    if existing:
        if (
            len(existing) != 1
            or ET.tostring(existing[0]).strip() != ET.tostring(entry).strip()
        ):
            # Compare structure without indentation tails.
            def values(node):
                return node.attrib, [(child.tag, child.text or "") for child in node]

            if len(existing) != 1 or values(existing[0]) != values(entry):
                raise ValueError("Cette version possède déjà une entrée différente.")
        updated = original
    else:
        closing = original.rfind("</plugins>")
        if closing < 0:
            raise ValueError("Balise de fermeture du catalogue absente.")
        block = ET.tostring(entry, encoding="unicode")
        updated = original[:closing] + "  " + block + "\n" + original[closing:]
    ET.fromstring(updated)
    destination = repository_dir / "packages" / filename
    if destination.exists() and _digest(destination) != _digest(package):
        raise ValueError("Un ZIP différent existe déjà pour cette version.")
    icon_destination = repository_dir / "icons" / icon_file
    if icon_destination.exists() and icon_destination.read_bytes() != icon_bytes:
        raise ValueError("Une icône différente existe déjà pour cette version.")
    if dry_run:
        return download_url
    destination.parent.mkdir(exist_ok=True)
    icons = repository_dir / "icons"
    icons.mkdir(exist_ok=True)
    shutil.copy2(package, destination)
    (icons / icon_file).write_bytes(icon_bytes)
    if updated != original:
        # Preserve the old catalogue and make the new catalogue visible atomically.
        backup = repository_dir / f"plugins.xml.before-{PLUGIN}-{version}"
        if not backup.exists():
            shutil.copy2(catalogue, backup)
        with tempfile.NamedTemporaryFile(
            "w", dir=repository_dir, encoding="utf-8", delete=False
        ) as out:
            out.write(updated)
            staged = Path(out.name)
        staged.chmod(catalogue.stat().st_mode & 0o777)
        staged.replace(catalogue)
    return download_url


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--repository-dir", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(publish(args.package, args.repository_dir, args.base_url, args.dry_run))


if __name__ == "__main__":
    main()
