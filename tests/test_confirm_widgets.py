"""Tests for the shared confirmation dialogs, particularly
confirm_irreversible's type-to-confirm gate: the OK button must stay
disabled until the exact target name has been typed, so a reflexive click
can't trigger an irreversible action."""

from __future__ import annotations

from PySide6.QtWidgets import QDialogButtonBox

from gcm.ui.widgets.confirm import _TypeToConfirmDialog


def test_ok_button_disabled_until_exact_text_is_typed(qtbot):
    dialog = _TypeToConfirmDialog("Delete user", "Delete Jane Doe?", "Jane Doe", None)
    qtbot.addWidget(dialog)
    ok_button = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)

    assert not ok_button.isEnabled()

    dialog.confirm_edit.setText("Jane D")
    assert not ok_button.isEnabled()

    dialog.confirm_edit.setText("Jane Doe")
    assert ok_button.isEnabled()


def test_ok_button_disabled_again_if_text_no_longer_matches(qtbot):
    dialog = _TypeToConfirmDialog("Delete user", "Delete Jane Doe?", "Jane Doe", None)
    qtbot.addWidget(dialog)
    ok_button = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)

    dialog.confirm_edit.setText("Jane Doe")
    assert ok_button.isEnabled()

    dialog.confirm_edit.setText("Jane Doe!")
    assert not ok_button.isEnabled()


def test_dialog_controls_have_accessible_names(qtbot):
    dialog = _TypeToConfirmDialog("Delete user", "Delete Jane Doe?", "Jane Doe", None)
    qtbot.addWidget(dialog)

    assert dialog.confirm_edit.accessibleName()
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).accessibleName()
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel).accessibleName()
