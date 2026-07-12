"""Main application window: keyboard-navigable sidebar + page stack.

Navigation uses a QListWidget rather than a custom-drawn sidebar because
Qt's built-in item view already gives correct Up/Down arrow-key navigation
and per-item accessible names for free -- a hand-rolled equivalent tends to
break screen-reader row announcements (see docs/DESIGN.md section 7).
"""

from __future__ import annotations

import asyncio
import webbrowser

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QWidget,
)
from qasync import asyncSlot

from gcm import __version__
from gcm.auth.auth_manager import AuthManager
from gcm.config import load_config
from gcm.graph.capabilities import TenantCapabilities, detect_capabilities
from gcm.graph.client import build_graph_client
from gcm.services import audit_log, updater
from gcm.services.graph_errors import friendly_error_message
from gcm.ui.login_dialog import LoginDialog
from gcm.ui.pages.audit_log_page import AuditLogPage
from gcm.ui.pages.bulk_import_page import BulkImportPage
from gcm.ui.pages.devices_page import DevicesPage
from gcm.ui.pages.exchange_page import ExchangePage
from gcm.ui.pages.groups_page import GroupsPage
from gcm.ui.pages.intune_page import IntunePage
from gcm.ui.pages.licensing_page import LicensingPage
from gcm.ui.pages.roles_page import RolesPage
from gcm.ui.pages.sign_in_logs_page import SignInLogsPage
from gcm.ui.pages.users_page import UsersPage
from gcm.ui.settings_dialog import SettingsDialog
from gcm.ui.widgets.live_region import announce

# (nav label, page factory) for the always-present core pages.
_CORE_PAGES = [
    ("Users", UsersPage),
    ("Groups", GroupsPage),
    ("Devices", DevicesPage),
    ("Licensing", LicensingPage),
    ("Roles (RBAC)", RolesPage),
    ("Bulk import", BulkImportPage),
    ("Audit log", AuditLogPage),
]


class _UncancellableProgressDialog(QProgressDialog):
    """A QProgressDialog for an operation that can't safely be interrupted
    once started (self-replacing the running executable). setCancelButton(None)
    alone only hides the button -- QProgressDialog still treats Escape (and the
    window's close button) as cancel/close, which would mislead the user into
    thinking they'd stopped something that's still running in the background."""

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        event.ignore()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Graphical Cloud Manager")
        self._auth_manager: AuthManager | None = None
        self._graph_client = None

        self.nav_list = QListWidget()
        self.nav_list.setAccessibleName("Section navigation")
        self.nav_list.setAccessibleDescription(
            "Choose a management section. Use the Up and Down arrow keys to move between sections."
        )

        self.page_stack = QStackedWidget()
        self.page_stack.setAccessibleName("Section content")

        splitter = QSplitter()
        splitter.addWidget(self.nav_list)
        splitter.addWidget(self.page_stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)

        self.nav_list.currentRowChanged.connect(self.page_stack.setCurrentIndex)

        self._build_menu()

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self.connection_label = self._make_status_label()
        status_bar.addWidget(self.connection_label)

        self._add_core_pages()
        self.set_capabilities(TenantCapabilities(has_intune=False, has_exchange=False, has_audit_logs=False))
        self.set_connected(False)

        # Silent background check a couple seconds after startup; failures
        # and "already up to date" are only shown when triggered manually via
        # Help > Check for Updates.
        QTimer.singleShot(2000, lambda: self._check_for_updates(interactive=False))

    def _make_status_label(self) -> QLabel:
        label = QLabel("Not connected")
        label.setAccessibleName("Connection status")
        return label

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        app_menu = menu_bar.addMenu("&Tenant")

        # Qt's default MenuRole is TextHeuristicRole, which scans an action's
        # text for words like "settings"/"preferences" and silently moves it
        # to the platform application menu on macOS (next to the Apple logo)
        # instead of leaving it in the menu we put it in. NoRole disables
        # that so Settings stays in the Tenant menu on every platform.
        self.settings_action = app_menu.addAction("&Settings...")
        self.settings_action.setMenuRole(QAction.MenuRole.NoRole)
        self.settings_action.setShortcut("Ctrl+,")
        self.settings_action.triggered.connect(self._on_settings_triggered)

        self.sign_in_action = app_menu.addAction("Sign &in...")
        self.sign_in_action.setMenuRole(QAction.MenuRole.NoRole)
        self.sign_in_action.setShortcut("Ctrl+Shift+I")
        self.sign_in_action.triggered.connect(self._on_sign_in_triggered)

        self.sign_out_action = app_menu.addAction("Sign &out")
        self.sign_out_action.setMenuRole(QAction.MenuRole.NoRole)
        self.sign_out_action.setShortcut("Ctrl+Shift+O")
        self.sign_out_action.setEnabled(False)
        self.sign_out_action.triggered.connect(self._on_sign_out_triggered)

        app_menu.addSeparator()

        # Left at the default heuristic role on purpose: "Exit" gets moved to
        # "Quit GraphicalCloudManager" under the macOS app menu, which is
        # exactly where Mac users expect quit to live (unlike Settings above).
        exit_action = app_menu.addAction("E&xit")
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)

        help_menu = menu_bar.addMenu("&Help")
        check_updates_action = help_menu.addAction("Check for &Updates...")
        check_updates_action.setMenuRole(QAction.MenuRole.NoRole)
        check_updates_action.triggered.connect(
            lambda: self._check_for_updates(interactive=True))

    def _on_settings_triggered(self) -> None:
        SettingsDialog(self).exec()

    @asyncSlot()
    async def _on_sign_in_triggered(self) -> None:
        config = load_config()
        if config is None:
            QMessageBox.information(
                self,
                "Tenant not configured",
                "Set a Tenant ID and Client ID first via Tenant > Settings...",
            )
            return

        dialog = LoginDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        profile_name = dialog.profile_name() or "default"

        announce(self.connection_label, f"Signing in to {profile_name}...")
        loop = asyncio.get_event_loop()
        try:
            auth_manager = AuthManager(profile_name, config)
            # MSAL's interactive flow opens a system browser and blocks on a
            # local redirect listener -- run it off the UI thread so the
            # window stays responsive while the admin signs in.
            result = await loop.run_in_executor(None, auth_manager.sign_in_interactive)
        except Exception as exc:  # MSAL/network/config errors -- surface, don't crash
            self.set_connected(False)
            QMessageBox.critical(self, "Sign-in failed", friendly_error_message(exc))
            return

        self._auth_manager = auth_manager
        self.set_connected(True, result.account_username)
        audit_log.set_actor(result.account_username)

        self._graph_client = build_graph_client(auth_manager)
        self.users_page.set_graph_client(self._graph_client)
        self.groups_page.set_graph_client(self._graph_client)
        self.devices_page.set_graph_client(self._graph_client)
        self.licensing_page.set_graph_client(self._graph_client)
        self.roles_page.set_graph_client(self._graph_client)
        self.bulk_import_page.set_graph_client(self._graph_client)

        try:
            capabilities = await detect_capabilities(self._graph_client)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Capability detection failed",
                "Signed in, but couldn't determine which products this tenant has: "
                f"{friendly_error_message(exc)}",
            )
            capabilities = TenantCapabilities(has_intune=False, has_exchange=False, has_audit_logs=False)
        self.set_capabilities(capabilities)

    def _on_sign_out_triggered(self) -> None:
        if self._auth_manager is not None:
            self._auth_manager.sign_out()
            self._auth_manager = None
        self._graph_client = None
        self.users_page.set_graph_client(None)
        self.groups_page.set_graph_client(None)
        self.devices_page.set_graph_client(None)
        self.licensing_page.set_graph_client(None)
        self.roles_page.set_graph_client(None)
        self.bulk_import_page.set_graph_client(None)
        self.set_connected(False)
        self.set_capabilities(TenantCapabilities(has_intune=False, has_exchange=False, has_audit_logs=False))

    # -- auto-update ------------------------------------------------------- #
    @asyncSlot()
    async def _check_for_updates(self, interactive: bool = False) -> None:
        if getattr(self, "_update_busy", False):
            if interactive:
                QMessageBox.information(
                    self, "Check for Updates",
                    "An update check is already in progress.")
            return
        self._update_busy = True
        try:
            loop = asyncio.get_event_loop()
            release = await loop.run_in_executor(
                None, updater.check_latest_release, __version__)
        except Exception as exc:  # noqa: BLE001 - surface any failure
            self._update_busy = False
            if interactive:
                QMessageBox.critical(
                    self, "Check for Updates",
                    f"Couldn't check for updates: {friendly_error_message(exc)}")
            return

        if release is None:
            self._update_busy = False
            if interactive:
                QMessageBox.information(
                    self, "Check for Updates",
                    f"You're up to date (version {__version__}).")
            return

        notes = release.notes or "No release notes provided."
        reply = QMessageBox.question(
            self, "Update available",
            f"Version {release.version} is available (you have {__version__}).\n\n"
            f"{notes}\n\nUpdate now?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            self._update_busy = False
            return

        if not updater.is_frozen():
            self._update_busy = False
            QMessageBox.information(
                self, "Update available",
                "Running from source, so this build can't update itself.\n\n"
                "Opening the release page in your browser...")
            webbrowser.open(updater.RELEASES_PAGE_URL)
            return

        if not release.asset_url:
            self._update_busy = False
            QMessageBox.critical(
                self, "Update available",
                "No download is available for this platform yet.\n\n"
                "Opening the release page in your browser...")
            webbrowser.open(updater.RELEASES_PAGE_URL)
            return

        await self._start_self_update(release)

    async def _start_self_update(self, release) -> None:
        # There is no safe way to cancel mid-self-replace, so refuse Escape
        # and the window close button rather than let the user think they
        # stopped something that's still running in the background.
        progress = _UncancellableProgressDialog(
            f"Downloading version {release.version}...", None, 0, 0, self)
        progress.setWindowTitle("Updating...")
        progress.setAccessibleName("Update download progress")
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()

        loop = asyncio.get_event_loop()
        try:
            # perform_self_update calls os._exit(0) on success -- it never
            # returns here when it works, so the process just quits mid-await.
            await loop.run_in_executor(None, updater.perform_self_update, release)
        except Exception as exc:  # noqa: BLE001 - surface any failure
            self._update_busy = False
            progress.close()
            QMessageBox.critical(
                self, "Update failed",
                f"Couldn't install the update: {friendly_error_message(exc)}\n\n"
                "Opening the release page in your browser so you can download "
                "it manually...")
            webbrowser.open(updater.RELEASES_PAGE_URL)

    def _add_core_pages(self) -> None:
        for label, page_cls in _CORE_PAGES:
            item = QListWidgetItem(label)
            self.nav_list.addItem(item)
            page = page_cls()
            self.page_stack.addWidget(page)
            if label == "Users":
                self.users_page = page
            elif label == "Groups":
                self.groups_page = page
            elif label == "Devices":
                self.devices_page = page
            elif label == "Licensing":
                self.licensing_page = page
            elif label == "Roles (RBAC)":
                self.roles_page = page
            elif label == "Bulk import":
                self.bulk_import_page = page
            elif label == "Audit log":
                self.audit_log_page = page
        self.nav_list.setCurrentRow(0)

    def set_capabilities(self, capabilities: TenantCapabilities) -> None:
        """Add/remove the Intune/Exchange/Sign-in-logs nav entries based on
        what the connected tenant is actually licensed for."""
        self.users_page.set_has_audit_logs(capabilities.has_audit_logs)
        self.devices_page.set_has_intune(capabilities.has_intune)
        self._remove_optional_page("Intune")
        self._remove_optional_page("Exchange")
        self._remove_optional_page("Sign-in logs")

        if capabilities.has_intune:
            intune_page = IntunePage()
            intune_page.set_graph_client(self._graph_client)
            self._add_optional_page("Intune", intune_page)
        if capabilities.has_exchange:
            exchange_page = ExchangePage()
            exchange_page.set_graph_client(self._graph_client)
            self._add_optional_page("Exchange", exchange_page)
        if capabilities.has_audit_logs:
            sign_in_logs_page = SignInLogsPage()
            sign_in_logs_page.set_graph_client(self._graph_client)
            self._add_optional_page("Sign-in logs", sign_in_logs_page)

    def _add_optional_page(self, label: str, page: QWidget) -> None:
        item = QListWidgetItem(label)
        self.nav_list.addItem(item)
        self.page_stack.addWidget(page)

    def _remove_optional_page(self, label: str) -> None:
        for row in range(self.nav_list.count()):
            if self.nav_list.item(row).text() == label:
                widget = self.page_stack.widget(row)
                self.nav_list.takeItem(row)
                self.page_stack.removeWidget(widget)
                widget.deleteLater()
                break

    def set_connected(self, connected: bool, profile_name: str = "") -> None:
        self.sign_in_action.setEnabled(not connected)
        self.sign_out_action.setEnabled(connected)
        message = f"Connected to {profile_name}" if connected else "Not connected"
        announce(self.connection_label, message)
