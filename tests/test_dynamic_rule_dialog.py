"""Tests for the dynamic group membership rule dialog: the guided builder's
generated text, client-side validation, and that existing rule text is
preserved unless the admin edits it."""

from __future__ import annotations

from gcm.ui.dialogs.dynamic_rule_dialog import DynamicRuleDialog


def test_existing_rule_is_preloaded_and_untouched(qtbot):
    dialog = DynamicRuleDialog("Sales Team", '(user.department -eq "Sales")', is_microsoft_365=False)
    qtbot.addWidget(dialog)

    assert dialog.rule_text() == '(user.department -eq "Sales")'


def test_insert_condition_into_empty_rule(qtbot):
    dialog = DynamicRuleDialog("Sales Team", None, is_microsoft_365=False)
    qtbot.addWidget(dialog)

    dialog.attribute_combo.setCurrentText("department")
    dialog.operator_combo.setCurrentText("Equals")
    dialog.value_edit.setText("Sales")
    dialog._on_insert_clicked()

    assert dialog.rule_text() == '(user.department -eq "Sales")'


def test_insert_condition_combines_with_existing_rule_using_chosen_connector(qtbot):
    dialog = DynamicRuleDialog("Sales Team", '(user.country -eq "US")', is_microsoft_365=False)
    qtbot.addWidget(dialog)

    dialog.attribute_combo.setCurrentText("department")
    dialog.operator_combo.setCurrentText("Equals")
    dialog.value_edit.setText("Sales")
    dialog.connector_combo.setCurrentText("or")
    dialog._on_insert_clicked()

    assert dialog.rule_text() == '(user.country -eq "US") or (user.department -eq "Sales")'


def test_insert_condition_requires_a_value(qtbot):
    dialog = DynamicRuleDialog("Sales Team", None, is_microsoft_365=False)
    qtbot.addWidget(dialog)

    dialog._on_insert_clicked()

    assert dialog.rule_text() == ""
    assert "value" in dialog.validation_label.text().lower()


def test_save_blocked_on_empty_rule(qtbot):
    dialog = DynamicRuleDialog("Sales Team", None, is_microsoft_365=False)
    qtbot.addWidget(dialog)

    dialog._on_save_clicked()

    assert dialog.result() != dialog.DialogCode.Accepted
    assert "empty" in dialog.validation_label.text().lower()


def test_save_blocked_on_unbalanced_parentheses(qtbot):
    dialog = DynamicRuleDialog("Sales Team", '(user.department -eq "Sales"', is_microsoft_365=False)
    qtbot.addWidget(dialog)

    dialog._on_save_clicked()

    assert "parenthes" in dialog.validation_label.text().lower()


def test_save_blocked_on_unbalanced_quotes(qtbot):
    dialog = DynamicRuleDialog("Sales Team", '(user.department -eq "Sales)', is_microsoft_365=False)
    qtbot.addWidget(dialog)

    dialog._on_save_clicked()

    assert "quote" in dialog.validation_label.text().lower()


def test_save_blocked_for_device_rule_on_microsoft_365_group(qtbot):
    dialog = DynamicRuleDialog(
        "All Staff", '(device.deviceOSType -eq "Windows")', is_microsoft_365=True
    )
    qtbot.addWidget(dialog)

    dialog._on_save_clicked()

    assert "microsoft 365" in dialog.validation_label.text().lower()


def test_save_accepts_a_valid_rule(qtbot):
    dialog = DynamicRuleDialog("Sales Team", '(user.department -eq "Sales")', is_microsoft_365=False)
    qtbot.addWidget(dialog)

    dialog._on_save_clicked()

    assert dialog.result() == dialog.DialogCode.Accepted


def test_microsoft_365_group_only_offers_user_attributes(qtbot):
    dialog = DynamicRuleDialog("All Staff", None, is_microsoft_365=True)
    qtbot.addWidget(dialog)

    items = [dialog.attribute_combo.itemText(i) for i in range(dialog.attribute_combo.count())]

    assert "deviceOSType" not in items
    assert "department" in items
