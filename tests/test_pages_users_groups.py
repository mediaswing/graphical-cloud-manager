"""Tests for the Users/Groups page table models and disconnected-state
behavior. Doesn't touch the network -- feeds the table models sample
dataclasses directly and checks the page's pre-sign-in state."""

from __future__ import annotations

from PySide6.QtCore import Qt

from gcm.models.group import GroupSummary
from gcm.models.user import UserSummary
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
