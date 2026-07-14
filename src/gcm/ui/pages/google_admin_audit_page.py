"""Google Admin audit log page: read-only tenant-side record of admin
console changes, from the Admin SDK Reports API's admin activity feed. This
is Google's own audit trail, distinct from the app's local Audit log page
(ui/pages/audit_log_page.py), which only records actions this app itself
made -- see services/google_admin_audit_service.py's module docstring.
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

from gcm.models.google_admin_audit import GoogleAdminAuditSummary
from gcm.services.google_admin_audit_service import GoogleAdminAuditService
from gcm.services.google_errors import friendly_google_error
from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.csv_export_button import CsvExportButton

_COLUMNS = ["Time", "Actor", "Event", "Details"]


class GoogleAdminAuditTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._entries: list[GoogleAdminAuditSummary] = []

    def set_entries(self, entries: list[GoogleAdminAuditSummary]) -> None:
        self.beginResetModel()
        self._entries = entries
        self.endResetModel()

    def all_entries(self) -> list[GoogleAdminAuditSummary]:
        return list(self._entries)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._entries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        entry = self._entries[index.row()]
        column = index.column()
        if column == 0:
            return entry.time.strftime("%Y-%m-%d %H:%M") if entry.time else "Unknown"
        if column == 1:
            return entry.actor_email
        if column == 2:
            return entry.event_name
        if column == 3:
            return entry.details
        return None


class GoogleAdminAuditPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Google Admin audit log")
        self._service: GoogleAdminAuditService | None = None

        layout = QVBoxLayout(self)

        heading = QLabel("Google Admin audit log")
        heading.setAccessibleName("Google Admin audit log")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel(
            "Sign in to Google Workspace (Google Workspace > Sign in...) to view the admin audit log."
        )
        self.status_label.setAccessibleName("Google Admin audit log status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        search_row = QHBoxLayout()
        search_label = QLabel("&Filter by actor")
        self.search_edit = QLineEdit()
        self.search_edit.setAccessibleName("Filter admin audit log by actor")
        self.search_edit.setAccessibleDescription("Matches a specific admin's email exactly")
        self.search_edit.setPlaceholderText("admin@contoso.com")
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

        self.export_button = CsvExportButton(
            self._csv_rows, self.status_label, default_filename="google_admin_audit_log.csv"
        )
        toolbar_row.addWidget(self.export_button)
        layout.addLayout(toolbar_row)

        self.model = GoogleAdminAuditTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Google Admin audit log table")
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self._set_controls_enabled(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.search_edit, self.search_button, self.refresh_button, self.export_button, self.table):
            widget.setEnabled(enabled)

    def _csv_rows(self):
        headers = _COLUMNS
        rows = [
            [
                e.time.strftime("%Y-%m-%d %H:%M") if e.time else "Unknown",
                e.actor_email,
                e.event_name,
                e.details,
            ]
            for e in self.model.all_entries()
        ]
        return headers, rows

    def set_reports_client(self, reports_client) -> None:
        if reports_client is None:
            self._service = None
            self.model.set_entries([])
            self.status_label.setText(
                "Sign in to Google Workspace (Google Workspace > Sign in...) to view the admin audit log."
            )
            self._set_controls_enabled(False)
            return
        self._service = GoogleAdminAuditService(reports_client)
        self._set_controls_enabled(True)
        self._on_refresh_clicked()

    @asyncSlot()
    async def _on_refresh_clicked(self) -> None:
        if self._service is None:
            return
        self.status_label.setText("Loading admin audit log...")
        try:
            entries = await self._service.list_recent_events(
                self.search_edit.text().strip() or None
            )
        except Exception as exc:
            self.status_label.setText(f"Couldn't load admin audit log: {friendly_google_error(exc)}")
            return
        self.model.set_entries(entries)
        self.status_label.setText(f"{len(entries)} recent event(s).")
