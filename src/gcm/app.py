"""Application entry point: wires the Qt event loop to asyncio via qasync so
Graph SDK calls (async/httpx-based) never block the UI thread."""

from __future__ import annotations

import asyncio
import sys

import qasync
from PySide6.QtWidgets import QApplication

from gcm.services.error_log import configure_logging, log_unhandled_exception
from gcm.ui.main_window import MainWindow


def main() -> int:
    configure_logging()
    sys.excepthook = log_unhandled_exception

    app = QApplication(sys.argv)
    app.setApplicationName("Graphical Cloud Manager")

    event_loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(event_loop)

    window = MainWindow()
    window.resize(900, 600)
    window.show()

    # Registered only once the window exists: an asyncio-level exception
    # (one an @asyncSlot's own try/except didn't catch) both logs, via
    # error_log.log_asyncio_exception, and surfaces a notification --
    # otherwise a background task failing would be invisible until someone
    # thought to check Help > Open Error Log.
    event_loop.set_exception_handler(window.on_asyncio_exception)

    with event_loop:
        return event_loop.run_forever()


if __name__ == "__main__":
    sys.exit(main())
