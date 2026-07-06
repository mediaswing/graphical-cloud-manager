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
