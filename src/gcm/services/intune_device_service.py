"""Read-only Intune managed-device inventory.

Deliberately read-only in this phase: there are no patch/action methods
here at all, so there's nothing to accidentally wire a remote action
(wipe/retire/sync/restart/lock) to. Those are a distinct, higher-risk
feature deferred to a later phase (docs/DESIGN.md section 10) -- adding
them later means adding new methods here, not modifying these ones.

Filtering is done client-side (in the UI layer) rather than via Graph
`$filter`/`$search`, since managedDevices' support for those isn't
consistent enough across tenants/API versions to rely on -- fetching the
full (paginated) list once and filtering in memory is both simpler and
safer than guessing at server-side query support.
"""

from __future__ import annotations

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph import GraphServiceClient
from msgraph.generated.device_management.managed_devices.managed_devices_request_builder import (
    ManagedDevicesRequestBuilder,
)
from msgraph.generated.models.managed_device import ManagedDevice

from gcm.graph.pagination import collect_all
from gcm.models.intune_device import IntuneDeviceSummary

_SELECT = [
    "id",
    "deviceName",
    "operatingSystem",
    "osVersion",
    "complianceState",
    "managementState",
    "managementAgent",
    "managedDeviceOwnerType",
    "userDisplayName",
    "userPrincipalName",
    "lastSyncDateTime",
    "serialNumber",
    "azureADDeviceId",
]


class IntuneDeviceService:
    def __init__(self, graph_client: GraphServiceClient) -> None:
        self._graph = graph_client

    async def list_managed_devices(self) -> list[IntuneDeviceSummary]:
        query_params = ManagedDevicesRequestBuilder.ManagedDevicesRequestBuilderGetQueryParameters(
            select=_SELECT, top=999,
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        first_page = await self._graph.device_management.managed_devices.get(
            request_configuration=request_config
        )
        devices = await collect_all(first_page, self._graph.request_adapter)
        return [_to_summary(d) for d in devices]


def _enum_value(value: object) -> str | None:
    # Kiota generates these as (str, Enum) mixins -- they're technically
    # strings, but str(x) gives "ComplianceState.Compliant" rather than the
    # plain "compliant" that .value gives, so always go through .value.
    return value.value if value is not None else None


def _to_summary(device: ManagedDevice) -> IntuneDeviceSummary:
    return IntuneDeviceSummary(
        id=device.id,
        device_name=device.device_name or "(no device name)",
        operating_system=device.operating_system,
        os_version=device.os_version,
        compliance_state=_enum_value(device.compliance_state),
        management_state=_enum_value(device.management_state),
        management_agent=_enum_value(device.management_agent),
        ownership=_enum_value(device.managed_device_owner_type),
        user_display_name=device.user_display_name,
        user_principal_name=device.user_principal_name,
        last_sync=device.last_sync_date_time,
        serial_number=device.serial_number,
        azure_ad_device_id=device.azure_a_d_device_id,
    )
