"""Delegated (interactive) sign-in against a customer's Google Workspace
domain via OAuth 2.0.

The app acts as an OAuth "Desktop app" client (client ID + secret, no
platform-verified redirect beyond the http://localhost loopback) that opens a
system browser and a local redirect listener -- the Google equivalent of
auth_manager.py's MSAL public-client flow. Each customer's admin signs in
with their own Workspace admin account and acts with their own Directory API
permissions; there is no tenant-wide admin-consent step here the way there is
for the Graph app, since Google grants these scopes per signed-in user.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from gcm.auth.google_token_cache import GoogleTokenCache
from gcm.config import GoogleConfig

# Requested unconditionally, on every sign-in. "openid"/userinfo.email are
# only there so sign-in can show *which* admin is connected (see
# _account_email below) -- they grant no directory access themselves. A
# single device scope pair covers both chromeosdevices and mobiledevices;
# Google doesn't split those into separate scopes the way Intune/Exchange
# have their own Graph permissions.
CORE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/admin.directory.user",
    "https://www.googleapis.com/auth/admin.directory.group",
    "https://www.googleapis.com/auth/admin.directory.group.member",
    "https://www.googleapis.com/auth/admin.directory.device.mobile",
    "https://www.googleapis.com/auth/admin.directory.device.chromeos",
    # Read-only access to the Reports API's login/admin activity feeds --
    # covers Google Sign-in logs and Google Admin audit log, the same way
    # AuditLog.Read.All covers Microsoft's Sign-in logs page.
    "https://www.googleapis.com/auth/admin.reports.audit.readonly",
]


@dataclass
class GoogleAuthResult:
    access_token: str
    account_email: str
    scopes: list[str] = field(default_factory=list)


def _account_email(creds: Credentials) -> str:
    """Best-effort read of the signed-in admin's email out of the ID token's
    claims, purely for display (e.g. the "Connected to ..." status label) --
    not verified/decoded as an auth check, since Credentials was only just
    minted moments ago by our own flow over TLS."""
    id_token = getattr(creds, "id_token", None)
    if not id_token:
        return "unknown"
    try:
        payload = id_token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        return claims.get("email", "unknown")
    except Exception:
        return "unknown"


class GoogleAuthManager:
    """One GoogleAuthManager per connection profile (i.e. per Workspace
    domain the admin manages) -- same one-per-profile shape as
    auth.AuthManager, keyed the same way in the OS keyring."""

    def __init__(self, profile_name: str, config: GoogleConfig) -> None:
        self.profile_name = profile_name
        self._config = config
        self._cache = GoogleTokenCache(profile_name)
        self._credentials: Credentials | None = None

    @property
    def credentials(self) -> Credentials | None:
        """The live Credentials object, for handing to googleapiclient's
        build() directly -- unlike the Graph SDK, googleapiclient has no
        async credential adapter to wrap; it self-refreshes an expired
        Credentials in place using the client_id/secret/token_uri already
        embedded in it, as long as sign_in_interactive/acquire_token_silent
        was called first."""
        return self._credentials

    def sign_in_interactive(self, scopes: list[str] | None = None) -> GoogleAuthResult:
        """Interactive browser sign-in via a local loopback redirect. Call
        once per profile; subsequent acquisitions should prefer
        acquire_token_silent."""
        scopes = scopes or CORE_SCOPES
        client_config = {
            "installed": {
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, scopes=scopes)
        creds = flow.run_local_server(port=0)
        self._credentials = creds
        self._cache.save(creds)
        return self._to_auth_result(creds, scopes)

    def acquire_token_silent(self, scopes: list[str] | None = None) -> GoogleAuthResult | None:
        """Refresh a token from the stored credential without prompting.
        Returns None if there's nothing cached or the refresh token has been
        revoked/expired -- callers should fall back to
        sign_in_interactive."""
        creds = self._cache.load()
        if creds is None:
            return None
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                return None
            self._cache.save(creds)
        elif not creds.valid:
            return None
        self._credentials = creds
        return self._to_auth_result(creds, scopes or CORE_SCOPES)

    def sign_out(self) -> None:
        self._credentials = None
        self._cache.clear()

    @staticmethod
    def _to_auth_result(creds: Credentials, scopes: list[str]) -> GoogleAuthResult:
        return GoogleAuthResult(
            access_token=creds.token,
            account_email=_account_email(creds),
            scopes=scopes,
        )
