"""Bridge 2.1 — controle du code embarque a l'enregistrement d'un projet QGIS
et neutralisation a l'ouverture (module sans Qt `bridge_project_safety`).

Regles portees de farois/qgis/project_store.py (scan_qgs, _action_finding,
inspect_archive, _parse_qgs)."""
from __future__ import annotations

import io
import zipfile
import xml.etree.ElementTree as ET

import pytest

from constructel_bridge import bridge_project_safety as ps


def qgs(body="", props="", attrs='saveUser="ad" saveDateTime="2026-11-19T10:00:00"'):
    return (f'<!DOCTYPE qgis PUBLIC "http://mrcc.com/qgis.dtd" "SYSTEM"><qgis version="3.34" {attrs}>'
            f"<properties>{props}</properties><projectlayers>{body}</projectlayers></qgis>")


def layer(name="Points", extra=""):
    return (f"<maplayer><id>l1</id><layername>{name}</layername><datasource>dbname='farois_ftth' host=db "
            f"authcfg=abc table=\"projet\".\"t\"</datasource>{extra}</maplayer>")


def qgz(xml, extra=()):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("p.qgs", xml)
        for name in extra:
            zf.writestr(name, "print(1)")
    return buf.getvalue()


def kinds(content):
    return [f.kind for f in ps.inspect_qgz(content).findings]


# ---------------------------------------------------------------- Task 1

def test_clean_project_has_no_finding_and_reads_save_attributes():
    report = ps.inspect_qgz(qgz(qgs(layer())))
    assert report.findings == () and report.qgs_name == "p.qgs"
    assert report.saved_by == "ad" and report.saved_at == "2026-11-19T10:00:00"


def test_save_user_full_wins_over_save_user():
    attrs = 'saveUser="ad" saveUserFull="Alice Dupont" saveDateTime="2026-11-19T10:00:00"'
    assert ps.inspect_qgz(qgz(qgs(attrs=attrs))).saved_by == "Alice Dupont"


def test_macros_and_expression_functions_are_refused():
    props = ("<Macros><pythonCode>import os</pythonCode></Macros>"
             "<ExpressionFunctions><pythonCode>def f(): pass</pythonCode></ExpressionFunctions>")
    assert kinds(qgz(qgs(props=props))) == ["macros", "expression_functions"]


def test_empty_macro_is_not_a_finding():
    assert kinds(qgz(qgs(props="<Macros><pythonCode>  </pythonCode></Macros>"))) == []


@pytest.mark.parametrize("action_type,refused", [(0, True), (1, True), (4, True), (5, False), (7, False), ("x", True)])
def test_layer_actions_by_type(action_type, refused):
    action = f'<attributeactions><actionsetting type="{action_type}" name="Go" action="do()"/></attributeactions>'
    found = ps.inspect_qgz(qgz(qgs(layer(extra=action)))).findings
    assert (found and found[0].kind == "action" and found[0].layer == "Points") if refused else not found


def test_action_detail_names_the_action():
    action = '<attributeactions><actionsetting type="1" name="Go" action="do()"/></attributeactions>'
    (finding,) = ps.inspect_qgz(qgz(qgs(layer(extra=action)))).findings
    assert "Go" in finding.detail and "1" in finding.detail


def test_action_outside_any_layer_is_refused_without_layer():
    xml = qgs().replace("</qgis>", '<x><actionsetting type="1" name="Go" action="do()"/></x></qgis>')
    (finding,) = ps.inspect_qgz(qgz(xml)).findings
    assert finding.kind == "action" and finding.layer == ""


def test_action_with_empty_command_is_ignored():
    action = '<attributeactions><actionsetting type="1" name="Go" action=""/></attributeactions>'
    assert kinds(qgz(qgs(layer(extra=action)))) == []


def test_form_init_code_only_with_a_source():
    with_source = ("<editforminit>run</editforminit><editforminitcodesource>2</editforminitcodesource>"
                   "<editforminitcode>def run(): pass</editforminitcode>")
    no_source = "<editforminit>run</editforminit><editforminitcodesource>0</editforminitcodesource>"
    assert kinds(qgz(qgs(layer(extra=with_source)))) == ["form_init"]
    assert kinds(qgz(qgs(layer(extra=no_source)))) == []


def test_clear_text_password_in_a_datasource():
    xml = qgs(layer().replace("authcfg=abc", "password='s3cret'"))
    assert kinds(qgz(xml)) == ["password"]


def test_python_file_in_archive():
    found = ps.inspect_qgz(qgz(qgs(), extra=("macros/init.py",))).findings
    assert [(f.kind, f.detail) for f in found] == [("python_file", "macros/init.py")]


@pytest.mark.parametrize("content", [b"", b"not a zip", qgz("<notqgis/>"), qgz('<!DOCTYPE x [<!ENTITY a "b">]><qgis/>')])
def test_unreadable_archives_raise(content):
    with pytest.raises(ps.ProjectFileError):
        ps.inspect_qgz(content)


def test_archive_without_qgs_raises():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("readme.txt", "x")
    with pytest.raises(ps.ProjectFileError):
        ps.inspect_qgz(buf.getvalue())
