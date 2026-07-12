"""Bulk user import page: guided CSV import for creating multiple users at
once, with per-row validation shown before anything is created and per-row
results shown after.

Requires only the delegated Graph scopes already used elsewhere in this
app: User.ReadWrite.All (create users), Group.ReadWrite.All (add to
groups), Directory.ReadWrite.All (assign licenses) -- no new permissions.
"""

from __future__ import annotations

import asyncio

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from gcm.models.bulk_import import ImportRow, ImportRowResult
from gcm.services.bulk_import_service import (
    TEMPLATE_CSV,
    BulkImportFileError,
    BulkImportService,
)
from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.confirm import confirm_destructive
from gcm.ui.widgets.csv_export_button import CsvExportButton

_COLUMNS = ["Row", "Display name", "User principal name", "Status"]

_HELP_TEXT = (
    "Import users from a CSV file. Required columns: display_name, "
    "user_principal_name, mail_nickname, password. Optional columns: "
    "account_enabled (true/false, default true), usage_location (two-letter "
    "country code), license_skus and groups (each semicolon-separated). "
    "Required Graph permissions -- User.ReadWrite.All to create users, "
    "Group.ReadWrite.All for group membership, Directory.ReadWrite.All for "
    "license assignment -- are all already requested by this app."
)


class BulkImportTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[ImportRow] = []
        self._results: dict[int, ImportRowResult] = {}

    def set_rows(self, rows: list[ImportRow]) -> None:
        self.beginResetModel()
        self._rows = rows
        self._results = {}
        self.endResetModel()

    def set_results(self, results: list[ImportRowResult]) -> None:
        self._results = {r.row_number: r for r in results}
        if self._rows:
            top_left = self.index(0, 3)
            bottom_right = self.index(len(self._rows) - 1, 3)
            self.dataChanged.emit(top_left, bottom_right)

    def all_rows(self) -> list[ImportRow]:
        return list(self._rows)

    def valid_row_count(self) -> int:
        return sum(1 for r in self._rows if r.is_valid)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        row = self._rows[index.row()]
        column = index.column()
        if column == 0:
            return row.row_number
        if column == 1:
            return row.display_name
        if column == 2:
            return row.user_principal_name
        if column == 3:
            result = self._results.get(row.row_number)
            if result is not None:
                return "Success" if result.success else f"Failed: {result.message}"
            if row.errors:
                return "Blocked: " + "; ".join(row.errors)
            if row.warnings:
                return "Warning: " + "; ".join(row.warnings)
            return "Ready"
        return None


class BulkImportPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Bulk user import")
        self._service: BulkImportService | None = None

        layout = QVBoxLayout(self)

        heading = QLabel("Bulk user import")
        heading.setAccessibleName("Bulk user import")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel("Sign in to a tenant (Tenant > Sign in...) to import users.")
        self.status_label.setAccessibleName("Bulk import status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        help_label = QLabel(_HELP_TEXT)
        help_label.setWordWrap(True)
        help_label.setAccessibleName("Bulk import help")
        layout.addWidget(help_label)

        toolbar_row = QHBoxLayout()
        self.save_template_button = AccessibleButton("&Save CSV template...")
        self.save_template_button.clicked.connect(self._on_save_template_clicked)
        toolbar_row.addWidget(self.save_template_button)

        self.choose_file_button = AccessibleButton("&Choose CSV file...")
        self.choose_file_button.clicked.connect(self._on_choose_file_clicked)
        toolbar_row.addWidget(self.choose_file_button)

        self.run_button = AccessibleButton("&Run import...")
        self.run_button.clicked.connect(self._on_run_clicked)
        toolbar_row.addWidget(self.run_button)

        self.cancel_button = AccessibleButton("Ca&ncel")
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        toolbar_row.addWidget(self.cancel_button)

        self.export_button = CsvExportButton(
            self._csv_rows, self.status_label, default_filename="bulk_import_results.csv"
        )
        toolbar_row.addWidget(self.export_button)
        layout.addLayout(toolbar_row)

        self.model = BulkImportTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Bulk import preview and results table")
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self._set_controls_enabled(False)
        self._update_run_cancel_state()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.save_template_button,
            self.choose_file_button,
            self.export_button,
            self.table,
        ):
            widget.setEnabled(enabled)
        if not enabled:
            self.run_button.setEnabled(False)
            self.cancel_button.setEnabled(False)

    def _update_run_cancel_state(self) -> None:
        has_rows = self.model.rowCount() > 0
        service_ready = self._service is not None
        self.run_button.setEnabled(service_ready and has_rows and self.model.valid_row_count() > 0)
        self.cancel_button.setEnabled(service_ready and has_rows)

    def set_graph_client(self, graph_client) -> None:
        if graph_client is None:
            self._service = None
            self.model.set_rows([])
            self.status_label.setText(
                "Sign in to a tenant (Tenant > Sign in...) to import users."
            )
            self._set_controls_enabled(False)
            self._update_run_cancel_state()
            return
        self._service = BulkImportService(graph_client)
        self._set_controls_enabled(True)
        self.status_label.setText("Choose a CSV file to begin.")
        self._update_run_cancel_state()

    def _on_save_template_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV template", "bulk_import_template.csv", "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(TEMPLATE_CSV)
        except OSError as exc:
            self.status_label.setText(f"Couldn't save template: {exc}")
            return
        self.status_label.setText(f"Template saved to {path}.")

    @asyncSlot()
    async def _on_choose_file_clicked(self) -> None:
        if self._service is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Choose CSV file", "", "CSV files (*.csv)")
        if not path:
            return

        loop = asyncio.get_event_loop()
        try:
            rows = await loop.run_in_executor(
                None, self._service.parse_and_validate_locally, path
            )
        except BulkImportFileError as exc:
            QMessageBox.critical(self, "Couldn't read CSV", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't read CSV", str(exc))
            return

        self.model.set_rows(rows)
        self._update_run_cancel_state()
        self.status_label.setText(f"Validating {len(rows)} row(s) against the tenant...")

        validation_note = ""
        try:
            await self._service.validate_against_tenant(rows)
        except Exception as exc:
            # Don't just show this and move on -- the very next lines used to
            # unconditionally overwrite it with the generic "loaded" message
            # before anyone could read it, hiding that per-row tenant checks
            # (existing user/group/SKU lookups) were skipped entirely.
            validation_note = f" Couldn't fully validate against the tenant: {exc}"
        self.model.set_rows(rows)  # re-set to refresh error/warning text after tenant checks

        blocked = sum(1 for r in rows if not r.is_valid)
        self.status_label.setText(
            f"{len(rows)} row(s) loaded: {len(rows) - blocked} ready, "
            f"{blocked} blocked.{validation_note}"
        )
        self._update_run_cancel_state()

    def _on_cancel_clicked(self) -> None:
        self.model.set_rows([])
        self.status_label.setText("Import cancelled. Choose a CSV file to start again.")
        self._update_run_cancel_state()

    @asyncSlot()
    async def _on_run_clicked(self) -> None:
        if self._service is None:
            return
        rows = self.model.all_rows()
        valid_count = self.model.valid_row_count()
        blocked_count = len(rows) - valid_count
        if valid_count == 0:
            self.status_label.setText("No valid rows to import.")
            return

        message = f"Create {valid_count} user(s)?"
        if blocked_count:
            message += f" {blocked_count} row(s) will be skipped due to validation errors."
        if not confirm_destructive(self, "Run bulk import", message):
            return

        self.status_label.setText("Running import...")
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        try:
            results = await self._service.execute(rows)
        finally:
            self._update_run_cancel_state()
        self.model.set_results(results)
        succeeded = sum(1 for r in results if r.success)
        self.status_label.setText(f"Import finished: {succeeded} of {len(results)} row(s) succeeded.")

    def _csv_rows(self):
        headers = list(_COLUMNS)
        rows = []
        for i in range(self.model.rowCount()):
            rows.append(
                [
                    self.model.data(self.model.index(i, 0)),
                    self.model.data(self.model.index(i, 1)),
                    self.model.data(self.model.index(i, 2)),
                    self.model.data(self.model.index(i, 3)),
                ]
            )
        return headers, rows
