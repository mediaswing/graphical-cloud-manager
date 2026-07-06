"""Unit test for IntuneDeviceService's Graph-model-to-dataclass conversion.
Doesn't touch the network -- constructs a real msgraph ManagedDevice model
directly.

Covers a real bug caught while writing this: Kiota generates Graph's
compliance/management enums as (str, Enum) mixins, so `str(x)` gives
"ComplianceState.Compliant" rather than the plain "compliant" -- _to_summary
must go through `.value`.
"""

from __future__ import annotations

import datetime

from msgraph.generated.models.compliance_state import ComplianceState
from msgraph.generated.models.managed_device import ManagedDevice
from msgraph.generated.models.managed_device_owner_type import ManagedDeviceOwnerType

from gcm.services.intune_device_service import _to_summary


def test_to_summary_converts_enum_fields_to_plain_string_values():
    device = ManagedDevice(
        id="d1",
        device_name="Janes-iPhone",
        operating_system="iOS",
        os_version="17.0",
        compliance_state=ComplianceState.Compliant,
        managed_device_owner_type=ManagedDeviceOwnerType.Company,
        user_display_name="Jane Doe",
        user_principal_name="jane@contoso.com",
        last_sync_date_time=datetime.datetime(2026, 7, 1, 9, 0),
        serial_number="SN12345",
    )
    summary = _to_summary(device)

    assert summary.compliance_state == "compliant"
    assert summary.ownership == "company"
    assert summary.device_name == "Janes-iPhone"
    assert summary.user_principal_name == "jane@contoso.com"


def test_to_summary_falls_back_to_placeholder_device_name():
    device = ManagedDevice(id="d2", device_name=None)
    summary = _to_summary(device)
    assert summary.device_name == "(no device name)"
    assert summary.compliance_state is None
