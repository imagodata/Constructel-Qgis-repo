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
    module.OUTPUT = tmp_path / f"farois_audit_rollback.{module.VERSION}.zip"
    module.main()
    with ZipFile(module.OUTPUT) as archive:
        names = archive.namelist()
        assert "farois_audit_rollback/plugin.py" in names
        assert all(n.startswith("farois_audit_rollback/") for n in names)
        assert all("__pycache__" not in n and ".env" not in n for n in names)


SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "package_farois_audit_rollback.py"


def test_zip_name_lets_qgis_derive_the_plugin_id():
    spec = importlib.util.spec_from_file_location("_package_script_name", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.VERSION == "0.2.2"
    assert module.OUTPUT.name == "farois_audit_rollback.0.2.2.zip"
    assert module.OUTPUT.name.partition(".")[0] == "farois_audit_rollback"
