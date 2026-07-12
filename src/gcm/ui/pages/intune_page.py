"""Intune page: read-only managed-device inventory.

This page itself stays read-only -- Sync lives on the Devices page's
right-click menu instead (see devices_page.py), since that's the only
device list shown regardless of tenant capability, letting it show a clear
error when a tenant lacks Intune rather than never being reachable at all.
See gcm.services.intune_device_service's module docstring for why the
remaining remote actions (wipe/retire/restart) are out of scope here rather
than just "not wired up yet". This page is only shown when tenant
capability detection finds Intune (see graph/capabilities.py); missing
permissions surface as a plain-language error via friendly_error_message
rather than an empty table with no explanation.
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

from gcm.models.intune_device import IntuneDeviceSummary
from gcm.services.graph_errors import friendly_error_message
from gcm.services.intune_device_service import IntuneDeviceService
from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.csv_export_button import CsvExportButton

_COLUMNS = [
    "Device name", "User", "Operating system", "Compliance",
    "Management state", "Ownership", "Last sync", "Serial number",
]


def _format_user_column(device: IntuneDeviceSummary) -> str:
    """Shared by the table model and the CSV export so a device with no
    assigned user, or a UPN but no display name, reads the same in both
    instead of "(none)" on screen and a bare "()" in the exported file."""
    if device.user_display_name:
        upn_part = f" ({device.user_principal_name})" if device.user_principal_name else ""
        return f"{device.user_display_name}{upn_part}"
    return device.user_principal_name or "(none)"


class IntuneDevicesTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._devices: list[IntuneDeviceSummary] = []
        self._filtered: list[IntuneDeviceSummary] = []

    def set_devices(self, devices: list[IntuneDeviceSummary]) -> None:
        self._devices = devices
        self.set_filter("")

    def set_filter(self, query: str) -> None:
        self.beginResetModel()
        query = query.strip().lower()
        if query:
            self._filtered = [
                d
                for d in self._devices
                if query in d.device_name.lower()
                or query in (d.user_display_name or "").lower()
                or query in (d.user_principal_name or "").lower()
            ]
        else:
            self._filtered = list(self._devices)
        self.endResetModel()

    def all_devices(self) -> list[IntuneDeviceSummary]:
        return list(self._devices)

    def filtered_devices(self) -> list[IntuneDeviceSummary]:
        return list(self._filtered)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._filtered)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        device = self._filtered[index.row()]
        column = index.column()
        if column == 0:
            return device.device_name
        if column == 1:
            return _format_user_column(device)
        if column == 2:
            os_name = device.operating_system or "Unknown"
            os_version = f" {device.os_version}" if device.os_version else ""
            return f"{os_name}{os_version}"
        if column == 3:
            return device.compliance_state or "Unknown"
        if column == 4:
            return device.management_state or "Unknown"
        if column == 5:
            return device.ownership or "Unknown"
        if column == 6:
            return device.last_sync.strftime("%Y-%m-%d %H:%M") if device.last_sync else "Never"
        if column == 7:
            return device.serial_number or ""
        return None


class IntunePage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Intune")
        self._service: IntuneDeviceService | None = None

        layout = QVBoxLayout(self)

        heading = QLabel("Intune")
        heading.setAccessibleName("Intune")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel(
            "Sign in to a tenant (Tenant > Sign in...) to view Intune devices."
        )
        self.status_label.setAccessibleName("Intune status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        note = QLabel(
            "Read-only device inventory here. To sync a device with Intune, "
            "right-click it on the Devices page. Other remote actions "
            "(wipe, retire, restart) aren't available in this version."
        )
        note.setWordWrap(True)
        note.setAccessibleName("Intune read-only note")
        layout.addWidget(note)

        search_row = QHBoxLayout()
        search_label = QLabel("&Filter")
        self.search_edit = QLineEdit()
        self.search_edit.setAccessibleName("Filter Intune devices")
        self.search_edit.setAccessibleDescription("Matches device name or assigned user")
        self.search_edit.setPlaceholderText("Device name or user")
        self.search_edit.textChanged.connect(self._on_filter_changed)
        search_label.setBuddy(self.search_edit)
        search_row.addWidget(search_label)
        search_row.addWidget(self.search_edit)
        layout.addLayout(search_row)

        toolbar_row = QHBoxLayout()
        self.refresh_button = AccessibleButton("&Refresh")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        toolbar_row.addWidget(self.refresh_button)

        self.export_button = CsvExportButton(
            self._csv_rows, self.status_label, default_filename="intune_devices.csv"
        )
        toolbar_row.addWidget(self.export_button)
        layout.addLayout(toolbar_row)

        self.model = IntuneDevicesTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Intune devices table")
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self._set_controls_enabled(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.search_edit, self.refresh_button, self.export_button, self.table):
            widget.setEnabled(enabled)

    def set_graph_client(self, graph_client) -> None:
        if graph_client is None:
            self._service = None
            self.model.set_devices([])
            self.status_label.setText(
                "Sign in to a tenant (Tenant > Sign in...) to view Intune devices."
            )
            self._set_controls_enabled(False)
            return
        self._service = IntuneDeviceService(graph_client)
        self._set_controls_enabled(True)
        self._on_refresh_clicked()

    def _on_filter_changed(self, text: str) -> None:
        self.model.set_filter(text)

    @asyncSlot()
    async def _on_refresh_clicked(self) -> None:
        if self._service is None:
            return
        self.status_label.setText("Loading Intune devices...")
        try:
            devices = await self._service.list_managed_devices()
        except Exception as exc:
            self.status_label.setText(
                f"Couldn't load Intune devices: {friendly_error_message(exc)}"
            )
            return
        self.model.set_devices(devices)
        self.model.set_filter(self.search_edit.text())
        self.status_label.setText(f"{len(devices)} device(s).")

    def _csv_rows(self):
        headers = list(_COLUMNS)
        rows = []
        for d in self.model.filtered_devices():
            os_name = d.operating_system or "Unknown"
            os_version = f" {d.os_version}" if d.os_version else ""
            last_sync = d.last_sync.strftime("%Y-%m-%d %H:%M") if d.last_sync else "Never"
            rows.append(
                [
                    d.device_name,
                    _format_user_column(d),
                    f"{os_name}{os_version}",
                    d.compliance_state or "Unknown",
                    d.management_state or "Unknown",
                    d.ownership or "Unknown",
                    last_sync,
                    d.serial_number or "",
                ]
            )
        return headers, rows
