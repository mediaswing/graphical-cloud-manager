"""Unit tests for friendly_error_message's throttling handling. Every write
path in the services funnels its exceptions through this, so an admin
running a bulk import or similar should see "you're being throttled,
retry" rather than a raw 429 body."""

from __future__ import annotations

from kiota_abstractions.api_error import APIError

from gcm.services.graph_errors import friendly_error_message


def test_429_status_code_without_retry_after():
    exc = APIError(response_status_code=429)
    assert "throttling" in friendly_error_message(exc)


def test_429_includes_retry_after_seconds_when_present():
    exc = APIError(response_status_code=429, response_headers={"Retry-After": "30"})
    message = friendly_error_message(exc)
    assert "throttling" in message
    assert "30 seconds" in message


def test_retry_after_header_lookup_is_case_insensitive():
    exc = APIError(response_status_code=429, response_headers={"retry-after": "5"})
    assert "5 seconds" in friendly_error_message(exc)


def test_permission_denied_still_takes_priority_over_generic_message():
    exc = APIError(response_status_code=403, message="raw graph text")
    message = friendly_error_message(exc)
    assert "don't have permission" in message
