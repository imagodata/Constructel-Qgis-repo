import configparser
import importlib.util
from pathlib import Path
import shutil
import zipfile


ROOT = Path(__file__).resolve().parents[2]
NAME = "asbuilt_depth_geocoder"


def test_package_asbuilt_sans_qml_ni_cache(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "package_asbuilt", ROOT / "package_collection.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    shutil.copy(ROOT / "metadata.ini", tmp_path / "metadata.ini")
    collection = tmp_path / "collections" / NAME
    shutil.copytree(ROOT / "collections" / NAME, collection)
    (collection / ".env").write_text("synthetic test fixture", encoding="utf-8")
    (collection / "__pycache__").mkdir(exist_ok=True)
    (collection / "__pycache__/test.pyc").write_bytes(b"synthetic")
    (collection / "style").mkdir(exist_ok=True)
    (collection / "style/stale.qml").write_text("<qgis/>", encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    module.main(NAME)
    with zipfile.ZipFile(tmp_path / "collections" / f"{NAME}.zip") as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            "processing/geocode_asbuilt_depth.py",
            "README.txt",
        }
        assert b"STYLES_FROM_FAROIS_MESSAGE" in archive.read(
            "processing/geocode_asbuilt_depth.py"
        )
    metadata = configparser.ConfigParser(interpolation=None)
    metadata.read(tmp_path / "metadata.ini", encoding="utf-8")
    assert metadata[NAME]["version"] == "1.3.0"


def test_package_collection_inconnue(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "package_unknown", ROOT / "package_collection.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        module.main("collection_inexistante")
    except SystemExit as exc:
        assert "unknown collection" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("SystemExit attendu")
