"""Unit tests for IntuneDeviceService: the Graph-model-to-dataclass
conversion (no network, real msgraph models), and sync_device_by_azure_ad_
device_id's ID-resolution + call flow (no network, hand-rolled fakes just
shaped enough to stand in for the Kiota request builders it calls).

Covers a real bug caught while writing this: Kiota generates Graph's
compliance/management enums as (str, Enum) mixins, so `str(x)` gives
"ComplianceState.Compliant" rather than the plain "compliant" -- _to_summary
must go through `.value`.
"""

from __future__ import annotations

import datetime

import pytest
from msgraph.generated.models.compliance_state import ComplianceState
from msgraph.generated.models.managed_device import ManagedDevice
from msgraph.generated.models.managed_device_owner_type import ManagedDeviceOwnerType

from gcm.services.intune_device_service import IntuneDeviceService, _to_summary


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


class _FakeManagedDevicesResponse:
    def __init__(self, value):
        self.value = value


class _FakeManagedDevice:
    def __init__(self, id):
        self.id = id


class _FakeManagedDeviceItemBuilder:
    def __init__(self, sync_calls):
        self._sync_calls = sync_calls
        self.sync_device = self

    async def post(self, request_configuration=None):
        self._sync_calls.append("synced")


class _FakeManagedDevicesRequestBuilder:
    def __init__(self, matches):
        self._matches = matches
        self.synced_ids: list[str] = []
        self.sync_calls: list[str] = []

    async def get(self, request_configuration=None):
        return _FakeManagedDevicesResponse(self._matches)

    def by_managed_device_id(self, managed_device_id):
        self.synced_ids.append(managed_device_id)
        return _FakeManagedDeviceItemBuilder(self.sync_calls)


class _FakeDeviceManagement:
    def __init__(self, matches):
        self.managed_devices = _FakeManagedDevicesRequestBuilder(matches)


class _FakeGraphClient:
    def __init__(self, matches):
        self.device_management = _FakeDeviceManagement(matches)


@pytest.mark.asyncio
async def test_sync_device_by_azure_ad_device_id_calls_sync_on_match(monkeypatch, tmp_path):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    graph = _FakeGraphClient([_FakeManagedDevice(id="managed-1")])
    service = IntuneDeviceService(graph)

    await service.sync_device_by_azure_ad_device_id(
        "entra-device-guid", display_name="Janes-iPhone"
    )

    assert graph.device_management.managed_devices.synced_ids == ["managed-1"]
    assert graph.device_management.managed_devices.sync_calls == ["synced"]


@pytest.mark.asyncio
async def test_sync_device_by_azure_ad_device_id_raises_when_not_enrolled(monkeypatch, tmp_path):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    graph = _FakeGraphClient([])
    service = IntuneDeviceService(graph)

    with pytest.raises(Exception, match="isn't enrolled in Intune"):
        await service.sync_device_by_azure_ad_device_id("entra-device-guid")

    assert graph.device_management.managed_devices.sync_calls == []
