"""Main application window: keyboard-navigable sidebar + page stack.

Navigation uses a QListWidget rather than a custom-drawn sidebar because
Qt's built-in item view already gives correct Up/Down arrow-key navigation
and per-item accessible names for free -- a hand-rolled equivalent tends to
break screen-reader row announcements (see docs/DESIGN.md section 7).
"""

from __future__ import annotations

import asyncio
import webbrowser

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QAction, QDesktopServices
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
from gcm.auth.google_auth_manager import GoogleAuthManager
from gcm.config import error_log_path, load_config, load_google_config
from gcm.google.client import build_directory_client, build_reports_client
from gcm.graph.capabilities import TenantCapabilities, detect_capabilities
from gcm.graph.client import build_graph_client
from gcm.services import audit_log, updater
from gcm.services.error_log import log_asyncio_exception
from gcm.services.graph_errors import friendly_error_message
from gcm.ui.google_settings_dialog import GoogleSettingsDialog
from gcm.ui.login_dialog import LoginDialog
from gcm.ui.pages.audit_log_page import AuditLogPage
from gcm.ui.pages.bulk_import_page import BulkImportPage
from gcm.ui.pages.devices_page import DevicesPage
from gcm.ui.pages.exchange_page import ExchangePage
from gcm.ui.pages.google_admin_audit_page import GoogleAdminAuditPage
from gcm.ui.pages.google_devices_page import GoogleDevicesPage
from gcm.ui.pages.google_groups_page import GoogleGroupsPage
from gcm.ui.pages.google_mailbox_page import GoogleMailboxPage
from gcm.ui.pages.google_sign_in_logs_page import GoogleSignInLogsPage
from gcm.ui.pages.google_users_page import GoogleUsersPage
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

# Always-present Google Workspace pages -- added alongside _CORE_PAGES at
# startup (not dynamically shown/hidden on Google sign-in/out) so they
# behave the same as the Microsoft core pages: visible immediately, showing
# an empty "sign in to view" state until set_directory_client(...) is called.
_GOOGLE_PAGES = [
    ("Google Users", GoogleUsersPage),
    ("Google Groups", GoogleGroupsPage),
    ("Google Devices", GoogleDevicesPage),
    ("Google Mailbox", GoogleMailboxPage),
    ("Google Sign-in logs", GoogleSignInLogsPage),
    ("Google Admin audit log", GoogleAdminAuditPage),
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
        self._google_auth_manager: GoogleAuthManager | None = None
        self._directory_client = None
        self._reports_client = None
        # Reused across calls rather than creating a new QMessageBox per
        # exception, so a burst of background failures updates one visible
        # notification instead of piling up separate windows.
        self._error_notice_box: QMessageBox | None = None

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
        self.google_connection_label = self._make_status_label()
        self.google_connection_label.setAccessibleName("Google Workspace connection status")
        status_bar.addWidget(self.google_connection_label)

        self._add_core_pages()
        self._add_google_pages()
        self.set_capabilities(TenantCapabilities(has_intune=False, has_exchange=False, has_audit_logs=False))
        self.set_connected(False)
        self.set_google_connected(False)

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

        google_menu = menu_bar.addMenu("&Google Workspace")

        self.google_settings_action = google_menu.addAction("&Settings...")
        self.google_settings_action.setMenuRole(QAction.MenuRole.NoRole)
        self.google_settings_action.triggered.connect(self._on_google_settings_triggered)

        self.google_sign_in_action = google_menu.addAction("Sign &in...")
        self.google_sign_in_action.setMenuRole(QAction.MenuRole.NoRole)
        self.google_sign_in_action.triggered.connect(self._on_google_sign_in_triggered)

        self.google_sign_out_action = google_menu.addAction("Sign &out")
        self.google_sign_out_action.setMenuRole(QAction.MenuRole.NoRole)
        self.google_sign_out_action.setEnabled(False)
        self.google_sign_out_action.triggered.connect(self._on_google_sign_out_triggered)

        help_menu = menu_bar.addMenu("&Help")
        check_updates_action = help_menu.addAction("Check for &Updates...")
        check_updates_action.setMenuRole(QAction.MenuRole.NoRole)
        check_updates_action.triggered.connect(
            lambda: self._check_for_updates(interactive=True))

        open_error_log_action = help_menu.addAction("Open &Error Log")
        open_error_log_action.setMenuRole(QAction.MenuRole.NoRole)
        open_error_log_action.triggered.connect(self._on_open_error_log_triggered)

    def _on_open_error_log_triggered(self) -> None:
        path = error_log_path()
        # Nothing's been logged yet if the file doesn't exist -- open its
        # parent folder instead of an error dialog about a missing file, so
        # this is never wrong to click, just sometimes empty.
        target = path if path.exists() else path.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

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

        # Block a second concurrent sign-in attempt (e.g. the menu action
        # clicked again, or via its shortcut) while this one's interactive
        # MSAL flow is still awaiting -- two at once could race to assign
        # self._auth_manager/self._graph_client, leaving pages wired to
        # whichever finished last while audit_log's actor doesn't match.
        self.sign_in_action.setEnabled(False)
        dialog = LoginDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.sign_in_action.setEnabled(True)
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
        try:
            if self._auth_manager is not None:
                self._auth_manager.sign_out()
        finally:
            # However sign_out() goes, the UI must not end up in a torn
            # state that still claims to be connected to a signed-out
            # account -- clear our side unconditionally.
            self._auth_manager = None
            self._graph_client = None
            self.users_page.set_graph_client(None)
            self.groups_page.set_graph_client(None)
            self.devices_page.set_graph_client(None)
            self.licensing_page.set_graph_client(None)
            self.roles_page.set_graph_client(None)
            self.bulk_import_page.set_graph_client(None)
            self.set_connected(False)
            self.set_capabilities(
                TenantCapabilities(has_intune=False, has_exchange=False, has_audit_logs=False))

    def _on_google_settings_triggered(self) -> None:
        dialog = GoogleSettingsDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Mailbox admin depends only on the service account path just
            # saved, not on the interactive Google sign-in state -- re-check
            # it now rather than waiting for a restart.
            self.google_mailbox_page.refresh_configuration()

    @asyncSlot()
    async def _on_google_sign_in_triggered(self) -> None:
        config = load_google_config()
        if config is None:
            QMessageBox.information(
                self,
                "Google Workspace not configured",
                "Set a Client ID and Client Secret first via "
                "Google Workspace > Settings...",
            )
            return

        # Same reasoning as _on_sign_in_triggered: block a second concurrent
        # attempt while this one's interactive OAuth flow is still awaiting.
        self.google_sign_in_action.setEnabled(False)
        dialog = LoginDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.google_sign_in_action.setEnabled(True)
            return
        profile_name = dialog.profile_name() or "default"

        announce(self.google_connection_label, f"Signing in to {profile_name}...")
        loop = asyncio.get_event_loop()
        try:
            google_auth_manager = GoogleAuthManager(profile_name, config)
            # InstalledAppFlow's local-server flow opens a system browser and
            # blocks on a local redirect listener -- run it off the UI thread
            # the same way the MSAL interactive flow is run above.
            result = await loop.run_in_executor(None, google_auth_manager.sign_in_interactive)
        except Exception as exc:  # OAuth/network/config errors -- surface, don't crash
            self.set_google_connected(False)
            QMessageBox.critical(self, "Sign-in failed", friendly_error_message(exc))
            return

        self._google_auth_manager = google_auth_manager
        self.set_google_connected(True, result.account_email)
        self._directory_client = build_directory_client(google_auth_manager)
        self._reports_client = build_reports_client(google_auth_manager)
        self.google_users_page.set_directory_client(self._directory_client)
        self.google_groups_page.set_directory_client(self._directory_client)
        self.google_devices_page.set_directory_client(self._directory_client)
        self.google_sign_in_logs_page.set_reports_client(self._reports_client)
        self.google_admin_audit_page.set_reports_client(self._reports_client)

    def _on_google_sign_out_triggered(self) -> None:
        try:
            if self._google_auth_manager is not None:
                self._google_auth_manager.sign_out()
        finally:
            # Same reasoning as _on_sign_out_triggered: whatever sign_out()
            # does, don't leave the UI claiming to be connected afterward.
            self._google_auth_manager = None
            self._directory_client = None
            self._reports_client = None
            self.google_users_page.set_directory_client(None)
            self.google_groups_page.set_directory_client(None)
            self.google_devices_page.set_directory_client(None)
            self.google_sign_in_logs_page.set_reports_client(None)
            self.google_admin_audit_page.set_reports_client(None)
            self.set_google_connected(False)

    def on_asyncio_exception(self, loop, context: dict) -> None:
        """Registered as the qasync event loop's exception handler in
        app.py. Logs the same way error_log.log_asyncio_exception always
        has, and additionally surfaces a non-modal notification -- without
        this, an exception an @asyncSlot's own try/except didn't catch was
        previously only ever visible by checking Help > Open Error Log."""
        log_asyncio_exception(loop, context)
        exc = context.get("exception")
        summary = str(exc) if exc is not None else context.get("message", "An unexpected error occurred")
        if self._error_notice_box is None:
            self._error_notice_box = QMessageBox(self)
            self._error_notice_box.setWindowTitle("Unexpected error")
            self._error_notice_box.setIcon(QMessageBox.Icon.Warning)
        self._error_notice_box.setText(
            "Something unexpected went wrong in the background:\n\n"
            f"{summary}\n\n"
            "Details were written to the error log (Help > Open Error Log)."
        )
        # Non-modal: a background failure shouldn't block the UI the way a
        # QMessageBox.exec() would, and re-showing an already-open box just
        # updates its text instead of stacking a new window.
        self._error_notice_box.show()

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

    def _add_google_pages(self) -> None:
        for label, page_cls in _GOOGLE_PAGES:
            item = QListWidgetItem(label)
            self.nav_list.addItem(item)
            page = page_cls()
            self.page_stack.addWidget(page)
            if label == "Google Users":
                self.google_users_page = page
            elif label == "Google Groups":
                self.google_groups_page = page
            elif label == "Google Devices":
                self.google_devices_page = page
            elif label == "Google Mailbox":
                self.google_mailbox_page = page
            elif label == "Google Sign-in logs":
                self.google_sign_in_logs_page = page
            elif label == "Google Admin audit log":
                self.google_admin_audit_page = page

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

    def set_google_connected(self, connected: bool, profile_name: str = "") -> None:
        self.google_sign_in_action.setEnabled(not connected)
        self.google_sign_out_action.setEnabled(connected)
        message = f"Google: connected to {profile_name}" if connected else "Google: not connected"
        announce(self.google_connection_label, message)
