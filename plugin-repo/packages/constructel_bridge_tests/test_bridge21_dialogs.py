"""Bridge 2.1, taches 17-18 : dialogues des projets QGIS (enregistrer,
conflit, partager, supprimer) sur les doublures fakes_widgets."""
from __future__ import annotations

import importlib
import sys

import pytest

from constructel_bridge import bridge_home_model as hm
from constructel_bridge import bridge_projets as pj
from constructel_bridge import bridge_qgis_store as store
from constructel_bridge.bridge_project_safety import Finding
from constructel_bridge.bridge_qgis_projects import EligibleUser, OpenedQgisProject
from constructel_bridge_tests.fakes_widgets import (
    _Button,
    _CheckBox,
    _Combo,
    _Completer,
    _Dialog,
    _Edit,
    _GroupBox,
    _Item,
    _ItemTree,
    _Label,
    _Layout,
    _StringModel,
    _Timer,
    _W,
)

MODULE = "constructel_bridge.bridge_qgis_dialogs"
FULL = pj.ProjetCapabilities(True, True, True, True, True, True, True)
LAYER = (pj.ProjetLayer("t", "T", None, "default", None, 0),)
GOFIBER = pj.ProjetInfo("uuid-g", "GOFIBER", "GoFiber", "WYRE", LAYER)
ORFEO = pj.ProjetInfo("uuid-o", "ORFEO", "Orfeo", None, LAYER)
STATE = hm.CurrentProjectState("Ixelles", 3, "jdoe")
ALICE = EligibleUser("a.leroy", "Alice Leroy", "BE")


@pytest.fixture
def dlg(bp18, monkeypatch):
    from qgis.PyQt import QtCore, QtWidgets

    for name, fake in (("QWidget", _W), ("QDialog", _Dialog), ("QLabel", _Label), ("QPushButton", _Button),
                       ("QComboBox", _Combo), ("QLineEdit", _Edit), ("QCompleter", _Completer),
                       ("QTreeWidget", _ItemTree), ("QTreeWidgetItem", _Item), ("QVBoxLayout", _Layout),
                       ("QHBoxLayout", _Layout), ("QGroupBox", _GroupBox), ("QRadioButton", _CheckBox),
                       ("QCheckBox", _CheckBox)):
        monkeypatch.setattr(QtWidgets, name, fake, raising=False)
    monkeypatch.setattr(QtCore, "QTimer", _Timer, raising=False)
    monkeypatch.setattr(QtCore, "QStringListModel", _StringModel, raising=False)
    for name in ("bridge_people_picker", "bridge_qgis_dialogs"):
        monkeypatch.delitem(sys.modules, f"constructel_bridge.{name}", raising=False)
    module = importlib.import_module(MODULE)
    yield module
    for name in ("bridge_people_picker", "bridge_qgis_dialogs"):
        sys.modules.pop(f"constructel_bridge.{name}", None)


def _save_dialog(dlg, opened=None, state=STATE, caps=FULL, projets=(GOFIBER, ORFEO)):
    searches = []

    def search(code, prefix, exclude):
        searches.append((code, prefix, list(exclude)))
        return [ALICE]

    dialog = dlg.SaveDialog(projets, opened, state, caps, search)
    dialog.searches = searches
    return dialog


def test_dialog_carries_the_home_style_and_fits_1366x768(dlg):
    dialog = _save_dialog(dlg)
    assert dialog.size == (560, 520) and dialog.title == dlg.tr("save.title")
    assert dlg.fitted_size(dialog, (560, 520)) == (560, 520)


def test_prefill_editable_opened_project_locks_projet_and_hides_visibility(dlg):
    opened = OpenedQgisProject("Vue", 4, "uuid-g", "GOFIBER", False, True, {"description": "ma vue"})
    dialog = _save_dialog(dlg, opened=opened)
    assert dialog.name_edit.text() == "Vue" and dialog.description_edit.text() == "ma vue"
    assert dialog.selected_projet() == GOFIBER and not dialog.projet_combo.isEnabled()
    assert not dialog.visibility_box.isVisible() and dialog.visibility_note.isVisible()
    assert dialog.is_update()
    dialog.name_edit.setText("Autre vue")           # autre nom : creation, visibilite de retour
    assert dialog.projet_combo.isEnabled() and dialog.visibility_box.isVisible() and not dialog.is_update()


def test_prefill_read_only_opened_project_suggests_login_suffix(dlg):
    opened = OpenedQgisProject("Vue", 4, None, None, False, False, {})
    dialog = _save_dialog(dlg, opened=opened, state=hm.CurrentProjectState("Vue", 3, "jdoe"))
    assert dialog.name_edit.text() == "Vue (jdoe)" and not dialog.is_update()


def test_prefill_without_opened_project_uses_title(dlg):
    assert _save_dialog(dlg).name_edit.text() == "Ixelles"
    assert _save_dialog(dlg, state=hm.CurrentProjectState("", 3, "jdoe")).name_edit.text() == ""


def test_projet_members_needs_a_projet_and_capability(dlg):
    dialog = _save_dialog(dlg)
    assert not dialog.projet_radio.isEnabled()
    dialog.projet_combo.setCurrentIndex(1)
    assert dialog.projet_radio.isEnabled() and "GoFiber" in dialog.projet_radio.text()
    dialog.projet_radio.setChecked(True)
    assert dialog.visibility() == hm.VISIBILITY_PROJET
    dialog.projet_combo.setCurrentIndex(0)          # plus de projet metier : retour a « moi seul »
    assert dialog.visibility() == hm.VISIBILITY_PRIVATE and not dialog.projet_radio.isEnabled()
    no_share_project = pj.ProjetCapabilities(True, True, True, True, True, True, False)
    dialog = _save_dialog(dlg, caps=no_share_project)
    dialog.projet_combo.setCurrentIndex(1)
    assert not dialog.projet_radio.isEnabled()


def test_people_visibility_absent_without_share_capability(dlg):
    caps = pj.ProjetCapabilities(True, True, True, True, True, False, True)
    dialog = _save_dialog(dlg, caps=caps)
    assert dialog.people_radio is None and dialog.picker is None


def test_changing_projet_clears_people_and_searches_with_its_code(dlg):
    dialog = _save_dialog(dlg)
    dialog.projet_combo.setCurrentIndex(1)
    dialog.people_radio.setChecked(True)
    dialog.picker.input.type("ale")
    dialog.picker.timer.timeout.emit()
    assert dialog.searches[-1] == ("GOFIBER", "ale", [])
    dialog.picker.choose(ALICE)
    dialog.projet_combo.setCurrentIndex(2)
    assert dialog.picker.chosen() == ()


def test_save_disabled_for_bad_name_or_empty_project(dlg):
    dialog = _save_dialog(dlg)
    assert dialog.save_button.isEnabled()
    dialog.name_edit.setText(" Vue")
    assert not dialog.save_button.isEnabled() and dialog.name_error_label.text() == dlg.tr("save.name_spaces")
    dialog.name_edit.setText("")
    assert dialog.name_error_label.text() == dlg.tr("save.name_empty")
    empty = _save_dialog(dlg, state=hm.CurrentProjectState("Vue", 0, "jdoe"))
    assert not empty.save_button.isEnabled() and empty.empty_label.isVisible()


def test_request_carries_people_and_visibility(dlg):
    dialog = _save_dialog(dlg)
    dialog.projet_combo.setCurrentIndex(1)
    dialog.description_edit.setText("  desc ")
    dialog.people_radio.setChecked(True)
    dialog.picker.choose(ALICE)
    dialog.picker.set_right("a.leroy", True)
    request = dialog.request()
    assert request == hm.SaveRequest("Ixelles", "desc", "uuid-g", "GOFIBER", hm.VISIBILITY_PEOPLE, (("a.leroy", True),))
    dialog.private_radio.setChecked(True)
    assert dialog.request().people == () and dialog.request().visibility == hm.VISIBILITY_PRIVATE


def test_update_request_never_carries_visibility(dlg):
    opened = OpenedQgisProject("Vue", 4, "uuid-g", "GOFIBER", True, True, {})
    dialog = _save_dialog(dlg, opened=opened)
    assert dialog.request().visibility == hm.VISIBILITY_PRIVATE and dialog.request().projet_id == "uuid-g"


def test_name_taken_outcome_suggests_another_name(dlg):
    dialog = _save_dialog(dlg)
    dialog.show_outcome(store.StoreOutcome(store.STATUS_NAME_TAKEN), "jdoe")
    assert dialog.outcome_label.text() == dlg.tr("save.name_taken") and dialog.name_edit.text() == "Ixelles (jdoe)"
    dialog.show_outcome(store.StoreOutcome(store.STATUS_GONE), "jdoe")
    assert dialog.name_edit.text() == "Ixelles (jdoe)"            # suggestion idempotente


@pytest.mark.parametrize("status,key", [("nominative", "save.nominative"), ("projet_denied", "save.projet_denied"),
                                        ("too_large", "save.too_large")])
def test_dedicated_outcome_messages(dlg, status, key):
    dialog = _save_dialog(dlg)
    dialog.show_outcome(store.StoreOutcome(status), "jdoe")
    assert dialog.outcome_label.text() == dlg.tr(key)


def test_invalid_and_error_show_the_server_message(dlg):
    dialog = _save_dialog(dlg)
    dialog.show_outcome(store.StoreOutcome(store.STATUS_INVALID, message="nom invalide"), "jdoe")
    assert dialog.outcome_label.text() == dlg.tr("save.invalid", message="nom invalide")
    dialog.show_outcome(store.StoreOutcome("error", message="QGISP_FUTURE refus"), "jdoe")
    assert dialog.outcome_label.text() == dlg.tr("save.error", message="QGISP_FUTURE refus")


def test_unsafe_outcome_lists_formatted_findings(dlg):
    dialog = _save_dialog(dlg)
    findings = (Finding("macros"), Finding("action", "Points", "Py (type=1)"), Finding("python_file", "", "init.py"))
    dialog.show_outcome(store.StoreOutcome("unsafe", value=findings), "jdoe")
    lines = dialog.outcome_label.text().split("\n")
    assert lines[0] == dlg.tr("save.unsafe_intro") and len(lines) == 4
    assert lines[2] == "• " + dlg.tr("save.finding_layer", layer="Points") + " " + dlg.tr("save.finding_action", detail="Py (type=1)")


def test_every_finding_kind_has_a_text(dlg):
    from constructel_bridge import bridge_project_safety as ps

    for kind in (ps.FINDING_MACROS, ps.FINDING_EXPRESSION_FUNCTIONS, ps.FINDING_ACTION, ps.FINDING_FORM_INIT,
                 ps.FINDING_PASSWORD, ps.FINDING_PYTHON_FILE):
        assert dlg.format_finding(Finding(kind, "", "x")) not in ("", kind)


# --- conflit et deroule d'enregistrement --------------------------------------------------


class _FlowDialog:
    """SaveDialog factice : exec() rend les reponses prevues ; journalise."""

    def __init__(self, answers, name="Vue", update=False):
        self.answers = list(answers)
        self.name = name
        self.update = update
        self.outcomes = []

    def exec(self):
        return self.answers.pop(0) if self.answers else 0

    def request(self):
        return hm.SaveRequest(self.name, "", None, None, hm.VISIBILITY_PRIVATE, ())

    def is_update(self):
        return self.update

    def suggest_rename(self, login):
        self.name = f"{self.name} ({login})"

    def show_outcome(self, outcome, login):
        self.outcomes.append(outcome.status)


class _FlowConflict:
    def __init__(self, choices, log):
        self.choices, self.log = choices, log

    def __call__(self, name, creating, detail):
        self.log.append(("conflict", name, creating, detail))
        choice = self.choices.pop(0)
        return type("C", (), {"exec": lambda self: 0, "choice": lambda self, c=choice: c})()


class _FlowActions:
    def __init__(self, saves, overwrites=()):
        self.saves, self.overwrites, self.log = list(saves), list(overwrites), []

    def save(self, request):
        self.log.append(("save", request.name))
        return self.saves.pop(0)

    def overwrite(self, request):
        self.log.append(("overwrite", request.name))
        return self.overwrites.pop(0)


CONFLICT = store.StoreOutcome(store.STATUS_CONFLICT, detail="version courante 5")
OK = store.StoreOutcome(store.STATUS_OK, value=2)


def test_conflict_flow_rename_then_overwrite_then_cancel(dlg):
    # 1. Conflit -> autre nom -> enregistre sous « Vue (jdoe) ».
    log = []
    dialog = _FlowDialog([1, 1])
    actions = _FlowActions([CONFLICT, OK])
    assert dlg.run_save_flow(lambda: dialog, _FlowConflict([dlg.CHOICE_RENAME], log), actions, "jdoe") == OK
    assert actions.log == [("save", "Vue"), ("save", "Vue (jdoe)")] and log[0][1:] == ("Vue", True, "version courante 5")

    # 2. Conflit -> ecraser -> nouveau conflit -> ecraser -> ok ; puis suppression entre-temps -> introuvable.
    log = []
    dialog = _FlowDialog([1, 0], update=True)
    actions = _FlowActions([CONFLICT], [CONFLICT, OK])
    flow = dlg.run_save_flow(lambda: dialog, _FlowConflict([dlg.CHOICE_OVERWRITE, dlg.CHOICE_OVERWRITE], log),
                             actions, "jdoe")
    assert flow == OK and [entry[0] for entry in actions.log] == ["save", "overwrite", "overwrite"]
    assert log[0][2] is False                       # mise a jour : « modifie depuis son ouverture »
    dialog = _FlowDialog([1, 0], update=True)
    actions = _FlowActions([CONFLICT], [store.StoreOutcome(store.STATUS_GONE)])
    assert dlg.run_save_flow(lambda: dialog, _FlowConflict([dlg.CHOICE_OVERWRITE], []), actions, "jdoe") is None
    assert dialog.outcomes == [store.STATUS_GONE]   # jamais d'ecrasement muet : message, dialogue rouvert

    # 3. Conflit -> annuler : rien n'est enregistre.
    dialog = _FlowDialog([1])
    actions = _FlowActions([CONFLICT])
    assert dlg.run_save_flow(lambda: dialog, _FlowConflict([dlg.CHOICE_CANCEL], []), actions, "jdoe") is None
    assert actions.log == [("save", "Vue")]


def test_refusal_keeps_the_dialog_open_then_cancel(dlg):
    dialog = _FlowDialog([1, 0])
    actions = _FlowActions([store.StoreOutcome(store.STATUS_NAME_TAKEN)])
    assert dlg.run_save_flow(lambda: dialog, _FlowConflict([], []), actions, "jdoe") is None
    assert dialog.outcomes == [store.STATUS_NAME_TAKEN]


def test_conflict_default_button_is_cancel(dlg):
    dialog = dlg.ConflictDialog("Vue", True, "version courante 5")
    assert dialog.cancel_button.isDefault() and not dialog.overwrite_button.isDefault()
    assert not dialog.overwrite_button.autoDefault() and not dialog.rename_button.autoDefault()
    assert "version courante 5" in dialog.message_label.text()
    assert dlg.tr("conflict.exists", name="Vue") in dialog.message_label.text()
    assert dialog.choice() == dlg.CHOICE_CANCEL
    dialog.overwrite_button.clicked.emit()
    assert dialog.choice() == dlg.CHOICE_OVERWRITE and dialog.result == 1
    update = dlg.ConflictDialog("Vue", False, "")
    assert update.message_label.text() == dlg.tr("conflict.changed", name="Vue")
    update.cancel_button.clicked.emit()
    assert update.choice() == dlg.CHOICE_CANCEL and update.result == 0
