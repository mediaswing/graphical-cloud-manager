"""Dynamic group membership rule editor.

Provides a guided builder for common single-condition rules alongside the
raw rule text editor, per docs/DESIGN.md's "strong first version" scope:
raw editor, common-condition helper, preview, validation guidance -- not a
full visual rule builder.

Deliberately does NOT parse the existing rule text. A pseudo-parser that
doesn't fully understand Entra's dynamic-membership-rule grammar risks
silently corrupting a valid existing rule it misreads; the guided builder
only ever *composes new text to insert*, and the existing rule is never
touched unless the admin edits it themselves.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from gcm.ui.widgets.accessible_button import AccessibleButton

_USER_ATTRIBUTES = [
    "department", "jobTitle", "companyName", "country", "userType", "accountEnabled",
]
_DEVICE_ATTRIBUTES = [
    "deviceOSType", "deviceOwnership", "displayName", "isManaged", "isCompliant",
]
_OPERATORS = [
    ("Equals", "-eq"),
    ("Not equals", "-ne"),
    ("Contains", "-contains"),
    ("Starts with", "-startsWith"),
    ("Does not start with", "-notStartsWith"),
]


class DynamicRuleDialog(QDialog):
    def __init__(
        self,
        group_display_name: str,
        current_rule: str | None,
        is_microsoft_365: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Dynamic membership rule - {group_display_name}")
        self.setAccessibleName(f"Dynamic membership rule for {group_display_name}")
        self._is_microsoft_365 = is_microsoft_365

        layout = QVBoxLayout(self)

        kind_note = QLabel(
            "This is a Microsoft 365 group: dynamic membership rules can only target "
            "users here, not devices. Device-based rules require a Security group."
            if is_microsoft_365
            else "This is a Security group: the rule can target users or devices."
        )
        kind_note.setWordWrap(True)
        kind_note.setAccessibleName("Dynamic group type note")
        layout.addWidget(kind_note)

        builder_heading = QLabel("Guided condition builder")
        builder_heading.setAccessibleName("Guided condition builder heading")
        layout.addWidget(builder_heading)

        builder_row = QHBoxLayout()
        attr_label = QLabel("&Attribute")
        self.attribute_combo = QComboBox()
        self.attribute_combo.setAccessibleName("Attribute")
        attrs = list(_USER_ATTRIBUTES) if is_microsoft_365 else _USER_ATTRIBUTES + _DEVICE_ATTRIBUTES
        self.attribute_combo.addItems(attrs)
        attr_label.setBuddy(self.attribute_combo)
        builder_row.addWidget(attr_label)
        builder_row.addWidget(self.attribute_combo)

        op_label = QLabel("&Operator")
        self.operator_combo = QComboBox()
        self.operator_combo.setAccessibleName("Operator")
        self.operator_combo.addItems([label for label, _ in _OPERATORS])
        op_label.setBuddy(self.operator_combo)
        builder_row.addWidget(op_label)
        builder_row.addWidget(self.operator_combo)

        value_label = QLabel("&Value")
        self.value_edit = QLineEdit()
        self.value_edit.setAccessibleName("Value")
        value_label.setBuddy(self.value_edit)
        builder_row.addWidget(value_label)
        builder_row.addWidget(self.value_edit)
        layout.addLayout(builder_row)

        insert_row = QHBoxLayout()
        connector_label = QLabel("Co&mbine with existing rule using")
        self.connector_combo = QComboBox()
        self.connector_combo.setAccessibleName("Combine with existing rule using")
        self.connector_combo.addItems(["and", "or"])
        connector_label.setBuddy(self.connector_combo)
        insert_row.addWidget(connector_label)
        insert_row.addWidget(self.connector_combo)

        self.insert_button = AccessibleButton("&Insert condition")
        self.insert_button.clicked.connect(self._on_insert_clicked)
        insert_row.addWidget(self.insert_button)
        layout.addLayout(insert_row)

        raw_heading = QLabel("Rule text")
        raw_heading.setAccessibleName("Rule text heading")
        layout.addWidget(raw_heading)

        self.rule_edit = QPlainTextEdit()
        self.rule_edit.setAccessibleName("Membership rule text")
        self.rule_edit.setAccessibleDescription(
            "The raw dynamic membership rule. Edit directly for advanced or complex rules."
        )
        self.rule_edit.setPlainText(current_rule or "")
        self.rule_edit.textChanged.connect(self._update_preview)
        layout.addWidget(self.rule_edit)

        self.preview_label = QLabel("")
        self.preview_label.setAccessibleName("Rule preview")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)

        self.validation_label = QLabel("")
        self.validation_label.setAccessibleName("Rule validation")
        self.validation_label.setWordWrap(True)
        layout.addWidget(self.validation_label)

        disclaimer = QLabel(
            "This only checks basic syntax (non-empty, balanced quotes/parentheses, and "
            "whether the rule matches this group's supported type). It cannot guarantee "
            "Microsoft Entra will accept the rule -- invalid attribute names or "
            "unsupported operators can still be rejected when you save."
        )
        disclaimer.setWordWrap(True)
        disclaimer.setAccessibleName("Validation disclaimer")
        layout.addWidget(disclaimer)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setAccessibleName("Save rule")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setAccessibleName("Cancel")
        buttons.accepted.connect(self._on_save_clicked)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._update_preview()

    def _on_insert_clicked(self) -> None:
        attribute = self.attribute_combo.currentText()
        operator_label = self.operator_combo.currentText()
        operator = next(op for label, op in _OPERATORS if label == operator_label)
        value = self.value_edit.text().strip()
        if not value:
            self.validation_label.setText("Enter a value before inserting a condition.")
            return
        prefix = "device." if attribute in _DEVICE_ATTRIBUTES else "user."
        clause = f'({prefix}{attribute} {operator} "{value}")'

        existing = self.rule_edit.toPlainText().strip()
        new_text = f"{existing} {self.connector_combo.currentText()} {clause}" if existing else clause
        self.rule_edit.setPlainText(new_text)
        self.value_edit.clear()

    def _update_preview(self) -> None:
        rule = self.rule_edit.toPlainText().strip()
        self.preview_label.setText(f"Preview: {rule}" if rule else "Preview: (empty)")
        self.validation_label.setText("")

    def _on_save_clicked(self) -> None:
        errors = self._validate()
        if errors:
            self.validation_label.setText(" ".join(errors))
            return
        self.accept()

    def _validate(self) -> list[str]:
        rule = self.rule_edit.toPlainText().strip()
        errors: list[str] = []
        if not rule:
            errors.append("The rule cannot be empty.")
            return errors
        if rule.count("(") != rule.count(")"):
            errors.append("Unbalanced parentheses.")
        if rule.count('"') % 2 != 0:
            errors.append("Unbalanced quotes.")
        if self._is_microsoft_365 and "device." in rule:
            errors.append(
                "Microsoft 365 groups can't use device-based rules (found 'device.'). "
                "Device-based dynamic membership requires a Security group."
            )
        return errors

    def rule_text(self) -> str:
        return self.rule_edit.toPlainText().strip()
