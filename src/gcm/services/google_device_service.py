"""Google Workspace mobile device operations, via the Admin SDK Directory
API. Plain Python, no Qt imports -- same shape as services/device_service.py.

Chrome OS devices are a separate Directory API resource (chromeosdevices)
with different fields and actions (org-unit moves, deprovisioning) --
deliberately out of scope for this module; a Chrome OS equivalent would be a
separate service/model/page, same as how Intune device management is split
from Entra device management on the Microsoft side.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from googleapiclient.discovery import Resource

from gcm.models.google_device import GoogleMobileDeviceSummary
from gcm.services import audit_log
from gcm.services.google_errors import friendly_google_error

_PAGE_SIZE = 200


def _build_query(search: str) -> str:
    # Same reasoning as google_user_service._build_query: drop embedded
    # quotes rather than try to escape them.
    term = search.replace('"', "").strip()
    return f'model:{term}* OR name:{term}*'


def _parse_last_sync(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class GoogleDeviceService:
    def __init__(self, directory_client: Resource) -> None:
        self._directory = directory_client

    async def _execute(self, request):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, request.execute)

    async def list_devices(self, search: str | None = None) -> list[GoogleMobileDeviceSummary]:
        query = _build_query(search) if search else None
        devices: list[dict] = []
        page_token = None
        while True:
            request = self._directory.mobiledevices().list(
                customerId="my_customer",
                maxResults=_PAGE_SIZE,
                query=query,
                pageToken=page_token,
            )
            response = await self._execute(request)
            devices.extend(response.get("mobiledevices", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return [_to_summary(d) for d in devices]

    async def _do_action(
        self, resource_id: str, action: str, *, action_label: str, display_name: str | None
    ) -> None:
        request = self._directory.mobiledevices().action(
            customerId="my_customer", resourceId=resource_id, body={"action": action}
        )
        try:
            await self._execute(request)
        except Exception as exc:
            audit_log.record(
                action_label, "GoogleMobileDevice", resource_id, display_name or resource_id,
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            action_label, "GoogleMobileDevice", resource_id, display_name or resource_id,
            result="success",
        )

    async def approve_device(self, resource_id: str, *, display_name: str | None = None) -> None:
        await self._do_action(
            resource_id, "approve", action_label="approve_device", display_name=display_name
        )

    async def block_device(self, resource_id: str, *, display_name: str | None = None) -> None:
        await self._do_action(
            resource_id, "block", action_label="block_device", display_name=display_name
        )

    async def remote_wipe_device(
        self, resource_id: str, *, display_name: str | None = None
    ) -> None:
        await self._do_action(
            resource_id, "admin_remote_wipe", action_label="remote_wipe_device",
            display_name=display_name,
        )

    async def delete_device(self, resource_id: str, *, display_name: str | None = None) -> None:
        # Unenrolls the device from management -- unlike remote_wipe_device,
        # this doesn't touch the device itself, mirroring DeviceService's
        # distinction between disabling/deleting an Entra device object and
        # Intune's separate wipe/retire actions.
        request = self._directory.mobiledevices().delete(
            customerId="my_customer", resourceId=resource_id
        )
        try:
            await self._execute(request)
        except Exception as exc:
            audit_log.record(
                "delete_device", "GoogleMobileDevice", resource_id, display_name or resource_id,
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            "delete_device", "GoogleMobileDevice", resource_id, display_name or resource_id,
            result="success",
        )


def _to_summary(device: dict) -> GoogleMobileDeviceSummary:
    emails = device.get("email") or []
    names = device.get("name") or []
    return GoogleMobileDeviceSummary(
        resource_id=device["resourceId"],
        model=device.get("model") or "Unknown",
        os_type=device.get("os") or device.get("type") or "Unknown",
        status=device.get("status") or "Unknown",
        owner_email=emails[0] if emails else "",
        owner_name=names[0] if names else "",
        serial_number=device.get("serialNumber"),
        last_sync=_parse_last_sync(device.get("lastSync")),
    )
