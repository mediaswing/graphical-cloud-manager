"""Sign-in dialog: pick/create a connection profile, then hand off to
AuthManager.sign_in_interactive() for the actual MSAL browser flow."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QVBoxLayout

from gcm.ui.widgets.accessible_button import AccessibleButton


class LoginDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sign in to a tenant")
        self.setAccessibleName("Sign in to a tenant")

        layout = QVBoxLayout(self)

        profile_label = QLabel("&Profile name")
        layout.addWidget(profile_label)

        self.profile_edit = QLineEdit()
        self.profile_edit.setAccessibleName("Profile name")
        self.profile_edit.setAccessibleDescription(
            "A label for this tenant connection, e.g. the customer's name"
        )
        self.profile_edit.setPlaceholderText("e.g. Contoso")
        profile_label.setBuddy(self.profile_edit)
        layout.addWidget(self.profile_edit)

        self.status_label = QLabel("")
        self.status_label.setAccessibleName("Sign-in status")
        layout.addWidget(self.status_label)

        self.sign_in_button = AccessibleButton("Sign &in")
        self.sign_in_button.setDefault(True)
        self.sign_in_button.clicked.connect(self.accept)
        layout.addWidget(self.sign_in_button)

        self.cancel_button = AccessibleButton("&Cancel")
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)

        self.setTabOrder(self.profile_edit, self.sign_in_button)
        self.setTabOrder(self.sign_in_button, self.cancel_button)

    def profile_name(self) -> str:
        return self.profile_edit.text().strip()
