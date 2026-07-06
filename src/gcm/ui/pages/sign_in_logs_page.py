"""Sign-in logs page: read-only recent sign-in activity, including which
device (if any) was used.

Only shown when TenantCapabilities.has_audit_logs is true (Azure AD Premium
P1+) -- see gcm.services.sign_in_log_service.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from gcm.models.sign_in import SignInSummary
from gcm.services.graph_errors import friendly_error_message
from gcm.services.sign_in_log_service import SignInLogService
from gcm.ui.widgets.accessible_button import AccessibleButton

_COLUMNS = ["Time", "User", "Application", "Device", "Result"]


class SignInLogsTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._sign_ins: list[SignInSummary] = []

    def set_sign_ins(self, sign_ins: list[SignInSummary]) -> None:
        self.beginResetModel()
        self._sign_ins = sign_ins
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._sign_ins)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        entry = self._sign_ins[index.row()]
        column = index.column()
        if column == 0:
            return entry.created_at.strftime("%Y-%m-%d %H:%M") if entry.created_at else "Unknown"
        if column == 1:
            return f"{entry.user_display_name} ({entry.user_principal_name})"
        if column == 2:
            return entry.app_display_name
        if column == 3:
            if entry.device_display_name:
                os_part = f", {entry.device_operating_system}" if entry.device_operating_system else ""
                return f"{entry.device_display_name}{os_part}"
            return "(no device info)"
        if column == 4:
            return "Success" if entry.succeeded else f"Failed: {entry.failure_reason or 'unknown reason'}"
        return None


class SignInLogsPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Sign-in logs")
        self._service: SignInLogService | None = None

        layout = QVBoxLayout(self)

        heading = QLabel("Sign-in logs")
        heading.setAccessibleName("Sign-in logs")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel(
            "Sign in to a tenant (Tenant > Sign in...) to view sign-in logs."
        )
        self.status_label.setAccessibleName("Sign-in logs status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        search_row = QHBoxLayout()
        search_label = QLabel("&Filter by user")
        self.search_edit = QLineEdit()
        self.search_edit.setAccessibleName("Filter sign-ins by user")
        self.search_edit.setAccessibleDescription(
            "Matches the start of a display name or user principal name"
        )
        self.search_edit.setPlaceholderText("jane.doe@contoso.com")
        self.search_edit.returnPressed.connect(self._on_refresh_clicked)
        search_label.setBuddy(self.search_edit)
        search_row.addWidget(search_label)
        search_row.addWidget(self.search_edit)

        self.search_button = AccessibleButton("Sea&rch")
        self.search_button.clicked.connect(self._on_refresh_clicked)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)

        self.refresh_button = AccessibleButton("&Refresh")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        layout.addWidget(self.refresh_button)

        self.model = SignInLogsTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Sign-in logs table")
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self._set_controls_enabled(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.search_edit, self.search_button, self.refresh_button, self.table):
            widget.setEnabled(enabled)

    def set_graph_client(self, graph_client) -> None:
        if graph_client is None:
            self._service = None
            self.model.set_sign_ins([])
            self.status_label.setText(
                "Sign in to a tenant (Tenant > Sign in...) to view sign-in logs."
            )
            self._set_controls_enabled(False)
            return
        self._service = SignInLogService(graph_client)
        self._set_controls_enabled(True)
        self._on_refresh_clicked()

    @asyncSlot()
    async def _on_refresh_clicked(self) -> None:
        if self._service is None:
            return
        self.status_label.setText("Loading sign-in logs...")
        try:
            sign_ins = await self._service.list_recent_sign_ins(
                self.search_edit.text().strip() or None
            )
        except Exception as exc:
            self.status_label.setText(
                f"Couldn't load sign-in logs: {friendly_error_message(exc)}"
            )
            return
        self.model.set_sign_ins(sign_ins)
        self.status_label.setText(f"{len(sign_ins)} recent sign-in(s).")
