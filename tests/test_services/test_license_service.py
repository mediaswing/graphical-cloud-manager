"""Unit test for LicenseService's Graph-model-to-dataclass conversion.
Doesn't touch the network -- constructs real msgraph models directly."""

from __future__ import annotations

from msgraph.generated.models.license_units_detail import LicenseUnitsDetail
from msgraph.generated.models.subscribed_sku import SubscribedSku

from gcm.services.license_service import _to_summary


def test_to_summary_maps_fields_and_computes_available():
    sku = SubscribedSku(
        sku_id="11111111-1111-1111-1111-111111111111",
        sku_part_number="ENTERPRISEPACK",
        consumed_units=5,
        prepaid_units=LicenseUnitsDetail(enabled=10),
    )
    summary = _to_summary(sku)
    assert summary.sku_part_number == "ENTERPRISEPACK"
    assert summary.enabled_units == 10
    assert summary.consumed_units == 5
    assert summary.available_units == 5


def test_to_summary_handles_missing_prepaid_units():
    sku = SubscribedSku(sku_id="s1", sku_part_number=None, consumed_units=None, prepaid_units=None)
    summary = _to_summary(sku)
    assert summary.sku_part_number == "(unknown)"
    assert summary.enabled_units == 0
    assert summary.consumed_units == 0
