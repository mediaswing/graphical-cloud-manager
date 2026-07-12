"""Tests for the Bulk import page table model and disconnected-state
behavior. Doesn't touch the network -- feeds the table model sample
dataclasses directly."""

from __future__ import annotations

import pytest

from gcm.models.bulk_import import ImportRow, ImportRowResult
from gcm.ui.pages import bulk_import_page as bulk_import_page_module
from gcm.ui.pages.bulk_import_page import BulkImportPage, BulkImportTableModel


def _row(row_number=1, errors=None, warnings=None):
    return ImportRow(
        row_number=row_number,
        display_name="Jane Doe",
        user_principal_name="jane@contoso.com",
        mail_nickname="jane",
        password="Password1!",
        account_enabled=True,
        usage_location=None,
        license_sku_part_numbers=[],
        group_names=[],
        errors=errors or [],
        warnings=warnings or [],
    )


def test_table_model_shows_ready_for_a_valid_row_before_running():
    model = BulkImportTableModel()
    model.set_rows([_row()])
    assert model.data(model.index(0, 3)) == "Ready"


def test_table_model_shows_blocked_reason_for_invalid_row():
    model = BulkImportTableModel()
    model.set_rows([_row(errors=["Display name is required."])])
    assert "Blocked" in model.data(model.index(0, 3))
    assert "Display name is required." in model.data(model.index(0, 3))


def test_table_model_shows_warning_for_a_row_with_only_warnings():
    model = BulkImportTableModel()
    model.set_rows([_row(warnings=["Password is shorter than 8 characters..."])])
    assert model.data(model.index(0, 3)).startswith("Warning")


def test_table_model_shows_result_after_execution():
    model = BulkImportTableModel()
    model.set_rows([_row(row_number=1)])
    model.set_results([ImportRowResult(1, "Jane Doe", "jane@contoso.com", success=True, message="Created successfully.")])
    assert model.data(model.index(0, 3)) == "Success"


def test_table_model_shows_failure_message_after_execution():
    model = BulkImportTableModel()
    model.set_rows([_row(row_number=1)])
    model.set_results(
        [ImportRowResult(1, "Jane Doe", "jane@contoso.com", success=False, message="Insufficient privileges")]
    )
    assert model.data(model.index(0, 3)) == "Failed: Insufficient privileges"


def test_valid_row_count_excludes_blocked_rows():
    model = BulkImportTableModel()
    model.set_rows([_row(row_number=1), _row(row_number=2, errors=["bad"])])
    assert model.valid_row_count() == 1


def test_bulk_import_page_starts_disconnected_and_disabled(qtbot):
    page = BulkImportPage()
    qtbot.addWidget(page)

    assert not page.choose_file_button.isEnabled()
    assert not page.run_button.isEnabled()
    assert not page.cancel_button.isEnabled()
    assert "Sign in" in page.status_label.text()


def test_bulk_import_page_run_button_disabled_with_no_valid_rows(qtbot):
    page = BulkImportPage()
    qtbot.addWidget(page)
    page.set_graph_client(object())  # any non-None sentinel is enough to "connect" the page
    page.model.set_rows([_row(errors=["bad"])])
    page._update_run_cancel_state()

    assert not page.run_button.isEnabled()
    assert page.cancel_button.isEnabled()


def test_bulk_import_page_run_button_enabled_with_a_valid_row(qtbot):
    page = BulkImportPage()
    qtbot.addWidget(page)
    page.set_graph_client(object())
    page.model.set_rows([_row()])
    page._update_run_cancel_state()

    assert page.run_button.isEnabled()


@pytest.mark.asyncio
async def test_choose_file_keeps_tenant_validation_error_visible(qtbot, monkeypatch, tmp_path):
    """A failed tenant-validation pass used to flash its error message for a
    moment before the very next lines unconditionally overwrote it with the
    generic "N row(s) loaded" summary -- hiding that per-row checks (existing
    user/SKU/group lookups) never actually ran."""
    page = BulkImportPage()
    qtbot.addWidget(page)

    csv_path = tmp_path / "import.csv"
    csv_path.write_text("display_name,user_principal_name,mail_nickname,password\n")
    monkeypatch.setattr(
        bulk_import_page_module.QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (str(csv_path), "")))

    class FakeService:
        def parse_and_validate_locally(self, path):
            return [_row()]

        async def validate_against_tenant(self, rows):
            raise RuntimeError("tenant unreachable")

    page._service = FakeService()

    await page._on_choose_file_clicked()

    text = page.status_label.text()
    assert "1 row(s) loaded" in text
    assert "Couldn't fully validate against the tenant" in text
