"""Unit test for DeviceService's Graph-model-to-dataclass conversion.
Doesn't touch the network -- constructs a real msgraph Device model directly."""

from __future__ import annotations

import datetime

from msgraph.generated.models.device import Device

from gcm.services.device_service import _to_summary


def test_to_summary_maps_fields():
    device = Device(
        id="d1",
        display_name="Janes-MacBook",
        operating_system="MacOS",
        operating_system_version="15.0",
        trust_type="AzureAd",
        is_compliant=True,
        is_managed=True,
        account_enabled=True,
        approximate_last_sign_in_date_time=datetime.datetime(2026, 7, 1),
    )
    summary = _to_summary(device)
    assert summary.display_name == "Janes-MacBook"
    assert summary.operating_system == "MacOS"
    assert summary.is_compliant is True
    assert summary.approximate_last_sign_in == datetime.datetime(2026, 7, 1)


def test_to_summary_falls_back_to_placeholder_display_name():
    device = Device(id="d2", display_name=None, account_enabled=False)
    summary = _to_summary(device)
    assert summary.display_name == "(no display name)"
    assert summary.is_compliant is None
    assert summary.approximate_last_sign_in is None
