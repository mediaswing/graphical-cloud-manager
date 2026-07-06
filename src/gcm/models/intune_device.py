from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class IntuneDeviceSummary:
    id: str
    device_name: str
    operating_system: str | None
    os_version: str | None
    compliance_state: str | None
    management_state: str | None
    management_agent: str | None
    ownership: str | None
    user_display_name: str | None
    user_principal_name: str | None
    last_sync: datetime | None
    serial_number: str | None
    azure_ad_device_id: str | None
