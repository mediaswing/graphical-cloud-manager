"""Centralized, bounded-cost impact preview for destructive/high-impact
actions.

Deliberately makes only a small, fixed number of targeted Graph calls --
never a tenant-wide scan -- so building a confirmation preview never
becomes its own source of excessive API traffic:

1. One call for the user's own identity/license fields.
2. One call for `subscribedSkus` (shared/cheap, needed to turn SKU ids into
   readable part numbers).
3. One capped call to `memberOf` (top=20) -- this single call yields BOTH
   group memberships and directory-role membership, since a directoryRole
   shows up in the same collection with a distinct type; no extra request
   needed to separately check "is this user an admin".
4. Only if `has_audit_logs` (Azure AD Premium) is true: one call for the
   user's most recent sign-in.

The preview is explicitly NOT exhaustive, and says so: app role assignments
(enterprise app access), administrative unit scoping, and resource-level
(Azure) RBAC aren't checked, and that's stated in the result rather than
implied away.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph import GraphServiceClient
from msgraph.generated.models.directory_role import DirectoryRole
from msgraph.generated.users.item.member_of.member_of_request_builder import (
    MemberOfRequestBuilder,
)
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder

from gcm.services.graph_errors import friendly_error_message
from gcm.services.sign_in_log_service import SignInLogService

NOT_CHECKED_NOTE = (
    "This preview isn't exhaustive: app role assignments (enterprise app "
    "access), administrative unit scoping, and resource-level (Azure) RBAC "
    "aren't checked."
)

_MEMBER_OF_LIMIT = 20


@dataclass
class ImpactPreview:
    target_id: str
    display_name: str
    user_principal_name: str
    account_enabled: bool | None
    license_names: list[str] = field(default_factory=list)
    group_names: list[str] = field(default_factory=list)
    admin_role_names: list[str] = field(default_factory=list)
    member_of_truncated: bool = False
    last_sign_in: str | None = None
    last_sign_in_checked: bool = False
    warnings: list[str] = field(default_factory=list)
    not_checked_note: str = NOT_CHECKED_NOTE


async def build_user_impact_preview(
    graph_client: GraphServiceClient, user_id: str, *, has_audit_logs: bool
) -> ImpactPreview:
    warnings: list[str] = []

    query_params = UserItemRequestBuilder.UserItemRequestBuilderGetQueryParameters(
        select=["id", "displayName", "userPrincipalName", "accountEnabled", "assignedLicenses"],
    )
    request_config = RequestConfiguration(query_parameters=query_params)
    user = await graph_client.users.by_user_id(user_id).get(request_configuration=request_config)

    license_names: list[str] = []
    try:
        skus_result = await graph_client.subscribed_skus.get()
        sku_name_by_id = {
            str(sku.sku_id): (sku.sku_part_number or str(sku.sku_id))
            for sku in (skus_result.value or [])
        }
        license_names = [
            sku_name_by_id.get(str(lic.sku_id), str(lic.sku_id))
            for lic in (user.assigned_licenses or [])
        ]
    except Exception as exc:
        warnings.append(f"Couldn't check licenses: {friendly_error_message(exc)}")

    group_names: list[str] = []
    admin_role_names: list[str] = []
    member_of_truncated = False
    try:
        member_of_params = MemberOfRequestBuilder.MemberOfRequestBuilderGetQueryParameters(
            top=_MEMBER_OF_LIMIT,
        )
        member_of_config = RequestConfiguration(query_parameters=member_of_params)
        member_of = await graph_client.users.by_user_id(user_id).member_of.get(
            request_configuration=member_of_config
        )
        entries = member_of.value or []
        member_of_truncated = bool(getattr(member_of, "odata_next_link", None))
        for entry in entries:
            name = getattr(entry, "display_name", None) or "(unnamed)"
            if isinstance(entry, DirectoryRole):
                admin_role_names.append(name)
            else:
                group_names.append(name)
    except Exception as exc:
        warnings.append(f"Couldn't check group/role memberships: {friendly_error_message(exc)}")

    last_sign_in = None
    if has_audit_logs:
        try:
            sign_ins = await SignInLogService(graph_client).list_recent_sign_ins(
                search=user.user_principal_name, top=1
            )
            if sign_ins:
                entry = sign_ins[0]
                last_sign_in = (
                    entry.created_at.strftime("%Y-%m-%d %H:%M") if entry.created_at else "Unknown"
                )
        except Exception as exc:
            warnings.append(f"Couldn't check last sign-in: {friendly_error_message(exc)}")

    return ImpactPreview(
        target_id=user.id,
        display_name=user.display_name or "(no display name)",
        user_principal_name=user.user_principal_name or "",
        account_enabled=user.account_enabled,
        license_names=license_names,
        group_names=group_names,
        admin_role_names=admin_role_names,
        member_of_truncated=member_of_truncated,
        last_sign_in=last_sign_in,
        last_sign_in_checked=has_audit_logs,
        warnings=warnings,
    )
