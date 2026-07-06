"""Follows `@odata.nextLink` so a list call returns every item, not just the
first page.

Every `list_*` method in this codebase used to fetch a single page (with
`top=999`) and silently drop anything beyond it on a tenant with more items
than that. `msgraph_core.PageIterator` is Microsoft's own pagination helper
for the Kiota-generated SDK; this just wraps it so callers get a plain list
back instead of managing page state themselves.
"""

from __future__ import annotations

from typing import Any

from msgraph_core import PageIterator


async def collect_all(first_page: Any, request_adapter: Any) -> list:
    """`first_page` is the result of an initial `.get(...)` call (must have
    `.value` and `.odata_next_link`, as every Graph collection response
    does). Returns every item across all pages."""
    items: list = []

    def _collect(item: Any) -> bool:
        items.append(item)
        return True

    await PageIterator(first_page, request_adapter).iterate(_collect)
    return items
