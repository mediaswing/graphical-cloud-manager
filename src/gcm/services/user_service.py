"""Entra user directory operations. Plain Python, no Qt imports, so it can be
unit-tested (with a fake Graph client) without a display."""

from __future__ import annotations

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph import GraphServiceClient
from msgraph.generated.models.password_profile import PasswordProfile
from msgraph.generated.models.user import User
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.generated.users.users_request_builder import UsersRequestBuilder

from gcm.graph.pagination import collect_all
from gcm.models.user import UserDetail, UserSummary
from gcm.services import audit_log
from gcm.services.graph_errors import friendly_error_message

_SELECT = ["id", "displayName", "userPrincipalName", "mail", "accountEnabled"]
_DETAIL_SELECT = [
    "id",
    "displayName",
    "jobTitle",
    "department",
    "officeLocation",
    "mobilePhone",
    "usageLocation",
]


class UserService:
    def __init__(self, graph_client: GraphServiceClient) -> None:
        self._graph = graph_client

    async def list_users(self, search: str | None = None) -> list[UserSummary]:
        query_params = UsersRequestBuilder.UsersRequestBuilderGetQueryParameters(
            select=_SELECT, top=999,
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        if search:
            # $search requires ConsistencyLevel: eventual, and (per Graph's
            # advanced-query rules) can't be combined with $orderby, which we
            # don't use here anyway.
            query_params.search = f'"displayName:{search}" OR "userPrincipalName:{search}"'
            query_params.count = True
            request_config.headers.add("ConsistencyLevel", "eventual")
        first_page = await self._graph.users.get(request_configuration=request_config)
        users = await collect_all(first_page, self._graph.request_adapter)
        return [_to_summary(u) for u in users]

    async def set_account_enabled(
        self, user_id: str, enabled: bool, *, display_name: str | None = None
    ) -> None:
        try:
            await self._graph.users.by_user_id(user_id).patch(User(account_enabled=enabled))
        except Exception as exc:
            audit_log.record(
                "set_account_enabled", "User", user_id, display_name or user_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "set_account_enabled", "User", user_id, display_name or user_id,
            result="success", after={"account_enabled": enabled},
        )

    async def create_user(
        self,
        *,
        display_name: str,
        user_principal_name: str,
        mail_nickname: str,
        password: str,
        account_enabled: bool = True,
    ) -> UserSummary:
        body = User(
            account_enabled=account_enabled,
            display_name=display_name,
            mail_nickname=mail_nickname,
            user_principal_name=user_principal_name,
            password_profile=PasswordProfile(
                force_change_password_next_sign_in=True,
                password=password,
            ),
        )
        try:
            created = await self._graph.users.post(body)
        except Exception as exc:
            audit_log.record(
                "create_user", "User", user_principal_name, display_name,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "create_user", "User", created.id, display_name,
            result="success",
            after={"user_principal_name": user_principal_name, "account_enabled": account_enabled},
        )
        return _to_summary(created)

    async def delete_user(self, user_id: str, *, display_name: str | None = None) -> None:
        try:
            await self._graph.users.by_user_id(user_id).delete()
        except Exception as exc:
            audit_log.record(
                "delete_user", "User", user_id, display_name or user_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "delete_user", "User", user_id, display_name or user_id, result="success"
        )

    async def get_user_detail(self, user_id: str) -> UserDetail:
        query_params = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters(
            select=_DETAIL_SELECT,
        )
        request_config = RequestConfiguration(query_parameters=query_params)
        user = await self._graph.users.by_user_id(user_id).get(
            request_configuration=request_config
        )
        return UserDetail(
            id=user.id,
            display_name=user.display_name or "(no display name)",
            job_title=user.job_title,
            department=user.department,
            office_location=user.office_location,
            mobile_phone=user.mobile_phone,
            usage_location=user.usage_location,
        )

    async def update_user(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        job_title: str | None = None,
        department: str | None = None,
        office_location: str | None = None,
        mobile_phone: str | None = None,
        usage_location: str | None = None,
    ) -> None:
        body = User(
            display_name=display_name,
            job_title=job_title,
            department=department,
            office_location=office_location,
            mobile_phone=mobile_phone,
            usage_location=usage_location,
        )
        target_name = display_name or user_id
        try:
            await self._graph.users.by_user_id(user_id).patch(body)
        except Exception as exc:
            audit_log.record(
                "update_user", "User", user_id, target_name,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        audit_log.record(
            "update_user", "User", user_id, target_name, result="success",
            after={
                "job_title": job_title,
                "department": department,
                "office_location": office_location,
                "mobile_phone": mobile_phone,
                "usage_location": usage_location,
            },
        )

    async def reset_password(
        self,
        user_id: str,
        new_password: str,
        force_change_at_next_sign_in: bool = True,
        *,
        display_name: str | None = None,
    ) -> None:
        # Admin password reset: PATCH passwordProfile (needs no knowledge of
        # the user's current password). This is different from the
        # self-service /changePassword action, which requires it.
        body = User(
            password_profile=PasswordProfile(
                password=new_password,
                force_change_password_next_sign_in=force_change_at_next_sign_in,
            )
        )
        try:
            await self._graph.users.by_user_id(user_id).patch(body)
        except Exception as exc:
            audit_log.record(
                "reset_password", "User", user_id, display_name or user_id,
                result="failure", error=friendly_error_message(exc),
            )
            raise
        # Never log the password itself -- only that a reset happened.
        audit_log.record(
            "reset_password", "User", user_id, display_name or user_id,
            result="success", after={"force_change_at_next_sign_in": force_change_at_next_sign_in},
        )


def _to_summary(user: User) -> UserSummary:
    return UserSummary(
        id=user.id,
        display_name=user.display_name or "(no display name)",
        user_principal_name=user.user_principal_name or "",
        mail=user.mail,
        account_enabled=bool(user.account_enabled),
    )
