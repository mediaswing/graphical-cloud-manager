"""Unit tests for the shared pagination helper. No network -- fakes just
enough of Kiota's page/request-adapter shape for PageIterator to walk pages
without ever making an HTTP call.

Every existing list_* method used to fetch a single page (top=999) and
silently drop anything beyond it; this locks in that collect_all() actually
follows @odata.nextLink instead.
"""

from __future__ import annotations

import pytest

from gcm.graph.pagination import collect_all


class _FakePage:
    def __init__(self, value: list, next_link: str = "") -> None:
        self.value = value
        self.odata_next_link = next_link


class _FakeRequestAdapter:
    def __init__(self, subsequent_pages: list[_FakePage]) -> None:
        self._pages = list(subsequent_pages)

    async def send_async(self, request_info, parsable_factory, error_mapping):
        return self._pages.pop(0)


@pytest.mark.asyncio
async def test_collect_all_returns_single_page_without_extra_requests():
    first_page = _FakePage(value=["a", "b"])
    result = await collect_all(first_page, _FakeRequestAdapter([]))
    assert result == ["a", "b"]


@pytest.mark.asyncio
async def test_collect_all_follows_next_link_across_multiple_pages():
    first_page = _FakePage(value=["a", "b"], next_link="https://graph.microsoft.com/v1.0/next")
    second_page = _FakePage(value=["c"], next_link="https://graph.microsoft.com/v1.0/next2")
    third_page = _FakePage(value=["d"])
    adapter = _FakeRequestAdapter([second_page, third_page])

    result = await collect_all(first_page, adapter)

    assert result == ["a", "b", "c", "d"]


@pytest.mark.asyncio
async def test_collect_all_handles_empty_first_page():
    first_page = _FakePage(value=[])
    result = await collect_all(first_page, _FakeRequestAdapter([]))
    assert result == []
