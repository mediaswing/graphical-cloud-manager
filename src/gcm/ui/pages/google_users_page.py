"""Google Users page: list, search, create, suspend/unsuspend, and delete
Google Workspace users. Same structure as ui/pages/users_page.py, minus the
Graph-specific impact-preview dialog (there's no Google equivalent of the
sign-in-logs/group-membership lookup that dialog is built on) -- destructive
actions here use the plain confirm_destructive/confirm_irreversible prompts
instead.
"""

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

from gcm.models.google_user import GoogleUserDetail, GoogleUserSummary
from gcm.services.google_errors import friendly_google_error
from gcm.services.google_user_service import GoogleUserService
from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.bulk_action import run_bulk_action, summarize_bulk_failures
from gcm.ui.widgets.confirm import confirm_destructive, confirm_irreversible
from gcm.ui.widgets.csv_export_button import CsvExportButton

_COLUMNS = ["Full name", "Primary email", "Status"]


class GoogleUsersTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._users: list[GoogleUserSummary] = []

    def set_users(self, users: list[GoogleUserSummary]) -> None:
        self.beginResetModel()
        self._users = users
        self.endResetModel()

    def user_at(self, row: int) -> GoogleUserSummary:
        return self._users[row]

    def all_users(self) -> list[GoogleUserSummary]:
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
            return user.full_name
        if column == 1:
            return user.primary_email
        if column == 2:
            return "Suspended" if user.suspended else "Active"
        return None


class NewGoogleUserDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Google user")
        self.setAccessibleName("New Google user")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.given_name_edit = QLineEdit()
        self.given_name_edit.setAccessibleName("Given name")
        form.addRow("&Given name", self.given_name_edit)

        self.family_name_edit = QLineEdit()
        self.family_name_edit.setAccessibleName("Family name")
        form.addRow("&Family name", self.family_name_edit)

        self.primary_email_edit = QLineEdit()
        self.primary_email_edit.setAccessibleName("Primary email")
        self.primary_email_edit.setPlaceholderText("e.g. jane.doe@contoso.com")
        form.addRow("Primary &email", self.primary_email_edit)

        self.org_unit_path_edit = QLineEdit("/")
        self.org_unit_path_edit.setAccessibleName("Organizational unit path")
        form.addRow("&Org unit path", self.org_unit_path_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setAccessibleName("Temporary password")
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("&Temporary password", self.password_edit)

        self.status_label = QLabel("")
        self.status_label.setAccessibleName("New Google user status")
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setAccessibleName("Create user")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setAccessibleName("Cancel")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self.given_name_edit.text().strip():
            self.status_label.setText("Given name is required.")
            self.given_name_edit.setFocus()
            return
        if not self.family_name_edit.text().strip():
            self.status_label.setText("Family name is required.")
            self.family_name_edit.setFocus()
            return
        if not self.primary_email_edit.text().strip():
            self.status_label.setText("Primary email is required.")
            self.primary_email_edit.setFocus()
            return
        if not self.password_edit.text():
            self.status_label.setText("Temporary password is required.")
            self.password_edit.setFocus()
            return
        self.accept()

    def values(self) -> dict:
        return {
            "given_name": self.given_name_edit.text().strip(),
            "family_name": self.family_name_edit.text().strip(),
            "primary_email": self.primary_email_edit.text().strip(),
            "org_unit_path": self.org_unit_path_edit.text().strip() or "/",
            "password": self.password_edit.text(),
        }


class EditGoogleUserDialog(QDialog):
    def __init__(self, detail: GoogleUserDetail, parent=None) -> None:
        super().__init__(parent)
        display_name = f"{detail.given_name} {detail.family_name}".strip() or detail.primary_email
        self.setWindowTitle(f"Edit {display_name}")
        self.setAccessibleName(f"Edit Google user {display_name}")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.given_name_edit = QLineEdit(detail.given_name)
        self.given_name_edit.setAccessibleName("Given name")
        form.addRow("&Given name", self.given_name_edit)

        self.family_name_edit = QLineEdit(detail.family_name)
        self.family_name_edit.setAccessibleName("Family name")
        form.addRow("&Family name", self.family_name_edit)

        self.org_unit_path_edit = QLineEdit(detail.org_unit_path)
        self.org_unit_path_edit.setAccessibleName("Organizational unit path")
        form.addRow("&Org unit path", self.org_unit_path_edit)

        self.recovery_email_edit = QLineEdit(detail.recovery_email or "")
        self.recovery_email_edit.setAccessibleName("Recovery email")
        form.addRow("&Recovery email", self.recovery_email_edit)

        self.recovery_phone_edit = QLineEdit(detail.recovery_phone or "")
        self.recovery_phone_edit.setAccessibleName("Recovery phone")
        form.addRow("Recovery &phone", self.recovery_phone_edit)

        self.status_label = QLabel("")
        self.status_label.setAccessibleName("Edit Google user status")
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
        if not self.given_name_edit.text().strip():
            self.status_label.setText("Given name is required.")
            self.given_name_edit.setFocus()
            return
        self.accept()

    def values(self) -> dict:
        return {
            "given_name": self.given_name_edit.text().strip(),
            "family_name": self.family_name_edit.text().strip(),
            "org_unit_path": self.org_unit_path_edit.text().strip() or "/",
            "recovery_email": self.recovery_email_edit.text().strip() or None,
            "recovery_phone": self.recovery_phone_edit.text().strip() or None,
        }


class ResetGoogleUserPasswordDialog(QDialog):
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


class GoogleUsersPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Google Users")
        self._service: GoogleUserService | None = None
        # Bumped on every refresh; a completed request only applies its
        # result if it's still the most recent one issued -- same staleness
        # guard as UsersPage._refresh_generation.
        self._refresh_generation = 0

        layout = QVBoxLayout(self)

        heading = QLabel("Google Users")
        heading.setAccessibleName("Google Users")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel(
            "Sign in to Google Workspace (Google Workspace > Sign in...) to view users."
        )
        self.status_label.setAccessibleName("Google Users status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        search_row = QHBoxLayout()
        search_label = QLabel("&Search")
        self.search_edit = QLineEdit()
        self.search_edit.setAccessibleName("Search Google users")
        self.search_edit.setAccessibleDescription("Matches given name, family name, or email")
        self.search_edit.setPlaceholderText("Name or email")
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

        self.unsuspend_button = AccessibleButton("&Unsuspend selected")
        self.unsuspend_button.clicked.connect(self._on_unsuspend_clicked)
        toolbar_row.addWidget(self.unsuspend_button)

        self.suspend_button = AccessibleButton("&Suspend selected")
        self.suspend_button.clicked.connect(self._on_suspend_clicked)
        toolbar_row.addWidget(self.suspend_button)

        self.delete_button = AccessibleButton("De&lete selected")
        self.delete_button.clicked.connect(self._on_delete_clicked)
        toolbar_row.addWidget(self.delete_button)

        self.export_button = CsvExportButton(
            self._csv_rows, self.status_label, default_filename="google_users.csv"
        )
        toolbar_row.addWidget(self.export_button)
        layout.addLayout(toolbar_row)

        self.model = GoogleUsersTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Google Users table")
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
            self.unsuspend_button,
            self.suspend_button,
            self.delete_button,
            self.export_button,
            self.table,
        ):
            widget.setEnabled(enabled)

    def set_directory_client(self, directory_client) -> None:
        if directory_client is None:
            self._service = None
            self.model.set_users([])
            self.status_label.setText(
                "Sign in to Google Workspace (Google Workspace > Sign in...) to view users."
            )
            self._set_controls_enabled(False)
            return
        self._service = GoogleUserService(directory_client)
        self._set_controls_enabled(True)
        self._on_refresh_clicked()

    def _selected_users(self) -> list[GoogleUserSummary]:
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        return [self.model.user_at(row) for row in sorted(rows)]

    def _csv_rows(self):
        headers = ["Full name", "Primary email", "Status"]
        rows = [
            [u.full_name, u.primary_email, "Suspended" if u.suspended else "Active"]
            for u in self.model.all_users()
        ]
        return headers, rows

    @asyncSlot()
    async def _on_refresh_clicked(self) -> None:
        if self._service is None:
            return
        self._refresh_generation += 1
        generation = self._refresh_generation
        self.status_label.setText("Loading users...")
        try:
            users = await self._service.list_users(self.search_edit.text().strip() or None)
        except Exception as exc:
            if generation != self._refresh_generation:
                return  # superseded by a newer refresh; don't show a stale error
            self.status_label.setText(f"Couldn't load users: {friendly_google_error(exc)}")
            return
        if generation != self._refresh_generation:
            return  # a newer refresh already started; don't clobber it with this stale result
        self.model.set_users(users)
        self.status_label.setText(f"{len(users)} user(s).")

    @asyncSlot()
    async def _on_new_clicked(self) -> None:
        if self._service is None:
            return
        dialog = NewGoogleUserDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            await self._service.create_user(**dialog.values())
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't create user", friendly_google_error(exc))
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
            QMessageBox.critical(self, "Couldn't load user", friendly_google_error(exc))
            return
        dialog = EditGoogleUserDialog(detail, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            await self._service.update_user(detail.id, **dialog.values())
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't update user", friendly_google_error(exc))
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
        dialog = ResetGoogleUserPasswordDialog(users[0].full_name, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            await self._service.reset_password(
                users[0].id, dialog.new_password(), display_name=users[0].full_name
            )
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't reset password", friendly_google_error(exc))
            return
        self.status_label.setText(f"Password reset for {users[0].full_name}.")

    @asyncSlot()
    async def _on_unsuspend_clicked(self) -> None:
        await self._set_selected_suspended(False)

    @asyncSlot()
    async def _on_suspend_clicked(self) -> None:
        users = self._selected_users()
        if not users:
            self.status_label.setText("Select at least one user first.")
            return
        names = ", ".join(u.full_name for u in users)
        if not confirm_destructive(
            self, "Suspend user",
            f"Suspend {names}? They will not be able to sign in.",
        ):
            return
        await self._set_selected_suspended(True, users=users)

    async def _set_selected_suspended(
        self, suspended: bool, *, users: list[GoogleUserSummary] | None = None
    ) -> None:
        if self._service is None:
            return
        if users is None:
            users = self._selected_users()
            if not users:
                self.status_label.setText("Select at least one user first.")
                return
        succeeded, failures = await run_bulk_action(
            users,
            lambda user: self._service.set_suspended(
                user.id, suspended, display_name=user.full_name),
            display_name=lambda user: user.full_name,
            format_error=friendly_google_error,
        )
        if failures:
            QMessageBox.critical(
                self, "Couldn't update user(s)",
                summarize_bulk_failures(len(users), succeeded, failures))
        await self._on_refresh_clicked()

    @asyncSlot()
    async def _on_delete_clicked(self) -> None:
        if self._service is None:
            return
        users = self._selected_users()
        if not users:
            self.status_label.setText("Select at least one user first.")
            return
        if len(users) == 1:
            if not confirm_irreversible(
                self, "Delete user",
                f"Permanently delete {users[0].full_name}? This cannot be undone.",
                type_to_confirm=users[0].full_name,
            ):
                return
        else:
            names = ", ".join(u.full_name for u in users)
            if not confirm_destructive(
                self, "Delete user",
                f"Permanently delete {names}? This cannot be undone.",
            ):
                return
        succeeded, failures = await run_bulk_action(
            users,
            lambda user: self._service.delete_user(user.id, display_name=user.full_name),
            display_name=lambda user: user.full_name,
            format_error=friendly_google_error,
        )
        if failures:
            QMessageBox.critical(
                self, "Couldn't delete user(s)",
                summarize_bulk_failures(len(users), succeeded, failures))
        await self._on_refresh_clicked()
