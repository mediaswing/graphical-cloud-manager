"""Entra group and membership operations. Plain Python, no Qt imports, so it
can be unit-tested (with a fake Graph client) without a display."""

from __future__ import annotations

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph import GraphServiceClient
from msgraph.generated.groups.groups_request_builder import GroupsRequestBuilder
from msgraph.generated.groups.item.group_item_request_builder import GroupItemRequestBuilder
from msgraph.generated.groups.item.members.members_request_builder import (
    MembersRequestBuilder,
)
from msgraph.generated.models.group import Group
from msgraph.generated.models.reference_create import ReferenceCreate
from msgraph.generated.users.item.user_item_request_builder import (
    UserItemRequestBuilder,
)

from gcm.graph.pagination import collect_all
from gcm.graph.search import escape_search_term
from gcm.models.group import DynamicMembershipInfo, GroupMember, GroupSummary
from gcm.services import audit_log
from gcm.services.graph_errors import friendly_error_message

_SELECT = ["id", "displayName", "mail", "groupTypes", "securityEnabled", "mailEnabled"]
_MEMBER_SELECT = ["id", "displayName"]
_DYNAMIC_SELECT = ["membershipRule", "membershipRuleProcessingState", "groupTypes"]
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
            query_params.search = f'"displayName:{escape_search_term(search)}"'
            query_params.count = True
            request_config.headers.add("ConsistencyLevel", "eventual")
        first_page = await self._graph.groups.get(request_configuration=request_config)
        groups = await collect_all(first_page, self._graph.request_adapter)
        return [_to_summary(g) for g in groups]

    async def get_group(self, group_id: str) -> GroupSummary:
        query_params = GroupItemRequestBuilder.GroupItemRequestBuilderGetQueryParameters(
            select=_SELECT
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        group = await self._graph.groups.by_group_id(group_id).get(
            request_configuration=request_config
        )
        return _to_summary(group)

    async def list_members(self, group_id: str) -> list[GroupMember]:
        query_params = MembersRequestBuilder.MembersRequestBuilderGetQueryParameters(
            select=_MEMBER_SELECT, top=999,
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        first_page = await self._graph.groups.by_group_id(group_id).members.get(
            request_configuration=request_config
        )
        members = await collect_all(first_page, self._graph.request_adapter)
        return [
            GroupMember(id=m.id, display_name=getattr(m, "display_name", None) or m.id)
            for m in members
        ]

    async def add_member(
        self, group_id: str, user_upn_or_id: str, *, group_display_name: str | None = None
    ) -> None:
        # The members/$ref reference must point at the object's GUID, but
        # Graph's /users/{key} accepts either a UPN or a GUID as the key --
        # resolve here so the caller can type in whichever one they have.
        query_params = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters(
            select=["id"],
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        target_name = f"{group_display_name or group_id} + {user_upn_or_id}"
        try:
            user = await self._graph.users.by_user_id(user_upn_or_id).get(
                request_configuration=request_config
            )
            body = ReferenceCreate(odata_id=_DIRECTORY_OBJECT_URL.format(id=user.id))
            await self._graph.groups.by_group_id(group_id).members.ref.post(body)
        except Exception as exc:
            audit_log.record(
                "add_member", "GroupMembership", f"{group_id}:{user_upn_or_id}", target_name,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "add_member", "GroupMembership", f"{group_id}:{user_upn_or_id}", target_name,
            result="success",
        )

    async def remove_member(
        self,
        group_id: str,
        user_id: str,
        *,
        group_display_name: str | None = None,
        member_display_name: str | None = None,
    ) -> None:
        target_name = f"{group_display_name or group_id} - {member_display_name or user_id}"
        try:
            await self._graph.groups.by_group_id(group_id).members.by_directory_object_id(
                user_id
            ).ref.delete()
        except Exception as exc:
            audit_log.record(
                "remove_member", "GroupMembership", f"{group_id}:{user_id}", target_name,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "remove_member", "GroupMembership", f"{group_id}:{user_id}", target_name,
            result="success",
        )

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
        try:
            created = await self._graph.groups.post(body)
        except Exception as exc:
            audit_log.record(
                "create_group", "Group", mail_nickname, display_name,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "create_group", "Group", created.id, display_name, result="success",
            after={"is_microsoft_365": is_microsoft_365},
        )
        return _to_summary(created)

    async def get_dynamic_membership_info(self, group_id: str) -> DynamicMembershipInfo:
        query_params = GroupItemRequestBuilder.GroupItemRequestBuilderGetQueryParameters(
            select=_DYNAMIC_SELECT,
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        group = await self._graph.groups.by_group_id(group_id).get(
            request_configuration=request_config
        )
        group_types = group.group_types or []
        return DynamicMembershipInfo(
            group_id=group_id,
            is_dynamic="DynamicMembership" in group_types,
            membership_rule=group.membership_rule,
            processing_state=group.membership_rule_processing_state,
            is_microsoft_365="Unified" in group_types,
            dynamic_kind=DynamicMembershipInfo.infer_kind(group.membership_rule),
        )

    async def set_membership_rule(
        self,
        group_id: str,
        rule: str,
        *,
        existing_group_types: list[str],
        display_name: str | None = None,
    ) -> None:
        """Turns on (or updates) dynamic membership. Merges "DynamicMembership"
        into the group's existing groupTypes rather than overwriting them --
        blindly replacing groupTypes would silently drop e.g. "Unified" on a
        Microsoft 365 group."""
        new_types = list(existing_group_types)
        if "DynamicMembership" not in new_types:
            new_types.append("DynamicMembership")
        body = Group(
            membership_rule=rule,
            membership_rule_processing_state="On",
            group_types=new_types,
        )
        try:
            await self._graph.groups.by_group_id(group_id).patch(body)
        except Exception as exc:
            audit_log.record(
                "set_membership_rule", "Group", group_id, display_name or group_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "set_membership_rule", "Group", group_id, display_name or group_id,
            result="success", after={"membership_rule": rule},
        )

    async def delete_group(self, group_id: str, *, display_name: str | None = None) -> None:
        try:
            await self._graph.groups.by_group_id(group_id).delete()
        except Exception as exc:
            audit_log.record(
                "delete_group", "Group", group_id, display_name or group_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "delete_group", "Group", group_id, display_name or group_id, result="success"
        )


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
