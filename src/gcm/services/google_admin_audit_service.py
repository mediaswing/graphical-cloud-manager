"""Google Workspace admin audit log reads, via the Admin SDK Reports API's
admin activity feed -- who changed what in the Admin console (user/group/
device/OU changes, role assignments, etc.). This is tenant-side data from
Google itself, distinct from services/audit_log.py's local record of what
*this app* has done; the two aren't redundant even though both are called
"audit log", the same way Entra's own audit logs and this app's local audit
log page are two different things on the Microsoft side.

Event parameters vary widely by event type (CREATE_USER carries different
fields than CHANGE_PASSWORD), so rather than modeling every event type,
parameters are flattened into a single display string -- same pragmatic
choice as not trying to strongly type Graph's audit log detail payloads.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from googleapiclient.discovery import Resource

from gcm.models.google_admin_audit import GoogleAdminAuditSummary

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _flatten_parameters(parameters: list[dict]) -> str:
    parts = []
    for param in parameters or []:
        name = param.get("name")
        if not name:
            continue
        value = param.get("value")
        if value is None:
            value = param.get("multiValue")
        if value is None:
            value = param.get("boolValue")
        if value is None:
            value = param.get("intValue")
        parts.append(f"{name}={value}")
    return ", ".join(parts)


class GoogleAdminAuditService:
    def __init__(self, reports_client: Resource) -> None:
        self._reports = reports_client

    async def list_recent_events(
        self, search: str | None = None, max_results: int = 100
    ) -> list[GoogleAdminAuditSummary]:
        loop = asyncio.get_event_loop()
        request = self._reports.activities().list(
            userKey=search or "all", applicationName="admin", maxResults=max_results,
        )
        response = await loop.run_in_executor(None, request.execute)
        summaries: list[GoogleAdminAuditSummary] = []
        for activity in response.get("items", []):
            actor_email = activity.get("actor", {}).get("email") or "unknown"
            time = _parse_time(activity.get("id", {}).get("time"))
            for event in activity.get("events", []):
                summaries.append(
                    GoogleAdminAuditSummary(
                        time=time,
                        actor_email=actor_email,
                        event_name=event.get("name", "unknown"),
                        details=_flatten_parameters(event.get("parameters", [])),
                    )
                )
        summaries.sort(key=lambda s: s.time or _EPOCH, reverse=True)
        return summaries
