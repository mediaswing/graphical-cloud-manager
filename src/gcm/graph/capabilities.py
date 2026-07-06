"""Detect which optional Microsoft 365 products a signed-in tenant actually
has, so the UI only shows Intune/Exchange sections (and only requests their
Graph scopes) when there is something to manage."""

from __future__ import annotations

from dataclasses import dataclass

from msgraph import GraphServiceClient

_INTUNE_SERVICE_PLAN_MARKERS = ("INTUNE",)
_EXCHANGE_SERVICE_PLAN_MARKERS = ("EXCHANGE", "EXCHANGEONLINE")


@dataclass
class TenantCapabilities:
    has_intune: bool
    has_exchange: bool


async def detect_capabilities(graph_client: GraphServiceClient) -> TenantCapabilities:
    skus = await graph_client.subscribed_skus.get()
    has_intune = False
    has_exchange = False

    for sku in skus.value or []:
        for plan in sku.service_plans or []:
            if plan.provisioning_status != "Success":
                continue
            name = (plan.service_plan_name or "").upper()
            if any(marker in name for marker in _INTUNE_SERVICE_PLAN_MARKERS):
                has_intune = True
            if any(marker in name for marker in _EXCHANGE_SERVICE_PLAN_MARKERS):
                has_exchange = True

    return TenantCapabilities(has_intune=has_intune, has_exchange=has_exchange)
