"""Tests for the Licensing/Roles page table models and disconnected-state
behavior. Doesn't touch the network -- feeds the table models sample
dataclasses directly and checks the page's pre-sign-in state."""

from __future__ import annotations

from PySide6.QtCore import Qt

from gcm.models.license import SubscribedSkuSummary
from gcm.models.role import RoleDefinitionSummary
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
    assert not page.sku_checklist.isEnabled()
    assert "Sign in" in page.status_label.text()


def test_roles_page_starts_disconnected_and_disabled(qtbot):
    page = RolesPage()
    qtbot.addWidget(page)

    assert not page.table.isEnabled()
    assert not page.assign_button.isEnabled()
    assert "Sign in" in page.status_label.text()
