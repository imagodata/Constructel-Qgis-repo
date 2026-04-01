#!/usr/bin/env python3
"""
Generates plugins.xml from plugin ZIP files in the packages directory.

Usage:
    python3 update_plugin_repo.py --base-url http://gis-server.company.lan:8080
"""

import argparse
import configparser
import io
import os
import zipfile
from html import escape
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
PACKAGES_DIR = REPO_ROOT / "plugin-repo" / "packages"
OUTPUT_XML = REPO_ROOT / "plugin-repo" / "plugins.xml"

# Fields to extract from metadata.txt -> XML element name mapping
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
    "icon": "icon",
    "tags": "tags",
    "experimental": "experimental",
    "deprecated": "deprecated",
    "server": "server",
    "hasProcessingProvider": "has_processing_provider",
}

DEFAULTS = {
    "qgisMaximumVersion": "3.99",
    "experimental": "False",
    "deprecated": "False",
    "server": "False",
    "hasProcessingProvider": "False",
    "homepage": "",
    "tracker": "",
    "repository": "",
    "icon": "",
    "tags": "",
    "email": "",
    "about": "",
}


def parse_metadata_from_zip(zip_path: Path) -> dict | None:
    """Extract metadata.txt from a QGIS plugin ZIP and parse it."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            metadata_files = [
                n for n in zf.namelist() if n.endswith("metadata.txt") and n.count("/") == 1
            ]
            if not metadata_files:
                print(f"  SKIP {zip_path.name}: no metadata.txt found")
                return None

            raw = zf.read(metadata_files[0]).decode("utf-8", errors="replace")

            cfg = configparser.RawConfigParser()
            cfg.read_string(raw)

            if not cfg.has_section("general"):
                print(f"  SKIP {zip_path.name}: no [general] section")
                return None

            meta = {}
            for key in FIELDS:
                meta[key] = cfg.get("general", key, fallback=DEFAULTS.get(key, ""))

            meta["name"] = cfg.get("general", "name", fallback=zip_path.stem)
            return meta

    except (zipfile.BadZipFile, Exception) as e:
        print(f"  ERROR {zip_path.name}: {e}")
        return None


def build_plugin_xml(meta: dict, zip_name: str, base_url: str) -> str:
    """Build a single <pyqgis_plugin> XML block."""
    download_url = f"{base_url.rstrip('/')}/plugin-repo/packages/{zip_name}"

    def cdata(val: str) -> str:
        return f"<![CDATA[{val}]]>"

    lines = [
        f'  <pyqgis_plugin name="{escape(meta["name"])}" version="{escape(meta.get("version", "0.0.0"))}">',
    ]

    for meta_key, xml_tag in FIELDS.items():
        val = meta.get(meta_key, "")
        if xml_tag in ("description", "about", "homepage", "author_name", "tracker", "repository", "tags"):
            lines.append(f"    <{xml_tag}>{cdata(val)}</{xml_tag}>")
        else:
            lines.append(f"    <{xml_tag}>{escape(val)}</{xml_tag}>")

    lines.append(f"    <file_name>{escape(zip_name)}</file_name>")
    lines.append(f"    <download_url>{escape(download_url)}</download_url>")
    lines.append("  </pyqgis_plugin>")

    return "\n".join(lines)


def generate_plugins_xml(base_url: str, packages_dir: Path, output: Path):
    """Scan all ZIPs and generate plugins.xml."""
    zip_files = sorted(packages_dir.glob("*.zip"))

    if not zip_files:
        print("No plugin ZIPs found in", packages_dir)

    plugin_blocks = []
    for zf in zip_files:
        print(f"Processing {zf.name}...")
        meta = parse_metadata_from_zip(zf)
        if meta:
            plugin_blocks.append(build_plugin_xml(meta, zf.name, base_url))

    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n<plugins>\n'
    xml_content += "\n".join(plugin_blocks)
    xml_content += "\n</plugins>\n"

    output.write_text(xml_content, encoding="utf-8")
    print(f"\nGenerated {output} with {len(plugin_blocks)} plugin(s).")


def main():
    parser = argparse.ArgumentParser(description="Generate QGIS plugin repository XML")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("QGIS_REPO_BASE_URL", "http://192.168.160.31:8080"),
        help="Base URL where the repository is served (default: $QGIS_REPO_BASE_URL or http://192.168.160.31:8080)",
    )
    parser.add_argument(
        "--packages-dir",
        type=Path,
        default=PACKAGES_DIR,
        help=f"Directory containing plugin ZIPs (default: {PACKAGES_DIR})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_XML,
        help=f"Output plugins.xml path (default: {OUTPUT_XML})",
    )
    args = parser.parse_args()

    generate_plugins_xml(args.base_url, args.packages_dir, args.output)


if __name__ == "__main__":
    main()
