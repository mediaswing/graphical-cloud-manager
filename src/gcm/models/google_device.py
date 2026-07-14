from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class GoogleMobileDeviceSummary:
    resource_id: str
    model: str
    os_type: str
    status: str  # "APPROVED" | "PENDING" | "BLOCKED" | "WIPING" | "WIPED" | ...
    owner_email: str
    owner_name: str
    serial_number: str | None
    last_sync: datetime | None
