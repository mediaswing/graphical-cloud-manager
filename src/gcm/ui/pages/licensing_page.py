"""Licensing page: tenant-wide SKU consumption, plus assigning/removing
licenses for a specific user."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from gcm.models.license import SubscribedSkuSummary
from gcm.services.graph_errors import friendly_error_message
from gcm.services.license_service import LicenseService
from gcm.services.user_service import UserService
from gcm.ui.widgets.accessible_button import AccessibleButton

_COLUMNS = ["SKU", "Enabled", "Consumed", "Available"]
_SKU_ID_ROLE = Qt.ItemDataRole.UserRole


class SkusTableModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._skus: list[SubscribedSkuSummary] = []

    def set_skus(self, skus: list[SubscribedSkuSummary]) -> None:
        self.beginResetModel()
        self._skus = skus
        self.endResetModel()

    def sku_at(self, row: int) -> SubscribedSkuSummary:
        return self._skus[row]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._skus)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        sku = self._skus[index.row()]
        column = index.column()
        if column == 0:
            return sku.sku_part_number
        if column == 1:
            return str(sku.enabled_units)
        if column == 2:
            return str(sku.consumed_units)
        if column == 3:
            return str(sku.available_units)
        return None


class LicensingPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Licensing")
        self._license_service: LicenseService | None = None
        self._user_service: UserService | None = None
        self._loaded_user_id: str | None = None
        self._original_sku_ids: set[str] = set()

        layout = QVBoxLayout(self)

        heading = QLabel("Licensing")
        heading.setAccessibleName("Licensing")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel(
            "Sign in to a tenant (Tenant > Sign in...) to view licensing."
        )
        self.status_label.setAccessibleName("Licensing status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.refresh_button = AccessibleButton("&Refresh SKUs")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        layout.addWidget(self.refresh_button)

        splitter = QSplitter()
        layout.addWidget(splitter, stretch=1)

        self.model = SkusTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Subscribed SKUs table")
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        splitter.addWidget(self.table)

        assign_panel = QWidget()
        assign_layout = QVBoxLayout(assign_panel)

        assign_heading = QLabel("Assign licenses to a user")
        assign_heading.setAccessibleName("Assign licenses to a user")
        assign_layout.addWidget(assign_heading)

        load_row = QHBoxLayout()
        load_label = QLabel("&User (UPN or object ID)")
        self.user_edit = QLineEdit()
        self.user_edit.setAccessibleName("User to manage licenses for")
        self.user_edit.setPlaceholderText("jane.doe@contoso.com")
        self.user_edit.returnPressed.connect(self._on_load_user_clicked)
        load_label.setBuddy(self.user_edit)
        load_row.addWidget(load_label)
        load_row.addWidget(self.user_edit)

        self.load_button = AccessibleButton("&Load")
        self.load_button.clicked.connect(self._on_load_user_clicked)
        load_row.addWidget(self.load_button)
        assign_layout.addLayout(load_row)

        self.assign_status_label = QLabel(
            "Load a user to see and change their assigned licenses."
        )
        self.assign_status_label.setAccessibleName("Assign licenses status")
        self.assign_status_label.setWordWrap(True)
        assign_layout.addWidget(self.assign_status_label)

        self.sku_checklist = QListWidget()
        self.sku_checklist.setAccessibleName("Licenses for this user")
        self.sku_checklist.setAccessibleDescription(
            "Check a license to assign it, uncheck to remove it, then choose Apply."
        )
        assign_layout.addWidget(self.sku_checklist)

        self.apply_button = AccessibleButton("&Apply license changes")
        self.apply_button.clicked.connect(self._on_apply_clicked)
        assign_layout.addWidget(self.apply_button)

        splitter.addWidget(assign_panel)

        self._set_controls_enabled(False)
        self._set_assign_controls_enabled(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.refresh_button, self.table, self.user_edit, self.load_button):
            widget.setEnabled(enabled)

    def _set_assign_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.sku_checklist, self.apply_button):
            widget.setEnabled(enabled)

    def set_graph_client(self, graph_client) -> None:
        if graph_client is None:
            self._license_service = None
            self._user_service = None
            self._loaded_user_id = None
            self.model.set_skus([])
            self.sku_checklist.clear()
            self.status_label.setText(
                "Sign in to a tenant (Tenant > Sign in...) to view licensing."
            )
            self.assign_status_label.setText(
                "Load a user to see and change their assigned licenses."
            )
            self._set_controls_enabled(False)
            self._set_assign_controls_enabled(False)
            return
        self._license_service = LicenseService(graph_client)
        self._user_service = UserService(graph_client)
        self._set_controls_enabled(True)
        self._on_refresh_clicked()

    @asyncSlot()
    async def _on_refresh_clicked(self) -> None:
        if self._license_service is None:
            return
        self.status_label.setText("Loading SKUs...")
        try:
            skus = await self._license_service.list_subscribed_skus()
        except Exception as exc:
            self.status_label.setText(f"Couldn't load SKUs: {friendly_error_message(exc)}")
            return
        self.model.set_skus(skus)
        self.status_label.setText(f"{len(skus)} subscribed SKU(s).")

    @asyncSlot()
    async def _on_load_user_clicked(self) -> None:
        if self._license_service is None or self._user_service is None:
            return
        upn_or_id = self.user_edit.text().strip()
        if not upn_or_id:
            self.assign_status_label.setText("Enter a user principal name or object ID first.")
            return
        try:
            detail = await self._user_service.get_user_detail(upn_or_id)
            sku_ids = await self._license_service.get_user_license_sku_ids(upn_or_id)
        except Exception as exc:
            self.assign_status_label.setText(f"Couldn't load user: {friendly_error_message(exc)}")
            return

        self._loaded_user_id = detail.id
        self._original_sku_ids = sku_ids
        self.sku_checklist.clear()
        for row in range(self.model.rowCount()):
            sku = self.model.sku_at(row)
            sku_id = sku.sku_id
            item = QListWidgetItem(sku.sku_part_number)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if sku_id in sku_ids else Qt.CheckState.Unchecked
            )
            item.setData(_SKU_ID_ROLE, sku_id)
            self.sku_checklist.addItem(item)

        location_note = (
            "" if detail.usage_location else " Note: this user has no usage location set "
            "(edit them on the Users page) -- Graph requires one before a license can be assigned."
        )
        self.assign_status_label.setText(f"Editing licenses for {detail.display_name}.{location_note}")
        self._set_assign_controls_enabled(True)

    @asyncSlot()
    async def _on_apply_clicked(self) -> None:
        if self._license_service is None or self._loaded_user_id is None:
            return
        checked_sku_ids = {
            self.sku_checklist.item(row).data(_SKU_ID_ROLE)
            for row in range(self.sku_checklist.count())
            if self.sku_checklist.item(row).checkState() == Qt.CheckState.Checked
        }
        add_sku_ids = list(checked_sku_ids - self._original_sku_ids)
        remove_sku_ids = list(self._original_sku_ids - checked_sku_ids)
        if not add_sku_ids and not remove_sku_ids:
            self.assign_status_label.setText("No license changes to apply.")
            return
        try:
            await self._license_service.set_user_licenses(
                self._loaded_user_id, add_sku_ids=add_sku_ids, remove_sku_ids=remove_sku_ids
            )
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't update licenses", friendly_error_message(exc))
            return
        self._original_sku_ids = checked_sku_ids
        self.assign_status_label.setText("License changes applied.")
        await self._on_refresh_clicked()
