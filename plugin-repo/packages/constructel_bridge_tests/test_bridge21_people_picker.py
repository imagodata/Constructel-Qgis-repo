"""Bridge 2.1, tache 16 : selecteur de personnes avec autocompletion
(bridge_people_picker, doublures fakes_widgets)."""
from __future__ import annotations

import importlib
import sys

import pytest

from constructel_bridge.bridge_qgis_projects import EligibleUser
from constructel_bridge_tests.fakes_widgets import (
    _Button,
    _Combo,
    _Completer,
    _Edit,
    _Item,
    _ItemTree,
    _Label,
    _Layout,
    _StringModel,
    _Timer,
    _W,
)

MODULE = "constructel_bridge.bridge_people_picker"
ALICE = EligibleUser("a.leroy", "Alice Leroy", "BE")
BOB = EligibleUser("b.martin", "Bob Martin", "ADMIN")


@pytest.fixture
def pp(bp18, monkeypatch):
    from qgis.PyQt import QtCore, QtWidgets

    for name, fake in (("QWidget", _W), ("QLabel", _Label), ("QPushButton", _Button), ("QComboBox", _Combo),
                       ("QLineEdit", _Edit), ("QCompleter", _Completer), ("QTreeWidget", _ItemTree),
                       ("QTreeWidgetItem", _Item), ("QVBoxLayout", _Layout)):
        monkeypatch.setattr(QtWidgets, name, fake, raising=False)
    monkeypatch.setattr(QtCore, "QTimer", _Timer, raising=False)
    monkeypatch.setattr(QtCore, "QStringListModel", _StringModel, raising=False)
    monkeypatch.delitem(sys.modules, MODULE, raising=False)
    module = importlib.import_module(MODULE)
    yield module
    sys.modules.pop(MODULE, None)


def _picker(pp, answer=(ALICE, BOB), excluded=()):
    calls = []

    def search(prefix, exclude):
        calls.append((prefix, list(exclude)))
        return None if answer is None else list(answer)

    picker = pp.PeoplePicker(search, excluded=excluded)
    picker.calls = calls
    return picker


def _type(picker, text):
    picker.input.type(text)
    assert picker.timer.active                     # relance a chaque frappe
    picker.timer.timeout.emit()                    # echeance du minuteur


def test_no_search_under_three_characters(pp):
    picker = _picker(pp)
    _type(picker, " al ")
    assert picker.calls == [] and picker.help.text() == pp.tr("people.min_chars")
    assert picker.timer.interval == pp.DEBOUNCE_MS == 300


def test_search_after_debounce_with_exclusions(pp):
    picker = _picker(pp, excluded=("c.deja",))
    picker.choose(BOB)
    _type(picker, "ale")
    assert picker.calls == [("ale", ["c.deja", "b.martin"])]
    assert picker._model.strings == ["Alice Leroy (a.leroy) — BE"]     # deja choisi : jamais propose
    assert picker.completer.popups == 1 and picker.completer.mode == _Completer.CompletionMode.UnfilteredPopupCompletion


def test_search_error_shows_message(pp):
    picker = _picker(pp, answer=None)
    _type(picker, "ale")
    assert picker.help.text() == pp.tr("people.search_error") and picker._model.strings == []


def test_choose_adds_with_open_right_and_clears_input(pp):
    picker = _picker(pp)
    _type(picker, "ale")
    picker.completer.activated.emit("Alice Leroy (a.leroy) — BE")
    assert picker.chosen() == (("a.leroy", False),) and picker.input.text() == ""
    (item,) = picker.list.children
    combo = picker.list.itemWidget(item, 1)
    assert combo.currentData() is False and picker.list.itemWidget(item, 2).text() == pp.tr("people.remove")


def test_duplicate_choice_ignored(pp):
    picker = _picker(pp)
    picker.choose(ALICE)
    picker.choose(ALICE)
    assert picker.chosen() == (("a.leroy", False),)


def test_twenty_people_maximum_disables_input(pp):
    picker = _picker(pp)
    for i in range(20):
        picker.choose(EligibleUser(f"u{i:02d}", None, None))
    assert len(picker.chosen()) == 20 and not picker.input.isEnabled()
    assert picker.help.text() == pp.tr("people.max_reached", count=20)
    picker.choose(EligibleUser("u99", None, None))
    assert len(picker.chosen()) == 20
    picker.remove("u00")
    assert picker.input.isEnabled() and picker.help.text() == ""


def test_set_right_and_remove(pp):
    picker = _picker(pp)
    changes = []
    picker.on_change = lambda: changes.append(1)
    picker.choose(ALICE)
    picker.choose(BOB)
    combo = picker.list.itemWidget(picker.list.children[0], 1)
    combo.setCurrentIndex(1)
    assert picker.chosen() == (("a.leroy", True), ("b.martin", False))
    picker.list.itemWidget(picker.list.children[1], 2).clicked.emit()
    assert picker.chosen() == (("a.leroy", True),)
    assert picker.list.itemWidget(picker.list.children[0], 1).currentData() is True    # droit garde apres reconstruction
    picker.clear()
    assert picker.chosen() == () and len(changes) == 5


def test_set_excluded(pp):
    picker = _picker(pp)
    picker.set_excluded(["x.y"])
    _type(picker, "bob")
    assert picker.calls[-1] == ("bob", ["x.y"])
