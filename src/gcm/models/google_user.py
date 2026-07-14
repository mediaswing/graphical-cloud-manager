from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GoogleUserSummary:
    id: str
    primary_email: str
    full_name: str
    suspended: bool


@dataclass
class GoogleUserDetail:
    id: str
    given_name: str
    family_name: str
    primary_email: str
    org_unit_path: str
    recovery_email: str | None
    recovery_phone: str | None
