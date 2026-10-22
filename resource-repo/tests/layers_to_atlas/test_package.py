import configparser
import importlib.util
from pathlib import Path
import shutil
import zipfile


ROOT = Path(__file__).resolve().parents[2]


def test_package_allowlist_excludes_caches_and_secrets(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "package_atlas", ROOT / "package_collection.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    shutil.copy(ROOT / "metadata.ini", tmp_path / "metadata.ini")
    collection = tmp_path / "collections/layers_to_atlas"
    shutil.copytree(ROOT / "collections/layers_to_atlas", collection)
    (collection / ".env").write_text("synthetic test fixture", encoding="utf-8")
    (collection / "__pycache__").mkdir(exist_ok=True)
    (collection / "__pycache__/test.pyc").write_bytes(b"synthetic")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "COLLECTION", collection)
    module.main()
    with zipfile.ZipFile(tmp_path / "collections/layers_to_atlas.zip") as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            "processing/layers_to_atlas.py",
            "svg/constructel.svg",
            "README.txt",
        }
        assert b'SCRIPT_VERSION = "1.1.0"' in archive.read(
            "processing/layers_to_atlas.py"
        )
    metadata = configparser.ConfigParser(interpolation=None)
    metadata.read(tmp_path / "metadata.ini", encoding="utf-8")
    assert metadata["layers_to_atlas"]["version"] == "1.1.0"
