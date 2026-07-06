"""Confirmation prompt for destructive actions.

docs/DESIGN.md section 8 requires these to name the specific object being
affected rather than a generic "Are you sure?" -- callers should always
build `message` with the actual name(s) involved.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def confirm_destructive(parent: QWidget, title: str, message: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes
