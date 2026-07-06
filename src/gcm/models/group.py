from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GroupSummary:
    id: str
    display_name: str
    mail: str | None
    group_type: str  # "Microsoft 365" | "Security" | "Mail-enabled security" | "Distribution"


@dataclass
class GroupMember:
    id: str
    display_name: str


@dataclass
class DynamicMembershipInfo:
    group_id: str
    is_dynamic: bool
    membership_rule: str | None
    processing_state: str | None
    is_microsoft_365: bool
    dynamic_kind: str  # "user" | "device" | "unknown" -- inferred from the rule text, display-only

    @staticmethod
    def infer_kind(rule: str | None) -> str:
        if not rule:
            return "unknown"
        has_device = "device." in rule
        has_user = "user." in rule
        if has_device and not has_user:
            return "device"
        if has_user and not has_device:
            return "user"
        return "unknown"
