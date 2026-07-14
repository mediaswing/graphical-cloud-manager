"""Google Devices page: mobile devices enrolled in Google Workspace device
management. Same structure as ui/pages/devices_page.py, but Google's device
lifecycle is approve/block/remote-wipe/unenroll rather than Entra's simple
enabled/disabled toggle, so the action set differs -- there's also no
Google equivalent of the Intune-sync context menu action, since Google has
no separate MDM layer the way Intune sits alongside Entra device objects.

Chrome OS devices are a separate Directory API resource with different
fields/actions (org-unit moves, deprovisioning) and are out of scope here --
see services/google_device_service.py's module docstring.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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

from gcm.models.google_device import GoogleMobileDeviceSummary
from gcm.services.google_device_service import GoogleDeviceService
from gcm.services.google_errors import friendly_google_error
from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.bulk_action import run_bulk_action, summarize_bulk_failures
from gcm.ui.widgets.confirm import confirm_destructive, confirm_irreversible
from gcm.ui.widgets.csv_export_button import CsvExportButton

_COLUMNS = ["Owner", "Model", "OS/Type", "Status", "Last sync"]


def _device_label(device: GoogleMobileDeviceSummary) -> str:
    return device.owner_name or device.owner_email or device.model


class GoogleDevicesTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._devices: list[GoogleMobileDeviceSummary] = []

    def set_devices(self, devices: list[GoogleMobileDeviceSummary]) -> None:
        self.beginResetModel()
        self._devices = devices
        self.endResetModel()

    def device_at(self, row: int) -> GoogleMobileDeviceSummary:
        return self._devices[row]

    def all_devices(self) -> list[GoogleMobileDeviceSummary]:
        return list(self._devices)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._devices)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        device = self._devices[index.row()]
        column = index.column()
        if column == 0:
            return device.owner_name or device.owner_email or "Unknown"
        if column == 1:
            return device.model
        if column == 2:
            return device.os_type
        if column == 3:
            return device.status
        if column == 4:
            return device.last_sync.strftime("%Y-%m-%d %H:%M") if device.last_sync else "Never"
        return None


class GoogleDevicesPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Google Devices")
        self._service: GoogleDeviceService | None = None
        # Bumped on every refresh; a completed request only applies its
        # result if it's still the most recent one issued -- same staleness
        # guard as DevicesPage._refresh_generation.
        self._refresh_generation = 0

        layout = QVBoxLayout(self)

        heading = QLabel("Google Devices")
        heading.setAccessibleName("Google Devices")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel(
            "Sign in to Google Workspace (Google Workspace > Sign in...) to view devices."
        )
        self.status_label.setAccessibleName("Google Devices status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        search_row = QHBoxLayout()
        search_label = QLabel("&Search")
        self.search_edit = QLineEdit()
        self.search_edit.setAccessibleName("Search Google devices")
        self.search_edit.setAccessibleDescription("Matches device model or owner name")
        self.search_edit.setPlaceholderText("Model or owner name")
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

        self.approve_button = AccessibleButton("&Approve selected")
        self.approve_button.clicked.connect(self._on_approve_clicked)
        toolbar_row.addWidget(self.approve_button)

        self.block_button = AccessibleButton("&Block selected")
        self.block_button.clicked.connect(self._on_block_clicked)
        toolbar_row.addWidget(self.block_button)

        self.remote_wipe_button = AccessibleButton("&Remote wipe selected...")
        self.remote_wipe_button.clicked.connect(self._on_remote_wipe_clicked)
        toolbar_row.addWidget(self.remote_wipe_button)

        self.delete_button = AccessibleButton("&Unenroll selected")
        self.delete_button.clicked.connect(self._on_delete_clicked)
        toolbar_row.addWidget(self.delete_button)

        self.export_button = CsvExportButton(
            self._csv_rows, self.status_label, default_filename="google_devices.csv"
        )
        toolbar_row.addWidget(self.export_button)
        layout.addLayout(toolbar_row)

        self.model = GoogleDevicesTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Google Devices table")
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
            self.approve_button,
            self.block_button,
            self.remote_wipe_button,
            self.delete_button,
            self.export_button,
            self.table,
        ):
            widget.setEnabled(enabled)

    def set_directory_client(self, directory_client) -> None:
        if directory_client is None:
            self._service = None
            self.model.set_devices([])
            self.status_label.setText(
                "Sign in to Google Workspace (Google Workspace > Sign in...) to view devices."
            )
            self._set_controls_enabled(False)
            return
        self._service = GoogleDeviceService(directory_client)
        self._set_controls_enabled(True)
        self._on_refresh_clicked()

    def _selected_devices(self) -> list[GoogleMobileDeviceSummary]:
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        return [self.model.device_at(row) for row in sorted(rows)]

    def _csv_rows(self):
        headers = _COLUMNS
        rows = [
            [
                d.owner_name or d.owner_email or "Unknown",
                d.model,
                d.os_type,
                d.status,
                d.last_sync.strftime("%Y-%m-%d %H:%M") if d.last_sync else "Never",
            ]
            for d in self.model.all_devices()
        ]
        return headers, rows

    @asyncSlot()
    async def _on_refresh_clicked(self) -> None:
        if self._service is None:
            return
        self._refresh_generation += 1
        generation = self._refresh_generation
        self.status_label.setText("Loading devices...")
        try:
            devices = await self._service.list_devices(self.search_edit.text().strip() or None)
        except Exception as exc:
            if generation != self._refresh_generation:
                return  # superseded by a newer refresh; don't show a stale error
            self.status_label.setText(f"Couldn't load devices: {friendly_google_error(exc)}")
            return
        if generation != self._refresh_generation:
            return  # a newer refresh already started; don't clobber it with this stale result
        self.model.set_devices(devices)
        self.status_label.setText(f"{len(devices)} device(s).")

    @asyncSlot()
    async def _on_approve_clicked(self) -> None:
        if self._service is None:
            return
        devices = self._selected_devices()
        if not devices:
            self.status_label.setText("Select at least one device first.")
            return
        succeeded, failures = await run_bulk_action(
            devices,
            lambda device: self._service.approve_device(
                device.resource_id, display_name=_device_label(device)),
            display_name=_device_label,
            format_error=friendly_google_error,
        )
        if failures:
            QMessageBox.critical(
                self, "Couldn't approve device(s)",
                summarize_bulk_failures(len(devices), succeeded, failures))
        await self._on_refresh_clicked()

    @asyncSlot()
    async def _on_block_clicked(self) -> None:
        if self._service is None:
            return
        devices = self._selected_devices()
        if not devices:
            self.status_label.setText("Select at least one device first.")
            return
        names = ", ".join(_device_label(d) for d in devices)
        if not confirm_destructive(
            self, "Block device(s)", f"Block {names}? They will lose access to Workspace data."
        ):
            return
        succeeded, failures = await run_bulk_action(
            devices,
            lambda device: self._service.block_device(
                device.resource_id, display_name=_device_label(device)),
            display_name=_device_label,
            format_error=friendly_google_error,
        )
        if failures:
            QMessageBox.critical(
                self, "Couldn't block device(s)",
                summarize_bulk_failures(len(devices), succeeded, failures))
        await self._on_refresh_clicked()

    @asyncSlot()
    async def _on_remote_wipe_clicked(self) -> None:
        if self._service is None:
            return
        devices = self._selected_devices()
        if not devices:
            self.status_label.setText("Select at least one device first.")
            return
        if len(devices) == 1:
            label = _device_label(devices[0])
            if not confirm_irreversible(
                self, "Remote wipe device",
                f"Remote wipe {label}'s device ({devices[0].model})? "
                "This erases the device's data and cannot be undone.",
                type_to_confirm=label,
            ):
                return
        else:
            names = ", ".join(_device_label(d) for d in devices)
            if not confirm_destructive(
                self, "Remote wipe device(s)",
                f"Remote wipe {names}? This erases each device's data and cannot be undone.",
            ):
                return
        succeeded, failures = await run_bulk_action(
            devices,
            lambda device: self._service.remote_wipe_device(
                device.resource_id, display_name=_device_label(device)),
            display_name=_device_label,
            format_error=friendly_google_error,
        )
        if failures:
            QMessageBox.critical(
                self, "Couldn't remote wipe device(s)",
                summarize_bulk_failures(len(devices), succeeded, failures))
        await self._on_refresh_clicked()

    @asyncSlot()
    async def _on_delete_clicked(self) -> None:
        if self._service is None:
            return
        devices = self._selected_devices()
        if not devices:
            self.status_label.setText("Select at least one device first.")
            return
        names = ", ".join(_device_label(d) for d in devices)
        if not confirm_destructive(
            self, "Unenroll device(s)",
            f"Unenroll {names} from device management? The device itself isn't wiped.",
        ):
            return
        succeeded, failures = await run_bulk_action(
            devices,
            lambda device: self._service.delete_device(
                device.resource_id, display_name=_device_label(device)),
            display_name=_device_label,
            format_error=friendly_google_error,
        )
        if failures:
            QMessageBox.critical(
                self, "Couldn't unenroll device(s)",
                summarize_bulk_failures(len(devices), succeeded, failures))
        await self._on_refresh_clicked()
