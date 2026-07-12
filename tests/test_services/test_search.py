"""Unit test for the $search term escaper used by user/group/device_service.

A $search phrase is wrapped in double quotes (e.g. "displayName:Jane"); an
unescaped " in the search term would otherwise break out of that phrase and
send Graph a malformed query."""

from __future__ import annotations

from gcm.graph.search import escape_search_term


def test_plain_term_is_unchanged():
    assert escape_search_term("Jane Doe") == "Jane Doe"


def test_embedded_double_quote_is_escaped():
    assert escape_search_term('Jane "JJ" Doe') == 'Jane \\"JJ\\" Doe'
