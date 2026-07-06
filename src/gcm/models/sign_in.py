from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class SignInSummary:
    id: str
    created_at: datetime | None
    user_display_name: str
    user_principal_name: str
    app_display_name: str
    ip_address: str | None
    device_display_name: str | None
    device_operating_system: str | None
    succeeded: bool
    failure_reason: str | None
