"""Google Workspace mailbox admin operations (vacation responder, auto
forwarding, delegates), via the Gmail API acting as each target user under
domain-wide delegation. Plain Python, no Qt imports -- same shape as
services/mailbox_service.py.

Unlike GoogleUserService/GoogleGroupService/GoogleDeviceService, which share
one long-lived Directory API client across the whole signed-in session, this
service builds a fresh delegated Gmail client per call: each call targets a
different mailbox owner, so there's no single "the client" to share.

Forwarding is two steps in Gmail, unlike Exchange's single inbox rule: a
forwarding address must first be added (create_forwarding_address, which
emails a verification link to the target address) and accepted by its
owner, before enable_auto_forwarding can point the mailbox at it -- Google
rejects updateAutoForwarding to an unverified address. Both steps are
exposed here rather than papered over, same as mailbox_service.py's
"documented gap, not a workaround" approach to Graph's own limitations.
"""

from __future__ import annotations

import asyncio

from googleapiclient.discovery import build

from gcm.google.service_account import build_delegated_credentials
from gcm.models.google_mailbox import (
    AutoForwardingSummary,
    ForwardingAddressSummary,
    MailboxDelegate,
    VacationResponderSummary,
)
from gcm.services import audit_log
from gcm.services.google_errors import friendly_google_error


class GoogleMailboxService:
    def __init__(self, service_account_json_path: str) -> None:
        self._service_account_json_path = service_account_json_path

    def _client_for(self, user_email: str):
        creds = build_delegated_credentials(self._service_account_json_path, user_email)
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    async def _execute(self, request):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, request.execute)

    # -- Vacation responder -----------------------------------------------------

    async def get_vacation_responder(self, user_email: str) -> VacationResponderSummary:
        client = self._client_for(user_email)
        settings = await self._execute(client.users().settings().getVacation(userId="me"))
        return VacationResponderSummary(
            enabled=bool(settings.get("enableAutoReply")),
            subject=settings.get("responseSubject") or "",
            message=settings.get("responseBodyPlainText") or "",
            restrict_to_contacts=bool(settings.get("restrictToContacts")),
        )

    async def set_vacation_responder(
        self,
        user_email: str,
        *,
        enabled: bool,
        subject: str,
        message: str,
        restrict_to_contacts: bool = False,
    ) -> None:
        body = {
            "enableAutoReply": enabled,
            "responseSubject": subject,
            "responseBodyPlainText": message,
            "restrictToContacts": restrict_to_contacts,
        }
        client = self._client_for(user_email)
        try:
            await self._execute(client.users().settings().updateVacation(userId="me", body=body))
        except Exception as exc:
            audit_log.record(
                "set_vacation_responder", "GoogleMailbox", user_email, user_email,
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            "set_vacation_responder", "GoogleMailbox", user_email, user_email,
            result="success", after={"enabled": enabled},
        )

    # -- Forwarding ---------------------------------------------------------

    async def list_forwarding_addresses(self, user_email: str) -> list[ForwardingAddressSummary]:
        client = self._client_for(user_email)
        response = await self._execute(
            client.users().settings().forwardingAddresses().list(userId="me")
        )
        return [
            ForwardingAddressSummary(
                forwarding_email=f.get("forwardingEmail", ""),
                verification_status=f.get("verificationStatus", "pending"),
            )
            for f in response.get("forwardingAddresses", [])
        ]

    async def request_forwarding_verification(self, user_email: str, forwarding_email: str) -> None:
        """Adds a forwarding address candidate, which sends a verification
        email to `forwarding_email` -- its owner must accept it before
        enable_auto_forwarding can target it."""
        client = self._client_for(user_email)
        try:
            await self._execute(
                client.users().settings().forwardingAddresses().create(
                    userId="me", body={"forwardingEmail": forwarding_email}
                )
            )
        except Exception as exc:
            audit_log.record(
                "request_forwarding_verification", "GoogleMailbox", user_email,
                f"{user_email} -> {forwarding_email}",
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            "request_forwarding_verification", "GoogleMailbox", user_email,
            f"{user_email} -> {forwarding_email}", result="success",
        )

    async def get_auto_forwarding(self, user_email: str) -> AutoForwardingSummary:
        client = self._client_for(user_email)
        settings = await self._execute(client.users().settings().getAutoForwarding(userId="me"))
        return AutoForwardingSummary(
            enabled=bool(settings.get("enabled")),
            forwarding_email=settings.get("emailAddress", ""),
            disposition=settings.get("disposition", "leaveInInbox"),
        )

    async def set_auto_forwarding(
        self,
        user_email: str,
        forwarding_email: str,
        *,
        enabled: bool,
        disposition: str = "leaveInInbox",
    ) -> None:
        body = {"enabled": enabled, "emailAddress": forwarding_email, "disposition": disposition}
        client = self._client_for(user_email)
        try:
            await self._execute(
                client.users().settings().updateAutoForwarding(userId="me", body=body)
            )
        except Exception as exc:
            audit_log.record(
                "set_auto_forwarding", "GoogleMailbox", user_email, user_email,
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            "set_auto_forwarding", "GoogleMailbox", user_email, user_email,
            result="success", after={"forwarding_email": forwarding_email, "enabled": enabled},
        )

    # -- Delegates ------------------------------------------------------------

    async def list_delegates(self, user_email: str) -> list[MailboxDelegate]:
        client = self._client_for(user_email)
        response = await self._execute(client.users().settings().delegates().list(userId="me"))
        return [
            MailboxDelegate(
                delegate_email=d.get("delegateEmail", ""),
                verification_status=d.get("verificationStatus", "pending"),
            )
            for d in response.get("delegates", [])
        ]

    async def add_delegate(self, user_email: str, delegate_email: str) -> None:
        client = self._client_for(user_email)
        try:
            await self._execute(
                client.users().settings().delegates().create(
                    userId="me", body={"delegateEmail": delegate_email}
                )
            )
        except Exception as exc:
            audit_log.record(
                "add_delegate", "GoogleMailbox", user_email, f"{user_email} + {delegate_email}",
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            "add_delegate", "GoogleMailbox", user_email, f"{user_email} + {delegate_email}",
            result="success",
        )

    async def remove_delegate(self, user_email: str, delegate_email: str) -> None:
        client = self._client_for(user_email)
        try:
            await self._execute(
                client.users().settings().delegates().delete(
                    userId="me", delegateEmail=delegate_email
                )
            )
        except Exception as exc:
            audit_log.record(
                "remove_delegate", "GoogleMailbox", user_email, f"{user_email} - {delegate_email}",
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            "remove_delegate", "GoogleMailbox", user_email, f"{user_email} - {delegate_email}",
            result="success",
        )
