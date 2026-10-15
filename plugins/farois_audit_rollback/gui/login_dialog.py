"""Saisie des identifiants Farois (AD). Le mot de passe n'est jamais conservé."""


def ask_credentials(parent, email=""):
    """Retourne (email, mot de passe) ou None si annulé ou incomplet."""
    from qgis.PyQt.QtWidgets import (
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
    form.addRow("Adresse mail", email_edit)
    form.addRow("Mot de passe", password_edit)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    try:
        if dialog.exec_() != QDialog.Accepted:
            return None
        address, secret = email_edit.text().strip(), password_edit.text()
        return (address, secret) if address and secret else None
    finally:
        password_edit.clear()
        dialog.deleteLater()
