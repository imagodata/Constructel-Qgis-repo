# -*- coding: utf-8 -*-
"""
Constructel Bridge - Dialogue de connexion.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .i18n import tr


class ConstructelConnectDialog(QDialog):
    """Dialogue simple pour saisir le mot de passe AD (auth LDAP wyre)."""

    def __init__(self, parent=None, host="localhost", port=5432, dbname="farois_ftth", user=""):
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

        self._user_edit = QLineEdit(user)
        self._user_edit.setReadOnly(True)
        form.addRow(tr("dialog.role"), self._user_edit)

        # Password field with show/hide toggle
        pw_layout = QHBoxLayout()
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.Password)
        self._password_edit.setPlaceholderText(tr("dialog.password_placeholder"))
        pw_layout.addWidget(self._password_edit)

        self._toggle_pw_btn = QPushButton("\U0001F441")
        self._toggle_pw_btn.setFixedWidth(32)
        self._toggle_pw_btn.setToolTip(tr("dialog.show_password"))
        self._toggle_pw_btn.setCheckable(True)
        self._toggle_pw_btn.toggled.connect(self._toggle_password_visibility)
        pw_layout.addWidget(self._toggle_pw_btn)

        form.addRow(tr("dialog.password"), pw_layout)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._ok_button = buttons.button(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Disable OK button when password is empty
        self._password_edit.textChanged.connect(self._validate)
        self._validate()

        self._password_edit.setFocus()

    def _validate(self):
        """Enable OK only when password is non-empty."""
        self._ok_button.setEnabled(bool(self._password_edit.text()))

    def _toggle_password_visibility(self, visible: bool):
        """Toggle between masked and clear-text password display."""
        if visible:
            self._password_edit.setEchoMode(QLineEdit.Normal)
            self._toggle_pw_btn.setToolTip(tr("dialog.hide_password"))
        else:
            self._password_edit.setEchoMode(QLineEdit.Password)
            self._toggle_pw_btn.setToolTip(tr("dialog.show_password"))

    def password(self) -> str:
        return self._password_edit.text()
