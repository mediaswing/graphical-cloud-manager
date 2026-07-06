from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RoleDefinitionSummary:
    id: str
    display_name: str
    description: str | None
    is_built_in: bool


@dataclass
class RoleAssignmentSummary:
    id: str
    principal_id: str
    principal_display_name: str
