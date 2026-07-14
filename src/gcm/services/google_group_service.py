"""Google Workspace group and membership operations, via the Admin SDK
Directory API. Plain Python, no Qt imports -- same shape as
services/group_service.py. Google Groups have no equivalent to Entra's
dynamic membership rules, so there's no analog here to
GroupService.get_dynamic_membership_info/set_membership_rule.
"""

from __future__ import annotations

import asyncio

from googleapiclient.discovery import Resource

from gcm.models.google_group import GoogleGroupMember, GoogleGroupSummary
from gcm.services import audit_log
from gcm.services.google_errors import friendly_google_error

_PAGE_SIZE = 200


def _build_query(search: str) -> str:
    # Same reasoning as google_user_service._build_query: drop embedded
    # quotes rather than try to escape them, since the query syntax has no
    # escape and none of these fields legitimately contain one.
    term = search.replace('"', "").strip()
    return f'email:{term}* OR name:{term}*'


class GoogleGroupService:
    def __init__(self, directory_client: Resource) -> None:
        self._directory = directory_client

    async def _execute(self, request):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, request.execute)

    async def list_groups(self, search: str | None = None) -> list[GoogleGroupSummary]:
        query = _build_query(search) if search else None
        groups: list[dict] = []
        page_token = None
        while True:
            request = self._directory.groups().list(
                customer="my_customer", maxResults=_PAGE_SIZE, query=query, pageToken=page_token,
            )
            response = await self._execute(request)
            groups.extend(response.get("groups", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return [_to_summary(g) for g in groups]

    async def get_group(self, group_id: str) -> GoogleGroupSummary:
        request = self._directory.groups().get(groupKey=group_id)
        group = await self._execute(request)
        return _to_summary(group)

    async def list_members(self, group_id: str) -> list[GoogleGroupMember]:
        members: list[dict] = []
        page_token = None
        while True:
            request = self._directory.members().list(
                groupKey=group_id, maxResults=_PAGE_SIZE, pageToken=page_token,
            )
            response = await self._execute(request)
            members.extend(response.get("members", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return [
            GoogleGroupMember(
                id=m.get("id") or m.get("email", ""),
                email=m.get("email", ""),
                role=m.get("role", "MEMBER"),
            )
            for m in members
        ]

    async def add_member(
        self,
        group_id: str,
        member_email: str,
        *,
        role: str = "MEMBER",
        group_display_name: str | None = None,
    ) -> None:
        # Unlike Graph's members/$ref (which needs the target's GUID),
        # Directory API's members.insert accepts an email directly -- no
        # separate lookup-then-reference step needed.
        target_name = f"{group_display_name or group_id} + {member_email}"
        try:
            await self._execute(
                self._directory.members().insert(
                    groupKey=group_id, body={"email": member_email, "role": role}
                )
            )
        except Exception as exc:
            audit_log.record(
                "add_member", "GoogleGroupMembership", f"{group_id}:{member_email}", target_name,
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            "add_member", "GoogleGroupMembership", f"{group_id}:{member_email}", target_name,
            result="success", after={"role": role},
        )

    async def remove_member(
        self,
        group_id: str,
        member_id: str,
        *,
        group_display_name: str | None = None,
        member_display_name: str | None = None,
    ) -> None:
        target_name = f"{group_display_name or group_id} - {member_display_name or member_id}"
        try:
            await self._execute(
                self._directory.members().delete(groupKey=group_id, memberKey=member_id)
            )
        except Exception as exc:
            audit_log.record(
                "remove_member", "GoogleGroupMembership", f"{group_id}:{member_id}", target_name,
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            "remove_member", "GoogleGroupMembership", f"{group_id}:{member_id}", target_name,
            result="success",
        )

    async def create_group(
        self, *, name: str, email: str, description: str | None = None
    ) -> GoogleGroupSummary:
        body = {"name": name, "email": email, "description": description or ""}
        try:
            created = await self._execute(self._directory.groups().insert(body=body))
        except Exception as exc:
            audit_log.record(
                "create_group", "GoogleGroup", email, name,
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            "create_group", "GoogleGroup", created["id"], name, result="success",
            after={"email": email},
        )
        return _to_summary(created)

    async def delete_group(self, group_id: str, *, display_name: str | None = None) -> None:
        try:
            await self._execute(self._directory.groups().delete(groupKey=group_id))
        except Exception as exc:
            audit_log.record(
                "delete_group", "GoogleGroup", group_id, display_name or group_id,
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            "delete_group", "GoogleGroup", group_id, display_name or group_id, result="success"
        )


def _to_summary(group: dict) -> GoogleGroupSummary:
    return GoogleGroupSummary(
        id=group["id"],
        email=group.get("email", ""),
        name=group.get("name") or "(no name)",
        description=group.get("description", ""),
    )
