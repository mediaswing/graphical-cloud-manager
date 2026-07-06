"""Confirmation prompts for destructive/high-impact actions.

docs/DESIGN.md section 8 requires these to name the specific object being
affected rather than a generic "Are you sure?" -- callers should always
build `message` with the actual name(s) involved.

Two strengths: `confirm_destructive` (a plain Yes/No) for reversible or
lower-impact actions, and `confirm_irreversible` (type-the-name-to-confirm)
for ones that can't be undone -- e.g. deleting a user. The stronger prompt
exists specifically so a reflexive click can't trigger something permanent.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)


def confirm_destructive(parent: QWidget, title: str, message: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes


class _TypeToConfirmDialog(QDialog):
    def __init__(self, title: str, message: str, type_to_confirm: str, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setAccessibleName(title)
        self._type_to_confirm = type_to_confirm

        layout = QVBoxLayout(self)

        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setAccessibleName("Confirmation message")
        layout.addWidget(message_label)

        prompt_label = QLabel(f'Type "{type_to_confirm}" to confirm:')
        prompt_label.setWordWrap(True)
        layout.addWidget(prompt_label)

        self.confirm_edit = QLineEdit()
        self.confirm_edit.setAccessibleName(f'Type "{type_to_confirm}" to confirm')
        self.confirm_edit.textChanged.connect(self._update_ok_enabled)
        prompt_label.setBuddy(self.confirm_edit)
        layout.addWidget(self.confirm_edit)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setAccessibleName("Confirm")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setAccessibleName("Cancel")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._update_ok_enabled()

    def _update_ok_enabled(self) -> None:
        matches = self.confirm_edit.text() == self._type_to_confirm
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(matches)


def confirm_irreversible(parent: QWidget, title: str, message: str, *, type_to_confirm: str) -> bool:
    """Requires typing `type_to_confirm` (typically the target's display
    name) exactly before the confirm button is even enabled -- for actions
    that can't be undone, where a plain Yes/No is too easy to click past."""
    dialog = _TypeToConfirmDialog(title, message, type_to_confirm, parent)
    return dialog.exec() == QDialog.DialogCode.Accepted
