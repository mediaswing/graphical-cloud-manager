"""Entra sign-in log reads.

Requires Azure AD Premium P1 or higher on the tenant -- callers should only
construct this once TenantCapabilities.has_audit_logs is true (see
graph/capabilities.py); the UI hides the whole page otherwise rather than
showing an empty/erroring table.
"""

from __future__ import annotations

from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph import GraphServiceClient
from msgraph.generated.audit_logs.sign_ins.sign_ins_request_builder import SignInsRequestBuilder
from msgraph.generated.models.sign_in import SignIn

from gcm.models.sign_in import SignInSummary


class SignInLogService:
    def __init__(self, graph_client: GraphServiceClient) -> None:
        self._graph = graph_client

    async def list_recent_sign_ins(
        self, search: str | None = None, top: int = 100
    ) -> list[SignInSummary]:
        query_params = SignInsRequestBuilder.SignInsRequestBuilderGetQueryParameters(
            top=top, orderby=["createdDateTime desc"],
        )
        if search:
            # Sign-in logs don't support $search; filter on userPrincipalName
            # or userDisplayName instead, which covers the common "look up
            # this person's recent sign-ins" case.
            escaped = search.replace("'", "''")
            query_params.filter = (
                f"startswith(userPrincipalName,'{escaped}') or "
                f"startswith(userDisplayName,'{escaped}')"
            )
        request_config = RequestConfiguration(query_parameters=query_params)
        result = await self._graph.audit_logs.sign_ins.get(request_configuration=request_config)
        return [_to_summary(entry) for entry in (result.value or [])]


def _to_summary(sign_in: SignIn) -> SignInSummary:
    status = sign_in.status
    error_code = getattr(status, "error_code", None)
    succeeded = error_code == 0
    detail = sign_in.device_detail
    return SignInSummary(
        id=sign_in.id,
        created_at=sign_in.created_date_time,
        user_display_name=sign_in.user_display_name or "(unknown)",
        user_principal_name=sign_in.user_principal_name or "",
        app_display_name=sign_in.app_display_name or "(unknown)",
        ip_address=sign_in.ip_address,
        device_display_name=getattr(detail, "display_name", None) or None,
        device_operating_system=getattr(detail, "operating_system", None) or None,
        succeeded=succeeded,
        failure_reason=None if succeeded else getattr(status, "failure_reason", None),
    )
