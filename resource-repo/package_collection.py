"""Validate and package only the Atlas collection, without rebuilding other ZIPs."""

import configparser
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
COLLECTION = ROOT / "collections" / "layers_to_atlas"


def main():
    metadata = configparser.ConfigParser(interpolation=None)
    metadata.read(ROOT / "metadata.ini", encoding="utf-8")
    registered = [
        name.strip() for name in metadata["general"]["collections"].split(",")
    ]
    assert registered.count("layers_to_atlas") == 1
    for name in registered:
        assert name in metadata
    for key in (
        "name",
        "author",
        "tags",
        "description",
        "version",
        "qgis_minimum_version",
        "qgis_maximum_version",
    ):
        assert metadata["layers_to_atlas"][key]
    files = ["processing/layers_to_atlas.py", "svg/constructel.svg", "README.txt"]
    compile((COLLECTION / files[0]).read_text(encoding="utf-8"), files[0], "exec")
    output = ROOT / "collections" / "layers_to_atlas.zip"
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(COLLECTION / name, name)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(files)
    print(f"Metadata, syntax and ZIP OK: {output}")


if __name__ == "__main__":
    main()
