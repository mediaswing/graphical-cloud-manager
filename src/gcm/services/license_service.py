"""Tenant licensing operations: SKU consumption, per-user license
assignment, and group-based license assignment. Plain Python, no Qt
imports, so it can be unit-tested (with a fake Graph client) without a
display.

Group-based licensing note: assigning a license to a group is asynchronous
on Microsoft's side (`Group.licenseProcessingState`) -- members don't get
the license instantly. Callers should surface that state rather than
implying the change took effect immediately.
"""

from __future__ import annotations

from uuid import UUID

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph import GraphServiceClient
from msgraph.generated.groups.item.assign_license.assign_license_post_request_body import (
    AssignLicensePostRequestBody as GroupAssignLicensePostRequestBody,
)
from msgraph.generated.groups.item.group_item_request_builder import GroupItemRequestBuilder
from msgraph.generated.models.assigned_license import AssignedLicense
from msgraph.generated.models.subscribed_sku import SubscribedSku
from msgraph.generated.users.item.assign_license.assign_license_post_request_body import (
    AssignLicensePostRequestBody,
)
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder

from gcm.models.license import ServicePlanSummary, SubscribedSkuSummary, UserLicenseAssignment
from gcm.services import audit_log
from gcm.services.graph_errors import friendly_error_message


class LicenseService:
    def __init__(self, graph_client: GraphServiceClient) -> None:
        self._graph = graph_client

    async def list_subscribed_skus(self) -> list[SubscribedSkuSummary]:
        result = await self._graph.subscribed_skus.get()
        return [_to_summary(sku) for sku in (result.value or [])]

    async def get_user_license_sku_ids(self, user_id: str) -> set[str]:
        query_params = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters(
            select=["assignedLicenses"],
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        user = await self._graph.users.by_user_id(user_id).get(
            request_configuration=request_config
        )
        return {str(lic.sku_id) for lic in (user.assigned_licenses or []) if lic.sku_id}

    async def get_user_license_assignments(
        self, user_id: str, skus: list[SubscribedSkuSummary]
    ) -> list[UserLicenseAssignment]:
        """`skus` should be the tenant's already-fetched SKU list (from
        `list_subscribed_skus`) -- avoids a redundant subscribedSkus call
        just to map SKU/service-plan IDs to names."""
        query_params = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters(
            select=["licenseAssignmentStates"],
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        user = await self._graph.users.by_user_id(user_id).get(
            request_configuration=request_config
        )
        sku_by_id = {s.sku_id: s for s in skus}
        assignments = []
        for state in user.license_assignment_states or []:
            sku_id = str(state.sku_id) if state.sku_id else ""
            sku = sku_by_id.get(sku_id)
            plan_name_by_id = {p.id: p.name for p in sku.service_plans} if sku else {}
            disabled_names = [
                plan_name_by_id.get(str(plan_id), str(plan_id))
                for plan_id in (state.disabled_plans or [])
            ]
            assignments.append(
                UserLicenseAssignment(
                    sku_id=sku_id,
                    sku_part_number=sku.sku_part_number if sku else sku_id,
                    assigned_by_group_id=(
                        str(state.assigned_by_group) if state.assigned_by_group else None
                    ),
                    state=state.state,
                    disabled_service_plan_names=disabled_names,
                )
            )
        return assignments

    async def set_user_licenses(
        self,
        user_id: str,
        *,
        add_sku_ids: list[str],
        remove_sku_ids: list[str],
        display_name: str | None = None,
    ) -> None:
        body = AssignLicensePostRequestBody(
            add_licenses=[AssignedLicense(sku_id=UUID(sku_id)) for sku_id in add_sku_ids],
            remove_licenses=[UUID(sku_id) for sku_id in remove_sku_ids],
        )
        try:
            await self._graph.users.by_user_id(user_id).assign_license.post(body)
        except Exception as exc:
            audit_log.record(
                "set_user_licenses", "User", user_id, display_name or user_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "set_user_licenses", "User", user_id, display_name or user_id, result="success",
            after={"added": add_sku_ids, "removed": remove_sku_ids},
        )

    async def get_group_license_info(self, group_id: str) -> tuple[set[str], str | None]:
        """Returns (assigned SKU ids, licenseProcessingState) in one call.
        The processing state is what tells the caller whether Microsoft has
        actually finished applying a recent change to this group's licenses
        -- members don't get a group's license instantly."""
        query_params = GroupItemRequestBuilder.GroupItemRequestBuilderGetQueryParameters(
            select=["assignedLicenses", "licenseProcessingState"],
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        group = await self._graph.groups.by_group_id(group_id).get(
            request_configuration=request_config
        )
        sku_ids = {str(lic.sku_id) for lic in (group.assigned_licenses or []) if lic.sku_id}
        processing_state = (
            group.license_processing_state.state if group.license_processing_state else None
        )
        return sku_ids, processing_state

    async def set_group_licenses(
        self,
        group_id: str,
        *,
        add_sku_ids: list[str],
        remove_sku_ids: list[str],
        display_name: str | None = None,
    ) -> None:
        body = GroupAssignLicensePostRequestBody(
            add_licenses=[AssignedLicense(sku_id=UUID(sku_id)) for sku_id in add_sku_ids],
            remove_licenses=[UUID(sku_id) for sku_id in remove_sku_ids],
        )
        try:
            await self._graph.groups.by_group_id(group_id).assign_license.post(body)
        except Exception as exc:
            audit_log.record(
                "set_group_licenses", "Group", group_id, display_name or group_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "set_group_licenses", "Group", group_id, display_name or group_id, result="success",
            after={"added": add_sku_ids, "removed": remove_sku_ids},
        )


def _to_summary(sku: SubscribedSku) -> SubscribedSkuSummary:
    return SubscribedSkuSummary(
        sku_id=str(sku.sku_id),
        sku_part_number=sku.sku_part_number or "(unknown)",
        enabled_units=(sku.prepaid_units.enabled if sku.prepaid_units else 0) or 0,
        consumed_units=sku.consumed_units or 0,
        service_plans=[
            ServicePlanSummary(id=str(p.service_plan_id), name=p.service_plan_name or "(unknown)")
            for p in (sku.service_plans or [])
        ],
    )
