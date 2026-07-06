"""Entra group and membership operations. Plain Python, no Qt imports, so it
can be unit-tested (with a fake Graph client) without a display."""

from __future__ import annotations

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph import GraphServiceClient
from msgraph.generated.groups.groups_request_builder import GroupsRequestBuilder
from msgraph.generated.groups.item.members.members_request_builder import (
    MembersRequestBuilder,
)
from msgraph.generated.models.group import Group
from msgraph.generated.models.reference_create import ReferenceCreate
from msgraph.generated.users.item.user_item_request_builder import (
    UserItemRequestBuilder,
)

from gcm.models.group import GroupMember, GroupSummary

_SELECT = ["id", "displayName", "mail", "groupTypes", "securityEnabled", "mailEnabled"]
_MEMBER_SELECT = ["id", "displayName"]
_DIRECTORY_OBJECT_URL = "https://graph.microsoft.com/v1.0/directoryObjects/{id}"


class GroupService:
    def __init__(self, graph_client: GraphServiceClient) -> None:
        self._graph = graph_client

    async def list_groups(self, search: str | None = None) -> list[GroupSummary]:
        query_params = GroupsRequestBuilder.GroupsRequestBuilderGetQueryParameters(
            select=_SELECT, top=999,
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        if search:
            query_params.search = f'"displayName:{search}"'
            query_params.count = True
            request_config.headers.add("ConsistencyLevel", "eventual")
        result = await self._graph.groups.get(request_configuration=request_config)
        return [_to_summary(g) for g in (result.value or [])]

    async def list_members(self, group_id: str) -> list[GroupMember]:
        query_params = MembersRequestBuilder.MembersRequestBuilderGetQueryParameters(
            select=_MEMBER_SELECT, top=999,
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        result = await self._graph.groups.by_group_id(group_id).members.get(
            request_configuration=request_config
        )
        return [
            GroupMember(id=m.id, display_name=getattr(m, "display_name", None) or m.id)
            for m in (result.value or [])
        ]

    async def add_member(self, group_id: str, user_upn_or_id: str) -> None:
        # The members/$ref reference must point at the object's GUID, but
        # Graph's /users/{key} accepts either a UPN or a GUID as the key --
        # resolve here so the caller can type in whichever one they have.
        query_params = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters(
            select=["id"],
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        user = await self._graph.users.by_user_id(user_upn_or_id).get(
            request_configuration=request_config
        )
        body = ReferenceCreate(odata_id=_DIRECTORY_OBJECT_URL.format(id=user.id))
        await self._graph.groups.by_group_id(group_id).members.ref.post(body)

    async def remove_member(self, group_id: str, user_id: str) -> None:
        await self._graph.groups.by_group_id(group_id).members.by_directory_object_id(
            user_id
        ).ref.delete()

    async def create_group(
        self,
        *,
        display_name: str,
        mail_nickname: str,
        is_microsoft_365: bool,
        description: str | None = None,
    ) -> GroupSummary:
        body = Group(
            display_name=display_name,
            mail_nickname=mail_nickname,
            description=description,
            mail_enabled=is_microsoft_365,
            security_enabled=not is_microsoft_365,
            group_types=["Unified"] if is_microsoft_365 else [],
        )
        created = await self._graph.groups.post(body)
        return _to_summary(created)

    async def delete_group(self, group_id: str) -> None:
        await self._graph.groups.by_group_id(group_id).delete()


def _to_summary(group: Group) -> GroupSummary:
    return GroupSummary(
        id=group.id,
        display_name=group.display_name or "(no display name)",
        mail=group.mail,
        group_type=_group_type(group),
    )


def _group_type(group: Group) -> str:
    if group.group_types and "Unified" in group.group_types:
        return "Microsoft 365"
    if group.security_enabled and group.mail_enabled:
        return "Mail-enabled security"
    if group.security_enabled:
        return "Security"
    if group.mail_enabled:
        return "Distribution"
    return "Unknown"
