"""Google Sign-in logs page: read-only recent sign-in activity from the
Admin SDK Reports API. Same structure as ui/pages/sign_in_logs_page.py --
always shown once signed in, since (unlike Entra sign-in logs) there's no
separate licensing tier gating this Reports API feed.
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

from gcm.models.google_sign_in import GoogleSignInSummary
from gcm.services.google_errors import friendly_google_error
from gcm.services.google_sign_in_log_service import GoogleSignInLogService
from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.csv_export_button import CsvExportButton

_COLUMNS = ["Time", "User", "IP address", "Event", "Result"]


class GoogleSignInLogsTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._sign_ins: list[GoogleSignInSummary] = []

    def set_sign_ins(self, sign_ins: list[GoogleSignInSummary]) -> None:
        self.beginResetModel()
        self._sign_ins = sign_ins
        self.endResetModel()

    def all_sign_ins(self) -> list[GoogleSignInSummary]:
        return list(self._sign_ins)

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
            return entry.time.strftime("%Y-%m-%d %H:%M") if entry.time else "Unknown"
        if column == 1:
            return entry.user_email
        if column == 2:
            return entry.ip_address or ""
        if column == 3:
            return entry.event_name
        if column == 4:
            return "Success" if entry.succeeded else f"Failed: {entry.failure_type or 'unknown reason'}"
        return None


class GoogleSignInLogsPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Google Sign-in logs")
        self._service: GoogleSignInLogService | None = None

        layout = QVBoxLayout(self)

        heading = QLabel("Google Sign-in logs")
        heading.setAccessibleName("Google Sign-in logs")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel(
            "Sign in to Google Workspace (Google Workspace > Sign in...) to view sign-in logs."
        )
        self.status_label.setAccessibleName("Google Sign-in logs status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        search_row = QHBoxLayout()
        search_label = QLabel("&Filter by user")
        self.search_edit = QLineEdit()
        self.search_edit.setAccessibleName("Filter sign-ins by user")
        self.search_edit.setAccessibleDescription("Matches a specific user's email exactly")
        self.search_edit.setPlaceholderText("jane.doe@contoso.com")
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
            self._csv_rows, self.status_label, default_filename="google_sign_in_logs.csv"
        )
        toolbar_row.addWidget(self.export_button)
        layout.addLayout(toolbar_row)

        self.model = GoogleSignInLogsTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Google Sign-in logs table")
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
        rows = []
        for entry in self.model.all_sign_ins():
            time_str = entry.time.strftime("%Y-%m-%d %H:%M") if entry.time else "Unknown"
            result = "Success" if entry.succeeded else f"Failed: {entry.failure_type or 'unknown reason'}"
            rows.append([time_str, entry.user_email, entry.ip_address or "", entry.event_name, result])
        return headers, rows

    def set_reports_client(self, reports_client) -> None:
        if reports_client is None:
            self._service = None
            self.model.set_sign_ins([])
            self.status_label.setText(
                "Sign in to Google Workspace (Google Workspace > Sign in...) to view sign-in logs."
            )
            self._set_controls_enabled(False)
            return
        self._service = GoogleSignInLogService(reports_client)
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
            self.status_label.setText(f"Couldn't load sign-in logs: {friendly_google_error(exc)}")
            return
        self.model.set_sign_ins(sign_ins)
        self.status_label.setText(f"{len(sign_ins)} recent sign-in(s).")
