"""Google Workspace sign-in log reads, via the Admin SDK Reports API's login
activity feed. Read-only -- same shape as services/sign_in_log_service.py,
but Google's Reports API has no Azure-AD-Premium-style licensing gate the
way Entra sign-in logs do, so there's no capability check needed before
using this; it's always available once the required scope is granted.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from googleapiclient.discovery import Resource

from gcm.models.google_sign_in import GoogleSignInSummary

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _param_value(parameters: list[dict], name: str) -> str | None:
    for param in parameters or []:
        if param.get("name") == name:
            return param.get("value") or param.get("stringValue")
    return None


class GoogleSignInLogService:
    def __init__(self, reports_client: Resource) -> None:
        self._reports = reports_client

    async def list_recent_sign_ins(
        self, search: str | None = None, max_results: int = 100
    ) -> list[GoogleSignInSummary]:
        # Reports API's userKey takes a specific user's email (or "all") in
        # place of the query-string search Graph's sign-in logs use -- the
        # same "look up this person's recent sign-ins" case, just a
        # different filtering mechanism.
        loop = asyncio.get_event_loop()
        request = self._reports.activities().list(
            userKey=search or "all", applicationName="login", maxResults=max_results,
        )
        response = await loop.run_in_executor(None, request.execute)
        summaries: list[GoogleSignInSummary] = []
        for activity in response.get("items", []):
            actor_email = activity.get("actor", {}).get("email") or "unknown"
            ip_address = activity.get("ipAddress")
            time = _parse_time(activity.get("id", {}).get("time"))
            for event in activity.get("events", []):
                name = event.get("name", "unknown")
                succeeded = "failure" not in name
                summaries.append(
                    GoogleSignInSummary(
                        time=time,
                        user_email=actor_email,
                        ip_address=ip_address,
                        succeeded=succeeded,
                        event_name=name,
                        failure_type=(
                            None if succeeded
                            else _param_value(event.get("parameters", []), "failure_type")
                        ),
                    )
                )
        summaries.sort(key=lambda s: s.time or _EPOCH, reverse=True)
        return summaries
