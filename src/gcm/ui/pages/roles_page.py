"""Roles (RBAC) page: Entra directory role definitions, plus who's assigned
to whichever role is selected.

v1 scope is Entra directory roles only -- see gcm.services.role_service for
why Intune/Exchange RBAC are deferred.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from gcm.models.role import RoleAssignmentSummary, RoleDefinitionSummary
from gcm.services.graph_errors import friendly_error_message
from gcm.services.role_service import RoleService
from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.confirm import confirm_destructive

_COLUMNS = ["Role", "Description", "Built-in"]


class RoleDefinitionsTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._roles: list[RoleDefinitionSummary] = []

    def set_roles(self, roles: list[RoleDefinitionSummary]) -> None:
        self.beginResetModel()
        self._roles = roles
        self.endResetModel()

    def role_at(self, row: int) -> RoleDefinitionSummary:
        return self._roles[row]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._roles)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        definition = self._roles[index.row()]
        column = index.column()
        if column == 0:
            return definition.display_name
        if column == 1:
            return definition.description or ""
        if column == 2:
            return "Yes" if definition.is_built_in else "No"
        return None


class RolesPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Roles (RBAC)")
        self._service: RoleService | None = None
        self._selected_role: RoleDefinitionSummary | None = None
        self._assignments: list[RoleAssignmentSummary] = []

        layout = QVBoxLayout(self)

        heading = QLabel("Roles (RBAC)")
        heading.setAccessibleName("Roles (RBAC)")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel("Sign in to a tenant (Tenant > Sign in...) to view roles.")
        self.status_label.setAccessibleName("Roles status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.refresh_button = AccessibleButton("&Refresh roles")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        layout.addWidget(self.refresh_button)

        splitter = QSplitter()
        layout.addWidget(splitter, stretch=1)

        self.model = RoleDefinitionsTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Role definitions table")
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.table)

        assignments_panel = QWidget()
        assignments_layout = QVBoxLayout(assignments_panel)

        self.assignments_label = QLabel("Select a role to view who's assigned to it.")
        self.assignments_label.setAccessibleName("Role assignments status")
        self.assignments_label.setWordWrap(True)
        assignments_layout.addWidget(self.assignments_label)

        self.assignments_list = QListWidget()
        self.assignments_list.setAccessibleName("Role assignments")
        assignments_layout.addWidget(self.assignments_list)

        assign_row = QHBoxLayout()
        assign_label = QLabel("&Assign to user (UPN or object ID)")
        self.assign_edit = QLineEdit()
        self.assign_edit.setAccessibleName("User to assign this role to")
        self.assign_edit.setPlaceholderText("jane.doe@contoso.com")
        self.assign_edit.returnPressed.connect(self._on_assign_clicked)
        assign_label.setBuddy(self.assign_edit)
        assign_row.addWidget(assign_label)
        assign_row.addWidget(self.assign_edit)

        self.assign_button = AccessibleButton("A&ssign")
        self.assign_button.clicked.connect(self._on_assign_clicked)
        assign_row.addWidget(self.assign_button)
        assignments_layout.addLayout(assign_row)

        self.remove_assignment_button = AccessibleButton("&Remove selected assignment")
        self.remove_assignment_button.clicked.connect(self._on_remove_assignment_clicked)
        assignments_layout.addWidget(self.remove_assignment_button)

        splitter.addWidget(assignments_panel)

        self._set_controls_enabled(False)
        self._set_assignment_controls_enabled(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.refresh_button, self.table):
            widget.setEnabled(enabled)

    def _set_assignment_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.assignments_list,
            self.assign_edit,
            self.assign_button,
            self.remove_assignment_button,
        ):
            widget.setEnabled(enabled)

    def set_graph_client(self, graph_client) -> None:
        if graph_client is None:
            self._service = None
            self._selected_role = None
            self.model.set_roles([])
            self.assignments_list.clear()
            self.assignments_label.setText("Select a role to view who's assigned to it.")
            self.status_label.setText(
                "Sign in to a tenant (Tenant > Sign in...) to view roles."
            )
            self._set_controls_enabled(False)
            self._set_assignment_controls_enabled(False)
            return
        self._service = RoleService(graph_client)
        self._set_controls_enabled(True)
        self._on_refresh_clicked()

    @asyncSlot()
    async def _on_refresh_clicked(self) -> None:
        if self._service is None:
            return
        self.status_label.setText("Loading role definitions...")
        try:
            roles = await self._service.list_role_definitions()
        except Exception as exc:
            self.status_label.setText(f"Couldn't load roles: {friendly_error_message(exc)}")
            return
        self.model.set_roles(roles)
        self.status_label.setText(f"{len(roles)} role(s).")

    def _on_selection_changed(self) -> None:
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        if not rows:
            self._selected_role = None
            self.assignments_list.clear()
            self.assignments_label.setText("Select a role to view who's assigned to it.")
            self._set_assignment_controls_enabled(False)
            return
        self._selected_role = self.model.role_at(next(iter(rows)))
        self._set_assignment_controls_enabled(True)
        self._refresh_assignments()

    @asyncSlot()
    async def _refresh_assignments(self) -> None:
        if self._service is None or self._selected_role is None:
            return
        role = self._selected_role
        self.assignments_label.setText(f"Loading assignments for {role.display_name}...")
        try:
            self._assignments = await self._service.list_role_assignments(role.id)
        except Exception as exc:
            self.assignments_label.setText(
                f"Couldn't load assignments: {friendly_error_message(exc)}"
            )
            return
        self.assignments_list.clear()
        for assignment in self._assignments:
            self.assignments_list.addItem(assignment.principal_display_name)
        self.assignments_label.setText(
            f"{len(self._assignments)} assignment(s) of {role.display_name}."
        )

    @asyncSlot()
    async def _on_assign_clicked(self) -> None:
        if self._service is None or self._selected_role is None:
            self.assignments_label.setText("Select a role first.")
            return
        upn_or_id = self.assign_edit.text().strip()
        if not upn_or_id:
            self.assignments_label.setText("Enter a user principal name or object ID first.")
            return
        try:
            await self._service.assign_role(
                self._selected_role.id, upn_or_id,
                role_display_name=self._selected_role.display_name,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't assign role", friendly_error_message(exc))
            return
        self.assign_edit.clear()
        await self._refresh_assignments()

    @asyncSlot()
    async def _on_remove_assignment_clicked(self) -> None:
        if self._service is None or self._selected_role is None:
            return
        row = self.assignments_list.currentRow()
        if row < 0 or row >= len(self._assignments):
            self.assignments_label.setText("Select an assignment to remove first.")
            return
        assignment = self._assignments[row]
        if not confirm_destructive(
            self,
            "Remove role assignment",
            f"Remove {assignment.principal_display_name!r} from "
            f"{self._selected_role.display_name!r}?",
        ):
            return
        try:
            await self._service.remove_role_assignment(
                self._selected_role.id, assignment.principal_id,
                role_display_name=self._selected_role.display_name,
                principal_display_name=assignment.principal_display_name,
            )
        except Exception as exc:
            QMessageBox.critical(
                self, "Couldn't remove role assignment", friendly_error_message(exc)
            )
            return
        await self._refresh_assignments()
