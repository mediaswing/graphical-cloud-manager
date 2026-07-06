"""Unit tests for the local audit log: JSONL read/write, the size cap, and
that no credential-shaped data leaks through the module's own API surface.
Uses GCM_AUDIT_LOG_PATH to point at a tmp_path file so tests never touch a
real user's audit log."""

from __future__ import annotations

import json

from gcm.services import audit_log


def test_record_then_read_all_round_trips(tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    audit_log.set_actor("admin@contoso.com")

    audit_log.record(
        "delete_user", "User", "u1", "Jane Doe", result="success", after={"deleted": True}
    )

    entries = audit_log.read_all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.actor == "admin@contoso.com"
    assert entry.action == "delete_user"
    assert entry.target_type == "User"
    assert entry.target_id == "u1"
    assert entry.target_display_name == "Jane Doe"
    assert entry.result == "success"
    assert entry.after == {"deleted": True}
    assert entry.error is None


def test_record_failure_captures_error(tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    audit_log.set_actor("admin@contoso.com")

    audit_log.record(
        "delete_user", "User", "u2", "John Roe", result="failure", error="Insufficient privileges"
    )

    entries = audit_log.read_all()
    assert entries[0].result == "failure"
    assert entries[0].error == "Insufficient privileges"


def test_read_all_returns_empty_list_when_no_log_file_exists(tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "does-not-exist.jsonl"))
    assert audit_log.read_all() == []


def test_read_all_skips_corrupted_lines(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(path))
    path.write_text(
        json.dumps({"timestamp": "t", "actor": "a", "action": "x", "target_type": "User",
                     "target_id": "1", "target_display_name": "Jane", "result": "success"})
        + "\nnot valid json\n",
        encoding="utf-8",
    )

    entries = audit_log.read_all()

    assert len(entries) == 1
    assert entries[0].action == "x"


def test_from_dict_tolerates_missing_fields_for_forward_compatibility():
    entry = audit_log.AuditEntry.from_dict({"action": "delete_user"})
    assert entry.action == "delete_user"
    assert entry.actor == ""
    assert entry.before is None


def test_entries_are_capped_at_max_size(tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setattr(audit_log, "_MAX_ENTRIES", 3)

    for i in range(5):
        audit_log.record("action", "User", str(i), f"User {i}", result="success")

    entries = audit_log.read_all()
    assert len(entries) == 3
    # the oldest entries are dropped, not the newest
    assert [e.target_id for e in entries] == ["2", "3", "4"]
