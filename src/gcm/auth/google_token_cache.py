"""Encrypted-at-rest Google OAuth token cache backed by the OS credential store.

Mirrors token_cache.py's KeyringTokenCache, but google.oauth2.credentials
doesn't have MSAL's SerializableTokenCache base to hook into -- there's no
has_state_changed flag, so this just serializes/deserializes a Credentials
object to/from JSON directly around each load/save instead.
"""

from __future__ import annotations

import json

import keyring
from google.oauth2.credentials import Credentials

_SERVICE_NAME = "GraphicalCloudManagerGoogle"


class GoogleTokenCache:
    """One cache per connection profile, so multiple Workspace domains can be
    signed into without their refresh tokens overwriting each other."""

    def __init__(self, profile_name: str) -> None:
        self._profile_name = profile_name

    def load(self) -> Credentials | None:
        existing = keyring.get_password(_SERVICE_NAME, self._profile_name)
        if not existing:
            return None
        return Credentials.from_authorized_user_info(json.loads(existing))

    def save(self, creds: Credentials) -> None:
        keyring.set_password(_SERVICE_NAME, self._profile_name, creds.to_json())

    def clear(self) -> None:
        try:
            keyring.delete_password(_SERVICE_NAME, self._profile_name)
        except keyring.errors.KeyringError:
            # Same reasoning as KeyringTokenCache.clear(): a locked keychain or
            # an already-missing entry shouldn't block sign-out from
            # completing on our side.
            pass
