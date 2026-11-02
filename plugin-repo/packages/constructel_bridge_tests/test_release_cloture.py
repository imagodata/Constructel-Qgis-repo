"""Cloture 1.8.x (AC12) : release.py --cloture produit un zip sans
identifiant partage et le controle. Aucun QGIS requis."""
import base64
import json
import zipfile

import pytest

from constructel_bridge import release

PW_WYRE = "wyre-shared-pw"
PW_BE = "be-shared-pw"


def _b64(text):
    return base64.b64encode(text.encode()).decode()


RAW = {
    "wyre": {"host": "10.0.0.1", "port": 5432, "dbname": "d", "user": "ftth_editor",
             "password": _b64(PW_WYRE), "sslmode": "require", "srid": 31370},
    "be": {"host": "10.0.0.1", "port": 5432, "dbname": "d", "user": "bureau_etudes",
           "password": _b64(PW_BE)},
}


def test_strip_removes_user_and_password_only_and_leaves_input_untouched():
    clean = release.strip_shared_credentials(RAW)
    assert clean["wyre"] == {"host": "10.0.0.1", "port": 5432, "dbname": "d",
                             "sslmode": "require", "srid": 31370}
    assert clean["be"] == {"host": "10.0.0.1", "port": 5432, "dbname": "d"}
    assert RAW["wyre"]["password"] == _b64(PW_WYRE)


def test_strip_handles_the_flat_pre_1_5_format():
    flat = {"host": "h", "dbname": "d", "user": "u", "password": _b64("x")}
    assert release.strip_shared_credentials(flat) == {"host": "h", "dbname": "d"}


def test_shared_secrets_lists_encoded_and_decoded_passwords():
    assert set(release.shared_secrets(RAW)) == {
        _b64(PW_WYRE), PW_WYRE, _b64(PW_BE), PW_BE}


def _zip_with(tmp_path, creds, extra=None):
    path = tmp_path / "b.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("constructel_bridge/credentials.json", json.dumps(creds))
        for name, data in (extra or {}).items():
            zf.writestr(f"constructel_bridge/{name}", data)
    return path


def test_verify_accepts_a_clean_zip(tmp_path):
    release.verify_cloture_zip(_zip_with(tmp_path, release.strip_shared_credentials(RAW)),
                               release.shared_secrets(RAW))


def test_verify_rejects_user_or_password_left_in_credentials(tmp_path):
    with pytest.raises(AssertionError, match="credentials.json"):
        release.verify_cloture_zip(_zip_with(tmp_path, RAW), release.shared_secrets(RAW))


def test_verify_rejects_a_secret_hidden_in_another_entry(tmp_path):
    clean = release.strip_shared_credentials(RAW)
    zp = _zip_with(tmp_path, clean, extra={"notes.txt": f"pw={PW_BE}"})
    with pytest.raises(AssertionError, match="notes.txt"):
        release.verify_cloture_zip(zp, release.shared_secrets(RAW))


def test_rebuild_zip_cloture_strips_the_zip_but_not_the_disk_file(tmp_path, monkeypatch):
    plugin_dir = tmp_path / "constructel_bridge"
    plugin_dir.mkdir()
    (plugin_dir / "metadata.txt").write_text("version=1.8.1\n")
    creds_file = plugin_dir / "credentials.json"
    creds_file.write_text(json.dumps(RAW))
    monkeypatch.setattr(release, "PLUGIN_DIR", plugin_dir)
    monkeypatch.setattr(release, "PLUGIN_NAME", "constructel_bridge")
    monkeypatch.setattr(release, "ZIP_PATH", tmp_path / "constructel_bridge.zip")

    release.rebuild_zip(cloture=True)

    with zipfile.ZipFile(tmp_path / "constructel_bridge.zip") as zf:
        in_zip = json.loads(zf.read("constructel_bridge/credentials.json"))
    assert "password" not in in_zip["wyre"] and "user" not in in_zip["be"]
    assert json.loads(creds_file.read_text()) == RAW  # disque intact (rollback possible)


def test_rebuild_zip_without_cloture_keeps_credentials_as_is(tmp_path, monkeypatch):
    plugin_dir = tmp_path / "constructel_bridge"
    plugin_dir.mkdir()
    (plugin_dir / "credentials.json").write_text(json.dumps(RAW))
    monkeypatch.setattr(release, "PLUGIN_DIR", plugin_dir)
    monkeypatch.setattr(release, "PLUGIN_NAME", "constructel_bridge")
    monkeypatch.setattr(release, "ZIP_PATH", tmp_path / "constructel_bridge.zip")

    release.rebuild_zip()

    with zipfile.ZipFile(tmp_path / "constructel_bridge.zip") as zf:
        assert json.loads(zf.read("constructel_bridge/credentials.json")) == RAW
