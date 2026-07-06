from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImportRow:
    row_number: int  # 1-based, matches the CSV's data rows for the admin's reference
    display_name: str
    user_principal_name: str
    mail_nickname: str
    password: str
    account_enabled: bool
    usage_location: str | None
    license_sku_part_numbers: list[str]
    group_names: list[str]
    errors: list[str] = field(default_factory=list)  # blocking -- row is skipped
    warnings: list[str] = field(default_factory=list)  # non-blocking -- row still runs

    @property
    def is_valid(self) -> bool:
        return not self.errors


@dataclass
class ImportRowResult:
    row_number: int
    display_name: str
    user_principal_name: str
    success: bool
    message: str
