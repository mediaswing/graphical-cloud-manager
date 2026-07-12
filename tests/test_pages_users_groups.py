"""Tests for the Users/Groups page table models and disconnected-state
behavior. Doesn't touch the network -- feeds the table models sample
dataclasses directly and checks the page's pre-sign-in state."""

from __future__ import annotations

import asyncio

import pytest
from PySide6.QtCore import Qt

from gcm.models.group import GroupMember, GroupSummary
from gcm.models.user import UserSummary
from gcm.services.impact_preview import ImpactPreview
from gcm.ui.pages import users_page as users_page_module
from gcm.ui.pages.groups_page import GroupsPage, GroupsTableModel
from gcm.ui.pages.users_page import UsersPage, UsersTableModel


def test_users_table_model_renders_rows():
    model = UsersTableModel()
    model.set_users(
        [
            UserSummary(
                id="u1",
                display_name="Jane Doe",
                user_principal_name="jane@contoso.com",
                mail="jane@contoso.com",
                account_enabled=True,
            ),
            UserSummary(
                id="u2",
                display_name="John Roe",
                user_principal_name="john@contoso.com",
                mail=None,
                account_enabled=False,
            ),
        ]
    )
    assert model.rowCount() == 2
    assert model.data(model.index(0, 0)) == "Jane Doe"
    assert model.data(model.index(0, 3)) == "Enabled"
    assert model.data(model.index(1, 3)) == "Disabled"
    assert model.data(model.index(1, 2)) == ""
    assert model.headerData(0, Qt.Orientation.Horizontal) == "Display name"


def test_groups_table_model_renders_rows():
    model = GroupsTableModel()
    model.set_groups(
        [GroupSummary(id="g1", display_name="Marketing", mail=None, group_type="Security")]
    )
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "Marketing"
    assert model.data(model.index(0, 2)) == "Security"


def test_users_page_starts_disconnected_and_disabled(qtbot):
    page = UsersPage()
    qtbot.addWidget(page)

    assert not page.table.isEnabled()
    assert not page.new_button.isEnabled()
    assert "Sign in" in page.status_label.text()


def test_groups_page_starts_disconnected_and_disabled(qtbot):
    page = GroupsPage()
    qtbot.addWidget(page)

    assert not page.table.isEnabled()
    assert not page.new_button.isEnabled()
    assert not page.add_member_button.isEnabled()
    assert "Sign in" in page.status_label.text()


def test_users_page_set_graph_client_none_resets_state(qtbot):
    page = UsersPage()
    qtbot.addWidget(page)
    page.model.set_users(
        [
            UserSummary(
                id="u1",
                display_name="Jane",
                user_principal_name="jane@contoso.com",
                mail=None,
                account_enabled=True,
            )
        ]
    )

    page.set_graph_client(None)

    assert page.model.rowCount() == 0
    assert not page.table.isEnabled()


def _user(id_="u1", display_name="Jane Doe") -> UserSummary:
    return UserSummary(
        id=id_,
        display_name=display_name,
        user_principal_name="jane@contoso.com",
        mail=None,
        account_enabled=True,
    )


@pytest.mark.asyncio
async def test_impact_preview_used_for_single_selection(qtbot, monkeypatch):
    """Deleting/disabling exactly one user should build the bounded impact
    preview and show it, rather than falling back to a plain confirm --
    this is the safety framework the delete/disable handlers are meant to
    use for single-target actions."""
    page = UsersPage()
    qtbot.addWidget(page)
    page._graph_client = object()

    preview = ImpactPreview(
        target_id="u1", display_name="Jane Doe", user_principal_name="jane@contoso.com",
        account_enabled=True,
    )

    build_calls = []

    async def fake_build(graph_client, user_id, *, has_audit_logs):
        build_calls.append((graph_client, user_id, has_audit_logs))
        return preview

    monkeypatch.setattr(users_page_module, "build_user_impact_preview", fake_build)

    shown_dialogs = []

    class FakeDialog:
        def __init__(self, *args, **kwargs):
            shown_dialogs.append((args, kwargs))

        def exec(self):
            from PySide6.QtWidgets import QDialog

            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(users_page_module, "ImpactPreviewDialog", FakeDialog)

    confirm_destructive_called = []
    monkeypatch.setattr(
        users_page_module,
        "confirm_destructive",
        lambda *a, **k: confirm_destructive_called.append((a, k)) or True,
    )

    result = await page._confirm_with_impact_preview(
        [_user()], action_title="Delete user", verb="Permanently delete",
        action_sentence="This cannot be undone.", require_typed_confirmation=True,
    )

    assert result is True
    assert build_calls == [(page._graph_client, "u1", page._has_audit_logs)]
    assert len(shown_dialogs) == 1
    assert not confirm_destructive_called


@pytest.mark.asyncio
async def test_impact_preview_falls_back_to_plain_confirm_for_multi_selection(qtbot, monkeypatch):
    """Bulk actions must not build one impact preview per selected row --
    that would scale Graph traffic with selection size -- so multi-select
    should go straight to the plain named confirmation instead."""
    page = UsersPage()
    qtbot.addWidget(page)
    page._graph_client = object()

    build_called = []

    async def fake_build(*args, **kwargs):
        build_called.append(True)
        raise AssertionError("should not be called for multi-selection")

    monkeypatch.setattr(users_page_module, "build_user_impact_preview", fake_build)

    confirm_messages = []

    def fake_confirm(parent, title, message):
        confirm_messages.append((title, message))
        return True

    monkeypatch.setattr(users_page_module, "confirm_destructive", fake_confirm)

    users = [_user("u1", "Jane Doe"), _user("u2", "John Roe")]
    result = await page._confirm_with_impact_preview(
        users, action_title="Delete user(s)", verb="Permanently delete",
        action_sentence="This cannot be undone.", require_typed_confirmation=True,
    )

    assert result is True
    assert not build_called
    assert len(confirm_messages) == 1
    assert "Jane Doe" in confirm_messages[0][1] and "John Roe" in confirm_messages[0][1]


@pytest.mark.asyncio
async def test_impact_preview_falls_back_to_plain_confirm_when_preview_build_fails(qtbot, monkeypatch):
    """A failed preview shouldn't block the action outright -- fall back to
    a plain confirmation that surfaces the error rather than a dead end."""
    page = UsersPage()
    qtbot.addWidget(page)
    page._graph_client = object()

    async def failing_build(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(users_page_module, "build_user_impact_preview", failing_build)

    confirm_messages = []

    def fake_confirm(parent, title, message):
        confirm_messages.append((title, message))
        return False

    monkeypatch.setattr(users_page_module, "confirm_destructive", fake_confirm)

    result = await page._confirm_with_impact_preview(
        [_user()], action_title="Delete user", verb="Permanently delete",
        action_sentence="This cannot be undone.", require_typed_confirmation=True,
    )

    assert result is False
    assert "Couldn't load impact preview" in confirm_messages[0][1]


@pytest.mark.asyncio
async def test_stale_refresh_does_not_clobber_a_newer_one(qtbot):
    """A slow broad search (e.g. one letter) that's still in flight when the
    admin refines it to a fast, narrow one must not overwrite the narrow
    result once it eventually completes."""
    page = UsersPage()
    qtbot.addWidget(page)

    slow_release = asyncio.Event()

    class FakeService:
        async def list_users(self, search):
            if search == "slow":
                await slow_release.wait()
                return [_user(display_name="StaleResult")]
            return [_user(display_name="FreshResult")]

    page._service = FakeService()

    page.search_edit.setText("slow")
    stale_task = page._on_refresh_clicked()
    await asyncio.sleep(0)  # let it reach the await inside list_users

    page.search_edit.setText("fresh")
    await page._on_refresh_clicked()
    assert [u.display_name for u in page.model.all_users()] == ["FreshResult"]

    slow_release.set()
    await stale_task

    assert [u.display_name for u in page.model.all_users()] == ["FreshResult"]


@pytest.mark.asyncio
async def test_stale_member_refresh_does_not_clobber_a_different_selection(qtbot):
    """Selecting group A (slow member fetch) then quickly selecting group B
    (fast fetch) must leave B's members displayed, not have A's slow
    response land afterwards and silently overwrite them."""
    page = GroupsPage()
    qtbot.addWidget(page)

    group_a = GroupSummary(id="a", display_name="Group A", mail=None, group_type="Security")
    group_b = GroupSummary(id="b", display_name="Group B", mail=None, group_type="Security")
    slow_release = asyncio.Event()

    class FakeService:
        async def list_members(self, group_id):
            if group_id == "a":
                await slow_release.wait()
                return [GroupMember(id="1", display_name="Alice")]
            return [GroupMember(id="2", display_name="Bob")]

    page._service = FakeService()

    page._selected_group = group_a
    stale_task = page._refresh_members()
    await asyncio.sleep(0)  # let it reach the await inside list_members

    page._selected_group = group_b
    await page._refresh_members()
    assert [page.members_list.item(i).text() for i in range(page.members_list.count())] == ["Bob"]

    slow_release.set()
    await stale_task

    assert [page.members_list.item(i).text() for i in range(page.members_list.count())] == ["Bob"]


@pytest.mark.asyncio
async def test_bulk_delete_continues_past_a_failure_and_reports_it(qtbot, monkeypatch):
    """One user failing to delete must not abort the rest of the selection,
    and the resulting message must say what succeeded vs failed."""
    page = UsersPage()
    qtbot.addWidget(page)
    users = [_user(id_="u1", display_name="Good1"),
             _user(id_="u2", display_name="Bad"),
             _user(id_="u3", display_name="Good2")]
    page.model.set_users(users)
    page.table.selectAll()

    deleted = []

    class FakeService:
        async def delete_user(self, user_id, *, display_name=None):
            if user_id == "u2":
                raise RuntimeError("locked")
            deleted.append(user_id)

        async def list_users(self, search=None):
            return []

    page._service = FakeService()
    monkeypatch.setattr(users_page_module, "confirm_destructive", lambda *a, **k: True)

    critical_calls = []
    monkeypatch.setattr(
        users_page_module.QMessageBox, "critical",
        lambda *a, **k: critical_calls.append(a))

    await page._on_delete_clicked()

    assert deleted == ["u1", "u3"]  # both good ones still attempted despite u2 failing
    assert len(critical_calls) == 1
    message = critical_calls[0][2]
    assert "2 of 3 succeeded" in message
    assert "Bad" in message
