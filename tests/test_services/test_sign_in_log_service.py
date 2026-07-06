"""Unit tests for SignInLogService's Graph-model-to-dataclass conversion.
Doesn't touch the network -- constructs real msgraph models directly."""

from __future__ import annotations

import datetime

from msgraph.generated.models.device_detail import DeviceDetail
from msgraph.generated.models.sign_in import SignIn
from msgraph.generated.models.sign_in_status import SignInStatus

from gcm.services.sign_in_log_service import _to_summary


def test_to_summary_maps_successful_sign_in_with_device():
    sign_in = SignIn(
        id="s1",
        created_date_time=datetime.datetime(2026, 7, 6, 10, 0),
        user_display_name="Jane Doe",
        user_principal_name="jane@contoso.com",
        app_display_name="Office 365",
        ip_address="1.2.3.4",
        status=SignInStatus(error_code=0),
        device_detail=DeviceDetail(display_name="Janes-MacBook", operating_system="MacOS"),
    )
    summary = _to_summary(sign_in)
    assert summary.succeeded is True
    assert summary.failure_reason is None
    assert summary.device_display_name == "Janes-MacBook"
    assert summary.device_operating_system == "MacOS"


def test_to_summary_maps_failed_sign_in_without_device():
    sign_in = SignIn(
        id="s2", status=SignInStatus(error_code=50126, failure_reason="Invalid password")
    )
    summary = _to_summary(sign_in)
    assert summary.succeeded is False
    assert summary.failure_reason == "Invalid password"
    assert summary.device_display_name is None
    assert summary.user_display_name == "(unknown)"
