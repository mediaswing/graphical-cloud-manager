"""Exchange page: mailbox basics built only on capabilities Microsoft Graph
genuinely supports -- see gcm.services.mailbox_service's module docstring
for what's deliberately NOT implemented (native ForwardingSmtpAddress,
shared-mailbox identification) and why.

Read-only information (usage report) is kept separate from write operations
(aliases, automatic replies, forwarding), and forwarding -- the one
consequential, easy-to-misuse setting here -- always shows the destination
address prominently, calls out external domains explicitly, and requires
confirmation before being enabled.
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

from gcm.services.graph_errors import friendly_error_message
from gcm.services.mailbox_service import MailboxService
from gcm.ui.widgets.accessible_button import AccessibleButton
from gcm.ui.widgets.confirm import confirm_destructive

_AUDIENCE_ITEMS = [("None", "none"), ("Contacts only", "contactsOnly"), ("Everyone", "all")]


class ExchangePage(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Exchange")
        self._service: MailboxService | None = None
        self._loaded_user_id: str | None = None
        self._loaded_display_name: str | None = None

        layout = QVBoxLayout(self)

        heading = QLabel("Exchange")
        heading.setAccessibleName("Exchange")
        heading.setAccessibleDescription("Page heading")
        font = heading.font()
        font.setPointSize(font.pointSize() + 4)
        font.setBold(True)
        heading.setFont(font)
        layout.addWidget(heading)

        self.status_label = QLabel(
            "Sign in to a tenant (Tenant > Sign in...) to manage mailboxes."
        )
        self.status_label.setAccessibleName("Exchange status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        note = QLabel(
            "Shared mailboxes can't be reliably identified through Microsoft Graph and "
            "aren't distinguished here. Forwarding uses an inbox rule this app manages "
            "under a fixed name -- it's a different mechanism from Exchange's classic "
            "mailbox-forwarding setting, which isn't available through Graph."
        )
        note.setWordWrap(True)
        note.setAccessibleName("Exchange limitations note")
        layout.addWidget(note)

        load_row = QHBoxLayout()
        load_label = QLabel("&Mailbox (UPN or object ID)")
        self.user_edit = QLineEdit()
        self.user_edit.setAccessibleName("Mailbox to manage")
        self.user_edit.setPlaceholderText("jane.doe@contoso.com")
        self.user_edit.returnPressed.connect(self._on_load_clicked)
        load_label.setBuddy(self.user_edit)
        load_row.addWidget(load_label)
        load_row.addWidget(self.user_edit)

        self.load_button = AccessibleButton("&Load mailbox")
        self.load_button.clicked.connect(self._on_load_clicked)
        load_row.addWidget(self.load_button)
        layout.addLayout(load_row)

        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Mailbox settings")
        self.tabs.addTab(self._build_aliases_tab(), "Aliases")
        self.tabs.addTab(self._build_auto_replies_tab(), "Automatic replies")
        self.tabs.addTab(self._build_forwarding_tab(), "Forwarding")
        self.tabs.addTab(self._build_usage_tab(), "Usage")
        layout.addWidget(self.tabs, stretch=1)

        self._set_load_controls_enabled(False)
        self._set_tab_controls_enabled(False)

    # -- Tab construction -------------------------------------------------------

    def _build_aliases_tab(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)

        self.primary_address_label = QLabel("Load a mailbox to see its addresses.")
        self.primary_address_label.setAccessibleName("Primary address")
        self.primary_address_label.setWordWrap(True)
        panel_layout.addWidget(self.primary_address_label)

        self.aliases_list = QListWidget()
        self.aliases_list.setAccessibleName("Mailbox aliases")
        panel_layout.addWidget(self.aliases_list)

        add_row = QHBoxLayout()
        add_label = QLabel("&New alias")
        self.alias_edit = QLineEdit()
        self.alias_edit.setAccessibleName("New alias address")
        self.alias_edit.setPlaceholderText("alias@contoso.com")
        add_label.setBuddy(self.alias_edit)
        add_row.addWidget(add_label)
        add_row.addWidget(self.alias_edit)

        self.add_alias_button = AccessibleButton("&Add alias")
        self.add_alias_button.clicked.connect(self._on_add_alias_clicked)
        add_row.addWidget(self.add_alias_button)
        panel_layout.addLayout(add_row)

        self.remove_alias_button = AccessibleButton("&Remove selected alias")
        self.remove_alias_button.clicked.connect(self._on_remove_alias_clicked)
        panel_layout.addWidget(self.remove_alias_button)

        return panel

    def _build_auto_replies_tab(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)

        self.auto_reply_enabled_check = QCheckBox("&Enable automatic replies")
        self.auto_reply_enabled_check.setAccessibleName("Enable automatic replies")
        panel_layout.addWidget(self.auto_reply_enabled_check)

        audience_row = QHBoxLayout()
        audience_label = QLabel("&Send external replies to")
        self.audience_combo = QComboBox()
        self.audience_combo.setAccessibleName("External reply audience")
        self.audience_combo.addItems([label for label, _ in _AUDIENCE_ITEMS])
        audience_label.setBuddy(self.audience_combo)
        audience_row.addWidget(audience_label)
        audience_row.addWidget(self.audience_combo)
        panel_layout.addLayout(audience_row)

        internal_label = QLabel("&Internal reply message")
        panel_layout.addWidget(internal_label)
        self.internal_message_edit = QPlainTextEdit()
        self.internal_message_edit.setAccessibleName("Internal reply message")
        internal_label.setBuddy(self.internal_message_edit)
        panel_layout.addWidget(self.internal_message_edit)

        external_label = QLabel("Externa&l reply message")
        panel_layout.addWidget(external_label)
        self.external_message_edit = QPlainTextEdit()
        self.external_message_edit.setAccessibleName("External reply message")
        external_label.setBuddy(self.external_message_edit)
        panel_layout.addWidget(self.external_message_edit)

        self.save_auto_replies_button = AccessibleButton("&Save automatic replies")
        self.save_auto_replies_button.clicked.connect(self._on_save_auto_replies_clicked)
        panel_layout.addWidget(self.save_auto_replies_button)

        return panel

    def _build_forwarding_tab(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)

        self.forwarding_status_label = QLabel("Load a mailbox to see its forwarding rule.")
        self.forwarding_status_label.setAccessibleName("Forwarding status")
        self.forwarding_status_label.setWordWrap(True)
        panel_layout.addWidget(self.forwarding_status_label)

        target_row = QHBoxLayout()
        target_label = QLabel("Forward &to address")
        self.forward_target_edit = QLineEdit()
        self.forward_target_edit.setAccessibleName("Forwarding destination address")
        self.forward_target_edit.setAccessibleDescription(
            "Shown prominently since forwarding to an external domain sends mail outside your organization"
        )
        self.forward_target_edit.setPlaceholderText("external@example.com")
        target_label.setBuddy(self.forward_target_edit)
        target_row.addWidget(target_label)
        target_row.addWidget(self.forward_target_edit)
        panel_layout.addLayout(target_row)

        self.keep_copy_check = QCheckBox("&Keep a copy of forwarded mail in this mailbox")
        self.keep_copy_check.setAccessibleName("Keep a copy of forwarded mail")
        panel_layout.addWidget(self.keep_copy_check)

        button_row = QHBoxLayout()
        self.save_forwarding_button = AccessibleButton("&Save forwarding rule")
        self.save_forwarding_button.clicked.connect(self._on_save_forwarding_clicked)
        button_row.addWidget(self.save_forwarding_button)

        self.remove_forwarding_button = AccessibleButton("Remove for&warding rule")
        self.remove_forwarding_button.clicked.connect(self._on_remove_forwarding_clicked)
        button_row.addWidget(self.remove_forwarding_button)
        panel_layout.addLayout(button_row)

        return panel

    def _build_usage_tab(self) -> QWidget:
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)

        self.usage_status_label = QLabel(
            "Load a mailbox, then choose Check usage. This is a tenant-wide report, "
            "not real-time -- it can take 24-48 hours to reflect recent activity, and "
            "Microsoft may anonymize names/addresses depending on a tenant reporting "
            "setting this app doesn't control."
        )
        self.usage_status_label.setAccessibleName("Mailbox usage status")
        self.usage_status_label.setWordWrap(True)
        panel_layout.addWidget(self.usage_status_label)

        self.check_usage_button = AccessibleButton("Chec&k usage")
        self.check_usage_button.clicked.connect(self._on_check_usage_clicked)
        panel_layout.addWidget(self.check_usage_button)

        return panel

    # -- Shared state -------------------------------------------------------------

    def _set_load_controls_enabled(self, enabled: bool) -> None:
        for widget in (self.user_edit, self.load_button):
            widget.setEnabled(enabled)

    def _set_tab_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.aliases_list,
            self.alias_edit,
            self.add_alias_button,
            self.remove_alias_button,
            self.auto_reply_enabled_check,
            self.audience_combo,
            self.internal_message_edit,
            self.external_message_edit,
            self.save_auto_replies_button,
            self.forward_target_edit,
            self.keep_copy_check,
            self.save_forwarding_button,
            self.remove_forwarding_button,
            self.check_usage_button,
        ):
            widget.setEnabled(enabled)

    def set_graph_client(self, graph_client) -> None:
        if graph_client is None:
            self._service = None
            self._loaded_user_id = None
            self.status_label.setText(
                "Sign in to a tenant (Tenant > Sign in...) to manage mailboxes."
            )
            self._set_load_controls_enabled(False)
            self._set_tab_controls_enabled(False)
            return
        self._service = MailboxService(graph_client)
        self._set_load_controls_enabled(True)
        self.status_label.setText("Enter a mailbox to load its settings.")

    @asyncSlot()
    async def _on_load_clicked(self) -> None:
        if self._service is None:
            return
        user_id = self.user_edit.text().strip()
        if not user_id:
            self.status_label.setText("Enter a UPN or object ID first.")
            return
        self.status_label.setText("Loading mailbox...")
        try:
            aliases = await self._service.get_aliases(user_id)
            replies = await self._service.get_automatic_replies(user_id)
            forwarding = await self._service.get_forwarding_rule(user_id)
        except Exception as exc:
            self.status_label.setText(f"Couldn't load mailbox: {friendly_error_message(exc)}")
            return

        self._loaded_user_id = user_id
        self._loaded_display_name = aliases.primary_address or user_id

        self.primary_address_label.setText(f"Primary address: {aliases.primary_address or 'unknown'}")
        self.aliases_list.clear()
        for alias in aliases.aliases:
            self.aliases_list.addItem(alias)

        self.auto_reply_enabled_check.setChecked(replies.enabled)
        audience_labels = {value: label for label, value in _AUDIENCE_ITEMS}
        self.audience_combo.setCurrentText(audience_labels.get(replies.external_audience, "None"))
        self.internal_message_edit.setPlainText(replies.internal_message)
        self.external_message_edit.setPlainText(replies.external_message)

        if forwarding.exists:
            copy_note = "keeping a copy" if forwarding.keep_copy else "not keeping a copy"
            self.forwarding_status_label.setText(
                f"Currently forwarding to {forwarding.target_address} ({copy_note})."
            )
            self.forward_target_edit.setText(forwarding.target_address or "")
            self.keep_copy_check.setChecked(forwarding.keep_copy)
        else:
            self.forwarding_status_label.setText("No rule-based forwarding is set up.")
            self.forward_target_edit.clear()
            self.keep_copy_check.setChecked(False)

        self.usage_status_label.setText(
            "Choose Check usage to fetch this mailbox's storage/item-count from the "
            "tenant's usage report (not real-time; see note above)."
        )

        self.status_label.setText(f"Loaded {self._loaded_display_name}.")
        self._set_tab_controls_enabled(True)

    # -- Aliases --------------------------------------------------------------

    @asyncSlot()
    async def _on_add_alias_clicked(self) -> None:
        if self._service is None or self._loaded_user_id is None:
            return
        alias = self.alias_edit.text().strip()
        if not alias:
            self.status_label.setText("Enter an alias address first.")
            return
        try:
            await self._service.add_alias(
                self._loaded_user_id, alias, display_name=self._loaded_display_name
            )
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't add alias", friendly_error_message(exc))
            return
        self.alias_edit.clear()
        await self._on_load_clicked()

    @asyncSlot()
    async def _on_remove_alias_clicked(self) -> None:
        if self._service is None or self._loaded_user_id is None:
            return
        item = self.aliases_list.currentItem()
        if item is None:
            self.status_label.setText("Select an alias to remove first.")
            return
        alias = item.text()
        if not confirm_destructive(self, "Remove alias", f"Remove the alias {alias!r}?"):
            return
        try:
            await self._service.remove_alias(
                self._loaded_user_id, alias, display_name=self._loaded_display_name
            )
        except Exception as exc:
            QMessageBox.critical(self, "Couldn't remove alias", friendly_error_message(exc))
            return
        await self._on_load_clicked()

    # -- Automatic replies ----------------------------------------------------

    @asyncSlot()
    async def _on_save_auto_replies_clicked(self) -> None:
        if self._service is None or self._loaded_user_id is None:
            return
        audience_value = dict(_AUDIENCE_ITEMS)[self.audience_combo.currentText()]
        try:
            await self._service.set_automatic_replies(
                self._loaded_user_id,
                enabled=self.auto_reply_enabled_check.isChecked(),
                external_audience=audience_value,
                internal_message=self.internal_message_edit.toPlainText(),
                external_message=self.external_message_edit.toPlainText(),
                display_name=self._loaded_display_name,
            )
        except Exception as exc:
            QMessageBox.critical(
                self, "Couldn't save automatic replies", friendly_error_message(exc)
            )
            return
        self.status_label.setText("Automatic replies saved.")

    # -- Forwarding -------------------------------------------------------------

    @asyncSlot()
    async def _on_save_forwarding_clicked(self) -> None:
        if self._service is None or self._loaded_user_id is None:
            return
        target = self.forward_target_edit.text().strip()
        if not target:
            self.status_label.setText("Enter a forwarding destination address first.")
            return
        own_domain = (self._loaded_display_name or "").split("@")[-1].lower()
        target_domain = target.split("@")[-1].lower() if "@" in target else ""
        external_warning = (
            f"\n\nThis domain ({target_domain}) is OUTSIDE your organization "
            "({own_domain}) -- mail will leave your tenant."
            if target_domain and own_domain and target_domain != own_domain
            else ""
        )
        keep_copy = self.keep_copy_check.isChecked()
        if not confirm_destructive(
            self,
            "Save forwarding rule",
            f"Forward mail for {self._loaded_display_name} to {target}? "
            f"{'A copy will stay in this mailbox.' if keep_copy else 'No copy will stay in this mailbox.'}"
            f"{external_warning}",
        ):
            return
        try:
            await self._service.set_forwarding_rule(
                self._loaded_user_id, target, keep_copy=keep_copy,
                display_name=self._loaded_display_name,
            )
        except Exception as exc:
            QMessageBox.critical(
                self, "Couldn't save forwarding rule", friendly_error_message(exc)
            )
            return
        await self._on_load_clicked()

    @asyncSlot()
    async def _on_remove_forwarding_clicked(self) -> None:
        if self._service is None or self._loaded_user_id is None:
            return
        if not confirm_destructive(
            self, "Remove forwarding rule",
            f"Stop forwarding mail for {self._loaded_display_name}?",
        ):
            return
        try:
            await self._service.remove_forwarding_rule(
                self._loaded_user_id, display_name=self._loaded_display_name
            )
        except Exception as exc:
            QMessageBox.critical(
                self, "Couldn't remove forwarding rule", friendly_error_message(exc)
            )
            return
        await self._on_load_clicked()

    # -- Usage ------------------------------------------------------------------

    @asyncSlot()
    async def _on_check_usage_clicked(self) -> None:
        if self._service is None or self._loaded_user_id is None:
            return
        self.usage_status_label.setText("Checking mailbox usage...")
        try:
            usage = await self._service.get_mailbox_usage(self._loaded_user_id)
        except Exception as exc:
            self.usage_status_label.setText(
                f"Couldn't check mailbox usage: {friendly_error_message(exc)}"
            )
            return
        if usage is None:
            self.usage_status_label.setText(
                "This mailbox wasn't found in the usage report (it may be new, or the "
                "report may not have refreshed yet)."
            )
            return
        storage_mb = f"{usage.storage_used_bytes / 1_048_576:.1f} MB" if usage.storage_used_bytes else "unknown"
        quota_gb = (
            f"{usage.prohibit_send_receive_quota_bytes / 1_073_741_824:.1f} GB"
            if usage.prohibit_send_receive_quota_bytes
            else "unknown"
        )
        self.usage_status_label.setText(
            f"Storage used: {storage_mb}. Items: {usage.item_count or 'unknown'}. "
            f"Send/receive quota: {quota_gb}. {usage.note}"
        )
