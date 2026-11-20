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


# ---------------------------------------------------------------- Task 2

def test_nothing_to_neutralize_returns_the_same_text():
    xml = qgs(layer())
    result = ps.neutralize_qgs_xml(xml)
    assert result.xml is xml and result.removed == ()


def test_everything_embedded_is_neutralized_and_reported():
    props = ("<Macros><pythonCode>import os</pythonCode></Macros>"
             "<ExpressionFunctions><pythonCode>def f(): pass</pythonCode></ExpressionFunctions>")
    extra = ('<attributeactions><actionsetting type="1" name="Py" action="x()"/>'
             '<actionsetting type="5" name="Url" action="http://a"/></attributeactions>'
             "<editforminit>run</editforminit><editforminitcodesource>2</editforminitcodesource>"
             "<editforminitcode>def run(): pass</editforminitcode>")
    xml = qgs(layer(extra=extra).replace("authcfg=abc", "password='s3cret'"), props=props)
    result = ps.neutralize_qgs_xml(xml)
    assert sorted(f.kind for f in result.removed) == ["action", "expression_functions", "form_init", "macros", "password"]
    assert ps.scan_qgs(ET.fromstring(result.xml.split("\n", 2)[2])) == []
    assert 'name="Url"' in result.xml and "s3cret" not in result.xml
    assert result.xml.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE qgis')


def test_form_init_is_reset_to_no_source():
    extra = ("<editforminit>run</editforminit><editforminitcodesource>1</editforminitcodesource>"
             "<editforminitfilepath>C:/x/init.py</editforminitfilepath>")
    root = ET.fromstring(ps.neutralize_qgs_xml(qgs(layer(extra=extra))).xml.split("\n", 2)[2])
    ml = root.find(".//maplayer")
    assert ml.findtext("editforminitcodesource") == "0"
    assert not ml.findtext("editforminit") and not ml.findtext("editforminitfilepath")


def test_password_in_layer_tree_source_attribute_is_stripped_too():
    xml = qgs(layer()).replace("</qgis>", '<layer-tree-group><layer-tree-layer id="l1" source="dbname=x password=abc"/></layer-tree-group></qgis>')
    result = ps.neutralize_qgs_xml(xml)
    assert "abc" not in result.xml.split("</projectlayers>")[1]
    assert [f.kind for f in result.removed] == ["password"]


@pytest.mark.parametrize("source,expected", [
    ("dbname='x' password='a b' user=u", "dbname='x' user=u"),
    ("dbname=x password=abc", "dbname=x"),
    ("contextualWMSLegend=0&password=abc&url=https://w", "contextualWMSLegend=0&url=https://w"),
    ("password=abc&url=https://w", "url=https://w"),
    ("dbname=x authcfg=abc", "dbname=x authcfg=abc"),
])
def test_strip_datasource_password(source, expected):
    assert ps.strip_datasource_password(source) == expected


def test_entity_declaration_refuses_to_open():
    with pytest.raises(ps.ProjectFileError):
        ps.neutralize_qgs_xml('<!DOCTYPE qgis [<!ENTITY a "b">]><qgis>&a;</qgis>')


@pytest.mark.parametrize("xml", ["<qgis>", "<notqgis/>", ""])
def test_unreadable_xml_refuses_to_open(xml):
    with pytest.raises(ps.ProjectFileError):
        ps.neutralize_qgs_xml(xml)



# ---------------------------------------------------------------- revue 2.1 : ecarts ElementTree / QDom

def test_default_namespace_on_a_child_is_refused():
    # C1 : ET renomme en {urn:x}maplayer (invisible aux recherches), QDom lit maplayer.
    action = '<attributeactions><actionsetting type="1" name="p" action="import os"/></attributeactions>'
    xml = qgs(layer(extra=action)).replace("<maplayer>", '<maplayer xmlns="urn:x">')
    with pytest.raises(ps.ProjectFileError):
        ps.neutralize_qgs_xml(xml)
    with pytest.raises(ps.ProjectFileError):
        ps.inspect_qgz(qgz(xml))
    with pytest.raises(ps.ProjectFileError):
        ps.neutralize_qgs_xml(qgs(props='<Macros xmlns="urn:x"><pythonCode>import os</pythonCode></Macros>'))


def test_text_after_a_child_element_is_seen_and_removed():
    # H1 : QDomElement::text() concatene tout le texte des descendants.
    props = '<Macros><pythonCode type="QString"><x/>import os</pythonCode></Macros>'
    form = ("<editforminit><x/>f</editforminit><editforminitcodesource><x/>2</editforminitcodesource>"
            "<editforminitcode><x/>def f(d, l, x): pass</editforminitcode>")
    xml = qgs(layer(extra=form), props=props)
    assert sorted(f.kind for f in ps.scan_qgs(ET.fromstring(xml.split(">", 1)[1]))) == ["form_init", "macros"]
    result = ps.neutralize_qgs_xml(xml)
    assert "import os" not in result.xml and "def f" not in result.xml


def test_form_init_code_of_an_alternative_style_is_neutralized():
    # M1 : style alternatif (map-layer-style-manager).
    style = ('<map-layer-style-manager><map-layer-style name="evil"><qgis><editforminit>f</editforminit>'
             "<editforminitcodesource>2</editforminitcodesource><editforminitcode>import os</editforminitcode>"
             "</qgis></map-layer-style></map-layer-style-manager>")
    xml = qgs(layer(extra=style))
    assert [(f.kind, f.layer) for f in ps.inspect_qgz(qgz(xml)).findings] == [("form_init", "Points")]
    assert "import os" not in ps.neutralize_qgs_xml(xml).xml


def test_internal_dtd_subset_is_refused():
    # M2 : valeur par defaut d'attribut appliquee par expat, pas par QDom.
    xml = '<!DOCTYPE qgis [<!ATTLIST actionsetting type CDATA "5">]>' + qgs(layer()).split(">", 1)[1]
    with pytest.raises(ps.ProjectFileError):
        ps.neutralize_qgs_xml(xml)


@pytest.mark.parametrize("raw", ["５", "٥", " 5x", "+5"])
def test_non_ascii_or_odd_action_type_is_refused(raw):
    # M3 : int("５") vaut 5 en Python, QString::toInt echoue (0 = Generic).
    action = f'<attributeactions><actionsetting type="{raw}" name="a" action="calc.exe"/></attributeactions>'
    assert [f.kind for f in ps.neutralize_qgs_xml(qgs(layer(extra=action))).removed] == ["action"]


def test_embedded_layer_from_another_project_is_refused():
    # M6 : QGIS lirait le fichier reference sans neutralisation (et UNC -> SMB).
    xml = qgs('<maplayer embedded="1" project="\\\\hote\\p\\evil.qgs" id="l2"/>')
    with pytest.raises(ps.ProjectFileError):
        ps.neutralize_qgs_xml(xml)
    assert [f.kind for f in ps.inspect_qgz(qgz(xml)).findings] == ["embedded_project"]


def test_dotted_init_function_without_source_is_neutralized():
    # L1 : « module.fn » sans source -> « from module import fn » (QGIS < 2.12).
    form = "<editforminit>evil.run</editforminit><editforminitcodesource>0</editforminitcodesource>"
    result = ps.neutralize_qgs_xml(qgs(layer(extra=form)))
    assert [f.kind for f in result.removed] == ["form_init"] and "evil.run" not in result.xml


def test_corrupt_deflate_stream_is_a_project_file_error():
    # L2 : zlib.error intercepte.
    content = bytearray(qgz(qgs(layer() * 50)))
    start = content.index(b"PK\x03\x04") + 30 + len(b"p.qgs")
    for i in range(start, start + 40):
        content[i] ^= 0xFF
    with pytest.raises(ps.ProjectFileError):
        ps.inspect_qgz(bytes(content))
