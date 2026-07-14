"""Turns a Directory API exception into a message a signed-in admin can act
on. Mirrors graph_errors.py's role for the Microsoft side, but
googleapiclient.errors.HttpError has a different shape than Graph's OData
errors -- the status code lives on .resp.status (or .status_code on newer
googleapiclient versions) and the message body is JSON bytes in .content,
not a structured `.error` object.
"""

from __future__ import annotations

import json

from googleapiclient.errors import HttpError

_KNOWN_STATUSES = {
    403: (
        "You don't have permission to do this. It typically requires a "
        "Workspace admin role with the right Directory API privilege, and "
        "-- for mailbox actions -- domain-wide delegation authorized for "
        "this app's service account in the Admin console."
    ),
    404: "That item couldn't be found -- it may have already been deleted.",
    429: "Google is throttling this app right now. Wait a moment and try again.",
}


def _status_code(exc: HttpError) -> int | None:
    status = getattr(exc, "status_code", None)
    if status is not None:
        return status
    resp = getattr(exc, "resp", None)
    return getattr(resp, "status", None) if resp is not None else None


def _error_message(exc: HttpError) -> str | None:
    content = getattr(exc, "content", None)
    if not content:
        return None
    try:
        details = json.loads(content.decode("utf-8"))
        return details.get("error", {}).get("message")
    except Exception:
        return None


def friendly_google_error(exc: Exception) -> str:
    if isinstance(exc, HttpError):
        status = _status_code(exc)
        if status in _KNOWN_STATUSES:
            return _KNOWN_STATUSES[status]
        message = _error_message(exc)
        if message:
            return message
    return str(exc)
