"""Unit tests for bulk user CSV import: local structural validation (no
network), and orchestration (tenant validation + execution) against fake
sub-services so no real Graph client is needed.
"""

from __future__ import annotations

import pytest
from msgraph.generated.models.o_data_errors.o_data_error import ODataError

from gcm.models.license import SubscribedSkuSummary
from gcm.models.user import UserDetail
from gcm.services.bulk_import_service import (
    BulkImportFileError,
    BulkImportService,
    _parse_row,
)

# ---------------------------------------------------------------------------
# _parse_row (pure function)
# ---------------------------------------------------------------------------


def test_parse_row_accepts_a_complete_valid_row():
    row = _parse_row(
        1,
        {
            "display_name": "Jane Doe",
            "user_principal_name": "jane@contoso.com",
            "mail_nickname": "jane",
            "password": "SuperSecret1!",
            "account_enabled": "true",
            "usage_location": "us",
            "license_skus": "ENTERPRISEPACK;FLOW_FREE",
            "groups": "Sales;All Staff",
        },
    )
    assert row.is_valid
    assert row.usage_location == "US"
    assert row.license_sku_part_numbers == ["ENTERPRISEPACK", "FLOW_FREE"]
    assert row.group_names == ["Sales", "All Staff"]
    assert row.account_enabled is True


def test_parse_row_flags_missing_required_fields():
    row = _parse_row(1, {"display_name": "", "user_principal_name": "", "mail_nickname": "", "password": ""})
    assert not row.is_valid
    assert any("Display name" in e for e in row.errors)
    assert any("User principal name" in e for e in row.errors)
    assert any("Mail nickname" in e for e in row.errors)
    assert any("Password" in e for e in row.errors)


def test_parse_row_flags_upn_without_at_sign():
    row = _parse_row(
        1,
        {"display_name": "Jane", "user_principal_name": "not-an-email", "mail_nickname": "jane", "password": "x1234567"},
    )
    assert any("email address" in e for e in row.errors)


def test_parse_row_warns_on_short_password_but_does_not_block():
    row = _parse_row(
        1,
        {"display_name": "Jane", "user_principal_name": "jane@contoso.com", "mail_nickname": "jane", "password": "short"},
    )
    assert row.is_valid
    assert any("shorter than 8" in w for w in row.warnings)


def test_parse_row_rejects_invalid_account_enabled_value():
    row = _parse_row(
        1,
        {
            "display_name": "Jane", "user_principal_name": "jane@contoso.com",
            "mail_nickname": "jane", "password": "x1234567", "account_enabled": "maybe",
        },
    )
    assert not row.is_valid


def test_parse_row_rejects_bad_usage_location_length():
    row = _parse_row(
        1,
        {
            "display_name": "Jane", "user_principal_name": "jane@contoso.com",
            "mail_nickname": "jane", "password": "x1234567", "usage_location": "USA",
        },
    )
    assert not row.is_valid


# ---------------------------------------------------------------------------
# parse_and_validate_locally
# ---------------------------------------------------------------------------


def test_parse_and_validate_locally_raises_on_missing_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("display_name,user_principal_name\nJane,jane@contoso.com\n", encoding="utf-8")
    service = BulkImportService(graph_client=None)

    with pytest.raises(BulkImportFileError):
        service.parse_and_validate_locally(str(path))


def test_parse_and_validate_locally_flags_duplicate_upns_in_file(tmp_path):
    path = tmp_path / "dupes.csv"
    path.write_text(
        "display_name,user_principal_name,mail_nickname,password\n"
        "Jane,jane@contoso.com,jane,Password1!\n"
        "Jane Two,jane@contoso.com,jane2,Password1!\n",
        encoding="utf-8",
    )
    service = BulkImportService(graph_client=None)

    rows = service.parse_and_validate_locally(str(path))

    assert rows[0].is_valid
    assert not rows[1].is_valid
    assert any("Duplicate" in e for e in rows[1].errors)


# ---------------------------------------------------------------------------
# validate_against_tenant / execute -- fake sub-services, no real Graph client
# ---------------------------------------------------------------------------


class _FakeUserService:
    def __init__(self, existing_upns=()):
        self._existing = set(existing_upns)
        self.created = []

    async def get_user_detail(self, upn_or_id):
        if upn_or_id in self._existing:
            return UserDetail(
                id="existing", display_name="x", job_title=None, department=None,
                office_location=None, mobile_phone=None, usage_location=None,
            )
        raise ODataError(response_status_code=404)

    async def create_user(self, **kwargs):
        self.created.append(kwargs)
        from gcm.models.user import UserSummary

        return UserSummary(
            id=f"new-{len(self.created)}",
            display_name=kwargs["display_name"],
            user_principal_name=kwargs["user_principal_name"],
            mail=None,
            account_enabled=kwargs.get("account_enabled", True),
        )

    async def update_user(self, user_id, **kwargs):
        pass


class _FakeGroupService:
    def __init__(self, groups):
        self._groups = groups
        self.added = []

    async def list_groups(self):
        return self._groups

    async def add_member(self, group_id, user_id, *, group_display_name=None):
        self.added.append((group_id, user_id))


class _FakeLicenseService:
    def __init__(self, skus):
        self._skus = skus
        self.assigned = []

    async def list_subscribed_skus(self):
        return self._skus

    async def set_user_licenses(self, user_id, *, add_sku_ids, remove_sku_ids, display_name=None):
        self.assigned.append((user_id, add_sku_ids, remove_sku_ids))


def _make_service_with_fakes(existing_upns=(), skus=(), groups=()):
    service = BulkImportService(graph_client=None)
    service._user_service = _FakeUserService(existing_upns)
    service._group_service = _FakeGroupService(list(groups))
    service._license_service = _FakeLicenseService(list(skus))
    return service


def _valid_row(row_number=1, upn="jane@contoso.com"):
    return _parse_row(
        row_number,
        {
            "display_name": "Jane Doe", "user_principal_name": upn,
            "mail_nickname": "jane", "password": "Password1!",
        },
    )


@pytest.mark.asyncio
async def test_validate_against_tenant_flags_existing_user():
    service = _make_service_with_fakes(existing_upns={"jane@contoso.com"})
    rows = [_valid_row()]

    await service.validate_against_tenant(rows)

    assert not rows[0].is_valid
    assert any("already exists" in e for e in rows[0].errors)


@pytest.mark.asyncio
async def test_validate_against_tenant_flags_unknown_sku_and_group():
    service = _make_service_with_fakes()
    row = _parse_row(
        1,
        {
            "display_name": "Jane", "user_principal_name": "jane@contoso.com",
            "mail_nickname": "jane", "password": "Password1!",
            "license_skus": "NOPE", "groups": "Nonexistent Group",
        },
    )

    await service.validate_against_tenant([row])

    assert not row.is_valid
    assert any("Unknown license SKU" in e for e in row.errors)
    assert any("Unknown group" in e for e in row.errors)


@pytest.mark.asyncio
async def test_execute_skips_invalid_rows_without_calling_create_user():
    service = _make_service_with_fakes()
    invalid_row = _parse_row(1, {"display_name": "", "user_principal_name": "", "mail_nickname": "", "password": ""})

    results = await service.execute([invalid_row])

    assert results[0].success is False
    assert "Skipped" in results[0].message
    assert service._user_service.created == []


@pytest.mark.asyncio
async def test_execute_continues_after_one_row_fails():
    service = _make_service_with_fakes()
    service._user_service.create_user = _raise_on_second_call(service._user_service.create_user)
    rows = [_valid_row(1, "a@contoso.com"), _valid_row(2, "b@contoso.com"), _valid_row(3, "c@contoso.com")]

    results = await service.execute(rows)

    assert len(results) == 3
    assert results[0].success is True
    assert results[1].success is False
    assert results[2].success is True


@pytest.mark.asyncio
async def test_execute_reports_partial_success_when_a_follow_up_step_fails():
    service = _make_service_with_fakes(skus=[])
    row = _parse_row(
        1,
        {
            "display_name": "Jane", "user_principal_name": "jane@contoso.com",
            "mail_nickname": "jane", "password": "Password1!", "license_skus": "MISSING",
        },
    )
    # Bypass validate_against_tenant (which would normally catch the unknown
    # SKU) to specifically exercise execute()'s own partial-failure handling.
    row.errors = []

    results = await service.execute([row])

    assert results[0].success is False
    assert "User created" in results[0].message
    assert len(service._user_service.created) == 1


def _raise_on_second_call(fn):
    calls = {"n": 0}

    async def wrapper(**kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated failure")
        return await fn(**kwargs)

    return wrapper
