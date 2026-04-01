# -*- coding: utf-8 -*-
"""
Constructel Bridge - Dialogue de connexion.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from .i18n import tr


class ConstructelConnectDialog(QDialog):
    """Dialogue simple pour saisir le mot de passe ftth_editor."""

    def __init__(self, parent=None, host="localhost", port=5432, dbname="wyre_ftth"):
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.title"))
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)

        header = QLabel(tr("dialog.header"))
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        form = QFormLayout()

        self._host_edit = QLineEdit(host)
        self._host_edit.setReadOnly(True)
        form.addRow(tr("dialog.server"), self._host_edit)

        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(port)
        self._port_spin.setReadOnly(True)
        form.addRow(tr("dialog.port"), self._port_spin)

        self._dbname_edit = QLineEdit(dbname)
        self._dbname_edit.setReadOnly(True)
        form.addRow(tr("dialog.database"), self._dbname_edit)

        self._user_edit = QLineEdit("ftth_editor")
        self._user_edit.setReadOnly(True)
        form.addRow(tr("dialog.role"), self._user_edit)

        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.Password)
        self._password_edit.setPlaceholderText(tr("dialog.password_placeholder"))
        form.addRow(tr("dialog.password"), self._password_edit)

        self._save_check = QCheckBox(tr("dialog.save_password"))
        self._save_check.setChecked(True)
        form.addRow("", self._save_check)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._password_edit.setFocus()

    def password(self) -> str:
        return self._password_edit.text()

    def save_password(self) -> bool:
        return self._save_check.isChecked()
