"""Shared "Export CSV..." button used by every exportable page (Users,
Groups, Licensing, Devices, Sign-in logs, Intune, Audit log). Centralizes
the file-picker + background-write + feedback pattern so no page duplicates
CSV logic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence

from PySide6.QtWidgets import QFileDialog, QLabel, QWidget
from qasync import asyncSlot

from gcm.services import csv_io
from gcm.ui.widgets.accessible_button import AccessibleButton

RowSource = Callable[[], tuple[Sequence[str], Sequence[Sequence[object]]]]


class CsvExportButton(AccessibleButton):
    """`row_source` is called at click time and must return
    `(headers, rows)`. Keeping it a callback (rather than a fixed snapshot
    passed in up front) means the export always reflects whatever's
    currently loaded in the page's table, without this widget needing to
    know how that page stores its data.
    """

    def __init__(
        self,
        row_source: RowSource,
        status_label: QLabel,
        *,
        default_filename: str = "export.csv",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Export &CSV...", parent)
        self._row_source = row_source
        self._status_label = status_label
        self._default_filename = default_filename
        self.clicked.connect(self._on_clicked)

    @asyncSlot()
    async def _on_clicked(self) -> None:
        headers, rows = self._row_source()
        if not rows:
            self._status_label.setText("Nothing to export.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", self._default_filename, "CSV files (*.csv)"
        )
        if not path:
            return
        loop = asyncio.get_event_loop()
        try:
            row_count = await loop.run_in_executor(None, csv_io.export_rows, path, headers, rows)
        except Exception as exc:
            self._status_label.setText(f"Couldn't export CSV: {exc}")
            return
        self._status_label.setText(f"Exported {row_count} row(s) to {path}.")
