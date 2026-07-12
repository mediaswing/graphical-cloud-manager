"""Tests for the Intune page table model, client-side filtering, and
disconnected-state behavior. Doesn't touch the network -- feeds the table
model sample dataclasses directly."""

from __future__ import annotations

import datetime

from gcm.models.intune_device import IntuneDeviceSummary
from gcm.ui.pages.intune_page import IntuneDevicesTableModel, IntunePage, _format_user_column


def _device(name="Janes-iPhone", user_display_name="Jane Doe", user_principal_name="jane@contoso.com"):
    return IntuneDeviceSummary(
        id="d1",
        device_name=name,
        operating_system="iOS",
        os_version="17.0",
        compliance_state="compliant",
        management_state="managed",
        management_agent="mdm",
        ownership="company",
        user_display_name=user_display_name,
        user_principal_name=user_principal_name,
        last_sync=datetime.datetime(2026, 7, 1, 9, 30),
        serial_number="SN1",
        azure_ad_device_id="aad-1",
    )


def test_table_model_renders_rows():
    model = IntuneDevicesTableModel()
    model.set_devices([_device()])
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "Janes-iPhone"
    assert model.data(model.index(0, 3)) == "compliant"
    assert model.data(model.index(0, 6)) == "2026-07-01 09:30"


def test_table_model_handles_missing_fields():
    device = IntuneDeviceSummary(
        id="d2", device_name="Device", operating_system=None, os_version=None,
        compliance_state=None, management_state=None, management_agent=None,
        ownership=None, user_display_name=None, user_principal_name=None,
        last_sync=None, serial_number=None, azure_ad_device_id=None,
    )
    model = IntuneDevicesTableModel()
    model.set_devices([device])
    assert model.data(model.index(0, 1)) == "(none)"
    assert model.data(model.index(0, 3)) == "Unknown"
    assert model.data(model.index(0, 6)) == "Never"


def test_format_user_column_matches_between_table_and_csv_export():
    """_format_user_column is shared by the table model's column 1 and the
    CSV export's user column specifically so they can't drift apart -- the
    table used to show "(none)"/a bare UPN while the CSV independently
    rendered "()"/a parenthesized UPN for the same rows."""
    no_user = _device(user_display_name=None, user_principal_name=None)
    assert _format_user_column(no_user) == "(none)"

    upn_only = _device(user_display_name=None, user_principal_name="jane@contoso.com")
    assert _format_user_column(upn_only) == "jane@contoso.com"

    both = _device(user_display_name="Jane Doe", user_principal_name="jane@contoso.com")
    assert _format_user_column(both) == "Jane Doe (jane@contoso.com)"


def test_filter_matches_device_name():
    model = IntuneDevicesTableModel()
    model.set_devices([_device(name="Janes-iPhone"), _device(name="Johns-iPad", user_display_name="John Roe", user_principal_name="john@contoso.com")])
    model.set_filter("iPad")
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "Johns-iPad"


def test_filter_matches_user_display_name():
    model = IntuneDevicesTableModel()
    model.set_devices([_device(name="Janes-iPhone"), _device(name="Johns-iPad", user_display_name="John Roe", user_principal_name="john@contoso.com")])
    model.set_filter("John Roe")
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "Johns-iPad"


def test_empty_filter_shows_all_devices():
    model = IntuneDevicesTableModel()
    model.set_devices([_device(name="A"), _device(name="B")])
    model.set_filter("")
    assert model.rowCount() == 2


def test_intune_page_starts_disconnected_and_disabled(qtbot):
    page = IntunePage()
    qtbot.addWidget(page)

    assert not page.table.isEnabled()
    assert not page.refresh_button.isEnabled()
    assert "Sign in" in page.status_label.text()
