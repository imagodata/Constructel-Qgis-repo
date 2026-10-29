"""Bridge 1.8 volet B2 — CA embarquees dans le paquet du plugin.

Le plugin ecrit ces deux certificats publics (non secrets) dans le root.crt
libpq du poste pour que sslmode=verify-full valide le serveur Farois
(CA Farois, spec §5.5) et un futur certificat emis par la PKI interne
Constructel (racine AD, constructelbe-ca.pem).
"""
import subprocess
from pathlib import Path

from constructel_bridge import bridge_nominatif as bn

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "constructel_bridge"
CERTS_DIR = PLUGIN_DIR / "certs"


def _subject(path):
    out = subprocess.run(
        ["openssl", "x509", "-in", str(path), "-noout", "-subject"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


def test_farois_db_ca_is_embedded_and_parses():
    path = CERTS_DIR / "farois-db-ca.crt"
    assert path.is_file()
    assert "Farois DB CA" in _subject(path)


def test_constructelbe_root_ca_is_embedded_and_parses():
    path = CERTS_DIR / "constructelbe-ca.pem"
    assert path.is_file()
    assert "CN" in _subject(path)


def test_embedded_ca_paths_lists_both_files_in_the_package():
    paths = bn.embedded_ca_paths(PLUGIN_DIR)
    assert [p.name for p in paths] == ["farois-db-ca.crt", "constructelbe-ca.pem"]
    assert all(p.is_file() for p in paths)


def test_embedded_cas_are_exactly_one_certificate_block_each():
    for path in bn.embedded_ca_paths(PLUGIN_DIR):
        blocks = bn.pem_blocks(path.read_text(encoding="utf-8"))
        assert len(blocks) == 1, path.name


def test_embedded_cas_upsert_into_root_crt_without_duplication():
    blocks = [p.read_text(encoding="utf-8") for p in bn.embedded_ca_paths(PLUGIN_DIR)]
    once = bn.upsert_root_crt_pem("", blocks)
    assert once.count("BEGIN CERTIFICATE") == 2
    assert bn.upsert_root_crt_pem(once, blocks) == once


def test_no_private_key_material_ships_in_certs_dir():
    for path in CERTS_DIR.iterdir():
        assert "PRIVATE KEY" not in path.read_text(encoding="utf-8", errors="replace"), path.name
