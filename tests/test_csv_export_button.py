"""Tests for the shared CsvExportButton widget: the "nothing to export"
guard (no dialog shown, no crash when rows are empty) and that it inherits
AccessibleButton's accessible-name enforcement.

`_on_clicked` is an `asyncSlot` -- calling it directly returns a Task, which
must be awaited (matching how the rest of the codebase drives its own
asyncSlot handlers in tests), rather than relying on `.click()` to run it
synchronously through Qt's event loop.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel

from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.csv_export_button import CsvExportButton


def test_csv_export_button_is_an_accessible_button(qtbot):
    label = QLabel()
    qtbot.addWidget(label)
    button = CsvExportButton(lambda: (["A"], []), label)
    qtbot.addWidget(button)

    assert isinstance(button, AccessibleButton)
    assert button.accessibleName()


@pytest.mark.asyncio
async def test_csv_export_button_reports_nothing_to_export_without_dialog(qtbot):
    label = QLabel()
    qtbot.addWidget(label)
    button = CsvExportButton(lambda: (["A"], []), label)
    qtbot.addWidget(button)

    await button._on_clicked()

    assert label.text() == "Nothing to export."
