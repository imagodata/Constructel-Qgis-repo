import importlib.util
from pathlib import Path
from zipfile import ZipFile


def test_zip_has_plugin_root_and_no_caches_or_secrets(tmp_path, capsys):
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(
        "farois_packager", root / "scripts/package_farois_audit_rollback.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.DIST = tmp_path
    module.OUTPUT = tmp_path / f"farois_audit_rollback_{module.VERSION}.zip"
    module.main()
    with ZipFile(module.OUTPUT) as archive:
        names = archive.namelist()
        assert "farois_audit_rollback/plugin.py" in names
        assert all(n.startswith("farois_audit_rollback/") for n in names)
        assert all("__pycache__" not in n and ".env" not in n for n in names)
