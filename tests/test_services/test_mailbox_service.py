"""Unit tests for MailboxService: aliases, automatic replies, rule-based
forwarding, and mailbox usage report parsing. No network -- fakes just the
handful of Graph client methods each test needs.
"""

from __future__ import annotations

import pytest
from msgraph.generated.models.automatic_replies_setting import AutomaticRepliesSetting
from msgraph.generated.models.automatic_replies_status import AutomaticRepliesStatus
from msgraph.generated.models.external_audience_scope import ExternalAudienceScope
from msgraph.generated.models.mailbox_settings import MailboxSettings
from msgraph.generated.models.message_rule import MessageRule
from msgraph.generated.models.message_rule_actions import MessageRuleActions
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.user import User

from gcm.services import audit_log
from gcm.services.mailbox_service import MailboxService, _split_proxy_addresses


def test_split_proxy_addresses_separates_primary_and_aliases():
    primary, aliases = _split_proxy_addresses(
        ["SMTP:jane@contoso.com", "smtp:jane.alias@contoso.com", "smtp:j@contoso.com"]
    )
    assert primary == "jane@contoso.com"
    assert aliases == ["jane.alias@contoso.com", "j@contoso.com"]


def test_split_proxy_addresses_handles_empty_list():
    primary, aliases = _split_proxy_addresses([])
    assert primary is None
    assert aliases == []


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeUserItemBuilder:
    def __init__(self, user=None) -> None:
        self._user = user
        self.patched_body = None

    async def get(self, request_configuration=None):
        return self._user

    async def patch(self, body):
        self.patched_body = body
        # keep the fake user's state in sync for tests that patch then re-read
        if self._user is not None:
            if body.proxy_addresses is not None:
                self._user.proxy_addresses = body.proxy_addresses


class _FakeMessageRulesBuilder:
    def __init__(self, rules=None) -> None:
        self._rules = rules or []
        self.posted_body = None
        self.patched = {}
        self.deleted_ids = []

    async def get(self, request_configuration=None):
        class _Result:
            pass

        result = _Result()
        result.value = self._rules
        return result

    async def post(self, body):
        self.posted_body = body

    def by_message_rule_id(self, rule_id):
        return _FakeMessageRuleItemBuilder(self, rule_id)


class _FakeMessageRuleItemBuilder:
    def __init__(self, parent, rule_id) -> None:
        self._parent = parent
        self._rule_id = rule_id

    async def patch(self, body):
        self._parent.patched[self._rule_id] = body

    async def delete(self):
        self._parent.deleted_ids.append(self._rule_id)


class _FakeMailFolderItemBuilder:
    def __init__(self, message_rules_builder) -> None:
        self.message_rules = message_rules_builder


class _FakeMailFoldersBuilder:
    def __init__(self, message_rules_builder) -> None:
        self._builder = message_rules_builder

    def by_mail_folder_id(self, folder_id):
        return _FakeMailFolderItemBuilder(self._builder)


class _FakeUsersBuilder:
    def __init__(self, user_item_builder, mail_folders_builder=None) -> None:
        self._user_item_builder = user_item_builder
        self.mail_folders_builder = mail_folders_builder

    def by_user_id(self, user_id):
        if self.mail_folders_builder is not None:
            self._user_item_builder.mail_folders = self.mail_folders_builder
        return self._user_item_builder


class _FakeReportsBuilder:
    def __init__(self, csv_bytes) -> None:
        self._csv_bytes = csv_bytes

    def get_mailbox_usage_detail_with_period(self, period):
        return self

    async def get(self, request_configuration=None):
        return self._csv_bytes


class _FakeGraphClient:
    def __init__(self, user=None, message_rules=None, csv_bytes=None) -> None:
        user_item_builder = _FakeUserItemBuilder(user)
        message_rules_builder = _FakeMessageRulesBuilder(message_rules)
        mail_folders_builder = _FakeMailFoldersBuilder(message_rules_builder)
        self.users = _FakeUsersBuilder(user_item_builder, mail_folders_builder)
        self.reports = _FakeReportsBuilder(csv_bytes)
        self._user_item_builder = user_item_builder
        self._message_rules_builder = message_rules_builder


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_aliases_reads_primary_and_secondary_addresses():
    user = User(id="u1", proxy_addresses=["SMTP:jane@contoso.com", "smtp:alias@contoso.com"])
    service = MailboxService(_FakeGraphClient(user))

    summary = await service.get_aliases("u1")

    assert summary.primary_address == "jane@contoso.com"
    assert summary.aliases == ["alias@contoso.com"]


@pytest.mark.asyncio
async def test_add_alias_appends_to_proxy_addresses(tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    audit_log.set_actor("admin@contoso.com")
    user = User(id="u1", proxy_addresses=["SMTP:jane@contoso.com"])
    client = _FakeGraphClient(user)
    service = MailboxService(client)

    await service.add_alias("u1", "newalias@contoso.com", display_name="Jane Doe")

    assert "smtp:newalias@contoso.com" in client._user_item_builder.patched_body.proxy_addresses


@pytest.mark.asyncio
async def test_add_alias_is_a_no_op_if_already_present():
    user = User(id="u1", proxy_addresses=["SMTP:jane@contoso.com", "smtp:existing@contoso.com"])
    client = _FakeGraphClient(user)
    service = MailboxService(client)

    await service.add_alias("u1", "existing@contoso.com")

    assert client._user_item_builder.patched_body is None


@pytest.mark.asyncio
async def test_remove_alias_blocks_removing_the_primary_address():
    user = User(id="u1", proxy_addresses=["SMTP:jane@contoso.com"])
    service = MailboxService(_FakeGraphClient(user))

    with pytest.raises(ValueError):
        await service.remove_alias("u1", "jane@contoso.com")


@pytest.mark.asyncio
async def test_remove_alias_removes_a_secondary_address():
    user = User(id="u1", proxy_addresses=["SMTP:jane@contoso.com", "smtp:oldalias@contoso.com"])
    client = _FakeGraphClient(user)
    service = MailboxService(client)

    await service.remove_alias("u1", "oldalias@contoso.com")

    assert "smtp:oldalias@contoso.com" not in client._user_item_builder.patched_body.proxy_addresses
    assert "SMTP:jane@contoso.com" in client._user_item_builder.patched_body.proxy_addresses


# ---------------------------------------------------------------------------
# Automatic replies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_automatic_replies_reads_enabled_state():
    user = User(
        mailbox_settings=MailboxSettings(
            automatic_replies_setting=AutomaticRepliesSetting(
                status=AutomaticRepliesStatus.AlwaysEnabled,
                external_audience=ExternalAudienceScope.All,
                internal_reply_message="I'm out",
                external_reply_message="Away",
            )
        )
    )
    service = MailboxService(_FakeGraphClient(user))

    summary = await service.get_automatic_replies("u1")

    assert summary.enabled is True
    assert summary.external_audience == "all"
    assert summary.internal_message == "I'm out"


@pytest.mark.asyncio
async def test_get_automatic_replies_handles_missing_settings():
    user = User(mailbox_settings=None)
    service = MailboxService(_FakeGraphClient(user))

    summary = await service.get_automatic_replies("u1")

    assert summary.enabled is False


@pytest.mark.asyncio
async def test_set_automatic_replies_maps_enabled_to_status_enum():
    client = _FakeGraphClient(User())
    service = MailboxService(client)

    await service.set_automatic_replies(
        "u1", enabled=True, external_audience="contactsOnly",
        internal_message="in", external_message="out",
    )

    body = client._user_item_builder.patched_body
    assert body.mailbox_settings.automatic_replies_setting.status == AutomaticRepliesStatus.AlwaysEnabled
    assert body.mailbox_settings.automatic_replies_setting.external_audience == ExternalAudienceScope.ContactsOnly


# ---------------------------------------------------------------------------
# Rule-based forwarding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_forwarding_rule_reports_not_exists_when_no_rule():
    service = MailboxService(_FakeGraphClient(message_rules=[]))

    summary = await service.get_forwarding_rule("u1")

    assert summary.exists is False


@pytest.mark.asyncio
async def test_get_forwarding_rule_reads_redirect_as_no_copy():
    rule = MessageRule(
        display_name="Graphical Cloud Manager - Forwarding",
        actions=MessageRuleActions(
            redirect_to=[Recipient(email_address=EmailAddress(address="ext@example.com"))]
        ),
    )
    service = MailboxService(_FakeGraphClient(message_rules=[rule]))

    summary = await service.get_forwarding_rule("u1")

    assert summary.exists is True
    assert summary.target_address == "ext@example.com"
    assert summary.keep_copy is False


@pytest.mark.asyncio
async def test_get_forwarding_rule_reads_forward_as_keep_copy():
    rule = MessageRule(
        display_name="Graphical Cloud Manager - Forwarding",
        actions=MessageRuleActions(
            forward_to=[Recipient(email_address=EmailAddress(address="ext@example.com"))]
        ),
    )
    service = MailboxService(_FakeGraphClient(message_rules=[rule]))

    summary = await service.get_forwarding_rule("u1")

    assert summary.keep_copy is True


@pytest.mark.asyncio
async def test_set_forwarding_rule_creates_a_new_rule_when_none_exists():
    client = _FakeGraphClient(message_rules=[])
    service = MailboxService(client)

    await service.set_forwarding_rule("u1", "ext@example.com", keep_copy=False)

    assert client._message_rules_builder.posted_body is not None
    assert client._message_rules_builder.posted_body.display_name == "Graphical Cloud Manager - Forwarding"


@pytest.mark.asyncio
async def test_set_forwarding_rule_updates_the_existing_rule_instead_of_duplicating():
    existing = MessageRule(id="r1", display_name="Graphical Cloud Manager - Forwarding")
    client = _FakeGraphClient(message_rules=[existing])
    service = MailboxService(client)

    await service.set_forwarding_rule("u1", "new@example.com", keep_copy=True)

    assert client._message_rules_builder.posted_body is None
    assert "r1" in client._message_rules_builder.patched


@pytest.mark.asyncio
async def test_remove_forwarding_rule_deletes_the_named_rule():
    existing = MessageRule(id="r1", display_name="Graphical Cloud Manager - Forwarding")
    client = _FakeGraphClient(message_rules=[existing])
    service = MailboxService(client)

    await service.remove_forwarding_rule("u1")

    assert "r1" in client._message_rules_builder.deleted_ids


@pytest.mark.asyncio
async def test_remove_forwarding_rule_is_a_no_op_when_none_exists():
    client = _FakeGraphClient(message_rules=[])
    service = MailboxService(client)

    await service.remove_forwarding_rule("u1")

    assert client._message_rules_builder.deleted_ids == []


# ---------------------------------------------------------------------------
# Mailbox usage report
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_mailbox_usage_parses_matching_row():
    csv_bytes = (
        "Report Refresh Date,User Principal Name,Display Name,Item Count,"
        "Storage Used (Byte),Prohibit Send/Receive Quota (Byte)\r\n"
        "2026-07-01,jane@contoso.com,Jane Doe,120,5000000,53687091200\r\n"
    ).encode("utf-8-sig")
    service = MailboxService(_FakeGraphClient(csv_bytes=csv_bytes))

    summary = await service.get_mailbox_usage("jane@contoso.com")

    assert summary is not None
    assert summary.display_name == "Jane Doe"
    assert summary.item_count == 120
    assert summary.storage_used_bytes == 5000000


@pytest.mark.asyncio
async def test_get_mailbox_usage_returns_none_when_user_not_in_report():
    csv_bytes = (
        "User Principal Name,Display Name,Item Count,Storage Used (Byte)\r\n"
        "someone.else@contoso.com,Someone Else,1,1\r\n"
    ).encode("utf-8-sig")
    service = MailboxService(_FakeGraphClient(csv_bytes=csv_bytes))

    summary = await service.get_mailbox_usage("jane@contoso.com")

    assert summary is None


@pytest.mark.asyncio
async def test_get_mailbox_usage_returns_none_on_empty_report():
    service = MailboxService(_FakeGraphClient(csv_bytes=b""))
    summary = await service.get_mailbox_usage("jane@contoso.com")
    assert summary is None
