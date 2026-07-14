"""Local configuration: which Entra tenant/app registration and which Google
Workspace OAuth client to sign in against. Stored outside the repo, in an
OS-standard per-user config directory, since it's environment-specific
rather than part of the app's source (docs/DESIGN.md section 4 covers the
auth model this feeds into). Both providers' settings live in one
config.toml, under top-level keys for Microsoft and a [google] table for
Google, so there's a single "where are my settings" answer for the admin.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

_APP_DIR_NAME = "GraphicalCloudManager"


@dataclass
class AppConfig:
    client_id: str
    tenant_id: str = "organizations"

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}"


@dataclass
class GoogleConfig:
    """The Google Workspace counterpart to AppConfig. client_id/client_secret
    are an OAuth 2.0 "Desktop app" client used for interactive Directory API
    sign-in (Users/Groups/Devices); service_account_json_path is optional and
    only needed for mailbox admin actions, which require domain-wide
    delegation rather than a per-admin interactive consent."""

    client_id: str
    client_secret: str = ""
    service_account_json_path: str = ""


def _app_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / _APP_DIR_NAME


def config_path() -> Path:
    override = os.environ.get("GCM_CONFIG_PATH")
    if override:
        return Path(override)
    return _app_dir() / "config.toml"


def error_log_path() -> Path:
    override = os.environ.get("GCM_ERROR_LOG_PATH")
    if override:
        return Path(override)
    return _app_dir() / "error.log"


def audit_log_path() -> Path:
    override = os.environ.get("GCM_AUDIT_LOG_PATH")
    if override:
        return Path(override)
    return _app_dir() / "audit.jsonl"


def _load_raw() -> dict:
    path = config_path()
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _write_raw(data: dict) -> None:
    """Both save_config() and save_google_config() go through this, each
    read-modify-writing the whole file via _load_raw() first -- otherwise
    saving one provider's settings would silently wipe out the other's,
    since they share a single config.toml."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if data.get("client_id"):
        lines.append(f'client_id = "{data["client_id"]}"')
        lines.append(f'tenant_id = "{data.get("tenant_id") or "organizations"}"')
    google = data.get("google")
    if google and google.get("client_id"):
        lines.append("")
        lines.append("[google]")
        lines.append(f'client_id = "{google["client_id"]}"')
        lines.append(f'client_secret = "{google.get("client_secret", "")}"')
        lines.append(
            f'service_account_json_path = "{google.get("service_account_json_path", "")}"'
        )
    path.write_text("\n".join(lines) + "\n")


def load_config() -> AppConfig | None:
    """Returns None if no config file exists yet, or it's missing a client_id --
    callers should treat that as "not configured" and prompt the user, not as
    an error."""
    data = _load_raw()
    client_id = data.get("client_id")
    if not client_id:
        return None
    return AppConfig(client_id=client_id, tenant_id=data.get("tenant_id") or "organizations")


def save_config(config: AppConfig) -> None:
    data = _load_raw()
    data["client_id"] = config.client_id
    data["tenant_id"] = config.tenant_id
    _write_raw(data)


def load_google_config() -> GoogleConfig | None:
    """Returns None if no [google] table exists yet, or it's missing a
    client_id -- same "not configured" convention as load_config()."""
    data = _load_raw()
    google = data.get("google", {})
    client_id = google.get("client_id")
    if not client_id:
        return None
    return GoogleConfig(
        client_id=client_id,
        client_secret=google.get("client_secret", ""),
        service_account_json_path=google.get("service_account_json_path", ""),
    )


def save_google_config(config: GoogleConfig) -> None:
    data = _load_raw()
    data["google"] = {
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "service_account_json_path": config.service_account_json_path,
    }
    _write_raw(data)
