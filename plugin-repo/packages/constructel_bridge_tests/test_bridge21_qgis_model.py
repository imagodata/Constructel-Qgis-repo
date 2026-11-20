"""Bridge 2.1 — modele des projets QGIS (sections, noms, plan de partage), sans Qt."""
from __future__ import annotations

import datetime as dt

import pytest

from constructel_bridge import bridge_qgis_projects as qm


def row(name, **kw):
    base = dict(owner="ad", projet_id=None, projet_code=None, projet_label=None, share_project=False, published=False,
                owner_role="BE", version=1, updated_at="2026-11-19T10:00:00", updated_by="ad", is_owner=False,
                can_edit=False, share_count=None, description=None)
    base.update(kw)
    return qm.QgisProjectRow(name=name, **base)


def test_row_from_record_converts_types():
    rec = ("Vue", "ad", "a0b1", "GOFIBER", "GoFiber", True, False, "BE", 3,
           dt.datetime(2026, 11, 19, 10, 0, tzinfo=dt.timezone.utc), "ad", True, True, 2, "desc")
    r = qm.row_from_record(rec)
    assert r.name == "Vue" and r.projet_id == "a0b1" and r.version == 3 and r.share_count == 2
    assert r.updated_at.startswith("2026-11-19T10:00:00") and r.is_owner is True and r.description == "desc"
    r2 = qm.row_from_record(("X", "bo", None, None, None, None, None, None, 1, None, None, None, None, None, None))
    assert r2.projet_id is None and r2.updated_at is None and r2.is_owner is False and r2.published is False


def test_each_project_in_exactly_one_section():
    rows = [row("mien", is_owner=True, published=True), row("pub", published=True, projet_code="GOFIBER"), row("part", can_edit=True)]
    s = qm.build_sections(rows, {"GOFIBER": "WYRE"})
    assert [r.name for r in s.mine] == ["mien"] and [r.name for r in s.shared] == ["part"]
    assert [(code, op, [r.name for r in rs]) for code, op, rs in s.published] == [("GOFIBER", "WYRE", ["pub"])]


def test_section_of_priority():
    assert qm.section_of(row("a", is_owner=True, published=True)) == qm.SECTION_MINE
    assert qm.section_of(row("a", published=True)) == qm.SECTION_PUBLISHED
    assert qm.section_of(row("a")) == qm.SECTION_SHARED


def test_published_groups_sorted_by_projet_then_operator_unattached_last():
    rows = [row("x", published=True), row("y", published=True, projet_code="ZZ"), row("z", published=True, projet_code="AA")]
    assert [code for code, _op, _rows in qm.build_sections(rows, {}).published] == ["AA", "ZZ", None]


def test_rows_sorted_by_name_casefold():
    rows = [row("b", is_owner=True), row("A", is_owner=True), row("c", is_owner=True)]
    assert [r.name for r in qm.build_sections(rows, {}).mine] == ["A", "b", "c"]


@pytest.mark.parametrize("name,error", [("", "empty"), ("a" * 201, "too_long"), ("a\tb", "control"), (" a", "spaces"),
                                        ("a ", "spaces"), ("Vue/Ixelles & co #1", None), ("a" * 200, None)])
def test_name_error(name, error):
    assert qm.name_error(name) == error


def test_suggest_name_is_idempotent_and_fits():
    assert qm.suggest_name("Vue", "ad") == "Vue (ad)"
    assert qm.suggest_name("Vue (ad)", "ad") == "Vue (ad)"
    assert len(qm.suggest_name("a" * 200, "ad")) == 200 and qm.suggest_name("a" * 200, "ad").endswith(" (ad)")
    assert qm.name_error(qm.suggest_name("", "ad")) is None


def test_save_target_update_only_for_same_editable_name():
    opened = qm.OpenedQgisProject("Vue", 4, "uuid-g", "GOFIBER", False, True, {})
    assert qm.save_target("Vue", opened) == (4, "uuid-g")
    assert qm.save_target("Autre", opened) == (None, None)
    assert qm.save_target("Vue", qm.OpenedQgisProject("Vue", 4, None, None, False, False, {})) == (None, None)
    assert qm.save_target("Vue", None) == (None, None)


def test_build_metadata_keeps_foreign_keys_and_drops_server_ones():
    meta = qm.build_metadata("desc", "ad", "2026-11-19", "", {"qgis_version": "3.34", "last_modified_user": "x", "description": "old"})
    assert meta == {"qgis_version": "3.34", "description": "desc", "saved_by": "ad", "saved_at": "2026-11-19"}


def test_build_metadata_without_previous_and_with_source_file():
    meta = qm.build_metadata("", None, None, "C:/x/p.qgz", None)
    assert meta == {"description": "", "source_file": "C:/x/p.qgz"}


def test_share_plan_diff():
    current = [qm.ShareRow("a", None, None, False, True), qm.ShareRow("b", None, None, True, True), qm.ShareRow("c", None, None, False, False)]
    plan = qm.share_plan(current, {"a": True, "b": True, "d": False, "e": True}, removed=["c", "zz"],
                         share_project_before=False, share_project_after=True)
    assert plan == qm.SharePlan(True, ("c",), ("a", "e"), ("d",))
    assert qm.share_plan(current, {"a": False, "b": True}, [], True, True).is_empty()


def test_share_plan_removed_wins_over_wanted():
    current = [qm.ShareRow("a", None, None, False, True)]
    plan = qm.share_plan(current, {"a": True}, ["a"], False, False)
    assert plan == qm.SharePlan(None, ("a",), (), ())


def test_chunks_of_twenty():
    assert [len(c) for c in qm.chunks([str(i) for i in range(45)])] == [20, 20, 5]
    assert qm.chunks([]) == []


def test_eligible_caption():
    assert qm.EligibleUser("a.leroy", "Alice Leroy", "BE").caption() == "Alice Leroy (a.leroy) — BE"
    assert qm.EligibleUser("a.leroy", None, None).caption() == "a.leroy"
    assert qm.EligibleUser("a.leroy", None, "BE").caption() == "a.leroy — BE"


def test_contract_bounds():
    assert qm.ELIGIBLE_MIN_PREFIX == 3 and qm.MAX_SHARE_LOGINS == 20
    assert qm.ELIGIBLE_LIMIT <= qm.ELIGIBLE_MAX_LIMIT == 50 and qm.ELIGIBLE_MAX_PREFIX == 50
    assert qm.LOGIN_RE.match("a.leroy") and not qm.LOGIN_RE.match("A.Leroy")
