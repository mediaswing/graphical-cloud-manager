"""Entra device operations (registered/joined devices -- not Intune-managed
device data, which is a separate module deferred per docs/DESIGN.md section
10). Plain Python, no Qt imports, so it can be unit-tested without a
display."""

from __future__ import annotations

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph import GraphServiceClient
from msgraph.generated.devices.devices_request_builder import DevicesRequestBuilder
from msgraph.generated.models.device import Device

from gcm.graph.pagination import collect_all
from gcm.models.device import DeviceSummary
from gcm.services import audit_log
from gcm.services.graph_errors import friendly_error_message

_SELECT = [
    "id",
    "displayName",
    "operatingSystem",
    "operatingSystemVersion",
    "trustType",
    "isCompliant",
    "isManaged",
    "accountEnabled",
    "approximateLastSignInDateTime",
]


class DeviceService:
    def __init__(self, graph_client: GraphServiceClient) -> None:
        self._graph = graph_client

    async def list_devices(self, search: str | None = None) -> list[DeviceSummary]:
        query_params = DevicesRequestBuilder.DevicesRequestBuilderGetQueryParameters(
            select=_SELECT, top=999,
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        if search:
            query_params.search = f'"displayName:{search}"'
            query_params.count = True
            request_config.headers.add("ConsistencyLevel", "eventual")
        first_page = await self._graph.devices.get(request_configuration=request_config)
        devices = await collect_all(first_page, self._graph.request_adapter)
        return [_to_summary(d) for d in devices]

    async def set_device_enabled(
        self, device_id: str, enabled: bool, *, display_name: str | None = None
    ) -> None:
        try:
            await self._graph.devices.by_device_id(device_id).patch(
                Device(account_enabled=enabled)
            )
        except Exception as exc:
            audit_log.record(
                "set_device_enabled", "Device", device_id, display_name or device_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "set_device_enabled", "Device", device_id, display_name or device_id,
            result="success", after={"account_enabled": enabled},
        )

    async def delete_device(self, device_id: str, *, display_name: str | None = None) -> None:
        try:
            await self._graph.devices.by_device_id(device_id).delete()
        except Exception as exc:
            audit_log.record(
                "delete_device", "Device", device_id, display_name or device_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "delete_device", "Device", device_id, display_name or device_id, result="success"
        )


def _to_summary(device: Device) -> DeviceSummary:
    return DeviceSummary(
        id=device.id,
        display_name=device.display_name or "(no display name)",
        operating_system=device.operating_system,
        operating_system_version=device.operating_system_version,
        trust_type=device.trust_type,
        is_compliant=device.is_compliant,
        is_managed=device.is_managed,
        account_enabled=bool(device.account_enabled),
        approximate_last_sign_in=device.approximate_last_sign_in_date_time,
    )
