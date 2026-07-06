"""Application entry point: wires the Qt event loop to asyncio via qasync so
Graph SDK calls (async/httpx-based) never block the UI thread."""

from __future__ import annotations

import asyncio
import sys

import qasync
from PySide6.QtWidgets import QApplication

from gcm.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Graphical Cloud Manager")

    event_loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    window = MainWindow()
    window.resize(900, 600)
    window.show()

    with event_loop:
        return event_loop.run_forever()


if __name__ == "__main__":
    sys.exit(main())
