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
    verified_domains = {"contoso.com", "contoso.onmicrosoft.com"}

    async def get_aliases(self, user_id):
        return AliasesSummary(user_id=user_id, primary_address="jane@contoso.com", aliases=["alias@contoso.com"])

    async def get_automatic_replies(self, user_id):
        return AutomaticRepliesSummary(
            enabled=True, external_audience="all", internal_message="in", external_message="out"
        )

    async def get_forwarding_rule(self, user_id):
        return ForwardingRuleSummary(exists=True, target_address="ext@example.com", keep_copy=False)

    async def set_forwarding_rule(self, user_id, target, *, keep_copy, display_name=None):
        pass

    async def list_verified_domain_names(self):
        return self.verified_domains


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


async def _prepare_forwarding_save(qtbot, monkeypatch, target, service=None):
    from gcm.ui.pages import exchange_page as exchange_page_module

    page = ExchangePage()
    qtbot.addWidget(page)
    page._service = service or _FakeMailboxService()
    page._set_tab_controls_enabled(True)
    page.user_edit.setText("jane@contoso.com")
    await page._on_load_clicked()
    page.forward_target_edit.setText(target)

    confirm_messages = []
    monkeypatch.setattr(
        exchange_page_module, "confirm_destructive",
        lambda parent, title, message: confirm_messages.append(message) or False)

    await page._on_save_forwarding_clicked()
    return confirm_messages[0] if confirm_messages else ""


@pytest.mark.asyncio
async def test_forwarding_to_a_second_verified_domain_does_not_warn(qtbot, monkeypatch):
    # contoso.onmicrosoft.com is a different domain than the loaded mailbox's
    # own (contoso.com) but is equally internal -- must not read as external.
    message = await _prepare_forwarding_save(qtbot, monkeypatch, "ops@contoso.onmicrosoft.com")
    assert "OUTSIDE your organization" not in message


@pytest.mark.asyncio
async def test_forwarding_to_an_unverified_domain_warns(qtbot, monkeypatch):
    message = await _prepare_forwarding_save(qtbot, monkeypatch, "ext@example.com")
    assert "OUTSIDE your organization" in message
    assert "example.com" in message


@pytest.mark.asyncio
async def test_forwarding_falls_back_to_own_domain_when_verified_domains_unavailable(qtbot, monkeypatch):
    class _NoDomainsService(_FakeMailboxService):
        async def list_verified_domain_names(self):
            raise RuntimeError("no permission")

    # Own domain (contoso.com) vs a different one: the fallback heuristic
    # should still flag it, same as the pre-fix behavior.
    message = await _prepare_forwarding_save(
        qtbot, monkeypatch, "ext@example.com", service=_NoDomainsService())
    assert "OUTSIDE your organization" in message
