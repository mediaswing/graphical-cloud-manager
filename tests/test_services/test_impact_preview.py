"""Unit tests for the centralized impact-preview builder: correct license/
group/admin-role derivation from a bounded set of fake Graph calls, and
that failures in one part (e.g. sign-in lookup) don't blow up the whole
preview -- they're recorded as warnings instead.
"""

from __future__ import annotations

import datetime

import pytest
from msgraph.generated.models.assigned_license import AssignedLicense
from msgraph.generated.models.directory_role import DirectoryRole
from msgraph.generated.models.group import Group
from msgraph.generated.models.sign_in import SignIn
from msgraph.generated.models.sign_in_status import SignInStatus
from msgraph.generated.models.subscribed_sku import SubscribedSku
from msgraph.generated.models.subscribed_sku_collection_response import (
    SubscribedSkuCollectionResponse,
)
from msgraph.generated.models.user import User

from gcm.services.impact_preview import build_user_impact_preview


class _Result:
    def __init__(self, value, next_link=""):
        self.value = value
        self.odata_next_link = next_link


class _FakeMemberOfBuilder:
    def __init__(self, result):
        self._result = result

    async def get(self, request_configuration=None):
        return self._result


class _FakeUserItemWrapper:
    """Wraps a user + a separate member_of sub-builder, matching the real
    SDK's `by_user_id(id).member_of.get(...)` chain."""

    def __init__(self, user, member_of_result):
        self._user = user
        self.member_of = _FakeMemberOfBuilder(member_of_result)

    async def get(self, request_configuration=None):
        return self._user


class _FakeUsersBuilder:
    def __init__(self, item):
        self._item = item

    def by_user_id(self, user_id):
        return self._item


class _FakeSubscribedSkus:
    def __init__(self, skus):
        self._skus = skus

    async def get(self):
        return _Result(self._skus)


class _FakeSignIns:
    def __init__(self, sign_ins):
        self._sign_ins = sign_ins
        self.should_fail = False

    async def get(self, request_configuration=None):
        if self.should_fail:
            raise RuntimeError("simulated failure")
        return _Result(self._sign_ins)


class _FakeAuditLogs:
    def __init__(self, sign_ins_builder):
        self.sign_ins = sign_ins_builder


class _FakeGraphClient:
    def __init__(self, user, member_of_entries, skus=(), sign_ins=()):
        self.users = _FakeUsersBuilder(
            _FakeUserItemWrapper(user, _Result(list(member_of_entries)))
        )
        self.subscribed_skus = _FakeSubscribedSkus(list(skus))
        self._sign_ins_builder = _FakeSignIns(list(sign_ins))
        self.audit_logs = _FakeAuditLogs(self._sign_ins_builder)


@pytest.mark.asyncio
async def test_preview_includes_licenses_groups_and_admin_roles():
    user = User(
        id="u1", display_name="Jane Doe", user_principal_name="jane@contoso.com",
        account_enabled=True,
        assigned_licenses=[AssignedLicense(sku_id="s1")],
    )
    sku = SubscribedSku(sku_id="s1", sku_part_number="ENTERPRISEPACK")
    group = Group(display_name="Sales Team")
    role = DirectoryRole(display_name="User Administrator")
    client = _FakeGraphClient(user, [group, role], skus=[sku])

    preview = await build_user_impact_preview(client, "u1", has_audit_logs=False)

    assert preview.display_name == "Jane Doe"
    assert preview.license_names == ["ENTERPRISEPACK"]
    assert preview.group_names == ["Sales Team"]
    assert preview.admin_role_names == ["User Administrator"]
    assert preview.last_sign_in_checked is False
    assert preview.last_sign_in is None
    assert preview.warnings == []


@pytest.mark.asyncio
async def test_preview_includes_last_sign_in_when_premium_available():
    user = User(id="u1", display_name="Jane", user_principal_name="jane@contoso.com")
    sign_in = SignIn(
        created_date_time=datetime.datetime(2026, 7, 1, 9, 0),
        status=SignInStatus(error_code=0),
    )
    client = _FakeGraphClient(user, [], sign_ins=[sign_in])

    preview = await build_user_impact_preview(client, "u1", has_audit_logs=True)

    assert preview.last_sign_in_checked is True
    assert preview.last_sign_in == "2026-07-01 09:00"


@pytest.mark.asyncio
async def test_preview_records_warning_when_sign_in_lookup_fails_but_still_returns():
    user = User(id="u1", display_name="Jane", user_principal_name="jane@contoso.com")
    client = _FakeGraphClient(user, [])
    client._sign_ins_builder.should_fail = True

    preview = await build_user_impact_preview(client, "u1", has_audit_logs=True)

    assert preview.display_name == "Jane"
    assert any("sign-in" in w.lower() for w in preview.warnings)


@pytest.mark.asyncio
async def test_preview_flags_truncated_member_of_when_more_pages_exist():
    user = User(id="u1", display_name="Jane", user_principal_name="jane@contoso.com")
    group = Group(display_name="Group 1")
    client = _FakeGraphClient(user, [group])
    client.users._item.member_of._result.odata_next_link = "https://graph.microsoft.com/v1.0/next"

    preview = await build_user_impact_preview(client, "u1", has_audit_logs=False)

    assert preview.member_of_truncated is True


def test_not_checked_note_is_present_and_non_empty():
    from gcm.services.impact_preview import NOT_CHECKED_NOTE

    assert len(NOT_CHECKED_NOTE) > 0
