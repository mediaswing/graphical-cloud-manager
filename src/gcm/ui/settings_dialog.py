"""Lets the admin point the app at their Entra app registration and tenant,
and saves it to the on-disk config file (gcm.config) so it's remembered
across launches."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QVBoxLayout

from gcm.config import AppConfig, config_path, load_config, save_config
from gcm.ui.widgets.accessible_button import AccessibleButton

_HELP_TEXT = (
    "Tenant ID: your Entra tenant's GUID, or \"organizations\" to allow sign-in "
    "from any work/school tenant.\n"
    "Client ID: the Application (client) ID of a public-client Entra app "
    "registration with a \"Mobile and desktop applications\" redirect URI of "
    "http://localhost."
)


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tenant settings")
        self.setAccessibleName("Tenant settings")

        layout = QVBoxLayout(self)

        help_label = QLabel(_HELP_TEXT)
        help_label.setWordWrap(True)
        help_label.setAccessibleName("Tenant settings help")
        layout.addWidget(help_label)

        location_label = QLabel(f"Saved to: {config_path()}")
        location_label.setWordWrap(True)
        location_label.setAccessibleName("Config file location")
        layout.addWidget(location_label)

        tenant_label = QLabel("&Tenant ID")
        layout.addWidget(tenant_label)
        self.tenant_edit = QLineEdit()
        self.tenant_edit.setAccessibleName("Tenant ID")
        self.tenant_edit.setPlaceholderText("organizations")
        tenant_label.setBuddy(self.tenant_edit)
        layout.addWidget(self.tenant_edit)

        client_label = QLabel("&Client ID")
        layout.addWidget(client_label)
        self.client_edit = QLineEdit()
        self.client_edit.setAccessibleName("Client ID")
        self.client_edit.setPlaceholderText("00000000-0000-0000-0000-000000000000")
        client_label.setBuddy(self.client_edit)
        layout.addWidget(self.client_edit)

        existing = load_config()
        if existing:
            self.tenant_edit.setText(existing.tenant_id)
            self.client_edit.setText(existing.client_id)

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

        self.setTabOrder(self.tenant_edit, self.client_edit)
        self.setTabOrder(self.client_edit, self.save_button)
        self.setTabOrder(self.save_button, self.cancel_button)

    def _on_save(self) -> None:
        client_id = self.client_edit.text().strip()
        if not client_id:
            self.status_label.setText("Client ID is required.")
            self.client_edit.setFocus()
            return
        tenant_id = self.tenant_edit.text().strip() or "organizations"
        save_config(AppConfig(client_id=client_id, tenant_id=tenant_id))
        self.accept()
