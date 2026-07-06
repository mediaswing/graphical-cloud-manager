"""Tests for the shared impact-preview dialog: content rendering, the "not
exhaustive" disclosure always showing, and the optional type-to-confirm gate
for irreversible actions."""

from __future__ import annotations

from PySide6.QtWidgets import QDialogButtonBox, QLabel

from gcm.services.impact_preview import ImpactPreview
from gcm.ui.widgets.impact_preview_dialog import ImpactPreviewDialog


def _preview(**overrides):
    defaults = dict(
        target_id="u1",
        display_name="Jane Doe",
        user_principal_name="jane@contoso.com",
        account_enabled=True,
        license_names=["ENTERPRISEPACK"],
        group_names=["Sales Team"],
        admin_role_names=[],
        member_of_truncated=False,
        last_sign_in=None,
        last_sign_in_checked=False,
        warnings=[],
    )
    defaults.update(overrides)
    return ImpactPreview(**defaults)


def _label_text(dialog: ImpactPreviewDialog, accessible_name: str) -> str:
    for label in dialog.findChildren(QLabel):
        if label.accessibleName() == accessible_name:
            return label.text()
    raise AssertionError(f"No label with accessible name {accessible_name!r} found")


def test_dialog_shows_licenses_and_groups(qtbot):
    dialog = ImpactPreviewDialog("Delete user", "Delete this user?", _preview())
    qtbot.addWidget(dialog)

    assert "ENTERPRISEPACK" in _label_text(dialog, "Target licenses")
    assert "Sales Team" in _label_text(dialog, "Target group memberships")
    assert "Jane Doe" in _label_text(dialog, "Target identity")
    assert "Enabled" in _label_text(dialog, "Target account status")


def test_dialog_shows_not_checked_disclosure(qtbot):
    dialog = ImpactPreviewDialog("Delete user", "Delete this user?", _preview())
    qtbot.addWidget(dialog)

    note = _label_text(dialog, "What this preview does not check")
    assert "app role" in note.lower() or "not exhaustive" in note.lower() or "isn't exhaustive" in note.lower()


def test_dialog_shows_sign_in_not_available_when_not_checked(qtbot):
    dialog = ImpactPreviewDialog(
        "Delete user", "Delete this user?", _preview(last_sign_in_checked=False)
    )
    qtbot.addWidget(dialog)

    assert "not available" in _label_text(dialog, "Target last sign-in").lower()


def test_dialog_shows_actual_sign_in_time_when_checked(qtbot):
    dialog = ImpactPreviewDialog(
        "Delete user", "Delete this user?",
        _preview(last_sign_in_checked=True, last_sign_in="2026-07-01 09:00"),
    )
    qtbot.addWidget(dialog)

    assert "2026-07-01 09:00" in _label_text(dialog, "Target last sign-in")


def test_dialog_shows_warnings_when_present(qtbot):
    dialog = ImpactPreviewDialog(
        "Delete user", "Delete this user?",
        _preview(warnings=["Couldn't check licenses: timed out"]),
    )
    qtbot.addWidget(dialog)

    assert "timed out" in _label_text(dialog, "Impact preview warnings")


def test_confirm_disabled_until_typed_confirmation_matches(qtbot):
    dialog = ImpactPreviewDialog(
        "Delete user", "Delete this user?", _preview(), require_typed_confirmation=True
    )
    qtbot.addWidget(dialog)
    ok_button = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)

    assert not ok_button.isEnabled()

    dialog.confirm_edit.setText("Jane Doe")
    assert ok_button.isEnabled()


def test_confirm_enabled_immediately_without_typed_confirmation_requirement(qtbot):
    dialog = ImpactPreviewDialog(
        "Disable user", "Disable this user?", _preview(), require_typed_confirmation=False
    )
    qtbot.addWidget(dialog)
    ok_button = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)

    assert ok_button.isEnabled()
    assert dialog.confirm_edit is None
