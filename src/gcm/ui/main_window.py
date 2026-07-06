"""Main application window: keyboard-navigable sidebar + page stack.

Navigation uses a QListWidget rather than a custom-drawn sidebar because
Qt's built-in item view already gives correct Up/Down arrow-key navigation
and per-item accessible names for free -- a hand-rolled equivalent tends to
break screen-reader row announcements (see docs/DESIGN.md section 7).
"""

from __future__ import annotations

import asyncio

from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QWidget,
)
from qasync import asyncSlot

from gcm.auth.auth_manager import AuthManager
from gcm.config import load_config
from gcm.graph.capabilities import TenantCapabilities, detect_capabilities
from gcm.graph.client import build_graph_client
from gcm.ui.login_dialog import LoginDialog
from gcm.ui.pages.exchange_page import ExchangePage
from gcm.ui.pages.groups_page import GroupsPage
from gcm.ui.pages.intune_page import IntunePage
from gcm.ui.pages.licensing_page import LicensingPage
from gcm.ui.pages.roles_page import RolesPage
from gcm.ui.pages.users_page import UsersPage
from gcm.ui.settings_dialog import SettingsDialog
from gcm.ui.widgets.live_region import announce

# (nav label, page factory) for the always-present core pages.
_CORE_PAGES = [
    ("Users", UsersPage),
    ("Groups", GroupsPage),
    ("Licensing", LicensingPage),
    ("Roles (RBAC)", RolesPage),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Graphical Cloud Manager")
        self._auth_manager: AuthManager | None = None

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
        self.set_capabilities(TenantCapabilities(has_intune=False, has_exchange=False))
        self.set_connected(False)

    def _make_status_label(self) -> QLabel:
        label = QLabel("Not connected")
        label.setAccessibleName("Connection status")
        return label

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        app_menu = menu_bar.addMenu("&Tenant")

        self.settings_action = app_menu.addAction("&Settings...")
        self.settings_action.setShortcut("Ctrl+,")
        self.settings_action.triggered.connect(self._on_settings_triggered)

        self.sign_in_action = app_menu.addAction("Sign &in...")
        self.sign_in_action.setShortcut("Ctrl+Shift+I")
        self.sign_in_action.triggered.connect(self._on_sign_in_triggered)

        self.sign_out_action = app_menu.addAction("Sign &out")
        self.sign_out_action.setShortcut("Ctrl+Shift+O")
        self.sign_out_action.setEnabled(False)
        self.sign_out_action.triggered.connect(self._on_sign_out_triggered)

        app_menu.addSeparator()

        exit_action = app_menu.addAction("E&xit")
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)

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
            QMessageBox.critical(self, "Sign-in failed", str(exc))
            return

        self._auth_manager = auth_manager
        self.set_connected(True, result.account_username)

        try:
            graph_client = build_graph_client(auth_manager)
            capabilities = await detect_capabilities(graph_client)
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Capability detection failed",
                f"Signed in, but couldn't determine which products this tenant has: {exc}",
            )
            capabilities = TenantCapabilities(has_intune=False, has_exchange=False)
        self.set_capabilities(capabilities)

    def _on_sign_out_triggered(self) -> None:
        if self._auth_manager is not None:
            self._auth_manager.sign_out()
            self._auth_manager = None
        self.set_connected(False)
        self.set_capabilities(TenantCapabilities(has_intune=False, has_exchange=False))

    def _add_core_pages(self) -> None:
        for label, page_cls in _CORE_PAGES:
            item = QListWidgetItem(label)
            self.nav_list.addItem(item)
            self.page_stack.addWidget(page_cls())
        self.nav_list.setCurrentRow(0)

    def set_capabilities(self, capabilities: TenantCapabilities) -> None:
        """Add/remove the Intune and Exchange nav entries based on what the
        connected tenant is actually licensed for."""
        self._remove_optional_page("Intune")
        self._remove_optional_page("Exchange")

        if capabilities.has_intune:
            self._add_optional_page("Intune", IntunePage())
        if capabilities.has_exchange:
            self._add_optional_page("Exchange", ExchangePage())

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
