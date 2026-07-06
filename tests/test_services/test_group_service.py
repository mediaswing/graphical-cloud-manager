"""Unit tests for the pure-Python parts of GroupService: group-type
classification and Graph-model-to-dataclass conversion. These don't touch
the network -- they construct real msgraph model objects directly."""

from __future__ import annotations

import pytest
from msgraph.generated.models.group import Group

from gcm.services.group_service import GroupService, _group_type, _to_summary


def test_group_type_microsoft_365():
    group = Group(group_types=["Unified"], security_enabled=False, mail_enabled=True)
    assert _group_type(group) == "Microsoft 365"


def test_group_type_security():
    group = Group(group_types=[], security_enabled=True, mail_enabled=False)
    assert _group_type(group) == "Security"


def test_group_type_mail_enabled_security():
    group = Group(group_types=[], security_enabled=True, mail_enabled=True)
    assert _group_type(group) == "Mail-enabled security"


def test_group_type_distribution():
    group = Group(group_types=[], security_enabled=False, mail_enabled=True)
    assert _group_type(group) == "Distribution"


def test_to_summary_falls_back_to_placeholder_display_name():
    group = Group(id="g1", display_name=None, group_types=[], security_enabled=True)
    summary = _to_summary(group)
    assert summary.id == "g1"
    assert summary.display_name == "(no display name)"


class _FakeGroupItemBuilder:
    def __init__(self, group) -> None:
        self._group = group

    async def get(self, request_configuration=None):
        return self._group


class _FakeGroupsBuilder:
    def __init__(self, group) -> None:
        self._group = group

    def by_group_id(self, group_id):
        return _FakeGroupItemBuilder(self._group)


class _FakeGraphClient:
    def __init__(self, group) -> None:
        self.groups = _FakeGroupsBuilder(group)


@pytest.mark.asyncio
async def test_get_group_fetches_a_single_group_by_id():
    group = Group(id="g1", display_name="Sales Team", group_types=[], security_enabled=True)
    service = GroupService(_FakeGraphClient(group))

    summary = await service.get_group("g1")

    assert summary.id == "g1"
    assert summary.display_name == "Sales Team"
