"""Encrypted-at-rest MSAL token cache backed by the OS credential store."""

from __future__ import annotations

import keyring
from msal import SerializableTokenCache

_SERVICE_NAME = "GraphicalCloudManager"


class KeyringTokenCache(SerializableTokenCache):
    """MSAL token cache persisted via `keyring` (Credential Manager / Keychain / Secret Service).

    One cache per connection profile, so multiple tenants can be signed into
    without their refresh tokens overwriting each other.
    """

    def __init__(self, profile_name: str) -> None:
        super().__init__()
        self._profile_name = profile_name
        existing = keyring.get_password(_SERVICE_NAME, profile_name)
        if existing:
            self.deserialize(existing)

    def persist_if_changed(self) -> None:
        """Call after every MSAL token acquisition; MSAL sets `has_state_changed`
        when it minted or refreshed a token, so this only writes when needed."""
        if self.has_state_changed:
            keyring.set_password(_SERVICE_NAME, self._profile_name, self.serialize())
            self.has_state_changed = False

    def clear(self) -> None:
        try:
            keyring.delete_password(_SERVICE_NAME, self._profile_name)
        except keyring.errors.PasswordDeleteError:
            pass
