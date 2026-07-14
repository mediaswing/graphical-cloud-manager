from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class GoogleAdminAuditSummary:
    time: datetime | None
    actor_email: str
    event_name: str  # e.g. "CREATE_USER" | "DELETE_GROUP" | "CHANGE_PASSWORD" | ...
    details: str  # flattened event parameters, e.g. "USER_EMAIL=jane@example.com"
