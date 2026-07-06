"""Tests for the Audit log page: table model rendering and the search/result
filters. Uses GCM_AUDIT_LOG_PATH so tests never touch a real user's log."""

from __future__ import annotations

from gcm.services import audit_log
from gcm.ui.pages.audit_log_page import AuditLogPage, AuditLogTableModel


def test_audit_log_table_model_renders_rows():
    model = AuditLogTableModel()
    model.set_entries(
        [
            audit_log.AuditEntry(
                timestamp="2026-07-06T10:00:00+00:00",
                actor="admin@contoso.com",
                action="delete_user",
                target_type="User",
                target_id="u1",
                target_display_name="Jane Doe",
                result="success",
            )
        ]
    )
    assert model.rowCount() == 1
    assert model.data(model.index(0, 1)) == "delete_user"
    assert model.data(model.index(0, 3)) == "Jane Doe"
    assert model.data(model.index(0, 4)) == "success"


def test_audit_log_page_loads_entries_on_construction(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    audit_log.set_actor("admin@contoso.com")
    audit_log.record("delete_user", "User", "u1", "Jane Doe", result="success")
    audit_log.record("create_user", "User", "u2", "John Roe", result="failure", error="denied")

    page = AuditLogPage()
    qtbot.addWidget(page)

    assert page.model.rowCount() == 2
    assert "2 of 2" in page.status_label.text()


def test_audit_log_page_filters_by_result(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    audit_log.set_actor("admin@contoso.com")
    audit_log.record("delete_user", "User", "u1", "Jane Doe", result="success")
    audit_log.record("create_user", "User", "u2", "John Roe", result="failure", error="denied")

    page = AuditLogPage()
    qtbot.addWidget(page)
    page.result_combo.setCurrentText("Failure")

    assert page.model.rowCount() == 1
    assert page.model.data(page.model.index(0, 1)) == "create_user"


def test_audit_log_page_filters_by_search_text(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    audit_log.set_actor("admin@contoso.com")
    audit_log.record("delete_user", "User", "u1", "Jane Doe", result="success")
    audit_log.record("create_user", "User", "u2", "John Roe", result="success")

    page = AuditLogPage()
    qtbot.addWidget(page)
    page.search_edit.setText("Jane")

    assert page.model.rowCount() == 1
    assert page.model.data(page.model.index(0, 3)) == "Jane Doe"


def test_audit_log_page_shows_most_recent_first(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    audit_log.set_actor("admin@contoso.com")
    audit_log.record("action_one", "User", "u1", "First", result="success")
    audit_log.record("action_two", "User", "u2", "Second", result="success")

    page = AuditLogPage()
    qtbot.addWidget(page)

    assert page.model.data(page.model.index(0, 3)) == "Second"
    assert page.model.data(page.model.index(1, 3)) == "First"
