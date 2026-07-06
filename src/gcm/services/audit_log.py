"""Local write-operation audit log (docs/DESIGN.md section 8): every write
this app makes to a tenant is recorded here, so an admin can review what
happened. This is a client-side convenience log, not a replacement for
Entra/Intune/Exchange's own audit logs, which remain authoritative.

Never records credentials: callers pass only fields that are already safe
to display. There is deliberately no generic "log the call arguments"
wrapper -- that would risk a method like reset_password() having its
password argument captured. Every call site names its own safe fields.

Stored as JSON Lines (one compact JSON object per line) so appending never
requires rewriting prior entries, and a reader from a future version that
adds new fields can still parse old lines (unknown/missing keys are simply
defaulted). Capped at a bounded number of entries so the file can't grow
unbounded on a long-lived install.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gcm.config import audit_log_path

_MAX_ENTRIES = 5000

_actor = "unknown"


@dataclass
class AuditEntry:
    timestamp: str
    actor: str
    action: str
    target_type: str
    target_id: str
    target_display_name: str
    result: str  # "success" | "failure"
    error: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditEntry:
        return cls(
            timestamp=data.get("timestamp", ""),
            actor=data.get("actor", ""),
            action=data.get("action", ""),
            target_type=data.get("target_type", ""),
            target_id=data.get("target_id", ""),
            target_display_name=data.get("target_display_name", ""),
            result=data.get("result", "unknown"),
            error=data.get("error"),
            before=data.get("before"),
            after=data.get("after"),
        )


def set_actor(username: str) -> None:
    """Called once, right after a successful sign-in."""
    global _actor
    _actor = username


def record(
    action: str,
    target_type: str,
    target_id: str,
    target_display_name: str,
    *,
    result: str,
    error: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        actor=_actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_display_name=target_display_name,
        result=result,
        error=error,
        before=before,
        after=after,
    )
    path = audit_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
    _trim_if_needed(path)


def _trim_if_needed(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > _MAX_ENTRIES:
        path.write_text("\n".join(lines[-_MAX_ENTRIES:]) + "\n", encoding="utf-8")


def read_all() -> list[AuditEntry]:
    path = audit_log_path()
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue  # skip a corrupted line rather than failing the whole read
        entries.append(AuditEntry.from_dict(data))
    return entries
