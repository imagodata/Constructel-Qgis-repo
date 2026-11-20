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
                 ps.FINDING_PASSWORD, ps.FINDING_PYTHON_FILE, ps.FINDING_EMBEDDED_PROJECT):
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


# --- partager (tache 18) -----------------------------------------------------------------------

from constructel_bridge.bridge_qgis_projects import QgisProjectRow, SharePlan, ShareRow  # noqa: E402


def qrow(name="Vue", **kw):
    base = dict(owner="jdoe", projet_id="uuid-g", projet_code="GOFIBER", projet_label="GoFiber", share_project=False,
                published=False, owner_role="BE", version=3, updated_at=None, updated_by="jdoe", is_owner=True,
                can_edit=True, share_count=2, description=None)
    base.update(kw)
    return QgisProjectRow(name=name, **base)


class _ShareActions:
    def __init__(self, lists, outcomes=()):
        self.lists = list(lists)
        self.outcomes = list(outcomes)
        self.log = []

    def shares_list(self, name):
        self.log.append(("list", name))
        return self.lists.pop(0) if len(self.lists) > 1 else self.lists[0]

    def apply_shares(self, name, plan):
        self.log.append(("apply", name, plan))
        return self.outcomes.pop(0)

    def eligible_users(self, code, prefix, exclude):
        self.log.append(("eligible", code, prefix, list(exclude)))
        return [ALICE]


SHARES = [ShareRow("b.martin", "Bob Martin", "ADMIN", True, True), ShareRow("c.vieux", None, None, False, False)]


def _share(dlg, lists=(SHARES,), outcomes=(), row=None, caps=FULL):
    actions = _ShareActions(lists, outcomes)
    dialog = dlg.ShareDialog(row or qrow(), actions, caps)
    dialog.actions = actions
    return dialog


def test_share_dialog_lists_people_and_marks_inoperant(dlg):
    dialog = _share(dlg)
    assert dialog.title == dlg.tr("share.title", name="Vue")
    first, second = dialog.who.children
    assert first.text(0) == "Bob Martin (b.martin) — ADMIN" and dialog.who.itemWidget(first, 1).currentData() is True
    assert second.toolTip(0) == dlg.tr("share.inoperant") and first.toolTip(0) == ""
    assert dialog.apply_button.isEnabled()
    dialog.picker.input.type("ali")
    dialog.picker.timer.timeout.emit()
    assert dialog.actions.log[-1] == ("eligible", "GOFIBER", "ali", ["b.martin", "c.vieux"])


def test_unreadable_share_list_disables_apply(dlg):
    dialog = _share(dlg, lists=(None,))
    assert not dialog.apply_button.isEnabled() and dialog.list_error_label.text() == dlg.tr("share.list_error")


def test_projet_box_only_for_attached_projects_with_capability(dlg):
    assert _share(dlg).projet_box is not None
    assert _share(dlg, row=qrow(share_project=True)).projet_box.isChecked()
    assert _share(dlg, row=qrow(projet_id=None, projet_code=None, projet_label=None)).projet_box is None
    no_cap = pj.ProjetCapabilities(True, True, True, True, True, True, False)
    assert _share(dlg, caps=no_cap).projet_box is None


def test_plan_from_rights_changes_removals_and_new_people(dlg):
    dialog = _share(dlg)
    dialog.projet_box.setChecked(True)
    dialog.who.itemWidget(dialog.who.children[0], 1).setCurrentIndex(0)      # b.martin : peut ouvrir
    dialog.who.itemWidget(dialog.who.children[1], 2).clicked.emit()           # c.vieux retire
    assert dialog.who.children[1].isDisabled()
    dialog.picker.choose(ALICE)
    dialog.picker.set_right("a.leroy", True)
    assert dialog.plan() == SharePlan(True, ("c.vieux",), ("a.leroy",), ("b.martin",))
    dialog.who.itemWidget(dialog.who.children[1], 2).clicked.emit()           # retabli
    assert dialog.plan().unshare == ()


def test_apply_empty_plan_just_closes(dlg):
    dialog = _share(dlg)
    out = dialog.apply()
    assert out.status == store.STATUS_OK and dialog.result == 1
    assert not any(entry[0] == "apply" for entry in dialog.actions.log)


def test_apply_ok_reloads_and_closes(dlg):
    dialog = _share(dlg, outcomes=(store.StoreOutcome(store.STATUS_OK, value=1),))
    dialog.picker.choose(ALICE)
    assert dialog.apply().status == store.STATUS_OK and dialog.result == 1
    assert dialog.done_message == dlg.tr("share.done")
    assert [e[0] for e in dialog.actions.log] == ["list", "apply", "list"]


def test_apply_ineligible_keeps_dialog_open_and_reloads_list(dlg):
    after = SHARES + [ShareRow("d.new", None, None, False, True)]
    dialog = _share(dlg, lists=(SHARES, after),
                    outcomes=(store.StoreOutcome(store.STATUS_INELIGIBLE, value=2, count=1),))
    dialog.projet_box.setChecked(True)
    dialog.picker.choose(ALICE)
    out = dialog.apply()
    assert out.status == store.STATUS_INELIGIBLE and dialog.result is None
    assert dialog.message_label.text() == dlg.tr("share.ineligible", count=1) + "\n" + dlg.tr("share.partial", done=2)
    assert len(dialog.who.children) == 3 and dialog.picker.chosen() == ()
    assert dialog.projet_box.isChecked()             # share_project applique avant l'erreur
    assert dialog.plan().share_project is None


def test_apply_denied_message(dlg):
    dialog = _share(dlg, outcomes=(store.StoreOutcome(store.STATUS_DENIED, value=0),))
    dialog.picker.choose(ALICE)
    dialog.apply()
    assert dialog.message_label.text() == dlg.tr("share.denied")


def test_confirm_delete_defaults_to_no(dlg, monkeypatch):
    asked = []
    assert dlg.confirm_delete(None, "Vue", ask=lambda title, text: asked.append(text) or False) is False
    assert asked == [dlg.tr("delete.confirm", name="Vue")]

    calls = []

    class _Box:
        class StandardButton:
            Yes, No = 0x4000, 0x10000

        @staticmethod
        def question(parent, title, text, buttons, default):
            calls.append(default)
            return _Box.StandardButton.No

    monkeypatch.setattr(dlg, "QMessageBox", _Box)
    assert dlg.confirm_delete(None, "Vue") is False and calls == [_Box.StandardButton.No]


@pytest.mark.parametrize("status,key", [("ok", "delete.done"), ("missing", "delete.missing"),
                                        ("denied", "delete.denied"), ("nominative", "save.nominative")])
def test_delete_messages_by_status(dlg, status, key):
    assert dlg.delete_message(store.StoreOutcome(status)) == dlg.tr(key)


def test_delete_error_message_carries_the_server_text(dlg):
    assert dlg.delete_message(store.StoreOutcome("error", message="boom")) == dlg.tr("delete.error", message="boom")


def test_enter_in_people_search_never_triggers_save_or_apply(dlg):
    # Revue 2.1 (L12) : aucun bouton par defaut dans les dialogues a recherche.
    save = _save_dialog(dlg)
    assert not save.save_button.isDefault() and not save.save_button.autoDefault()
    share = _share(dlg)
    assert not share.apply_button.isDefault() and not share.apply_button.autoDefault()
