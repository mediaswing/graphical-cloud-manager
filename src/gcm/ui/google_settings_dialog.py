"""Lets the admin point the app at their Google Cloud OAuth client (and,
optionally, a domain-wide-delegation service account for mailbox admin), and
saves it to the same on-disk config file settings_dialog.py uses -- under a
[google] table, alongside the existing Microsoft settings -- so it's
remembered across launches."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from gcm.config import GoogleConfig, config_path, load_google_config, save_google_config
from gcm.ui.widgets.accessible_button import AccessibleButton

_HELP_TEXT = (
    "Client ID / Client Secret: from a \"Desktop app\" OAuth 2.0 client in a "
    "Google Cloud project with the Admin SDK API enabled.\n"
    "Service account JSON (optional): only needed for Mailbox admin actions, "
    "which require domain-wide delegation authorized in the Workspace Admin "
    "console rather than a per-admin interactive sign-in."
)


class GoogleSettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Google Workspace settings")
        self.setAccessibleName("Google Workspace settings")

        layout = QVBoxLayout(self)

        help_label = QLabel(_HELP_TEXT)
        help_label.setWordWrap(True)
        help_label.setAccessibleName("Google Workspace settings help")
        layout.addWidget(help_label)

        location_label = QLabel(f"Saved to: {config_path()}")
        location_label.setWordWrap(True)
        location_label.setAccessibleName("Config file location")
        layout.addWidget(location_label)

        client_id_label = QLabel("&Client ID")
        layout.addWidget(client_id_label)
        self.client_id_edit = QLineEdit()
        self.client_id_edit.setAccessibleName("Client ID")
        self.client_id_edit.setPlaceholderText("00000000000-xxxxxxxxxxxx.apps.googleusercontent.com")
        client_id_label.setBuddy(self.client_id_edit)
        layout.addWidget(self.client_id_edit)

        client_secret_label = QLabel("Client &Secret")
        layout.addWidget(client_secret_label)
        self.client_secret_edit = QLineEdit()
        self.client_secret_edit.setAccessibleName("Client Secret")
        self.client_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        client_secret_label.setBuddy(self.client_secret_edit)
        layout.addWidget(self.client_secret_edit)

        service_account_label = QLabel("Service accou&nt JSON path (optional)")
        layout.addWidget(service_account_label)
        service_account_row = QHBoxLayout()
        self.service_account_edit = QLineEdit()
        self.service_account_edit.setAccessibleName("Service account JSON path")
        self.service_account_edit.setAccessibleDescription(
            "Only required for Mailbox admin actions"
        )
        service_account_label.setBuddy(self.service_account_edit)
        service_account_row.addWidget(self.service_account_edit)

        self.browse_button = AccessibleButton("&Browse...")
        self.browse_button.clicked.connect(self._on_browse)
        service_account_row.addWidget(self.browse_button)
        layout.addLayout(service_account_row)

        existing = load_google_config()
        if existing:
            self.client_id_edit.setText(existing.client_id)
            self.client_secret_edit.setText(existing.client_secret)
            self.service_account_edit.setText(existing.service_account_json_path)

        self.status_label = QLabel("")
        self.status_label.setAccessibleName("Settings status")
        layout.addWidget(self.status_label)

        self.save_button = AccessibleButton("&Save")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self._on_save)
        layout.addWidget(self.save_button)

        self.cancel_button = AccessibleButton("&Cancel")
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)

        self.setTabOrder(self.client_id_edit, self.client_secret_edit)
        self.setTabOrder(self.client_secret_edit, self.service_account_edit)
        self.setTabOrder(self.service_account_edit, self.browse_button)
        self.setTabOrder(self.browse_button, self.save_button)
        self.setTabOrder(self.save_button, self.cancel_button)

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose service account JSON key", "", "JSON files (*.json)"
        )
        if path:
            self.service_account_edit.setText(path)

    def _on_save(self) -> None:
        client_id = self.client_id_edit.text().strip()
        if not client_id:
            self.status_label.setText("Client ID is required.")
            self.client_id_edit.setFocus()
            return
        save_google_config(
            GoogleConfig(
                client_id=client_id,
                client_secret=self.client_secret_edit.text().strip(),
                service_account_json_path=self.service_account_edit.text().strip(),
            )
        )
        self.accept()
