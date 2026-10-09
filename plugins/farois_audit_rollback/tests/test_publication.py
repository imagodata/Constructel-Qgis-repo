"""Repository publication preserves other plugins and refuses version collisions."""

import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import pytest


@pytest.fixture
def publication(tmp_path):
    script = (
        Path(__file__).resolve().parents[3] / "scripts/publish_farois_audit_rollback.py"
    )
    if not script.exists():
        pytest.skip("Publication script lives outside the installable plugin.")
    spec = importlib.util.spec_from_file_location("farois_publisher", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "repository"
    root.mkdir()
    xml = '<?xml version="1.0"?><plugins><pyqgis_plugin name="Existing" version="1"><description><![CDATA[Keep <styles>]]></description><file_name>existing.zip</file_name></pyqgis_plugin></plugins>'
    (root / "plugins.xml").write_text(xml)
    package = tmp_path / "source.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "farois_audit_rollback/metadata.txt",
            "[general]\nname=Farois\nversion=0.1.6\nicon=farois-logo.png\nexperimental=True\n",
        )
        archive.writestr("farois_audit_rollback/farois-logo.png", b"fixture-icon")
    return module, root, package, xml


def test_publication_keeps_old_entries_and_serves_icon(publication):
    module, root, package, xml = publication
    url = module.publish(package, root, "http://fixture-repository")
    current = (root / "plugins.xml").read_text()
    assert xml.replace("</plugins>", "") in current
    nodes = ET.fromstring(current)
    assert len(nodes) == 2
    assert (
        nodes[1].findtext("icon")
        == "http://fixture-repository/plugin-repo/icons/farois_audit_rollback_0.1.6.png"
    )
    assert url.endswith("/plugin-repo/packages/farois_audit_rollback_0.1.6.zip")
    assert (root / "plugins.xml.before-farois_audit_rollback-0.1.6").read_text() == xml
    assert (
        root / "icons/farois_audit_rollback_0.1.6.png"
    ).read_bytes() == b"fixture-icon"


def test_publication_is_idempotent(publication):
    module, root, package, _ = publication
    module.publish(package, root, "http://fixture-repository")
    current = (root / "plugins.xml").read_bytes()
    module.publish(package, root, "http://fixture-repository")
    assert (root / "plugins.xml").read_bytes() == current


def test_dry_run_does_not_publish(publication):
    module, root, package, xml = publication
    module.publish(package, root, "http://fixture-repository", dry_run=True)
    assert (root / "plugins.xml").read_text() == xml
    assert not (root / "packages").exists()


def test_different_package_same_version_is_refused(publication):
    module, root, package, _ = publication
    module.publish(package, root, "http://fixture-repository")
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr("farois_audit_rollback/extra.py", "# fixture")
    with pytest.raises(ValueError, match="ZIP différent"):
        module.publish(package, root, "http://fixture-repository")


def test_invalid_archive_root_refused(publication):
    module, root, package, _ = publication
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr("another-plugin/file.py", "# fixture")
    with pytest.raises(ValueError, match="uniquement"):
        module.publish(package, root, "http://fixture-repository")
