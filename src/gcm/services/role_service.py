"""Entra directory role (RBAC) operations.

v1 scope is Entra directory roles only -- Intune role-based access (scope
tags) and Exchange management role groups use different permission models
entirely and are deferred to a later phase (docs/DESIGN.md section 6/10).
"""

from __future__ import annotations

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph import GraphServiceClient
from msgraph.generated.models.unified_role_assignment import UnifiedRoleAssignment
from msgraph.generated.role_management.directory.role_assignments.role_assignments_request_builder import (
    RoleAssignmentsRequestBuilder,
)
from msgraph.generated.role_management.directory.role_definitions.role_definitions_request_builder import (
    RoleDefinitionsRequestBuilder,
)
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder

from gcm.models.role import RoleAssignmentSummary, RoleDefinitionSummary

_DEFINITION_SELECT = ["id", "displayName", "description", "isBuiltIn"]


class RoleService:
    def __init__(self, graph_client: GraphServiceClient) -> None:
        self._graph = graph_client

    async def list_role_definitions(self) -> list[RoleDefinitionSummary]:
        query_params = (
            RoleDefinitionsRequestBuilder.RoleDefinitionsRequestBuilderGetQueryParameters(
                select=_DEFINITION_SELECT, top=999,
            )
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        result = await self._graph.role_management.directory.role_definitions.get(
            request_configuration=request_config
        )
        return [_to_definition_summary(d) for d in (result.value or [])]

    async def list_role_assignments(self, role_definition_id: str) -> list[RoleAssignmentSummary]:
        query_params = (
            RoleAssignmentsRequestBuilder.RoleAssignmentsRequestBuilderGetQueryParameters(
                filter=f"roleDefinitionId eq '{role_definition_id}'",
                expand=["principal"],
                top=999,
            )
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        result = await self._graph.role_management.directory.role_assignments.get(
            request_configuration=request_config
        )
        return [_to_assignment_summary(a) for a in (result.value or [])]

    async def assign_role(self, role_definition_id: str, principal_upn_or_id: str) -> None:
        # v1 supports user principals only; group/service-principal role
        # assignment can follow once this is exercised in practice.
        query_params = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters(
            select=["id"],
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        user = await self._graph.users.by_user_id(principal_upn_or_id).get(
            request_configuration=request_config
        )
        body = UnifiedRoleAssignment(
            role_definition_id=role_definition_id,
            principal_id=user.id,
            directory_scope_id="/",
        )
        await self._graph.role_management.directory.role_assignments.post(body)

    async def remove_role_assignment(self, assignment_id: str) -> None:
        await self._graph.role_management.directory.role_assignments.by_unified_role_assignment_id(
            assignment_id
        ).delete()


def _to_definition_summary(definition) -> RoleDefinitionSummary:
    return RoleDefinitionSummary(
        id=definition.id,
        display_name=definition.display_name or "(no display name)",
        description=definition.description,
        is_built_in=bool(definition.is_built_in),
    )


def _to_assignment_summary(assignment) -> RoleAssignmentSummary:
    principal_name = getattr(assignment.principal, "display_name", None)
    return RoleAssignmentSummary(
        id=assignment.id,
        principal_id=assignment.principal_id or "",
        principal_display_name=principal_name or assignment.principal_id or "(unknown)",
    )
