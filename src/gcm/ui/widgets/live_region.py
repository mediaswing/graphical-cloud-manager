"""Proactive screen-reader announcements for transient status changes.

Setting a label's text alone doesn't make most screen readers announce it
unprompted -- the user only hears it if they happen to move focus there.
Firing an Alert accessibility event tells the platform accessibility layer
(AT-SPI/UIA/NSAccessibility) to announce it immediately, the same way a web
page's `aria-live="assertive"` region would.
"""

from __future__ import annotations

from PySide6.QtGui import QAccessible, QAccessibleEvent
from PySide6.QtWidgets import QLabel


def announce(label: QLabel, message: str) -> None:
    label.setText(message)
    label.setAccessibleName(message)
    if QAccessible.isActive():
        QAccessible.updateAccessibility(QAccessibleEvent(label, QAccessible.Event.Alert))
