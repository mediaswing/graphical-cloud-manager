"""Unit tests for dynamic group membership rule handling: kind inference,
and GroupService's get/set methods against a fake Graph client (no
network).
"""

from __future__ import annotations

import pytest
from msgraph.generated.models.group import Group

from gcm.models.group import DynamicMembershipInfo
from gcm.services import audit_log
from gcm.services.group_service import GroupService


def test_infer_kind_user():
    assert DynamicMembershipInfo.infer_kind('(user.department -eq "Sales")') == "user"


def test_infer_kind_device():
    assert DynamicMembershipInfo.infer_kind('(device.deviceOSType -eq "Windows")') == "device"


def test_infer_kind_unknown_when_empty():
    assert DynamicMembershipInfo.infer_kind(None) == "unknown"
    assert DynamicMembershipInfo.infer_kind("") == "unknown"


def test_infer_kind_unknown_when_mixed_or_neither():
    assert DynamicMembershipInfo.infer_kind("something else entirely") == "unknown"


class _FakeGroupItemBuilder:
    def __init__(self, group=None) -> None:
        self._group = group
        self.patched_body = None

    async def get(self, request_configuration=None):
        return self._group

    async def patch(self, body):
        self.patched_body = body


class _FakeGroupsBuilder:
    def __init__(self, item_builder) -> None:
        self._item_builder = item_builder

    def by_group_id(self, group_id):
        return self._item_builder


class _FakeGraphClient:
    def __init__(self, item_builder) -> None:
        self.groups = _FakeGroupsBuilder(item_builder)


@pytest.mark.asyncio
async def test_get_dynamic_membership_info_reads_rule_and_state():
    group = Group(
        membership_rule='(user.department -eq "Sales")',
        membership_rule_processing_state="On",
        group_types=["DynamicMembership"],
    )
    service = GroupService(_FakeGraphClient(_FakeGroupItemBuilder(group)))

    info = await service.get_dynamic_membership_info("g1")

    assert info.is_dynamic is True
    assert info.dynamic_kind == "user"
    assert info.is_microsoft_365 is False
    assert info.processing_state == "On"


@pytest.mark.asyncio
async def test_get_dynamic_membership_info_detects_microsoft_365():
    group = Group(membership_rule=None, membership_rule_processing_state=None, group_types=["Unified"])
    service = GroupService(_FakeGraphClient(_FakeGroupItemBuilder(group)))

    info = await service.get_dynamic_membership_info("g1")

    assert info.is_dynamic is False
    assert info.is_microsoft_365 is True


@pytest.mark.asyncio
async def test_set_membership_rule_preserves_existing_group_types(tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    audit_log.set_actor("admin@contoso.com")
    item_builder = _FakeGroupItemBuilder()
    service = GroupService(_FakeGraphClient(item_builder))

    await service.set_membership_rule(
        "g1", '(user.department -eq "Sales")',
        existing_group_types=["Unified"], display_name="Sales Team",
    )

    assert "Unified" in item_builder.patched_body.group_types
    assert "DynamicMembership" in item_builder.patched_body.group_types
    assert item_builder.patched_body.membership_rule_processing_state == "On"
    entries = audit_log.read_all()
    assert entries[-1].action == "set_membership_rule"
    assert entries[-1].result == "success"


@pytest.mark.asyncio
async def test_set_membership_rule_does_not_duplicate_dynamic_membership_type(tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    audit_log.set_actor("admin@contoso.com")
    item_builder = _FakeGroupItemBuilder()
    service = GroupService(_FakeGraphClient(item_builder))

    await service.set_membership_rule(
        "g1", '(user.department -eq "Sales")',
        existing_group_types=["DynamicMembership"], display_name="Sales Team",
    )

    assert item_builder.patched_body.group_types.count("DynamicMembership") == 1
