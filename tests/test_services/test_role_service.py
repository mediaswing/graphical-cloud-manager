"""Unit tests for RoleService's Graph-model-to-dataclass conversion.
Doesn't touch the network -- constructs real msgraph models directly."""

from __future__ import annotations

from msgraph.generated.models.unified_role_assignment import UnifiedRoleAssignment
from msgraph.generated.models.unified_role_definition import UnifiedRoleDefinition
from msgraph.generated.models.user import User

from gcm.services.role_service import _to_assignment_summary, _to_definition_summary


def test_to_definition_summary_maps_fields():
    definition = UnifiedRoleDefinition(
        id="r1", display_name="User Administrator", description="Manages users", is_built_in=True
    )
    summary = _to_definition_summary(definition)
    assert summary.id == "r1"
    assert summary.display_name == "User Administrator"
    assert summary.is_built_in is True


def test_to_definition_summary_falls_back_to_placeholder_name():
    definition = UnifiedRoleDefinition(id="r2", display_name=None, is_built_in=False)
    summary = _to_definition_summary(definition)
    assert summary.display_name == "(no display name)"


def test_to_assignment_summary_uses_expanded_principal_display_name():
    assignment = UnifiedRoleAssignment(
        id="a1", principal_id="p1", principal=User(display_name="Jane Doe")
    )
    summary = _to_assignment_summary(assignment)
    assert summary.principal_display_name == "Jane Doe"


def test_to_assignment_summary_falls_back_to_principal_id():
    assignment = UnifiedRoleAssignment(id="a2", principal_id="p2", principal=None)
    summary = _to_assignment_summary(assignment)
    assert summary.principal_display_name == "p2"
