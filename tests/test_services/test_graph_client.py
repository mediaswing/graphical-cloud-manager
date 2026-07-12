"""_AuthManagerCredential.get_token must be async and must never call MSAL
directly on the calling (event loop) thread -- see graph/client.py's
module docstring for why a sync get_token would freeze the UI on every
single Graph request."""

from __future__ import annotations

import asyncio
import threading

import pytest

from gcm.auth.auth_manager import CORE_SCOPES
from gcm.graph.client import _AuthManagerCredential, build_graph_client


class _FakeAuthManager:
    def __init__(self, silent_result=None):
        self._silent_result = silent_result
        self.silent_calls: list[list[str]] = []
        self.interactive_calls: list[list[str]] = []
        self.threads_used: set[int] = set()

    def acquire_token_silent(self, scopes):
        self.threads_used.add(threading.get_ident())
        self.silent_calls.append(scopes)
        return self._silent_result

    def sign_in_interactive(self, scopes):
        self.threads_used.add(threading.get_ident())
        self.interactive_calls.append(scopes)
        return type("Result", (), {"access_token": "interactive-token"})()


@pytest.mark.asyncio
async def test_get_token_is_awaitable_and_runs_off_the_event_loop_thread():
    result = type("Result", (), {"access_token": "cached-token"})()
    auth_manager = _FakeAuthManager(silent_result=result)
    credential = _AuthManagerCredential(auth_manager)

    coro = credential.get_token("https://graph.microsoft.com/.default")
    assert asyncio.iscoroutine(coro)
    token = await coro

    assert token.token == "cached-token"
    assert auth_manager.silent_calls == [["https://graph.microsoft.com/.default"]]
    assert threading.get_ident() not in auth_manager.threads_used


@pytest.mark.asyncio
async def test_get_token_falls_back_to_interactive_on_cache_miss():
    auth_manager = _FakeAuthManager(silent_result=None)
    credential = _AuthManagerCredential(auth_manager)

    token = await credential.get_token("https://graph.microsoft.com/.default")

    assert token.token == "interactive-token"
    assert auth_manager.interactive_calls == [["https://graph.microsoft.com/.default"]]


@pytest.mark.asyncio
async def test_close_and_async_context_manager_are_noops():
    credential = _AuthManagerCredential(_FakeAuthManager())
    await credential.close()
    async with credential as ctx:
        assert ctx is credential


def test_build_graph_client_passes_core_scopes_so_the_token_cache_is_reused():
    client = build_graph_client(_FakeAuthManager())
    token_provider = client.request_adapter._authentication_provider.access_token_provider
    assert token_provider._scopes == CORE_SCOPES
