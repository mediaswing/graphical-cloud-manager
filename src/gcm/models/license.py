from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SubscribedSkuSummary:
    sku_id: str
    sku_part_number: str
    enabled_units: int
    consumed_units: int

    @property
    def available_units(self) -> int:
        return self.enabled_units - self.consumed_units
