"""Unit tests for RoleService's Graph-model-to-dataclass conversion.
Doesn't touch the network -- constructs real msgraph models directly.

Uses directoryRoleTemplates/directoryRoles' member shape (a plain User, since
role membership is a DirectoryObject collection) rather than the unified RBAC
API's models -- see role_service.py's module docstring for why.
"""

from __future__ import annotations

from msgraph.generated.models.directory_role_template import DirectoryRoleTemplate
from msgraph.generated.models.user import User

from gcm.services.role_service import _to_assignment_summary, _to_definition_summary


def test_to_definition_summary_maps_fields():
    template = DirectoryRoleTemplate(
        id="r1", display_name="User Administrator", description="Manages users"
    )
    summary = _to_definition_summary(template)
    assert summary.id == "r1"
    assert summary.display_name == "User Administrator"
    assert summary.is_built_in is True


def test_to_definition_summary_falls_back_to_placeholder_name():
    template = DirectoryRoleTemplate(id="r2", display_name=None)
    summary = _to_definition_summary(template)
    assert summary.display_name == "(no display name)"


def test_to_assignment_summary_uses_member_display_name():
    member = User(id="p1", display_name="Jane Doe")
    summary = _to_assignment_summary(member)
    assert summary.principal_id == "p1"
    assert summary.principal_display_name == "Jane Doe"


def test_to_assignment_summary_falls_back_to_member_id():
    member = User(id="p2", display_name=None)
    summary = _to_assignment_summary(member)
    assert summary.principal_display_name == "p2"
