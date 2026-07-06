"""Thin wrapper that adapts our MSAL-based AuthManager to the credential
interface the Microsoft Graph SDK expects (azure.core's TokenCredential
protocol: an object with a `get_token(*scopes, **kwargs) -> AccessToken`)."""

from __future__ import annotations

import time

from azure.core.credentials import AccessToken
from msgraph import GraphServiceClient

from gcm.auth.auth_manager import AuthManager


class _AuthManagerCredential:
    """Adapts AuthManager (interactive/silent MSAL) to azure.core's
    TokenCredential protocol so it can be handed to GraphServiceClient."""

    def __init__(self, auth_manager: AuthManager) -> None:
        self._auth_manager = auth_manager

    def get_token(self, *scopes: str, **kwargs) -> AccessToken:
        result = self._auth_manager.acquire_token_silent(list(scopes))
        if result is None:
            result = self._auth_manager.sign_in_interactive(list(scopes))
        # MSAL doesn't expose a hard expiry here; a short conservative TTL
        # forces re-check via acquire_token_silent (which is cheap/cached)
        # rather than risking a stale/expired token being reused.
        return AccessToken(result.access_token, int(time.time()) + 300)


def build_graph_client(auth_manager: AuthManager) -> GraphServiceClient:
    """Construct a GraphServiceClient backed by our delegated MSAL sign-in."""
    credential = _AuthManagerCredential(auth_manager)
    return GraphServiceClient(credentials=credential)
