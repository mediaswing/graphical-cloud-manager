from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GoogleGroupSummary:
    id: str
    email: str
    name: str
    description: str


@dataclass
class GoogleGroupMember:
    id: str
    email: str
    role: str  # "MEMBER" | "MANAGER" | "OWNER"
