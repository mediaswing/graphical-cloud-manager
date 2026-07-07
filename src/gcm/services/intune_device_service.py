"""Intune managed-device inventory, plus the one remote action implemented
so far: Sync.

Sync is the sole intentional exception to "read-only" -- it's the least
destructive of Intune's remote actions (no data loss, fully reversible,
just asks the device to check in now), so it's wired up ahead of
wipe/retire/restart/lock, which remain deferred to a later phase
(docs/DESIGN.md section 10) precisely because they need heavier
confirmation treatment. Adding one of those later means adding a new
method here, not modifying `sync_device_by_azure_ad_device_id`.

Filtering is done client-side (in the UI layer) rather than via Graph
`$filter`/`$search`, since managedDevices' support for those isn't
consistent enough across tenants/API versions to rely on -- fetching the
full (paginated) list once and filtering in memory is both simpler and
safer than guessing at server-side query support. The one exception is
`sync_device_by_azure_ad_device_id`'s own lookup, which targets exactly one
device by its Entra `deviceId` and so has no pagination/consistency concern.
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
from gcm.services import audit_log
from gcm.services.graph_errors import friendly_error_message

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

    async def sync_device_by_azure_ad_device_id(
        self, azure_ad_device_id: str, *, display_name: str | None = None
    ) -> None:
        """Ask Intune to sync the managed device whose azureADDeviceId
        matches an Entra device's own `deviceId` -- the two ID spaces
        (Entra object ID vs. Intune managedDevice ID) are otherwise
        unrelated. Raises with a friendly message (rather than proceeding)
        if the tenant has Intune but this particular device isn't enrolled
        in it, which is a distinct, expected outcome from the tenant having
        no Intune at all."""
        try:
            query_params = (
                ManagedDevicesRequestBuilder.ManagedDevicesRequestBuilderGetQueryParameters(
                    filter=f"azureADDeviceId eq '{azure_ad_device_id}'", select=["id"], top=1,
                )
            )
            request_config = RequestConfiguration(query_parameters=query_params)
            result = await self._graph.device_management.managed_devices.get(
                request_configuration=request_config
            )
            matches = result.value if result else None
            if not matches:
                raise Exception("This device isn't enrolled in Intune, so it can't be synced.")
            managed_device_id = matches[0].id
            await self._graph.device_management.managed_devices.by_managed_device_id(
                managed_device_id
            ).sync_device.post()
        except Exception as exc:
            audit_log.record(
                "sync_intune_device", "Device", azure_ad_device_id,
                display_name or azure_ad_device_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "sync_intune_device", "Device", azure_ad_device_id,
            display_name or azure_ad_device_id, result="success",
        )


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
