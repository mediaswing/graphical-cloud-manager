"""Tenant licensing operations: SKU consumption and per-user license
assignment. Plain Python, no Qt imports, so it can be unit-tested (with a
fake Graph client) without a display."""

from __future__ import annotations

from uuid import UUID

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph import GraphServiceClient
from msgraph.generated.models.assigned_license import AssignedLicense
from msgraph.generated.models.subscribed_sku import SubscribedSku
from msgraph.generated.users.item.assign_license.assign_license_post_request_body import (
    AssignLicensePostRequestBody,
)
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder

from gcm.models.license import SubscribedSkuSummary


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

    async def set_user_licenses(
        self, user_id: str, *, add_sku_ids: list[str], remove_sku_ids: list[str]
    ) -> None:
        body = AssignLicensePostRequestBody(
            add_licenses=[AssignedLicense(sku_id=UUID(sku_id)) for sku_id in add_sku_ids],
            remove_licenses=[UUID(sku_id) for sku_id in remove_sku_ids],
        )
        await self._graph.users.by_user_id(user_id).assign_license.post(body)


def _to_summary(sku: SubscribedSku) -> SubscribedSkuSummary:
    return SubscribedSkuSummary(
        sku_id=str(sku.sku_id),
        sku_part_number=sku.sku_part_number or "(unknown)",
        enabled_units=(sku.prepaid_units.enabled if sku.prepaid_units else 0) or 0,
        consumed_units=sku.consumed_units or 0,
    )
