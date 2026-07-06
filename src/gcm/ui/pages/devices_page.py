"""Devices page: Entra-registered/joined devices (not Intune-managed device
data -- see gcm.services.device_service for why that's a separate module)."""

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

from gcm.models.device import DeviceSummary
from gcm.services.device_service import DeviceService
from gcm.services.graph_errors import friendly_error_message
from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.confirm import confirm_destructive

_COLUMNS = ["Display name", "Operating system", "Trust type", "Compliant", "Managed", "Status", "Last sign-in"]


def _yes_no_unknown(value: bool | None) -> str:
    if value is None:
        return "Unknown"
    return "Yes" if value else "No"


class DevicesTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._devices: list[DeviceSummary] = []

    def set_devices(self, devices: list[DeviceSummary]) -> None:
        self.beginResetModel()
        self._devices = devices
        self.endResetModel()

    def device_at(self, row: int) -> DeviceSummary:
        return self._devices[row]

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
            return device.display_name
        if column == 1:
            os_name = device.operating_system or "Unknown"
            os_version = f" {device.operating_system_version}" if device.operating_system_version else ""
            return f"{os_name}{os_version}"
        if column == 2:
            return device.trust_type or "Unknown"
        if column == 3:
            return _yes_no_unknown(device.is_compliant)
        if column == 4:
            return _yes_no_unknown(device.is_managed)
        if column == 5:
            return "Enabled" if device.account_enabled else "Disabled"
        if column == 6:
            if device.approximate_last_sign_in is None:
                return "Never"
            return device.approximate_last_sign_in.strftime("%Y-%m-%d %H:%M")
        return None


class DevicesPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Devices")
        self._service: DeviceService | None = None

        layout = QVBoxLayout(self)

        heading = QLabel("Devices")
        heading.setAccessibleName("Devices")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel("Sign in to a tenant (Tenant > Sign in...) to view devices.")
        self.status_label.setAccessibleName("Devices status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        search_row = QHBoxLayout()
        search_label = QLabel("&Search")
        self.search_edit = QLineEdit()
        self.search_edit.setAccessibleName("Search devices")
        self.search_edit.setAccessibleDescription("Matches device display name")
        self.search_edit.setPlaceholderText("Device name")
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

        self.enable_button = AccessibleButton("&Enable selected")
        self.enable_button.clicked.connect(self._on_enable_clicked)
        toolbar_row.addWidget(self.enable_button)

        self.disable_button = AccessibleButton("&Disable selected")
        self.disable_button.clicked.connect(self._on_disable_clicked)
        toolbar_row.addWidget(self.disable_button)

        self.delete_button = AccessibleButton("De&lete selected")
        self.delete_button.clicked.connect(self._on_delete_clicked)
        toolbar_row.addWidget(self.delete_button)
        layout.addLayout(toolbar_row)

        self.model = DevicesTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Devices table")
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
            self.enable_button,
            self.disable_button,
            self.delete_button,
            self.table,
        ):
            widget.setEnabled(enabled)

    def set_graph_client(self, graph_client) -> None:
        if graph_client is None:
            self._service = None
            self.model.set_devices([])
            self.status_label.setText(
                "Sign in to a tenant (Tenant > Sign in...) to view devices."
            )
            self._set_controls_enabled(False)
            return
        self._service = DeviceService(graph_client)
        self._set_controls_enabled(True)
        self._on_refresh_clicked()

    def _selected_devices(self) -> list[DeviceSummary]:
        rows = {index.row() for index in self.table.selectionModel().selectedRows()}
        return [self.model.device_at(row) for row in sorted(rows)]

    @asyncSlot()
    async def _on_refresh_clicked(self) -> None:
        if self._service is None:
            return
        self.status_label.setText("Loading devices...")
        try:
            devices = await self._service.list_devices(self.search_edit.text().strip() or None)
        except Exception as exc:
            self.status_label.setText(f"Couldn't load devices: {friendly_error_message(exc)}")
            return
        self.model.set_devices(devices)
        self.status_label.setText(f"{len(devices)} device(s).")

    @asyncSlot()
    async def _on_enable_clicked(self) -> None:
        await self._set_selected_enabled(True)

    @asyncSlot()
    async def _on_disable_clicked(self) -> None:
        await self._set_selected_enabled(False)

    async def _set_selected_enabled(self, enabled: bool) -> None:
        if self._service is None:
            return
        devices = self._selected_devices()
        if not devices:
            self.status_label.setText("Select at least one device first.")
            return
        try:
            for device in devices:
                await self._service.set_device_enabled(device.id, enabled)
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't update device(s)", friendly_error_message(exc))
        await self._on_refresh_clicked()

    @asyncSlot()
    async def _on_delete_clicked(self) -> None:
        if self._service is None:
            return
        devices = self._selected_devices()
        if not devices:
            self.status_label.setText("Select at least one device first.")
            return
        names = ", ".join(device.display_name for device in devices)
        if not confirm_destructive(
            self, "Delete device(s)", f"Permanently delete {names}? This cannot be undone."
        ):
            return
        try:
            for device in devices:
                await self._service.delete_device(device.id)
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't delete device(s)", friendly_error_message(exc))
        await self._on_refresh_clicked()
