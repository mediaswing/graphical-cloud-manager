"""Builds an Admin SDK Directory API client from our GoogleAuthManager.

googleapiclient's Resource objects make synchronous/blocking HTTP calls --
unlike msgraph-sdk there's no async credential protocol to hook a
non-blocking token refresh into (see graph/client.py's _AuthManagerCredential
for that side). Instead, every service method built on top of this client
must wrap its own `.execute()` calls in `loop.run_in_executor(...)` to stay
off the qasync event loop.
"""

from __future__ import annotations

from googleapiclient.discovery import Resource, build

from gcm.auth.google_auth_manager import GoogleAuthManager


def build_directory_client(auth_manager: GoogleAuthManager) -> Resource:
    """Construct an Admin SDK Directory API client backed by our interactive
    Google sign-in. `auth_manager.credentials` self-refreshes in place when
    expired (it carries its own client_id/secret/token_uri), so this client
    stays usable across the whole signed-in session without going back
    through GoogleAuthManager again.

    `cache_discovery=False` avoids googleapiclient's file-based discovery
    cache, which both warns on modern oauth2client-less installs and -- more
    importantly for a packaged app -- would otherwise try to write to a
    cache directory that may not exist/be writable under PyInstaller.
    """
    return build(
        "admin", "directory_v1", credentials=auth_manager.credentials, cache_discovery=False
    )


def build_reports_client(auth_manager: GoogleAuthManager) -> Resource:
    """Construct an Admin SDK Reports API client (login/admin activity feeds)
    from the same signed-in credentials as build_directory_client -- Reports
    is a separate API/service name from Directory, but both are read under
    the one interactive Google sign-in, unlike Mailbox admin's separate
    service-account credential."""
    return build(
        "admin", "reports_v1", credentials=auth_manager.credentials, cache_discovery=False
    )
