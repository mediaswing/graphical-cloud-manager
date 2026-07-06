"""Groups page: list/search/create/delete groups, plus a membership panel
(add/remove members) for whichever group is selected."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from gcm.models.group import GroupMember, GroupSummary
from gcm.services.graph_errors import friendly_error_message
from gcm.services.group_service import GroupService
from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.confirm import confirm_destructive

_COLUMNS = ["Display name", "Email", "Type"]


class GroupsTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._groups: list[GroupSummary] = []

    def set_groups(self, groups: list[GroupSummary]) -> None:
        self.beginResetModel()
        self._groups = groups
        self.endResetModel()

    def group_at(self, row: int) -> GroupSummary:
        return self._groups[row]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._groups)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        group = self._groups[index.row()]
        column = index.column()
        if column == 0:
            return group.display_name
        if column == 1:
            return group.mail or ""
        if column == 2:
            return group.group_type
        return None


class NewGroupDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New group")
        self.setAccessibleName("New group")

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.display_name_edit = QLineEdit()
        self.display_name_edit.setAccessibleName("Display name")
        form.addRow("&Display name", self.display_name_edit)

        self.mail_nickname_edit = QLineEdit()
        self.mail_nickname_edit.setAccessibleName("Mail nickname")
        form.addRow("&Mail nickname", self.mail_nickname_edit)

        self.description_edit = QLineEdit()
        self.description_edit.setAccessibleName("Description")
        form.addRow("&Description", self.description_edit)

        self.m365_checkbox = QCheckBox("&Microsoft 365 group (unchecked = Security group)")
        self.m365_checkbox.setAccessibleName("Microsoft 365 group")
        form.addRow(self.m365_checkbox)

        self.status_label = QLabel("")
        self.status_label.setAccessibleName("New group status")
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        # QDialogButtonBox creates its buttons with visible text only --
        # accessibleName isn't derived from that automatically, so it must
        # be set explicitly like every other control in this app.
        buttons.button(QDialogButtonBox.StandardButton.Ok).setAccessibleName("Create group")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setAccessibleName("Cancel")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        if not self.display_name_edit.text().strip():
            self.status_label.setText("Display name is required.")
            self.display_name_edit.setFocus()
            return
        if not self.mail_nickname_edit.text().strip():
            self.status_label.setText("Mail nickname is required.")
            self.mail_nickname_edit.setFocus()
            return
        self.accept()

    def values(self) -> dict:
        return {
            "display_name": self.display_name_edit.text().strip(),
            "mail_nickname": self.mail_nickname_edit.text().strip(),
            "description": self.description_edit.text().strip() or None,
            "is_microsoft_365": self.m365_checkbox.isChecked(),
        }


class GroupsPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Groups")
        self._service: GroupService | None = None
        self._selected_group: GroupSummary | None = None

        layout = QVBoxLayout(self)

        heading = QLabel("Groups")
        heading.setAccessibleName("Groups")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel("Sign in to a tenant (Tenant > Sign in...) to view groups.")
        self.status_label.setAccessibleName("Groups status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        search_row = QHBoxLayout()
        search_label = QLabel("&Search")
        self.search_edit = QLineEdit()
        self.search_edit.setAccessibleName("Search groups")
        self.search_edit.setAccessibleDescription("Matches display name")
        self.search_edit.setPlaceholderText("Display name")
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

        self.new_button = AccessibleButton("&New group...")
        self.new_button.clicked.connect(self._on_new_clicked)
        toolbar_row.addWidget(self.new_button)

        self.delete_button = AccessibleButton("De&lete selected group")
        self.delete_button.clicked.connect(self._on_delete_clicked)
        toolbar_row.addWidget(self.delete_button)
        layout.addLayout(toolbar_row)

        splitter = QSplitter()
        layout.addWidget(splitter, stretch=1)

        self.model = GroupsTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Groups table")
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.table)

        members_panel = QWidget()
        members_layout = QVBoxLayout(members_panel)
        self.members_label = QLabel("Select a group to view its members.")
        self.members_label.setAccessibleName("Members status")
        self.members_label.setWordWrap(True)
        members_layout.addWidget(self.members_label)

        self.members_list = QListWidget()
        self.members_list.setAccessibleName("Group members")
        members_layout.addWidget(self.members_list)

        add_member_row = QHBoxLayout()
        add_member_label = QLabel("&Add member (UPN or object ID)")
        self.add_member_edit = QLineEdit()
        self.add_member_edit.setAccessibleName("User to add")
        self.add_member_edit.setPlaceholderText("jane.doe@contoso.com")
        self.add_member_edit.returnPressed.connect(self._on_add_member_clicked)
        add_member_label.setBuddy(self.add_member_edit)
        add_member_row.addWidget(add_member_label)
        add_member_row.addWidget(self.add_member_edit)

        self.add_member_button = AccessibleButton("A&dd")
        self.add_member_button.clicked.connect(self._on_add_member_clicked)
        add_member_row.addWidget(self.add_member_button)
        members_layout.addLayout(add_member_row)

        self.remove_member_button = AccessibleButton("&Remove selected member")
        self.remove_member_button.clicked.connect(self._on_remove_member_clicked)
        members_layout.addWidget(self.remove_member_button)

        splitter.addWidget(members_panel)

        self._set_controls_enabled(False)
        self._set_member_controls_enabled(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.search_edit,
            self.search_button,
            self.refresh_button,
            self.new_button,
            self.delete_button,
            self.table,
        ):
            widget.setEnabled(enabled)

    def _set_member_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.members_list,
            self.add_member_edit,
            self.add_member_button,
            self.remove_member_button,
        ):
            widget.setEnabled(enabled)

    def set_graph_client(self, graph_client) -> None:
        if graph_client is None:
            self._service = None
            self._selected_group = None
            self.model.set_groups([])
            self.members_list.clear()
            self.members_label.setText("Select a group to view its members.")
            self.status_label.setText(
                "Sign in to a tenant (Tenant > Sign in...) to view groups."
            )
            self._set_controls_enabled(False)
            self._set_member_controls_enabled(False)
            return
        self._service = GroupService(graph_client)
        self._set_controls_enabled(True)
        self._on_refresh_clicked()

    @asyncSlot()
    async def _on_refresh_clicked(self) -> None:
        if self._service is None:
            return
        self.status_label.setText("Loading groups...")
        try:
            groups = await self._service.list_groups(self.search_edit.text().strip() or None)
        except Exception as exc:
            self.status_label.setText(f"Couldn't load groups: {friendly_error_message(exc)}")
            return
        self.model.set_groups(groups)
        self.status_label.setText(f"{len(groups)} group(s).")

    @asyncSlot()
    async def _on_new_clicked(self) -> None:
        if self._service is None:
            return
        dialog = NewGroupDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            await self._service.create_group(**dialog.values())
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't create group", friendly_error_message(exc))
            return
        await self._on_refresh_clicked()

    @asyncSlot()
    async def _on_delete_clicked(self) -> None:
        if self._service is None or self._selected_group is None:
            self.status_label.setText("Select a group first.")
            return
        group = self._selected_group
        if not confirm_destructive(
            self,
            "Delete group",
            f"Permanently delete the group {group.display_name!r}? This cannot be undone.",
        ):
            return
        try:
            await self._service.delete_group(group.id)
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't delete group", friendly_error_message(exc))
        await self._on_refresh_clicked()

    def _on_selection_changed(self) -> None:
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        if not rows:
            self._selected_group = None
            self.members_list.clear()
            self.members_label.setText("Select a group to view its members.")
            self._set_member_controls_enabled(False)
            return
        self._selected_group = self.model.group_at(next(iter(rows)))
        self._set_member_controls_enabled(True)
        self._refresh_members()

    @asyncSlot()
    async def _refresh_members(self) -> None:
        if self._service is None or self._selected_group is None:
            return
        group = self._selected_group
        self.members_label.setText(f"Loading members of {group.display_name}...")
        try:
            members = await self._service.list_members(group.id)
        except Exception as exc:
            self.members_label.setText(f"Couldn't load members: {friendly_error_message(exc)}")
            return
        self.members_list.clear()
        for member in members:
            self.members_list.addItem(member.display_name)
        self._members: list[GroupMember] = members
        self.members_label.setText(f"{len(members)} member(s) of {group.display_name}.")

    @asyncSlot()
    async def _on_add_member_clicked(self) -> None:
        if self._service is None or self._selected_group is None:
            self.members_label.setText("Select a group first.")
            return
        upn_or_id = self.add_member_edit.text().strip()
        if not upn_or_id:
            self.members_label.setText("Enter a user principal name or object ID first.")
            return
        try:
            await self._service.add_member(self._selected_group.id, upn_or_id)
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't add member", friendly_error_message(exc))
            return
        self.add_member_edit.clear()
        await self._refresh_members()

    @asyncSlot()
    async def _on_remove_member_clicked(self) -> None:
        if self._service is None or self._selected_group is None:
            return
        row = self.members_list.currentRow()
        if row < 0 or row >= len(getattr(self, "_members", [])):
            self.members_label.setText("Select a member to remove first.")
            return
        member = self._members[row]
        if not confirm_destructive(
            self,
            "Remove member",
            f"Remove {member.display_name!r} from {self._selected_group.display_name!r}?",
        ):
            return
        try:
            await self._service.remove_member(self._selected_group.id, member.id)
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't remove member", friendly_error_message(exc))
            return
        await self._refresh_members()
