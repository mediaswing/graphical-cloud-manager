from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VacationResponderSummary:
    enabled: bool
    subject: str
    message: str
    restrict_to_contacts: bool


@dataclass
class AutoForwardingSummary:
    enabled: bool
    forwarding_email: str
    disposition: str  # "leaveInInbox" | "archive" | "trash" | "markRead"


@dataclass
class ForwardingAddressSummary:
    forwarding_email: str
    verification_status: str  # "accepted" | "pending"


@dataclass
class MailboxDelegate:
    delegate_email: str
    verification_status: str  # "accepted" | "pending" | "expired" | ...
