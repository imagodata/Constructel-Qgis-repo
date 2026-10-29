"""Bridge 1.8 — dialogue de connexion (plan 2026-10-29 volet B4) : login
nominatif pre-rempli et MODIFIABLE (fini user='ftth_editor' en dur), mot de
passe AD, OK seulement si login ET mot de passe non vides, message de
ressaisie optionnel, plus de case « retenir le mot de passe » (le mot de
passe est toujours memorise par l'Auth Manager, comme 1.7.x de fait).
Stub-level : widgets Qt enregistreurs, aucune boucle d'evenements.
"""
import importlib
import sys

import pytest


@pytest.fixture
def dialog_module(bp18):
    for name in list(sys.modules):
        if name == "constructel_bridge.bridge_dialog":
            del sys.modules[name]
    return importlib.import_module("constructel_bridge.bridge_dialog")


def _dialog(mod, **kwargs):
    params = dict(host="test-host.invalid", port=5432, dbname="test_db", login="jdoe")
    params.update(kwargs)
    return mod.ConstructelConnectDialog(None, **params)


def test_login_is_prefilled_and_editable(dialog_module):
    dlg = _dialog(dialog_module)
    assert dlg.login() == "jdoe"
    assert dlg._user_edit.isReadOnly() is False
    dlg._user_edit.setText("JDupont")
    assert dlg.login() == "jdupont"


def test_ok_requires_login_and_password(dialog_module):
    dlg = _dialog(dialog_module)
    assert dlg._ok_button.isEnabled() is False
    dlg._password_edit.setText("secret")
    assert dlg._ok_button.isEnabled() is True
    dlg._user_edit.setText("")
    assert dlg._ok_button.isEnabled() is False


@pytest.mark.parametrize("typed, login", [
    ("CONSTRUCTELBE\\JDupont", "jdupont"),
    ("jdupont@constructelbe.corp", "jdupont"),
    ("ftth_editor", "ftth_editor"),  # secours admin D5
])
def test_typed_login_is_normalized(dialog_module, typed, login):
    dlg = _dialog(dialog_module)
    dlg._user_edit.setText(typed)
    dlg._password_edit.setText("secret")
    assert dlg.login() == login
    assert dlg._ok_button.isEnabled() is True
    assert dlg._login_error.isVisible() is False


def test_invalid_login_is_reported_in_the_dialog(dialog_module):
    # Revue 29/10 (I5) : plus de bascule silencieuse en partage.
    dlg = _dialog(dialog_module)
    dlg._password_edit.setText("secret")
    dlg._user_edit.setText("Jean Dupont")
    assert dlg._login_error.isVisible() is True
    assert dlg._ok_button.isEnabled() is False
    assert dlg.login() == ""
    dlg._user_edit.setText("")
    assert dlg._login_error.isVisible() is False


def test_password_is_masked_and_never_prefilled(dialog_module):
    from qgis.PyQt.QtWidgets import QLineEdit

    dlg = _dialog(dialog_module)
    assert dlg.password() == ""
    assert dlg._password_edit.echoMode() == QLineEdit.EchoMode.Password


def test_reprompt_message_is_shown_only_when_given(dialog_module):
    silent = _dialog(dialog_module)
    assert getattr(silent, "_message_label", None) is None or not silent._message_label.isVisible()
    loud = _dialog(dialog_module, message="Mot de passe refuse pour jdoe.")
    assert loud._message_label.text() == "Mot de passe refuse pour jdoe."
    assert loud._message_label.isVisible() is True


def test_no_remember_password_checkbox_anymore(dialog_module):
    dlg = _dialog(dialog_module)
    assert not hasattr(dlg, "_save_check")
    assert not hasattr(dlg, "save_password")


def test_header_and_placeholders_no_longer_mention_ftth_editor(dialog_module, bp18):
    dlg = _dialog(dialog_module)
    for lang in ("en", "fr", "pt"):
        header = bp18.tr.__globals__["TRANSLATIONS"][lang]["dialog.header"]
        placeholder = bp18.tr.__globals__["TRANSLATIONS"][lang]["dialog.password_placeholder"]
        assert "ftth_editor" not in header, lang
        assert "ftth_editor" not in placeholder, lang
    assert "ftth_editor" not in dlg._password_edit.placeholderText()


def test_server_fields_stay_read_only(dialog_module):
    dlg = _dialog(dialog_module)
    assert dlg._host_edit.isReadOnly() is True
    assert dlg._dbname_edit.isReadOnly() is True
