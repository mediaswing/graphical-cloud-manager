"""Shared impact-preview confirmation dialog: shows what's cheaply known
about a target before a destructive/high-impact action, then requires
confirmation -- optionally the stronger type-the-name kind for irreversible
actions. Centralizes the pattern (task 8) so other modules (Devices, future
ones) can reuse it instead of rolling their own.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from gcm.services.impact_preview import ImpactPreview


class ImpactPreviewDialog(QDialog):
    def __init__(
        self,
        title: str,
        action_description: str,
        preview: ImpactPreview,
        *,
        require_typed_confirmation: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setAccessibleName(title)
        self._require_typed = require_typed_confirmation
        self._type_target = preview.display_name

        layout = QVBoxLayout(self)

        action_label = QLabel(action_description)
        action_label.setWordWrap(True)
        action_label.setAccessibleName("Action description")
        layout.addWidget(action_label)

        identity_label = QLabel(f"{preview.display_name} ({preview.user_principal_name})")
        identity_label.setAccessibleName("Target identity")
        layout.addWidget(identity_label)

        if preview.account_enabled is None:
            status_line = "Unknown"
        else:
            status_line = "Enabled" if preview.account_enabled else "Disabled"
        status_label = QLabel(f"Account status: {status_line}")
        status_label.setAccessibleName("Target account status")
        layout.addWidget(status_label)

        licenses_label = QLabel(
            "Licenses: " + (", ".join(preview.license_names) if preview.license_names else "none")
        )
        licenses_label.setWordWrap(True)
        licenses_label.setAccessibleName("Target licenses")
        layout.addWidget(licenses_label)

        groups_text = ", ".join(preview.group_names) if preview.group_names else "none"
        if preview.member_of_truncated:
            groups_text += " (and more not shown)"
        groups_label = QLabel(f"Group memberships: {groups_text}")
        groups_label.setWordWrap(True)
        groups_label.setAccessibleName("Target group memberships")
        layout.addWidget(groups_label)

        roles_text = ", ".join(preview.admin_role_names) if preview.admin_role_names else "none"
        roles_label = QLabel(f"Administrative roles: {roles_text}")
        roles_label.setWordWrap(True)
        roles_label.setAccessibleName("Target administrative roles")
        layout.addWidget(roles_label)

        if preview.last_sign_in_checked:
            sign_in_text = preview.last_sign_in or "No recent sign-in found"
        else:
            sign_in_text = "Not available (requires Azure AD Premium)"
        sign_in_label = QLabel(f"Last sign-in: {sign_in_text}")
        sign_in_label.setAccessibleName("Target last sign-in")
        layout.addWidget(sign_in_label)

        if preview.warnings:
            warnings_label = QLabel("Couldn't check: " + "; ".join(preview.warnings))
            warnings_label.setWordWrap(True)
            warnings_label.setAccessibleName("Impact preview warnings")
            layout.addWidget(warnings_label)

        not_checked_label = QLabel(preview.not_checked_note)
        not_checked_label.setWordWrap(True)
        not_checked_label.setAccessibleName("What this preview does not check")
        layout.addWidget(not_checked_label)

        self.confirm_edit: QLineEdit | None = None
        if require_typed_confirmation:
            prompt_label = QLabel(f'Type "{self._type_target}" to confirm:')
            prompt_label.setWordWrap(True)
            layout.addWidget(prompt_label)
            self.confirm_edit = QLineEdit()
            self.confirm_edit.setAccessibleName(f'Type "{self._type_target}" to confirm')
            self.confirm_edit.textChanged.connect(self._update_ok_enabled)
            prompt_label.setBuddy(self.confirm_edit)
            layout.addWidget(self.confirm_edit)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setAccessibleName("Confirm")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setAccessibleName("Cancel")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        if require_typed_confirmation:
            self._update_ok_enabled()

    def _update_ok_enabled(self) -> None:
        matches = self.confirm_edit is not None and self.confirm_edit.text() == self._type_target
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(matches)
