"""Regression test for gcm.ui.widgets.live_region.announce().

A real user hit an AttributeError here (QAccessible.QAccessibleEvent doesn't
exist -- QAccessibleEvent is a top-level QtGui class, not nested under
QAccessible) that our other tests never caught, because they all run with
QT_QPA_PLATFORM=offscreen, where QAccessible.isActive() is always False, so
the buggy line never executed. Force isActive() to True here so the actual
alert-firing code path gets exercised in CI too.
"""

from __future__ import annotations

from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QLabel

from gcm.ui.widgets.live_region import announce


def test_announce_does_not_raise_when_accessibility_is_active(qtbot, monkeypatch):
    monkeypatch.setattr(QAccessible, "isActive", staticmethod(lambda: True))

    label = QLabel()
    qtbot.addWidget(label)

    announce(label, "Signing in to Contoso...")

    assert label.text() == "Signing in to Contoso..."
    assert label.accessibleName() == "Signing in to Contoso..."
