"""Local configuration: which Entra tenant and app registration to sign in
against. Stored outside the repo, in an OS-standard per-user config
directory, since it's environment-specific rather than part of the app's
source (docs/DESIGN.md section 4 covers the auth model this feeds into).
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


def audit_log_path() -> Path:
    override = os.environ.get("GCM_AUDIT_LOG_PATH")
    if override:
        return Path(override)
    return _app_dir() / "audit.jsonl"


def load_config() -> AppConfig | None:
    """Returns None if no config file exists yet, or it's missing a client_id --
    callers should treat that as "not configured" and prompt the user, not as
    an error."""
    path = config_path()
    if not path.exists():
        return None
    with path.open("rb") as f:
        data = tomllib.load(f)
    client_id = data.get("client_id")
    if not client_id:
        return None
    return AppConfig(client_id=client_id, tenant_id=data.get("tenant_id") or "organizations")


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'client_id = "{config.client_id}"\n'
        f'tenant_id = "{config.tenant_id}"\n'
    )
