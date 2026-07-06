"""Unit tests for LicenseService's Graph-model-to-dataclass conversion and
group-licensing orchestration. Doesn't touch the network -- constructs real
msgraph models directly, or fakes just the couple of Graph client methods
each test needs.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from msgraph.generated.models.license_assignment_state import LicenseAssignmentState
from msgraph.generated.models.license_units_detail import LicenseUnitsDetail
from msgraph.generated.models.service_plan_info import ServicePlanInfo
from msgraph.generated.models.subscribed_sku import SubscribedSku
from msgraph.generated.models.user import User

from gcm.models.license import ServicePlanSummary, SubscribedSkuSummary
from gcm.services import audit_log
from gcm.services.license_service import LicenseService, _to_summary


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
    assert summary.service_plans == []


def test_to_summary_includes_service_plans():
    sku = SubscribedSku(
        sku_id="s1",
        sku_part_number="ENTERPRISEPACK",
        service_plans=[ServicePlanInfo(service_plan_id="p1", service_plan_name="EXCHANGE_S_ENTERPRISE")],
    )
    summary = _to_summary(sku)
    assert summary.service_plans[0].id == "p1"
    assert summary.service_plans[0].name == "EXCHANGE_S_ENTERPRISE"


def test_to_summary_handles_missing_prepaid_units():
    sku = SubscribedSku(sku_id="s1", sku_part_number=None, consumed_units=None, prepaid_units=None)
    summary = _to_summary(sku)
    assert summary.sku_part_number == "(unknown)"
    assert summary.enabled_units == 0
    assert summary.consumed_units == 0


# ---------------------------------------------------------------------------
# get_user_license_assignments -- direct vs group-derived, disabled plans
# ---------------------------------------------------------------------------


class _FakeUserItemBuilder:
    def __init__(self, user):
        self._user = user

    async def get(self, request_configuration=None):
        return self._user


class _FakeUsersBuilder:
    def __init__(self, user):
        self._user = user

    def by_user_id(self, user_id):
        return _FakeUserItemBuilder(self._user)


class _FakeGraphClientForUser:
    def __init__(self, user):
        self.users = _FakeUsersBuilder(user)


@pytest.mark.asyncio
async def test_get_user_license_assignments_distinguishes_direct_and_group_derived():
    sku_id = str(uuid4())
    group_id = str(uuid4())
    plan_id = str(uuid4())
    skus = [
        SubscribedSkuSummary(
            sku_id=sku_id, sku_part_number="ENTERPRISEPACK", enabled_units=10, consumed_units=1,
            service_plans=[ServicePlanSummary(id=plan_id, name="EXCHANGE_S_ENTERPRISE")],
        )
    ]
    user = User(
        license_assignment_states=[
            LicenseAssignmentState(sku_id=sku_id, assigned_by_group=None, state="Active", disabled_plans=[plan_id]),
            LicenseAssignmentState(sku_id=sku_id, assigned_by_group=group_id, state="Active"),
        ]
    )
    service = LicenseService(_FakeGraphClientForUser(user))

    assignments = await service.get_user_license_assignments("u1", skus)

    assert len(assignments) == 2
    direct, via_group = assignments
    assert direct.is_direct is True
    assert direct.disabled_service_plan_names == ["EXCHANGE_S_ENTERPRISE"]
    assert via_group.is_direct is False
    assert via_group.assigned_by_group_id == group_id


# ---------------------------------------------------------------------------
# Group licensing: get_group_license_info / set_group_licenses
# ---------------------------------------------------------------------------


class _FakeGroupItemBuilder:
    def __init__(self, group=None, assign_license=None):
        self._group = group
        self.assign_license = assign_license

    async def get(self, request_configuration=None):
        return self._group


class _FakeAssignLicenseBuilder:
    def __init__(self):
        self.posted_body = None
        self.should_fail = False

    async def post(self, body):
        if self.should_fail:
            raise RuntimeError("simulated failure")
        self.posted_body = body


class _FakeGroupsBuilder:
    def __init__(self, item_builder):
        self._item_builder = item_builder

    def by_group_id(self, group_id):
        return self._item_builder


class _FakeGraphClientForGroup:
    def __init__(self, item_builder):
        self.groups = _FakeGroupsBuilder(item_builder)


@pytest.mark.asyncio
async def test_get_group_license_info_returns_sku_ids_and_processing_state():
    from msgraph.generated.models.assigned_license import AssignedLicense
    from msgraph.generated.models.group import Group
    from msgraph.generated.models.license_processing_state import LicenseProcessingState

    sku_id = str(uuid4())
    group = Group(
        assigned_licenses=[AssignedLicense(sku_id=sku_id)],
        license_processing_state=LicenseProcessingState(state="Processing"),
    )
    item_builder = _FakeGroupItemBuilder(group=group)
    service = LicenseService(_FakeGraphClientForGroup(item_builder))

    sku_ids, processing_state = await service.get_group_license_info("g1")

    assert sku_ids == {sku_id}
    assert processing_state == "Processing"


@pytest.mark.asyncio
async def test_set_group_licenses_success_records_audit_log(tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    audit_log.set_actor("admin@contoso.com")
    assign_builder = _FakeAssignLicenseBuilder()
    item_builder = _FakeGroupItemBuilder(assign_license=assign_builder)
    service = LicenseService(_FakeGraphClientForGroup(item_builder))

    await service.set_group_licenses(
        "g1", add_sku_ids=[str(uuid4())], remove_sku_ids=[], display_name="Sales Team"
    )

    assert assign_builder.posted_body is not None
    entries = audit_log.read_all()
    assert entries[-1].action == "set_group_licenses"
    assert entries[-1].result == "success"
    assert entries[-1].target_display_name == "Sales Team"


@pytest.mark.asyncio
async def test_set_group_licenses_failure_records_audit_log_and_reraises(tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    audit_log.set_actor("admin@contoso.com")
    assign_builder = _FakeAssignLicenseBuilder()
    assign_builder.should_fail = True
    item_builder = _FakeGroupItemBuilder(assign_license=assign_builder)
    service = LicenseService(_FakeGraphClientForGroup(item_builder))

    with pytest.raises(RuntimeError):
        await service.set_group_licenses(
            "g1", add_sku_ids=[str(uuid4())], remove_sku_ids=[], display_name="Sales Team"
        )

    entries = audit_log.read_all()
    assert entries[-1].result == "failure"
    assert entries[-1].error is not None
