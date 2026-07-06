"""Walks the main window's widget tree and fails if any interactive control
lacks an accessible name -- a screen-reader user would otherwise hit a
button/field/action announced only as its generic type ("button", "edit").

This is a floor, not a ceiling: it catches an obviously missing label, not
whether the label text is actually good. The manual NVDA/VoiceOver/Orca pass
described in docs/DESIGN.md section 7 remains the release gate for quality.
"""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QWidget,
)

from gcm.models.user import UserDetail
from gcm.ui.dialogs.dynamic_rule_dialog import DynamicRuleDialog
from gcm.ui.login_dialog import LoginDialog
from gcm.ui.main_window import MainWindow
from gcm.ui.pages.exchange_page import ExchangePage
from gcm.ui.pages.groups_page import NewGroupDialog
from gcm.ui.pages.intune_page import IntunePage
from gcm.ui.pages.sign_in_logs_page import SignInLogsPage
from gcm.ui.pages.users_page import EditUserDialog, NewUserDialog, ResetPasswordDialog
from gcm.ui.settings_dialog import SettingsDialog

_CHECKED_TYPES = (QAbstractButton, QLineEdit, QComboBox, QListWidget, QPlainTextEdit)


def _find_unlabeled(root: QWidget) -> list[str]:
    unlabeled = []
    for widget_type in _CHECKED_TYPES:
        for widget in root.findChildren(widget_type):
            # Qt creates its own internal helper widgets (e.g. the menu bar's
            # overflow button, "qt_menubar_ext_button"); those are Qt's own
            # accessibility responsibility, not ours.
            if widget.objectName().startswith("qt_"):
                continue
            if not widget.accessibleName().strip():
                unlabeled.append(f"{type(widget).__name__} (text={widget.property('text')!r})")
    return unlabeled


def test_main_window_controls_have_accessible_names(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    unlabeled = _find_unlabeled(window)
    assert not unlabeled, f"Controls missing accessible names: {unlabeled}"


def test_login_dialog_controls_have_accessible_names(qtbot):
    dialog = LoginDialog()
    qtbot.addWidget(dialog)

    unlabeled = _find_unlabeled(dialog)
    assert not unlabeled, f"Controls missing accessible names: {unlabeled}"


def test_new_user_dialog_controls_have_accessible_names(qtbot):
    dialog = NewUserDialog()
    qtbot.addWidget(dialog)

    unlabeled = _find_unlabeled(dialog)
    assert not unlabeled, f"Controls missing accessible names: {unlabeled}"


def test_new_group_dialog_controls_have_accessible_names(qtbot):
    dialog = NewGroupDialog()
    qtbot.addWidget(dialog)

    unlabeled = _find_unlabeled(dialog)
    assert not unlabeled, f"Controls missing accessible names: {unlabeled}"


def test_dynamic_rule_dialog_controls_have_accessible_names(qtbot):
    dialog = DynamicRuleDialog("Sales Team", '(user.department -eq "Sales")', is_microsoft_365=False)
    qtbot.addWidget(dialog)

    unlabeled = _find_unlabeled(dialog)
    assert not unlabeled, f"Controls missing accessible names: {unlabeled}"


def test_edit_user_dialog_controls_have_accessible_names(qtbot):
    detail = UserDetail(
        id="u1",
        display_name="Jane Doe",
        job_title=None,
        department=None,
        office_location=None,
        mobile_phone=None,
        usage_location=None,
    )
    dialog = EditUserDialog(detail)
    qtbot.addWidget(dialog)

    unlabeled = _find_unlabeled(dialog)
    assert not unlabeled, f"Controls missing accessible names: {unlabeled}"


def test_reset_password_dialog_controls_have_accessible_names(qtbot):
    dialog = ResetPasswordDialog("Jane Doe")
    qtbot.addWidget(dialog)

    unlabeled = _find_unlabeled(dialog)
    assert not unlabeled, f"Controls missing accessible names: {unlabeled}"


def test_sign_in_logs_page_controls_have_accessible_names(qtbot):
    # Not part of MainWindow's default tree -- it's only added when
    # capability detection finds Azure AD Premium, so it needs its own check.
    page = SignInLogsPage()
    qtbot.addWidget(page)

    unlabeled = _find_unlabeled(page)
    assert not unlabeled, f"Controls missing accessible names: {unlabeled}"


def test_intune_page_controls_have_accessible_names(qtbot):
    # Not part of MainWindow's default tree -- it's only added when
    # capability detection finds Intune, so it needs its own check.
    page = IntunePage()
    qtbot.addWidget(page)

    unlabeled = _find_unlabeled(page)
    assert not unlabeled, f"Controls missing accessible names: {unlabeled}"


def test_exchange_page_controls_have_accessible_names(qtbot):
    # Not part of MainWindow's default tree -- it's only added when
    # capability detection finds Exchange Online, so it needs its own check.
    page = ExchangePage()
    qtbot.addWidget(page)

    unlabeled = _find_unlabeled(page)
    assert not unlabeled, f"Controls missing accessible names: {unlabeled}"


def test_settings_dialog_controls_have_accessible_names(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_CONFIG_PATH", str(tmp_path / "config.toml"))
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    unlabeled = _find_unlabeled(dialog)
    assert not unlabeled, f"Controls missing accessible names: {unlabeled}"


def test_tenant_menu_actions_stay_in_the_tenant_menu(qtbot):
    """Qt's default MenuRole is a text heuristic that silently relocates
    actions like "Settings..." to the macOS application menu, out of the menu
    they were actually added to -- a real user hit this (the item just
    looked missing). Pin these to NoRole so they stay put on every platform.
    """
    window = MainWindow()
    qtbot.addWidget(window)

    for action in (window.settings_action, window.sign_in_action, window.sign_out_action):
        assert action.menuRole() == QAction.MenuRole.NoRole, (
            f"{action.text()!r} must use MenuRole.NoRole or macOS may move it "
            "out of the Tenant menu"
        )


def test_main_window_nav_is_keyboard_reachable(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.nav_list.focusPolicy() != 0, "Section navigation must be keyboard-focusable"
    assert window.nav_list.count() >= 7, (
        "Core sections (Users/Groups/Devices/Licensing/Roles/Bulk import/Audit log) must be present"
    )
