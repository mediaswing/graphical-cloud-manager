"""Unit tests for tenant capability detection, using a fake Graph client
stub (no network) that returns pre-built subscribedSkus responses."""

from __future__ import annotations

import pytest
from msgraph.generated.models.service_plan_info import ServicePlanInfo
from msgraph.generated.models.subscribed_sku import SubscribedSku
from msgraph.generated.models.subscribed_sku_collection_response import (
    SubscribedSkuCollectionResponse,
)

from gcm.graph.capabilities import detect_capabilities


class _FakeSubscribedSkusBuilder:
    def __init__(self, skus: list[SubscribedSku]) -> None:
        self._response = SubscribedSkuCollectionResponse(value=skus)

    async def get(self):
        return self._response


class _FakeGraphClient:
    def __init__(self, service_plan_names: list[str], status: str = "Success") -> None:
        plans = [
            ServicePlanInfo(service_plan_name=name, provisioning_status=status)
            for name in service_plan_names
        ]
        self.subscribed_skus = _FakeSubscribedSkusBuilder(
            [SubscribedSku(service_plans=plans)]
        )


@pytest.mark.asyncio
async def test_detects_intune_and_exchange():
    client = _FakeGraphClient(["INTUNE_A_VNEXT", "EXCHANGEONLINE_MULTIGEO"])
    capabilities = await detect_capabilities(client)
    assert capabilities.has_intune is True
    assert capabilities.has_exchange is True
    assert capabilities.has_audit_logs is False


@pytest.mark.asyncio
async def test_detects_audit_logs_for_premium_p1():
    client = _FakeGraphClient(["AAD_PREMIUM"])
    capabilities = await detect_capabilities(client)
    assert capabilities.has_audit_logs is True


@pytest.mark.asyncio
async def test_detects_audit_logs_for_premium_p2():
    client = _FakeGraphClient(["AAD_PREMIUM_P2"])
    capabilities = await detect_capabilities(client)
    assert capabilities.has_audit_logs is True


@pytest.mark.asyncio
async def test_ignores_non_provisioned_plans():
    client = _FakeGraphClient(["INTUNE_A_VNEXT"], status="Disabled")
    capabilities = await detect_capabilities(client)
    assert capabilities.has_intune is False
