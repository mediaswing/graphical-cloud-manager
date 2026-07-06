from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ServicePlanSummary:
    id: str
    name: str


@dataclass
class SubscribedSkuSummary:
    sku_id: str
    sku_part_number: str
    enabled_units: int
    consumed_units: int
    service_plans: list[ServicePlanSummary] = field(default_factory=list)

    @property
    def available_units(self) -> int:
        return self.enabled_units - self.consumed_units


@dataclass
class UserLicenseAssignment:
    """One SKU assigned to a user, with enough info to tell a direct
    assignment apart from one inherited through a group (`assigned_by_group_id`
    is None for direct assignments)."""

    sku_id: str
    sku_part_number: str
    assigned_by_group_id: str | None
    state: str | None
    disabled_service_plan_names: list[str] = field(default_factory=list)

    @property
    def is_direct(self) -> bool:
        return self.assigned_by_group_id is None
