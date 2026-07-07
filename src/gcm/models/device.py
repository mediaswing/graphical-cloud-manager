from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class DeviceSummary:
    id: str
    display_name: str
    operating_system: str | None
    operating_system_version: str | None
    trust_type: str | None
    is_compliant: bool | None
    is_managed: bool | None
    account_enabled: bool
    approximate_last_sign_in: datetime | None
    azure_ad_device_id: str | None
