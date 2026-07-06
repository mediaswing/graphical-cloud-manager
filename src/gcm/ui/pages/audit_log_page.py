"""Audit log page: local record of every write action this app has made,
independent of sign-in state (it's local data, not tenant data) -- see
gcm.services.audit_log for the underlying storage and docs/DESIGN.md
section 8 for why this exists (a client-side convenience log, not a
replacement for Entra/Intune/Exchange's own audit logs).
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from gcm.models.audit_entry import AuditEntry
from gcm.services import audit_log
from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.csv_export_button import CsvExportButton

_COLUMNS = ["Timestamp", "Action", "Target type", "Target", "Result", "Error"]


class AuditLogTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._entries: list[AuditEntry] = []

    def set_entries(self, entries: list[AuditEntry]) -> None:
        self.beginResetModel()
        self._entries = entries
        self.endResetModel()

    def all_entries(self) -> list[AuditEntry]:
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
            return entry.timestamp
        if column == 1:
            return entry.action
        if column == 2:
            return entry.target_type
        if column == 3:
            return entry.target_display_name
        if column == 4:
            return entry.result
        if column == 5:
            return entry.error or ""
        return None


class AuditLogPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Audit log")
        self._all_entries: list[AuditEntry] = []

        layout = QVBoxLayout(self)

        heading = QLabel("Audit log")
        heading.setAccessibleName("Audit log")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel(
            "Local record of write actions this app has made. Not a replacement for "
            "Entra/Intune/Exchange's own audit logs."
        )
        self.status_label.setAccessibleName("Audit log status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        filter_row = QHBoxLayout()
        search_label = QLabel("&Filter")
        self.search_edit = QLineEdit()
        self.search_edit.setAccessibleName("Filter audit log")
        self.search_edit.setAccessibleDescription("Matches actor, action, or target")
        self.search_edit.setPlaceholderText("e.g. jane@contoso.com or delete_user")
        self.search_edit.textChanged.connect(self._apply_filter)
        search_label.setBuddy(self.search_edit)
        filter_row.addWidget(search_label)
        filter_row.addWidget(self.search_edit)

        result_label = QLabel("&Result")
        self.result_combo = QComboBox()
        self.result_combo.setAccessibleName("Filter by result")
        self.result_combo.addItems(["All", "Success", "Failure"])
        self.result_combo.currentIndexChanged.connect(self._apply_filter)
        result_label.setBuddy(self.result_combo)
        filter_row.addWidget(result_label)
        filter_row.addWidget(self.result_combo)
        layout.addLayout(filter_row)

        toolbar_row = QHBoxLayout()
        self.refresh_button = AccessibleButton("&Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        toolbar_row.addWidget(self.refresh_button)

        self.export_button = CsvExportButton(
            self._csv_rows, self.status_label, default_filename="audit_log.csv"
        )
        toolbar_row.addWidget(self.export_button)
        layout.addLayout(toolbar_row)

        self.model = AuditLogTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Audit log table")
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self.refresh()

    def refresh(self) -> None:
        self._all_entries = audit_log.read_all()
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self.search_edit.text().strip().lower()
        result_filter = self.result_combo.currentText()
        filtered = self._all_entries
        if result_filter != "All":
            filtered = [e for e in filtered if e.result.lower() == result_filter.lower()]
        if query:
            filtered = [
                e
                for e in filtered
                if query in e.actor.lower()
                or query in e.action.lower()
                or query in e.target_display_name.lower()
                or query in e.target_type.lower()
            ]
        filtered = list(reversed(filtered))  # most recent first
        self.model.set_entries(filtered)
        self.status_label.setText(f"Showing {len(filtered)} of {len(self._all_entries)} entries.")

    def _csv_rows(self):
        headers = ["Timestamp", "Actor", "Action", "Target type", "Target", "Result", "Error"]
        rows = [
            [
                e.timestamp,
                e.actor,
                e.action,
                e.target_type,
                e.target_display_name,
                e.result,
                e.error or "",
            ]
            for e in self.model.all_entries()
        ]
        return headers, rows
