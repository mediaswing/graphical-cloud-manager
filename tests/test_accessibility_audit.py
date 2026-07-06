"""Walks the main window's widget tree and fails if any interactive control
lacks an accessible name -- a screen-reader user would otherwise hit a
button/field/action announced only as its generic type ("button", "edit").

This is a floor, not a ceiling: it catches an obviously missing label, not
whether the label text is actually good. The manual NVDA/VoiceOver/Orca pass
described in docs/DESIGN.md section 7 remains the release gate for quality.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QLineEdit,
    QListWidget,
    QWidget,
)

from gcm.ui.login_dialog import LoginDialog
from gcm.ui.main_window import MainWindow
from gcm.ui.settings_dialog import SettingsDialog

_CHECKED_TYPES = (QAbstractButton, QLineEdit, QComboBox, QListWidget)


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


def test_settings_dialog_controls_have_accessible_names(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("GCM_CONFIG_PATH", str(tmp_path / "config.toml"))
    dialog = SettingsDialog()
    qtbot.addWidget(dialog)

    unlabeled = _find_unlabeled(dialog)
    assert not unlabeled, f"Controls missing accessible names: {unlabeled}"


def test_main_window_nav_is_keyboard_reachable(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.nav_list.focusPolicy() != 0, "Section navigation must be keyboard-focusable"
    assert window.nav_list.count() >= 4, "Core sections (Users/Groups/Licensing/Roles) must be present"
