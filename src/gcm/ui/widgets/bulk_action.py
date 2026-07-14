"""Runs an async action across a bulk selection without letting one failure
silently abort the rest of the batch.

Every bulk enable/disable/delete handler used to run `for item in items:
await action(item)` inside a single try/except -- the first failure raised
out of the loop, so anything after it in the selection was never attempted,
and the resulting error message gave no indication of which items (if any)
actually succeeded before that point.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from gcm.services.graph_errors import friendly_error_message

T = TypeVar("T")


async def run_bulk_action(
    items: list[T],
    action: Callable[[T], Awaitable[None]],
    *,
    display_name: Callable[[T], str],
    format_error: Callable[[Exception], str] = friendly_error_message,
) -> tuple[int, list[tuple[str, str]]]:
    """Await `action(item)` for every item, even if earlier ones raise.

    `format_error` defaults to Graph's friendly_error_message, but callers
    working against a different backend (e.g. Google's
    services.google_errors.friendly_google_error) can pass their own --
    this helper has no provider-specific logic of its own.

    Returns (succeeded_count, failures), where failures is a list of
    (display_name, formatted error) pairs for each item that raised.
    """
    succeeded = 0
    failures: list[tuple[str, str]] = []
    for item in items:
        try:
            await action(item)
            succeeded += 1
        except Exception as exc:  # noqa: BLE001 - collected, not swallowed
            failures.append((display_name(item), format_error(exc)))
    return succeeded, failures


def summarize_bulk_failures(total: int, succeeded: int, failures: list[tuple[str, str]]) -> str:
    """A message body naming exactly what succeeded and what didn't, for the
    common case of showing it in a QMessageBox.critical after run_bulk_action."""
    detail = "; ".join(f"{name} ({error})" for name, error in failures)
    return f"{succeeded} of {total} succeeded.\n\nFailed: {detail}"
