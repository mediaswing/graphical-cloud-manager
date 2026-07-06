"""Users page: list, search, create, enable/disable, and delete Entra users."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from gcm.models.user import UserDetail, UserSummary
from gcm.services.graph_errors import friendly_error_message
from gcm.services.impact_preview import build_user_impact_preview
from gcm.services.user_service import UserService
from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.confirm import confirm_destructive
from gcm.ui.widgets.csv_export_button import CsvExportButton
from gcm.ui.widgets.impact_preview_dialog import ImpactPreviewDialog

_COLUMNS = ["Display name", "User principal name", "Email", "Status"]


class UsersTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._users: list[UserSummary] = []

    def set_users(self, users: list[UserSummary]) -> None:
        self.beginResetModel()
        self._users = users
        self.endResetModel()

    def user_at(self, row: int) -> UserSummary:
        return self._users[row]

    def all_users(self) -> list[UserSummary]:
        return list(self._users)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._users)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        user = self._users[index.row()]
        column = index.column()
        if column == 0:
            return user.display_name
        if column == 1:
            return user.user_principal_name
        if column == 2:
            return user.mail or ""
        if column == 3:
            return "Enabled" if user.account_enabled else "Disabled"
        return None


class NewUserDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New user")
        self.setAccessibleName("New user")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.display_name_edit = QLineEdit()
        self.display_name_edit.setAccessibleName("Display name")
        form.addRow("&Display name", self.display_name_edit)

        self.upn_edit = QLineEdit()
        self.upn_edit.setAccessibleName("User principal name")
        self.upn_edit.setPlaceholderText("e.g. jane.doe@contoso.com")
        form.addRow("&User principal name", self.upn_edit)

        self.mail_nickname_edit = QLineEdit()
        self.mail_nickname_edit.setAccessibleName("Mail nickname")
        form.addRow("&Mail nickname", self.mail_nickname_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setAccessibleName("Temporary password")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("&Temporary password", self.password_edit)

        self.status_label = QLabel("")
        self.status_label.setAccessibleName("New user status")
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        # QDialogButtonBox creates its buttons with visible text only --
        # accessibleName isn't derived from that automatically, so it must
        # be set explicitly like every other control in this app.
        buttons.button(QDialogButtonBox.StandardButton.Ok).setAccessibleName("Create user")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setAccessibleName("Cancel")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self.display_name_edit.text().strip():
            self.status_label.setText("Display name is required.")
            self.display_name_edit.setFocus()
            return
        if not self.upn_edit.text().strip():
            self.status_label.setText("User principal name is required.")
            self.upn_edit.setFocus()
            return
        if not self.mail_nickname_edit.text().strip():
            self.status_label.setText("Mail nickname is required.")
            self.mail_nickname_edit.setFocus()
            return
        if not self.password_edit.text():
            self.status_label.setText("Temporary password is required.")
            self.password_edit.setFocus()
            return
        self.accept()

    def values(self) -> dict:
        return {
            "display_name": self.display_name_edit.text().strip(),
            "user_principal_name": self.upn_edit.text().strip(),
            "mail_nickname": self.mail_nickname_edit.text().strip(),
            "password": self.password_edit.text(),
        }


class EditUserDialog(QDialog):
    """Prefilled from a UserDetail so every field round-trips through this
    dialog even if the admin only means to change one of them -- avoids
    accidentally clearing fields the form doesn't surface."""

    def __init__(self, detail: UserDetail, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit {detail.display_name}")
        self.setAccessibleName(f"Edit user {detail.display_name}")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.display_name_edit = QLineEdit(detail.display_name)
        self.display_name_edit.setAccessibleName("Display name")
        form.addRow("&Display name", self.display_name_edit)

        self.job_title_edit = QLineEdit(detail.job_title or "")
        self.job_title_edit.setAccessibleName("Job title")
        form.addRow("&Job title", self.job_title_edit)

        self.department_edit = QLineEdit(detail.department or "")
        self.department_edit.setAccessibleName("Department")
        form.addRow("&Department", self.department_edit)

        self.office_location_edit = QLineEdit(detail.office_location or "")
        self.office_location_edit.setAccessibleName("Office location")
        form.addRow("O&ffice location", self.office_location_edit)

        self.mobile_phone_edit = QLineEdit(detail.mobile_phone or "")
        self.mobile_phone_edit.setAccessibleName("Mobile phone")
        form.addRow("&Mobile phone", self.mobile_phone_edit)

        self.usage_location_edit = QLineEdit(detail.usage_location or "")
        self.usage_location_edit.setAccessibleName("Usage location")
        self.usage_location_edit.setAccessibleDescription(
            "Two-letter country code, e.g. US or GB. Required before a license can be assigned."
        )
        self.usage_location_edit.setPlaceholderText("e.g. US")
        form.addRow("&Usage location", self.usage_location_edit)

        self.status_label = QLabel("")
        self.status_label.setAccessibleName("Edit user status")
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setAccessibleName("Save changes")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setAccessibleName("Cancel")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self.display_name_edit.text().strip():
            self.status_label.setText("Display name is required.")
            self.display_name_edit.setFocus()
            return
        self.accept()

    def values(self) -> dict:
        return {
            "display_name": self.display_name_edit.text().strip(),
            "job_title": self.job_title_edit.text().strip() or None,
            "department": self.department_edit.text().strip() or None,
            "office_location": self.office_location_edit.text().strip() or None,
            "mobile_phone": self.mobile_phone_edit.text().strip() or None,
            "usage_location": self.usage_location_edit.text().strip() or None,
        }


class ResetPasswordDialog(QDialog):
    def __init__(self, display_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Reset password for {display_name}")
        self.setAccessibleName(f"Reset password for {display_name}")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.password_edit = QLineEdit()
        self.password_edit.setAccessibleName("New temporary password")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("&New temporary password", self.password_edit)

        self.status_label = QLabel(
            "The user will be required to change this password at next sign-in."
        )
        self.status_label.setAccessibleName("Reset password status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setAccessibleName("Reset password")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setAccessibleName("Cancel")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self.password_edit.text():
            self.status_label.setText("A new password is required.")
            self.password_edit.setFocus()
            return
        self.accept()

    def new_password(self) -> str:
        return self.password_edit.text()


class UsersPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Users")
        self._service: UserService | None = None
        self._graph_client = None
        self._has_audit_logs = False

        layout = QVBoxLayout(self)

        heading = QLabel("Users")
        heading.setAccessibleName("Users")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel("Sign in to a tenant (Tenant > Sign in...) to view users.")
        self.status_label.setAccessibleName("Users status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        search_row = QHBoxLayout()
        search_label = QLabel("&Search")
        self.search_edit = QLineEdit()
        self.search_edit.setAccessibleName("Search users")
        self.search_edit.setAccessibleDescription(
            "Matches display name or user principal name"
        )
        self.search_edit.setPlaceholderText("Display name or user principal name")
        self.search_edit.returnPressed.connect(self._on_refresh_clicked)
        search_label.setBuddy(self.search_edit)
        search_row.addWidget(search_label)
        search_row.addWidget(self.search_edit)

        self.search_button = AccessibleButton("Sea&rch")
        self.search_button.clicked.connect(self._on_refresh_clicked)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)

        toolbar_row = QHBoxLayout()
        self.refresh_button = AccessibleButton("&Refresh")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        toolbar_row.addWidget(self.refresh_button)

        self.new_button = AccessibleButton("&New user...")
        self.new_button.clicked.connect(self._on_new_clicked)
        toolbar_row.addWidget(self.new_button)

        self.edit_button = AccessibleButton("&Edit selected...")
        self.edit_button.clicked.connect(self._on_edit_clicked)
        toolbar_row.addWidget(self.edit_button)

        self.reset_password_button = AccessibleButton("Rese&t password...")
        self.reset_password_button.clicked.connect(self._on_reset_password_clicked)
        toolbar_row.addWidget(self.reset_password_button)

        self.enable_button = AccessibleButton("&Enable selected")
        self.enable_button.clicked.connect(self._on_enable_clicked)
        toolbar_row.addWidget(self.enable_button)

        self.disable_button = AccessibleButton("&Disable selected")
        self.disable_button.clicked.connect(self._on_disable_clicked)
        toolbar_row.addWidget(self.disable_button)

        self.delete_button = AccessibleButton("De&lete selected")
        self.delete_button.clicked.connect(self._on_delete_clicked)
        toolbar_row.addWidget(self.delete_button)

        self.export_button = CsvExportButton(
            self._csv_rows, self.status_label, default_filename="users.csv"
        )
        toolbar_row.addWidget(self.export_button)
        layout.addLayout(toolbar_row)

        self.model = UsersTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Users table")
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self._set_controls_enabled(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.search_edit,
            self.search_button,
            self.refresh_button,
            self.new_button,
            self.edit_button,
            self.reset_password_button,
            self.enable_button,
            self.disable_button,
            self.delete_button,
            self.export_button,
            self.table,
        ):
            widget.setEnabled(enabled)

    def set_graph_client(self, graph_client) -> None:
        self._graph_client = graph_client
        if graph_client is None:
            self._service = None
            self.model.set_users([])
            self.status_label.setText(
                "Sign in to a tenant (Tenant > Sign in...) to view users."
            )
            self._set_controls_enabled(False)
            return
        self._service = UserService(graph_client)
        self._set_controls_enabled(True)
        self._on_refresh_clicked()

    def set_has_audit_logs(self, has_audit_logs: bool) -> None:
        """Whether the impact preview can attempt a last-sign-in lookup --
        only possible with Azure AD Premium."""
        self._has_audit_logs = has_audit_logs

    def _selected_users(self) -> list[UserSummary]:
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        return [self.model.user_at(row) for row in sorted(rows)]

    def _csv_rows(self):
        headers = ["Display name", "User principal name", "Email", "Status"]
        rows = [
            [u.display_name, u.user_principal_name, u.mail or "", "Enabled" if u.account_enabled else "Disabled"]
            for u in self.model.all_users()
        ]
        return headers, rows

    @asyncSlot()
    async def _on_refresh_clicked(self) -> None:
        if self._service is None:
            return
        self.status_label.setText("Loading users...")
        try:
            users = await self._service.list_users(self.search_edit.text().strip() or None)
        except Exception as exc:
            self.status_label.setText(f"Couldn't load users: {friendly_error_message(exc)}")
            return
        self.model.set_users(users)
        self.status_label.setText(f"{len(users)} user(s).")

    @asyncSlot()
    async def _on_new_clicked(self) -> None:
        if self._service is None:
            return
        dialog = NewUserDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            await self._service.create_user(**dialog.values())
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't create user", friendly_error_message(exc))
            return
        await self._on_refresh_clicked()

    @asyncSlot()
    async def _on_edit_clicked(self) -> None:
        if self._service is None:
            return
        users = self._selected_users()
        if len(users) != 1:
            self.status_label.setText("Select exactly one user to edit.")
            return
        try:
            detail = await self._service.get_user_detail(users[0].id)
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't load user", friendly_error_message(exc))
            return
        dialog = EditUserDialog(detail, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            await self._service.update_user(detail.id, **dialog.values())
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't update user", friendly_error_message(exc))
            return
        await self._on_refresh_clicked()

    @asyncSlot()
    async def _on_reset_password_clicked(self) -> None:
        if self._service is None:
            return
        users = self._selected_users()
        if len(users) != 1:
            self.status_label.setText("Select exactly one user to reset the password for.")
            return
        dialog = ResetPasswordDialog(users[0].display_name, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            await self._service.reset_password(
                users[0].id, dialog.new_password(), display_name=users[0].display_name
            )
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't reset password", friendly_error_message(exc))
            return
        self.status_label.setText(f"Password reset for {users[0].display_name}.")

    @asyncSlot()
    async def _on_enable_clicked(self) -> None:
        await self._set_selected_enabled(True)

    async def _set_selected_enabled(self, enabled: bool) -> None:
        if self._service is None:
            return
        users = self._selected_users()
        if not users:
            self.status_label.setText("Select at least one user first.")
            return
        try:
            for user in users:
                await self._service.set_account_enabled(
                    user.id, enabled, display_name=user.display_name
                )
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't update user(s)", friendly_error_message(exc))
        await self._on_refresh_clicked()

    @asyncSlot()
    async def _on_disable_clicked(self) -> None:
        # Disable is high-impact (locks the person out) but reversible, so
        # this gets the impact preview but not the stronger type-to-confirm
        # gate -- that's reserved for Delete, below, which is irreversible.
        if self._service is None:
            return
        users = self._selected_users()
        if not users:
            self.status_label.setText("Select at least one user first.")
            return
        if not await self._confirm_with_impact_preview(
            users, action_title="Disable user", verb="Disable",
            action_sentence="They will not be able to sign in.",
            require_typed_confirmation=False,
        ):
            return
        try:
            for user in users:
                await self._service.set_account_enabled(
                    user.id, False, display_name=user.display_name
                )
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't disable user(s)", friendly_error_message(exc))
        await self._on_refresh_clicked()

    @asyncSlot()
    async def _on_delete_clicked(self) -> None:
        if self._service is None:
            return
        users = self._selected_users()
        if not users:
            self.status_label.setText("Select at least one user first.")
            return
        if not await self._confirm_with_impact_preview(
            users, action_title="Delete user", verb="Permanently delete",
            action_sentence="This cannot be undone.",
            require_typed_confirmation=True,
        ):
            return
        try:
            for user in users:
                await self._service.delete_user(user.id, display_name=user.display_name)
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't delete user(s)", friendly_error_message(exc))
        await self._on_refresh_clicked()

    async def _confirm_with_impact_preview(
        self,
        users: list[UserSummary],
        *,
        action_title: str,
        verb: str,
        action_sentence: str,
        require_typed_confirmation: bool,
    ) -> bool:
        """Shows the impact-preview dialog for a single selected user, or
        falls back to a plain named confirmation for a multi-select bulk
        action -- building one impact preview per row in a bulk action would
        mean unbounded Graph traffic scaling with selection size, which is
        exactly what this pattern is meant to avoid."""
        if len(users) == 1 and self._graph_client is not None:
            try:
                preview = await build_user_impact_preview(
                    self._graph_client, users[0].id, has_audit_logs=self._has_audit_logs
                )
            except Exception as exc:
                return confirm_destructive(
                    self, action_title,
                    f"{verb} {users[0].display_name}? {action_sentence} "
                    f"(Couldn't load impact preview: {friendly_error_message(exc)})",
                )
            dialog = ImpactPreviewDialog(
                action_title,
                f"{verb} {preview.display_name}? {action_sentence}",
                preview,
                require_typed_confirmation=require_typed_confirmation,
                parent=self,
            )
            return dialog.exec() == QDialog.DialogCode.Accepted

        names = ", ".join(user.display_name for user in users)
        return confirm_destructive(self, action_title, f"{verb} {names}? {action_sentence}")
