"""Entra directory role (RBAC) operations.

Deliberately built on the *classic* `/directoryRoles` + `/directoryRoleTemplates`
API rather than the newer unified RBAC API (`/roleManagement/directory/*`,
used for PIM). The unified API requires Azure AD Premium to return any data
at all -- a tenant without it gets a silent, error-free empty list, which is
exactly what plain role assignment (a free-tier feature) shouldn't require.
The trade-off: `directoryRoleTemplates` only covers built-in roles, not
custom ones -- but custom roles themselves need Premium to create, so a
free-tier tenant has none to miss.

A role only has a `directoryRole` object (and thus a member list) once it's
been "activated" at least once; `_get_or_activate_role` does that
transparently the first time someone assigns it, mirroring how Entra's own
admin center behaves.

v1 scope is Entra directory roles only -- Intune role-based access (scope
tags) and Exchange management role groups use different permission models
entirely and are deferred to a later phase (docs/DESIGN.md section 6/10).
"""

from __future__ import annotations

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph import GraphServiceClient
from msgraph.generated.directory_roles.directory_roles_request_builder import (
    DirectoryRolesRequestBuilder,
)
from msgraph.generated.models.directory_role import DirectoryRole
from msgraph.generated.models.reference_create import ReferenceCreate
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder

from gcm.graph.pagination import collect_all
from gcm.models.role import RoleAssignmentSummary, RoleDefinitionSummary
from gcm.services import audit_log
from gcm.services.graph_errors import friendly_error_message

_DIRECTORY_OBJECT_URL = "https://graph.microsoft.com/v1.0/directoryObjects/{id}"


class RoleService:
    def __init__(self, graph_client: GraphServiceClient) -> None:
        self._graph = graph_client

    async def list_role_definitions(self) -> list[RoleDefinitionSummary]:
        first_page = await self._graph.directory_role_templates.get()
        templates = await collect_all(first_page, self._graph.request_adapter)
        return [_to_definition_summary(template) for template in templates]

    async def list_role_assignments(self, role_template_id: str) -> list[RoleAssignmentSummary]:
        directory_role_id = await self._find_activated_role_id(role_template_id)
        if directory_role_id is None:
            return []  # never activated -- so nobody has been assigned it yet
        first_page = await self._graph.directory_roles.by_directory_role_id(
            directory_role_id
        ).members.get()
        members = await collect_all(first_page, self._graph.request_adapter)
        return [_to_assignment_summary(member) for member in members]

    async def assign_role(
        self,
        role_template_id: str,
        principal_upn_or_id: str,
        *,
        role_display_name: str | None = None,
    ) -> None:
        target_name = f"{role_display_name or role_template_id} + {principal_upn_or_id}"
        try:
            directory_role_id = await self._get_or_activate_role(role_template_id)
            query_params = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters(
                select=["id"],
            )
            request_config = RequestConfiguration(query_parameters=query_params)
            user = await self._graph.users.by_user_id(principal_upn_or_id).get(
                request_configuration=request_config
            )
            body = ReferenceCreate(odata_id=_DIRECTORY_OBJECT_URL.format(id=user.id))
            await self._graph.directory_roles.by_directory_role_id(
                directory_role_id
            ).members.ref.post(body)
        except Exception as exc:
            audit_log.record(
                "assign_role", "RoleAssignment", f"{role_template_id}:{principal_upn_or_id}",
                target_name, result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "assign_role", "RoleAssignment", f"{role_template_id}:{principal_upn_or_id}",
            target_name, result="success",
        )

    async def remove_role_assignment(
        self,
        role_template_id: str,
        principal_id: str,
        *,
        role_display_name: str | None = None,
        principal_display_name: str | None = None,
    ) -> None:
        target_name = (
            f"{role_display_name or role_template_id} - {principal_display_name or principal_id}"
        )
        try:
            directory_role_id = await self._find_activated_role_id(role_template_id)
            if directory_role_id is not None:
                await self._graph.directory_roles.by_directory_role_id(
                    directory_role_id
                ).members.by_directory_object_id(principal_id).ref.delete()
        except Exception as exc:
            audit_log.record(
                "remove_role_assignment", "RoleAssignment",
                f"{role_template_id}:{principal_id}", target_name,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "remove_role_assignment", "RoleAssignment", f"{role_template_id}:{principal_id}",
            target_name, result="success",
        )

    async def _find_activated_role_id(self, role_template_id: str) -> str | None:
        query_params = DirectoryRolesRequestBuilder.DirectoryRolesRequestBuilderGetQueryParameters(
            filter=f"roleTemplateId eq '{role_template_id}'",
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        result = await self._graph.directory_roles.get(request_configuration=request_config)
        roles = result.value or []
        return roles[0].id if roles else None

    async def _get_or_activate_role(self, role_template_id: str) -> str:
        existing_id = await self._find_activated_role_id(role_template_id)
        if existing_id is not None:
            return existing_id
        activated = await self._graph.directory_roles.post(
            DirectoryRole(role_template_id=role_template_id)
        )
        return activated.id


def _to_definition_summary(template) -> RoleDefinitionSummary:
    return RoleDefinitionSummary(
        id=template.id,
        display_name=template.display_name or "(no display name)",
        description=template.description,
        is_built_in=True,
    )


def _to_assignment_summary(member) -> RoleAssignmentSummary:
    display_name = getattr(member, "display_name", None)
    return RoleAssignmentSummary(
        id=member.id,
        principal_id=member.id,
        principal_display_name=display_name or member.id,
    )
