"""Saisie des identifiants Farois (AD). Le mot de passe n'est jamais conservé."""

BRIDGE_EMAIL_KEY = "constructel_bridge/audit_email"  # réglage de Constructel Bridge


def bridge_email():
    """Adresse saisie dans Constructel Bridge, ou "" (sans QGIS ou sans réglage)."""
    try:
        from qgis.core import QgsSettings

        return str(QgsSettings().value(BRIDGE_EMAIL_KEY, "") or "").strip()
    except Exception:
        return ""


def ask_credentials(parent, email="", remember=True):
    """Retourne (email, mot de passe, se souvenir) ou None si annulé ou incomplet."""
    from qgis.PyQt.QtWidgets import (
        QCheckBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QLineEdit,
    )

    dialog = QDialog(parent)
    dialog.setWindowTitle("Se connecter à Farois")
    form = QFormLayout(dialog)
    email_edit = QLineEdit(email)
    password_edit = QLineEdit()
    password_edit.setEchoMode(QLineEdit.Password)
    remember_box = QCheckBox("Se souvenir de moi (30 jours)")
    remember_box.setChecked(bool(remember))
    remember_box.setToolTip(
        "Garde un jeton de session Farois (30 jours) chiffré dans le gestionnaire "
        "d'authentification QGIS. Le mot de passe n'est jamais enregistré."
    )
    form.addRow("Adresse mail", email_edit)
    form.addRow("Mot de passe", password_edit)
    form.addRow(remember_box)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if email:
        password_edit.setFocus()
    try:
        if dialog.exec_() != QDialog.Accepted:
            return None
        address, secret = email_edit.text().strip(), password_edit.text()
        if not (address and secret):
            return None
        return address, secret, remember_box.isChecked()
    finally:
        password_edit.clear()
        dialog.deleteLater()
