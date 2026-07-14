"""Application-wide error logging: uncaught exceptions, from both the Qt/
sync side (sys.excepthook) and the asyncio/qasync side (an async slot whose
own try/except didn't catch something), are logged here instead of
disappearing to stderr or a silently-swallowed asyncio warning.

This is a different, broader net than services/audit_log.py's audit trail:
audit_log only records explicit write-action attempts, at their own call
sites, that already anticipated failure. This catches whatever *wasn't*
anticipated -- a bug in this app, or an unexpected shape of data from
Microsoft/Google -- so it isn't lost. It deliberately doesn't duplicate
audit_log's entries; a service method that already reports its own failure
there has nothing new to add here.

A rotating file handler bounds the log's size, the same bounded-growth
goal as audit_log's own trim-on-write, just via the stdlib's built-in
mechanism instead of a hand-rolled one.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from types import TracebackType

from gcm.config import error_log_path

_LOGGER_NAME = "gcm"
_MAX_BYTES = 2_000_000
_BACKUP_COUNT = 3

_logger = logging.getLogger(_LOGGER_NAME)


def configure_logging() -> None:
    """Call once, at startup. Idempotent -- safe to call again (e.g. from a
    test) without installing a duplicate handler each time."""
    if _logger.handlers:
        return
    path = error_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _logger.addHandler(handler)
    _logger.setLevel(logging.WARNING)


def log_unhandled_exception(
    exc_type: type[BaseException], exc_value: BaseException, exc_tb: TracebackType | None
) -> None:
    """Installed as sys.excepthook -- catches anything raised on the main
    thread outside of Qt's own event handling (or that Qt re-raises)."""
    if issubclass(exc_type, KeyboardInterrupt):
        # An intentional Ctrl+C during a debug run, not a bug worth logging.
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    _logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))


def log_asyncio_exception(loop, context: dict) -> None:
    """Installed via event_loop.set_exception_handler(...) -- catches
    whatever an @asyncSlot coroutine's own try/except didn't, which
    qasync/asyncio would otherwise only print to stderr and lose."""
    exc = context.get("exception")
    message = context.get("message", "Unhandled error in the event loop")
    if exc is not None:
        _logger.error("Unhandled asyncio exception: %s", message, exc_info=exc)
    else:
        _logger.error("Unhandled asyncio exception: %s", message)
