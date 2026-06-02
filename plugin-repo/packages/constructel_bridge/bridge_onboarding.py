# -*- coding: utf-8 -*-
"""
Constructel Bridge - Wizard d'onboarding.

Affiche apres la premiere connexion reussie:
  Page 1: Creation / confirmation du profil utilisateur
  Page 2: Plugins recommandes (facultatifs) avec bouton d'installation
  Page 3: Configuration QGIS Resource Sharing (repo Constructel)
  Page 4: Resume et finalisation
"""

import json
import os
import platform
import re
import shutil

from qgis.PyQt.QtCore import Qt, QCoreApplication
from qgis.PyQt.QtGui import QCursor, QFont
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsSettings
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
        "id": "StreetViewPro",
        "name": "StreetView Pro",
        "desc_key": "plugin.streetview.desc",
    },
    {
        "id": "plugin_reloader",
        "name": "Plugin Reloader",
        "desc_key": "plugin.reloader.desc",
    },
]

RESOURCE_SHARING_REPO_NAME = "Constructel"
RESOURCE_SHARING_REPO_URL = os.environ.get(
    "CONSTRUCTEL_RESOURCE_REPO_URL", "http://192.168.160.31:9081/"
)

# FilterMate favorites_sharing — Constructel git smart-HTTP server on port 9082.
# The bare repo at server root holds the resource-repo tree; collection layout:
#   collections/<target_collection>/filter_mate/favorites/*.fmfav-pack.json
FILTERMATE_REPO_NAME = "Constructel"
FILTERMATE_REPO_GIT_URL = os.environ.get(
    "CONSTRUCTEL_FILTERMATE_GIT_URL", "http://192.168.160.31:9082/"
)
FILTERMATE_REPO_BRANCH = os.environ.get("CONSTRUCTEL_FILTERMATE_BRANCH", "master")
FILTERMATE_TARGET_COLLECTION = os.environ.get(
    "CONSTRUCTEL_FILTERMATE_COLLECTION", "filtermate"
)


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

        page_layout = QVBoxLayout(self)
        self._checkboxes: dict[str, QCheckBox] = {}

        # Scrollable container for the plugin list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)

        installed = set(available_plugins)

        for plugin in RECOMMENDED_PLUGINS:
            pid = plugin["id"]
            already = pid in installed
            active = pid in active_plugins

            group = QGroupBox()
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(6, 4, 6, 4)
            group_layout.setSpacing(2)

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
        scroll.setWidget(container)
        page_layout.addWidget(scroll)

        note = QLabel(tr("onboard.plugins.note"))
        note.setWordWrap(True)
        page_layout.addWidget(note)

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
# Page 4 — Partage FilterMate (favoris via git Constructel)
# =========================================================================
class FilterMateSharingPage(QWizardPage):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTitle(tr("onboard.fm.title"))
        self.setSubTitle(tr("onboard.fm.subtitle"))

        layout = QVBoxLayout(self)

        self._fm_installed = "filter_mate" in available_plugins
        info = QLabel(
            tr("onboard.fm.installed") if self._fm_installed
            else tr("onboard.fm.not_installed")
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()

        self._repo_name = QLineEdit(FILTERMATE_REPO_NAME)
        self._repo_name.setReadOnly(True)
        form.addRow(tr("onboard.fm.repo_name"), self._repo_name)

        self._repo_url = QLineEdit(FILTERMATE_REPO_GIT_URL)
        self._repo_url.setReadOnly(True)
        form.addRow(tr("onboard.fm.repo_url"), self._repo_url)

        self._branch = QLineEdit(FILTERMATE_REPO_BRANCH)
        self._branch.setReadOnly(True)
        form.addRow(tr("onboard.fm.branch"), self._branch)

        self._collection = QLineEdit(FILTERMATE_TARGET_COLLECTION)
        self._collection.setReadOnly(True)
        form.addRow(tr("onboard.fm.collection"), self._collection)

        layout.addLayout(form)

        self._cb_configure = QCheckBox(tr("onboard.fm.auto_configure"))
        self._cb_configure.setChecked(self._fm_installed)
        self._cb_configure.setEnabled(self._fm_installed)
        layout.addWidget(self._cb_configure)

        desc = QLabel(tr("onboard.fm.note"))
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addStretch()

    def should_configure(self) -> bool:
        return self._cb_configure.isChecked()


# =========================================================================
# Page 5 — Services externes (WMTS / XYZ / WFS)
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
    PAGE_FILTERMATE = 3
    PAGE_SERVICES = 4
    PAGE_SUMMARY = 5

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
        self._page_fm = FilterMateSharingPage()
        self._page_services = ExternalServicesPage()
        self._page_summary = SummaryPage()

        self.setPage(self.PAGE_USER, self._page_user)
        self.setPage(self.PAGE_PLUGINS, self._page_plugins)
        self.setPage(self.PAGE_RESOURCE_SHARING, self._page_rs)
        self.setPage(self.PAGE_FILTERMATE, self._page_fm)
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

        if self._page_fm.should_configure():
            self._configure_filtermate_sharing()

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

    def _ensure_filtermate_git_binary(self) -> str:
        sys_git = shutil.which("git")
        if sys_git:
            self._actions_done.append(tr("onboard.action.fm_git_system", path=sys_git))
            return sys_git

        profile_tools = os.path.join(
            QgsApplication.qgisSettingsDirPath(), "FilterMate", "tools"
        )
        portable_exe = os.path.join(profile_tools, "PortableGit", "cmd", "git.exe")
        if os.path.isfile(portable_exe):
            self._actions_done.append(tr("onboard.action.fm_git_portable_existing", path=portable_exe))
            return portable_exe

        if platform.system() != "Windows":
            self._actions_done.append(tr("onboard.action.fm_git_missing_unix"))
            return ""

        try:
            from filter_mate.extensions.favorites_sharing.portable_git_installer import (
                download_and_install,
                is_supported_platform,
            )
        except Exception as exc:
            self._actions_done.append(tr("onboard.action.fm_git_installer_missing", error=exc))
            self._log(f"FilterMate portable_git_installer import error: {exc}", Qgis.Warning)
            return ""

        if not is_supported_platform():
            self._actions_done.append(tr("onboard.action.fm_git_unsupported"))
            return ""

        QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        try:
            os.makedirs(profile_tools, exist_ok=True)
            self._page_summary.set_summary(tr("onboard.action.fm_git_downloading"))
            QCoreApplication.processEvents()

            def _progress(downloaded: int, total):
                if total:
                    pct = max(0, min(100, int(downloaded * 100 / total)))
                    self._page_summary.set_summary(
                        tr("onboard.action.fm_git_downloading_pct", pct=pct)
                    )
                QCoreApplication.processEvents()

            result = download_and_install(profile_tools, progress_callback=_progress)
            self._actions_done.append(
                tr("onboard.action.fm_git_installed", path=result.git_executable)
            )
            self._log(f"Portable git installed: {result.git_executable}")
            return result.git_executable
        except Exception as exc:
            self._actions_done.append(tr("onboard.action.fm_git_install_failed", error=exc))
            self._log(f"Portable git install failed: {exc}", Qgis.Warning)
            return ""
        finally:
            QApplication.restoreOverrideCursor()

    def _configure_filtermate_sharing(self):
        if "filter_mate" not in available_plugins and "filter_mate" not in active_plugins:
            self._actions_done.append(tr("onboard.action.fm_not_installed"))
            return

        git_binary = self._ensure_filtermate_git_binary()

        new_entry = {
            "name": FILTERMATE_REPO_NAME,
            "git_url": FILTERMATE_REPO_GIT_URL,
            "branch": FILTERMATE_REPO_BRANCH,
            "local_clone": "",
            "target_collection": FILTERMATE_TARGET_COLLECTION,
            "is_default": True,
            "authcfg_id": "",
            "auth_header": "",
        }

        if self._configure_filtermate_via_api(new_entry, git_binary):
            return
        self._configure_filtermate_via_json(new_entry, git_binary)

    def _configure_filtermate_via_api(self, entry: dict, git_binary: str) -> bool:
        try:
            from filter_mate.extensions.registry import get_extension_registry
            from filter_mate.extensions.favorites_sharing.remote_repo_manager import (
                RemoteRepo,
                RemoteRepoManager,
            )
        except Exception as exc:
            self._log(f"FilterMate API import failed, falling back to JSON: {exc}", Qgis.Info)
            return False

        try:
            registry = get_extension_registry()
            ext = registry.get_extension("favorites_sharing")
            if ext is None:
                self._log(
                    "FilterMate registry returned no 'favorites_sharing' extension; falling back to JSON",
                    Qgis.Info,
                )
                return False

            if git_binary:
                ext.set_config("git_binary_path", git_binary)

            manager = RemoteRepoManager(ext)
            repos = list(manager.list_repos())
            existing = manager.get_by_name(FILTERMATE_REPO_NAME)
            if existing is not None:
                repos = [r for r in repos if r.name != FILTERMATE_REPO_NAME]
                action_msg = tr("onboard.action.fm_updated", url=FILTERMATE_REPO_GIT_URL)
            else:
                action_msg = tr("onboard.action.fm_added", url=FILTERMATE_REPO_GIT_URL)

            for r in repos:
                if getattr(r, "is_default", False):
                    r.is_default = False

            new_repo = RemoteRepo.from_config_entry(entry)
            if new_repo is None:
                self._log("RemoteRepo.from_config_entry returned None; falling back to JSON", Qgis.Warning)
                return False
            repos.append(new_repo)

            if not manager.save_repos(repos):
                self._log("RemoteRepoManager.save_repos returned False; falling back to JSON", Qgis.Warning)
                return False

            self._actions_done.append(action_msg)
            self._log(f"FilterMate sharing configured via API: {FILTERMATE_REPO_GIT_URL}")
            return True
        except Exception as exc:
            self._log(f"FilterMate API configure failed, falling back to JSON: {exc}", Qgis.Warning)
            return False

    @staticmethod
    def _fm_unwrap(raw):
        if isinstance(raw, dict) and "value" in raw:
            return raw["value"]
        return raw

    @staticmethod
    def _fm_wrap(existing, value):
        # Preserve sibling metadata (description, choices, ...) if present.
        if isinstance(existing, dict) and "value" in existing:
            existing["value"] = value
            return existing
        return {"value": value}

    def _configure_filtermate_via_json(self, entry: dict, git_binary: str) -> None:
        config_path = os.path.join(
            QgsApplication.qgisSettingsDirPath(), "FilterMate", "config.json"
        )

        config: dict = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f) or {}
            except Exception as exc:
                self._actions_done.append(tr("onboard.action.fm_read_error", error=exc))
                self._log(f"FilterMate config read error: {exc}", Qgis.Warning)
                return

        extensions = config.setdefault("EXTENSIONS", {})
        fs = extensions.setdefault("favorites_sharing", {})

        # FilterMate stores each config value wrapped as {"value": <data>, ...metadata}.
        # We must read from / write to that wrapper, not the raw key, otherwise
        # FilterMate's get_config() returns the schema default and the repo
        # appears unconfigured.
        repos_wrapped = fs.get("remote_repos")
        repos = self._fm_unwrap(repos_wrapped) or []
        if not isinstance(repos, list):
            self._actions_done.append(
                tr("onboard.action.fm_read_error",
                   error="EXTENSIONS.favorites_sharing.remote_repos n'est pas une liste")
            )
            return

        if git_binary:
            fs["git_binary_path"] = self._fm_wrap(fs.get("git_binary_path"), git_binary)

        existing = next(
            (r for r in repos if isinstance(r, dict) and r.get("name") == FILTERMATE_REPO_NAME),
            None,
        )
        if existing is None:
            for r in repos:
                if isinstance(r, dict) and r.get("is_default"):
                    r["is_default"] = False
            repos.append(entry)
            action_msg = tr("onboard.action.fm_added", url=FILTERMATE_REPO_GIT_URL)
        else:
            existing.update(entry)
            for r in repos:
                if isinstance(r, dict) and r is not existing and r.get("is_default"):
                    r["is_default"] = False
            action_msg = tr("onboard.action.fm_updated", url=FILTERMATE_REPO_GIT_URL)

        fs["remote_repos"] = self._fm_wrap(repos_wrapped, repos)

        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            tmp_path = config_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, config_path)
        except Exception as exc:
            self._actions_done.append(tr("onboard.action.fm_write_error", error=exc))
            self._log(f"FilterMate config write error: {exc}", Qgis.Warning)
            return

        self._actions_done.append(action_msg)
        self._actions_done.append(tr("onboard.action.fm_restart_needed"))
        self._log(f"FilterMate sharing configured via JSON (restart needed): {FILTERMATE_REPO_GIT_URL}")

    def _log(self, message: str, level=Qgis.Info):
        QgsMessageLog.logMessage(message, TAG, level=level)
