"""Helpers for building Microsoft Graph `$search` query values.

A `$search` phrase is wrapped in double quotes, e.g. `"displayName:Jane"`.
An unescaped `"` inside the search term itself closes that phrase early and
produces a malformed query -- Graph returns a 400 rather than results.
"""

from __future__ import annotations


def escape_search_term(term: str) -> str:
    """Escape a literal `"` so it can't break out of a quoted $search phrase."""
    return term.replace('"', '\\"')
