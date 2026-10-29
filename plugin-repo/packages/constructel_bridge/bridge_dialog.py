# -*- coding: utf-8 -*-
"""
Constructel Bridge - Dialogue de connexion.

Bridge 1.8 : login PostgreSQL nominatif (compte Windows / AD de la
personne), pre-rempli et modifiable, + mot de passe AD. Le mot de passe est
toujours memorise par l'Auth Manager QGIS (sonde silencieuse au demarrage
suivant) : plus de case « retenir le mot de passe ».
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
    """Dialogue : login nominatif (modifiable) + mot de passe AD."""

    def __init__(self, parent=None, host="localhost", port=5432, dbname="farois_ftth",
                 login="", message=""):
        super().__init__(parent)
        self.setWindowTitle(tr("dialog.title"))
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)

        header = QLabel(tr("dialog.header"))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        # Message de ressaisie (mot de passe refuse) : affiche seulement
        # quand l'appelant en fournit un.
        self._message_label = None
        if message:
            self._message_label = QLabel(message)
            self._message_label.setWordWrap(True)
            self._message_label.setStyleSheet("color: #b00020;")
            layout.addWidget(self._message_label)

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

        # Login nominatif : pre-rempli depuis le nom d'utilisateur du poste,
        # modifiable (compte AD different, identifiant de secours admin).
        self._user_edit = QLineEdit(login)
        self._user_edit.setPlaceholderText(tr("dialog.login_placeholder"))
        form.addRow(tr("dialog.login"), self._user_edit)

        # Password field with show/hide toggle -- jamais pre-rempli.
        pw_layout = QHBoxLayout()
        self._password_edit = QLineEdit()
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
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

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # OK seulement quand login ET mot de passe sont renseignes.
        self._user_edit.textChanged.connect(self._validate)
        self._password_edit.textChanged.connect(self._validate)
        self._validate()

        if login:
            self._password_edit.setFocus()
        else:
            self._user_edit.setFocus()

    def _validate(self, *_args):
        """Enable OK only when login and password are non-empty."""
        self._ok_button.setEnabled(bool(self._user_edit.text().strip()) and bool(self._password_edit.text()))

    def _toggle_password_visibility(self, visible: bool):
        """Toggle between masked and clear-text password display."""
        if visible:
            self._password_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._toggle_pw_btn.setToolTip(tr("dialog.hide_password"))
        else:
            self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._toggle_pw_btn.setToolTip(tr("dialog.show_password"))

    def login(self) -> str:
        return self._user_edit.text().strip()

    def password(self) -> str:
        return self._password_edit.text()
