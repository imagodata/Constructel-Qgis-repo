from plugins.farois_audit_rollback.gui.change_details import (
    change_rows,
    columns_label,
    summary_text,
)
from plugins.farois_audit_rollback.gui.history_model import HistoryEntry


def entry(**overrides):
    data = dict(change_id="1", operation="UPDATE")
    data.update(overrides)
    return HistoryEntry(**data)


UPDATE = entry(
    changed_columns=("label", "status"),
    before={"label": "a0", "status": "TODO", "other": 1},
    after={"label": "w1", "status": "DONE", "other": 1},
)


def test_columns_label_update_keeps_changed_columns():
    assert columns_label(UPDATE) == "label, status"


def test_columns_label_insert_and_delete_without_columns():
    assert columns_label(entry(operation="INSERT")) == "création"
    assert columns_label(entry(operation="DELETE")) == "suppression"


def test_columns_label_insert_with_columns_lists_them():
    assert columns_label(entry(operation="INSERT", changed_columns=("a",))) == "a"


def test_summary_update_two_fields():
    assert summary_text(UPDATE) == "label : a0 → w1 ; status : TODO → DONE"


def test_summary_insert_non_null_without_geometry_and_technical_columns():
    e = entry(
        operation="INSERT",
        before=None,
        after={
            "id": 5,
            "created_at": "x",
            "updated_at": "y",
            "geom": "SRID=31370;POINT(1 2)",
            "label": "n1",
            "note": None,
            "qty": 3,
        },
    )
    assert summary_text(e) == "label : n1 ; qty : 3"


def test_summary_delete_uses_before():
    e = entry(operation="DELETE", before={"label": "n1", "x": None}, after=None)
    assert summary_text(e) == "label : n1"


def test_summary_update_geometry_and_none():
    e = entry(
        changed_columns=("geom", "note"),
        before={"geom": "SRID=1;POINT(0 0)", "note": None},
        after={"geom": "SRID=1;POINT(1 1)", "note": "ok"},
    )
    assert summary_text(e) == "geom : géométrie modifiée ; note : ∅ → ok"


def test_geometry_detected_by_geojson_string():
    e = entry(
        changed_columns=("shape",),
        before={"shape": '{"type": "Point"}'},
        after={"shape": '{"type":"Point"}'},
    )
    assert "géométrie modifiée" in summary_text(e)


def test_value_truncated_to_40_chars():
    e = entry(changed_columns=("c",), before={"c": "x" * 50}, after={"c": "y"})
    assert summary_text(e) == "c : " + "x" * 40 + "… → y"


def test_cell_truncated_to_200_and_full_text_kept_for_tooltip():
    cols = tuple(f"c{i}" for i in range(30))
    e = entry(
        changed_columns=cols,
        before={c: "a" for c in cols},
        after={c: "b" for c in cols},
    )
    cell = summary_text(e)
    assert len(cell) == 201 and cell.endswith("…")
    full = summary_text(e, full=True)
    assert full.count("\n") == 29 and "…" not in full
    assert full.splitlines()[0] == "c0 : a → b"


def test_full_text_has_no_value_truncation():
    e = entry(changed_columns=("c",), before={"c": "x" * 50}, after={"c": "y"})
    assert summary_text(e, full=True) == "c : " + "x" * 50 + " → y"


def test_summary_empty_when_no_values():
    assert summary_text(entry(operation="INSERT")) == ""
    assert summary_text(entry(changed_columns=())) == ""


def test_change_rows_update_default_only_changed():
    assert change_rows(UPDATE) == [
        ("label", "a0", "w1"),
        ("status", "TODO", "DONE"),
    ]


def test_change_rows_all_fields():
    rows = change_rows(UPDATE, all_fields=True)
    assert ("other", "1", "1") in rows and len(rows) == 3


def test_change_rows_insert_and_delete():
    ins = entry(operation="INSERT", after={"a": 1, "b": None, "geom": "SRID=1;P"})
    assert change_rows(ins) == [("a", "∅", "1"), ("geom", "∅", "géométrie")]
    assert ("b", "∅", "∅") in change_rows(ins, all_fields=True)
    dele = entry(operation="DELETE", before={"a": 1, "b": None})
    assert change_rows(dele) == [("a", "1", "∅")]


def test_change_rows_update_geometry():
    e = entry(
        changed_columns=("geom",),
        before={"geom": "SRID=1;P"},
        after={"geom": "SRID=1;Q"},
    )
    assert change_rows(e) == [("geom", "géométrie modifiée", "géométrie modifiée")]


def test_change_rows_full_values_not_truncated():
    e = entry(changed_columns=("c",), before={"c": "x" * 50}, after={"c": "y"})
    assert change_rows(e) == [("c", "x" * 50, "y")]


def test_non_dict_values_are_tolerated():
    e = entry(changed_columns=("a",), before=None, after=None)
    assert summary_text(e) == "a : ∅ → ∅"
    assert change_rows(e) == [("a", "∅", "∅")]
