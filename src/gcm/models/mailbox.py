from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AliasesSummary:
    user_id: str
    primary_address: str | None
    aliases: list[str] = field(default_factory=list)


@dataclass
class AutomaticRepliesSummary:
    enabled: bool
    external_audience: str  # "none" | "contactsOnly" | "all"
    internal_message: str
    external_message: str


@dataclass
class ForwardingRuleSummary:
    """Rule-based forwarding via a dedicated, recognizably-named inbox rule
    -- not the same mechanism as Exchange's classic ForwardingSmtpAddress
    mailbox attribute, which Graph doesn't expose (EXO PowerShell only)."""

    exists: bool
    target_address: str | None = None
    keep_copy: bool = False


@dataclass
class MailboxUsageSummary:
    display_name: str | None
    storage_used_bytes: int | None
    item_count: int | None
    prohibit_send_receive_quota_bytes: int | None
    report_period_days: int
    note: str
