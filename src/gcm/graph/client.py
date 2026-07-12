"""Thin wrapper that adapts our MSAL-based AuthManager to the credential
interface the Microsoft Graph SDK expects (azure.core's AsyncTokenCredential
protocol: an object with an `async def get_token(*scopes, **kwargs) ->
AccessToken`).

``get_token`` is async (not the sync `TokenCredential` protocol) because
kiota's ``AzureIdentityAccessTokenProvider.get_authorization_token`` awaits
it whenever the result is awaitable (see
``kiota_authentication_azure/azure_identity_access_token_provider.py``), and
it runs inline inside every Graph request -- which itself runs on the
qasync event loop. A sync `get_token` would call MSAL's blocking silent
acquisition (and, on a cache miss, its blocking interactive browser flow)
directly on that loop, freezing the whole UI for the round trip on every
single Graph call.
"""

from __future__ import annotations

import asyncio
import time

from azure.core.credentials import AccessToken
from msgraph import GraphServiceClient

from gcm.auth.auth_manager import CORE_SCOPES, AuthManager


class _AuthManagerCredential:
    """Adapts AuthManager (interactive/silent MSAL) to azure.core's
    AsyncTokenCredential protocol so it can be handed to GraphServiceClient."""

    def __init__(self, auth_manager: AuthManager) -> None:
        self._auth_manager = auth_manager

    async def get_token(self, *scopes: str, **kwargs) -> AccessToken:
        loop = asyncio.get_event_loop()
        scope_list = list(scopes)
        result = await loop.run_in_executor(
            None, self._auth_manager.acquire_token_silent, scope_list)
        if result is None:
            # Falls back to an interactive browser sign-in -- still off the
            # event loop thread, same as the initial sign-in in main_window.py.
            result = await loop.run_in_executor(
                None, self._auth_manager.sign_in_interactive, scope_list)
        # MSAL doesn't expose a hard expiry here; a short conservative TTL
        # forces re-check via acquire_token_silent (which is cheap/cached)
        # rather than risking a stale/expired token being reused.
        return AccessToken(result.access_token, int(time.time()) + 300)

    async def close(self) -> None:
        pass

    async def __aenter__(self) -> "_AuthManagerCredential":
        return self

    async def __aexit__(self, *exc_info) -> None:
        pass


def build_graph_client(auth_manager: AuthManager) -> GraphServiceClient:
    """Construct a GraphServiceClient backed by our delegated MSAL sign-in."""
    credential = _AuthManagerCredential(auth_manager)
    # Without an explicit scopes= here, kiota derives a per-request
    # ["https://graph.microsoft.com/.default"] scope from each request's
    # hostname instead of reusing CORE_SCOPES -- which is what sign-in
    # actually cached the token under -- turning every single Graph call
    # into an MSAL cache miss (and a silent-but-not-free token redemption
    # over the network) instead of a cheap cache hit.
    return GraphServiceClient(credentials=credential, scopes=CORE_SCOPES)
