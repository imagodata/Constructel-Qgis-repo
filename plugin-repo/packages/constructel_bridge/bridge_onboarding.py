# -*- coding: utf-8 -*-
"""
Constructel Bridge - Wizard d'onboarding.

Affiche apres la premiere connexion reussie:
  Page 1: Creation / confirmation du profil utilisateur
  Page 2: Plugins recommandes (facultatifs) avec bouton d'installation
  Page 3: Configuration QGIS Resource Sharing (repo Constructel)
  Page 4: Resume et finalisation
"""

import re

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from qgis.core import Qgis, QgsMessageLog, QgsSettings
from qgis.utils import available_plugins, active_plugins, loadPlugin, startPlugin

from .i18n import tr

TAG = "Constructel Bridge"

# ---------------------------------------------------------------------------
# Catalogue des plugins recommandes
# ---------------------------------------------------------------------------
RECOMMENDED_PLUGINS = [
    {
        "id": "nominatim_locator_filter",
        "name": "Nominatim Locator Filter",
        "desc_key": "plugin.nominatim.desc",
    },
    {
        "id": "filter_mate",
        "name": "FilterMate",
        "desc_key": "plugin.filtermate.desc",
    },
    {
        "id": "qfieldsync",
        "name": "QField Sync",
        "desc_key": "plugin.qfieldsync.desc",
    },
    {
        "id": "qgis_resource_sharing",
        "name": "QGIS Resource Sharing",
        "desc_key": "plugin.resource_sharing.desc",
    },
    {
        "id": "streetviewplugin",
        "name": "Street View",
        "desc_key": "plugin.streetview.desc",
    },
    {
        "id": "plugin_reloader",
        "name": "Plugin Reloader",
        "desc_key": "plugin.reloader.desc",
    },
]

RESOURCE_SHARING_REPO_NAME = "Constructel"
RESOURCE_SHARING_REPO_URL = "http://192.168.160.31:9081/"


# =========================================================================
# Page 1 — Profil utilisateur
# =========================================================================
class UserProfilePage(QWizardPage):

    _EMAIL_DOMAIN = "constructel.be"  # overridden in __init__ from credentials

    def __init__(self, username: str, user_id: str, is_new: bool, parent=None, email_domain: str = ""):
        super().__init__(parent)
        if email_domain:
            self._EMAIL_DOMAIN = email_domain
        self.setTitle(tr("onboard.user.title"))
        self.setSubTitle(tr("onboard.user.subtitle"))

        # Track whether the user has manually edited the email
        self._email_manual = False

        layout = QVBoxLayout(self)

        if is_new:
            info = QLabel(tr("onboard.user.welcome_new"))
        else:
            info = QLabel(tr("onboard.user.welcome_back"))
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()

        self._username_edit = QLineEdit(username)
        self._username_edit.setReadOnly(True)
        form.addRow(tr("onboard.user.field_id"), self._username_edit)

        # Split PascalCase username (e.g. "SimonDucourneau" -> "Simon", "Ducourneau")
        parts = re.findall(r'[A-Z][a-z]*|[a-z]+', username)
        if len(parts) >= 2:
            default_first = parts[0]
            default_last = " ".join(parts[1:])
        else:
            default_first = ""
            default_last = username

        self._firstname_edit = QLineEdit()
        self._firstname_edit.setPlaceholderText(tr("onboard.user.field_firstname_hint"))
        self.registerField("first_name", self._firstname_edit)
        self._firstname_edit.setText(default_first)
        form.addRow(tr("onboard.user.field_firstname"), self._firstname_edit)

        self._lastname_edit = QLineEdit()
        self._lastname_edit.setPlaceholderText(tr("onboard.user.field_lastname_hint"))
        self.registerField("last_name", self._lastname_edit)
        self._lastname_edit.setText(default_last)
        form.addRow(tr("onboard.user.field_lastname"), self._lastname_edit)

        self._email_edit = QLineEdit()
        self._email_edit.setPlaceholderText(tr("onboard.user.field_email_hint"))
        self.registerField("email", self._email_edit)
        self._email_edit.setText(self._build_email(username))
        form.addRow(tr("onboard.user.field_email"), self._email_edit)

        layout.addLayout(form)

        # Connect signals: firstname/lastname changes update email automatically
        self._firstname_edit.textChanged.connect(self._sync_email)
        self._lastname_edit.textChanged.connect(self._sync_email)
        self._email_edit.textEdited.connect(self._on_email_edited)

        # Notify wizard when completeness changes
        self._lastname_edit.textChanged.connect(self.completeChanged)
        self._email_edit.textChanged.connect(self.completeChanged)

        note = QLabel(tr("onboard.user.note"))
        note.setWordWrap(True)
        layout.addWidget(note)

    def _build_email(self, *_) -> str:
        """Build email from firstnamelastname (lowercase, no dots, no spaces)."""
        first = self._firstname_edit.text().strip() if hasattr(self, "_firstname_edit") else ""
        last = self._lastname_edit.text().strip() if hasattr(self, "_lastname_edit") else ""
        local = f"{first}{last}" if first or last else "user"
        # Lowercase, remove spaces
        local = local.lower().replace(" ", "")
        return f"{local}@{self._EMAIL_DOMAIN}"

    def _sync_email(self):
        """Auto-update email when name fields change (unless user edited manually)."""
        if not self._email_manual:
            self._email_edit.setText(self._build_email())

    def _on_email_edited(self):
        """Mark email as manually edited so auto-sync stops."""
        self._email_manual = True

    def isComplete(self) -> bool:
        """Page is complete when last_name and email are filled."""
        return bool(self._lastname_edit.text().strip() and self._email_edit.text().strip())


# =========================================================================
# Page 2 — Plugins recommandes
# =========================================================================
class PluginBundlePage(QWizardPage):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle(tr("onboard.plugins.title"))
        self.setSubTitle(tr("onboard.plugins.subtitle"))

        layout = QVBoxLayout(self)
        self._checkboxes: dict[str, QCheckBox] = {}

        installed = set(available_plugins)

        for plugin in RECOMMENDED_PLUGINS:
            pid = plugin["id"]
            already = pid in installed
            active = pid in active_plugins

            group = QGroupBox()
            group_layout = QVBoxLayout(group)

            cb = QCheckBox(plugin["name"])
            cb.setFont(QFont(cb.font().family(), cb.font().pointSize(), QFont.Bold))
            if already and active:
                cb.setChecked(False)
                cb.setEnabled(False)
                cb.setText(tr("onboard.plugins.already_active", name=plugin["name"]))
            elif already:
                cb.setChecked(True)
                cb.setText(tr("onboard.plugins.installed_inactive", name=plugin["name"]))
            else:
                cb.setChecked(True)
            self._checkboxes[pid] = cb
            group_layout.addWidget(cb)

            desc = QLabel(tr(plugin["desc_key"]))
            desc.setWordWrap(True)
            desc.setStyleSheet("color: #555; margin-left: 20px;")
            group_layout.addWidget(desc)

            layout.addWidget(group)

        layout.addStretch()

        note = QLabel(tr("onboard.plugins.note"))
        note.setWordWrap(True)
        layout.addWidget(note)

    def get_selected_plugins(self) -> list[str]:
        return [pid for pid, cb in self._checkboxes.items() if cb.isChecked()]


# =========================================================================
# Page 3 — QGIS Resource Sharing
# =========================================================================
class ResourceSharingPage(QWizardPage):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle(tr("onboard.rs.title"))
        self.setSubTitle(tr("onboard.rs.subtitle"))

        layout = QVBoxLayout(self)

        self._rs_installed = "qgis_resource_sharing" in available_plugins

        if self._rs_installed:
            info = QLabel(tr("onboard.rs.installed"))
        else:
            info = QLabel(tr("onboard.rs.not_installed"))
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()

        self._repo_name = QLineEdit(RESOURCE_SHARING_REPO_NAME)
        self._repo_name.setReadOnly(True)
        form.addRow(tr("onboard.rs.repo_name"), self._repo_name)

        self._repo_url = QLineEdit(RESOURCE_SHARING_REPO_URL)
        self._repo_url.setReadOnly(True)
        form.addRow(tr("onboard.rs.repo_url"), self._repo_url)

        layout.addLayout(form)

        self._cb_configure = QCheckBox(tr("onboard.rs.auto_configure"))
        self._cb_configure.setChecked(self._rs_installed)
        self._cb_configure.setEnabled(self._rs_installed)
        layout.addWidget(self._cb_configure)

        desc = QLabel(tr("onboard.rs.note"))
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addStretch()

    def should_configure(self) -> bool:
        return self._cb_configure.isChecked()


# =========================================================================
# Page 4 — Services externes (WMTS / XYZ / WFS)
# =========================================================================

# Catalogue des flux externes — type affiché, nom, clé de traduction description
EXTERNAL_SERVICES_CATALOG = [
    {
        "type": "XYZ",
        "name": "Google Streetview Coverage",
        "desc_key": "service.streetview.desc",
    },
    {
        "type": "WMTS",
        "name": "WMTS UrbIS Bruxelles",
        "desc_key": "service.urbis_wmts.desc",
    },
    {
        "type": "WMTS",
        "name": "WMTS NGI CartoWeb Belgique",
        "desc_key": "service.cartoweb.desc",
    },
    {
        "type": "WFS",
        "name": "WFS Cadastre UrbIS Bruxelles",
        "desc_key": "service.urbis_wfs.desc",
    },
]


class ExternalServicesPage(QWizardPage):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle(tr("onboard.services.title"))
        self.setSubTitle(tr("onboard.services.subtitle"))

        layout = QVBoxLayout(self)

        for svc in EXTERNAL_SERVICES_CATALOG:
            group = QGroupBox()
            group_layout = QVBoxLayout(group)

            # En-tête : badge type + nom
            header = QHBoxLayout()
            badge = QLabel(f"<b>{svc['type']}</b>")
            badge.setStyleSheet(
                "background-color: #3574b0; color: white; padding: 2px 8px;"
                "border-radius: 3px; font-size: 11px;"
            )
            badge.setFixedWidth(50)
            badge.setAlignment(Qt.AlignCenter)
            name_label = QLabel(f"<b>{svc['name']}</b>")
            header.addWidget(badge)
            header.addWidget(name_label)
            header.addStretch()
            group_layout.addLayout(header)

            desc = QLabel(tr(svc["desc_key"]))
            desc.setWordWrap(True)
            desc.setStyleSheet("color: #555; margin-left: 20px;")
            group_layout.addWidget(desc)

            layout.addWidget(group)

        layout.addStretch()

        note = QLabel(tr("onboard.services.note"))
        note.setWordWrap(True)
        layout.addWidget(note)


# =========================================================================
# Page 5 — Resume
# =========================================================================
class SummaryPage(QWizardPage):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle(tr("onboard.summary.title"))
        self.setSubTitle(tr("onboard.summary.subtitle"))
        self._layout = QVBoxLayout(self)
        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._layout.addWidget(self._summary_label)
        self._layout.addStretch()

    def set_summary(self, text: str):
        self._summary_label.setText(text)


# =========================================================================
# Wizard principal
# =========================================================================
class OnboardingWizard(QWizard):

    PAGE_USER = 0
    PAGE_PLUGINS = 1
    PAGE_RESOURCE_SHARING = 2
    PAGE_SERVICES = 3
    PAGE_SUMMARY = 4

    def __init__(
        self,
        parent,
        username: str,
        user_id: str,
        is_new_user: bool,
        db_conn=None,
        email_domain: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle(tr("wizard.title"))
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        self.setWizardStyle(QWizard.ModernStyle)

        self._username = username
        self._user_id = user_id
        self._db_conn = db_conn
        self._actions_done: list[str] = []

        self._page_user = UserProfilePage(username, user_id, is_new_user, email_domain=email_domain)
        self._page_plugins = PluginBundlePage()
        self._page_rs = ResourceSharingPage()
        self._page_services = ExternalServicesPage()
        self._page_summary = SummaryPage()

        self.setPage(self.PAGE_USER, self._page_user)
        self.setPage(self.PAGE_PLUGINS, self._page_plugins)
        self.setPage(self.PAGE_RESOURCE_SHARING, self._page_rs)
        self.setPage(self.PAGE_SERVICES, self._page_services)
        self.setPage(self.PAGE_SUMMARY, self._page_summary)

        self.currentIdChanged.connect(self._on_page_changed)

    def _on_page_changed(self, page_id: int):
        if page_id == self.PAGE_SUMMARY:
            self._execute_actions()

    def _execute_actions(self):
        self._actions_done.clear()

        self._update_user_profile()
        self._install_selected_plugins()

        if self._page_rs.should_configure():
            self._configure_resource_sharing()

        QgsSettings().setValue("constructel_bridge/onboarding_done", True)
        self._actions_done.append(tr("onboard.action.onboarding_done"))

        summary = tr("onboard.summary.header")
        for action in self._actions_done:
            summary += f"<li>{action}</li>"
        summary += tr("onboard.summary.footer")
        self._page_summary.set_summary(summary)

    def _update_user_profile(self):
        if not self._db_conn or self._db_conn.closed:
            return

        first_name = self._page_user._firstname_edit.text().strip()
        last_name = self._page_user._lastname_edit.text().strip()
        email = self._page_user._email_edit.text().strip()

        if not last_name or not email:
            return

        cur = self._db_conn.cursor()
        try:
            cur.execute(
                """
                UPDATE ref.users
                SET last_name = %s,
                    first_name = NULLIF(%s, ''),
                    email = %s,
                    last_login = NOW()
                WHERE username = %s
                """,
                (last_name, first_name, email, self._username),
            )
            self._actions_done.append(
                tr("onboard.action.profile_updated",
                   first_name=first_name, last_name=last_name, email=email)
            )
            self._log(f"Profile updated: {self._username}")
        except Exception as exc:
            self._actions_done.append(tr("onboard.action.profile_error", error=exc))
            self._log(f"Profile update error: {exc}", Qgis.Warning)
        finally:
            cur.close()

    def _install_selected_plugins(self):
        selected = self._page_plugins.get_selected_plugins()
        if not selected:
            self._actions_done.append(tr("onboard.action.no_plugins"))
            return

        try:
            from pyplugin_installer import instance as plugin_installer_instance
            installer = plugin_installer_instance()
            installer.fetchAvailablePlugins(False)
        except Exception as exc:
            self._actions_done.append(
                tr("onboard.action.installer_unavailable", error=exc)
            )
            self._log(f"pyplugin_installer unavailable: {exc}", Qgis.Warning)
            return

        for pid in selected:
            try:
                if pid in available_plugins and pid in active_plugins:
                    continue

                if pid in available_plugins and pid not in active_plugins:
                    loadPlugin(pid)
                    startPlugin(pid)
                    self._actions_done.append(tr("onboard.action.plugin_activated", pid=pid))
                    self._log(f"Plugin activated: {pid}")
                else:
                    installer.installPlugin(pid)
                    self._actions_done.append(tr("onboard.action.plugin_installed", pid=pid))
                    self._log(f"Plugin installed: {pid}")
            except Exception as exc:
                self._actions_done.append(tr("onboard.action.plugin_error", pid=pid, error=exc))
                self._log(f"Plugin error {pid}: {exc}", Qgis.Warning)

    def _configure_resource_sharing(self):
        rs_available = (
            "qgis_resource_sharing" in available_plugins
            or "qgis_resource_sharing" in active_plugins
        )
        if not rs_available:
            self._actions_done.append(tr("onboard.action.rs_not_installed"))
            return

        settings = QgsSettings()
        base = "ResourceSharing/repositories"
        repo_exists = False
        max_index = -1

        settings.beginGroup(base)
        groups = settings.childGroups()
        settings.endGroup()

        for group in groups:
            try:
                idx = int(group)
                if idx > max_index:
                    max_index = idx
            except ValueError:
                continue

            name = settings.value(f"{base}/{group}/name", "")
            url = settings.value(f"{base}/{group}/url", "")
            if name == RESOURCE_SHARING_REPO_NAME or url == RESOURCE_SHARING_REPO_URL:
                repo_exists = True
                if name == RESOURCE_SHARING_REPO_NAME and url != RESOURCE_SHARING_REPO_URL:
                    settings.setValue(f"{base}/{group}/url", RESOURCE_SHARING_REPO_URL)
                    self._actions_done.append(
                        tr("onboard.action.rs_updated",
                           name=RESOURCE_SHARING_REPO_NAME, url=RESOURCE_SHARING_REPO_URL)
                    )
                else:
                    self._actions_done.append(
                        tr("onboard.action.rs_exists", name=RESOURCE_SHARING_REPO_NAME)
                    )
                break

        if not repo_exists:
            new_index = max_index + 1
            settings.setValue(f"{base}/{new_index}/name", RESOURCE_SHARING_REPO_NAME)
            settings.setValue(f"{base}/{new_index}/url", RESOURCE_SHARING_REPO_URL)
            settings.setValue(f"{base}/{new_index}/auth_cfg", "")
            self._actions_done.append(
                tr("onboard.action.rs_added",
                   name=RESOURCE_SHARING_REPO_NAME, url=RESOURCE_SHARING_REPO_URL)
            )
            self._log(f"Resource Sharing: repo added (index={new_index})")

    def _log(self, message: str, level=Qgis.Info):
        QgsMessageLog.logMessage(message, TAG, level=level)
