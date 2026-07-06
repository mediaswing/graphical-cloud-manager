"""A QPushButton that refuses to be created without an accessible name.

Cheap, local enforcement of docs/DESIGN.md section 7 ("Accessible names on
everything") at the point buttons are created, rather than relying solely on
the whole-tree audit test to catch a missing label after the fact.
"""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget


class AccessibleButton(QPushButton):
    def __init__(
        self,
        text: str,
        parent: QWidget | None = None,
        *,
        accessible_description: str | None = None,
    ) -> None:
        super().__init__(text, parent)
        # QWidget.accessibleName() is a distinct, independently-set string --
        # Qt does not populate it from the visible label automatically, so
        # every button must set it explicitly (stripping the `&` mnemonic
        # marker, which a screen reader shouldn't read literally).
        label = text.replace("&", "").strip()
        if not label and not accessible_description:
            raise ValueError("AccessibleButton requires visible text or an accessible_description")
        self.setAccessibleName(label or accessible_description)
        if accessible_description:
            self.setAccessibleDescription(accessible_description)
