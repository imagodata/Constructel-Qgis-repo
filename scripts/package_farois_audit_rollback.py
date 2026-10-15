#!/usr/bin/env python3
"""Build a clean QGIS-installable ZIP without secrets, caches, or local data."""

from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "farois_audit_rollback"
VERSION = next(
    line.split("=", 1)[1].strip()
    for line in (PLUGIN / "metadata.txt").read_text().splitlines()
    if line.startswith("version=")
)
DIST = ROOT / "dist"
# QGIS dérive l'id du plugin de file_name.partition(".")[0] : séparer la version par un point.
OUTPUT = DIST / f"farois_audit_rollback.{VERSION}.zip"
EXCLUDED = {
    ".env",
    ".env.secrets",
    ".env.local",
    "__pycache__",
    ".pytest_cache",
    ".git",
    "tests",
}


def allowed(path):
    return not any(
        part in EXCLUDED or part.endswith((".log", ".dump", ".sql", ".pyc", ".pyo"))
        for part in path.parts
    )


def main():
    DIST.mkdir(exist_ok=True)
    if OUTPUT.exists():
        OUTPUT.unlink()
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PLUGIN.rglob("*")):
            if path.is_file() and allowed(path.relative_to(PLUGIN)):
                archive.write(
                    path, Path("farois_audit_rollback") / path.relative_to(PLUGIN)
                )
    print(OUTPUT)


if __name__ == "__main__":
    main()
