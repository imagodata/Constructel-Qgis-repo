"""Validate and package ONE Resource Sharing collection, without rebuilding the others.

Usage:
    python3 package_collection.py                         # layers_to_atlas
    python3 package_collection.py asbuilt_depth_geocoder

Each packaged collection has an explicit allowlist (no caches, no secrets, no
stray files): the ZIP must contain exactly those files.
"""

import configparser
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
DEFAULT_COLLECTION = "layers_to_atlas"
COLLECTION = ROOT / "collections" / DEFAULT_COLLECTION

ALLOWLISTS = {
    "layers_to_atlas": [
        "processing/layers_to_atlas.py",
        "svg/constructel.svg",
        "README.txt",
    ],
    # 1.3.0 : plus de style/*.qml, les styles As-Built viennent de Farois.
    "asbuilt_depth_geocoder": [
        "processing/geocode_asbuilt_depth.py",
        "README.txt",
    ],
}


def main(name: str = DEFAULT_COLLECTION):
    if name not in ALLOWLISTS:
        sys.exit(f"ERROR: unknown collection '{name}' (known: {', '.join(sorted(ALLOWLISTS))})")
    collection = COLLECTION if name == DEFAULT_COLLECTION else ROOT / "collections" / name
    metadata = configparser.ConfigParser(interpolation=None)
    metadata.read(ROOT / "metadata.ini", encoding="utf-8")
    registered = [
        entry.strip() for entry in metadata["general"]["collections"].split(",")
    ]
    assert registered.count(name) == 1
    for entry in registered:
        assert entry in metadata
    for key in (
        "name",
        "author",
        "tags",
        "description",
        "version",
        "qgis_minimum_version",
        "qgis_maximum_version",
    ):
        assert metadata[name][key]
    files = ALLOWLISTS[name]
    for rel in files:
        if rel.endswith(".py"):
            compile((collection / rel).read_text(encoding="utf-8"), rel, "exec")
    output = ROOT / "collections" / f"{name}.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in files:
            archive.write(collection / rel, rel)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(files)
    print(f"Metadata, syntax and ZIP OK: {output} (version {metadata[name]['version']})")


if __name__ == "__main__":
    main(*sys.argv[1:2])
