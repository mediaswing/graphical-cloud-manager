"""Tests for the Devices/Sign-in-logs page table models and disconnected-
state behavior. Doesn't touch the network -- feeds the table models sample
dataclasses directly and checks the page's pre-sign-in state."""

from __future__ import annotations

import datetime

from gcm.models.device import DeviceSummary
from gcm.models.sign_in import SignInSummary
from gcm.ui.pages.devices_page import DevicesPage, DevicesTableModel
from gcm.ui.pages.sign_in_logs_page import SignInLogsPage, SignInLogsTableModel


def test_devices_table_model_renders_rows():
    model = DevicesTableModel()
    model.set_devices(
        [
            DeviceSummary(
                id="d1",
                display_name="Janes-MacBook",
                operating_system="MacOS",
                operating_system_version="15.0",
                trust_type="AzureAd",
                is_compliant=True,
                is_managed=True,
                account_enabled=True,
                approximate_last_sign_in=datetime.datetime(2026, 7, 1, 9, 30),
            )
        ]
    )
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "Janes-MacBook"
    assert model.data(model.index(0, 1)) == "MacOS 15.0"
    assert model.data(model.index(0, 3)) == "Yes"
    assert model.data(model.index(0, 6)) == "2026-07-01 09:30"


def test_devices_table_model_handles_unknown_fields():
    model = DevicesTableModel()
    model.set_devices(
        [
            DeviceSummary(
                id="d2",
                display_name="Device",
                operating_system=None,
                operating_system_version=None,
                trust_type=None,
                is_compliant=None,
                is_managed=None,
                account_enabled=False,
                approximate_last_sign_in=None,
            )
        ]
    )
    assert model.data(model.index(0, 1)) == "Unknown"
    assert model.data(model.index(0, 3)) == "Unknown"
    assert model.data(model.index(0, 5)) == "Disabled"
    assert model.data(model.index(0, 6)) == "Never"


def test_sign_in_logs_table_model_renders_rows():
    model = SignInLogsTableModel()
    model.set_sign_ins(
        [
            SignInSummary(
                id="s1",
                created_at=datetime.datetime(2026, 7, 6, 10, 0),
                user_display_name="Jane Doe",
                user_principal_name="jane@contoso.com",
                app_display_name="Office 365",
                ip_address="1.2.3.4",
                device_display_name="Janes-MacBook",
                device_operating_system="MacOS",
                succeeded=True,
                failure_reason=None,
            )
        ]
    )
    assert model.rowCount() == 1
    assert model.data(model.index(0, 1)) == "Jane Doe (jane@contoso.com)"
    assert model.data(model.index(0, 3)) == "Janes-MacBook, MacOS"
    assert model.data(model.index(0, 4)) == "Success"


def test_sign_in_logs_table_model_renders_failure_without_device():
    model = SignInLogsTableModel()
    model.set_sign_ins(
        [
            SignInSummary(
                id="s2",
                created_at=None,
                user_display_name="(unknown)",
                user_principal_name="",
                app_display_name="(unknown)",
                ip_address=None,
                device_display_name=None,
                device_operating_system=None,
                succeeded=False,
                failure_reason="Invalid password",
            )
        ]
    )
    assert model.data(model.index(0, 0)) == "Unknown"
    assert model.data(model.index(0, 3)) == "(no device info)"
    assert model.data(model.index(0, 4)) == "Failed: Invalid password"


def test_devices_page_starts_disconnected_and_disabled(qtbot):
    page = DevicesPage()
    qtbot.addWidget(page)

    assert not page.table.isEnabled()
    assert not page.delete_button.isEnabled()
    assert "Sign in" in page.status_label.text()


def test_sign_in_logs_page_starts_disconnected_and_disabled(qtbot):
    page = SignInLogsPage()
    qtbot.addWidget(page)

    assert not page.table.isEnabled()
    assert not page.search_button.isEnabled()
    assert "Sign in" in page.status_label.text()
