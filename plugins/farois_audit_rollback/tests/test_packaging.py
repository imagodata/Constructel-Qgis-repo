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
    assert module.VERSION == "0.2.5"
    assert module.OUTPUT.name == "farois_audit_rollback.0.2.5.zip"
    assert module.OUTPUT.name.partition(".")[0] == "farois_audit_rollback"


def test_readme_warns_that_remember_me_can_trigger_the_qgis_master_password():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    section = readme.split("Version 0.2.1 :")[0]
    assert "« Se souvenir de moi (30 jours) », cochée par défaut" in section
    assert "mot de passe maître" in section and "en faire créer un" in section
    assert "relu à l'ouverture du panneau" in section
