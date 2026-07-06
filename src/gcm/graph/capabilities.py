"""Detect which optional Microsoft 365 products a signed-in tenant actually
has, so the UI only shows Intune/Exchange/sign-in-log sections (and only
requests their Graph scopes) when there is something to manage."""

from __future__ import annotations

from dataclasses import dataclass

from msgraph import GraphServiceClient

_INTUNE_SERVICE_PLAN_MARKERS = ("INTUNE",)
_EXCHANGE_SERVICE_PLAN_MARKERS = ("EXCHANGE", "EXCHANGEONLINE")
# "AAD_PREMIUM" matches both P1's own plan name and P2's ("AAD_PREMIUM_P2")
# as a substring -- sign-in logs need at least P1.
_AUDIT_LOG_SERVICE_PLAN_MARKERS = ("AAD_PREMIUM",)


@dataclass
class TenantCapabilities:
    has_intune: bool
    has_exchange: bool
    has_audit_logs: bool


async def detect_capabilities(graph_client: GraphServiceClient) -> TenantCapabilities:
    skus = await graph_client.subscribed_skus.get()
    has_intune = False
    has_exchange = False
    has_audit_logs = False

    for sku in skus.value or []:
        for plan in sku.service_plans or []:
            if plan.provisioning_status != "Success":
                continue
            name = (plan.service_plan_name or "").upper()
            if any(marker in name for marker in _INTUNE_SERVICE_PLAN_MARKERS):
                has_intune = True
            if any(marker in name for marker in _EXCHANGE_SERVICE_PLAN_MARKERS):
                has_exchange = True
            if any(marker in name for marker in _AUDIT_LOG_SERVICE_PLAN_MARKERS):
                has_audit_logs = True

    return TenantCapabilities(
        has_intune=has_intune, has_exchange=has_exchange, has_audit_logs=has_audit_logs
    )
