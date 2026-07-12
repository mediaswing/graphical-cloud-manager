"""Exchange mailbox basics, built only on capabilities Microsoft Graph
genuinely supports -- verified against the installed SDK, not assumed.

Two important gaps, documented rather than worked around:

- **Forwarding**: Graph has no equivalent of Exchange's classic
  `ForwardingSmtpAddress` mailbox attribute at all (confirmed by grepping
  every generated model for "forwarding" -- nothing exists). The only
  Graph-native mechanism is an inbox rule with a `forwardTo`/`redirectTo`
  action, which is what this module uses, managed under a fixed,
  recognizable rule name so it never touches the mailbox owner's own
  rules. This is a genuinely different mechanism from the classic
  attribute (visible/editable by the owner in Outlook's rule list) and is
  always labeled "rule-based forwarding", never plain "forwarding".
- **Shared mailboxes**: Graph has no reliable way to tell a shared mailbox
  apart from a regular user mailbox (no `recipientTypeDetails`-equivalent
  on the `user` resource). Not implemented -- EXO PowerShell only.

Mailbox usage reports return raw CSV bytes (not JSON), and Microsoft may
anonymize identities in them depending on a tenant-wide admin-center
privacy setting this app doesn't control -- both are surfaced to the UI
rather than papered over.
"""

from __future__ import annotations

import csv
import io

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph import GraphServiceClient
from msgraph.generated.models.automatic_replies_setting import AutomaticRepliesSetting
from msgraph.generated.models.automatic_replies_status import AutomaticRepliesStatus
from msgraph.generated.models.email_address import EmailAddress
from msgraph.generated.models.external_audience_scope import ExternalAudienceScope
from msgraph.generated.models.mailbox_settings import MailboxSettings
from msgraph.generated.models.message_rule import MessageRule
from msgraph.generated.models.message_rule_actions import MessageRuleActions
from msgraph.generated.models.recipient import Recipient
from msgraph.generated.models.user import User
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder

from gcm.graph.pagination import collect_all
from gcm.models.mailbox import (
    AliasesSummary,
    AutomaticRepliesSummary,
    ForwardingRuleSummary,
    MailboxUsageSummary,
)
from gcm.services import audit_log
from gcm.services.graph_errors import friendly_error_message

_FORWARDING_RULE_NAME = "Graphical Cloud Manager - Forwarding"

_AUDIENCE_TO_ENUM = {
    "none": ExternalAudienceScope.None_,
    "contactsOnly": ExternalAudienceScope.ContactsOnly,
    "all": ExternalAudienceScope.All,
}


class MailboxService:
    def __init__(self, graph_client: GraphServiceClient) -> None:
        self._graph = graph_client

    # -- Tenant domains ---------------------------------------------------------

    async def list_verified_domain_names(self) -> set[str]:
        """Lowercased domain names verified for this tenant. A tenant
        routinely has more than one (e.g. contoso.com and its default
        contoso.onmicrosoft.com), all equally internal -- a forwarding
        target's domain needs checking against this whole set, not just
        whichever domain the loaded mailbox happens to use, or two internal
        domains would wrongly warn "leaving your tenant" against each other."""
        result = await self._graph.domains.get()
        domains = result.value if result else []
        return {d.id.lower() for d in domains if d.id}

    # -- Aliases (proxyAddresses) ---------------------------------------------

    async def get_aliases(self, user_id: str) -> AliasesSummary:
        user = await self._get_user_select(user_id, ["id", "proxyAddresses"])
        primary, aliases = _split_proxy_addresses(user.proxy_addresses or [])
        return AliasesSummary(user_id=user.id, primary_address=primary, aliases=aliases)

    async def add_alias(self, user_id: str, alias: str, *, display_name: str | None = None) -> None:
        try:
            user = await self._get_user_select(user_id, ["proxyAddresses"])
            proxy_addresses = list(user.proxy_addresses or [])
            if any(addr.lower() == f"smtp:{alias.lower()}" for addr in proxy_addresses):
                return  # already present -- nothing to do
            proxy_addresses.append(f"smtp:{alias}")
            await self._graph.users.by_user_id(user_id).patch(
                User(proxy_addresses=proxy_addresses)
            )
        except Exception as exc:
            audit_log.record(
                "add_mailbox_alias", "User", user_id, display_name or user_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "add_mailbox_alias", "User", user_id, display_name or user_id,
            result="success", after={"alias": alias},
        )

    async def remove_alias(
        self, user_id: str, alias: str, *, display_name: str | None = None
    ) -> None:
        try:
            user = await self._get_user_select(user_id, ["proxyAddresses"])
            proxy_addresses = user.proxy_addresses or []
            is_primary = any(
                addr.startswith("SMTP:") and addr[5:].lower() == alias.lower()
                for addr in proxy_addresses
            )
            if is_primary:
                raise ValueError("Can't remove the primary email address as an alias.")
            new_addresses = [
                addr
                for addr in proxy_addresses
                if not (addr.lower().startswith("smtp:") and addr[5:].lower() == alias.lower())
            ]
            await self._graph.users.by_user_id(user_id).patch(
                User(proxy_addresses=new_addresses)
            )
        except Exception as exc:
            audit_log.record(
                "remove_mailbox_alias", "User", user_id, display_name or user_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "remove_mailbox_alias", "User", user_id, display_name or user_id,
            result="success", after={"alias": alias},
        )

    # -- Automatic replies -----------------------------------------------------

    async def get_automatic_replies(self, user_id: str) -> AutomaticRepliesSummary:
        user = await self._get_user_select(user_id, ["mailboxSettings"])
        settings = user.mailbox_settings.automatic_replies_setting if user.mailbox_settings else None
        if settings is None:
            return AutomaticRepliesSummary(
                enabled=False, external_audience="none", internal_message="", external_message=""
            )
        return AutomaticRepliesSummary(
            enabled=settings.status == AutomaticRepliesStatus.AlwaysEnabled,
            external_audience=settings.external_audience.value if settings.external_audience else "none",
            internal_message=settings.internal_reply_message or "",
            external_message=settings.external_reply_message or "",
        )

    async def set_automatic_replies(
        self,
        user_id: str,
        *,
        enabled: bool,
        external_audience: str,
        internal_message: str,
        external_message: str,
        display_name: str | None = None,
    ) -> None:
        body = User(
            mailbox_settings=MailboxSettings(
                automatic_replies_setting=AutomaticRepliesSetting(
                    status=(
                        AutomaticRepliesStatus.AlwaysEnabled
                        if enabled
                        else AutomaticRepliesStatus.Disabled
                    ),
                    external_audience=_AUDIENCE_TO_ENUM.get(
                        external_audience, ExternalAudienceScope.None_
                    ),
                    internal_reply_message=internal_message,
                    external_reply_message=external_message,
                )
            )
        )
        try:
            await self._graph.users.by_user_id(user_id).patch(body)
        except Exception as exc:
            audit_log.record(
                "set_automatic_replies", "User", user_id, display_name or user_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "set_automatic_replies", "User", user_id, display_name or user_id, result="success",
            after={"enabled": enabled, "external_audience": external_audience},
        )

    # -- Rule-based forwarding --------------------------------------------------

    async def get_forwarding_rule(self, user_id: str) -> ForwardingRuleSummary:
        rule = await self._find_forwarding_rule(user_id)
        if rule is None:
            return ForwardingRuleSummary(exists=False)
        actions = rule.actions
        if actions and actions.forward_to:
            return ForwardingRuleSummary(
                exists=True, target_address=actions.forward_to[0].email_address.address, keep_copy=True
            )
        if actions and actions.redirect_to:
            return ForwardingRuleSummary(
                exists=True, target_address=actions.redirect_to[0].email_address.address, keep_copy=False
            )
        return ForwardingRuleSummary(exists=True)

    async def set_forwarding_rule(
        self,
        user_id: str,
        target_address: str,
        *,
        keep_copy: bool,
        display_name: str | None = None,
    ) -> None:
        recipient = Recipient(email_address=EmailAddress(address=target_address))
        body = MessageRule(
            display_name=_FORWARDING_RULE_NAME,
            is_enabled=True,
            actions=MessageRuleActions(
                forward_to=[recipient] if keep_copy else None,
                redirect_to=[recipient] if not keep_copy else None,
            ),
        )
        try:
            existing = await self._find_forwarding_rule(user_id)
            rules_client = self._graph.users.by_user_id(user_id).mail_folders.by_mail_folder_id(
                "inbox"
            ).message_rules
            if existing is not None:
                await rules_client.by_message_rule_id(existing.id).patch(body)
            else:
                await rules_client.post(body)
        except Exception as exc:
            audit_log.record(
                "set_forwarding_rule", "User", user_id, display_name or user_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "set_forwarding_rule", "User", user_id, display_name or user_id, result="success",
            after={"target_address": target_address, "keep_copy": keep_copy},
        )

    async def remove_forwarding_rule(self, user_id: str, *, display_name: str | None = None) -> None:
        try:
            existing = await self._find_forwarding_rule(user_id)
            if existing is None:
                return
            await self._graph.users.by_user_id(user_id).mail_folders.by_mail_folder_id(
                "inbox"
            ).message_rules.by_message_rule_id(existing.id).delete()
        except Exception as exc:
            audit_log.record(
                "remove_forwarding_rule", "User", user_id, display_name or user_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "remove_forwarding_rule", "User", user_id, display_name or user_id, result="success"
        )

    async def _find_forwarding_rule(self, user_id: str) -> MessageRule | None:
        first_page = await self._graph.users.by_user_id(user_id).mail_folders.by_mail_folder_id(
            "inbox"
        ).message_rules.get()
        rules = await collect_all(first_page, self._graph.request_adapter)
        for rule in rules:
            if rule.display_name == _FORWARDING_RULE_NAME:
                return rule
        return None

    # -- Mailbox usage report (read-only) ---------------------------------------

    async def get_mailbox_usage(
        self, user_principal_name: str, *, period_days: int = 7
    ) -> MailboxUsageSummary | None:
        period = f"D{period_days}"
        raw = await self._graph.reports.get_mailbox_usage_detail_with_period(period).get()
        if not raw:
            return None
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        note = (
            "Mailbox usage reports can take 24-48 hours to reflect recent activity, "
            "and Microsoft may show anonymized names/addresses depending on a "
            "tenant-wide reporting privacy setting this app doesn't control."
        )
        for row in reader:
            if row.get("User Principal Name", "").lower() == user_principal_name.lower():
                return MailboxUsageSummary(
                    display_name=row.get("Display Name") or None,
                    storage_used_bytes=_to_int(row.get("Storage Used (Byte)")),
                    item_count=_to_int(row.get("Item Count")),
                    prohibit_send_receive_quota_bytes=_to_int(
                        row.get("Prohibit Send/Receive Quota (Byte)")
                    ),
                    report_period_days=period_days,
                    note=note,
                )
        return None

    async def _get_user_select(self, user_id: str, select: list[str]) -> User:
        query_params = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters(
            select=select
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        return await self._graph.users.by_user_id(user_id).get(request_configuration=request_config)


def _split_proxy_addresses(proxy_addresses: list[str]) -> tuple[str | None, list[str]]:
    primary = None
    aliases = []
    for addr in proxy_addresses:
        if addr.startswith("SMTP:"):
            primary = addr[5:]
        elif addr.lower().startswith("smtp:"):
            aliases.append(addr[5:])
    return primary, aliases


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None
