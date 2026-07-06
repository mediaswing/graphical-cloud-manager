"""Turns a Graph SDK exception into a message a signed-in admin can act on.

The whole point of delegated auth (docs/DESIGN.md section 4) is that this
app runs with whatever privilege the signed-in admin actually has -- which
means every write action can legitimately fail with "you're not allowed to
do this," and that has to read as an explanation, not a stack trace.
"""

from __future__ import annotations

from kiota_abstractions.api_error import APIError

_KNOWN_CODES = {
    "Authorization_RequestDenied": (
        "You don't have permission to do this. It typically requires a role "
        "like User Administrator, Groups Administrator, or Global "
        "Administrator, and the app's permissions must be admin-consented "
        "for this tenant."
    ),
    "Request_ResourceNotFound": "That item couldn't be found -- it may have already been deleted.",
}


def friendly_error_message(exc: Exception) -> str:
    if isinstance(exc, APIError):
        code = getattr(getattr(exc, "error", None), "code", None)
        message = getattr(getattr(exc, "error", None), "message", None)
        if code in _KNOWN_CODES:
            return _KNOWN_CODES[code]
        if getattr(exc, "response_status_code", None) == 403:
            return _KNOWN_CODES["Authorization_RequestDenied"]
        if message:
            return message
    return str(exc)
