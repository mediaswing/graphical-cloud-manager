from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class GoogleSignInSummary:
    time: datetime | None
    user_email: str
    ip_address: str | None
    succeeded: bool
    event_name: str  # e.g. "login_success" | "login_failure" | "logout" | ...
    failure_type: str | None
