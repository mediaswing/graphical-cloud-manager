"""Tests for the Exchange page: disconnected state and the load flow
populating all four tabs from fake service data (no network)."""

from __future__ import annotations

import pytest

from gcm.models.mailbox import AliasesSummary, AutomaticRepliesSummary, ForwardingRuleSummary
from gcm.ui.pages.exchange_page import ExchangePage


def test_exchange_page_starts_disconnected_and_disabled(qtbot):
    page = ExchangePage()
    qtbot.addWidget(page)

    assert not page.load_button.isEnabled()
    assert not page.add_alias_button.isEnabled()
    assert "Sign in" in page.status_label.text()


class _FakeMailboxService:
    async def get_aliases(self, user_id):
        return AliasesSummary(user_id=user_id, primary_address="jane@contoso.com", aliases=["alias@contoso.com"])

    async def get_automatic_replies(self, user_id):
        return AutomaticRepliesSummary(
            enabled=True, external_audience="all", internal_message="in", external_message="out"
        )

    async def get_forwarding_rule(self, user_id):
        return ForwardingRuleSummary(exists=True, target_address="ext@example.com", keep_copy=False)


@pytest.mark.asyncio
async def test_load_populates_all_tabs(qtbot):
    page = ExchangePage()
    qtbot.addWidget(page)
    page._service = _FakeMailboxService()
    page._set_tab_controls_enabled(True)
    page.user_edit.setText("jane@contoso.com")

    await page._on_load_clicked()

    assert "jane@contoso.com" in page.primary_address_label.text()
    assert page.aliases_list.count() == 1
    assert page.auto_reply_enabled_check.isChecked() is True
    assert page.internal_message_edit.toPlainText() == "in"
    assert "ext@example.com" in page.forwarding_status_label.text()
    assert page.forward_target_edit.text() == "ext@example.com"
    assert page.keep_copy_check.isChecked() is False


@pytest.mark.asyncio
async def test_load_shows_no_forwarding_rule_message(qtbot):
    class _NoForwardingService(_FakeMailboxService):
        async def get_forwarding_rule(self, user_id):
            return ForwardingRuleSummary(exists=False)

    page = ExchangePage()
    qtbot.addWidget(page)
    page._service = _NoForwardingService()
    page._set_tab_controls_enabled(True)
    page.user_edit.setText("jane@contoso.com")

    await page._on_load_clicked()

    assert "No rule-based forwarding" in page.forwarding_status_label.text()
