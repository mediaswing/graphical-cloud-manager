"""Re-exports AuditEntry from services.audit_log so the UI layer can import
it from `models`, like every other page's data class."""

from __future__ import annotations

from gcm.services.audit_log import AuditEntry

__all__ = ["AuditEntry"]
