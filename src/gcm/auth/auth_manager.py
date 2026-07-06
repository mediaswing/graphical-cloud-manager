"""Delegated (interactive) sign-in against a customer's Entra tenant via MSAL.

The app is a public client (no client secret) registered as multi-tenant.
Each customer's admin performs a one-time admin-consent grant; after that,
users of this tool sign in with their own account and act with their own
directory permissions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import msal

from gcm.auth.token_cache import KeyringTokenCache
from gcm.config import AppConfig

# Scopes requested unconditionally, on every sign-in. Device management and
# audit-log reading don't require any particular tenant licensing to
# *request* -- only Devices always works, while sign-in logs additionally
# need the tenant to have Azure AD Premium P1+ (checked via
# TenantCapabilities.has_audit_logs, which just hides the page rather than
# gating what's requested here).
CORE_SCOPES = [
    "User.ReadWrite.All",
    "Group.ReadWrite.All",
    "Organization.Read.All",
    "Directory.ReadWrite.All",
    "RoleManagement.ReadWrite.Directory",
    "Device.ReadWrite.All",
    "AuditLog.Read.All",
    # Read-only for now -- the Intune module only lists devices this phase.
    "DeviceManagementManagedDevices.Read.All",
    # Rule-based forwarding (an inbox rule) and mailbox usage reports.
    "Mail.ReadWrite",
    "Reports.Read.All",
]

# Not yet requested anywhere: placeholders for if/when Intune grows remote
# actions (wipe/retire/sync) or configuration/app management, which would
# need write access beyond today's read-only device inventory.
INTUNE_FUTURE_WRITE_SCOPES = [
    "DeviceManagementManagedDevices.ReadWrite.All",
    "DeviceManagementConfiguration.ReadWrite.All",
    "DeviceManagementApps.ReadWrite.All",
]


@dataclass
class AuthResult:
    access_token: str
    account_username: str
    tenant_id: str
    scopes: list[str] = field(default_factory=list)


class AuthManager:
    """One AuthManager per connection profile (i.e. per tenant the admin manages)."""

    def __init__(self, profile_name: str, config: AppConfig) -> None:
        self.profile_name = profile_name
        self._cache = KeyringTokenCache(profile_name)
        self._app = msal.PublicClientApplication(
            config.client_id, authority=config.authority, token_cache=self._cache
        )

    def sign_in_interactive(self, scopes: list[str] | None = None) -> AuthResult:
        """Interactive browser sign-in. Call once per profile; subsequent
        acquisitions should prefer `acquire_token_silent`."""
        scopes = scopes or CORE_SCOPES
        result = self._app.acquire_token_interactive(scopes=scopes)
        self._cache.persist_if_changed()
        return self._to_auth_result(result, scopes)

    def acquire_token_silent(self, scopes: list[str] | None = None) -> AuthResult | None:
        """Refresh a token from cache without prompting. Returns None if the
        user needs to re-authenticate interactively (e.g. expired refresh
        token, revoked consent, added scopes not yet consented)."""
        scopes = scopes or CORE_SCOPES
        accounts = self._app.get_accounts()
        if not accounts:
            return None
        result = self._app.acquire_token_silent(scopes=scopes, account=accounts[0])
        self._cache.persist_if_changed()
        if result is None:
            return None
        return self._to_auth_result(result, scopes)

    def sign_out(self) -> None:
        for account in self._app.get_accounts():
            self._app.remove_account(account)
        self._cache.clear()

    @staticmethod
    def _to_auth_result(result: dict, scopes: list[str]) -> AuthResult:
        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "unknown error"))
            raise RuntimeError(f"Sign-in failed: {error}")
        claims = result.get("id_token_claims", {})
        return AuthResult(
            access_token=result["access_token"],
            account_username=claims.get("preferred_username", "unknown"),
            tenant_id=claims.get("tid", "unknown"),
            scopes=scopes,
        )
