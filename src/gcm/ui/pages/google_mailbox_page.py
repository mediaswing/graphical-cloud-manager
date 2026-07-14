"""Google Mailbox page: vacation responder, auto forwarding, and delegates
for a Google Workspace mailbox. Same tabbed-panel shape as
ui/pages/exchange_page.py, but gated differently: this page depends only on
a service account (GoogleConfig.service_account_json_path) being configured
in Google Workspace > Settings..., not on the interactive Google sign-in
used by the Users/Groups/Devices pages -- see
services/google_mailbox_service.py's module docstring for why mailbox admin
needs a separate domain-wide-delegation credential.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qasync import asyncSlot

from gcm.config import load_google_config
from gcm.services.google_errors import friendly_google_error
from gcm.services.google_mailbox_service import GoogleMailboxService
from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.confirm import confirm_destructive

_DISPOSITION_ITEMS = [
    ("Keep in inbox", "leaveInInbox"),
    ("Archive", "archive"),
    ("Trash", "trash"),
    ("Mark as read", "markRead"),
]

_NOT_CONFIGURED_MESSAGE = (
    "Configure a service account in Google Workspace > Settings... to manage mailboxes. "
    "Mailbox actions need domain-wide delegation, which is separate from the interactive "
    "sign-in used by Users/Groups/Devices."
)


class GoogleMailboxPage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Google Mailbox")
        self._service: GoogleMailboxService | None = None
        self._loaded_email: str | None = None

        layout = QVBoxLayout(self)

        heading = QLabel("Google Mailbox")
        heading.setAccessibleName("Google Mailbox")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel(_NOT_CONFIGURED_MESSAGE)
        self.status_label.setAccessibleName("Google Mailbox status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        load_row = QHBoxLayout()
        load_label = QLabel("&Mailbox email")
        self.email_edit = QLineEdit()
        self.email_edit.setAccessibleName("Mailbox to manage")
        self.email_edit.setPlaceholderText("jane.doe@contoso.com")
        self.email_edit.returnPressed.connect(self._on_load_clicked)
        load_label.setBuddy(self.email_edit)
        load_row.addWidget(load_label)
        load_row.addWidget(self.email_edit)

        self.load_button = AccessibleButton("&Load mailbox")
        self.load_button.clicked.connect(self._on_load_clicked)
        load_row.addWidget(self.load_button)
        layout.addLayout(load_row)

        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Mailbox settings")
        self.tabs.addTab(self._build_vacation_tab(), "Vacation responder")
        self.tabs.addTab(self._build_forwarding_tab(), "Forwarding")
        self.tabs.addTab(self._build_delegates_tab(), "Delegates")
        layout.addWidget(self.tabs, stretch=1)

        self._set_load_controls_enabled(False)
        self._set_tab_controls_enabled(False)
        self.refresh_configuration()

    # -- Tab construction -------------------------------------------------------

    def _build_vacation_tab(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)

        self.vacation_enabled_check = QCheckBox("&Enable vacation responder")
        self.vacation_enabled_check.setAccessibleName("Enable vacation responder")
        panel_layout.addWidget(self.vacation_enabled_check)

        self.restrict_contacts_check = QCheckBox("&Only reply to contacts")
        self.restrict_contacts_check.setAccessibleName("Only reply to contacts")
        panel_layout.addWidget(self.restrict_contacts_check)

        subject_label = QLabel("&Subject")
        panel_layout.addWidget(subject_label)
        self.vacation_subject_edit = QLineEdit()
        self.vacation_subject_edit.setAccessibleName("Vacation responder subject")
        subject_label.setBuddy(self.vacation_subject_edit)
        panel_layout.addWidget(self.vacation_subject_edit)

        message_label = QLabel("&Message")
        panel_layout.addWidget(message_label)
        self.vacation_message_edit = QPlainTextEdit()
        self.vacation_message_edit.setAccessibleName("Vacation responder message")
        message_label.setBuddy(self.vacation_message_edit)
        panel_layout.addWidget(self.vacation_message_edit)

        self.save_vacation_button = AccessibleButton("&Save vacation responder")
        self.save_vacation_button.clicked.connect(self._on_save_vacation_clicked)
        panel_layout.addWidget(self.save_vacation_button)

        return panel

    def _build_forwarding_tab(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)

        note = QLabel(
            "Google requires a forwarding address to be verified before mail can be "
            "auto-forwarded to it. Request verification below, then wait for that "
            "address's owner to accept the email Google sends them before enabling "
            "auto-forwarding to it."
        )
        note.setWordWrap(True)
        note.setAccessibleName("Forwarding limitations note")
        panel_layout.addWidget(note)

        self.forwarding_addresses_list = QListWidget()
        self.forwarding_addresses_list.setAccessibleName("Forwarding addresses")
        panel_layout.addWidget(self.forwarding_addresses_list)

        request_row = QHBoxLayout()
        request_label = QLabel("&Request verification for")
        self.forwarding_candidate_edit = QLineEdit()
        self.forwarding_candidate_edit.setAccessibleName("Forwarding address to verify")
        self.forwarding_candidate_edit.setPlaceholderText("external@example.com")
        request_label.setBuddy(self.forwarding_candidate_edit)
        request_row.addWidget(request_label)
        request_row.addWidget(self.forwarding_candidate_edit)

        self.request_verification_button = AccessibleButton("&Request verification")
        self.request_verification_button.clicked.connect(self._on_request_verification_clicked)
        request_row.addWidget(self.request_verification_button)
        panel_layout.addLayout(request_row)

        self.auto_forward_status_label = QLabel("Load a mailbox to see its auto-forwarding status.")
        self.auto_forward_status_label.setAccessibleName("Auto-forwarding status")
        self.auto_forward_status_label.setWordWrap(True)
        panel_layout.addWidget(self.auto_forward_status_label)

        self.auto_forward_enabled_check = QCheckBox("Enable auto-for&warding")
        self.auto_forward_enabled_check.setAccessibleName("Enable auto-forwarding")
        panel_layout.addWidget(self.auto_forward_enabled_check)

        target_row = QHBoxLayout()
        target_label = QLabel("Forward &to (verified address)")
        self.auto_forward_target_edit = QLineEdit()
        self.auto_forward_target_edit.setAccessibleName("Auto-forwarding destination address")
        self.auto_forward_target_edit.setPlaceholderText("external@example.com")
        target_label.setBuddy(self.auto_forward_target_edit)
        target_row.addWidget(target_label)
        target_row.addWidget(self.auto_forward_target_edit)
        panel_layout.addLayout(target_row)

        disposition_row = QHBoxLayout()
        disposition_label = QLabel("Cop&y disposition")
        self.disposition_combo = QComboBox()
        self.disposition_combo.setAccessibleName("Forwarded mail disposition")
        self.disposition_combo.addItems([label for label, _ in _DISPOSITION_ITEMS])
        disposition_label.setBuddy(self.disposition_combo)
        disposition_row.addWidget(disposition_label)
        disposition_row.addWidget(self.disposition_combo)
        panel_layout.addLayout(disposition_row)

        self.save_forwarding_button = AccessibleButton("&Save auto-forwarding")
        self.save_forwarding_button.clicked.connect(self._on_save_forwarding_clicked)
        panel_layout.addWidget(self.save_forwarding_button)

        return panel

    def _build_delegates_tab(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)

        self.delegates_list = QListWidget()
        self.delegates_list.setAccessibleName("Mailbox delegates")
        panel_layout.addWidget(self.delegates_list)

        add_row = QHBoxLayout()
        add_label = QLabel("&Add delegate")
        self.delegate_edit = QLineEdit()
        self.delegate_edit.setAccessibleName("Delegate email to add")
        self.delegate_edit.setPlaceholderText("assistant@contoso.com")
        add_label.setBuddy(self.delegate_edit)
        add_row.addWidget(add_label)
        add_row.addWidget(self.delegate_edit)

        self.add_delegate_button = AccessibleButton("A&dd")
        self.add_delegate_button.clicked.connect(self._on_add_delegate_clicked)
        add_row.addWidget(self.add_delegate_button)
        panel_layout.addLayout(add_row)

        self.remove_delegate_button = AccessibleButton("&Remove selected delegate")
        self.remove_delegate_button.clicked.connect(self._on_remove_delegate_clicked)
        panel_layout.addWidget(self.remove_delegate_button)

        return panel

    # -- Shared state -------------------------------------------------------------

    def _set_load_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.email_edit, self.load_button):
            widget.setEnabled(enabled)

    def _set_tab_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.vacation_enabled_check,
            self.restrict_contacts_check,
            self.vacation_subject_edit,
            self.vacation_message_edit,
            self.save_vacation_button,
            self.forwarding_addresses_list,
            self.forwarding_candidate_edit,
            self.request_verification_button,
            self.auto_forward_enabled_check,
            self.auto_forward_target_edit,
            self.disposition_combo,
            self.save_forwarding_button,
            self.delegates_list,
            self.delegate_edit,
            self.add_delegate_button,
            self.remove_delegate_button,
        ):
            widget.setEnabled(enabled)

    def refresh_configuration(self) -> None:
        """Re-reads GoogleConfig from disk -- called once at construction and
        again whenever GoogleSettingsDialog is saved, since this page's
        availability depends on the service account path being set, not on
        the interactive Google sign-in state other Google pages fan out
        set_directory_client(...) from."""
        config = load_google_config()
        if config is None or not config.service_account_json_path:
            self._service = None
            self._loaded_email = None
            self.status_label.setText(_NOT_CONFIGURED_MESSAGE)
            self._set_load_controls_enabled(False)
            self._set_tab_controls_enabled(False)
            return
        self._service = GoogleMailboxService(config.service_account_json_path)
        self._set_load_controls_enabled(True)
        self.status_label.setText("Enter a mailbox address to load its settings.")

    @asyncSlot()
    async def _on_load_clicked(self) -> None:
        if self._service is None:
            return
        email = self.email_edit.text().strip()
        if not email:
            self.status_label.setText("Enter a mailbox email address first.")
            return
        self.status_label.setText("Loading mailbox...")
        try:
            vacation = await self._service.get_vacation_responder(email)
            auto_forward = await self._service.get_auto_forwarding(email)
            forwarding_addresses = await self._service.list_forwarding_addresses(email)
            delegates = await self._service.list_delegates(email)
        except Exception as exc:
            self.status_label.setText(f"Couldn't load mailbox: {friendly_google_error(exc)}")
            return

        self._loaded_email = email

        self.vacation_enabled_check.setChecked(vacation.enabled)
        self.restrict_contacts_check.setChecked(vacation.restrict_to_contacts)
        self.vacation_subject_edit.setText(vacation.subject)
        self.vacation_message_edit.setPlainText(vacation.message)

        self.forwarding_addresses_list.clear()
        for addr in forwarding_addresses:
            self.forwarding_addresses_list.addItem(
                f"{addr.forwarding_email} ({addr.verification_status})"
            )

        if auto_forward.enabled:
            self.auto_forward_status_label.setText(
                f"Currently forwarding to {auto_forward.forwarding_email}."
            )
        else:
            self.auto_forward_status_label.setText("Auto-forwarding is currently off.")
        self.auto_forward_enabled_check.setChecked(auto_forward.enabled)
        self.auto_forward_target_edit.setText(auto_forward.forwarding_email)
        disposition_labels = {value: label for label, value in _DISPOSITION_ITEMS}
        self.disposition_combo.setCurrentText(
            disposition_labels.get(auto_forward.disposition, "Keep in inbox")
        )

        self.delegates_list.clear()
        self._delegates = delegates
        for delegate in delegates:
            self.delegates_list.addItem(
                f"{delegate.delegate_email} ({delegate.verification_status})"
            )

        self.status_label.setText(f"Loaded {email}.")
        self._set_tab_controls_enabled(True)

    # -- Vacation responder -----------------------------------------------------

    @asyncSlot()
    async def _on_save_vacation_clicked(self) -> None:
        if self._service is None or self._loaded_email is None:
            return
        try:
            await self._service.set_vacation_responder(
                self._loaded_email,
                enabled=self.vacation_enabled_check.isChecked(),
                subject=self.vacation_subject_edit.text(),
                message=self.vacation_message_edit.toPlainText(),
                restrict_to_contacts=self.restrict_contacts_check.isChecked(),
            )
        except Exception as exc:
            QMessageBox.critical(
                self, "Couldn't save vacation responder", friendly_google_error(exc)
            )
            return
        self.status_label.setText("Vacation responder saved.")

    # -- Forwarding ---------------------------------------------------------

    @asyncSlot()
    async def _on_request_verification_clicked(self) -> None:
        if self._service is None or self._loaded_email is None:
            return
        candidate = self.forwarding_candidate_edit.text().strip()
        if not candidate:
            self.status_label.setText("Enter an address to request verification for first.")
            return
        try:
            await self._service.request_forwarding_verification(self._loaded_email, candidate)
        except Exception as exc:
            QMessageBox.critical(
                self, "Couldn't request verification", friendly_google_error(exc)
            )
            return
        self.forwarding_candidate_edit.clear()
        self.status_label.setText(
            f"Verification requested for {candidate}. They must accept it before "
            "auto-forwarding can target it."
        )
        await self._on_load_clicked()

    @asyncSlot()
    async def _on_save_forwarding_clicked(self) -> None:
        if self._service is None or self._loaded_email is None:
            return
        target = self.auto_forward_target_edit.text().strip()
        enabled = self.auto_forward_enabled_check.isChecked()
        if enabled and not target:
            self.status_label.setText("Enter a forwarding destination address first.")
            return
        disposition = dict(_DISPOSITION_ITEMS)[self.disposition_combo.currentText()]
        if enabled and not confirm_destructive(
            self, "Save auto-forwarding",
            f"Forward mail for {self._loaded_email} to {target}? "
            "This only works if that address has already accepted verification.",
        ):
            return
        try:
            await self._service.set_auto_forwarding(
                self._loaded_email, target, enabled=enabled, disposition=disposition,
            )
        except Exception as exc:
            QMessageBox.critical(
                self, "Couldn't save auto-forwarding", friendly_google_error(exc)
            )
            return
        await self._on_load_clicked()

    # -- Delegates ------------------------------------------------------------

    @asyncSlot()
    async def _on_add_delegate_clicked(self) -> None:
        if self._service is None or self._loaded_email is None:
            return
        delegate_email = self.delegate_edit.text().strip()
        if not delegate_email:
            self.status_label.setText("Enter a delegate email address first.")
            return
        try:
            await self._service.add_delegate(self._loaded_email, delegate_email)
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't add delegate", friendly_google_error(exc))
            return
        self.delegate_edit.clear()
        await self._on_load_clicked()

    @asyncSlot()
    async def _on_remove_delegate_clicked(self) -> None:
        if self._service is None or self._loaded_email is None:
            return
        row = self.delegates_list.currentRow()
        if row < 0 or row >= len(getattr(self, "_delegates", [])):
            self.status_label.setText("Select a delegate to remove first.")
            return
        delegate = self._delegates[row]
        if not confirm_destructive(
            self, "Remove delegate",
            f"Remove {delegate.delegate_email!r} as a delegate of {self._loaded_email}?",
        ):
            return
        try:
            await self._service.remove_delegate(self._loaded_email, delegate.delegate_email)
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't remove delegate", friendly_google_error(exc))
            return
        await self._on_load_clicked()
