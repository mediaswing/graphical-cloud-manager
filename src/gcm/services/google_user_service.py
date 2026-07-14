"""Google Workspace user directory operations, via the Admin SDK Directory
API. Plain Python, no Qt imports, so it can be unit-tested (with a fake
Directory resource) without a display -- same shape as services/user_service.py.
"""

from __future__ import annotations

import asyncio

from googleapiclient.discovery import Resource

from gcm.models.google_user import GoogleUserDetail, GoogleUserSummary
from gcm.services import audit_log
from gcm.services.google_errors import friendly_google_error

_PAGE_SIZE = 500


def _build_query(search: str) -> str:
    # Directory API's query syntax has no escape for embedded quotes; just
    # drop them rather than risk a malformed query, since none of these
    # fields legitimately contain one.
    term = search.replace('"', "").strip()
    return f'email:{term}* OR givenName:{term}* OR familyName:{term}*'


class GoogleUserService:
    def __init__(self, directory_client: Resource) -> None:
        self._directory = directory_client

    async def _execute(self, request):
        # googleapiclient requests are synchronous/blocking -- see
        # google/client.py's module docstring for why this has to run off
        # the qasync event loop for every single call.
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, request.execute)

    async def list_users(self, search: str | None = None) -> list[GoogleUserSummary]:
        query = _build_query(search) if search else None
        users: list[dict] = []
        page_token = None
        while True:
            request = self._directory.users().list(
                customer="my_customer",
                maxResults=_PAGE_SIZE,
                query=query,
                orderBy="email",
                pageToken=page_token,
            )
            response = await self._execute(request)
            users.extend(response.get("users", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return [_to_summary(u) for u in users]

    async def create_user(
        self,
        *,
        given_name: str,
        family_name: str,
        primary_email: str,
        password: str,
        org_unit_path: str = "/",
    ) -> GoogleUserSummary:
        body = {
            "name": {"givenName": given_name, "familyName": family_name},
            "primaryEmail": primary_email,
            "password": password,
            "changePasswordAtNextLogin": True,
            "orgUnitPath": org_unit_path,
        }
        display_name = f"{given_name} {family_name}".strip() or primary_email
        try:
            created = await self._execute(self._directory.users().insert(body=body))
        except Exception as exc:
            audit_log.record(
                "create_user", "GoogleUser", primary_email, display_name,
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            "create_user", "GoogleUser", created["id"], display_name,
            result="success",
            after={"primary_email": primary_email, "org_unit_path": org_unit_path},
        )
        return _to_summary(created)

    async def set_suspended(
        self, user_id: str, suspended: bool, *, display_name: str | None = None
    ) -> None:
        request = self._directory.users().update(userKey=user_id, body={"suspended": suspended})
        try:
            await self._execute(request)
        except Exception as exc:
            audit_log.record(
                "set_suspended", "GoogleUser", user_id, display_name or user_id,
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            "set_suspended", "GoogleUser", user_id, display_name or user_id,
            result="success", after={"suspended": suspended},
        )

    async def delete_user(self, user_id: str, *, display_name: str | None = None) -> None:
        request = self._directory.users().delete(userKey=user_id)
        try:
            await self._execute(request)
        except Exception as exc:
            audit_log.record(
                "delete_user", "GoogleUser", user_id, display_name or user_id,
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            "delete_user", "GoogleUser", user_id, display_name or user_id, result="success"
        )

    async def get_user_detail(self, user_id: str) -> GoogleUserDetail:
        request = self._directory.users().get(userKey=user_id, projection="full")
        user = await self._execute(request)
        name = user.get("name", {})
        return GoogleUserDetail(
            id=user["id"],
            given_name=name.get("givenName", ""),
            family_name=name.get("familyName", ""),
            primary_email=user.get("primaryEmail", ""),
            org_unit_path=user.get("orgUnitPath", "/"),
            recovery_email=user.get("recoveryEmail"),
            recovery_phone=user.get("recoveryPhone"),
        )

    async def update_user(
        self,
        user_id: str,
        *,
        given_name: str,
        family_name: str,
        org_unit_path: str,
        recovery_email: str | None = None,
        recovery_phone: str | None = None,
    ) -> None:
        body: dict = {
            "name": {"givenName": given_name, "familyName": family_name},
            "orgUnitPath": org_unit_path,
        }
        if recovery_email is not None:
            body["recoveryEmail"] = recovery_email
        if recovery_phone is not None:
            body["recoveryPhone"] = recovery_phone
        target_name = f"{given_name} {family_name}".strip() or user_id
        request = self._directory.users().update(userKey=user_id, body=body)
        try:
            await self._execute(request)
        except Exception as exc:
            audit_log.record(
                "update_user", "GoogleUser", user_id, target_name,
                result="failure", error=friendly_google_error(exc),
            )
            raise
        audit_log.record(
            "update_user", "GoogleUser", user_id, target_name, result="success", after=body
        )

    async def reset_password(
        self,
        user_id: str,
        new_password: str,
        change_at_next_login: bool = True,
        *,
        display_name: str | None = None,
    ) -> None:
        body = {"password": new_password, "changePasswordAtNextLogin": change_at_next_login}
        request = self._directory.users().update(userKey=user_id, body=body)
        try:
            await self._execute(request)
        except Exception as exc:
            audit_log.record(
                "reset_password", "GoogleUser", user_id, display_name or user_id,
                result="failure", error=friendly_google_error(exc),
            )
            raise
        # Never log the password itself -- only that a reset happened.
        audit_log.record(
            "reset_password", "GoogleUser", user_id, display_name or user_id,
            result="success", after={"change_at_next_login": change_at_next_login},
        )


def _to_summary(user: dict) -> GoogleUserSummary:
    name = user.get("name", {})
    full_name = name.get("fullName") or f'{name.get("givenName", "")} {name.get("familyName", "")}'.strip()
    return GoogleUserSummary(
        id=user["id"],
        primary_email=user.get("primaryEmail", ""),
        full_name=full_name or "(no display name)",
        suspended=bool(user.get("suspended", False)),
    )
