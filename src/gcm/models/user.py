from __future__ import annotations

from dataclasses import dataclass


@dataclass
class UserSummary:
    id: str
    display_name: str
    user_principal_name: str
    mail: str | None
    account_enabled: bool


@dataclass
class UserDetail:
    id: str
    display_name: str
    job_title: str | None
    department: str | None
    office_location: str | None
    mobile_phone: str | None
    usage_location: str | None
