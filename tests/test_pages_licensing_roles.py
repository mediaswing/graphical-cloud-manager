"""Tests for the Licensing/Roles page table models and disconnected-state
behavior. Doesn't touch the network -- feeds the table models sample
dataclasses directly and checks the page's pre-sign-in state."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from gcm.models.license import SubscribedSkuSummary, UserLicenseAssignment
from gcm.models.role import RoleDefinitionSummary
from gcm.models.user import UserDetail
from gcm.ui.pages.licensing_page import LicensingPage, SkusTableModel
from gcm.ui.pages.roles_page import RoleDefinitionsTableModel, RolesPage


def test_skus_table_model_renders_rows_and_computes_available():
    model = SkusTableModel()
    model.set_skus(
        [SubscribedSkuSummary(sku_id="s1", sku_part_number="ENTERPRISEPACK", enabled_units=10, consumed_units=4)]
    )
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "ENTERPRISEPACK"
    assert model.data(model.index(0, 3)) == "6"
    assert model.headerData(0, Qt.Orientation.Horizontal) == "SKU"


def test_role_definitions_table_model_renders_rows():
    model = RoleDefinitionsTableModel()
    model.set_roles(
        [
            RoleDefinitionSummary(
                id="r1", display_name="User Administrator", description="Manages users", is_built_in=True
            )
        ]
    )
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "User Administrator"
    assert model.data(model.index(0, 2)) == "Yes"


def test_licensing_page_starts_disconnected_and_disabled(qtbot):
    page = LicensingPage()
    qtbot.addWidget(page)

    assert not page.table.isEnabled()
    assert not page.user_sku_checklist.isEnabled()
    assert not page.group_sku_checklist.isEnabled()
    assert "Sign in" in page.status_label.text()


def test_roles_page_starts_disconnected_and_disabled(qtbot):
    page = RolesPage()
    qtbot.addWidget(page)

    assert not page.table.isEnabled()
    assert not page.assign_button.isEnabled()
    assert "Sign in" in page.status_label.text()


class _FakeUserServiceForLicensing:
    async def get_user_detail(self, upn_or_id):
        return UserDetail(
            id="u1", display_name="Jane Doe", job_title=None, department=None,
            office_location=None, mobile_phone=None, usage_location="US",
        )


class _FakeLicenseServiceForUserPanel:
    def __init__(self, assignments):
        self._assignments = assignments

    async def get_user_license_assignments(self, user_id, skus):
        return self._assignments


@pytest.mark.asyncio
async def test_user_panel_marks_group_derived_license_non_interactive(qtbot):
    page = LicensingPage()
    qtbot.addWidget(page)
    page.model.set_skus(
        [SubscribedSkuSummary(sku_id="s1", sku_part_number="ENTERPRISEPACK", enabled_units=10, consumed_units=1)]
    )
    page._user_service = _FakeUserServiceForLicensing()
    page._license_service = _FakeLicenseServiceForUserPanel(
        [UserLicenseAssignment(sku_id="s1", sku_part_number="ENTERPRISEPACK", assigned_by_group_id="g1", state="Active")]
    )
    page.user_edit.setText("jane@contoso.com")

    await page._on_load_user_clicked()

    item = page.user_sku_checklist.item(0)
    assert "inherited via group" in item.text()
    assert not (item.flags() & Qt.ItemFlag.ItemIsEnabled)
    assert item.checkState() == Qt.CheckState.Checked


@pytest.mark.asyncio
async def test_user_panel_keeps_direct_license_checkbox_interactive(qtbot):
    page = LicensingPage()
    qtbot.addWidget(page)
    page.model.set_skus(
        [SubscribedSkuSummary(sku_id="s1", sku_part_number="ENTERPRISEPACK", enabled_units=10, consumed_units=1)]
    )
    page._user_service = _FakeUserServiceForLicensing()
    page._license_service = _FakeLicenseServiceForUserPanel(
        [UserLicenseAssignment(sku_id="s1", sku_part_number="ENTERPRISEPACK", assigned_by_group_id=None, state="Active")]
    )
    page.user_edit.setText("jane@contoso.com")

    await page._on_load_user_clicked()

    item = page.user_sku_checklist.item(0)
    assert "inherited via group" not in item.text()
    assert item.flags() & Qt.ItemFlag.ItemIsEnabled
    assert item.checkState() == Qt.CheckState.Checked
