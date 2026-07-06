"""Licensing page: tenant-wide SKU consumption, plus assigning/removing
licenses for a specific user or a specific group.

Group-based licensing is asynchronous on Microsoft's side: a group's
`licenseProcessingState` tells you whether Microsoft has actually finished
applying a recent change, and that state is always shown rather than
implying the change took effect the moment Apply was clicked. A user's
license checklist distinguishes licenses assigned directly from ones
inherited through a group -- the latter can't be removed here (Graph
manages them), so their checkboxes are shown but not interactive.
"""

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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from gcm.models.license import SubscribedSkuSummary
from gcm.services.graph_errors import friendly_error_message
from gcm.services.group_service import GroupService
from gcm.services.license_service import LicenseService
from gcm.services.user_service import UserService
from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.confirm import confirm_destructive
from gcm.ui.widgets.csv_export_button import CsvExportButton

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

    def all_skus(self) -> list[SubscribedSkuSummary]:
        return list(self._skus)

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
        self._group_service: GroupService | None = None

        self._loaded_user_id: str | None = None
        self._loaded_display_name: str | None = None
        self._original_direct_sku_ids: set[str] = set()

        self._loaded_group_id: str | None = None
        self._loaded_group_display_name: str | None = None
        self._original_group_sku_ids: set[str] = set()

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

        toolbar_row = QHBoxLayout()
        self.refresh_button = AccessibleButton("&Refresh SKUs")
        self.refresh_button.clicked.connect(self._on_refresh_clicked)
        toolbar_row.addWidget(self.refresh_button)

        self.export_button = CsvExportButton(
            self._csv_rows, self.status_label, default_filename="licenses.csv"
        )
        toolbar_row.addWidget(self.export_button)
        layout.addLayout(toolbar_row)

        splitter = QSplitter()
        layout.addWidget(splitter, stretch=1)

        self.model = SkusTableModel()
        self.table = QTableView()
        self.table.setAccessibleName("Subscribed SKUs table")
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        splitter.addWidget(self.table)

        self.assign_tabs = QTabWidget()
        self.assign_tabs.setAccessibleName("Assign licenses")
        self.assign_tabs.addTab(self._build_user_panel(), "User")
        self.assign_tabs.addTab(self._build_group_panel(), "Group")
        splitter.addWidget(self.assign_tabs)

        self._set_controls_enabled(False)
        self._set_user_assign_controls_enabled(False)
        self._set_group_assign_controls_enabled(False)

    # -- User panel ---------------------------------------------------------

    def _build_user_panel(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)

        load_row = QHBoxLayout()
        load_label = QLabel("&User (UPN or object ID)")
        self.user_edit = QLineEdit()
        self.user_edit.setAccessibleName("User to manage licenses for")
        self.user_edit.setPlaceholderText("jane.doe@contoso.com")
        self.user_edit.returnPressed.connect(self._on_load_user_clicked)
        load_label.setBuddy(self.user_edit)
        load_row.addWidget(load_label)
        load_row.addWidget(self.user_edit)

        self.load_user_button = AccessibleButton("&Load user")
        self.load_user_button.clicked.connect(self._on_load_user_clicked)
        load_row.addWidget(self.load_user_button)
        panel_layout.addLayout(load_row)

        self.user_assign_status_label = QLabel(
            "Load a user to see and change their assigned licenses."
        )
        self.user_assign_status_label.setAccessibleName("User license status")
        self.user_assign_status_label.setWordWrap(True)
        panel_layout.addWidget(self.user_assign_status_label)

        self.user_sku_checklist = QListWidget()
        self.user_sku_checklist.setAccessibleName("Licenses for this user")
        self.user_sku_checklist.setAccessibleDescription(
            "Check a license to assign it directly, uncheck to remove it, then choose "
            "Apply. Licenses inherited from a group can't be changed here."
        )
        panel_layout.addWidget(self.user_sku_checklist)

        self.apply_user_button = AccessibleButton("&Apply license changes")
        self.apply_user_button.clicked.connect(self._on_apply_user_clicked)
        panel_layout.addWidget(self.apply_user_button)

        return panel

    # -- Group panel ----------------------------------------------------------

    def _build_group_panel(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)

        note = QLabel(
            "Licenses assigned here apply to every current and future member of the "
            "group. Microsoft processes group license changes asynchronously -- the "
            "processing status below shows when a recent change hasn't fully applied "
            "yet."
        )
        note.setWordWrap(True)
        note.setAccessibleName("Group licensing note")
        panel_layout.addWidget(note)

        load_row = QHBoxLayout()
        load_label = QLabel("&Group object ID")
        self.group_edit = QLineEdit()
        self.group_edit.setAccessibleName("Group to manage licenses for")
        self.group_edit.setAccessibleDescription(
            "The group's object ID -- find it via the Groups page's CSV export"
        )
        self.group_edit.setPlaceholderText("11111111-2222-3333-4444-555555555555")
        self.group_edit.returnPressed.connect(self._on_load_group_clicked)
        load_label.setBuddy(self.group_edit)
        load_row.addWidget(load_label)
        load_row.addWidget(self.group_edit)

        self.load_group_button = AccessibleButton("Load &group")
        self.load_group_button.clicked.connect(self._on_load_group_clicked)
        load_row.addWidget(self.load_group_button)
        panel_layout.addLayout(load_row)

        self.group_assign_status_label = QLabel(
            "Load a group to see and change its assigned licenses."
        )
        self.group_assign_status_label.setAccessibleName("Group license status")
        self.group_assign_status_label.setWordWrap(True)
        panel_layout.addWidget(self.group_assign_status_label)

        self.group_sku_checklist = QListWidget()
        self.group_sku_checklist.setAccessibleName("Licenses for this group")
        self.group_sku_checklist.setAccessibleDescription(
            "Check a license to assign it to the group, uncheck to remove it, then "
            "choose Apply."
        )
        panel_layout.addWidget(self.group_sku_checklist)

        self.apply_group_button = AccessibleButton("App&ly group license changes")
        self.apply_group_button.clicked.connect(self._on_apply_group_clicked)
        panel_layout.addWidget(self.apply_group_button)

        return panel

    # -- Shared state ---------------------------------------------------------

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.refresh_button,
            self.export_button,
            self.table,
            self.user_edit,
            self.load_user_button,
            self.group_edit,
            self.load_group_button,
        ):
            widget.setEnabled(enabled)

    def _set_user_assign_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.user_sku_checklist, self.apply_user_button):
            widget.setEnabled(enabled)

    def _set_group_assign_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.group_sku_checklist, self.apply_group_button):
            widget.setEnabled(enabled)

    def _csv_rows(self):
        headers = ["SKU", "Enabled", "Consumed", "Available"]
        rows = [
            [sku.sku_part_number, sku.enabled_units, sku.consumed_units, sku.available_units]
            for sku in self.model.all_skus()
        ]
        return headers, rows

    def set_graph_client(self, graph_client) -> None:
        if graph_client is None:
            self._license_service = None
            self._user_service = None
            self._group_service = None
            self._loaded_user_id = None
            self._loaded_group_id = None
            self.model.set_skus([])
            self.user_sku_checklist.clear()
            self.group_sku_checklist.clear()
            self.status_label.setText(
                "Sign in to a tenant (Tenant > Sign in...) to view licensing."
            )
            self.user_assign_status_label.setText(
                "Load a user to see and change their assigned licenses."
            )
            self.group_assign_status_label.setText(
                "Load a group to see and change its assigned licenses."
            )
            self._set_controls_enabled(False)
            self._set_user_assign_controls_enabled(False)
            self._set_group_assign_controls_enabled(False)
            return
        self._license_service = LicenseService(graph_client)
        self._user_service = UserService(graph_client)
        self._group_service = GroupService(graph_client)
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

    # -- User assignment ------------------------------------------------------

    @asyncSlot()
    async def _on_load_user_clicked(self) -> None:
        if self._license_service is None or self._user_service is None:
            return
        upn_or_id = self.user_edit.text().strip()
        if not upn_or_id:
            self.user_assign_status_label.setText("Enter a user principal name or object ID first.")
            return
        try:
            detail = await self._user_service.get_user_detail(upn_or_id)
            assignments = await self._license_service.get_user_license_assignments(
                upn_or_id, self.model.all_skus()
            )
        except Exception as exc:
            self.user_assign_status_label.setText(
                f"Couldn't load user: {friendly_error_message(exc)}"
            )
            return

        self._loaded_user_id = detail.id
        self._loaded_display_name = detail.display_name
        direct_sku_ids = {a.sku_id for a in assignments if a.is_direct}
        group_derived_sku_ids = {a.sku_id for a in assignments if not a.is_direct}
        self._original_direct_sku_ids = direct_sku_ids

        self.user_sku_checklist.clear()
        for sku in self.model.all_skus():
            via_group = sku.sku_id in group_derived_sku_ids
            label = sku.sku_part_number + (" (inherited via group membership)" if via_group else "")
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if via_group:
                # Graph manages group-derived licenses; toggling them off
                # here wouldn't remove them (the group would just reassign
                # it), so make that state visible but not interactive.
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(
                    Qt.CheckState.Checked if sku.sku_id in direct_sku_ids else Qt.CheckState.Unchecked
                )
            item.setData(_SKU_ID_ROLE, sku.sku_id)
            self.user_sku_checklist.addItem(item)

        location_note = (
            "" if detail.usage_location else " Note: this user has no usage location set "
            "(edit them on the Users page) -- Graph requires one before a license can be assigned."
        )
        self.user_assign_status_label.setText(
            f"Editing licenses for {detail.display_name}.{location_note}"
        )
        self._set_user_assign_controls_enabled(True)

    @asyncSlot()
    async def _on_apply_user_clicked(self) -> None:
        if self._license_service is None or self._loaded_user_id is None:
            return
        checked_sku_ids = {
            self.user_sku_checklist.item(row).data(_SKU_ID_ROLE)
            for row in range(self.user_sku_checklist.count())
            if self.user_sku_checklist.item(row).flags() & Qt.ItemFlag.ItemIsEnabled
            and self.user_sku_checklist.item(row).checkState() == Qt.CheckState.Checked
        }
        add_sku_ids = list(checked_sku_ids - self._original_direct_sku_ids)
        remove_sku_ids = list(self._original_direct_sku_ids - checked_sku_ids)
        if not add_sku_ids and not remove_sku_ids:
            self.user_assign_status_label.setText("No license changes to apply.")
            return
        if not confirm_destructive(
            self,
            "Apply license changes",
            f"Assign {len(add_sku_ids)} and remove {len(remove_sku_ids)} license(s) "
            f"for {self._loaded_display_name}?",
        ):
            return
        try:
            await self._license_service.set_user_licenses(
                self._loaded_user_id,
                add_sku_ids=add_sku_ids,
                remove_sku_ids=remove_sku_ids,
                display_name=self._loaded_display_name,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't update licenses", friendly_error_message(exc))
            return
        self._original_direct_sku_ids = checked_sku_ids
        self.user_assign_status_label.setText("License changes applied.")
        await self._on_refresh_clicked()

    # -- Group assignment -----------------------------------------------------

    @asyncSlot()
    async def _on_load_group_clicked(self) -> None:
        if self._license_service is None or self._group_service is None:
            return
        group_id = self.group_edit.text().strip()
        if not group_id:
            self.group_assign_status_label.setText("Enter a group object ID first.")
            return
        try:
            group = await self._group_service.get_group(group_id)
            sku_ids, processing_state = await self._license_service.get_group_license_info(
                group_id
            )
        except Exception as exc:
            self.group_assign_status_label.setText(
                f"Couldn't load group: {friendly_error_message(exc)}"
            )
            return

        self._loaded_group_id = group.id
        self._loaded_group_display_name = group.display_name
        self._original_group_sku_ids = sku_ids

        self.group_sku_checklist.clear()
        for sku in self.model.all_skus():
            item = QListWidgetItem(sku.sku_part_number)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if sku.sku_id in sku_ids else Qt.CheckState.Unchecked
            )
            item.setData(_SKU_ID_ROLE, sku.sku_id)
            self.group_sku_checklist.addItem(item)

        processing_note = (
            f" License processing status: {processing_state}."
            if processing_state and processing_state != "Success"
            else ""
        )
        self.group_assign_status_label.setText(
            f"Editing licenses for group {group.display_name}.{processing_note}"
        )
        self._set_group_assign_controls_enabled(True)

    @asyncSlot()
    async def _on_apply_group_clicked(self) -> None:
        if self._license_service is None or self._loaded_group_id is None:
            return
        checked_sku_ids = {
            self.group_sku_checklist.item(row).data(_SKU_ID_ROLE)
            for row in range(self.group_sku_checklist.count())
            if self.group_sku_checklist.item(row).checkState() == Qt.CheckState.Checked
        }
        add_sku_ids = list(checked_sku_ids - self._original_group_sku_ids)
        remove_sku_ids = list(self._original_group_sku_ids - checked_sku_ids)
        if not add_sku_ids and not remove_sku_ids:
            self.group_assign_status_label.setText("No license changes to apply.")
            return
        if not confirm_destructive(
            self,
            "Apply group license changes",
            f"Assign {len(add_sku_ids)} and remove {len(remove_sku_ids)} license(s) "
            f"for every member of {self._loaded_group_display_name!r}? Microsoft applies "
            "this to members asynchronously, not instantly.",
        ):
            return
        try:
            await self._license_service.set_group_licenses(
                self._loaded_group_id,
                add_sku_ids=add_sku_ids,
                remove_sku_ids=remove_sku_ids,
                display_name=self._loaded_group_display_name,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't update group licenses", friendly_error_message(exc))
            return
        self._original_group_sku_ids = checked_sku_ids
        self.group_assign_status_label.setText(
            "License changes submitted. Microsoft may take some time to finish applying them."
        )
        await self._on_refresh_clicked()
