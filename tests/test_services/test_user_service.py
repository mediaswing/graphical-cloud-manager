"""Unit test for UserService's Graph-model-to-dataclass conversion. Doesn't
touch the network -- constructs a real msgraph User model directly."""

from __future__ import annotations

from msgraph.generated.models.user import User

from gcm.services.user_service import _to_summary


def test_to_summary_maps_fields():
    user = User(
        id="u1",
        display_name="Jane Doe",
        user_principal_name="jane@contoso.com",
        mail="jane@contoso.com",
        account_enabled=True,
    )
    summary = _to_summary(user)
    assert summary.id == "u1"
    assert summary.display_name == "Jane Doe"
    assert summary.user_principal_name == "jane@contoso.com"
    assert summary.account_enabled is True


def test_to_summary_falls_back_to_placeholder_display_name():
    user = User(id="u2", display_name=None, user_principal_name="x@contoso.com")
    summary = _to_summary(user)
    assert summary.display_name == "(no display name)"
    assert summary.account_enabled is False
